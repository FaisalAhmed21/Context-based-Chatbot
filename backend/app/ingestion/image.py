

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path

import pytesseract
from PIL import Image

from app.types import DocumentLoader, ElementType, RawElement

logger = logging.getLogger(__name__)

_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

def is_image_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() in _IMAGE_EXT

def _ocr_tesseract_sync(file_path: Path) -> str:
    img = Image.open(file_path)
    text = pytesseract.image_to_string(img)
    return text.strip()

def _fallback_caption(file_path: Path) -> str:
    return (
        f"Image file named '{file_path.name}'. "
        "No local OCR text available — ensure Tesseract OCR is installed on the system."
    )

class ImageLoader(DocumentLoader):

    def load(self, file_path: str, source_id: str) -> list[RawElement]:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(file_path)
        if not is_image_path(path):
            raise ValueError(f"Not an image: {path.suffix}")

        mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
        
        try:
            caption = _ocr_tesseract_sync(path)
            if not caption:
                caption = f"Image file named '{path.name}'. No text detected by Tesseract OCR."
        except Exception as exc:
            logger.warning("Tesseract OCR failed: %s", exc)
            caption = _fallback_caption(path)

        logger.info("Image OCR'd (%d chars) for %s", len(caption), path.name)
        return [
            RawElement(
                type=ElementType.IMAGE,
                content=caption,
                page_number=1,
                source_id=source_id,
                section_title=path.name,
                metadata={
                    "mime": mime,
                    "filename": path.name,
                    "bytes": path.stat().st_size,
                },
            )
        ]
