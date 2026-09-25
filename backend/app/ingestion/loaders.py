

from __future__ import annotations

from pathlib import Path

from app.ingestion.image import ImageLoader, is_image_path
from app.ingestion.pdf import PDFLoader
from app.ingestion.text import TextLoader, is_text_path
from app.ingestion.video import VideoLoader, is_video_path
from app.ingestion.web import WebLoader
from app.types import DocumentLoader

def get_loader_for_path(file_path: str) -> DocumentLoader:
    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return PDFLoader()
    if suffix in {".url", ".html", ".htm"}:
        return WebLoader()
    if is_text_path(path):
        return TextLoader()
    if is_image_path(path):
        return ImageLoader()
    if is_video_path(path):
        return VideoLoader()
    raise ValueError(f"Unsupported file type: {suffix}")

