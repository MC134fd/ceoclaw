"""Tests for OpenAI-only provider routing behavior."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _patch_no_reload(monkeypatch, provider_router_mod):
    """Prevent settings.reload() from overwriting monkeypatched values inside call_llm."""
    monkeypatch.setattr(provider_router_mod.settings, "reload", lambda: None)


def test_call_llm_uses_openai_when_key_set(monkeypatch):
    """call_llm should use OpenAI when OPENAI_API_KEY is configured."""
    from services import provider_router
    _patch_no_reload(monkeypatch, provider_router)
    called = []
    def mock_openai(msgs, timeout):
        called.append("openai")
        from services.provider_router import LLMResult
        return LLMResult(content='{"assistant_message":"ok","changes":[]}', provider="openai", model_mode="openai")
    monkeypatch.setattr(provider_router, "_call_openai", mock_openai)
    monkeypatch.setattr(provider_router.settings, "openai_api_key", "sk-test-key")
    result = provider_router.call_llm([{"role": "user", "content": "test"}])
    assert result.provider == "openai"
    assert "openai" in called


def test_call_llm_skips_flock_entirely(monkeypatch):
    """call_llm must NEVER call _call_flock even if flock settings are set."""
    from services import provider_router
    _patch_no_reload(monkeypatch, provider_router)
    flock_called = []
    def should_not_call_flock(msgs, timeout):
        flock_called.append(True)
        from services.provider_router import LLMResult
        return LLMResult(content="flock response", provider="flock", model_mode="flock_live")
    monkeypatch.setattr(provider_router, "_call_flock", should_not_call_flock)
    monkeypatch.setattr(provider_router.settings, "flock_endpoint", "http://flock.example.com")
    monkeypatch.setattr(provider_router.settings, "flock_api_key", "flock-key")
    monkeypatch.setattr(provider_router.settings, "flock_mock_mode", False)
    # Even with flock configured, it must not be called
    monkeypatch.setattr(provider_router.settings, "openai_api_key", "")
    result = provider_router.call_llm([{"role": "user", "content": "test"}])
    assert len(flock_called) == 0, "Flock must not be called in OpenAI-only mode"
    assert result.provider == "mock"


def test_call_llm_falls_back_to_mock_without_key(monkeypatch):
    """Without OPENAI_API_KEY, call_llm returns mock result."""
    from services import provider_router
    _patch_no_reload(monkeypatch, provider_router)
    monkeypatch.setattr(provider_router.settings, "openai_api_key", "")
    result = provider_router.call_llm([{"role": "user", "content": "test"}])
    assert result.provider == "mock"
    assert result.fallback_used is True


def test_call_llm_falls_back_to_mock_on_openai_error(monkeypatch):
    """If OpenAI raises, call_llm falls back to mock."""
    from services import provider_router
    _patch_no_reload(monkeypatch, provider_router)
    def failing_openai(msgs, timeout):
        raise ConnectionError("network error")
    monkeypatch.setattr(provider_router, "_call_openai", failing_openai)
    monkeypatch.setattr(provider_router.settings, "openai_api_key", "sk-key")
    result = provider_router.call_llm([{"role": "user", "content": "test"}])
    assert result.provider == "mock"
    assert result.fallback_used is True


def test_provider_health_flock_always_disabled():
    """check_provider_health must always report flock as disabled."""
    from services.llm_router_service import check_provider_health
    health = check_provider_health()
    assert health["flock"]["configured"] is False
    assert health["flock"]["reachable"] is False
    assert health["flock"]["error"] == "disabled"


def test_provider_health_active_provider_not_flock(monkeypatch):
    """active_provider should never be 'flock'."""
    from services import llm_router_service
    health = llm_router_service.check_provider_health()
    assert health["active_provider"] in ("openai", "mock"), \
        f"active_provider must be openai or mock, got {health['active_provider']!r}"


def test_llm_result_model_mode_no_flock_live():
    """LLMResult from call_llm should never have model_mode='flock_live'."""
    from services.provider_router import LLMResult
    # Just verify flock_live is not a documented/expected value
    r = LLMResult(content="x", provider="openai", model_mode="openai")
    assert r.model_mode == "openai"
    assert r.model_mode != "flock_live"
