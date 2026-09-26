

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import AuthUser, get_current_user
from app.db.models import Document, EvalLog
from app.db.session import get_db
from app.eval.ragas_eval import run_eval_async, tune_relevance_threshold

router = APIRouter(prefix="/eval", tags=["Evaluations"])

_DEFAULT_DATASET = Path(__file__).resolve().parents[1] / "eval" / "test_qa_sets" / "example.json"

class RunEvalBody(BaseModel):
    document_ids: list[uuid.UUID] = Field(..., min_length=1)
    dataset_path: str | None = None

class TuneBody(BaseModel):
    document_ids: list[uuid.UUID] = Field(..., min_length=1)
    dataset_path: str | None = None
    thresholds: list[float] | None = None

@router.get("/summary")
async def eval_summary(
    db: AsyncSession = Depends(get_db),
    _user: AuthUser = Depends(get_current_user),
) -> dict[str, Any]:

    total = await db.scalar(select(func.count()).select_from(EvalLog)) or 0
    by_gate: dict[str, int] = {}
    rows = await db.execute(
        select(EvalLog.gate, func.count()).group_by(EvalLog.gate)
    )
    for gate, n in rows.all():
        by_gate[str(gate)] = int(n)

    recent_result = await db.execute(
        select(EvalLog).order_by(EvalLog.created_at.desc()).limit(20)
    )
    recent_logs = list(recent_result.scalars().all())

    rel_scores = [
        e.top_score
        for e in recent_logs
        if e.gate == "relevance" and e.top_score is not None
    ]
    suggested = None
    if rel_scores:
        rel_scores_sorted = sorted(rel_scores)
        mid = rel_scores_sorted[len(rel_scores_sorted) // 2]
        suggested = round(min(0.6, max(0.2, float(mid) + 0.05)), 3)

    return {
        "total_gate_events": int(total),
        "by_gate": by_gate,
        "suggested_relevance_threshold": suggested,
        "recent": [
            {
                "gate": e.gate,
                "question": e.question[:200],
                "top_score": e.top_score,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in recent_logs[:10]
        ],
    }

@router.post("/run")
async def run_eval(
    body: RunEvalBody,
    db: AsyncSession = Depends(get_db),
    _user: AuthUser = Depends(get_current_user),
) -> dict[str, Any]:
    ids = [str(d) for d in body.document_ids]
    uuids = list(body.document_ids)
    result = await db.execute(select(Document).where(Document.id.in_(uuids)))
    docs = list(result.scalars().all())
    if len(docs) != len(uuids):
        raise HTTPException(status_code=404, detail="One or more documents not found")
    not_ready = [d.filename for d in docs if d.status != "ready"]
    if not_ready:
        raise HTTPException(status_code=400, detail=f"Documents not ready: {not_ready}")

    names = {str(d.id): d.filename for d in docs}
    dataset = body.dataset_path or str(_DEFAULT_DATASET)
    if not Path(dataset).exists():
        raise HTTPException(status_code=400, detail=f"Dataset not found: {dataset}")

    return await run_eval_async(dataset, document_ids=ids, document_names=names)

@router.post("/tune")
async def tune_thresholds(
    body: TuneBody,
    db: AsyncSession = Depends(get_db),
    _user: AuthUser = Depends(get_current_user),
) -> dict[str, Any]:

    ids = [str(d) for d in body.document_ids]
    uuids = list(body.document_ids)
    result = await db.execute(select(Document).where(Document.id.in_(uuids)))
    docs = list(result.scalars().all())
    if len(docs) != len(uuids):
        raise HTTPException(status_code=404, detail="One or more documents not found")
    not_ready = [d.filename for d in docs if d.status != "ready"]
    if not_ready:
        raise HTTPException(status_code=400, detail=f"Documents not ready: {not_ready}")

    dataset = body.dataset_path or str(_DEFAULT_DATASET)
    if not Path(dataset).exists():
        raise HTTPException(status_code=400, detail=f"Dataset not found: {dataset}")

    data = json_load(dataset)
    return await tune_relevance_threshold(
        document_ids=ids,
        questions=list(data["pairs"]),
        candidates=body.thresholds,
    )

def json_load(path: str) -> dict[str, Any]:
    import json

    return json.loads(Path(path).read_text(encoding="utf-8"))
