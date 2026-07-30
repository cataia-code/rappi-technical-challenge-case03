"""Genera una plantilla de 30 casos para etiquetado humano.

La muestra toma 10 casos por bucket de riesgo (LEGITIMO, AMBIGUO, FRAUDE), repartidos
por score para cubrir casos fáciles y de frontera. La columna `etiqueta_manual` queda
vacía a propósito: debe completarla un revisor humano con APROBAR/RECHAZAR/ESCALAR.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from caso03.services.data_service import load_cases  # noqa: E402
from caso03.services.risk_service import assess  # noqa: E402

OUTPUT = ROOT / "data" / "labels" / "manual_30_template.csv"


def _even_sample(group: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    group = group.sort_values("risk_score").reset_index(drop=True)
    if len(group) <= n:
        return group
    positions = [round(i * (len(group) - 1) / (n - 1)) for i in range(n)]
    return group.iloc[positions]


def main() -> None:
    rows = []
    for case in load_cases():
        risk = assess(case)
        rows.append(
            {
                "caso_id": case.caso_id,
                "risk_bucket": risk.resolved_bucket,
                "risk_score": risk.risk_score,
                "top_contribuyentes": "; ".join(risk.top_contribuyentes),
                "ciudad": case.ciudad,
                "vertical": case.vertical,
                "valor_orden_mxn": case.valor_orden_mxn,
                "compensacion_solicitada_mxn": case.compensacion_solicitada_mxn,
                "num_compensaciones_90d": case.num_compensaciones_90d,
                "monto_compensado_90d_mxn": case.monto_compensado_90d_mxn,
                "entrega_confirmada_gps": case.entrega_confirmada_gps,
                "tiempo_entrega_real_min": case.tiempo_entrega_real_min,
                "flags_fraude_previos": case.flags_fraude_previos,
                "motivo_reclamo": case.motivo_reclamo,
                "descripcion_reclamo": case.descripcion_reclamo,
                "etiqueta_manual": "",
                "notas_revisor": "",
            }
        )

    df = pd.DataFrame(rows)
    sample = pd.concat(
        [_even_sample(group) for _, group in df.groupby("risk_bucket")],
        ignore_index=True,
    )
    sample = sample.sort_values(["risk_bucket", "risk_score", "caso_id"])
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    sample.to_csv(OUTPUT, index=False, encoding="utf-8-sig")
    print(f"Plantilla generada: {OUTPUT}")
    print(sample["risk_bucket"].value_counts().to_string())


if __name__ == "__main__":
    main()
