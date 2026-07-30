"""Tests del cliente LLM multi-proveedor: fallback en cascada y trazabilidad."""
import pytest

from caso03.config import Settings
from caso03.llm.client import AllProvidersFailed, LLMClient


def _settings(order: tuple[str, ...]) -> Settings:
    has = lambda n: "key" if n in order else ""
    return Settings(
        groq_api_key=has("groq"), groq_model="gm",
        gemini_api_key=has("gemini"), gemini_model="gemm",
        openrouter_api_key=has("openrouter"), openrouter_model="orm",
        temperature=0.0, confidence_escalate_threshold=0.6, provider_order=order,
    )


class _FakeCompletions:
    def __init__(self, behavior):
        self._b = behavior

    def create(self, **_kw):
        if isinstance(self._b, Exception):
            raise self._b
        msg = type("M", (), {"content": self._b})()
        return type("R", (), {"choices": [type("C", (), {"message": msg})()]})()


class _FakeClient:
    def __init__(self, behavior):
        self.chat = type("Chat", (), {"completions": _FakeCompletions(behavior)})()


def test_fallback_pasa_al_siguiente_proveedor(monkeypatch):
    client = LLMClient(_settings(("groq", "gemini")))
    fakes = {
        "groq": _FakeClient(RuntimeError("groq caído")),
        "gemini": _FakeClient('{"ok": 1}'),
    }
    monkeypatch.setattr(client, "_client_for", lambda name, api_key: fakes[name])

    resp = client.complete("sys", "usr")

    assert resp.content == '{"ok": 1}'
    assert resp.model_used == "gemini:gemm"  # registra qué modelo respondió


def test_sin_proveedores_configurados_lanza():
    with pytest.raises(AllProvidersFailed):
        LLMClient(_settings(())).complete("s", "u")
