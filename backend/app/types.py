

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

class ElementType(str, Enum):
    TEXT = "text"
    TABLE = "table"
    IMAGE = "image"
    TRANSCRIPT_SEGMENT = "transcript_segment"

class RawElement(BaseModel):

    type: ElementType
    content: str
    page_number: int | None = None
    source_id: str
    section_title: str | None = None
    bbox: list[float] | None = None  
    timestamp_start: float | None = None  
    timestamp_end: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

class Chunk(BaseModel):

    id: str | None = None
    document_id: str
    content: str
    contextualized_content: str | None = None  
    page_number: int | None = None
    section_title: str | None = None
    chunk_type: ElementType = ElementType.TEXT
    char_offset: int | None = None
    chunk_index: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)

class RetrievedChunk(BaseModel):
    chunk: Chunk
    score: float  
    dense_rank: int | None = None
    sparse_rank: int | None = None
    dense_score: float | None = None  
    rerank_score: float | None = None

class Citation(BaseModel):
    document_id: str
    document_name: str | None = None
    page_number: int | None = None
    section_title: str | None = None
    chunk_id: str | None = None
    snippet: str | None = None

    timestamp_start: float | None = None
    timestamp_end: float | None = None

class GenerationResult(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    refused: bool = False
    refusal_reason: str | None = None  
    confidence: float | None = None

class DocumentLoader(ABC):

    @abstractmethod
    def load(self, file_path: str, source_id: str) -> list[RawElement]:
        ...

class DocumentStatus(str, Enum):
    PENDING = "pending"
    PARSING = "parsing"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    READY = "ready"
    FAILED = "failed"

class DocumentOut(BaseModel):
    id: UUID
    filename: str
    status: DocumentStatus
    page_count: int | None = None
    chunk_count: int | None = None
    error_message: str | None = None
    content_type: str | None = None

class ChatMessageOut(BaseModel):
    id: UUID
    role: str
    content: str
    citations: list[Citation] = Field(default_factory=list)
    refused: bool = False
