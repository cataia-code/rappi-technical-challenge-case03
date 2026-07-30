"""Reporting service for CS-reviewable outputs.

Generates an Excel workbook with two sheets:
- 'Casos': original cases plus agent decision, confidence, dominant signals,
  summary, and audit traces.
- 'Resumen': decision distribution for quick calibration checks.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from caso03.config import OUTPUT_DIR
from caso03.domain.models import CompensationCase, Decision

_DECISION_COLUMNS = [
    "recomendacion_agente",
    "risk_bucket",
    "risk_score",
    "top_contribuyentes",
    "confianza",
    "senales_dominantes",
    "resumen_cs",
    "razonamiento",
    "override_guardrail",
    "modelo_usado",
]


def build_dataframe(
    cases: list[CompensationCase], decisions: list[Decision]
) -> pd.DataFrame:
    by_id = {d.caso_id: d for d in decisions}
    rows = []
    for c in cases:
        d = by_id[c.caso_id]
        row = c.model_dump()
        row.update(
            recomendacion_agente=d.recomendacion.value,
            risk_bucket=d.risk_bucket or "",
            risk_score=d.risk_score if d.risk_score is not None else "",
            top_contribuyentes="; ".join(d.top_contribuyentes),
            confianza=round(d.confianza, 2),
            senales_dominantes="; ".join(d.senales_dominantes),
            resumen_cs=d.resumen_cs,
            razonamiento=d.razonamiento or "",
            override_guardrail=d.override_guardrail or "",
            modelo_usado=d.modelo_usado or "",
        )
        rows.append(row)
    return pd.DataFrame(
        rows,
        columns=[*CompensationCase.model_fields.keys(), *_DECISION_COLUMNS],
    )


def build_summary(df: pd.DataFrame) -> pd.DataFrame:
    total = len(df)
    if total == 0 or "recomendacion_agente" not in df.columns:
        return pd.DataFrame(columns=["recomendacion", "casos", "porcentaje"])
    counts = df["recomendacion_agente"].value_counts()
    summary = (
        counts.rename_axis("recomendacion")
        .reset_index(name="casos")
        .assign(porcentaje=lambda x: (x["casos"] / total * 100).round(1))
    )
    return summary


def write_excel(df: pd.DataFrame, path: Path | None = None) -> Path:
    path = path or (OUTPUT_DIR / "salida_150.xlsx")
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        df.to_excel(xl, sheet_name="Casos", index=False)
        build_summary(df).to_excel(xl, sheet_name="Resumen", index=False)
    return path
