

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from app.config import get_settings
from app.types import DocumentLoader, ElementType, RawElement

logger = logging.getLogger(__name__)

_VIDEO_EXT = {".mp4", ".webm", ".mov", ".mkv", ".avi", ".mpeg", ".mp3", ".wav", ".m4a"}
_MAX_GROQ_BYTES = 25 * 1024 * 1024  

def is_video_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() in _VIDEO_EXT

def _format_ts(seconds: float | None) -> str:
    if seconds is None:
        return "0:00"
    s = max(0, int(seconds))
    return f"{s // 60}:{s % 60:02d}"

def _transcribe_groq(path: Path, api_key: str) -> dict:

    size = path.stat().st_size
    if size > _MAX_GROQ_BYTES:
        raise RuntimeError(
            f"Video/audio file is {size // (1024*1024)}MB; Groq Whisper limit is ~25MB. "
            "Compress or trim the file."
        )
    model = "whisper-large-v3"
    with path.open("rb") as f:
        files = {"file": (path.name, f, "application/octet-stream")}
        data = {
            "model": model,
            "response_format": "verbose_json",
            "temperature": "0",
        }
        with httpx.Client(timeout=300.0) as client:
            resp = client.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                files=files,
                data=data,
            )
    if resp.status_code >= 400:
        raise RuntimeError(f"Groq Whisper error {resp.status_code}: {resp.text[:400]}")
    return resp.json()

def _segments_to_elements(payload: dict, source_id: str, filename: str) -> list[RawElement]:
    segments = payload.get("segments") or []
    elements: list[RawElement] = []

    if not segments and payload.get("text"):
        text = str(payload["text"]).strip()
        if text:
            elements.append(
                RawElement(
                    type=ElementType.TRANSCRIPT_SEGMENT,
                    content=text,
                    page_number=1,
                    source_id=source_id,
                    section_title=filename,
                    timestamp_start=0.0,
                    timestamp_end=None,
                    metadata={"filename": filename, "source": "whisper"},
                )
            )
        return elements

    buf: list[str] = []
    start: float | None = None
    end: float | None = None
    page = 1

    def flush() -> None:
        nonlocal buf, start, end, page
        text = " ".join(buf).strip()
        if not text:
            buf, start, end = [], None, None
            return
        label = f"{filename} @ {_format_ts(start)}"
        elements.append(
            RawElement(
                type=ElementType.TRANSCRIPT_SEGMENT,
                content=text,
                page_number=page,
                source_id=source_id,
                section_title=label,
                timestamp_start=start,
                timestamp_end=end,
                metadata={
                    "filename": filename,
                    "timestamp_start": start,
                    "timestamp_end": end,
                    "timestamp_label": _format_ts(start),
                    "source": "whisper",
                },
            )
        )
        page += 1
        buf, start, end = [], None, None

    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        s = float(seg.get("start") or 0)
        e = float(seg.get("end") or s)
        if start is None:
            start = s
        end = e
        buf.append(text)

        if (end - (start or 0)) >= 30 or sum(len(x) for x in buf) >= 500:
            flush()
    flush()
    return elements

class VideoLoader(DocumentLoader):

    def load(self, file_path: str, source_id: str) -> list[RawElement]:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(file_path)
        if not is_video_path(path):
            raise ValueError(f"Not a video/audio file: {path.suffix}")

        settings = get_settings()
        if not settings.groq_api_key:
            raise RuntimeError(
                "Video transcription requires GROQ_API_KEY (whisper-large-v3)."
            )

        logger.info("Transcribing %s via Groq Whisper…", path.name)
        payload = _transcribe_groq(path, settings.groq_api_key)
        elements = _segments_to_elements(payload, source_id, path.name)
        if not elements:
            raise RuntimeError("Whisper returned empty transcript — no speech detected?")
        logger.info("Video produced %d transcript segments", len(elements))
        return elements
