"""feature_service — Capa 0: features derivadas + guardrails determinísticos.

Dos responsabilidades:
1. compute_features(case): cross-checks de negocio que alimentan el prompt del LLM.
2. evaluate_guardrail / reconcile: hard-stops de política que ACOTAN la salida del
   LLM (no la reemplazan). Fuerzan fronteras auditables y corrigen el sesgo del
   LLM a anclar la confianza: casos estructuralmente ambiguos van a ESCALAR aunque
   el modelo reporte alta confianza.

Diseño conservador (sesgo costo FP>FN): el guardrail más fuerte es FORBID_APPROVE
(no puede auto-aprobar) — nunca un RECHAZAR determinístico por reglas solas.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from caso03.domain.models import CompensationCase, Decision, Recommendation

if TYPE_CHECKING:
    from caso03.services.risk_service import RiskAssessment

# --- Umbrales de contexto para el prompt (NO deciden; la decisión usa el risk_model) ---
# Booleanos informativos que se pasan al LLM como pistas; los cortes que DECIDEN son
# los del modelo de riesgo derivado de los datos (risk_model.json).
FLAGS_ELEVADO = 2        # flags_fraude_previos: mediana 0, 48/150 casos >=2
COMP90_ELEVADO = 6       # num_compensaciones_90d: mediana 3, 42/150 casos >=6
EXPOSICION_ALTA = 1500.0 # monto_compensado_90d: mediana 394, máx 2764 (~4x mediana)
USUARIO_NUEVO_DIAS = 30  # 23/150 usuarios

# Vocabulario GPS/motivo (normalizado sin acentos)
_GPS_CONFIRMADA = "si - confirmada"
_GPS_NO_CONFIRMADA = "no confirmada"
_GPS_NO_CONCLUYENTE = {"parcial", "senal perdida"}
_MOTIVOS_NO_ENTREGA = {"orden no llego", "orden cancelada sin reembolso"}


def _clave(texto: str) -> str:
    sin_acentos = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return sin_acentos.casefold().strip()


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
    gps = _clave(case.entrega_confirmada_gps)
    motivo = _clave(case.motivo_reclamo)
    es_no_entrega = motivo in _MOTIVOS_NO_ENTREGA
    return CaseFeatures(
        ratio_comp_orden=round(case.compensacion_solicitada_mxn / case.valor_orden_mxn, 2),
        gps_contradice_reclamo=(gps == _GPS_CONFIRMADA and es_no_entrega),
        gps_corrobora_reclamo=(gps == _GPS_NO_CONFIRMADA and motivo == "orden no llego"),
        gps_no_concluyente=(gps in _GPS_NO_CONCLUYENTE),
        es_usuario_nuevo=(case.antiguedad_usuario_dias <= USUARIO_NUEVO_DIAS),
        reincidencia_alta=(case.num_compensaciones_90d >= COMP90_ELEVADO),
        flags_altos=(case.flags_fraude_previos >= FLAGS_ELEVADO),
        exposicion_alta=(case.monto_compensado_90d_mxn >= EXPOSICION_ALTA),
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
    """Guardrails guiados por el bucket de riesgo DERIVADO DE LOS DATOS.

    El bucket (risk_service) es el backbone determinístico; el GPS actúa de
    desempate secundario (los datos mostraron que es señal específica, no primaria).
    Diseño conservador (FP>FN): el tope es FORBID_APPROVE, nunca un RECHAZAR por regla.
    """
    b = risk.resolved_bucket
    score = risk.risk_score

    # FRAUDE (datos) -> no puede auto-aprobar
    if b == "FRAUDE":
        return GuardrailVerdict(
            GuardrailAction.FORBID_APPROVE, f"riesgo alto derivado (score {score})"
        )
    # LEGÍTIMO (datos) y sin contradicción de GPS -> no puede rechazar (protege legítimo)
    if b == "LEGITIMO" and not f.gps_contradice_reclamo:
        return GuardrailVerdict(
            GuardrailAction.FORBID_REJECT, f"riesgo bajo derivado (score {score})"
        )
    # AMBIGUO + GPS contradice el reclamo -> el desempate lo saca de aprobación
    if b == "AMBIGUO" and f.gps_contradice_reclamo:
        return GuardrailVerdict(
            GuardrailAction.FORBID_APPROVE, "ambiguo + GPS contradice el reclamo"
        )
    # AMBIGUO limpio -> sin restricción: el LLM decide con el texto del reclamo
    return GuardrailVerdict(GuardrailAction.NONE, "")


def reconcile(decision: Decision, verdict: GuardrailVerdict) -> Decision:
    """Reconcilia la decisión del LLM con la política. Conservador: degrada a ESCALAR."""
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
