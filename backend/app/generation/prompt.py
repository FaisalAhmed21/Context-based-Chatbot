

from __future__ import annotations

from app.types import RetrievedChunk

REFUSAL_MESSAGE = "I don't have enough context in the document to answer that."

_REFUSAL_MARKERS = (
    "don't have enough context",
    "do not have enough context",
    "doesn't have enough context",
    "does not have enough context",
    "insufficient context",
    "not enough information in the document",
    "not enough context in the document",
    "cannot find that in the document",
    "can't find that in the document",
    "no relevant information in the document",
    "the document does not contain",
    "the provided context does not",
)

SYSTEM_PROMPT = """You are a strictly document-grounded assistant.

Rules:
1. Answer ONLY using facts explicitly present in the Context block below.
2. Prior conversation is for resolving pronouns/references only — NEVER treat it as a source of facts.
3. Do NOT use world knowledge, general trivia, coding ability, live/current data, or personal guesses.
4. If Context does not contain the answer, reply exactly with: "I don't have enough context in the document to answer that."
5. When you answer from Context, include inline citations like [1] or [2].
6. Prefer short, direct answers that quote or closely paraphrase the relevant fact."""

def is_refusal_text(answer: str) -> bool:
    """True when the model refused (exact or common paraphrase)."""
    text = (answer or "").strip()
    if not text:
        return True
    if text == REFUSAL_MESSAGE:
        return True
    lower = text.lower()
    if lower == REFUSAL_MESSAGE.lower():
        return True
    # Short paraphrases of the refusal — not long answers that merely mention context.
    if len(text) <= 280 and any(m in lower for m in _REFUSAL_MARKERS):
        return True
    return False

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

def build_messages(
    question: str,
    chunks: list[RetrievedChunk],
    *,
    chat_history: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    context = format_context(chunks)
    history_block = ""
    if chat_history:
        # Prior turns only (caller should already exclude the current question).
        lines = []
        for m in chat_history[-4:]:
            role = m.get("role", "user")
            content = (m.get("content") or "").strip()
            if not content:
                continue
            lines.append(f"{role}: {content[:500]}")
        if lines:
            history_block = (
                "Prior conversation (coreference only; not evidence):\n"
                + "\n".join(lines)
                + "\n\n"
            )
    user = f"{history_block}Context:\n{context}\n\nQuestion: {question}"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
