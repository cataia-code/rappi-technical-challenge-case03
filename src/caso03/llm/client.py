"""client — cliente LLM multi-proveedor con fallback en cascada.

Groq, Gemini y OpenRouter exponen endpoints OpenAI-compatible, así que un solo
SDK (openai) los cubre variando base_url + api_key + modelo.

Estrategia: recorre los proveedores disponibles (con API key) en el orden de
LLM_PROVIDER_ORDER. Ante rate-limit agotado o error de un proveedor, pasa al
siguiente — así el batch no se cae si Groq agota su cuota diaria. Cada respuesta
registra qué modelo la produjo (para trazabilidad y para mostrarlo en la web).

Import perezoso de `openai`: no es requerido en modo --no-llm.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from caso03.config import Settings

# Endpoints OpenAI-compatible por proveedor
_BASE_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "openrouter": "https://openrouter.ai/api/v1",
}


@dataclass(frozen=True)
class LLMResponse:
    content: str
    model_used: str  # ej. "groq:llama-3.3-70b-versatile"


class AllProvidersFailed(RuntimeError):
    """Ningún proveedor configurado pudo responder."""


def _retry_after_seconds(exc: Exception, fallback: float, cap: float = 30.0) -> float:
    """Extrae retry-after del 429 (segundos) + buffer; si no está, usa fallback."""
    try:
        ra = exc.response.headers.get("retry-after")  # type: ignore[attr-defined]
        if ra is not None:
            return min(float(ra) + 0.5, cap)
    except Exception:
        pass
    return min(fallback, cap)


class LLMClient:
    def __init__(self, settings: Settings, max_tokens: int = 450):
        self.settings = settings
        self.max_tokens = max_tokens
        self._clients: dict[str, object] = {}

    def _client_for(self, name: str, api_key: str):
        from openai import OpenAI  # import perezoso
        if name not in self._clients:
            self._clients[name] = OpenAI(api_key=api_key, base_url=_BASE_URLS[name])
        return self._clients[name]

    def complete(
        self, system: str, user: str, retries_per_provider: int = 4
    ) -> LLMResponse:
        providers = self.settings.iter_providers()
        if not providers:
            raise AllProvidersFailed(
                "No hay ningún proveedor LLM configurado (falta API key)."
            )
        last_exc: Exception | None = None
        for name, api_key, model in providers:
            try:
                return self._call(name, api_key, model, system, user, retries_per_provider)
            except Exception as exc:  # rate-limit agotado o error del proveedor
                last_exc = exc
                continue
        raise AllProvidersFailed(f"Todos los proveedores fallaron: {last_exc!r}")

    def _call(self, name, api_key, model, system, user, retries) -> LLMResponse:
        from openai import RateLimitError
        client = self._client_for(name, api_key)
        for intento in range(retries):
            try:
                resp = client.chat.completions.create(
                    model=model,
                    temperature=self.settings.temperature,
                    response_format={"type": "json_object"},
                    max_tokens=self.max_tokens,  # acota output -> menos tokens, más throughput
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
                return LLMResponse(
                    content=resp.choices[0].message.content,
                    model_used=f"{name}:{model}",
                )
            except RateLimitError as exc:
                if intento == retries - 1:
                    raise
                time.sleep(_retry_after_seconds(exc, fallback=2 ** intento))
        raise RuntimeError("unreachable")
