"""FastAPI entry point for the compensation decision agent.

Run from the repository root:
    uvicorn apps.api.main:app --reload
"""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from domain.models import CompensationCase, Decision  # noqa: E402
from services.data_service import load_cases  # noqa: E402
from services.decision_service import DecisionService  # noqa: E402

app = FastAPI(
    title="Rappi Compensation Agent API",
    version="0.1.0",
    description="HTTP boundary for scoring and decisioning compensation cases.",
)


@lru_cache(maxsize=1)
def _cases_by_id() -> dict[str, CompensationCase]:
    return {case.caso_id: case for case in load_cases()}


def _service(use_llm: bool) -> DecisionService:
    return DecisionService(use_llm=use_llm)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/decisions", response_model=Decision)
def review_payload(
    case: CompensationCase,
    use_llm: bool = Query(
        default=False,
        description="Use the LLM for ambiguous cases. Defaults to false for deterministic runs.",
    ),
) -> Decision:
    try:
        return _service(use_llm=use_llm).decide(case)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Decision engine failed: {exc}") from exc


@app.post("/cases/{case_id}/decisions", response_model=Decision)
def review_dataset_case(
    case_id: str,
    use_llm: bool = Query(
        default=False,
        description="Use the LLM for ambiguous cases. Defaults to false for deterministic runs.",
    ),
) -> Decision:
    case = _cases_by_id().get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"case_id '{case_id}' not found")
    return review_payload(case, use_llm=use_llm)
