

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.generation.grounding_check import relevance_gate
from app.generation.llm_client import complete_chat, has_any_llm_key
from app.generation.orchestrator import answer_question
from app.generation.prompt import REFUSAL_MESSAGE, format_context
from app.retrieval.hybrid_search import hybrid_search
from app.retrieval.reranker import rerank
from app.types import RetrievedChunk

logger = logging.getLogger(__name__)

_SCORE_RE = re.compile(r"([01](?:\.\d+)?)")

def _load_dataset(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if "pairs" not in data:
        raise ValueError("Dataset must contain a 'pairs' list")
    return data

async def _score_pair_llm(question: str, answer: str, context: str) -> dict[str, float]:

    if not has_any_llm_key() or answer.strip() == REFUSAL_MESSAGE:
        return {
            "faithfulness": 1.0 if answer.strip() == REFUSAL_MESSAGE else 0.5,
            "answer_relevance": 0.5,
        }

    prompt = f
    raw = await complete_chat(
        [
            {
                "role": "system",
                "content": "You are a strict RAG evaluator. Output only the two score lines.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
    )
    faith, rel = 0.5, 0.5
    for line in raw.splitlines():
        nums = _SCORE_RE.findall(line)
        if not nums:
            continue
        val = float(nums[0])
        val = max(0.0, min(1.0, val))
        upper = line.upper()
        if "FAITH" in upper:
            faith = val
        elif "RELEV" in upper:
            rel = val
    return {"faithfulness": faith, "answer_relevance": rel}

def _chunk_texts(ranked: list[RetrievedChunk], *, limit: int = 8) -> list[str]:
    out: list[str] = []
    for rc in ranked[:limit]:
        text = (rc.chunk.contextualized_content or rc.chunk.content or "").strip()
        if text:
            out.append(text[:2000])
    return out

async def evaluate_pair(
    *,
    question: str,
    document_ids: list[str],
    document_names: dict[str, str] | None = None,
    should_refuse: bool = False,
    ground_truth: str | None = None,
) -> dict[str, Any]:
    candidates = await hybrid_search(question, document_ids=document_ids, top_k=20)
    ranked = await rerank(question, candidates, top_n=8)
    result = await answer_question(
        question,
        document_ids=document_ids,
        document_names=document_names,
    )

    refused = bool(result.refused) or result.answer.strip() == REFUSAL_MESSAGE
    refusal_ok = refused == should_refuse
    contexts = _chunk_texts(ranked)
    context = format_context(ranked) if ranked else ""
    top_dense = ranked[0].dense_score if ranked else None
    top_rerank = ranked[0].rerank_score if ranked else None

    settings = get_settings()
    thr = settings.relevance_threshold
    if ranked:
        hits = sum(1 for c in ranked if (c.dense_score or 0) >= thr)
        context_precision = hits / len(ranked)
    else:
        context_precision = 0.0

    scores = {
        "faithfulness": 1.0 if refused and should_refuse else 0.0,
        "answer_relevance": 1.0 if refused and should_refuse else 0.0,
    }
    if not should_refuse and not refused:
        scores = await _score_pair_llm(question, result.answer, context)

        if ground_truth and ground_truth.strip():
            gt = ground_truth.lower()
            ans = result.answer.lower()
            overlap = sum(1 for w in gt.split() if len(w) > 3 and w in ans)
            if overlap >= 2:
                scores["answer_relevance"] = min(
                    1.0, scores["answer_relevance"] + 0.1
                )
    elif not should_refuse and refused:
        scores = {"faithfulness": 0.0, "answer_relevance": 0.0}

    return {
        "question": question,
        "should_refuse": should_refuse,
        "refused": refused,
        "refusal_accuracy": 1.0 if refusal_ok else 0.0,
        "retrieved_chunks": len(ranked),
        "contexts": contexts,
        "context_recall_proxy": 1.0 if ranked else 0.0,
        "context_precision": round(context_precision, 3),
        "top_dense_score": top_dense,
        "top_rerank_score": top_rerank,
        "faithfulness": scores["faithfulness"],
        "answer_relevance": scores["answer_relevance"],
        "answer": result.answer,
        "answer_preview": result.answer[:300],
        "ground_truth": ground_truth,
        "citations": [c.model_dump() for c in result.citations],
    }

async def run_eval_async(
    dataset_path: str,
    *,
    document_ids: list[str],
    document_names: dict[str, str] | None = None,
) -> dict[str, Any]:
    data = _load_dataset(dataset_path)
    rows: list[dict[str, Any]] = []
    for pair in data["pairs"]:
        row = await evaluate_pair(
            question=pair["question"],
            document_ids=document_ids,
            document_names=document_names,
            should_refuse=bool(pair.get("should_refuse")),
            ground_truth=pair.get("ground_truth"),
        )
        rows.append(row)

    def avg(key: str) -> float:
        if not rows:
            return 0.0
        return sum(float(r[key]) for r in rows) / len(rows)

    summary = {
        "dataset": str(dataset_path),
        "n": len(rows),
        "document_ids": document_ids,
        "refusal_accuracy": round(avg("refusal_accuracy"), 3),
        "faithfulness": round(avg("faithfulness"), 3),
        "answer_relevance": round(avg("answer_relevance"), 3),
        "context_recall_proxy": round(avg("context_recall_proxy"), 3),
        "context_precision": round(avg("context_precision"), 3),
        "current_relevance_threshold": get_settings().relevance_threshold,
        "rows": rows,
    }

    try:
        summary["ragas"] = await _try_ragas(rows)
    except Exception as exc:  
        summary["ragas"] = {"available": False, "detail": str(exc)[:200]}

    return summary

async def _try_ragas(rows: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        from datasets import Dataset
        from ragas import evaluate
        from ragas.metrics import answer_relevancy, faithfulness
    except ImportError:
        return {"available": False, "detail": "pip install -e '.[eval]' to enable RAGAS"}

    usable = [
        r
        for r in rows
        if not r["refused"] and r.get("contexts") and r.get("answer")
    ]
    if not usable:
        return {"available": True, "detail": "no non-refusal rows with contexts to score"}

    ds = Dataset.from_list(
        [
            {
                "question": r["question"],
                "answer": r.get("answer") or r["answer_preview"],
                "contexts": r["contexts"],
            }
            for r in usable
        ]
    )
    try:
        result = evaluate(ds, metrics=[faithfulness, answer_relevancy])
        scores = dict(result) if hasattr(result, "items") else {}

        if hasattr(result, "to_pandas"):
            pdf = result.to_pandas()
            scores = {
                "faithfulness": float(pdf["faithfulness"].mean())
                if "faithfulness" in pdf
                else None,
                "answer_relevancy": float(pdf["answer_relevancy"].mean())
                if "answer_relevancy" in pdf
                else None,
            }
        return {"available": True, "scores": scores, "n": len(usable)}
    except Exception as exc:  
        logger.warning("RAGAS evaluate failed: %s", exc)
        return {"available": True, "detail": f"RAGAS run failed: {exc}"[:240]}

async def tune_relevance_threshold(
    *,
    document_ids: list[str],
    questions: list[dict[str, Any]],
    candidates: list[float] | None = None,
) -> dict[str, Any]:

    thresholds = candidates or [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55]
    settings = get_settings()
    original = settings.relevance_threshold

    prepared: list[dict[str, Any]] = []
    for q in questions:
        ranked = await rerank(
            q["question"],
            await hybrid_search(q["question"], document_ids=document_ids, top_k=20),
            top_n=8,
        )
        prepared.append(
            {
                "should_refuse": bool(q.get("should_refuse")),
                "ranked": ranked,
                "top_dense": ranked[0].dense_score if ranked else None,
            }
        )

    sweeps: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None

    for thr in thresholds:
        settings.relevance_threshold = thr
        tp = fp = tn = fn = 0
        for row in prepared:
            gate = relevance_gate(row["ranked"])
            refused = gate is not None
            should = row["should_refuse"]
            if refused and should:
                tp += 1
            elif refused and not should:
                fp += 1
            elif not refused and not should:
                tn += 1
            else:
                fn += 1
        total = max(1, tp + fp + tn + fn)
        accuracy = (tp + tn) / total
        precision = tp / max(1, tp + fp)
        recall = tp / max(1, tp + fn)
        f1 = (2 * precision * recall / max(1e-9, precision + recall)) if (tp + fp + fn) else 0.0
        entry = {
            "threshold": thr,
            "refusal_accuracy": round(accuracy, 3),
            "refusal_precision": round(precision, 3),
            "refusal_recall": round(recall, 3),
            "f1": round(f1, 3),
            "tp": tp,
            "fp": fp,
            "tn": tn,
            "fn": fn,
        }
        sweeps.append(entry)
        if best is None or entry["f1"] > best["f1"] or (
            entry["f1"] == best["f1"] and entry["refusal_accuracy"] > best["refusal_accuracy"]
        ):
            best = entry

    settings.relevance_threshold = original
    return {
        "current_threshold": original,
        "recommended_threshold": best["threshold"] if best else original,
        "best": best,
        "sweep": sweeps,
        "n_questions": len(prepared),
        "note": "Set RELEVANCE_THRESHOLD in .env to the recommended value, then restart.",
    }

def run_ragas_eval(dataset_path: str, document_ids: list[str] | None = None) -> dict:

    if not document_ids:
        raise ValueError("document_ids required — pass ready document UUID(s)")
    return asyncio.run(
        run_eval_async(dataset_path, document_ids=document_ids, document_names=None)
    )

def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Run Grounded RAG eval set")
    parser.add_argument(
        "--dataset",
        default=str(Path(__file__).parent / "test_qa_sets" / "example.json"),
    )
    parser.add_argument(
        "--document-id",
        action="append",
        dest="document_ids",
        required=True,
        help="Ready document UUID (repeatable)",
    )
    parser.add_argument("--tune", action="store_true", help="Sweep relevance thresholds")
    parser.add_argument("--out", default="", help="Optional JSON output path")
    args = parser.parse_args()

    if args.tune:
        data = _load_dataset(args.dataset)
        result = asyncio.run(
            tune_relevance_threshold(
                document_ids=args.document_ids,
                questions=list(data["pairs"]),
            )
        )
    else:
        result = run_ragas_eval(args.dataset, document_ids=args.document_ids)

    text = json.dumps(result, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")

if __name__ == "__main__":
    main()
