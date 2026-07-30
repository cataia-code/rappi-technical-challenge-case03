"""Análisis no supervisado: dejar que los datos digan qué señales pesan y dónde cortar.

No hay etiquetas (recomendacion_agente vacío), pero el reto afirma que los 150 casos
están en 3 buckets latentes (fraude / legítimo / ambiguo). Estrategia:

1. Construir la matriz de señales.
2. Ver correlaciones (redundancia entre señales).
3. Recuperar los 3 buckets con KMeans (features estandarizadas).
4. Rankear cada señal por su poder discriminante (eta² = varianza entre-cluster /
   varianza total) → "qué pesa más", derivado de los datos, no asertado.
5. Leer los centroides por cluster → de ahí salen los umbrales.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from caso03.services.data_service import load_cases  # noqa: E402
from caso03.services.feature_service import compute_features  # noqa: E402

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
    """Proporción de varianza explicada por el cluster (0..1). Poder discriminante."""
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
    print("1) CORRELACIÓN entre señales (Pearson)")
    print("=" * 70)
    print(df.corr(numeric_only=True).round(2).to_string())

    X = StandardScaler().fit_transform(df.values)
    km = KMeans(n_clusters=3, n_init=20, random_state=42).fit(X)
    labels = km.labels_
    df_lab = df.assign(cluster=labels)

    print("\n" + "=" * 70)
    print(f"2) KMeans k=3 | silhouette={silhouette_score(X, labels):.3f} | tamaños:")
    print("=" * 70)
    print(df_lab.cluster.value_counts().sort_index().to_string())

    print("\n" + "=" * 70)
    print("3) PERFIL de cada cluster (media por señal)")
    print("=" * 70)
    profile = df_lab.groupby("cluster")[feats].mean().round(2)
    print(profile.T.to_string())

    print("\n" + "=" * 70)
    print("4) QUÉ PESA MÁS — poder discriminante (eta²), rankeado")
    print("=" * 70)
    etas = {f: eta_squared(df[f].values.astype(float), labels) for f in feats}
    rank = pd.Series(etas).sort_values(ascending=False).round(3)
    print(rank.to_string())

    print("\n" + "=" * 70)
    print("5) UMBRALES sugeridos por los centroides (top señales)")
    print("=" * 70)
    for f in rank.head(5).index:
        vals = profile[f].sort_values()
        print(f"  {f:20s} centroides por cluster (ordenados): {vals.to_dict()}")


if __name__ == "__main__":
    main()
