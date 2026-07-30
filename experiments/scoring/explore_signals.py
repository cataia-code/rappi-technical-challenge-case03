"""Unsupervised analysis: let the data determine signal weight and thresholds.

There are no labels, but the challenge states that the 150 cases contain three
latent buckets: fraud, legitimate, and ambiguous. Strategy:

1. Build the signal matrix.
2. Inspect correlations and signal redundancy.
3. Recover 3 buckets with KMeans over standardized features.
4. Rank signals by discriminative power (eta2 = between-cluster variance /
   total variance).
5. Read cluster centroids to infer thresholds.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from services.data_service import load_cases  # noqa: E402
from features.feature_service import compute_features  # noqa: E402

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 30)


def build_matrix() -> pd.DataFrame:
    rows = []
    for c in load_cases():
        f = compute_features(c)
        rows.append(
            dict(
                caso_id=c.caso_id,
                antiguedad=c.antiguedad_usuario_dias,
                num_comp_90d=c.num_compensaciones_90d,
                monto_comp_90d=c.monto_compensado_90d_mxn,
                flags=c.flags_fraude_previos,
                ratio_comp_orden=f.ratio_comp_orden,
                tiempo_entrega=c.tiempo_entrega_real_min,
                valor_orden=c.valor_orden_mxn,
                gps_contradice=int(f.gps_contradice_reclamo),
                gps_corrobora=int(f.gps_corrobora_reclamo),
                gps_no_concluyente=int(f.gps_no_concluyente),
            )
        )
    return pd.DataFrame(rows).set_index("caso_id")


def eta_squared(values: np.ndarray, labels: np.ndarray) -> float:
    """Share of variance explained by clusters (0..1)."""
    grand = values.mean()
    ss_total = ((values - grand) ** 2).sum()
    ss_between = sum(
        len(values[labels == k]) * (values[labels == k].mean() - grand) ** 2
        for k in np.unique(labels)
    )
    return float(ss_between / ss_total) if ss_total else 0.0


def main() -> None:
    df = build_matrix()
    feats = df.columns.tolist()

    print("=" * 70)
    print("1) Signal correlation (Pearson)")
    print("=" * 70)
    print(df.corr(numeric_only=True).round(2).to_string())

    X = StandardScaler().fit_transform(df.values)
    km = KMeans(n_clusters=3, n_init=20, random_state=42).fit(X)
    labels = km.labels_
    df_lab = df.assign(cluster=labels)

    print("\n" + "=" * 70)
    print(f"2) KMeans k=3 | silhouette={silhouette_score(X, labels):.3f} | sizes:")
    print("=" * 70)
    print(df_lab.cluster.value_counts().sort_index().to_string())

    print("\n" + "=" * 70)
    print("3) Cluster profile (feature means)")
    print("=" * 70)
    profile = df_lab.groupby("cluster")[feats].mean().round(2)
    print(profile.T.to_string())

    print("\n" + "=" * 70)
    print("4) Ranked discriminative power (eta2)")
    print("=" * 70)
    etas = {f: eta_squared(df[f].values.astype(float), labels) for f in feats}
    rank = pd.Series(etas).sort_values(ascending=False).round(3)
    print(rank.to_string())

    print("\n" + "=" * 70)
    print("5) Centroid-suggested thresholds (top signals)")
    print("=" * 70)
    for f in rank.head(5).index:
        vals = profile[f].sort_values()
        print(f"  {f:20s} ordered cluster centroids: {vals.to_dict()}")


if __name__ == "__main__":
    main()
