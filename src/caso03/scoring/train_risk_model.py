"""Ajusta el modelo de riesgo híbrido y exporta sus parámetros a JSON.

Eje de abuso = las 5 señales top por eta² (poder discriminante empírico):
    num_comp_90d, flags, tiempo_entrega, antiguedad, monto_comp_90d

Exporta (sin pickle, solo params) a src/caso03/scoring/artifacts/risk_model.json:
- orden de features, media/desvío del scaler, signo (orientación a "fraude"),
- pesos eta² normalizados,
- centroides KMeans (espacio estandarizado) y mapeo cluster→bucket,
- cortes del abuse_index para bucketing por score, y min/max para escala 0-1.

Reproducible (random_state fijo). Correr: python -m caso03.scoring.train_risk_model
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # consola Windows cp1252 -> UTF-8

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from caso03.services.data_service import load_cases  # noqa: E402

# Señales del eje de abuso y su orientación hacia "fraude" (+1 sube riesgo)
FEATURES = ["num_comp_90d", "flags", "tiempo_entrega", "antiguedad", "monto_comp_90d"]
SIGNS = {"num_comp_90d": +1, "flags": +1, "tiempo_entrega": -1,
         "antiguedad": -1, "monto_comp_90d": +1}
ARTIFACT = Path(__file__).resolve().parent / "artifacts" / "risk_model.json"


def _matrix() -> pd.DataFrame:
    rows = [
        dict(
            num_comp_90d=c.num_compensaciones_90d,
            flags=c.flags_fraude_previos,
            tiempo_entrega=c.tiempo_entrega_real_min,
            antiguedad=c.antiguedad_usuario_dias,
            monto_comp_90d=c.monto_compensado_90d_mxn,
        )
        for c in load_cases()
    ]
    return pd.DataFrame(rows)[FEATURES]


def _eta2(values: np.ndarray, labels: np.ndarray) -> float:
    grand = values.mean()
    ss_t = ((values - grand) ** 2).sum()
    ss_b = sum(len(values[labels == k]) * (values[labels == k].mean() - grand) ** 2
               for k in np.unique(labels))
    return float(ss_b / ss_t) if ss_t else 0.0


def main() -> None:
    df = _matrix()
    scaler = StandardScaler().fit(df.values)
    Z = scaler.transform(df.values)                      # estandarizado
    signs = np.array([SIGNS[f] for f in FEATURES])
    Z_oriented = Z * signs                               # + = dirección fraude

    km = KMeans(n_clusters=3, n_init=20, random_state=42).fit(Z)
    labels = km.labels_

    # pesos = eta² por feature, normalizados
    etas = np.array([_eta2(df[f].values.astype(float), labels) for f in FEATURES])
    weights = etas / etas.sum()

    abuse_index = Z_oriented @ weights                   # escalar por caso

    # mapeo cluster -> bucket según su abuse_index medio
    order = pd.Series(abuse_index).groupby(labels).mean().sort_values()
    bucket_names = ["LEGITIMO", "AMBIGUO", "FRAUDE"]
    cluster_to_bucket = {int(cl): bucket_names[i] for i, cl in enumerate(order.index)}

    # cortes del score = puntos medios entre abuse_index medios de clusters adyacentes
    means = order.values
    cuts = [float((means[0] + means[1]) / 2), float((means[1] + means[2]) / 2)]

    params = dict(
        features=FEATURES,
        signs={f: int(SIGNS[f]) for f in FEATURES},
        scaler_mean=scaler.mean_.tolist(),
        scaler_scale=scaler.scale_.tolist(),
        weights=weights.tolist(),
        eta2={f: float(e) for f, e in zip(FEATURES, etas)},
        centroids=km.cluster_centers_.tolist(),          # espacio estandarizado
        cluster_to_bucket={str(k): v for k, v in cluster_to_bucket.items()},
        score_cuts=cuts,
        abuse_index_min=float(abuse_index.min()),
        abuse_index_max=float(abuse_index.max()),
    )
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(params, indent=2, ensure_ascii=False), encoding="utf-8")

    # --- reporte legible ---
    print("Pesos eta² (normalizados):")
    for f, w in sorted(zip(FEATURES, weights), key=lambda x: -x[1]):
        print(f"  {f:16s} {w:.3f}")
    print("\nMapeo cluster→bucket:", cluster_to_bucket)
    print("Tamaños:", pd.Series(labels).map(cluster_to_bucket).value_counts().to_dict())
    print(f"Cortes de score (abuse_index): {cuts[0]:.3f} | {cuts[1]:.3f}")
    print(f"Rango abuse_index: [{abuse_index.min():.3f}, {abuse_index.max():.3f}]")
    print(f"\nArtefacto: {ARTIFACT}")


if __name__ == "__main__":
    main()
