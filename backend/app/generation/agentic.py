

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from app.config import get_settings
from app.generation.grounding_check import (
    groundedness_check,
    log_gate_failure,
    relevance_gate,
)
from app.generation.llm_client import generate_answer, stream_generate_answer
from app.retrieval.hybrid_search import hybrid_search
from app.retrieval.query_transform import (
    hyde_document,
    looks_multihop,
    refine_retrieval_query,
    rewrite_query,
)
from app.retrieval.reranker import rerank
from app.types import GenerationResult, RetrievedChunk

logger = logging.getLogger(__name__)

def _chunk_key(rc: RetrievedChunk) -> str:
    return rc.chunk.id or f"{rc.chunk.document_id}:{rc.chunk.chunk_index}"

def _merge_ranked(
    primary: list[RetrievedChunk],
    secondary: list[RetrievedChunk],
    *,
    top_n: int = 8,
) -> list[RetrievedChunk]:
    seen: dict[str, RetrievedChunk] = {}
    for rc in primary + secondary:
        kid = _chunk_key(rc)
        if kid not in seen:
            seen[kid] = rc
        else:

            cur = seen[kid]
            cur_score = cur.rerank_score or cur.dense_score or cur.score
            new_score = rc.rerank_score or rc.dense_score or rc.score
            if new_score is not None and (cur_score is None or new_score > cur_score):
                seen[kid] = rc
    merged = list(seen.values())
    merged.sort(
        key=lambda c: (
            c.rerank_score
            if c.rerank_score is not None
            else (c.dense_score if c.dense_score is not None else c.score)
        ),
        reverse=True,
    )
    return merged[:top_n]

async def _retrieve(
    query: str,
    *,
    document_ids: list[str] | None,
    top_k: int = 20,
    top_n: int = 8,
) -> list[RetrievedChunk]:
    settings = get_settings()
    search_q = query
    if settings.hyde_enabled:
        hypo = await hyde_document(query)
        if hypo:
            search_q = hypo
    candidates = await hybrid_search(search_q, document_ids=document_ids, top_k=top_k)
    return await rerank(query, candidates, top_n=top_n)

async def _run_retrieval_loop(
    question: str,
    *,
    document_ids: list[str] | None = None,
    chat_history: list[dict[str, str]] | None = None,
) -> tuple[list[RetrievedChunk], GenerationResult | None]:

    settings = get_settings()
    q = await rewrite_query(question, chat_history=chat_history)
    ranked = await _retrieve(q, document_ids=document_ids)

    if settings.graphrag_enabled:
        try:
            from app.retrieval.graph_rag import expand_via_graph

            graph_hits = await expand_via_graph(
                q, ranked, document_ids=document_ids, limit=4
            )
            if graph_hits:
                ranked = _merge_ranked(ranked, graph_hits)
                logger.info("GraphRAG expanded +%d chunks", len(graph_hits))
        except Exception:  
            logger.debug("GraphRAG expand skipped", exc_info=True)

    gate = relevance_gate(ranked)
    multihop = looks_multihop(question)
    do_second = settings.agentic_enabled and (
        multihop or gate is not None or (ranked and (ranked[0].dense_score or 0) < settings.relevance_threshold + 0.05)
    )

    agentic_hops = 1
    if do_second:
        follow = await refine_retrieval_query(question, ranked)
        if follow and follow.lower() != q.lower():
            logger.info("Agentic second hop query: %s", follow[:120])
            ranked2 = await _retrieve(follow, document_ids=document_ids)
            ranked = _merge_ranked(ranked, ranked2)
            agentic_hops = 2
            gate = relevance_gate(ranked)

    if gate is not None:
        await log_gate_failure(
            question=question,
            gate="relevance",
            top_score=ranked[0].dense_score if ranked else 0.0,
        )
        gate.refusal_reason = gate.refusal_reason or "relevance_gate"
        return ranked, gate

    return ranked, None

async def answer_question_agentic(
    question: str,
    *,
    document_ids: list[str] | None = None,
    document_names: dict[str, str] | None = None,
    chat_history: list[dict[str, str]] | None = None,
) -> GenerationResult:
    settings = get_settings()
    ranked, gate = await _run_retrieval_loop(
        question, document_ids=document_ids, chat_history=chat_history,
    )
    if gate is not None:
        return gate

    result = await generate_answer(question, ranked, document_names=document_names)
    if result.refused:
        return result

    bad = await groundedness_check(result.answer, ranked, question=question)
    if bad is not None and settings.agentic_enabled:
        follow = await refine_retrieval_query(
            f"{question}\nPrior answer was insufficiently grounded.",
            ranked,
        )
        if follow:
            ranked2 = await _retrieve(follow, document_ids=document_ids)
            ranked = _merge_ranked(ranked, ranked2)
            result = await generate_answer(question, ranked, document_names=document_names)
            if result.refused:
                return result
            bad = await groundedness_check(result.answer, ranked, question=question)

    if bad is not None:
        return bad

    if result.confidence is None and ranked:
        result.confidence = ranked[0].dense_score or ranked[0].score
    return result

async def stream_answer_question_agentic(
    question: str,
    *,
    document_ids: list[str] | None = None,
    document_names: dict[str, str] | None = None,
    chat_history: list[dict[str, str]] | None = None,
) -> AsyncIterator[str | GenerationResult]:

    settings = get_settings()
    ranked, gate = await _run_retrieval_loop(
        question, document_ids=document_ids, chat_history=chat_history,
    )
    if gate is not None:
        yield gate
        return

    full_answer = ""
    final_result: GenerationResult | None = None

    async for item in stream_generate_answer(
        question, ranked, document_names=document_names,
    ):
        if isinstance(item, str):
            full_answer += item
            yield item  
        elif isinstance(item, GenerationResult):
            final_result = item

    if final_result is None:

        final_result = GenerationResult(
            answer=full_answer, refused=False,
        )

    if final_result.refused:
        yield final_result
        return

    bad = await groundedness_check(final_result.answer, ranked, question=question)
    if bad is not None and settings.agentic_enabled:

        follow = await refine_retrieval_query(
            f"{question}\nPrior answer was insufficiently grounded.",
            ranked,
        )
        if follow:
            ranked2 = await _retrieve(follow, document_ids=document_ids)
            ranked = _merge_ranked(ranked, ranked2)
            corrected = await generate_answer(question, ranked, document_names=document_names)
            if not corrected.refused:
                bad = await groundedness_check(corrected.answer, ranked, question=question)
                if bad is None:
                    final_result = corrected

    if bad is not None:
        yield bad
        return

    if final_result.confidence is None and ranked:
        final_result.confidence = ranked[0].dense_score or ranked[0].score
    yield final_result
