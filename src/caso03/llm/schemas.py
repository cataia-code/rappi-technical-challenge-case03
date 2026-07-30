"""Strict Pydantic contract for LLM output.

The LLM returns JSON; this schema validates it before it reaches business logic.
Invalid payloads fail safe to ESCALAR in decision_service.
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
            raise ValueError("empty field")
        return value

    @field_validator("senales_dominantes")
    @classmethod
    def _signals_not_blank(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if not cleaned:
            raise ValueError("missing dominant signals")
        return cleaned[:3]
