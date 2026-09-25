

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from sqlalchemy import String, Text, UniqueConstraint, delete, select
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.models import Base, ChunkRecord
from app.db.session import SessionLocal
from app.types import Chunk, ElementType, RetrievedChunk

logger = logging.getLogger(__name__)

class GraphEntity(Base):
    __tablename__ = "graph_entities"
    __table_args__ = (UniqueConstraint("document_id", "name", name="uq_entity_doc_name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), default="concept")

class GraphRelation(Base):
    __tablename__ = "graph_relations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    source_name: Mapped[str] = mapped_column(String(256), nullable=False)
    target_name: Mapped[str] = mapped_column(String(256), nullable=False)
    relation: Mapped[str] = mapped_column(String(128), default="related_to")
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)

_JSON_BLOCK = re.compile(r"\{[\s\S]*\}|\[[\s\S]*\]")

async def build_graph_for_document(document_id: uuid.UUID) -> dict[str, int]:

    from app.config import get_settings
    from app.generation.llm_client import complete_chat, has_any_llm_key

    settings = get_settings()
    if not getattr(settings, "graphrag_enabled", True):
        return {"entities": 0, "relations": 0}
    if not has_any_llm_key():
        logger.info("GraphRAG skipped — no LLM key")
        return {"entities": 0, "relations": 0}

    async with SessionLocal() as session:

        from app.db.session import engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        await session.execute(delete(GraphRelation).where(GraphRelation.document_id == document_id))
        await session.execute(delete(GraphEntity).where(GraphEntity.document_id == document_id))
        await session.commit()

        result = await session.execute(
            select(ChunkRecord)
            .where(ChunkRecord.document_id == document_id)
            .order_by(ChunkRecord.chunk_index.asc())
        )
        chunks = list(result.scalars().all())
        if not chunks:
            return {"entities": 0, "relations": 0}

        sample = chunks[:12]
        blob = "\n\n".join(
            f"[chunk {c.chunk_index} id={c.id}]\n{(c.content or '')[:600]}" for c in sample
        )
        prompt = f
        try:
            raw = await complete_chat(
                [
                    {
                        "role": "system",
                        "content": "You extract entities and relations. Output JSON only.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
            )
        except Exception as exc:  
            logger.warning("GraphRAG extraction failed: %s", exc)
            return {"entities": 0, "relations": 0}

        data = _parse_json(raw)
        if not isinstance(data, dict):
            return {"entities": 0, "relations": 0}

        index_to_id = {c.chunk_index: c.id for c in sample}
        entities = data.get("entities") or []
        relations = data.get("relations") or []
        seen_names: set[str] = set()

        for ent in entities[:20]:
            if not isinstance(ent, dict):
                continue
            name = str(ent.get("name") or "").strip()
            if not name or name.lower() in seen_names:
                continue
            seen_names.add(name.lower())
            session.add(
                GraphEntity(
                    document_id=document_id,
                    name=name[:256],
                    entity_type=str(ent.get("type") or "concept")[:64],
                )
            )

        for rel in relations[:25]:
            if not isinstance(rel, dict):
                continue
            src = str(rel.get("source") or "").strip()
            tgt = str(rel.get("target") or "").strip()
            if not src or not tgt:
                continue
            idx = rel.get("chunk_index")
            chunk_id = index_to_id.get(int(idx)) if idx is not None else None
            session.add(
                GraphRelation(
                    document_id=document_id,
                    source_name=src[:256],
                    target_name=tgt[:256],
                    relation=str(rel.get("relation") or "related_to")[:128],
                    chunk_id=chunk_id,
                    evidence=None,
                )
            )

        await session.commit()
        logger.info(
            "GraphRAG doc=%s entities=%d relations=%d",
            document_id,
            len(seen_names),
            min(len(relations), 25),
        )
        return {"entities": len(seen_names), "relations": min(len(relations), 25)}

def _parse_json(raw: str) -> Any:
    text = raw.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = _JSON_BLOCK.search(text)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None

async def expand_via_graph(
    question: str,
    ranked: list[RetrievedChunk],
    *,
    document_ids: list[str] | None,
    limit: int = 4,
) -> list[RetrievedChunk]:

    if not ranked and not question:
        return []

    terms = set()
    for tok in re.findall(r"[A-Za-z][A-Za-z0-9_\-]{2,}", question):
        terms.add(tok.lower())
    for rc in ranked[:3]:
        for tok in re.findall(r"[A-Za-z][A-Za-z0-9_\-]{2,}", rc.chunk.content[:200]):
            terms.add(tok.lower())

    if not terms:
        return []

    async with SessionLocal() as session:
        stmt = select(GraphRelation)
        if document_ids:
            try:
                ids = [uuid.UUID(d) for d in document_ids]
            except ValueError:
                return []
            stmt = stmt.where(GraphRelation.document_id.in_(ids))
        rels = list((await session.execute(stmt)).scalars().all())
        if not rels:
            return []

        chunk_ids: list[uuid.UUID] = []
        for rel in rels:
            s = rel.source_name.lower()
            t = rel.target_name.lower()
            if any(term in s or term in t or s in term or t in term for term in terms):
                if rel.chunk_id:
                    chunk_ids.append(rel.chunk_id)

        if not chunk_ids:
            return []

        rows = list(
            (
                await session.execute(
                    select(ChunkRecord).where(ChunkRecord.id.in_(chunk_ids[:limit]))
                )
            )
            .scalars()
            .all()
        )

    out: list[RetrievedChunk] = []
    for rec in rows:
        try:
            ctype = ElementType(rec.chunk_type or "text")
        except ValueError:
            ctype = ElementType.TEXT
        chunk = Chunk(
            id=str(rec.id),
            document_id=str(rec.document_id),
            content=rec.content or "",
            contextualized_content=rec.contextualized_content,
            page_number=rec.page_number,
            section_title=rec.section_title,
            chunk_type=ctype,
            char_offset=rec.char_offset,
            chunk_index=rec.chunk_index or 0,
            metadata=dict(rec.meta or {}),
        )
        out.append(
            RetrievedChunk(
                chunk=chunk,
                score=0.35,
                dense_score=0.35,
                sparse_rank=None,
            )
        )
    return out
