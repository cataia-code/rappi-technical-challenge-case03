"""Tests for derived features, risk model, and hybrid guardrails."""
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


# --- Derived features: GPS cross-checks --------------------------------------
def test_gps_contradicts_fraud_case(cases_by_id):
    f = compute_features(cases_by_id["COMP-0011"])
    assert f.gps_contradice_reclamo is True


def test_gps_does_not_contradict_wrong_product_case(cases_by_id):
    f = compute_features(cases_by_id["COMP-0012"])
    assert f.gps_contradice_reclamo is False


# --- Data-driven risk model --------------------------------------------------
def test_anchor_risk_buckets(cases_by_id):
    assert assess(cases_by_id["COMP-0011"]).resolved_bucket == "FRAUDE"
    assert assess(cases_by_id["COMP-0001"]).resolved_bucket == "LEGITIMO"
    assert assess(cases_by_id["COMP-0012"]).resolved_bucket == "AMBIGUO"


# --- Bucket-driven guardrails ------------------------------------------------
def test_fraud_guardrail_forbids_approval(cases_by_id):
    case = cases_by_id["COMP-0011"]
    v = evaluate_guardrail(assess(case), compute_features(case))
    assert v.action is GuardrailAction.FORBID_APPROVE


def test_legitimate_guardrail_forbids_rejection(cases_by_id):
    case = cases_by_id["COMP-0001"]
    v = evaluate_guardrail(assess(case), compute_features(case))
    assert v.action is GuardrailAction.FORBID_REJECT


def test_reconcile_degrades_approval_on_fraud_bucket(cases_by_id):
    """Even a high-confidence LLM approval is degraded by layer 0."""
    case = cases_by_id["COMP-0011"]
    v = evaluate_guardrail(assess(case), compute_features(case))
    d = Decision(
        caso_id=case.caso_id, recomendacion=Recommendation.APROBAR, confianza=0.9,
        senales_dominantes=["x"], resumen_cs="...",
    )
    out = reconcile(d, v)
    assert out.recomendacion is Recommendation.ESCALAR
    assert "no puede APROBAR" in out.override_guardrail


def test_reconcile_protects_legitimate_bucket(cases_by_id):
    case = cases_by_id["COMP-0001"]
    v = evaluate_guardrail(assess(case), compute_features(case))
    d = Decision(
        caso_id=case.caso_id, recomendacion=Recommendation.RECHAZAR, confianza=0.9,
        senales_dominantes=["x"], resumen_cs="...",
    )
    out = reconcile(d, v)
    assert out.recomendacion is Recommendation.ESCALAR
