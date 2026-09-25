

from __future__ import annotations

from collections.abc import AsyncIterator

from app.config import get_settings
from app.types import GenerationResult

async def answer_question(
    question: str,
    *,
    document_ids: list[str] | None = None,
    document_names: dict[str, str] | None = None,
    chat_history: list[dict[str, str]] | None = None,
) -> GenerationResult:
    settings = get_settings()
    if settings.use_langgraph:
        from app.generation.langgraph_agent import answer_with_langgraph

        return await answer_with_langgraph(
            question,
            document_ids=document_ids,
            document_names=document_names,
            chat_history=chat_history,
        )

    from app.generation.agentic import answer_question_agentic

    return await answer_question_agentic(
        question,
        document_ids=document_ids,
        document_names=document_names,
        chat_history=chat_history,
    )

async def stream_answer_question(
    question: str,
    *,
    document_ids: list[str] | None = None,
    document_names: dict[str, str] | None = None,
    chat_history: list[dict[str, str]] | None = None,
) -> AsyncIterator[str | GenerationResult]:

    settings = get_settings()

    if settings.use_langgraph:
        result = await answer_question(
            question,
            document_ids=document_ids,
            document_names=document_names,
            chat_history=chat_history,
        )
        yield result
        return

    from app.generation.agentic import stream_answer_question_agentic

    async for item in stream_answer_question_agentic(
        question,
        document_ids=document_ids,
        document_names=document_names,
        chat_history=chat_history,
    ):
        yield item

