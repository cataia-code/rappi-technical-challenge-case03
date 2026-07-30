"""Verifies the JS port of the decision core (apps/web/assets/js/scoring.js)
produces the exact same output as the Python core for the same inputs.

The live demo runs clustering in the browser using that JS file; if it drifts
from scoring/risk_service.py + features/feature_service.py, the demo would
silently disagree with the batch pipeline. This test runs both sides on the
same synthetic cases (fixed seed) and diffs the results.

Skipped automatically when Node.js isn't available on PATH.
"""
from __future__ import annotations

import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from domain.models import CompensationCase
from features.feature_service import compute_features, evaluate_guardrail
from scoring.risk_service import assess

ROOT = Path(__file__).resolve().parents[1]
SCORING_JS = ROOT / "apps" / "web" / "assets" / "js" / "scoring.js"
RISK_MODEL_JSON = ROOT / "src" / "scoring" / "artifacts" / "risk_model.json"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not on PATH")

_CITIES = ["CDMX", "Bogotá", "Medellín", "Buenos Aires", "Tijuana", "Querétaro"]
_VERTICALS = ["Comida", "Mercado", "Farmacia"]
_GPS = ["SÍ - confirmada", "NO confirmada", "Señal perdida", "Parcial"]
_MOTIVOS = ["Orden no llego", "Producto incorrecto", "Orden cancelada sin reembolso", "Demora excesiva"]


def _random_case(rng: random.Random, i: int) -> CompensationCase:
    valor = round(rng.uniform(80, 900), 2)
    return CompensationCase(
        caso_id=f"PARITY-{i:03d}",
        usuario_id=f"U-{i:03d}",
        antiguedad_usuario_dias=rng.randint(1, 2000),
        ciudad=rng.choice(_CITIES),
        vertical=rng.choice(_VERTICALS),
        restaurante="Parity Test",
        valor_orden_mxn=valor,
        compensacion_solicitada_mxn=round(min(valor, rng.uniform(20, valor)), 2),
        num_compensaciones_90d=rng.randint(0, 14),
        monto_compensado_90d_mxn=round(rng.uniform(0, 2800), 2),
        entrega_confirmada_gps=rng.choice(_GPS),
        tiempo_entrega_real_min=rng.randint(5, 120),
        flags_fraude_previos=rng.randint(0, 4),
        motivo_reclamo=rng.choice(_MOTIVOS),
        descripcion_reclamo="Caso sintético para verificación de paridad Python<->JS.",
    )


def _run_node(cases_raw: list[dict]) -> list[dict]:
    risk_model = json.loads(RISK_MODEL_JSON.read_text(encoding="utf-8"))
    script = """
const scoring = require(process.argv[1]);
const riskModel = JSON.parse(require('fs').readFileSync(process.argv[2], 'utf-8'));
const cases = JSON.parse(require('fs').readFileSync(0, 'utf-8'));
const out = cases.map((raw) => {
  const features = scoring.computeFeatures(raw);
  const risk = scoring.assessRisk(raw, riskModel);
  const guardrail = scoring.evaluateGuardrail(risk, features);
  return {
    caso_id: raw.caso_id,
    risk_score: risk.risk_score,
    resolved_bucket: risk.resolved_bucket,
    top_contribuyentes: risk.top_contribuyentes,
    guardrail_action: guardrail.action,
  };
});
process.stdout.write(JSON.stringify(out));
"""
    result = subprocess.run(
        ["node", "-e", script, "--", str(SCORING_JS), str(RISK_MODEL_JSON)],
        input=json.dumps(cases_raw, ensure_ascii=False).encode("utf-8"),
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout.decode("utf-8"))


def test_js_scoring_matches_python_for_synthetic_cases():
    rng = random.Random(20260730)
    cases = [_random_case(rng, i) for i in range(25)]

    py_results = []
    for case in cases:
        risk = assess(case)
        features = compute_features(case)
        guardrail = evaluate_guardrail(risk, features)
        py_results.append({
            "caso_id": case.caso_id,
            "risk_score": risk.risk_score,
            "resolved_bucket": risk.resolved_bucket,
            "top_contribuyentes": risk.top_contribuyentes,
            "guardrail_action": guardrail.action.value,
        })

    cases_raw = [c.model_dump() for c in cases]
    js_results = _run_node(cases_raw)

    assert len(js_results) == len(py_results)
    for py, js in zip(py_results, js_results):
        assert py["caso_id"] == js["caso_id"]
        assert py["risk_score"] == pytest.approx(js["risk_score"], abs=1e-6), py["caso_id"]
        assert py["resolved_bucket"] == js["resolved_bucket"], py["caso_id"]
        assert py["top_contribuyentes"] == js["top_contribuyentes"], py["caso_id"]
        assert py["guardrail_action"] == js["guardrail_action"], py["caso_id"]
