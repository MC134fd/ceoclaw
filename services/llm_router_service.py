"""
LLM router service — re-exports provider_router and adds provider health check.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from config.settings import settings
from services.provider_router import LLMResult, call_llm  # noqa: F401 — re-export

logger = logging.getLogger(__name__)

_HEALTH_TIMEOUT = 5  # seconds


def check_provider_health() -> dict[str, Any]:
    """Check which providers are configured and reachable.

    Returns:
        {
            "flock": {"configured": bool, "reachable": bool, "error": str | None},
            "openai": {"configured": bool, "reachable": bool, "error": str | None},
            "active_provider": "flock" | "openai" | "mock",
        }
    """
    reload_fn = getattr(settings, "reload", None)
    if callable(reload_fn):
        reload_fn()

    flock_configured = bool(settings.flock_endpoint and settings.flock_api_key and not settings.flock_mock_mode)
    openai_configured = bool(settings.openai_api_key)

    # --- Flock health ---
    flock_reachable = False
    flock_error: str | None = None
    if flock_configured:
        try:
            headers: dict[str, str] = {"Content-Type": "application/json"}
            strategy = settings.flock_auth_strategy
            if strategy in ("bearer", "both"):
                headers["Authorization"] = f"Bearer {settings.flock_api_key}"
            if strategy in ("litellm", "both"):
                headers["x-litellm-api-key"] = settings.flock_api_key

            # Minimal ping — send a tiny message and check for a valid HTTP response
            resp = httpx.post(
                settings.flock_endpoint,
                json={
                    "model": settings.flock_model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                },
                headers=headers,
                timeout=_HEALTH_TIMEOUT,
            )
            # Any 2xx or even 4xx means the server responded
            flock_reachable = resp.status_code < 500
            if not flock_reachable:
                flock_error = f"HTTP {resp.status_code}"
        except httpx.TimeoutException:
            flock_error = "timeout"
        except Exception as exc:
            flock_error = str(exc)[:120]
    else:
        flock_error = "not_configured" if not settings.flock_mock_mode else "mock_mode_enabled"

    # --- OpenAI health ---
    openai_reachable = False
    openai_error: str | None = None
    if openai_configured:
        try:
            endpoint = settings.openai_endpoint or "https://api.openai.com/v1/chat/completions"
            resp = httpx.post(
                endpoint,
                json={
                    "model": settings.openai_model or "gpt-4o-mini",
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                },
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {settings.openai_api_key}",
                },
                timeout=_HEALTH_TIMEOUT,
            )
            openai_reachable = resp.status_code < 500
            if not openai_reachable:
                openai_error = f"HTTP {resp.status_code}"
        except httpx.TimeoutException:
            openai_error = "timeout"
        except Exception as exc:
            openai_error = str(exc)[:120]
    else:
        openai_error = "not_configured"

    # --- Active provider ---
    if flock_configured and flock_reachable:
        active_provider = "flock"
    elif openai_configured and openai_reachable:
        active_provider = "openai"
    else:
        active_provider = "mock"

    return {
        "flock": {
            "configured": flock_configured,
            "reachable": flock_reachable,
            "error": flock_error,
        },
        "openai": {
            "configured": openai_configured,
            "reachable": openai_reachable,
            "error": openai_error,
        },
        "active_provider": active_provider,
    }
