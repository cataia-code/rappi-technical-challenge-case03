"""Clustering model selection for the risk backbone.

Compares numeric and numeric+categorical matrices across several unsupervised
algorithms. The challenge defines 3 latent buckets, so the selection rule
prefers solutions with 3 effective clusters; within those, the highest
silhouette wins. If no valid 3-cluster solution exists, the global highest
silhouette wins.

Output:
- data/processed/model_selection.json: comparative metrics, winner, and compact
  chart data for the web (bars, PCA 2D, eta2 weights).

Run from the repository root:
    ./.venv/Scripts/python.exe experiments/scoring/model_selection.py
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering, DBSCAN, KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import (
    calinski_harabasz_score,
    davies_bouldin_score,
    silhouette_score,
)
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from features.feature_service import normalize_key  # noqa: E402
from services.data_service import load_cases  # noqa: E402

NUMERIC_FEATURES = [
    "num_comp_90d",
    "flags",
    "tiempo_entrega",
    "antiguedad",
    "monto_comp_90d",
]
SIGNS = {
    "num_comp_90d": +1,
    "flags": +1,
    "tiempo_entrega": -1,
    "antiguedad": -1,
    "monto_comp_90d": +1,
}
BUCKETS = ["LEGITIMO", "AMBIGUO", "FRAUDE"]
OUT = ROOT / "data" / "processed" / "model_selection.json"


@dataclass(frozen=True)
class MatrixSpec:
    name: str
    X: np.ndarray
    feature_names: list[str]
    numeric_df: pd.DataFrame


def _case_frame() -> pd.DataFrame:
    rows = []
    for c in load_cases():
        rows.append(
            {
                "caso_id": c.caso_id,
                "num_comp_90d": c.num_compensaciones_90d,
                "flags": c.flags_fraude_previos,
                "tiempo_entrega": c.tiempo_entrega_real_min,
                "antiguedad": c.antiguedad_usuario_dias,
                "monto_comp_90d": c.monto_compensado_90d_mxn,
                "vertical": normalize_key(c.vertical),
                "motivo_reclamo": normalize_key(c.motivo_reclamo),
                "entrega_confirmada_gps": normalize_key(c.entrega_confirmada_gps),
            }
        )
    return pd.DataFrame(rows)


def _matrices(df: pd.DataFrame) -> list[MatrixSpec]:
    numeric = df[NUMERIC_FEATURES].astype(float)
    numeric_scaled = StandardScaler().fit_transform(numeric.values)
    specs = [
        MatrixSpec(
            name="numeric",
            X=numeric_scaled,
            feature_names=NUMERIC_FEATURES,
            numeric_df=numeric,
        )
    ]

    categoricals = pd.get_dummies(
        df[["vertical", "motivo_reclamo", "entrega_confirmada_gps"]],
        prefix=["vertical", "motivo", "gps"],
        dtype=float,
    )
    mixed = np.hstack([numeric_scaled, categoricals.values])
    specs.append(
        MatrixSpec(
            name="numeric_categorical",
            X=mixed,
            feature_names=[*NUMERIC_FEATURES, *categoricals.columns.tolist()],
            numeric_df=numeric,
        )
    )
    return specs


def _valid_labels(labels: np.ndarray) -> bool:
    unique = set(labels.tolist())
    return 1 < len(unique) < len(labels)


def _cluster_count(labels: np.ndarray) -> int:
    return len({int(label) for label in labels if int(label) != -1})


def _metrics(X: np.ndarray, labels: np.ndarray) -> dict:
    if not _valid_labels(labels):
        return {
            "silhouette": None,
            "davies_bouldin": None,
            "calinski_harabasz": None,
        }
    return {
        "silhouette": float(silhouette_score(X, labels)),
        "davies_bouldin": float(davies_bouldin_score(X, labels)),
        "calinski_harabasz": float(calinski_harabasz_score(X, labels)),
    }


def _eta2(values: np.ndarray, labels: np.ndarray) -> float:
    grand = values.mean()
    ss_total = ((values - grand) ** 2).sum()
    ss_between = sum(
        len(values[labels == label]) * (values[labels == label].mean() - grand) ** 2
        for label in np.unique(labels)
    )
    return float(ss_between / ss_total) if ss_total else 0.0


def _abuse_index(numeric_df: pd.DataFrame, labels: np.ndarray) -> tuple[np.ndarray, dict]:
    scaler = StandardScaler().fit(numeric_df.values)
    Z = scaler.transform(numeric_df.values)
    signs = np.array([SIGNS[f] for f in NUMERIC_FEATURES])
    oriented = Z * signs
    etas = np.array(
        [_eta2(numeric_df[f].values.astype(float), labels) for f in NUMERIC_FEATURES]
    )
    weights = etas / etas.sum() if etas.sum() else np.ones(len(etas)) / len(etas)
    return oriented @ weights, {
        feature: float(weight)
        for feature, weight in sorted(
            zip(NUMERIC_FEATURES, weights), key=lambda item: -item[1]
        )
    }


def _bucket_map(numeric_df: pd.DataFrame, labels: np.ndarray) -> dict[str, str]:
    abuse, _weights = _abuse_index(numeric_df, labels)
    means = pd.Series(abuse).groupby(labels).mean().sort_values()
    non_noise = [int(label) for label in means.index if int(label) != -1]
    if not non_noise:
        return {}
    names = BUCKETS if len(non_noise) == 3 else [
        f"CLUSTER_{i}" for i in range(len(non_noise))
    ]
    return {str(label): names[i] for i, label in enumerate(non_noise)}


def _rows_for_matrix(spec: MatrixSpec) -> Iterable[dict]:
    for k in range(2, 7):
        labels = KMeans(n_clusters=k, n_init=20, random_state=42).fit_predict(spec.X)
        yield _result_row(spec, "kmeans", k, labels)

        labels = GaussianMixture(n_components=k, random_state=42).fit_predict(spec.X)
        yield _result_row(spec, "gaussian_mixture", k, labels)

        labels = AgglomerativeClustering(n_clusters=k).fit_predict(spec.X)
        yield _result_row(spec, "agglomerative", k, labels)

    for eps in np.round(np.arange(0.5, 3.1, 0.25), 2):
        labels = DBSCAN(eps=float(eps), min_samples=4).fit_predict(spec.X)
        yield _result_row(spec, "dbscan", None, labels, eps=float(eps))


def _result_row(
    spec: MatrixSpec,
    algorithm: str,
    k: int | None,
    labels: np.ndarray,
    eps: float | None = None,
) -> dict:
    metrics = _metrics(spec.X, labels)
    return {
        "matrix": spec.name,
        "algorithm": algorithm,
        "k": k,
        "eps": eps,
        "effective_clusters": _cluster_count(labels),
        "noise_points": int((labels == -1).sum()),
        "cluster_sizes": {
            str(int(label)): int(count)
            for label, count in zip(*np.unique(labels, return_counts=True))
        },
        "bucket_map": _bucket_map(spec.numeric_df, labels),
        "labels": [int(label) for label in labels],
        **metrics,
    }


def _choose_winner(rows: list[dict]) -> dict:
    scored = [row for row in rows if row["silhouette"] is not None]
    preferred = [row for row in scored if row["effective_clusters"] == 3]
    candidates = preferred or scored
    if not candidates:
        raise RuntimeError("No model produced valid clusters.")
    return max(candidates, key=lambda row: row["silhouette"])


def _chart_payload(df: pd.DataFrame, spec: MatrixSpec, winner: dict) -> dict:
    labels = np.array(winner["labels"])
    coords = PCA(n_components=2, random_state=42).fit_transform(spec.X)
    _abuse, weights = _abuse_index(spec.numeric_df, labels)
    return {
        "winner_weights": weights,
        "pca": [
            {
                "caso_id": row.caso_id,
                "x": float(x),
                "y": float(y),
                "cluster": int(label),
                "bucket": winner["bucket_map"].get(str(int(label)), "NOISE"),
            }
            for row, (x, y), label in zip(df.itertuples(index=False), coords, labels)
        ],
        "silhouette_by_k": [
            {
                "matrix": row["matrix"],
                "algorithm": row["algorithm"],
                "k": row["k"],
                "silhouette": row["silhouette"],
            }
            for row in winner["all_rows"]
            if row["k"] is not None and row["silhouette"] is not None
        ],
    }


def main() -> None:
    df = _case_frame()
    specs = _matrices(df)
    rows: list[dict] = []
    for spec in specs:
        rows.extend(_rows_for_matrix(spec))

    winner = _choose_winner(rows)
    winner_spec = next(spec for spec in specs if spec.name == winner["matrix"])
    payload_winner = {k: v for k, v in winner.items() if k != "labels"}
    charts = _chart_payload(df, winner_spec, {**winner, "all_rows": rows})
    payload = {
        "selection_rule": (
            "Prefer 3 effective clusters because the challenge defines 3 latent "
            "buckets; break ties by highest silhouette. If no valid 3-cluster "
            "solution exists, use the global highest silhouette."
        ),
        "winner": payload_winner,
        "results": [{k: v for k, v in row.items() if k != "labels"} for row in rows],
        "charts": charts,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    table = pd.DataFrame(payload["results"]).sort_values(
        ["effective_clusters", "silhouette"], ascending=[True, False]
    )
    print("Top models with 3 effective clusters:")
    cols = [
        "matrix",
        "algorithm",
        "k",
        "eps",
        "effective_clusters",
        "silhouette",
        "davies_bouldin",
        "calinski_harabasz",
    ]
    print(
        table[table["effective_clusters"] == 3][cols]
        .sort_values("silhouette", ascending=False)
        .head(10)
        .to_string(index=False)
    )
    print("\nWinner:")
    print(json.dumps(payload_winner, indent=2, ensure_ascii=False))
    print(f"\nJSON: {OUT}")


if __name__ == "__main__":
    main()
