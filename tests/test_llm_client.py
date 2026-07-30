"""Tests for multi-provider LLM fallback and traceability."""
import httpx
import pytest
from openai import RateLimitError

from config import Settings
from llm.client import AllProvidersFailed, LLMClient


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


def test_fallback_moves_to_next_provider(monkeypatch):
    client = LLMClient(_settings(("groq", "gemini")))
    fakes = {
        "groq": _FakeClient(RuntimeError("groq down")),
        "gemini": _FakeClient('{"ok": 1}'),
    }
    monkeypatch.setattr(client, "_client_for", lambda name, api_key: fakes[name])

    resp = client.complete("sys", "usr")

    assert resp.content == '{"ok": 1}'
    assert resp.model_used == "gemini:gemm"


def test_no_configured_providers_raises():
    with pytest.raises(AllProvidersFailed):
        LLMClient(_settings(())).complete("s", "u")


def _rate_limit_error(retry_after: str | None = None) -> RateLimitError:
    headers = {"retry-after": retry_after} if retry_after else {}
    response = httpx.Response(
        429, headers=headers, request=httpx.Request("POST", "https://example.test")
    )
    return RateLimitError("rate limited", response=response, body=None)


class _RetryingCompletions:
    """Raises RateLimitError N times, then succeeds -- exercises the in-provider retry loop."""

    def __init__(self, failures: int, retry_after: str | None = None):
        self._remaining = failures
        self._retry_after = retry_after

    def create(self, **_kw):
        if self._remaining > 0:
            self._remaining -= 1
            raise _rate_limit_error(self._retry_after)
        msg = type("M", (), {"content": '{"ok": "recovered"}'})()
        return type("R", (), {"choices": [type("C", (), {"message": msg})()]})()


def test_rate_limit_retries_within_same_provider_then_succeeds(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _s: None)  # don't actually wait in tests
    client = LLMClient(_settings(("groq",)))
    fake = type("FakeClient", (), {"chat": type("Chat", (), {
        "completions": _RetryingCompletions(failures=2, retry_after="0.01"),
    })()})()
    monkeypatch.setattr(client, "_client_for", lambda name, api_key: fake)

    resp = client.complete("sys", "usr", retries_per_provider=4)

    assert resp.content == '{"ok": "recovered"}'
    assert resp.model_used == "groq:gm"


def test_rate_limit_exhausted_falls_back_to_next_provider(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _s: None)
    client = LLMClient(_settings(("groq", "gemini")))
    fakes = {
        "groq": type("FakeClient", (), {"chat": type("Chat", (), {
            "completions": _RetryingCompletions(failures=99),  # never recovers
        })()})(),
        "gemini": _FakeClient('{"ok": "fallback"}'),
    }
    monkeypatch.setattr(client, "_client_for", lambda name, api_key: fakes[name])

    resp = client.complete("sys", "usr", retries_per_provider=2)

    assert resp.content == '{"ok": "fallback"}'
    assert resp.model_used == "gemini:gemm"
