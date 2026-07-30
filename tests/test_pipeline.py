"""Tests de resiliencia del pipeline batch."""
from pathlib import Path

from caso03 import pipeline
from caso03.domain.models import Recommendation
from caso03.services.data_service import load_cases
from caso03.services.decision_service import DecisionService


def test_safe_decide_llm_conserva_scoring_en_fail_safe():
    svc = DecisionService(use_llm=False)
    case = {c.caso_id: c for c in load_cases()}["COMP-0012"]

    def _boom(_case):
        raise RuntimeError("fallo simulado")

    svc.decide_llm = _boom

    out = pipeline._safe_decide_llm(svc, case)

    assert out.recomendacion is Recommendation.ESCALAR
    assert out.risk_bucket == "AMBIGUO"
    assert out.risk_score is not None
    assert out.top_contribuyentes
    assert out.override_guardrail == "Fail-safe LLM: RuntimeError"


def test_pipeline_no_llm_produce_150_decisiones_con_scoring(monkeypatch, tmp_path):
    captured = {}

    def _write_excel(df, path=None):
        captured["df"] = df
        return Path(tmp_path) / "salida_150.xlsx"

    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setattr(pipeline, "write_excel", _write_excel)

    pipeline.run(use_llm=False)

    df = captured["df"]
    assert len(df) == 150
    assert not df["risk_bucket"].isna().any()
    assert not df["risk_score"].isna().any()
    assert df["recomendacion_agente"].value_counts().to_dict() == {
        "APROBAR": 60,
        "ESCALAR": 59,
        "RECHAZAR": 31,
    }


def test_pipeline_limit_cero_genera_reporte_vacio_valido(monkeypatch, tmp_path):
    captured = {}

    def _write_excel(df, path=None):
        captured["df"] = df
        return Path(tmp_path) / "salida_0.xlsx"

    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setattr(pipeline, "write_excel", _write_excel)

    pipeline.run(limit=0, use_llm=False)

    df = captured["df"]
    assert len(df) == 0
    assert "recomendacion_agente" in df.columns
    assert "risk_bucket" in df.columns
