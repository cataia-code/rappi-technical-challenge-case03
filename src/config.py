"""Central configuration: load .env and expose typed settings.

Single source of truth for credentials and decision-engine parameters.
Never hardcode API keys; always load them from the environment.

Multi-provider support: Groq, Gemini, and OpenRouter are OpenAI-compatible.
LLM_PROVIDER_ORDER defines fallback order; providers without API keys are skipped.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Project root = one level above this file (src/config.py).
PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

RAW_DATA = PROJECT_ROOT / "data" / "raw" / "Rappi_AI_Builder_Challenge_Dataset.xlsx"
OUTPUT_DIR = PROJECT_ROOT / "data" / "output"
SHEET_NAME = "Caso3_Compensaciones"
HEADER_ROW = 1  # The real header is row 1; row 0 is the sheet title.


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
                "No LLM API keys are configured. Set at least one of "
                "GROQ_API_KEY / GEMINI_API_KEY / OPENROUTER_API_KEY in .env, "
                "or run the pipeline with --no-llm."
            )
        return settings

    def iter_providers(self) -> list[tuple[str, str, str]]:
        """Configured providers as (name, api_key, model), in fallback order."""
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
