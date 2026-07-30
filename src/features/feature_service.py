"""Derived features and deterministic guardrails.

Responsibilities:
1. compute_features(case): business cross-checks that feed the LLM prompt.
2. evaluate_guardrail / reconcile: policy hard stops that constrain LLM output
   instead of replacing it. They enforce auditable boundaries and prevent
   structurally ambiguous cases from being forced into binary outcomes.

The design is conservative: the strongest guardrail forbids approval; it never
rejects deterministically from rules alone.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from domain.models import CompensationCase, Decision, Recommendation

if TYPE_CHECKING:
    from scoring.risk_service import RiskAssessment

# Prompt context thresholds. They do not decide; risk_model.json does.
# These booleans are hints passed to the LLM for compact, observable context.
HIGH_FLAGS = 2              # flags_fraude_previos: median 0, 48/150 cases >= 2
HIGH_COMPENSATIONS_90D = 6  # num_compensaciones_90d: median 3, 42/150 cases >= 6
HIGH_EXPOSURE_MXN = 1500.0  # monto_compensado_90d: median 394, max 2764 (~4x median)
NEW_USER_DAYS = 30          # 23/150 users

# GPS/reason vocabulary normalized without accents.
_GPS_CONFIRMADA = "si - confirmada"
_GPS_NO_CONFIRMADA = "no confirmada"
_GPS_NO_CONCLUYENTE = {"parcial", "senal perdida"}
_NON_DELIVERY_REASONS = {"orden no llego", "orden cancelada sin reembolso"}


def normalize_key(text: str) -> str:
    """Normalize business text for accent-insensitive comparisons."""
    without_accents = "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    )
    return without_accents.casefold().strip()


@dataclass(frozen=True)
class CaseFeatures:
    ratio_comp_orden: float
    gps_contradice_reclamo: bool
    gps_corrobora_reclamo: bool
    gps_no_concluyente: bool
    es_usuario_nuevo: bool
    reincidencia_alta: bool
    flags_altos: bool
    exposicion_alta: bool


def compute_features(case: CompensationCase) -> CaseFeatures:
    gps = normalize_key(case.entrega_confirmada_gps)
    reason = normalize_key(case.motivo_reclamo)
    is_non_delivery = reason in _NON_DELIVERY_REASONS
    return CaseFeatures(
        ratio_comp_orden=round(case.compensacion_solicitada_mxn / case.valor_orden_mxn, 2),
        gps_contradice_reclamo=(gps == _GPS_CONFIRMADA and is_non_delivery),
        gps_corrobora_reclamo=(gps == _GPS_NO_CONFIRMADA and reason == "orden no llego"),
        gps_no_concluyente=(gps in _GPS_NO_CONCLUYENTE),
        es_usuario_nuevo=(case.antiguedad_usuario_dias <= NEW_USER_DAYS),
        reincidencia_alta=(case.num_compensaciones_90d >= HIGH_COMPENSATIONS_90D),
        flags_altos=(case.flags_fraude_previos >= HIGH_FLAGS),
        exposicion_alta=(case.monto_compensado_90d_mxn >= HIGH_EXPOSURE_MXN),
    )


class GuardrailAction(str, Enum):
    NONE = "NONE"
    FORBID_APPROVE = "FORBID_APPROVE"   # fraude fuerte: no puede APROBAR
    FORBID_REJECT = "FORBID_REJECT"     # perfil limpio: no puede RECHAZAR
    FORCE_ESCALATE = "FORCE_ESCALATE"   # ambigüedad estructural: ESCALAR


@dataclass(frozen=True)
class GuardrailVerdict:
    action: GuardrailAction
    reason: str


def evaluate_guardrail(risk: "RiskAssessment", f: CaseFeatures) -> GuardrailVerdict:
    """Return policy guardrails driven by the data-derived risk bucket.

    The risk bucket is the deterministic backbone. GPS acts only as a secondary
    tie-breaker because the data showed it is specific but not primary.
    """
    b = risk.resolved_bucket
    score = risk.risk_score

    # Fraud bucket -> cannot auto-approve.
    if b == "FRAUDE":
        return GuardrailVerdict(
            GuardrailAction.FORBID_APPROVE, f"riesgo alto derivado (score {score})"
        )
    # Clean low-risk bucket without GPS contradiction -> cannot reject.
    if b == "LEGITIMO" and not f.gps_contradice_reclamo:
        return GuardrailVerdict(
            GuardrailAction.FORBID_REJECT, f"riesgo bajo derivado (score {score})"
        )
    # Ambiguous + GPS contradiction -> prevent approval.
    if b == "AMBIGUO" and f.gps_contradice_reclamo:
        return GuardrailVerdict(
            GuardrailAction.FORBID_APPROVE, "ambiguo + GPS contradice el reclamo"
        )
    # Clean ambiguous case -> no restriction; let the LLM use the claim text.
    return GuardrailVerdict(GuardrailAction.NONE, "")


def reconcile(decision: Decision, verdict: GuardrailVerdict) -> Decision:
    """Reconcile LLM output with policy, conservatively degrading to ESCALAR."""
    a, rec = verdict.action, decision.recomendacion
    tag = f"Capa0: {verdict.reason}"

    if a is GuardrailAction.FORBID_APPROVE and rec is Recommendation.APROBAR:
        decision.recomendacion = Recommendation.ESCALAR
        decision.override_guardrail = f"{tag} → no puede APROBAR, se ESCALA"
    elif a is GuardrailAction.FORBID_REJECT and rec is Recommendation.RECHAZAR:
        decision.recomendacion = Recommendation.ESCALAR
        decision.override_guardrail = f"{tag} → no puede RECHAZAR, se ESCALA"
    elif a is GuardrailAction.FORCE_ESCALATE and rec is not Recommendation.ESCALAR:
        decision.override_guardrail = f"{tag} → ESCALAR (era {rec.value})"
        decision.recomendacion = Recommendation.ESCALAR
    return decision
