

from __future__ import annotations

import logging
from typing import Any, TypedDict

from app.config import get_settings
from app.types import GenerationResult

logger = logging.getLogger(__name__)

class AgentState(TypedDict, total=False):
    question: str
    document_ids: list[str] | None
    document_names: dict[str, str] | None
    chat_history: list[dict[str, str]] | None
    result: GenerationResult | None

def langgraph_available() -> bool:
    try:
        import langgraph  

        return True
    except ImportError:
        return False

async def answer_with_langgraph(
    question: str,
    *,
    document_ids: list[str] | None = None,
    document_names: dict[str, str] | None = None,
    chat_history: list[dict[str, str]] | None = None,
) -> GenerationResult:

    from app.generation.agentic import answer_question_agentic

    settings = get_settings()
    if not settings.use_langgraph or not langgraph_available():
        return await answer_question_agentic(
            question,
            document_ids=document_ids,
            document_names=document_names,
            chat_history=chat_history,
        )

    from langgraph.graph import END, StateGraph

    async def run_agentic(state: AgentState) -> dict[str, Any]:
        result = await answer_question_agentic(
            state["question"],
            document_ids=state.get("document_ids"),
            document_names=state.get("document_names"),
            chat_history=state.get("chat_history"),
        )
        return {"result": result}

    graph = StateGraph(AgentState)
    graph.add_node("agentic_rag", run_agentic)
    graph.set_entry_point("agentic_rag")
    graph.add_edge("agentic_rag", END)
    app = graph.compile()

    out = await app.ainvoke(
        {
            "question": question,
            "document_ids": document_ids,
            "document_names": document_names,
            "chat_history": chat_history,
        }
    )
    result = out.get("result")
    if result is None:

        return await answer_question_agentic(
            question,
            document_ids=document_ids,
            document_names=document_names,
            chat_history=chat_history,
        )
    return result
