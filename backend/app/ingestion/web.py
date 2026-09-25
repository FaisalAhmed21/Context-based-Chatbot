

from __future__ import annotations

import logging
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

from app.types import DocumentLoader, ElementType, RawElement

logger = logging.getLogger(__name__)

_SKIP_TAGS = {
    "script",
    "style",
    "noscript",
    "svg",
    "iframe",
    "nav",
    "footer",
    "header",
}

class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0
        self.title: str | None = None
        self._in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:  
        t = tag.lower()
        if t in _SKIP_TAGS:
            self._skip_depth += 1
        if t == "title":
            self._in_title = True
        if t in {"p", "br", "div", "li", "h1", "h2", "h3", "h4", "tr"} and self._skip_depth == 0:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if t == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title = (self.title or "") + data
            return
        if self._skip_depth == 0:
            self._parts.append(data)

    def text(self) -> str:
        raw = "".join(self._parts)
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()

def fetch_url_text(url: str, *, timeout: float = 30.0) -> tuple[str, str]:

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http(s) URLs are supported")
    with httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": "GroundedRAG/1.0 (+local)"},
    ) as client:
        resp = client.get(url)
    if resp.status_code >= 400:
        raise RuntimeError(f"Failed to fetch URL ({resp.status_code})")
    ctype = (resp.headers.get("content-type") or "").lower()
    body = resp.text
    if "html" in ctype or body.lstrip().lower().startswith("<!doctype") or "<html" in body[:500].lower():
        parser = _TextExtractor()
        parser.feed(body)
        title = (parser.title or parsed.netloc or url).strip()
        text = parser.text()
    else:
        title = parsed.path.rsplit("/", 1)[-1] or url
        text = body.strip()
    if not text or len(text) < 40:
        raise RuntimeError("Page had little extractable text (may be JS-rendered)")
    return title, text

class WebLoader(DocumentLoader):

    def load(self, file_path: str, source_id: str) -> list[RawElement]:
        from pathlib import Path

        path = Path(file_path)
        raw = path.read_text(encoding="utf-8", errors="replace").strip()

        if path.suffix.lower() == ".url" or raw.startswith("http"):
            lines = raw.splitlines()
            url = lines[0].strip()
            cached = "\n".join(lines[1:]).strip()
            if cached and len(cached) >= 40:
                title = urlparse(url).netloc or url
                return _text_to_elements(cached, source_id, title, url)
            title, text = fetch_url_text(url)
            return _text_to_elements(text, source_id, title, url)
        parser = _TextExtractor()
        parser.feed(raw)
        title = (parser.title or path.name).strip()
        text = parser.text() or raw
        return _text_to_elements(text, source_id, title, None)

def _text_to_elements(
    text: str,
    source_id: str,
    title: str,
    url: str | None,
) -> list[RawElement]:
    blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
    if not blocks:
        blocks = [text]

    blocks = blocks[:80]
    elements: list[RawElement] = []
    for i, block in enumerate(blocks, start=1):
        elements.append(
            RawElement(
                type=ElementType.TEXT,
                content=block[:4000],
                page_number=1,
                source_id=source_id,
                section_title=title if i == 1 else f"{title} · §{i}",
                metadata={"title": title, "url": url, "source": "web"},
            )
        )
    logger.info("Web page '%s' → %d blocks", title, len(elements))
    return elements
