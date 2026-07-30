"""Calcula métricas del agente contra una muestra etiquetada manualmente.

Entrada esperada: data/labels/manual_30.csv con `caso_id` y `etiqueta_manual`
completada como APROBAR, RECHAZAR o ESCALAR. Si solo existe la plantilla, primero
hay que copiarla a manual_30.csv y completarla con criterio humano.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from caso03.services.data_service import load_cases  # noqa: E402
from caso03.services.decision_service import DecisionService  # noqa: E402

LABELS = ROOT / "data" / "labels" / "manual_30.csv"
VALID_LABELS = {"APROBAR", "RECHAZAR", "ESCALAR"}


def _agent_decisions() -> pd.DataFrame:
    svc = DecisionService(use_llm=False)
    rows = []
    for case in load_cases():
        decision = svc.decide(case)
        rows.append(
            {
                "caso_id": case.caso_id,
                "ciudad": case.ciudad,
                "vertical": case.vertical,
                "recomendacion_agente": decision.recomendacion.value,
                "risk_bucket": decision.risk_bucket,
                "risk_score": decision.risk_score,
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    if not LABELS.exists():
        raise SystemExit(
            "No existe data/labels/manual_30.csv. Generá la plantilla con "
            "python analysis/prepare_manual_label_sample.py, copiala a manual_30.csv "
            "y completá etiqueta_manual."
        )

    labels = pd.read_csv(LABELS)
    labels["etiqueta_manual"] = labels["etiqueta_manual"].astype(str).str.strip().str.upper()
    invalid = sorted(set(labels["etiqueta_manual"]) - VALID_LABELS)
    if invalid:
        raise SystemExit(f"Etiquetas inválidas: {invalid}. Usá {sorted(VALID_LABELS)}.")

    df = _agent_decisions().merge(
        labels[["caso_id", "etiqueta_manual"]],
        on="caso_id",
        how="inner",
    )
    if df.empty:
        raise SystemExit("No hay casos etiquetados que crucen con el dataset.")

    reject_mask = df["recomendacion_agente"] == "RECHAZAR"
    reject_precision = (
        (df.loc[reject_mask, "etiqueta_manual"] == "RECHAZAR").mean()
        if reject_mask.any()
        else float("nan")
    )
    false_rejects = df[
        (df["recomendacion_agente"] == "RECHAZAR")
        & (df["etiqueta_manual"] == "APROBAR")
    ]

    print(f"Casos evaluados: {len(df)}")
    print(f"Exact match: {(df['recomendacion_agente'] == df['etiqueta_manual']).mean():.2%}")
    print(f"Precisión RECHAZAR: {reject_precision:.2%}")
    print(f"Falsos rechazos: {len(false_rejects)}")
    print(f"Tasa ESCALAR agente: {(df['recomendacion_agente'] == 'ESCALAR').mean():.2%}")
    print("\nMatriz agente vs manual:")
    print(pd.crosstab(df["recomendacion_agente"], df["etiqueta_manual"]).to_string())
    print("\nReparto por ciudad:")
    print(pd.crosstab(df["ciudad"], df["recomendacion_agente"]).to_string())
    print("\nReparto por vertical:")
    print(pd.crosstab(df["vertical"], df["recomendacion_agente"]).to_string())


if __name__ == "__main__":
    main()
