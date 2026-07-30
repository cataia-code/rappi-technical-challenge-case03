"""Tests de Capa 0: features derivadas, modelo de riesgo y guardrails híbridos."""
import pytest

from caso03.domain.models import Decision, Recommendation
from caso03.services.data_service import load_cases
from caso03.features.feature_service import (
    GuardrailAction,
    compute_features,
    evaluate_guardrail,
    reconcile,
)
from caso03.scoring.risk_service import assess


@pytest.fixture(scope="module")
def cases_by_id():
    return {c.caso_id: c for c in load_cases()}


# --- Features derivadas (cross-check GPS) ------------------------------------
def test_gps_contradice_en_caso_fraude(cases_by_id):
    f = compute_features(cases_by_id["COMP-0011"])
    assert f.gps_contradice_reclamo is True


def test_gps_no_contradice_producto_incorrecto(cases_by_id):
    f = compute_features(cases_by_id["COMP-0012"])
    assert f.gps_contradice_reclamo is False


# --- Modelo de riesgo (data-driven) ------------------------------------------
def test_risk_buckets_de_los_anclas(cases_by_id):
    assert assess(cases_by_id["COMP-0011"]).resolved_bucket == "FRAUDE"
    assert assess(cases_by_id["COMP-0001"]).resolved_bucket == "LEGITIMO"
    assert assess(cases_by_id["COMP-0012"]).resolved_bucket == "AMBIGUO"


# --- Guardrails guiados por bucket -------------------------------------------
def test_guardrail_fraude_prohibe_aprobar(cases_by_id):
    case = cases_by_id["COMP-0011"]
    v = evaluate_guardrail(assess(case), compute_features(case))
    assert v.action is GuardrailAction.FORBID_APPROVE


def test_guardrail_legitimo_prohibe_rechazar(cases_by_id):
    case = cases_by_id["COMP-0001"]
    v = evaluate_guardrail(assess(case), compute_features(case))
    assert v.action is GuardrailAction.FORBID_REJECT


def test_reconcile_degrada_aprobar_en_fraude(cases_by_id):
    """Aunque el LLM apruebe con alta confianza, Capa 0 lo baja a ESCALAR."""
    case = cases_by_id["COMP-0011"]
    v = evaluate_guardrail(assess(case), compute_features(case))
    d = Decision(
        caso_id=case.caso_id, recomendacion=Recommendation.APROBAR, confianza=0.9,
        senales_dominantes=["x"], resumen_cs="...",
    )
    out = reconcile(d, v)
    assert out.recomendacion is Recommendation.ESCALAR
    assert "no puede APROBAR" in out.override_guardrail


def test_reconcile_protege_legitimo(cases_by_id):
    case = cases_by_id["COMP-0001"]
    v = evaluate_guardrail(assess(case), compute_features(case))
    d = Decision(
        caso_id=case.caso_id, recomendacion=Recommendation.RECHAZAR, confianza=0.9,
        senales_dominantes=["x"], resumen_cs="...",
    )
    out = reconcile(d, v)
    assert out.recomendacion is Recommendation.ESCALAR
