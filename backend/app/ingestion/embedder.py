

from __future__ import annotations

import logging
from functools import lru_cache

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

@lru_cache
def _fastembed_model():
    from fastembed import TextEmbedding

    settings = get_settings()
    logger.info("Loading fastembed model %s …", settings.embedding_model)
    return TextEmbedding(model_name=settings.embedding_model)

async def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    settings = get_settings()
    provider = settings.embedding_provider.lower()

    if provider == "gemini":
        return await _embed_gemini(texts)
    if provider == "fastembed":
        return await _embed_fastembed(texts)
    raise ValueError(f"Unsupported embedding_provider: {provider}")

async def embed_query(text: str) -> list[float]:
    vectors = await embed_texts([text])
    return vectors[0]

async def _embed_fastembed(texts: list[str]) -> list[list[float]]:
    import asyncio

    def _run() -> list[list[float]]:
        model = _fastembed_model()
        return [vec.tolist() for vec in model.embed(texts)]

    return await asyncio.to_thread(_run)

async def _embed_gemini(texts: list[str]) -> list[list[float]]:
    settings = get_settings()
    if not settings.gemini_api_key:
        raise RuntimeError("EMBEDDING_PROVIDER=gemini requires GEMINI_API_KEY")

    model = settings.embedding_model
    if model.startswith("BAAI/") or "bge" in model.lower():
        model = "text-embedding-004"

    out: list[list[float]] = []
    async with httpx.AsyncClient(timeout=60.0) as client:
        for text in texts:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:embedContent"
            )
            resp = await client.post(
                url,
                params={"key": settings.gemini_api_key},
                json={
                    "model": f"models/{model}",
                    "content": {"parts": [{"text": text}]},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            out.append(data["embedding"]["values"])
    return out
