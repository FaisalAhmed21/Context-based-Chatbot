

from __future__ import annotations

import logging
import math
import re
import uuid
from collections import Counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChunkRecord
from app.db.session import SessionLocal
from app.types import Chunk, ElementType, RetrievedChunk

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)?", re.I)

def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "") if len(t) > 1]

def _bm25_scores(
    corpus: list[list[str]],
    query: list[str],
    *,
    k1: float = 1.5,
    b: float = 0.75,
) -> list[float]:

    n_docs = len(corpus)
    if n_docs == 0 or not query:
        return []
    avgdl = sum(len(doc) for doc in corpus) / n_docs
    df: Counter[str] = Counter()
    for doc in corpus:
        for term in set(doc):
            df[term] += 1

    scores: list[float] = []
    for doc in corpus:
        tf = Counter(doc)
        dl = len(doc) or 1
        score = 0.0
        for term in query:
            freq = tf.get(term, 0)
            if not freq:
                continue
            n_qi = df.get(term, 0)
            idf = math.log(1.0 + (n_docs - n_qi + 0.5) / (n_qi + 0.5))
            denom = freq + k1 * (1.0 - b + b * dl / avgdl)
            score += idf * (freq * (k1 + 1.0)) / denom
        scores.append(score)
    return scores

def _record_to_retrieved(rec: ChunkRecord, score: float, sparse_rank: int) -> RetrievedChunk:
    try:
        chunk_type = ElementType(rec.chunk_type or "text")
    except ValueError:
        chunk_type = ElementType.TEXT
    chunk = Chunk(
        id=str(rec.id),
        document_id=str(rec.document_id),
        content=rec.content or "",
        contextualized_content=rec.contextualized_content,
        page_number=rec.page_number,
        section_title=rec.section_title,
        chunk_type=chunk_type,
        char_offset=rec.char_offset,
        chunk_index=rec.chunk_index or 0,
        metadata=dict(rec.meta or {}),
    )
    return RetrievedChunk(
        chunk=chunk,
        score=score,
        sparse_rank=sparse_rank,
        dense_score=None,
    )

async def sparse_search(
    query: str,
    *,
    document_ids: list[str] | None = None,
    top_k: int = 20,
) -> list[RetrievedChunk]:

    q_tokens = _tokenize(query)
    if not q_tokens:
        return []

    async with SessionLocal() as session:
        session: AsyncSession
        stmt = select(ChunkRecord)
        if document_ids:
            try:
                ids = [uuid.UUID(d) for d in document_ids]
            except ValueError:
                return []
            stmt = stmt.where(ChunkRecord.document_id.in_(ids))
        result = await session.execute(stmt.order_by(ChunkRecord.chunk_index.asc()))
        records = list(result.scalars().all())

    if not records:
        return []

    paired = [
        (r, toks)
        for r, toks in (
            (r, _tokenize(r.contextualized_content or r.content)) for r in records
        )
        if toks
    ]
    if not paired:
        return []
    records_f, corpus_f = zip(*paired)
    scores = _bm25_scores(list(corpus_f), q_tokens)

    ranked = sorted(
        zip(records_f, scores),
        key=lambda x: float(x[1]),
        reverse=True,
    )[:top_k]

    out: list[RetrievedChunk] = []
    for rank, (rec, sc) in enumerate(ranked, start=1):
        if float(sc) <= 0:
            continue
        out.append(_record_to_retrieved(rec, float(sc), rank))
    return out
