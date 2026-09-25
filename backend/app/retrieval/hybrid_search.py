

from __future__ import annotations

import asyncio
import logging

from app.config import get_settings
from app.ingestion.embedder import embed_query
from app.retrieval.bm25 import sparse_search
from app.retrieval.vector_store import search_dense
from app.types import Chunk, ElementType, RetrievedChunk

logger = logging.getLogger(__name__)

def reciprocal_rank_fusion(
    dense: list[RetrievedChunk],
    sparse: list[RetrievedChunk],
    *,
    k: int = 60,
) -> list[RetrievedChunk]:

    scores: dict[str, float] = {}
    best: dict[str, RetrievedChunk] = {}

    def key(rc: RetrievedChunk) -> str:
        return rc.chunk.id or f"{rc.chunk.document_id}:{rc.chunk.chunk_index}"

    for rank, rc in enumerate(dense, start=1):
        kid = key(rc)
        scores[kid] = scores.get(kid, 0.0) + 1.0 / (k + rank)
        rc.dense_rank = rank
        if rc.dense_score is None:
            rc.dense_score = rc.score
        best[kid] = rc.model_copy(deep=True)

    for rank, rc in enumerate(sparse, start=1):
        kid = key(rc)
        scores[kid] = scores.get(kid, 0.0) + 1.0 / (k + rank)
        existing = best.get(kid)
        if existing:
            existing.sparse_rank = rank
        else:
            copy = rc.model_copy(deep=True)
            copy.sparse_rank = rank
            best[kid] = copy

    for kid, sc in scores.items():
        best[kid].score = sc

    return sorted(best.values(), key=lambda x: x.score, reverse=True)

def _scored_point_to_retrieved(hit, *, dense_rank: int) -> RetrievedChunk:
    payload = hit.payload or {}
    chunk_type_raw = payload.get("chunk_type") or "text"
    try:
        chunk_type = ElementType(chunk_type_raw)
    except ValueError:
        chunk_type = ElementType.TEXT

    cosine = float(hit.score)
    meta = dict(payload.get("metadata") or {})
    for key in ("timestamp_start", "timestamp_end", "timestamp_label", "url", "source"):
        if key in payload and key not in meta:
            meta[key] = payload[key]
    chunk = Chunk(
        id=payload.get("chunk_id"),
        document_id=str(payload.get("document_id", "")),
        content=str(payload.get("content") or ""),
        page_number=payload.get("page_number"),
        section_title=payload.get("section_title"),
        chunk_type=chunk_type,
        char_offset=payload.get("char_offset"),
        chunk_index=int(payload.get("chunk_index") or 0),
        metadata=meta,
    )
    return RetrievedChunk(
        chunk=chunk,
        score=cosine,
        dense_rank=dense_rank,
        dense_score=cosine,
    )

async def dense_search(
    query: str,
    *,
    document_ids: list[str] | None = None,
    top_k: int = 20,
) -> list[RetrievedChunk]:

    vector = await embed_query(query)
    hits = search_dense(vector, document_ids=document_ids, top_k=top_k)
    return [_scored_point_to_retrieved(h, dense_rank=i) for i, h in enumerate(hits, start=1)]

async def hybrid_search(
    query: str,
    *,
    document_ids: list[str] | None = None,
    top_k: int = 20,
) -> list[RetrievedChunk]:

    settings = get_settings()
    dense_task = dense_search(query, document_ids=document_ids, top_k=top_k)

    if not settings.hybrid_enabled:
        return await dense_task

    dense, sparse = await asyncio.gather(
        dense_task,
        sparse_search(query, document_ids=document_ids, top_k=top_k),
        return_exceptions=True,
    )

    if isinstance(dense, Exception):
        logger.error("Dense search failed: %s", dense)
        dense = []
    if isinstance(sparse, Exception):
        logger.warning("Sparse search failed: %s", sparse)
        sparse = []

    if not sparse:
        return list(dense)
    if not dense:
        return list(sparse)

    fused = reciprocal_rank_fusion(list(dense), list(sparse))
    return fused[: max(top_k, 30)]
