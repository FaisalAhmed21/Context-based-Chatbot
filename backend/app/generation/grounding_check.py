

from __future__ import annotations

import logging
import re

from app.config import get_settings
from app.generation.prompt import REFUSAL_MESSAGE, format_context
from app.types import GenerationResult, RetrievedChunk

logger = logging.getLogger(__name__)

_GROUNDED_RE = re.compile(r"\bGROUNDED\b", re.I)
_UNGROUNDED_RE = re.compile(r"\bUNGROUNDED\b", re.I)

_CHECK_SYSTEM = """You are a strict grading evaluator. Check if the ANSWER is completely supported by the CONTEXT. If the answer contains any information not present in the context, output UNGROUNDED. Otherwise output GROUNDED. Only output one word: GROUNDED or UNGROUNDED."""

def relevance_gate(chunks: list[RetrievedChunk]) -> GenerationResult | None:

    settings = get_settings()
    if not chunks:
        return GenerationResult(
            answer=REFUSAL_MESSAGE,
            refused=True,
            refusal_reason="relevance_gate",
            confidence=0.0,
        )

    top = chunks[0]
    dense_scores = [c.dense_score for c in chunks if c.dense_score is not None]
    best_dense = max(dense_scores) if dense_scores else None

    dense_ok = best_dense is not None and best_dense >= settings.relevance_threshold
    sparse_ok = (
        top.sparse_rank is not None
        and top.rerank_score is not None
        and top.rerank_score >= settings.rerank_threshold
    )

    confidence = best_dense if best_dense is not None else (top.rerank_score or top.score)
    if not dense_ok and not sparse_ok:
        return GenerationResult(
            answer=REFUSAL_MESSAGE,
            refused=True,
            refusal_reason="relevance_gate",
            confidence=confidence,
        )
    return None

def _parse_verdict(raw: str) -> bool | None:

    text = (raw or "").strip()
    if _UNGROUNDED_RE.search(text):
        return False
    if _GROUNDED_RE.search(text):
        return True
    return None

async def log_gate_failure(
    *,
    question: str,
    gate: str,
    answer_draft: str | None = None,
    top_score: float | None = None,
) -> None:
    try:
        from app.db.models import EvalLog
        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            session.add(
                EvalLog(
                    question=question or "(unknown)",
                    gate=gate,
                    top_score=top_score,
                    answer_draft=(answer_draft or "")[:4000] or None,
                )
            )
            await session.commit()
    except Exception:  
        logger.debug("EvalLog write skipped", exc_info=True)

async def groundedness_check(
    answer: str,
    chunks: list[RetrievedChunk],
    *,
    question: str | None = None,
) -> GenerationResult | None:

    settings = get_settings()

    if answer.strip() == REFUSAL_MESSAGE:
        return GenerationResult(
            answer=REFUSAL_MESSAGE,
            refused=True,
            refusal_reason="prompt",
        )

    if answer.startswith("[No LLM API key") or "All LLM providers failed" in answer:
        return None

    if not settings.groundedness_enabled:
        return None

    if not chunks:
        return GenerationResult(
            answer=REFUSAL_MESSAGE,
            refused=True,
            refusal_reason="groundedness_check",
            confidence=0.0,
        )

    from app.generation.llm_client import complete_chat, has_any_llm_key

    if not has_any_llm_key():
        return None

    context = format_context(chunks)
    user = (
        f"Question: {question or '(not provided)'}\n\n"
        f"CONTEXT:\n{context}\n\n"
        f"ANSWER:\n{answer}\n\n"
        "Verdict (GROUNDED or UNGROUNDED):"
    )
    messages = [
        {"role": "system", "content": _CHECK_SYSTEM},
        {"role": "user", "content": user},
    ]

    try:
        raw = await complete_chat(messages, temperature=0.0)
    except Exception as exc:  
        logger.warning("Groundedness check failed open (%s) — accepting answer", exc)
        return None

    verdict = _parse_verdict(raw)
    if verdict is True:
        return None
    if verdict is False:
        logger.info("Groundedness check rejected answer (draft len=%d)", len(answer))
        await log_gate_failure(
            question=question or "",
            gate="groundedness",
            answer_draft=answer,
            top_score=chunks[0].dense_score or chunks[0].score,
        )
        return GenerationResult(
            answer=REFUSAL_MESSAGE,
            refused=True,
            refusal_reason="groundedness_check",
            confidence=0.0,
        )

    logger.warning("Groundedness verdict unparseable: %r — accepting answer", raw[:120])
    return None
