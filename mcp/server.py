"""Servidor MCP — expone el agente de decisión como herramienta (bonus).

Misma frontera que la referencia air_travel (AI Agent → MCP → SDK/servicio), pero
sin infra pesada: el tool llama en-proceso al DecisionService sobre los datos locales.

Correr:  python mcp/server.py         (stdio, para un cliente MCP)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastmcp import FastMCP  # noqa: E402

from caso03.domain.models import CompensationCase  # noqa: E402
from caso03.services.data_service import load_cases  # noqa: E402
from caso03.services.decision_service import DecisionService  # noqa: E402

mcp = FastMCP("caso03-compensaciones")
_svc = DecisionService()
_cases = {c.caso_id: c for c in load_cases()}


@mcp.tool
def revisar_caso(caso_id: str) -> dict:
    """Revisa un caso existente del dataset por su ID (ej. 'COMP-0011').

    Devuelve recomendación (APROBAR/RECHAZAR/ESCALAR), risk_score, bucket,
    señales que más pesan y un resumen accionable para el agente CS.
    """
    case = _cases.get(caso_id)
    if case is None:
        return {"error": f"caso_id '{caso_id}' no encontrado"}
    return _svc.decide(case).model_dump()


@mcp.tool
def revisar_datos(
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
    """Revisa un caso ARBITRARIO a partir de sus señales (narrativa de producción).

    Permite scorear un caso nuevo que no está en el dataset — como lo haría el
    agente en vivo a 200+/día.
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
