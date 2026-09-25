

from __future__ import annotations

from app.types import RetrievedChunk

REFUSAL_MESSAGE = "I don't have enough context in the document to answer that."

SYSTEM_PROMPT = """You are a strictly grounded answering assistant. Answer the question using ONLY the provided context. If the context does not contain the answer, reply exactly with: "I don't have enough context in the document to answer that." Do not hallucinate or add external knowledge. Include inline citations like [1] or [2] when referencing the context."""

def format_context(chunks: list[RetrievedChunk]) -> str:
    parts: list[str] = []
    for i, rc in enumerate(chunks, start=1):
        page = rc.chunk.page_number
        section = rc.chunk.section_title
        header = f"[{i}]"
        if page is not None:
            header += f" page {page}"
        if section:
            header += f" — {section}"
        parts.append(f"{header}\n{rc.chunk.content}")
    return "\n\n".join(parts)

def build_messages(question: str, chunks: list[RetrievedChunk]) -> list[dict[str, str]]:
    context = format_context(chunks)
    user = f"Context:\n{context}\n\nQuestion: {question}"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
