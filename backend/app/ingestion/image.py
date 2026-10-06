

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
import httpx

from app.types import DocumentLoader, ElementType, RawElement

logger = logging.getLogger(__name__)

_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

def is_image_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() in _IMAGE_EXT

def _ocr_space_api_sync(file_path: Path) -> str:
    url = "https://api.ocr.space/parse/image"
    payload = {
        "apikey": "helloworld",
        "language": "eng",
        "OCREngine": "2",
    }
    mime = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    
    with open(file_path, "rb") as f:
        files = {"file": (file_path.name, f, mime)}
        response = httpx.post(url, data=payload, files=files, timeout=30.0)
        
    response.raise_for_status()
    data = response.json()
    
    if data.get("IsErroredOnProcessing"):
        error_msg = data.get("ErrorMessage", ["Unknown OCR error"])[0]
        raise Exception(f"OCR.space API Error: {error_msg}")
        
    parsed_results = data.get("ParsedResults", [])
    if not parsed_results:
        return ""
        
    return parsed_results[0].get("ParsedText", "").strip()

class ImageLoader(DocumentLoader):

    def load(self, file_path: str, source_id: str) -> list[RawElement]:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(file_path)
        if not is_image_path(path):
            raise ValueError(f"Not an image: {path.suffix}")

        mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
        
        caption = _ocr_space_api_sync(path)
        if not caption:
            caption = f"Image file named '{path.name}'. No text detected by OCR API."

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
