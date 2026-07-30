"""risk_service — Capa 0 data-driven: score de riesgo híbrido (score + clustering).

Carga los parámetros ajustados (risk_model.json) y evalúa cada caso con SOLO numpy:
- risk_score 0-1 (interpretable), derivado del eje de abuso ponderado por eta².
- score_bucket: bucket según los cortes del score.
- cluster_bucket: bucket por centroide KMeans más cercano (partición nativa).
- agreement: si ambos coinciden. El DESACUERDO es la señal más honesta de
  ambigüedad → se resuelve como AMBIGUO (escalar).
- top_contribuyentes: las señales que más empujan el riesgo (el "por qué" para CS).

Ajustar el modelo: python -m caso03.scoring.train_risk_model
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from caso03.domain.models import CompensationCase

_ARTIFACT = Path(__file__).resolve().parent / "artifacts" / "risk_model.json"

# Frase legible por señal según la dirección de su contribución al riesgo
_PHRASES = {
    "num_comp_90d": ("muchas compensaciones en 90d", "pocas compensaciones en 90d"),
    "flags": ("flags de fraude previos", "sin flags de fraude"),
    "tiempo_entrega": ("entrega atípicamente rápida", "tiempo de entrega normal/alto"),
    "antiguedad": ("cuenta nueva", "cuenta con antigüedad"),
    "monto_comp_90d": ("monto compensado acumulado alto", "monto compensado bajo"),
}


@dataclass(frozen=True)
class RiskAssessment:
    risk_score: float           # 0-1 (mayor = más riesgo de fraude)
    score_bucket: str           # LEGITIMO | AMBIGUO | FRAUDE (por cortes del score)
    cluster_bucket: str         # LEGITIMO | AMBIGUO | FRAUDE (por centroide más cercano)
    agreement: bool
    top_contribuyentes: list[str]

    @property
    def resolved_bucket(self) -> str:
        """Bucket final: si score y cluster no coinciden, es ambigüedad -> AMBIGUO."""
        return self.score_bucket if self.agreement else "AMBIGUO"


@lru_cache(maxsize=1)
def _params() -> dict:
    return json.loads(_ARTIFACT.read_text(encoding="utf-8"))


def _raw_vector(case: CompensationCase, features: list[str]) -> np.ndarray:
    mapping = {
        "num_comp_90d": case.num_compensaciones_90d,
        "flags": case.flags_fraude_previos,
        "tiempo_entrega": case.tiempo_entrega_real_min,
        "antiguedad": case.antiguedad_usuario_dias,
        "monto_comp_90d": case.monto_compensado_90d_mxn,
    }
    return np.array([mapping[f] for f in features], dtype=float)


def assess(case: CompensationCase) -> RiskAssessment:
    p = _params()
    feats = p["features"]
    x = _raw_vector(case, feats)
    z = (x - np.array(p["scaler_mean"])) / np.array(p["scaler_scale"])
    signs = np.array([p["signs"][f] for f in feats])
    weights = np.array(p["weights"])
    oriented = z * signs
    abuse_index = float(oriented @ weights)

    # bucket por cortes del score
    c0, c1 = p["score_cuts"]
    if abuse_index < c0:
        score_bucket = "LEGITIMO"
    elif abuse_index < c1:
        score_bucket = "AMBIGUO"
    else:
        score_bucket = "FRAUDE"

    # bucket por centroide KMeans más cercano (en espacio estandarizado)
    centroids = np.array(p["centroids"])
    nearest = int(np.argmin(((centroids - z) ** 2).sum(axis=1)))
    cluster_bucket = p["cluster_to_bucket"][str(nearest)]

    # score 0-1
    lo, hi = p["abuse_index_min"], p["abuse_index_max"]
    risk_score = float(np.clip((abuse_index - lo) / (hi - lo), 0.0, 1.0))

    # top contribuyentes (por magnitud de contribución ponderada)
    contrib = oriented * weights
    order = np.argsort(-np.abs(contrib))
    top = []
    for i in order[:3]:
        pos, neg = _PHRASES[feats[i]]
        top.append(pos if contrib[i] > 0 else neg)

    return RiskAssessment(
        risk_score=round(risk_score, 2),
        score_bucket=score_bucket,
        cluster_bucket=cluster_bucket,
        agreement=(score_bucket == cluster_bucket),
        top_contribuyentes=top,
    )
