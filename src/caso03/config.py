"""Configuración central: carga .env y expone settings tipados.

Punto único de verdad para credenciales y parámetros del motor de decisión.
Nunca hardcodear la API key: siempre vía entorno (.env, gitignored).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Raíz del proyecto = dos niveles arriba de este archivo (src/caso03/config.py)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

RAW_DATA = PROJECT_ROOT / "data" / "raw" / "Rappi_AI_Builder_Challenge_Dataset.xlsx"
OUTPUT_DIR = PROJECT_ROOT / "data" / "output"
SHEET_NAME = "Caso3_Compensaciones"
HEADER_ROW = 1  # el encabezado real está en la fila 1 (fila 0 es el título)


@dataclass(frozen=True)
class Settings:
    groq_api_key: str
    groq_model: str
    temperature: float
    confidence_escalate_threshold: float

    @classmethod
    def from_env(cls, require_groq: bool = False) -> "Settings":
        key = os.getenv("GROQ_API_KEY", "")
        if require_groq and not key:
            raise RuntimeError(
                "GROQ_API_KEY no está definida. Copiá .env.example a .env y completala."
            )
        return cls(
            groq_api_key=key,
            groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0")),
            confidence_escalate_threshold=float(
                os.getenv("CONFIDENCE_ESCALATE_THRESHOLD", "0.6")
            ),
        )
