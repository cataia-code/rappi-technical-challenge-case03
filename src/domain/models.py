"""Domain contract shared by all services.

Defines the input (CompensationCase), validated output (Decision), and
recommendation enums. The decision core and reporting layer only communicate
through this contract, regardless of whether data comes from Excel, an API,
or an MCP tool.
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
    """Normalized, validated case ready for feature extraction and decisioning.

    Field constraints are the explicit validation layer. The current dataset is
    clean, but at 200+ cases/day this rejects corrupt values instead of silently
    propagating them.
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
    """Agent output for one case; this is what CS reviews."""

    caso_id: str
    recomendacion: Recommendation
    confianza: float = Field(ge=0.0, le=1.0)
    senales_dominantes: list[str] = Field(min_length=1, max_length=3)
    resumen_cs: str
    # Data-driven backbone values travel with the decision into every output.
    risk_score: Optional[float] = None
    risk_bucket: Optional[str] = None
    top_contribuyentes: list[str] = Field(default_factory=list)
    razonamiento: Optional[str] = Field(
        default=None,
        description="Brief justification based on observable signals; no chain-of-thought.",
    )
    override_guardrail: Optional[str] = Field(
        default=None,
        description="Reason recorded when a layer-0 hard stop overrides the LLM.",
    )
    modelo_usado: Optional[str] = Field(
        default=None,
        description="Provider:model that produced the LLM decision, e.g. "
        "'groq:llama-3.3-70b'; None for deterministic decisions.",
    )
    pasos_recomendados: list[str] = Field(
        default_factory=list,
        description="Short, concrete next steps for CS on ESCALAR cases: what to check and "
        "what specifically kept the model from reaching a verdict. Empty for APROBAR/RECHAZAR.",
    )
