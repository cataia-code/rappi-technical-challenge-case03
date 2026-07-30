"""Fit the winning hybrid risk model and export its parameters to JSON.

Abuse axis = top 5 eta2 signals:
    num_comp_90d, flags, tiempo_entrega, antiguedad, monto_comp_90d

The winner from `experiments/scoring/model_selection.py` is Agglomerative(k=3)
over the numeric matrix. Since this algorithm has no native `predict()`, the
artifact exports centroid proxies and `risk_service` assigns new cases to the
nearest centroid in the same standardized space.

Exports JSON only, no pickle, to src/caso03/scoring/artifacts/risk_model.json.
Run with: python -m caso03.scoring.train_risk_model
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from caso03.services.data_service import load_cases  # noqa: E402

FEATURES = ["num_comp_90d", "flags", "tiempo_entrega", "antiguedad", "monto_comp_90d"]
SIGNS = {
    "num_comp_90d": +1,
    "flags": +1,
    "tiempo_entrega": -1,
    "antiguedad": -1,
    "monto_comp_90d": +1,
}
ARTIFACT = Path(__file__).resolve().parent / "artifacts" / "risk_model.json"
MODEL_SELECTION = ROOT / "data" / "processed" / "model_selection.json"


def _matrix() -> pd.DataFrame:
    rows = [
        {
            "num_comp_90d": c.num_compensaciones_90d,
            "flags": c.flags_fraude_previos,
            "tiempo_entrega": c.tiempo_entrega_real_min,
            "antiguedad": c.antiguedad_usuario_dias,
            "monto_comp_90d": c.monto_compensado_90d_mxn,
        }
        for c in load_cases()
    ]
    return pd.DataFrame(rows)[FEATURES]


def _eta2(values: np.ndarray, labels: np.ndarray) -> float:
    grand = values.mean()
    ss_total = ((values - grand) ** 2).sum()
    ss_between = sum(
        len(values[labels == label]) * (values[labels == label].mean() - grand) ** 2
        for label in np.unique(labels)
    )
    return float(ss_between / ss_total) if ss_total else 0.0


def main() -> None:
    df = _matrix()
    scaler = StandardScaler().fit(df.values)
    z = scaler.transform(df.values)
    labels = AgglomerativeClustering(n_clusters=3).fit_predict(z)
    centroids = np.vstack([z[labels == label].mean(axis=0) for label in sorted(set(labels))])

    signs = np.array([SIGNS[f] for f in FEATURES])
    oriented = z * signs
    etas = np.array([_eta2(df[f].values.astype(float), labels) for f in FEATURES])
    weights = etas / etas.sum()
    abuse_index = oriented @ weights

    order = pd.Series(abuse_index).groupby(labels).mean().sort_values()
    cluster_to_bucket = {
        int(cluster): bucket
        for cluster, bucket in zip(order.index, ["LEGITIMO", "AMBIGUO", "FRAUDE"])
    }
    means = order.values
    cuts = [float((means[0] + means[1]) / 2), float((means[1] + means[2]) / 2)]

    cases = load_cases()
    case_cluster = {case.caso_id: int(label) for case, label in zip(cases, labels)}
    case_bucket = {
        case_id: cluster_to_bucket[label] for case_id, label in case_cluster.items()
    }

    params = {
        "model_version": "2026-07-30.agglomerative-v1",
        "training_algorithm": "agglomerative",
        "inference_strategy": "nearest_centroid_proxy",
        "matrix": "numeric",
        "n_clusters": 3,
        "selection_source": str(MODEL_SELECTION.relative_to(ROOT)),
        "features": FEATURES,
        "signs": {feature: int(SIGNS[feature]) for feature in FEATURES},
        "scaler_mean": scaler.mean_.tolist(),
        "scaler_scale": scaler.scale_.tolist(),
        "weights": weights.tolist(),
        "eta2": {feature: float(eta) for feature, eta in zip(FEATURES, etas)},
        "centroids": centroids.tolist(),
        "cluster_to_bucket": {str(k): v for k, v in cluster_to_bucket.items()},
        "cluster_sizes": {
            str(int(label)): int((labels == label).sum()) for label in sorted(set(labels))
        },
        "training_case_cluster": {case_id: int(label) for case_id, label in case_cluster.items()},
        "training_case_bucket": case_bucket,
        "score_cuts": cuts,
        "abuse_index_min": float(abuse_index.min()),
        "abuse_index_max": float(abuse_index.max()),
    }
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(params, indent=2, ensure_ascii=False), encoding="utf-8")

    print("Modelo ganador: Agglomerative(k=3) + nearest-centroid proxy")
    print("Normalized eta2 weights:")
    for feature, weight in sorted(zip(FEATURES, weights), key=lambda item: -item[1]):
        print(f"  {feature:16s} {weight:.3f}")
    print("\nCluster->bucket map:", cluster_to_bucket)
    print("Bucket sizes:", pd.Series(labels).map(cluster_to_bucket).value_counts().to_dict())
    print(f"Score cuts (abuse_index): {cuts[0]:.3f} | {cuts[1]:.3f}")
    print(f"Rango abuse_index: [{abuse_index.min():.3f}, {abuse_index.max():.3f}]")
    print(f"\nArtefacto: {ARTIFACT}")


if __name__ == "__main__":
    main()
