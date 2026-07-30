"""Configuración central: carga .env y expone settings tipados.

Punto único de verdad para credenciales y parámetros del motor de decisión.
Nunca hardcodear API keys: siempre vía entorno (.env, gitignored).

Multi-proveedor: Groq, Gemini y OpenRouter (todos OpenAI-compatible). El orden de
fallback lo define LLM_PROVIDER_ORDER; solo se usan los proveedores con API key.
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
    gemini_api_key: str
    gemini_model: str
    openrouter_api_key: str
    openrouter_model: str
    temperature: float
    confidence_escalate_threshold: float
    provider_order: tuple[str, ...]

    @classmethod
    def from_env(cls, require_llm: bool = False) -> "Settings":
        order = tuple(
            p.strip().lower()
            for p in os.getenv("LLM_PROVIDER_ORDER", "groq,gemini,openrouter").split(",")
            if p.strip()
        )
        settings = cls(
            groq_api_key=os.getenv("GROQ_API_KEY", ""),
            groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY", ""),
            openrouter_model=os.getenv(
                "OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct"
            ),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0")),
            confidence_escalate_threshold=float(
                os.getenv("CONFIDENCE_ESCALATE_THRESHOLD", "0.6")
            ),
            provider_order=order,
        )
        if require_llm and not settings.iter_providers():
            raise RuntimeError(
                "No hay API keys de LLM configuradas. Completá al menos una "
                "(GROQ_API_KEY / GEMINI_API_KEY / OPENROUTER_API_KEY) en .env, "
                "o ejecutá el pipeline con --no-llm."
            )
        return settings

    def iter_providers(self) -> list[tuple[str, str, str]]:
        """Proveedores configurados como (nombre, api_key, modelo), en orden de fallback."""
        table = {
            "groq": (self.groq_api_key, self.groq_model),
            "gemini": (self.gemini_api_key, self.gemini_model),
            "openrouter": (self.openrouter_api_key, self.openrouter_model),
        }
        out: list[tuple[str, str, str]] = []
        for name in self.provider_order:
            key, model = table.get(name, ("", ""))
            if key:
                out.append((name, key, model))
        return out
