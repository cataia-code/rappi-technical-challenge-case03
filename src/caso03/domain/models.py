"""Contrato de dominio — el lenguaje común de todos los servicios.

Define la entrada (CompensationCase), la salida validada (Decision) y las
enums de recomendación. El núcleo de decisión y el output hablan SOLO este
contrato; da igual si los datos vienen de un Excel, una API o un tool MCP.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Recommendation(str, Enum):
    APROBAR = "APROBAR"
    RECHAZAR = "RECHAZAR"
    ESCALAR = "ESCALAR"


class GpsStatus(str, Enum):
    CONFIRMADA = "SÍ - confirmada"
    NO_CONFIRMADA = "NO confirmada"
    SENAL_PERDIDA = "Señal perdida"
    PARCIAL = "Parcial"


class CompensationCase(BaseModel):
    """Un caso normalizado, validado y listo para features y decisión.

    Las restricciones (ge=0, min_length) son la capa de validación explícita del
    pipeline: hoy el dataset está limpio, pero a 200+/día esto rechaza datos
    corruptos (montos negativos, IDs vacíos) en vez de propagarlos silenciosamente.
    """

    caso_id: str = Field(min_length=1)
    usuario_id: str = Field(min_length=1)
    antiguedad_usuario_dias: int = Field(ge=0)
    ciudad: str = Field(min_length=1)
    vertical: str = Field(min_length=1)
    restaurante: str = Field(min_length=1)
    valor_orden_mxn: float = Field(gt=0)
    compensacion_solicitada_mxn: float = Field(gt=0)
    num_compensaciones_90d: int = Field(ge=0)
    monto_compensado_90d_mxn: float = Field(ge=0)
    entrega_confirmada_gps: str = Field(min_length=1)
    tiempo_entrega_real_min: int = Field(ge=0)
    flags_fraude_previos: int = Field(ge=0)
    motivo_reclamo: str = Field(min_length=1)
    descripcion_reclamo: str


class Decision(BaseModel):
    """Salida del agente por caso — lo que revisa el CS 'en 5 segundos'."""

    caso_id: str
    recomendacion: Recommendation
    confianza: float = Field(ge=0.0, le=1.0)
    senales_dominantes: list[str] = Field(min_length=1, max_length=3)
    resumen_cs: str
    # Backbone data-driven (risk_service): viaja con la decisión hasta el output.
    risk_score: Optional[float] = None
    risk_bucket: Optional[str] = None
    top_contribuyentes: list[str] = Field(default_factory=list)
    razonamiento: Optional[str] = Field(
        default=None,
        description="Justificación breve basada en señales observables; no chain-of-thought.",
    )
    override_guardrail: Optional[str] = Field(
        default=None,
        description="Si un hard-stop de Capa 0 anuló al LLM, aquí se registra el motivo.",
    )
