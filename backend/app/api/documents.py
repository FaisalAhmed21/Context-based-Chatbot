

from __future__ import annotations

import logging
import mimetypes
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import AuthUser, get_current_user
from app.config import get_settings
from app.db.models import Document
from app.db.session import SessionLocal, get_db
from app.ingestion.image import is_image_path
from app.ingestion.pipeline import ensure_upload_dir, run_ingestion
from app.ingestion.text import is_text_path
from app.ingestion.video import is_video_path
from app.ingestion.web import fetch_url_text
from app.retrieval.vector_store import delete_by_document
from app.types import DocumentOut, DocumentStatus

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])

_ALLOWED = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".bmp",
    ".mp4",
    ".webm",
    ".mov",
    ".mkv",
    ".avi",
    ".mpeg",
    ".mp3",
    ".wav",
    ".m4a",
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".json",
    ".log",
    ".html",
    ".htm",
}

def _to_out(doc: Document) -> DocumentOut:
    return DocumentOut(
        id=doc.id,
        filename=doc.filename,
        status=DocumentStatus(doc.status),
        page_count=doc.page_count,
        chunk_count=doc.chunk_count,
        error_message=doc.error_message,
        content_type=doc.content_type,
    )

def _owned(doc: Document, user: AuthUser) -> bool:
    if user.id is None:
        return True
    return doc.user_id == user.id

def _content_type_for(filename: str, guessed: str | None) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return guessed or "application/pdf"
    if is_image_path(filename):
        return guessed or "image/png"
    if is_video_path(filename):
        if Path(filename).suffix.lower() in {".mp3", ".wav", ".m4a"}:
            return guessed or "audio/mpeg"
        return guessed or "video/mp4"
    if is_text_path(filename) or suffix in {".html", ".htm"}:
        return guessed or "text/plain"
    return guessed or "application/octet-stream"

@router.post(
    "/upload",
    response_model=DocumentOut,
    summary="Upload a knowledge-base file",
    description=(
        "Accepts PDF, images, video/audio (Groq Whisper), and text/markdown. "
        "Kicks off async parse → chunk → embed → index. Replacing content: "
        "upload again or call POST /documents/{id}/reingest."
    ),
)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
) -> DocumentOut:
    settings = get_settings()
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in _ALLOWED:
        raise HTTPException(
            status_code=400,
            detail=(
                "Supported: PDF, images (PNG/JPG/WEBP/GIF), video/audio "
                "(MP4/WEBM/MOV/MP3/WAV ≤25MB for Whisper), text (.txt/.md)."
            ),
        )

    data = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(status_code=400, detail=f"File exceeds {settings.max_upload_mb}MB limit.")
    if is_video_path(file.filename) and len(data) > 25 * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail="Video/audio must be ≤25MB for Groq Whisper free tier. Compress or trim.",
        )

    upload_root = ensure_upload_dir(settings.upload_dir)
    doc_id = uuid.uuid4()
    dest = upload_root / str(doc_id) / file.filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)

    guessed = file.content_type or mimetypes.guess_type(file.filename)[0]
    content_type = _content_type_for(file.filename, guessed)

    doc = Document(
        id=doc_id,
        user_id=user.id,
        filename=file.filename,
        storage_path=str(dest.resolve()),
        content_type=content_type,
        status=DocumentStatus.PENDING.value,
        meta={"source": "upload"},
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    logger.info("Queued ingest %s (%s, %d bytes)", doc.id, file.filename, len(data))
    background_tasks.add_task(run_ingestion, doc.id, SessionLocal)
    return _to_out(doc)

class UrlIngestBody(BaseModel):
    url: HttpUrl
    title: str | None = Field(default=None, description="Optional display name")

@router.post(
    "/from-url",
    response_model=DocumentOut,
    summary="Ingest a public web page",
    description="Fetches the URL, extracts readable text, and indexes it like any other document.",
)
async def ingest_from_url(
    body: UrlIngestBody,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
) -> DocumentOut:
    settings = get_settings()
    url = str(body.url)
    try:
        page_title, text = fetch_url_text(url)
    except Exception as exc:  
        raise HTTPException(status_code=400, detail=f"Could not fetch URL: {exc}") from exc

    display = body.title or page_title or url

    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in display)[:80] or "webpage"
    filename = f"{safe}.url"

    upload_root = ensure_upload_dir(settings.upload_dir)
    doc_id = uuid.uuid4()
    dest = upload_root / str(doc_id) / filename
    dest.parent.mkdir(parents=True, exist_ok=True)

    dest.write_text(f"{url}\n\n{text}", encoding="utf-8")

    doc = Document(
        id=doc_id,
        user_id=user.id,
        filename=display[:512],
        storage_path=str(dest.resolve()),
        content_type="text/uri-list",
        status=DocumentStatus.PENDING.value,
        meta={"source": "web", "url": url},
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    logger.info("Queued URL ingest %s → %s", doc.id, url)
    background_tasks.add_task(run_ingestion, doc.id, SessionLocal)
    return _to_out(doc)

@router.post(
    "/{document_id}/reingest",
    response_model=DocumentOut,
    summary="Re-index a document without full retraining",
    description=(
        "Re-runs parse → chunk → embed → index for an existing file. "
        "Old vectors are replaced — no model retraining."
    ),
)
async def reingest_document(
    document_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
) -> DocumentOut:
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc or not _owned(doc, user):
        raise HTTPException(status_code=404, detail="Document not found")
    if not Path(doc.storage_path).exists():
        raise HTTPException(status_code=400, detail="Source file missing on disk")

    doc.status = DocumentStatus.PENDING.value
    doc.error_message = None
    await db.commit()
    await db.refresh(doc)

    logger.info("Re-ingest queued for %s", document_id)
    background_tasks.add_task(run_ingestion, doc.id, SessionLocal)
    return _to_out(doc)

@router.get("/{document_id}/file")
async def document_file(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None, description="Bearer JWT for <img>/pdf.js/video"),
) -> FileResponse:

    from app.api.auth import resolve_token_user

    user = await resolve_token_user(db, authorization=authorization, access_token=token)
    user_id = user.id

    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if user_id is not None and doc.user_id is not None and doc.user_id != user_id:
        raise HTTPException(status_code=404, detail="Document not found")
    path = Path(doc.storage_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing on disk")
    media = doc.content_type or mimetypes.guess_type(doc.filename)[0] or "application/octet-stream"

    if path.suffix.lower() == ".url":
        media = "text/plain"
    return FileResponse(
        path,
        media_type=media,
        filename=doc.filename,
        headers={"Cache-Control": "private, max-age=3600"},
    )

@router.get("/{document_id}/status", response_model=DocumentOut)
async def document_status(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
) -> DocumentOut:
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc or not _owned(doc, user):
        raise HTTPException(status_code=404, detail="Document not found")
    return _to_out(doc)

@router.get("", response_model=list[DocumentOut])
async def list_documents(
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
) -> list[DocumentOut]:
    stmt = select(Document).order_by(Document.created_at.desc())
    if user.id is not None:
        stmt = stmt.where(Document.user_id == user.id)
    result = await db.execute(stmt)
    return [_to_out(d) for d in result.scalars().all()]

@router.delete("/{document_id}")
async def delete_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
) -> dict[str, str]:
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc or not _owned(doc, user):
        raise HTTPException(status_code=404, detail="Document not found")

    path = Path(doc.storage_path)
    if path.exists():
        path.unlink(missing_ok=True)
        parent = path.parent
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()

    delete_by_document(str(document_id))

    try:
        from sqlalchemy import delete as sql_delete

        from app.retrieval.graph_rag import GraphEntity, GraphRelation

        await db.execute(sql_delete(GraphRelation).where(GraphRelation.document_id == document_id))
        await db.execute(sql_delete(GraphEntity).where(GraphEntity.document_id == document_id))
    except Exception:  
        logger.debug("Graph cleanup skipped", exc_info=True)

    await db.delete(doc)
    await db.commit()
    return {"status": "deleted", "id": str(document_id)}

