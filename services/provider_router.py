"""
LLM provider router for CEOClaw website generation.

Priority: Flock (live) → OpenAI → deterministic mock.
Both Flock and OpenAI speak the OpenAI chat-completions wire format.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 180  # seconds per provider attempt (luxury HTML generation can be large)


@dataclass
class LLMResult:
    content: str
    provider: str        # "flock" | "openai" | "mock"
    model_mode: str      # "flock_live" | "openai" | "mock" | "fallback_mock"
    error: Optional[str] = None
    fallback_used: bool = False
    fallback_reason: str = ""


def call_llm(messages: list[dict], timeout: int = _TIMEOUT) -> LLMResult:
    """Try providers in priority order; return first success."""
    # Pick up runtime changes to .env (e.g., user adds OPENAI_API_KEY in UI session).
    reload_fn = getattr(settings, "reload", None)
    if callable(reload_fn):
        reload_fn()

    flock_error: Optional[str] = None

    # 1. Flock — live only (skip if mock_mode flag is set)
    if settings.flock_endpoint and settings.flock_api_key and not settings.flock_mock_mode:
        try:
            result = _call_flock(messages, timeout)
            result.fallback_used = False
            result.fallback_reason = ""
            return result
        except Exception as exc:
            flock_error = str(exc)
            logger.warning("[ProviderRouter] Flock failed: %s — trying OpenAI", exc)

    # 2. OpenAI
    if settings.openai_api_key:
        try:
            result = _call_openai(messages, timeout)
            reason = f"flock_error: {flock_error}" if flock_error else "flock_not_configured"
            result.fallback_used = True
            result.fallback_reason = reason
            return result
        except Exception as exc:
            logger.warning("[ProviderRouter] OpenAI failed: %s — using mock", exc)

    # 3. Mock fallback
    if flock_error:
        reason = f"flock_error: {flock_error}"
    elif not settings.flock_endpoint and not settings.openai_api_key:
        reason = "no_providers_configured"
    else:
        reason = "all_providers_failed"
    return _mock_response(error="No configured provider succeeded", fallback_reason=reason)


def _call_flock(messages: list[dict], timeout: int) -> LLMResult:
    payload = {
        "model": settings.flock_model,
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 4096,
    }
    headers = {"Content-Type": "application/json"}
    strategy = settings.flock_auth_strategy
    if strategy in ("bearer", "both"):
        headers["Authorization"] = f"Bearer {settings.flock_api_key}"
    if strategy in ("litellm", "both"):
        headers["x-litellm-api-key"] = settings.flock_api_key

    resp = httpx.post(settings.flock_endpoint, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    content: str = resp.json()["choices"][0]["message"]["content"]
    return LLMResult(content=content, provider="flock", model_mode="flock_live",
                     fallback_used=False, fallback_reason="")


def _call_openai(messages: list[dict], timeout: int) -> LLMResult:
    """Route to Responses API or Chat Completions based on openai_api_mode setting."""
    model = settings.openai_model or "gpt-4o-mini"
    mode = getattr(settings, "openai_api_mode", "auto")

    use_responses = (
        mode == "responses"
        or (mode == "auto" and model.startswith("gpt-5"))
    )

    if use_responses:
        return _call_openai_responses(messages, model, timeout)
    return _call_openai_chat(messages, model, timeout)


def _call_openai_chat(messages: list[dict], model: str, timeout: int) -> LLMResult:
    """OpenAI Chat Completions — /v1/chat/completions."""
    endpoint = settings.openai_endpoint or "https://api.openai.com/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.openai_api_key}",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 8192,
    }
    resp = httpx.post(endpoint, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    content: str = resp.json()["choices"][0]["message"]["content"]
    return LLMResult(content=content, provider="openai", model_mode="openai",
                     fallback_used=False, fallback_reason="")


def _call_openai_responses(messages: list[dict], model: str, timeout: int) -> LLMResult:
    """OpenAI Responses API — /v1/responses (GPT-5 family)."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.openai_api_key}",
    }

    # Convert chat messages: system → instructions, rest → input items.
    input_items: list[dict] = []
    instructions: Optional[str] = None
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            instructions = content
        else:
            input_items.append({"role": role, "content": content})

    payload: dict = {"model": model, "input": input_items}
    if instructions:
        payload["instructions"] = instructions

    resp = httpx.post("https://api.openai.com/v1/responses",
                      json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    body = resp.json()

    # Prefer output_text shorthand; fall back to walking output items.
    content = body.get("output_text", "")
    if not content:
        for item in body.get("output", []):
            for part in item.get("content", []):
                if part.get("type") == "output_text":
                    content += part.get("text", "")
            if not content and item.get("type") == "message":
                for part in item.get("content", []):
                    content += part.get("text", "")

    if not content:
        raise ValueError(
            f"Responses API returned no text content. body keys: {list(body.keys())}"
        )

    return LLMResult(content=content, provider="openai", model_mode="openai_responses",
                     fallback_used=False, fallback_reason="")


def _mock_response(error: Optional[str] = None, fallback_reason: str = "no_providers_configured") -> LLMResult:
    return LLMResult(content="", provider="mock", model_mode="mock", error=error,
                     fallback_used=True, fallback_reason=fallback_reason)
