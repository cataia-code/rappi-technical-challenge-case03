"""schemas — contrato de salida del LLM (validación estricta con Pydantic).

El LLM devuelve JSON; este esquema lo valida antes de que toque la lógica de
negocio. Si no valida, decision_service cae a ESCALAR (fail-safe).
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from caso03.domain.models import Recommendation


class LLMDecisionPayload(BaseModel):
    justificacion: str = Field(min_length=1)
    recomendacion: Recommendation
    confianza: float = Field(ge=0.0, le=1.0)
    senales_dominantes: list[str] = Field(min_length=1, max_length=3)
    resumen_cs: str = Field(min_length=1)

    @field_validator("justificacion", "resumen_cs")
    @classmethod
    def _text_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("campo vacío")
        return value

    @field_validator("senales_dominantes")
    @classmethod
    def _signals_not_blank(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if not cleaned:
            raise ValueError("sin señales dominantes")
        return cleaned[:3]
