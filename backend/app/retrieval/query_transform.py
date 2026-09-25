

from __future__ import annotations

import logging
import re

from app.config import get_settings
from app.types import RetrievedChunk

logger = logging.getLogger(__name__)

_MULTI_HOP = re.compile(
    r"\b(compare|versus|vs\.?|difference|both|across|relationship|how does .+ relate|"
    r"as well as|in addition|and also)\b",
    re.I,
)

def looks_multihop(question: str) -> bool:
    q = question.strip()
    if _MULTI_HOP.search(q):
        return True

    if q.lower().count(" and ") >= 1 and q.count("?") <= 1 and len(q.split()) > 8:
        return True
    return False

async def rewrite_query(
    question: str,
    chat_history: list[dict[str, str]] | None = None,
) -> str:

    q = question.strip()
    if not chat_history:
        return q

    from app.generation.llm_client import complete_chat, has_any_llm_key

    if not has_any_llm_key():
        return q

    hist = "\n".join(f"{m['role']}: {m['content'][:300]}" for m in chat_history[-4:])
    try:
        out = await complete_chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Rewrite the latest user question as a standalone search query. "
                        "Resolve pronouns using history. Return ONLY the rewritten query."
                    ),
                },
                {"role": "user", "content": f"History:\n{hist}\n\nQuestion: {q}"},
            ],
            temperature=0.0,
        )
        return out.strip().strip('"') or q
    except Exception as exc:  
        logger.warning("rewrite_query failed: %s", exc)
        return q

async def refine_retrieval_query(
    question: str,
    chunks: list[RetrievedChunk],
) -> str | None:

    from app.generation.llm_client import complete_chat, has_any_llm_key

    if not has_any_llm_key():
        return None

    preview = "\n".join(
        f"- (p.{c.chunk.page_number}) {c.chunk.content[:180]}" for c in chunks[:4]
    ) or "(no chunks)"
    try:
        out = await complete_chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You plan a second document search. Given the user question and "
                        "already-retrieved snippets, output ONE short search query that "
                        "would find missing facts. If nothing is missing, reply NONE."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Question: {question}\n\nRetrieved:\n{preview}\n\nSecond query:",
                },
            ],
            temperature=0.0,
        )
        text = out.strip().strip('"')
        if not text or text.upper() == "NONE" or len(text) < 3:
            return None
        return text
    except Exception as exc:  
        logger.warning("refine_retrieval_query failed: %s", exc)
        return None

async def hyde_document(question: str) -> str | None:

    settings = get_settings()
    if not getattr(settings, "hyde_enabled", False):
        return None

    from app.generation.llm_client import complete_chat, has_any_llm_key

    if not has_any_llm_key():
        return None
    try:
        out = await complete_chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Write a short hypothetical passage (3–5 sentences) that would "
                        "answer the question, as if quoted from a document. No preamble."
                    ),
                },
                {"role": "user", "content": question},
            ],
            temperature=0.2,
        )
        return out.strip() or None
    except Exception as exc:  
        logger.warning("hyde_document failed: %s", exc)
        return None
