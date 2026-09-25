

from __future__ import annotations

from pathlib import Path

from app.types import DocumentLoader, ElementType, RawElement

_TEXT_EXT = {".txt", ".md", ".markdown", ".csv", ".json", ".log"}

def is_text_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() in _TEXT_EXT

class TextLoader(DocumentLoader):
    def load(self, file_path: str, source_id: str) -> list[RawElement]:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(file_path)
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        if not text:
            raise RuntimeError("Text file is empty")

        blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
        if not blocks:
            blocks = [text]

        elements: list[RawElement] = []
        for i, block in enumerate(blocks, start=1):
            elements.append(
                RawElement(
                    type=ElementType.TEXT,
                    content=block,
                    page_number=1,
                    source_id=source_id,
                    section_title=path.name if i == 1 else f"{path.name} · part {i}",
                    metadata={"filename": path.name, "source": "text"},
                )
            )
        return elements
