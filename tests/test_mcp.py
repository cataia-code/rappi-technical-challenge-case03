"""Smoke tests for the MCP tool boundary.

@mcp.tool leaves the underlying function directly callable (it just attaches
FastMCP metadata), so these call the tools the same way a batch test calls a
plain function -- no MCP client/transport needed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "mcp"))

import server  # noqa: E402


def test_review_case_known_id():
    out = server.review_case("COMP-0001")

    assert out["caso_id"] == "COMP-0001"
    assert out["recomendacion"] == "APROBAR"
    assert out["risk_bucket"] == "LEGITIMO"


def test_review_case_unknown_id_returns_error_dict():
    out = server.review_case("UNKNOWN-ID")

    assert "error" in out


def test_review_payload_scores_an_arbitrary_case():
    out = server.review_payload(
        antiguedad_usuario_dias=1500,
        ciudad="CDMX",
        vertical="Comida",
        valor_orden_mxn=300.0,
        compensacion_solicitada_mxn=100.0,
        num_compensaciones_90d=1,
        monto_compensado_90d_mxn=50.0,
        entrega_confirmada_gps="NO confirmada",
        tiempo_entrega_real_min=60,
        flags_fraude_previos=0,
        motivo_reclamo="Orden no llego",
        descripcion_reclamo="El pedido nunca llegó.",
    )

    assert out["recomendacion"] in {"APROBAR", "RECHAZAR", "ESCALAR"}
    assert out["risk_score"] is not None
