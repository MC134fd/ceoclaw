"""
LLM provider router for CEOClaw website generation.

Runtime provider: OpenAI only.
If OPENAI_API_KEY is missing or OpenAI fails, raises RuntimeError — no silent fallback.
Flock is retained for backward compat but never called at runtime.
"""

import logging
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 600  # seconds per provider attempt (reasoning models + large HTML can take 300s+)
_DEBUG_LOG_PATH = Path("/Users/marcuschien/code/MC134fd/ceoclaw/.cursor/debug-ae58c9.log")


@dataclass
class LLMResult:
    content: str
    provider: str        # "openai" | "openai_responses"
    model_mode: str      # "openai" | "openai_responses"
    error: Optional[str] = None
    fallback_used: bool = False
    fallback_reason: str = ""


def _debug_log(run_id: str, hypothesis_id: str, location: str, message: str, data: dict) -> None:
    # #region agent log
    try:
        payload = {
            "sessionId": "ae58c9",
            "runId": run_id,
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(__import__("time").time() * 1000),
        }
        _DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _DEBUG_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload) + "\n")
    except Exception:
        pass
    # #endregion


def call_llm(messages: list[dict], timeout: int = _TIMEOUT, max_tokens: int = 16000) -> LLMResult:
    """Call OpenAI. Returns template-fallback signal when unavailable."""
    run_id = f"provider_{int(__import__('time').time() * 1000)}"
    # Pick up runtime changes to .env (e.g., user adds OPENAI_API_KEY in UI session).
    reload_fn = getattr(settings, "reload", None)
    if callable(reload_fn):
        reload_fn()

    _debug_log(
        run_id, "H1", "services/provider_router.py:call_llm",
        "provider config snapshot",
        {
            "openaiConfigured": bool(settings.openai_api_key),
            "openaiKeyLen": len(settings.openai_api_key or ""),
            "openaiModel": settings.openai_model or "",
            "openaiApiMode": getattr(settings, "openai_api_mode", "missing"),
            "openaiEndpoint": settings.openai_endpoint or "",
        },
    )

    if not settings.openai_api_key:
        _debug_log(run_id, "H2", "services/provider_router.py:call_llm",
                   "no openai key — returning fallback signal", {})
        return LLMResult(content="", provider="openai", model_mode="fallback",
                         fallback_used=True, fallback_reason="no_openai_key")

    try:
        result = _call_openai(messages, timeout, max_tokens=max_tokens)
        _debug_log(
            run_id, "H2", "services/provider_router.py:call_llm",
            "openai call succeeded",
            {"modelMode": result.model_mode, "contentLen": len(result.content or "")},
        )
        return result
    except Exception as exc:
        _debug_log(
            run_id, "H2", "services/provider_router.py:call_llm",
            "openai call failed — returning fallback signal",
            {"errorType": type(exc).__name__, "error": str(exc)[:240]},
        )
        return LLMResult(content="", provider="openai", model_mode="fallback",
                         fallback_used=True, fallback_reason=f"openai_error: {exc}")


def _call_flock(messages: list[dict], timeout: int) -> LLMResult:
    """Retained for backward compat — never called in the runtime path."""
    payload = {
        "model": settings.flock_model,
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 16384,
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


def _call_openai(messages: list[dict], timeout: int, max_tokens: int = 16000) -> LLMResult:
    """Route to Responses API or Chat Completions based on openai_api_mode setting."""
    model = settings.openai_model or "gpt-4o-mini"
    mode = getattr(settings, "openai_api_mode", "auto")

    use_responses = (
        mode == "responses"
        or (mode == "auto" and model.startswith("gpt-5"))
    )
    _debug_log(
        f"openai_mode_{int(__import__('time').time() * 1000)}",
        "H3", "services/provider_router.py:_call_openai",
        "openai mode selection",
        {"model": model, "modeSetting": mode, "useResponses": use_responses},
    )

    if use_responses:
        return _call_openai_responses(messages, model, timeout, max_tokens=max_tokens)
    return _call_openai_chat(messages, model, timeout, max_tokens=max_tokens)


def _call_openai_chat(messages: list[dict], model: str, timeout: int, max_tokens: int = 16000) -> LLMResult:
    """OpenAI Chat Completions — /v1/chat/completions."""
    endpoint = settings.openai_endpoint or "https://api.openai.com/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.openai_api_key}",
    }
    token_key = "max_completion_tokens" if model.startswith("gpt-5") or model.startswith("o") else "max_tokens"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.4,
        token_key: max_tokens,
    }
    _debug_log(
        f"openai_chat_{int(__import__('time').time() * 1000)}",
        "H4", "services/provider_router.py:_call_openai_chat",
        "openai chat request dispatch",
        {"endpoint": endpoint, "model": model, "messageCount": len(messages)},
    )
    resp = httpx.post(endpoint, json=payload, headers=headers, timeout=timeout)
    _debug_log(
        f"openai_chat_{int(__import__('time').time() * 1000)}",
        "H4", "services/provider_router.py:_call_openai_chat",
        "openai chat response",
        {"statusCode": resp.status_code},
    )
    resp.raise_for_status()
    content: str = resp.json()["choices"][0]["message"]["content"]
    return LLMResult(content=content, provider="openai", model_mode="openai",
                     fallback_used=False, fallback_reason="")


def _call_openai_responses(messages: list[dict], model: str, timeout: int, max_tokens: int = 16000) -> LLMResult:
    """OpenAI Responses API — /v1/responses (GPT-5 family)."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.openai_api_key}",
    }

    input_items: list[dict] = []
    instructions: Optional[str] = None
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            instructions = content
        else:
            input_items.append({"role": role, "content": content})

    payload: dict = {"model": model, "input": input_items, "max_output_tokens": max_tokens}
    if instructions:
        payload["instructions"] = instructions

    _debug_log(
        f"openai_resp_{int(__import__('time').time() * 1000)}",
        "H5", "services/provider_router.py:_call_openai_responses",
        "openai responses request dispatch",
        {"endpoint": "https://api.openai.com/v1/responses", "model": model,
         "inputCount": len(input_items), "hasInstructions": bool(instructions)},
    )
    resp = httpx.post("https://api.openai.com/v1/responses",
                      json=payload, headers=headers, timeout=timeout)
    _debug_log(
        f"openai_resp_{int(__import__('time').time() * 1000)}",
        "H5", "services/provider_router.py:_call_openai_responses",
        "openai responses response",
        {"statusCode": resp.status_code},
    )
    resp.raise_for_status()
    body = resp.json()

    content = body.get("output_text", "")
    if not content:
        for item in body.get("output", []):
            if item.get("type") == "message":
                for part in item.get("content", []):
                    if part.get("type") in ("output_text", "text"):
                        content += part.get("text", "")
            elif item.get("type") == "text":
                content += item.get("text", "")
            if not content:
                for part in item.get("content", []):
                    if part.get("type") == "output_text":
                        content += part.get("text", "")

    if not content:
        raise ValueError(
            f"Responses API returned no text content. body keys: {list(body.keys())}"
        )

    return LLMResult(content=content, provider="openai", model_mode="openai_responses",
                     fallback_used=False, fallback_reason="")
