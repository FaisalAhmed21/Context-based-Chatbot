

from __future__ import annotations

from app.types import Chunk, ElementType, RawElement

def fixed_size_chunk(
    elements: list[RawElement],
    document_id: str,
    *,
    chunk_size: int = 800,
    overlap: int = 120,
) -> list[Chunk]:

    chunks: list[Chunk] = []
    buffer = ""
    current_page: int | None = None
    current_section: str | None = None
    char_offset = 0
    index = 0

    def flush(text: str, page: int | None, offset: int, section: str | None) -> None:
        nonlocal index
        text = text.strip()
        if not text:
            return
        chunks.append(
            Chunk(
                document_id=document_id,
                content=text,
                page_number=page,
                section_title=section,
                chunk_type=ElementType.TEXT,
                char_offset=offset,
                chunk_index=index,
            )
        )
        index += 1

    for el in elements:
        if el.type == ElementType.TABLE:
            if buffer:
                flush(buffer, current_page, char_offset, current_section)
                buffer = ""
            chunks.append(
                Chunk(
                    document_id=document_id,
                    content=el.content.strip(),
                    page_number=el.page_number,
                    section_title=el.section_title,
                    chunk_type=ElementType.TABLE,
                    char_offset=char_offset,
                    chunk_index=index,
                )
            )
            index += 1
            char_offset += len(el.content)
            continue

        if not el.content:
            continue

        current_page = el.page_number
        current_section = el.section_title
        remaining = el.content
        while remaining:
            space = chunk_size - len(buffer)
            if space <= 0:
                flush(buffer, current_page, char_offset, current_section)
                buffer = buffer[-overlap:] if overlap and len(buffer) > overlap else ""
                char_offset += max(0, chunk_size - overlap)
                continue
            take = remaining[:space]
            buffer += take
            remaining = remaining[space:]
            if len(buffer) >= chunk_size:
                flush(buffer, current_page, char_offset, current_section)
                buffer = buffer[-overlap:] if overlap else ""
                char_offset += chunk_size - overlap

    if buffer.strip():
        flush(buffer, current_page, char_offset, current_section)

    return chunks

def _split_oversized(text: str, max_chars: int, overlap: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    parts: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))

        if end < len(text):
            window = text[start:end]
            break_at = max(window.rfind("\n\n"), window.rfind(". "), window.rfind("\n"))
            if break_at > max_chars * 0.4:
                end = start + break_at + 1
        parts.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [p for p in parts if p]

def structure_aware_chunk(
    elements: list[RawElement],
    document_id: str,
    *,
    max_chars: int = 1200,
    overlap: int = 150,
) -> list[Chunk]:

    chunks: list[Chunk] = []
    index = 0
    char_offset = 0

    groups: list[list[RawElement]] = []
    current: list[RawElement] = []

    def flush_group() -> None:
        nonlocal current
        if current:
            groups.append(current)
            current = []

    for el in elements:
        if el.type == ElementType.TABLE:
            flush_group()
            groups.append([el])
            continue
        if el.type == ElementType.IMAGE:
            flush_group()
            groups.append([el])
            continue
        if el.type == ElementType.TRANSCRIPT_SEGMENT:
            flush_group()
            groups.append([el])
            continue
        if not el.content or not el.content.strip():
            continue
        if current and (
            current[-1].section_title != el.section_title
            or current[-1].page_number != el.page_number
        ):
            flush_group()
        current.append(el)
    flush_group()

    for group in groups:
        if group[0].type in (
            ElementType.TABLE,
            ElementType.IMAGE,
            ElementType.TRANSCRIPT_SEGMENT,
        ):
            el = group[0]
            meta = dict(el.metadata or {})
            if el.timestamp_start is not None:
                meta["timestamp_start"] = el.timestamp_start
            if el.timestamp_end is not None:
                meta["timestamp_end"] = el.timestamp_end
            chunks.append(
                Chunk(
                    document_id=document_id,
                    content=el.content.strip(),
                    page_number=el.page_number,
                    section_title=el.section_title,
                    chunk_type=el.type,
                    char_offset=char_offset,
                    chunk_index=index,
                    metadata=meta,
                )
            )
            index += 1
            char_offset += len(el.content)
            continue

        merged = "\n\n".join(e.content.strip() for e in group if e.content.strip())
        section = group[0].section_title
        page = group[0].page_number
        for piece in _split_oversized(merged, max_chars, overlap):
            chunks.append(
                Chunk(
                    document_id=document_id,
                    content=piece,
                    page_number=page,
                    section_title=section,
                    chunk_type=ElementType.TEXT,
                    char_offset=char_offset,
                    chunk_index=index,
                )
            )
            index += 1
            char_offset += len(piece)

    if not chunks:
        return fixed_size_chunk(elements, document_id, chunk_size=max_chars, overlap=overlap)
    return chunks

import logging
from app.config import get_settings
from app.generation.llm_client import complete_chat, has_any_llm_key

logger = logging.getLogger(__name__)

async def apply_contextual_prefix(
    chunks: list[Chunk],
    *,
    document_name: str | None = None,
) -> list[Chunk]:

    doc = document_name or "the document"
    settings = get_settings()

    def _apply_heuristic(chs: list[Chunk]) -> None:
        for ch in chs:
            bits: list[str] = [f"This chunk is from '{doc}'"]
            if ch.section_title:
                bits.append(f"section '{ch.section_title}'")
            if ch.page_number is not None:
                bits.append(f"page {ch.page_number}")
            if ch.chunk_type == ElementType.TABLE:
                bits.append("(table)")
            if ch.chunk_type == ElementType.IMAGE:
                bits.append("(image caption)")
            if ch.chunk_type == ElementType.TRANSCRIPT_SEGMENT:
                bits.append("(video transcript)")
                ts = (ch.metadata or {}).get("timestamp_label") or (ch.metadata or {}).get(
                    "timestamp_start"
                )
                if ts is not None:
                    bits.append(f"at {ts}")
            prefix = ", ".join(bits) + ".\n\n"
            ch.contextualized_content = prefix + ch.content

    if not settings.contextual_retrieval_llm or not has_any_llm_key():
        _apply_heuristic(chunks)
        return chunks

    logger.info("Generating LLM contextual retrieval prefixes for %d chunks in %s", len(chunks), doc)

    batch_size = 5
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        prompt = f"You are a helpful assistant. We are preparing text chunks from a document named '{doc}' for search.\n"
        prompt += "For each chunk, write a 1-sentence description of its context (what the document is and how this chunk fits in) to prepend to it for better search retrieval.\n"
        prompt += "Do NOT explain what the chunk says in detail, just give the context. Output ONLY the 1-sentence prefixes separated by '|||'.\n\n"

        for idx, ch in enumerate(batch):
            prompt += f"--- Chunk {idx + 1} ---\n{ch.content[:800]}\n\n"

        try:
            resp = await complete_chat([{"role": "user", "content": prompt}], temperature=0.0)
            prefixes = [p.strip() for p in resp.split("|||") if p.strip()]

            if len(prefixes) == len(batch):
                for ch, prefix in zip(batch, prefixes):

                    if len(prefix) > 250:
                        prefix = prefix[:250] + "..."
                    ch.contextualized_content = f"{prefix}\n\n{ch.content}"
            else:
                logger.warning("LLM returned %d prefixes for %d chunks, falling back", len(prefixes), len(batch))
                _apply_heuristic(batch)
        except Exception as e:
            logger.warning("Failed to generate context for batch: %s", e)
            _apply_heuristic(batch)

    return chunks
