"""Batch pipeline: load cases, make decisions, and write reports.

Run with:
    python -m pipeline
    python -m pipeline --limit 10

Resilience: if one case fails because of network errors or malformed LLM JSON,
the batch does not fail. That case is marked ESCALAR with an audit trace.
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from domain.models import CompensationCase, Decision
from services.data_service import load_cases
from services.decision_service import DecisionService
from services.report_service import build_summary, build_dataframe, write_excel


def _safe_decide_llm(svc: DecisionService, case: CompensationCase) -> Decision:
    try:
        return svc.decide_llm(case)
    except Exception as exc:  # fail-safe: never lose a case
        decision = svc.escalate_without_llm(case)
        decision.confianza = 0.0
        decision.override_guardrail = f"Fail-safe LLM: {type(exc).__name__}"
        return decision


def run(limit: int | None = None, max_workers: int = 3, use_llm: bool = True) -> None:
    cases = load_cases()
    if limit is not None:
        cases = cases[:limit]
    svc = DecisionService(use_llm=use_llm)

    # Phase 1: deterministic cases do not consume LLM rate limits.
    decisions: list[Decision] = []
    llm_cases: list[CompensationCase] = []
    for c in cases:
        d = svc.fast_decision(c)
        (decisions.append(d) if d is not None else llm_cases.append(c))
    print(f"Phase 1: {len(decisions)} deterministic cases (no LLM).")

    # Phase 2: ambiguous cases go to the LLM, or to ESCALAR in no-LLM mode.
    if use_llm:
        print(f"Phase 2: {len(llm_cases)} cases routed to LLM (workers={max_workers})...")
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_safe_decide_llm, svc, c): c for c in llm_cases}
            for i, fut in enumerate(as_completed(futures), 1):
                decisions.append(fut.result())
                if i % 5 == 0 or i == len(llm_cases):
                    print(f"  LLM {i}/{len(llm_cases)}")
    else:
        print(f"Phase 2 (NO LLM): {len(llm_cases)} ambiguous cases -> ESCALAR fallback.")
        decisions.extend(svc.escalate_without_llm(c) for c in llm_cases)

    df = build_dataframe(cases, decisions)
    path = write_excel(df)
    print(f"\nExcel generated: {path}")
    print("\nDecision distribution:")
    print(build_summary(df).to_string(index=False))


def main() -> None:
    ap = argparse.ArgumentParser(description="Compensation review agent - Case 03")
    ap.add_argument("--limit", type=int, default=None, help="process only N cases")
    ap.add_argument("--workers", type=int, default=3, help="concurrent LLM calls")
    ap.add_argument("--no-llm", action="store_true",
                    help="no-LLM fallback: ambiguous cases are escalated")
    args = ap.parse_args()
    run(limit=args.limit, max_workers=args.workers, use_llm=not args.no_llm)


if __name__ == "__main__":
    main()
