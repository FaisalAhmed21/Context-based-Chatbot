

from __future__ import annotations

import base64
import logging
import re
import tempfile
from pathlib import Path

from app.config import get_settings
from app.types import DocumentLoader, ElementType, RawElement

logger = logging.getLogger(__name__)

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
_TABLE_SEP_RE = re.compile(r"^\|[\s\-:|]+\|$")
_ZW_RE = re.compile(r"[\u200b\u200c\u200d\ufeff]")

# Pages with little extractable text but embedded images need vision OCR.
_SPARSE_TEXT_CHARS = 220

def _parse_markdown_blocks(
    md: str,
    *,
    source_id: str,
    page_hint: int | None = None,
) -> list[RawElement]:

    elements: list[RawElement] = []
    section: str | None = None
    buf: list[str] = []
    page = page_hint or 1
    in_table = False
    table_lines: list[str] = []

    def flush_text() -> None:
        nonlocal buf
        text = "\n".join(buf).strip()
        buf = []
        if not text:
            return
        elements.append(
            RawElement(
                type=ElementType.TEXT,
                content=text,
                page_number=page,
                source_id=source_id,
                section_title=section,
            )
        )

    def flush_table() -> None:
        nonlocal table_lines, in_table
        content = "\n".join(table_lines).strip()
        table_lines = []
        in_table = False
        if not content:
            return
        elements.append(
            RawElement(
                type=ElementType.TABLE,
                content=content,
                page_number=page,
                source_id=source_id,
                section_title=section,
                metadata={"format": "markdown"},
            )
        )

    for raw_line in md.splitlines():
        line = raw_line.rstrip()

        if line.strip() in ("---", "***") and not in_table:
            continue
        m_page = re.match(r"^<!--\s*page\s*[=:]\s*(\d+)\s*-->$", line.strip(), re.IGNORECASE)
        if m_page:
            flush_text()
            if in_table:
                flush_table()
            page = int(m_page.group(1))
            continue

        if line.startswith("|"):
            if buf:
                flush_text()
            in_table = True
            table_lines.append(line)
            continue
        if in_table:

            flush_table()

        hm = _HEADING_RE.match(line)
        if hm:
            flush_text()
            section = hm.group(2).strip()
            continue

        if not line.strip():
            if buf and buf[-1] != "":
                buf.append("")
            continue
        buf.append(line)

    if in_table:
        flush_table()
    flush_text()
    return elements

def _load_pymupdf4llm(file_path: str, source_id: str) -> list[RawElement]:
    import pymupdf4llm

    chunks = pymupdf4llm.to_markdown(file_path, page_chunks=True)
    elements: list[RawElement] = []
    if isinstance(chunks, list):
        for ch in chunks:
            if isinstance(ch, dict):
                text = (ch.get("text") or ch.get("markdown") or "").strip()
                meta = ch.get("metadata") or {}
                page = int(meta.get("page") or meta.get("page_number") or 1)
            else:
                text = str(ch).strip()
                page = 1
            if not text:
                continue
            elements.extend(
                _parse_markdown_blocks(text, source_id=source_id, page_hint=page)
            )
    else:
        elements = _parse_markdown_blocks(str(chunks), source_id=source_id, page_hint=1)
    return elements

def _load_docling(file_path: str, source_id: str) -> list[RawElement]:
    from docling.document_converter import DocumentConverter

    converter = DocumentConverter()
    result = converter.convert(file_path)
    md = result.document.export_to_markdown()

    return _parse_markdown_blocks(md, source_id=source_id, page_hint=1)

def _clean_pdf_text(text: str) -> str:
    return _ZW_RE.sub("", text or "").strip()


def _vision_ocr_png_bytes(png_bytes: bytes, *, page_number: int) -> str:
    """OCR / describe a rendered PDF page via Gemini (preferred) or Groq vision."""
    settings = get_settings()
    mime = "image/png"
    b64 = base64.b64encode(png_bytes).decode("ascii")
    prompt = (
        "This is a scanned or screenshot page from a PDF. "
        "Transcribe ALL visible text exactly (OCR). Then briefly describe any "
        "diagrams, charts, UI screenshots, or figures that are not pure text. "
        "Be factual; do not invent content that is not visible."
    )

    if settings.gemini_api_key:
        model = (settings.llm_fallback_model or "gemini-3.6-flash").strip()
        if not model.startswith("gemini"):
            model = "gemini-3.6-flash"
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent"
        )
        body = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": mime, "data": b64}},
                    ]
                }
            ],
            "generationConfig": {"temperature": 0.1},
        }
        import httpx

        with httpx.Client(timeout=120.0) as client:
            resp = client.post(url, params={"key": settings.gemini_api_key}, json=body)
            if resp.status_code >= 400:
                raise RuntimeError(f"Gemini OCR {resp.status_code}: {resp.text[:300]}")
            parts = resp.json()["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts).strip()
            if text:
                return text

    if settings.groq_api_key:
        from app.ingestion.image import _caption_groq_sync

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(png_bytes)
            tmp_path = Path(tmp.name)
        try:
            return _caption_groq_sync(tmp_path, mime, settings.groq_api_key)
        finally:
            tmp_path.unlink(missing_ok=True)

    raise RuntimeError("No vision API key available for PDF page OCR")


def _enrich_sparse_pages_with_ocr(
    file_path: str,
    source_id: str,
    elements: list[RawElement],
) -> list[RawElement]:
    """Render image-heavy / sparse pages and append vision-OCR elements."""
    settings = get_settings()
    if not (settings.gemini_api_key or settings.groq_api_key):
        logger.info("Skipping PDF page OCR — no Gemini/Groq vision key configured")
        return elements

    try:
        import fitz
    except ImportError:
        return elements

    by_page: dict[int, list[RawElement]] = {}
    for el in elements:
        if el.page_number is not None:
            by_page.setdefault(el.page_number, []).append(el)

    try:
        doc = fitz.open(file_path)
    except Exception as exc:
        logger.warning("Could not open PDF for OCR enrichment: %s", exc)
        return elements

    extras: list[RawElement] = []
    try:
        for page_idx in range(len(doc)):
            page_no = page_idx + 1
            page = doc[page_idx]
            native = _clean_pdf_text(page.get_text("text"))
            existing = "\n".join(
                _clean_pdf_text(e.content) for e in by_page.get(page_no, []) if e.content
            )
            text_len = max(len(native), len(existing))
            image_count = len(page.get_images(full=True) or [])
            needs_ocr = text_len < _SPARSE_TEXT_CHARS or (
                image_count > 0 and text_len < _SPARSE_TEXT_CHARS * 2
            )
            if not needs_ocr:
                continue
            try:
                # ~144 DPI is enough for OCR while keeping payloads smaller
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                ocr_text = _vision_ocr_png_bytes(pix.tobytes("png"), page_number=page_no)
                ocr_text = _clean_pdf_text(ocr_text)
                if not ocr_text or len(ocr_text) < 20:
                    continue
                # Avoid near-duplicate of already-extracted text
                if existing and ocr_text.lower() in existing.lower():
                    continue
                extras.append(
                    RawElement(
                        type=ElementType.IMAGE,
                        content=ocr_text,
                        page_number=page_no,
                        source_id=source_id,
                        section_title=f"Page {page_no} (OCR)",
                        metadata={
                            "source": "pdf_page_ocr",
                            "native_text_chars": text_len,
                            "image_count": image_count,
                        },
                    )
                )
                logger.info(
                    "PDF page %d OCR added (%d chars, %d images)",
                    page_no,
                    len(ocr_text),
                    image_count,
                )
            except Exception as exc:
                logger.warning("PDF page %d OCR failed: %s", page_no, exc)
    finally:
        doc.close()

    if not extras:
        return elements
    return list(elements) + extras


def _load_pymupdf_plain(file_path: str, source_id: str) -> list[RawElement]:
    import fitz

    elements: list[RawElement] = []
    doc = fitz.open(file_path)
    try:
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            text = _clean_pdf_text(page.get_text("text"))
            if not text:
                elements.append(
                    RawElement(
                        type=ElementType.TEXT,
                        content="",
                        page_number=page_idx + 1,
                        source_id=source_id,
                        metadata={"needs_ocr": True},
                    )
                )
                continue
            elements.append(
                RawElement(
                    type=ElementType.TEXT,
                    content=text,
                    page_number=page_idx + 1,
                    source_id=source_id,
                )
            )
    finally:
        doc.close()
    return [e for e in elements if e.content or e.metadata.get("needs_ocr")]

def layout_looks_hard(file_path: str, *, sample_pages: int = 6) -> bool:

    try:
        import fitz
    except ImportError:
        return False

    try:
        doc = fitz.open(file_path)
    except Exception:  
        return False

    try:
        n = len(doc)
        if n == 0:
            return True
        indices = list(range(min(n, sample_pages)))
        if n > sample_pages:

            mid = n // 2
            for i in (mid, n - 1):
                if i not in indices:
                    indices.append(i)

        emptyish = 0
        multi_col_votes = 0
        table_votes = 0

        for i in indices:
            page = doc[i]
            text = page.get_text("text").strip()
            chars = len(text)

            if chars < 80:
                emptyish += 1
                continue

            blocks = page.get_text("blocks")
            text_blocks = [b for b in blocks if len(b) >= 5 and str(b[4]).strip()]
            if len(text_blocks) >= 4:
                xs = sorted(float(b[0]) for b in text_blocks)

                if xs[-1] - xs[0] > page.rect.width * 0.35:
                    left = sum(1 for x in xs if x < page.rect.width * 0.4)
                    right = sum(1 for x in xs if x > page.rect.width * 0.45)
                    if left >= 2 and right >= 2:
                        multi_col_votes += 1

            if text.count("|") >= 8 or text.lower().count("\t") >= 6:
                table_votes += 1

        sampled = max(1, len(indices))
        if emptyish / sampled >= 0.4:
            logger.info("Hard layout: sparse/OCR-ish pages (%d/%d)", emptyish, sampled)
            return True
        if multi_col_votes >= 2 or (multi_col_votes >= 1 and sampled <= 3):
            logger.info("Hard layout: multi-column detected")
            return True
        if table_votes >= 2:
            logger.info("Hard layout: table-heavy pages")
            return True
        return False
    finally:
        doc.close()

def _docling_available() -> bool:
    try:
        import docling

        return True
    except ImportError:
        return False

class PDFLoader(DocumentLoader):

    def load(self, file_path: str, source_id: str) -> list[RawElement]:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(file_path)

        settings = get_settings()
        parser = (settings.pdf_parser or "auto").lower().strip()

        if parser == "auto":
            hard = layout_looks_hard(file_path)
            prefer_docling = hard and _docling_available()
            if prefer_docling:
                order = ["docling", "pymupdf4llm", "pymupdf"]
                logger.info("PDF auto -> Docling (hard layout)")
            else:
                order = ["pymupdf4llm", "docling", "pymupdf"]
                if hard:
                    logger.info(
                        "PDF auto -> pymupdf4llm (hard layout but Docling not installed; "
                        "pip install -e '.[advanced]')"
                    )
        else:
            order = [parser]
            for alt in ("pymupdf4llm", "docling", "pymupdf"):
                if alt not in order:
                    order.append(alt)

        last_err: Exception | None = None
        for name in order:
            try:
                if name == "docling":
                    if not _docling_available():
                        continue
                    elements = _load_docling(file_path, source_id)
                elif name == "pymupdf4llm":
                    elements = _load_pymupdf4llm(file_path, source_id)
                elif name == "pymupdf":
                    elements = _load_pymupdf_plain(file_path, source_id)
                else:
                    continue

                usable = [e for e in elements if e.content.strip()]
                if usable:
                    # Clean zero-width junk common in Word→PDF exports
                    for el in usable:
                        el.content = _clean_pdf_text(el.content)
                    usable = [e for e in usable if e.content]
                    usable = _enrich_sparse_pages_with_ocr(file_path, source_id, usable)
                    logger.info("PDF parsed with %s (%d elements)", name, len(usable))
                    return usable
                last_err = RuntimeError(f"{name} returned no text")
            except Exception as exc:
                logger.warning("PDF parser %s failed: %s", name, exc)
                last_err = exc

        if last_err:
            raise RuntimeError(f"All PDF parsers failed: {last_err}") from last_err
        return []
