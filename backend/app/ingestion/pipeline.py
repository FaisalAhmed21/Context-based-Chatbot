

from __future__ import annotations

import logging
from pathlib import Path
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChunkRecord, Document
from app.ingestion.chunker import apply_contextual_prefix, structure_aware_chunk
from app.ingestion.embedder import embed_texts
from app.ingestion.loaders import get_loader_for_path
from app.retrieval.vector_store import delete_by_document, new_point_id, upsert_chunks
from app.types import DocumentStatus

logger = logging.getLogger(__name__)

_EMBED_BATCH = 32

async def _set_status(
    session: AsyncSession,
    doc: Document,
    status: DocumentStatus,
    *,
    error: str | None = None,
    page_count: int | None = None,
    chunk_count: int | None = None,
) -> None:
    doc.status = status.value
    if error is not None:
        doc.error_message = error
    if page_count is not None:
        doc.page_count = page_count
    if chunk_count is not None:
        doc.chunk_count = chunk_count
    await session.commit()

async def run_ingestion(document_id: UUID, session_factory) -> None:

    async with session_factory() as session:
        session: AsyncSession
        result = await session.execute(select(Document).where(Document.id == document_id))
        doc = result.scalar_one_or_none()
        if doc is None:
            logger.error("Document %s not found", document_id)
            return

        try:
            doc_pk = doc.id
            doc_name = doc.filename
            storage_path = doc.storage_path

            await _set_status(session, doc, DocumentStatus.PARSING)
            loader = get_loader_for_path(storage_path)
            elements = loader.load(storage_path, source_id=str(doc_pk))
            pages = {e.page_number for e in elements if e.page_number}
            page_count = max(pages) if pages else (1 if elements else 0)

            await _set_status(session, doc, DocumentStatus.CHUNKING, page_count=page_count)
            chunks = structure_aware_chunk(elements, document_id=str(doc_pk))
            chunks = await apply_contextual_prefix(chunks, document_name=doc_name)

            await _set_status(session, doc, DocumentStatus.EMBEDDING, chunk_count=len(chunks))

            delete_by_document(str(doc_pk))
            await session.execute(
                delete(ChunkRecord).where(ChunkRecord.document_id == doc_pk)
            )
            await session.commit()

            texts = [c.contextualized_content or c.content for c in chunks]
            vectors: list[list[float]] = []
            for i in range(0, len(texts), _EMBED_BATCH):
                batch = texts[i : i + _EMBED_BATCH]
                vectors.extend(await embed_texts(batch))

            points: list[dict] = []
            for ch, vector in zip(chunks, vectors, strict=True):
                point_id = new_point_id()
                record = ChunkRecord(
                    document_id=doc_pk,
                    content=ch.content,
                    contextualized_content=ch.contextualized_content,
                    page_number=ch.page_number,
                    section_title=ch.section_title,
                    chunk_type=ch.chunk_type.value,
                    char_offset=ch.char_offset,
                    chunk_index=ch.chunk_index,
                    qdrant_point_id=point_id,
                    meta=ch.metadata,
                )
                session.add(record)
                await session.flush()  

                payload = {
                    "chunk_id": str(record.id),
                    "document_id": str(doc_pk),
                    "content": ch.content,
                    "page_number": ch.page_number,
                    "section_title": ch.section_title,
                    "chunk_type": ch.chunk_type.value,
                    "chunk_index": ch.chunk_index,
                    "char_offset": ch.char_offset,
                    "metadata": ch.metadata or {},
                }

                for k in ("timestamp_start", "timestamp_end", "timestamp_label"):
                    if ch.metadata and k in ch.metadata:
                        payload[k] = ch.metadata[k]
                points.append({"id": point_id, "vector": vector, "payload": payload})

            upsert_chunks(points=points)
            await session.commit()

            result = await session.execute(select(Document).where(Document.id == document_id))
            doc = result.scalar_one()
            await _set_status(
                session,
                doc,
                DocumentStatus.READY,
                page_count=page_count,
                chunk_count=len(chunks),
            )
            logger.info("Ingestion complete for %s (%d chunks)", document_id, len(chunks))

            try:
                from app.config import get_settings
                from app.retrieval.graph_rag import build_graph_for_document

                if get_settings().graphrag_enabled:
                    stats = await build_graph_for_document(document_id)
                    logger.info("GraphRAG built for %s: %s", document_id, stats)
            except Exception:  
                logger.warning("GraphRAG build skipped/failed for %s", document_id, exc_info=True)
        except Exception as exc:  
            logger.exception("Ingestion failed for %s", document_id)
            await session.rollback()
            try:
                delete_by_document(str(document_id))
            except Exception:  
                logger.warning("Failed to clean Qdrant points after ingestion error", exc_info=True)
            result = await session.execute(select(Document).where(Document.id == document_id))
            doc = result.scalar_one_or_none()
            if doc:
                await _set_status(session, doc, DocumentStatus.FAILED, error=str(exc))

def ensure_upload_dir(upload_dir: str) -> Path:
    path = Path(upload_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path
