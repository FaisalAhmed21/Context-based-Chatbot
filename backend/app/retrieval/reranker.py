

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache

from app.config import get_settings
from app.types import RetrievedChunk

logger = logging.getLogger(__name__)

@lru_cache
def _cross_encoder():
    settings = get_settings()
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    logger.info("Loading reranker %s …", settings.rerank_model)
    return TextCrossEncoder(model_name=settings.rerank_model)

async def rerank(
    query: str,
    candidates: list[RetrievedChunk],
    *,
    top_n: int = 15,
) -> list[RetrievedChunk]:

    if not candidates:
        return []

    settings = get_settings()
    if not settings.rerank_enabled:
        ranked = sorted(
            candidates,
            key=lambda c: (
                c.dense_score if c.dense_score is not None else c.score,
            ),
            reverse=True,
        )[:top_n]
        for c in ranked:
            c.rerank_score = c.dense_score if c.dense_score is not None else c.score
        return ranked

    docs = [c.chunk.content for c in candidates]

    def _run() -> list[float]:
        model = _cross_encoder()

        scores = list(model.rerank(query, docs))
        return [float(s) for s in scores]

    try:
        scores = await asyncio.to_thread(_run)
    except Exception as exc:  
        logger.warning("Reranker failed (%s) — falling back to fusion order", exc)
        ranked = sorted(candidates, key=lambda c: c.score, reverse=True)[:top_n]
        for c in ranked:
            c.rerank_score = c.dense_score if c.dense_score is not None else c.score
        return ranked

    if len(scores) != len(candidates):

        logger.warning(
            "Reranker returned %d scores for %d docs — truncating",
            len(scores),
            len(candidates),
        )

    paired: list[tuple[RetrievedChunk, float]] = []
    for i, c in enumerate(candidates):
        sc = scores[i] if i < len(scores) else (c.dense_score or c.score)
        c.rerank_score = float(sc)
        paired.append((c, float(sc)))

    paired.sort(key=lambda x: x[1], reverse=True)
    return [c for c, _ in paired[:top_n]]
