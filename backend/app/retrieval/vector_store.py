

from __future__ import annotations

import logging
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from app.config import get_settings

logger = logging.getLogger(__name__)

@lru_cache
def get_qdrant() -> QdrantClient:
    settings = get_settings()
    if settings.qdrant_url.strip():
        logger.info("Qdrant client → %s", settings.qdrant_url)
        kwargs: dict[str, Any] = {"url": settings.qdrant_url, "timeout": 30}
        if settings.qdrant_api_key.strip():
            kwargs["api_key"] = settings.qdrant_api_key.strip()
        return QdrantClient(**kwargs)
    path = Path(settings.qdrant_path)
    path.mkdir(parents=True, exist_ok=True)
    logger.info("Qdrant local path → %s", path.resolve())
    return QdrantClient(path=str(path))

def ensure_collection(dim: int | None = None) -> None:
    settings = get_settings()
    client = get_qdrant()
    dim = dim or settings.embedding_dim
    name = settings.qdrant_collection
    if client.collection_exists(name):
        try:
            info = client.get_collection(name)
            existing_dim = info.config.params.vectors.size
            if existing_dim == dim:
                return
            logger.warning("Recreating collection %s (dim %s -> %s)", name, existing_dim, dim)
            client.delete_collection(name)
        except Exception as e:
            logger.warning("Failed to check collection info: %s", e)
            return

    client.create_collection(
        collection_name=name,
        vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
    )

    if settings.qdrant_url.strip():
        client.create_payload_index(
            collection_name=name,
            field_name="document_id",
            field_schema=qm.PayloadSchemaType.KEYWORD,
        )

def upsert_chunks(
    *,
    points: list[dict[str, Any]],
) -> None:

    if not points:
        return
    settings = get_settings()
    ensure_collection(len(points[0]["vector"]))
    client = get_qdrant()
    client.upsert(
        collection_name=settings.qdrant_collection,
        points=[
            qm.PointStruct(
                id=p["id"],
                vector=p["vector"],
                payload=p["payload"],
            )
            for p in points
        ],
    )

def delete_by_document(document_id: str) -> None:
    settings = get_settings()
    client = get_qdrant()
    if not client.collection_exists(settings.qdrant_collection):
        return
    client.delete(
        collection_name=settings.qdrant_collection,
        points_selector=qm.FilterSelector(
            filter=qm.Filter(
                must=[
                    qm.FieldCondition(
                        key="document_id",
                        match=qm.MatchValue(value=document_id),
                    )
                ]
            )
        ),
    )

def search_dense(
    query_vector: list[float],
    *,
    document_ids: list[str] | None = None,
    top_k: int = 20,
) -> list[qm.ScoredPoint]:
    settings = get_settings()
    client = get_qdrant()
    if not client.collection_exists(settings.qdrant_collection):
        return []

    query_filter = None
    if document_ids:
        query_filter = qm.Filter(
            must=[
                qm.FieldCondition(
                    key="document_id",
                    match=qm.MatchAny(any=document_ids),
                )
            ]
        )

    try:
        result = client.query_points(
            collection_name=settings.qdrant_collection,
            query=query_vector,
            query_filter=query_filter,
            limit=top_k,
            with_payload=True,
        )
        return list(result.points)
    except AttributeError:
        return client.search(
            collection_name=settings.qdrant_collection,
            query_vector=query_vector,
            query_filter=query_filter,
            limit=top_k,
            with_payload=True,
        )

def new_point_id() -> str:
    return str(uuid.uuid4())
