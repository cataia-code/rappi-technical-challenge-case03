"""decision_service — Capa 1: motor de decisión para casos ambiguos.

Toma un CompensationCase, evalúa señales observables y devuelve una Decision
validada (APROBAR / RECHAZAR / ESCALAR) con justificación auditable.

Orquesta las piezas del paquete llm/ (cliente multi-proveedor, prompts versionados,
esquema de salida). El fast-path resuelve determinísticamente los buckets claros y
solo llama al LLM en los casos ambiguos.

Controles de rigor:
- temperature=0 y JSON mode  -> reproducibilidad.
- Routing de incertidumbre: si la confianza < umbral, se enruta a ESCALAR
  (política "no forzar binario donde no lo hay").
- Capa 0 (guardrails) tiene la última palabra sobre la salida del LLM.
"""
from __future__ import annotations

import json

from pydantic import ValidationError

from caso03.config import Settings
from caso03.domain.models import CompensationCase, Decision, Recommendation
from caso03.features.feature_service import (
    compute_features,
    evaluate_guardrail,
    reconcile,
)
from caso03.llm.client import LLMClient
from caso03.llm.prompts import SYSTEM_PROMPT, build_user_prompt
from caso03.llm.schemas import LLMDecisionPayload
from caso03.scoring.risk_service import assess


class DecisionService:
    def __init__(
        self,
        settings: Settings | None = None,
        fast_path: bool = True,
        use_llm: bool = True,
    ):
        self.settings = settings or Settings.from_env(require_llm=False)
        self._client: LLMClient | None = None
        # fast_path: decidir LEGÍTIMO/FRAUDE de forma determinística y llamar al
        # LLM SOLO en los casos ambiguos (ahorra ~60% de llamadas y de tokens).
        self.fast_path = fast_path
        self.use_llm = use_llm

    # --- API pública ---------------------------------------------------------
    def decide(self, case: CompensationCase) -> Decision:
        """Entrada única (uso por caso / MCP): fast-path si aplica, si no LLM."""
        if self.fast_path:
            fast = self.fast_decision(case)
            if fast is not None:
                return fast
        if not self.use_llm:
            return self.escalate_without_llm(case)
        return self.decide_llm(case)

    def fast_decision(self, case: CompensationCase) -> Decision | None:
        """Decisión determinística (sin LLM) si el score la determina; None si no."""
        features = compute_features(case)
        risk = assess(case)
        return self._fast_path(case, features, risk)

    def escalate_without_llm(self, case: CompensationCase) -> Decision:
        """Fallback sin LLM: los ambiguos se ESCALAN (default seguro para ambigüedad)."""
        risk = assess(case)
        return Decision(
            caso_id=case.caso_id,
            recomendacion=Recommendation.ESCALAR,
            confianza=0.5,
            senales_dominantes=risk.top_contribuyentes[:3],
            resumen_cs=(
                f"Caso ambiguo (score {risk.risk_score}): "
                f"{', '.join(risk.top_contribuyentes)}. Requiere revisión humana."
            ),
            risk_score=risk.risk_score,
            risk_bucket=risk.resolved_bucket,
            top_contribuyentes=risk.top_contribuyentes,
            razonamiento="Ambiguo por el modelo de riesgo; escalado sin LLM (fallback).",
            override_guardrail="Fallback sin LLM: bucket AMBIGUO → ESCALAR",
        )

    def decide_llm(self, case: CompensationCase) -> Decision:
        """Camino LLM para los casos que el score no determina (ambiguos)."""
        features = compute_features(case)
        risk = assess(case)
        resp = self._llm().complete(SYSTEM_PROMPT, build_user_prompt(case, features, risk))
        decision = self._parse(case, resp.content)
        decision.modelo_usado = resp.model_used
        decision.risk_score = risk.risk_score
        decision.risk_bucket = risk.resolved_bucket
        decision.top_contribuyentes = risk.top_contribuyentes
        decision = self._route_uncertainty(decision)
        # Capa 0 tiene la última palabra: acota la salida del LLM a la política.
        return reconcile(decision, evaluate_guardrail(risk, features))

    # --- internos ------------------------------------------------------------
    def _llm(self) -> LLMClient:
        if self._client is None:
            self._client = LLMClient(self.settings)
        return self._client

    def _fast_path(self, case, features, risk) -> Decision | None:
        """Decisión determinística para buckets claros; None si hay que llamar al LLM."""
        b = risk.resolved_bucket
        if b == "LEGITIMO" and not features.gps_contradice_reclamo:
            return self._deterministic(
                case, risk, Recommendation.APROBAR, round(1 - risk.risk_score, 2),
                f"Bajo riesgo (score {risk.risk_score}): "
                f"{', '.join(risk.top_contribuyentes)}. Reclamo consistente; proceder.",
            )
        if b == "FRAUDE":
            return self._deterministic(
                case, risk, Recommendation.RECHAZAR, risk.risk_score,
                f"Alto riesgo (score {risk.risk_score}): "
                f"{', '.join(risk.top_contribuyentes)}. Señales de abuso; no proceder.",
            )
        return None  # AMBIGUO (o legítimo con GPS que contradice) -> al LLM

    def _deterministic(self, case, risk, rec, confianza, resumen) -> Decision:
        return Decision(
            caso_id=case.caso_id,
            recomendacion=rec,
            confianza=confianza,
            senales_dominantes=risk.top_contribuyentes[:3],
            resumen_cs=resumen,
            risk_score=risk.risk_score,
            risk_bucket=risk.resolved_bucket,
            top_contribuyentes=risk.top_contribuyentes,
            razonamiento="Justificación determinística por bucket de riesgo (sin LLM).",
        )

    def _parse(self, case: CompensationCase, raw: str) -> Decision:
        try:
            data = json.loads(raw)
            if "justificacion" not in data and "razonamiento" in data:
                data["justificacion"] = data["razonamiento"]
            payload = LLMDecisionPayload.model_validate(data)
        except (json.JSONDecodeError, TypeError, ValidationError, ValueError) as exc:
            return Decision(
                caso_id=case.caso_id,
                recomendacion=Recommendation.ESCALAR,
                confianza=0.0,
                senales_dominantes=["respuesta LLM inválida"],
                resumen_cs="El LLM devolvió una respuesta inválida; requiere revisión humana.",
                razonamiento="Salida LLM inválida o no estructurada.",
                override_guardrail=f"Parser LLM: {type(exc).__name__}",
            )
        return Decision(
            caso_id=case.caso_id,
            recomendacion=payload.recomendacion,
            confianza=payload.confianza,
            senales_dominantes=payload.senales_dominantes[:3],
            resumen_cs=payload.resumen_cs,
            razonamiento=payload.justificacion,
        )

    def _route_uncertainty(self, decision: Decision) -> Decision:
        """Si la confianza es baja y no es ya ESCALAR, enruta a ESCALAR."""
        thr = self.settings.confidence_escalate_threshold
        if decision.recomendacion is not Recommendation.ESCALAR and decision.confianza < thr:
            decision.override_guardrail = (
                f"Confianza {decision.confianza:.2f} < {thr}: enrutado a ESCALAR "
                f"(era {decision.recomendacion.value})."
            )
            decision.recomendacion = Recommendation.ESCALAR
        return decision
