"""MCP server exposing the decision agent as tools.

This keeps the AI Agent -> MCP -> service boundary without additional
infrastructure: tools call DecisionService in-process over local data.

Run with: python apps/mcp/server.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from fastmcp import FastMCP  # noqa: E402

from caso03.domain.models import CompensationCase  # noqa: E402
from caso03.services.data_service import load_cases  # noqa: E402
from caso03.services.decision_service import DecisionService  # noqa: E402

mcp = FastMCP("caso03-compensaciones")
_svc = DecisionService()
_cases = {c.caso_id: c for c in load_cases()}


@mcp.tool
def review_case(caso_id: str) -> dict:
    """Review an existing dataset case by ID, e.g. 'COMP-0011'.

    Returns recommendation, risk_score, bucket, dominant signals, and an
    actionable CS summary.
    """
    case = _cases.get(caso_id)
    if case is None:
        return {"error": f"caso_id '{caso_id}' not found"}
    return _svc.decide(case).model_dump()


@mcp.tool
def review_payload(
    antiguedad_usuario_dias: int,
    ciudad: str,
    vertical: str,
    valor_orden_mxn: float,
    compensacion_solicitada_mxn: float,
    num_compensaciones_90d: int,
    monto_compensado_90d_mxn: float,
    entrega_confirmada_gps: str,
    tiempo_entrega_real_min: int,
    flags_fraude_previos: int,
    motivo_reclamo: str,
    descripcion_reclamo: str,
    caso_id: str = "AD-HOC",
    usuario_id: str = "AD-HOC",
    restaurante: str = "N/D",
) -> dict:
    """Review an arbitrary case from its observable signals.

    This scores a new case outside the dataset, matching the live-agent flow.
    """
    case = CompensationCase(
        caso_id=caso_id, usuario_id=usuario_id, antiguedad_usuario_dias=antiguedad_usuario_dias,
        ciudad=ciudad, vertical=vertical, restaurante=restaurante,
        valor_orden_mxn=valor_orden_mxn, compensacion_solicitada_mxn=compensacion_solicitada_mxn,
        num_compensaciones_90d=num_compensaciones_90d, monto_compensado_90d_mxn=monto_compensado_90d_mxn,
        entrega_confirmada_gps=entrega_confirmada_gps, tiempo_entrega_real_min=tiempo_entrega_real_min,
        flags_fraude_previos=flags_fraude_previos, motivo_reclamo=motivo_reclamo,
        descripcion_reclamo=descripcion_reclamo,
    )
    return _svc.decide(case).model_dump()


if __name__ == "__main__":
    mcp.run()
