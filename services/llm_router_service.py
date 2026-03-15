"""
LLM router service — re-exports provider_router and adds provider health check.
"""

from __future__ import annotations

import logging
import json
import time
from pathlib import Path
from typing import Any

import httpx

from config.settings import settings
from services.provider_router import LLMResult, call_llm  # noqa: F401 — re-export

logger = logging.getLogger(__name__)

_HEALTH_TIMEOUT = 5  # seconds
_DEBUG_LOG_PATH = Path("/Users/marcuschien/code/MC134fd/ceoclaw/.cursor/debug-ae58c9.log")


def _debug_log(message: str, data: dict[str, Any]) -> None:
    # #region agent log
    try:
        payload = {
            "sessionId": "ae58c9",
            "runId": f"health_{int(time.time() * 1000)}",
            "hypothesisId": "H8",
            "location": "services/llm_router_service.py:check_provider_health",
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        _DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _DEBUG_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload) + "\n")
    except Exception:
        pass
    # #endregion


def check_provider_health() -> dict[str, Any]:
    """Check which providers are configured and reachable.

    Flock is permanently disabled in the runtime path; its entry is always
    returned as disabled for backward compat with clients that read the key.

    Returns:
        {
            "flock": {"configured": False, "reachable": False, "error": "disabled"},
            "openai": {"configured": bool, "reachable": bool, "error": str | None},
            "active_provider": "openai" | "mock",
        }
    """
    reload_fn = getattr(settings, "reload", None)
    if callable(reload_fn):
        reload_fn()

    openai_configured = bool(settings.openai_api_key)

    # --- Flock — always disabled in runtime path ---
    flock_status: dict[str, Any] = {
        "configured": False,
        "reachable": False,
        "error": "disabled",
    }

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

    # --- Active provider — only openai or mock ---
    if openai_configured and openai_reachable:
        active_provider = "openai"
    else:
        active_provider = "mock"

    result = {
        "flock": flock_status,
        "openai": {
            "configured": openai_configured,
            "reachable": openai_reachable,
            "error": openai_error,
        },
        "active_provider": active_provider,
    }
    _debug_log(
        "provider health snapshot",
        {
            "flockDisabled": True,
            "openaiConfigured": openai_configured,
            "openaiReachable": openai_reachable,
            "openaiError": openai_error,
            "activeProvider": active_provider,
        },
    )
    return result
