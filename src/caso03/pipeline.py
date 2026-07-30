"""pipeline — orquesta los servicios: carga → decisión → reporte.

Rol equivalente al `cli/` de la referencia air_travel. Ejecutable:
    python -m caso03.pipeline            # los 150 casos
    python -m caso03.pipeline --limit 10 # subconjunto para demo rápida

Resiliencia: si un caso falla (error de red o JSON malformado del LLM), NO se
cae el batch — ese caso se marca ESCALAR con la traza del error (fail-safe:
ante la duda, revisión humana).
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    sys.stdout.reconfigure(encoding="utf-8")  # consola Windows cp1252 -> UTF-8
except Exception:
    pass

from caso03.domain.models import CompensationCase, Decision
from caso03.services.data_service import load_cases
from caso03.services.decision_service import DecisionService
from caso03.services.report_service import build_summary, build_dataframe, write_excel


def _safe_decide_llm(svc: DecisionService, case: CompensationCase) -> Decision:
    try:
        return svc.decide_llm(case)
    except Exception as exc:  # fail-safe: nunca perder un caso
        decision = svc.escalate_without_llm(case)
        decision.confianza = 0.0
        decision.override_guardrail = f"Fail-safe LLM: {type(exc).__name__}"
        return decision


def run(limit: int | None = None, max_workers: int = 3, use_llm: bool = True) -> None:
    cases = load_cases()
    if limit is not None:
        cases = cases[:limit]
    svc = DecisionService(use_llm=use_llm)

    # Fase 1 — determinísticos (sin LLM, instantáneo). No compiten por el rate limit.
    decisions: list[Decision] = []
    llm_cases: list[CompensationCase] = []
    for c in cases:
        d = svc.fast_decision(c)
        (decisions.append(d) if d is not None else llm_cases.append(c))
    print(f"Fase 1: {len(decisions)} determinísticos (sin LLM).")

    # Fase 2 — los ambiguos: al LLM, o al fallback ESCALAR si no hay presupuesto.
    if use_llm:
        print(f"Fase 2: {len(llm_cases)} casos al LLM (workers={max_workers})...")
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_safe_decide_llm, svc, c): c for c in llm_cases}
            for i, fut in enumerate(as_completed(futures), 1):
                decisions.append(fut.result())
                if i % 5 == 0 or i == len(llm_cases):
                    print(f"  LLM {i}/{len(llm_cases)}")
    else:
        print(f"Fase 2 (SIN LLM): {len(llm_cases)} ambiguos → ESCALAR (fallback).")
        decisions.extend(svc.escalate_without_llm(c) for c in llm_cases)

    df = build_dataframe(cases, decisions)
    path = write_excel(df)
    print(f"\nExcel generado: {path}")
    print("\nReparto de decisiones:")
    print(build_summary(df).to_string(index=False))


def main() -> None:
    ap = argparse.ArgumentParser(description="Agente de revisión de compensaciones — Caso 03")
    ap.add_argument("--limit", type=int, default=None, help="procesar solo N casos")
    ap.add_argument("--workers", type=int, default=3, help="llamadas concurrentes a Groq")
    ap.add_argument("--no-llm", action="store_true",
                    help="fallback sin LLM: los ambiguos se ESCALAN (sin consumir tokens)")
    args = ap.parse_args()
    run(limit=args.limit, max_workers=args.workers, use_llm=not args.no_llm)


if __name__ == "__main__":
    main()
