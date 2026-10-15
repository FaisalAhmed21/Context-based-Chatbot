

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.api.auth import AuthUser, get_current_user
from app.db.models import ChatSession, Document, Message
from app.db.session import SessionLocal, get_db
from app.generation.orchestrator import answer_question
from app.types import ChatMessageOut, Citation

router = APIRouter(prefix="/chat", tags=["Chat"])

class CreateSessionBody(BaseModel):
    document_ids: list[uuid.UUID] = Field(default_factory=list)
    title: str | None = None

class SendMessageBody(BaseModel):
    content: str
    document_ids: list[uuid.UUID] | None = None
    stream: bool = True

@router.post("/sessions")
async def create_session(
    body: CreateSessionBody,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
) -> dict[str, Any]:
    session = ChatSession(
        title=body.title,
        user_id=user.id,
        document_ids=[str(d) for d in body.document_ids],
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return {"id": str(session.id), "document_ids": session.document_ids, "title": session.title}

@router.get("/sessions")
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    if not user.id:
        return []
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == user.id)
        .order_by(ChatSession.created_at.desc())
    )
    sessions = result.scalars().all()
    return [
        {
            "id": str(s.id),
            "title": s.title or "Untitled Chat",
            "document_ids": s.document_ids or [],
            "created_at": s.created_at.isoformat(),
        }
        for s in sessions
    ]

@router.post("/{session_id}/message")
async def send_message(
    session_id: uuid.UUID,
    body: SendMessageBody,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if user.id is not None and session.user_id is not None and session.user_id != user.id:
        raise HTTPException(status_code=404, detail="Session not found")

    user_msg = Message(session_id=session.id, role="user", content=body.content)
    db.add(user_msg)
    await db.commit()

    hist_rows = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.desc())
        .limit(8)
    )
    history = [
        {"role": m.role, "content": m.content}
        for m in reversed(list(hist_rows.scalars().all()))
        if m.role in ("user", "assistant")
    ]
    # Current user turn was just committed — exclude it so query rewrite sees prior turns only.
    if (
        history
        and history[-1]["role"] == "user"
        and history[-1]["content"] == body.content
    ):
        history = history[:-1]

    doc_ids = (
        [str(d) for d in body.document_ids] if body.document_ids else list(session.document_ids or [])
    )
    names: dict[str, str] = {}
    if doc_ids:
        uuids = [uuid.UUID(d) for d in doc_ids]
        docs = await db.execute(select(Document).where(Document.id.in_(uuids)))
        names = {str(d.id): d.filename for d in docs.scalars().all()}

    if body.stream:

        async def event_gen():
            from app.generation.orchestrator import stream_answer_question
            from app.types import GenerationResult
            import logging
            _log = logging.getLogger(__name__)

            queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

            async def producer():
                try:
                    async for item in stream_answer_question(
                        body.content,
                        document_ids=doc_ids or None,
                        document_names=names,
                        chat_history=history,
                    ):
                        await queue.put(("item", item))
                    await queue.put(("done_signal", None))
                except Exception as exc:
                    _log.exception("Exception during chat SSE stream: %s", exc)
                    await queue.put(("error", str(exc)))

            producer_task = asyncio.create_task(producer())

            # Yield an immediate ping event to flush HTTP/2 headers immediately
            yield ": ping\n\n"

            gen = None
            try:
                while True:
                    try:
                        kind, data = await asyncio.wait_for(queue.get(), timeout=3.0)
                    except asyncio.TimeoutError:
                        # Send periodic keepalive ping every 3s so intermediate edge proxies never time out
                        yield ": ping\n\n"
                        continue

                    if kind == "item":
                        if isinstance(data, str):
                            yield f"event: token\ndata: {json.dumps({'token': data})}\n\n"
                        elif isinstance(data, GenerationResult):
                            gen = data
                    elif kind == "error":
                        err_payload = json.dumps({
                            "answer": f"The AI model encountered an error: {data}. Please try again.",
                            "citations": [],
                            "refused": True,
                            "refusal_reason": "stream_error",
                        })
                        yield f"event: done\ndata: {err_payload}\n\n"
                        break
                    elif kind == "done_signal":
                        if gen:
                            payload = {
                                "answer": gen.answer,
                                "citations": [c.model_dump() for c in gen.citations],
                                "refused": gen.refused,
                                "refusal_reason": gen.refusal_reason,
                            }
                            yield f"event: done\ndata: {json.dumps(payload)}\n\n"

                            async with SessionLocal() as persist:
                                persist.add(
                                    Message(
                                        session_id=session_id,
                                        role="assistant",
                                        content=gen.answer,
                                        citations=[c.model_dump() for c in gen.citations],
                                        refused=gen.refused,
                                        refusal_reason=gen.refusal_reason,
                                    )
                                )
                                await persist.commit()
                        else:
                            empty_payload = json.dumps({
                                "answer": "No response could be generated.",
                                "citations": [],
                                "refused": True,
                                "refusal_reason": "empty_generation",
                            })
                            yield f"event: done\ndata: {empty_payload}\n\n"
                        break
            finally:
                if not producer_task.done():
                    producer_task.cancel()

        return StreamingResponse(
            event_gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "X-Accel-Buffering": "no",
            },
        )

    gen = await answer_question(
        body.content,
        document_ids=doc_ids or None,
        document_names=names,
        chat_history=history,
    )
    assistant = Message(
        session_id=session.id,
        role="assistant",
        content=gen.answer,
        citations=[c.model_dump() for c in gen.citations],
        refused=gen.refused,
        refusal_reason=gen.refusal_reason,
    )
    db.add(assistant)
    await db.commit()
    await db.refresh(assistant)

    return ChatMessageOut(
        id=assistant.id,
        role="assistant",
        content=assistant.content,
        citations=[Citation(**c) for c in (assistant.citations or [])],
        refused=assistant.refused,
    )

@router.get("/{session_id}/history", response_model=list[ChatMessageOut])
async def chat_history(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
) -> list[ChatMessageOut]:
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if user.id is not None and session.user_id is not None and session.user_id != user.id:
        raise HTTPException(status_code=404, detail="Session not found")

    msgs = await db.execute(
        select(Message).where(Message.session_id == session_id).order_by(Message.created_at.asc())
    )
    out: list[ChatMessageOut] = []
    for m in msgs.scalars().all():
        out.append(
            ChatMessageOut(
                id=m.id,
                role=m.role,
                content=m.content,
                citations=[Citation(**c) for c in (m.citations or [])],
                refused=m.refused,
            )
        )
    return out

@router.delete('/{session_id}')
async def delete_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
) -> dict[str, Any]:
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail='Session not found')
    if user.id is not None and session.user_id is not None and session.user_id != user.id:
        raise HTTPException(status_code=404, detail='Session not found')
    await db.delete(session)
    await db.commit()
    return {'status': 'deleted'}
