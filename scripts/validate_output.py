"""Sanity-checks data/output/salida_150.xlsx before a demo or presentation.

Run: python scripts/validate_output.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
XLSX = ROOT / "data" / "output" / "salida_150.xlsx"

VALID_RECOMMENDATIONS = {"APROBAR", "RECHAZAR", "ESCALAR"}
REQUIRED_COLUMNS = [
    "caso_id", "recomendacion_agente", "risk_bucket", "risk_score",
    "resumen_cs", "senales_dominantes", "pasos_recomendados",
]


def main() -> int:
    if not XLSX.exists():
        print(f"ERROR: {XLSX} does not exist. Run scripts/run_pipeline.ps1 first.")
        return 1

    df = pd.read_excel(XLSX, sheet_name="Casos")
    problems: list[str] = []

    if len(df) != 150:
        problems.append(f"expected 150 cases, found {len(df)}")

    missing_cols = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_cols:
        problems.append(f"missing columns: {missing_cols}")
    else:
        blank_rec = df["recomendacion_agente"].isna() | (df["recomendacion_agente"] == "")
        if blank_rec.any():
            problems.append(f"{blank_rec.sum()} cases have no recomendacion_agente")

        invalid_rec = ~df["recomendacion_agente"].isin(VALID_RECOMMENDATIONS)
        if invalid_rec.any():
            problems.append(f"{invalid_rec.sum()} cases have an invalid recomendacion_agente")

        blank_score = df["risk_score"].isna()
        if blank_score.any():
            problems.append(f"{blank_score.sum()} cases have no risk_score")

        escalar = df["recomendacion_agente"] == "ESCALAR"
        pasos = df["pasos_recomendados"].fillna("").astype(str).str.strip()
        escalar_sin_pasos = escalar & (pasos == "")
        if escalar_sin_pasos.any():
            problems.append(f"{escalar_sin_pasos.sum()} ESCALAR cases have no pasos_recomendados")

        counts = df["recomendacion_agente"].value_counts()
        esc_pct = counts.get("ESCALAR", 0) / len(df) * 100
        print(f"Distribution: {counts.to_dict()} (ESCALAR = {esc_pct:.1f}%)")
        if esc_pct > 45:
            problems.append(f"ESCALAR rate {esc_pct:.1f}% is above the 35% saturation alarm")

    if problems:
        print("\nFAILED:")
        for p in problems:
            print(f"  - {p}")
        return 1

    print("OK: 150 cases, all recommendations valid, every ESCALAR has next steps.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
