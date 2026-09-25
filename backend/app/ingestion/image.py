

from __future__ import annotations

import base64
import logging
import mimetypes
from pathlib import Path

import httpx

from app.config import get_settings
from app.types import DocumentLoader, ElementType, RawElement

logger = logging.getLogger(__name__)

_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

def is_image_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() in _IMAGE_EXT

def _caption_gemini_sync(file_path: Path, mime: str, api_key: str) -> str:
    data = base64.b64encode(file_path.read_bytes()).decode("ascii")
    model = "gemini-3.6-flash"
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )
    body = {
        "contents": [
            {
                "parts": [
                    {
                        "text": (
                            "Describe this image thoroughly for a document search index. "
                            "Include visible text (OCR), objects, layout, and any data "
                            "that someone might ask about. Be factual; do not invent."
                        )
                    },
                    {"inline_data": {"mime_type": mime, "data": data}},
                ]
            }
        ],
        "generationConfig": {"temperature": 0.1},
    }
    with httpx.Client(timeout=120.0) as client:
        resp = client.post(url, params={"key": api_key}, json=body)
        if resp.status_code >= 400:
            raise RuntimeError(f"Gemini vision error {resp.status_code}: {resp.text[:300]}")
        parts = resp.json()["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts).strip()

def _caption_groq_sync(file_path: Path, mime: str, api_key: str) -> str:
    data = base64.b64encode(file_path.read_bytes()).decode("ascii")
    model = "meta-llama/llama-4-scout-17b-16e-instruct"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Describe this image thoroughly for a document search index. "
                            "Include visible text and key visual details. Be factual."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{data}"},
                    },
                ],
            }
        ],
        "temperature": 0.1,
    }
    with httpx.Client(timeout=120.0) as client:
        resp = client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"Groq vision error {resp.status_code}: {resp.text[:300]}")
        return resp.json()["choices"][0]["message"]["content"].strip()

def _fallback_caption(file_path: Path) -> str:
    return (
        f"Image file named '{file_path.name}'. "
        "No vision API caption available — set GEMINI_API_KEY (recommended) to index visual content."
    )

class ImageLoader(DocumentLoader):

    def load(self, file_path: str, source_id: str) -> list[RawElement]:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(file_path)
        if not is_image_path(path):
            raise ValueError(f"Not an image: {path.suffix}")

        mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
        settings = get_settings()
        caption = _fallback_caption(path)

        if settings.gemini_api_key:
            try:
                caption = _caption_gemini_sync(path, mime, settings.gemini_api_key)
            except Exception as exc:  
                logger.warning("Gemini image caption failed: %s", exc)
                if settings.groq_api_key:
                    try:
                        caption = _caption_groq_sync(path, mime, settings.groq_api_key)
                    except Exception as exc2:  
                        logger.warning("Groq image caption failed: %s", exc2)
        elif settings.groq_api_key:
            try:
                caption = _caption_groq_sync(path, mime, settings.groq_api_key)
            except Exception as exc:  
                logger.warning("Groq image caption failed: %s", exc)

        logger.info("Image captioned (%d chars) for %s", len(caption), path.name)
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
