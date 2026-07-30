"""Multi-provider LLM client with cascading fallback.

Groq, Gemini, and OpenRouter expose OpenAI-compatible endpoints, so the OpenAI
SDK can cover all three by changing base_url, api_key, and model.

Strategy: iterate over configured providers in LLM_PROVIDER_ORDER. When a
provider fails or rate-limits, try the next one so the batch does not fail.
Each response records the provider and model for traceability.

The `openai` import is lazy; --no-llm mode does not require it.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from caso03.config import Settings

# OpenAI-compatible endpoints by provider.
_BASE_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "openrouter": "https://openrouter.ai/api/v1",
}


@dataclass(frozen=True)
class LLMResponse:
    content: str
    model_used: str  # Example: "groq:llama-3.3-70b-versatile"


class AllProvidersFailed(RuntimeError):
    """No configured provider produced a successful response."""


def _retry_after_seconds(exc: Exception, fallback: float, cap: float = 30.0) -> float:
    """Extract retry-after seconds from a 429 response, otherwise use fallback."""
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
        from openai import OpenAI  # lazy import
        if name not in self._clients:
            self._clients[name] = OpenAI(api_key=api_key, base_url=_BASE_URLS[name])
        return self._clients[name]

    def complete(
        self, system: str, user: str, retries_per_provider: int = 4
    ) -> LLMResponse:
        providers = self.settings.iter_providers()
        if not providers:
            raise AllProvidersFailed(
                "No LLM provider is configured; at least one API key is required."
            )
        last_exc: Exception | None = None
        for name, api_key, model in providers:
            try:
                return self._call(name, api_key, model, system, user, retries_per_provider)
            except Exception as exc:  # provider error or exhausted rate limit
                last_exc = exc
                continue
        raise AllProvidersFailed(f"Todos los proveedores fallaron: {last_exc!r}")

    def _call(self, name, api_key, model, system, user, retries) -> LLMResponse:
        from openai import RateLimitError
        client = self._client_for(name, api_key)
        for attempt in range(retries):
            try:
                resp = client.chat.completions.create(
                    model=model,
                    temperature=self.settings.temperature,
                    response_format={"type": "json_object"},
                    max_tokens=self.max_tokens,  # constrain output for better throughput
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
                if attempt == retries - 1:
                    raise
                time.sleep(_retry_after_seconds(exc, fallback=2 ** attempt))
        raise RuntimeError("unreachable")
