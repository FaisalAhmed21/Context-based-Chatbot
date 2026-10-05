

from __future__ import annotations

import asyncio
import json as _json
import logging
from collections.abc import AsyncIterator

import httpx

from app.config import get_settings
from app.generation.prompt import REFUSAL_MESSAGE, build_messages, is_refusal_text
from app.types import Citation, GenerationResult, RetrievedChunk

logger = logging.getLogger(__name__)

import re

_RETRY_AFTER_RE = re.compile(r"try again in (\d+(?:\.\d+)?)s", re.IGNORECASE)


def _is_rate_limit_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "429" in msg or "rate limit" in msg or "quota" in msg


async def _sleep_for_rate_limit(exc: BaseException, attempt: int) -> None:
    m = _RETRY_AFTER_RE.search(str(exc))
    wait = float(m.group(1)) + 1.5 if m else min(5.0 * (2**attempt), 60.0)
    logger.warning("LLM rate limited; retrying in %.1fs", wait)
    await asyncio.sleep(wait)


def _extract_best_snippet(text: str, query: str) -> str:
    sentences = re.split(r'(?<=[.!?])\s+', text)
    if not sentences:
        return text.strip()[:160] + ("…" if len(text.strip()) > 160 else "")
        
    query_words = set(re.findall(r'\w+', query.lower()))
    
    best_score = -1
    best_sentence = sentences[0]
    
    for sentence in sentences:
        words = set(re.findall(r'\w+', sentence.lower()))
        score = len(query_words.intersection(words))
        if score > best_score:
            best_score = score
            best_sentence = sentence
            
    snippet = best_sentence.strip()
    if len(snippet) > 160:
        snippet = snippet[:160] + "…"
    return snippet

def _filter_citations_from_answer(answer: str, all_citations: list[Citation], chunks: list[RetrievedChunk]) -> list[Citation]:
    used = set()
    for m in re.finditer(r'\[(\d+)\]', answer):
        try:
            used.add(int(m.group(1)))
        except ValueError:
            pass
            
    if not used:
        return all_citations
        
    used_keys = set()
    for idx in used:
        if 1 <= idx <= len(chunks):
            rc = chunks[idx - 1]
            meta = rc.chunk.metadata or {}
            ts = meta.get("timestamp_start")
            try:
                ts_f = float(ts) if ts is not None else None
            except (TypeError, ValueError):
                ts_f = None
            used_keys.add((rc.chunk.document_id, rc.chunk.page_number, ts_f))
            
    return [c for c in all_citations if (c.document_id, c.page_number, c.timestamp_start) in used_keys]

def _citations(
    question: str,
    chunks: list[RetrievedChunk],
    document_names: dict[str, str],
) -> list[Citation]:

    seen: dict[tuple[str, int | None, float | None], Citation] = {}
    for rc in chunks:
        doc_id = rc.chunk.document_id
        page = rc.chunk.page_number
        meta = rc.chunk.metadata or {}
        ts = meta.get("timestamp_start")
        try:
            ts_f = float(ts) if ts is not None else None
        except (TypeError, ValueError):
            ts_f = None
        te = meta.get("timestamp_end")
        try:
            te_f = float(te) if te is not None else None
        except (TypeError, ValueError):
            te_f = None
        key = (doc_id, page, ts_f)
        if key in seen:
            continue
            
        snippet = _extract_best_snippet(rc.chunk.content, question)
        
        seen[key] = Citation(
            document_id=doc_id,
            document_name=document_names.get(doc_id),
            page_number=page,
            section_title=rc.chunk.section_title,
            chunk_id=rc.chunk.id,
            snippet=snippet or None,
            timestamp_start=ts_f,
            timestamp_end=te_f,
        )
    return list(seen.values())

def _provider_key(provider: str) -> str:
    settings = get_settings()
    p = provider.lower()
    if p == "groq":
        return settings.groq_api_key
    if p == "gemini":
        return settings.gemini_api_key
    if p == "openai":
        return settings.openai_api_key
    if p == "anthropic":
        return settings.anthropic_api_key
    return ""

async def _chat_groq(
    messages: list[dict[str, str]],
    model: str,
    api_key: str,
    *,
    temperature: float = 0.1,
) -> str:
    last_err: Exception | None = None
    for attempt in range(4):
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                },
            )
            if resp.status_code >= 400:
                err = RuntimeError(f"Groq error {resp.status_code}: {resp.text[:400]}")
                if resp.status_code == 429 or _is_rate_limit_error(err):
                    last_err = err
                    await _sleep_for_rate_limit(err, attempt)
                    continue
                raise err
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
    raise last_err or RuntimeError("Groq rate limit retries exhausted")

async def _chat_gemini(
    messages: list[dict[str, str]],
    model: str,
    api_key: str,
    *,
    temperature: float = 0.1,
) -> str:
    system = ""
    contents: list[dict] = []
    for m in messages:
        if m["role"] == "system":
            system = m["content"]
            continue
        role = "user" if m["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})

    body: dict = {
        "contents": contents,
        "generationConfig": {"temperature": temperature},
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )
    last_err: Exception | None = None
    for attempt in range(4):
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(url, params={"key": api_key}, json=body)
            if resp.status_code >= 400:
                err = RuntimeError(f"Gemini error {resp.status_code}: {resp.text[:400]}")
                if resp.status_code == 429 or _is_rate_limit_error(err):
                    last_err = err
                    await _sleep_for_rate_limit(err, attempt)
                    continue
                raise err
            data = resp.json()
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts).strip()
    raise last_err or RuntimeError("Gemini rate limit retries exhausted")

async def _call_provider(
    provider: str,
    model: str,
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.1,
) -> str:
    key = _provider_key(provider)
    if not key:
        raise RuntimeError(f"No API key configured for provider '{provider}'")
    p = provider.lower()
    if p == "groq":
        return await _chat_groq(messages, model, key, temperature=temperature)
    if p == "gemini":
        return await _chat_gemini(messages, model, key, temperature=temperature)
    raise RuntimeError(f"Unsupported LLM provider: {provider}")

async def _stream_groq(
    messages: list[dict[str, str]],
    model: str,
    api_key: str,
    *,
    temperature: float = 0.1,
) -> AsyncIterator[str]:

    async with httpx.AsyncClient(timeout=120.0) as client, client.stream(
        "POST",
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        },
    ) as resp:
        if resp.status_code >= 400:
            body = await resp.aread()
            raise RuntimeError(f"Groq stream error {resp.status_code}: {body.decode()[:400]}")
        buf = ""
        async for raw in resp.aiter_text():
            buf += raw
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if not line or not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    return
                try:
                    obj = _json.loads(payload)
                    delta = obj["choices"][0].get("delta") or {}
                    token = delta.get("content")
                    if token:
                        yield token
                except (KeyError, IndexError, _json.JSONDecodeError):
                    continue

async def _stream_gemini(
    messages: list[dict[str, str]],
    model: str,
    api_key: str,
    *,
    temperature: float = 0.1,
) -> AsyncIterator[str]:

    system = ""
    contents: list[dict] = []
    for m in messages:
        if m["role"] == "system":
            system = m["content"]
            continue
        role = "user" if m["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})

    body: dict = {
        "contents": contents,
        "generationConfig": {"temperature": temperature},
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:streamGenerateContent"
    )
    async with httpx.AsyncClient(timeout=120.0) as client, client.stream(
        "POST", url, params={"key": api_key, "alt": "sse"}, json=body,
    ) as resp:
        if resp.status_code >= 400:
            body_bytes = await resp.aread()
            raise RuntimeError(
                f"Gemini stream error {resp.status_code}: {body_bytes.decode()[:400]}"
            )
        buf = ""
        async for raw in resp.aiter_text():
            buf += raw
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if not line or not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload:
                    continue
                try:
                    obj = _json.loads(payload)
                    parts = obj.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                    for p in parts:
                        text = p.get("text")
                        if text:
                            yield text
                except (KeyError, IndexError, _json.JSONDecodeError):
                    continue

async def _stream_provider(
    provider: str,
    model: str,
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.1,
) -> AsyncIterator[str]:

    key = _provider_key(provider)
    if not key:
        raise RuntimeError(f"No API key configured for provider '{provider}'")
    p = provider.lower()
    if p == "groq":
        async for token in _stream_groq(messages, model, key, temperature=temperature):
            yield token
        return
    if p == "gemini":
        async for token in _stream_gemini(messages, model, key, temperature=temperature):
            yield token
        return

    text = await _call_provider(provider, model, messages, temperature=temperature)
    yield text

def has_any_llm_key() -> bool:
    settings = get_settings()
    return bool(_provider_key(settings.llm_provider) or _provider_key(settings.llm_fallback_provider))

async def complete_chat(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.1,
) -> str:

    settings = get_settings()
    errors: list[str] = []
    for provider, model in (
        (settings.llm_provider, settings.llm_model),
        (settings.llm_fallback_provider, settings.llm_fallback_model),
    ):
        if not _provider_key(provider):
            continue
        try:
            return await _call_provider(provider, model, messages, temperature=temperature)
        except Exception as exc:  
            logger.warning("LLM provider %s failed: %s", provider, exc)
            errors.append(f"{provider}: {exc}")
    raise RuntimeError(
        "All LLM providers failed. "
        + (" | ".join(errors) if errors else "Check GROQ_API_KEY / GEMINI_API_KEY.")
    )

async def generate_answer(
    question: str,
    chunks: list[RetrievedChunk],
    *,
    document_names: dict[str, str] | None = None,
    chat_history: list[dict[str, str]] | None = None,
) -> GenerationResult:
    settings = get_settings()
    document_names = document_names or {}
    citations = _citations(question, chunks, document_names)

    if not chunks:
        return GenerationResult(
            answer=REFUSAL_MESSAGE,
            refused=True,
            refusal_reason="relevance_gate",
        )

    primary = settings.llm_provider
    fallback = settings.llm_fallback_provider
    primary_model = settings.llm_model
    fallback_model = settings.llm_fallback_model

    if not _provider_key(primary) and not _provider_key(fallback):
        preview = chunks[0].chunk.content[:400]
        return GenerationResult(
            answer=(
                "[No LLM API key - set GROQ_API_KEY (recommended) or GEMINI_API_KEY]\n\n"
                f"Retrieved context (page {chunks[0].chunk.page_number}): {preview}"
            ),
            citations=citations,
            refused=False,
            confidence=chunks[0].score if chunks else None,
        )

    messages = build_messages(question, chunks, chat_history=chat_history)
    errors: list[str] = []
    tried: set[str] = set()

    for provider, model in ((primary, primary_model), (fallback, fallback_model)):
        key = f"{provider.lower()}::{model}"
        if key in tried or not _provider_key(provider):
            continue
        tried.add(key)
        try:
            answer = await _call_provider(provider, model, messages)
            refused = is_refusal_text(answer)
            return GenerationResult(
                answer=REFUSAL_MESSAGE if refused else answer,
                citations=[] if refused else _filter_citations_from_answer(answer, citations, chunks),
                refused=refused,
                refusal_reason="prompt" if refused else None,
                confidence=chunks[0].score if chunks else None,
            )
        except Exception as exc:
            logger.warning("LLM provider %s failed: %s", provider, exc)
            errors.append(f"{provider}: {exc}")

    return GenerationResult(
        answer=(
            "All LLM providers failed. "
            + (" | ".join(errors) if errors else "Check GROQ_API_KEY / GEMINI_API_KEY.")
        ),
        citations=[],
        refused=False,
        refusal_reason="provider_error",
    )

async def stream_generate_answer(
    question: str,
    chunks: list[RetrievedChunk],
    *,
    document_names: dict[str, str] | None = None,
    chat_history: list[dict[str, str]] | None = None,
) -> AsyncIterator[str | GenerationResult]:

    settings = get_settings()
    document_names = document_names or {}
    citations = _citations(question, chunks, document_names)

    if not chunks:
        yield GenerationResult(
            answer=REFUSAL_MESSAGE, refused=True, refusal_reason="relevance_gate",
        )
        return

    primary = settings.llm_provider
    fallback = settings.llm_fallback_provider

    if not _provider_key(primary) and not _provider_key(fallback):
        preview = chunks[0].chunk.content[:400]
        yield GenerationResult(
            answer=(
                "[No LLM API key - set GROQ_API_KEY (recommended) or GEMINI_API_KEY]\n\n"
                f"Retrieved context (page {chunks[0].chunk.page_number}): {preview}"
            ),
            citations=citations, refused=False,
            confidence=chunks[0].score if chunks else None,
        )
        return

    # When groundedness is on, avoid streaming a draft that may later be refused.
    if settings.groundedness_enabled:
        result = await generate_answer(
            question,
            chunks,
            document_names=document_names,
            chat_history=chat_history,
        )
        yield result
        return

    messages = build_messages(question, chunks, chat_history=chat_history)
    full_answer = ""
    streamed = False
    tried: set[str] = set()

    for provider, model in (
        (primary, settings.llm_model),
        (fallback, settings.llm_fallback_model),
    ):
        key = f"{provider.lower()}::{model}"
        if key in tried or not _provider_key(provider):
            continue
        tried.add(key)
        try:
            async for token in _stream_provider(provider, model, messages):
                full_answer += token
                yield token
            streamed = True
            break
        except Exception as exc:
            logger.warning("Stream LLM %s failed: %s", provider, exc)
            full_answer = ""

    if not streamed:
        result = await generate_answer(
            question,
            chunks,
            document_names=document_names,
            chat_history=chat_history,
        )
        yield result
        return

    refused = is_refusal_text(full_answer)
    yield GenerationResult(
        answer=REFUSAL_MESSAGE if refused else full_answer,
        citations=[] if refused else _filter_citations_from_answer(full_answer, citations, chunks),
        refused=refused,
        refusal_reason="prompt" if refused else None,
        confidence=chunks[0].score if chunks else None,
    )
