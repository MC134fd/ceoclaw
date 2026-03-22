"""
FLock / OpenClaw model adapter — the canonical OpenClaw integration point.

This module wraps the FLock HTTP API as a LangChain ``BaseChatModel``.
All CEOClaw model calls go through ``FlockChatModel``.

Features:
  - Retry logic with exponential back-off
  - Deterministic template fallback on retry exhaustion (``[FALLBACK]`` prefix)
  - Structured ``response_metadata`` on every ``AIMessage``:
      model_mode, fallback_used, fallback_reason,
      tokens_estimated, external_calls_delta
"""

import json
import logging
import time
from urllib.parse import urlparse
from typing import Any, Iterator, Optional

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from config.settings import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Deterministic template fallback library
# ---------------------------------------------------------------------------

_DOMAIN_CYCLE = ["product", "marketing", "sales", "ops"]

_PLANNER_TEMPLATES = [
    {
        "selected_domain": "product",
        "selected_action": "build_landing_page",
        "strategy_rationale": "Build a landing page to establish online presence.",
        "priority_score": 0.90,
    },
    {
        "selected_domain": "marketing",
        "selected_action": "run_seo_analysis",
        "strategy_rationale": "Optimise landing page for organic search traffic.",
        "priority_score": 0.80,
    },
    {
        "selected_domain": "sales",
        "selected_action": "create_outreach_campaign",
        "strategy_rationale": "Reach out to early adopters to generate first MRR.",
        "priority_score": 0.85,
    },
    {
        "selected_domain": "ops",
        "selected_action": "record_baseline_metrics",
        "strategy_rationale": "Capture baseline metrics before next growth cycle.",
        "priority_score": 0.70,
    },
]

_EVALUATOR_TEMPLATE = {
    "kpi_snapshot": {"mrr": 0.0, "signups": 0, "traffic": 0},
    "progress_score": 0.0,
    "recommendation": "Continue iterating — no revenue yet.",
    "risk_flags": [],
}


def _template_planner_response(cycle_index: int) -> str:
    template = _PLANNER_TEMPLATES[cycle_index % len(_PLANNER_TEMPLATES)]
    return json.dumps(template)


def _template_evaluator_response(progress_score: float = 0.0) -> str:
    payload = dict(_EVALUATOR_TEMPLATE)
    payload["progress_score"] = round(progress_score, 4)
    return json.dumps(payload)


def _estimate_tokens(messages: list[BaseMessage]) -> int:
    """Rough token estimate: ~1.3 tokens per word across all messages."""
    total_words = sum(
        len(m.content.split()) if isinstance(m.content, str) else 0
        for m in messages
    )
    return int(total_words * 1.3)


def _classify_prompt(messages: list[BaseMessage]) -> str:
    """Heuristically detect whether this is a planner or evaluator call."""
    combined = " ".join(
        m.content if isinstance(m.content, str) else ""
        for m in messages
    ).lower()
    if "evaluat" in combined or "kpi" in combined or "progress" in combined:
        return "evaluator"
    return "planner"


# ---------------------------------------------------------------------------
# FlockChatModel
# ---------------------------------------------------------------------------

class FlockChatModel(BaseChatModel):
    """LangChain BaseChatModel adapter for the FLock API.

    Attributes:
        endpoint:       FLock chat completions URL.
        api_key:        API key (sent according to auth_strategy).
        model:          Model name sent in the request payload.
        auth_strategy:  Header strategy: "both" | "bearer" | "litellm".
        timeout:        HTTP request timeout in seconds.
        max_retries:    Number of retries on transient failures.
        cycle_index:    Tracks which fallback template to use (incremented externally).
    """

    endpoint: str = Field(default_factory=lambda: settings.flock_endpoint)
    api_key: str = Field(default_factory=lambda: settings.flock_api_key)
    model: str = Field(default_factory=lambda: settings.flock_model)
    auth_strategy: str = Field(default_factory=lambda: settings.flock_auth_strategy)
    timeout: int = Field(default_factory=lambda: settings.flock_timeout)
    max_retries: int = Field(default_factory=lambda: settings.flock_max_retries)
    cycle_index: int = Field(default=0)

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        self._log_startup()

    def _log_startup(self) -> None:
        host = urlparse(self.endpoint).netloc or self.endpoint or "(no endpoint set)"
        strategy = self.auth_strategy
        if self.api_key:
            auth_desc = f"key=*** strategy={strategy}"
        else:
            auth_desc = "key=(none)"
        if not self.endpoint:
            logger.warning(
                "[FLock] mode=LIVE but endpoint is empty — "
                "calls will fail and activate FALLBACK"
            )
        else:
            logger.info(
                "[FLock] mode=LIVE  endpoint=%s  model=%s  auth=%s",
                host, self.model, auth_desc,
            )

    @property
    def _llm_type(self) -> str:
        return "flock"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {
            "model_name": self.model,
            "endpoint": self.endpoint,
            "auth_strategy": self.auth_strategy,
        }

    # ------------------------------------------------------------------
    # Core generate
    # ------------------------------------------------------------------

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                return self._http_generate(messages)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.debug(
                    "[FLock] attempt %d/%d failed: %s: %s",
                    attempt + 1, self.max_retries, type(exc).__name__, exc,
                )
                if attempt < self.max_retries - 1:
                    time.sleep(0.5 * (attempt + 1))

        # All retries exhausted — fall back to deterministic templates.
        fallback_reason = f"{type(last_error).__name__}: {last_error}"
        logger.warning(
            "[FLock] FALLBACK activated after %d retries — "
            "last error: %s. "
            "Responses will be tagged [FALLBACK]. "
            "Check endpoint=%r model=%r",
            self.max_retries,
            fallback_reason,
            self.endpoint or "(empty)",
            self.model,
        )
        return self._template_generate(
            messages,
            prefix="[FALLBACK] ",
            model_mode="fallback",
            fallback_reason=fallback_reason,
            external_calls_delta=self.max_retries,
        )

    def _http_generate(self, messages: list[BaseMessage]) -> ChatResult:
        """Call the FLock HTTP endpoint."""
        if not self.endpoint:
            raise ValueError(
                "FLOCK_ENDPOINT is not set. "
                "Set it in .env or pass endpoint= to FlockChatModel."
            )

        payload = {
            "model": self.model,
            "messages": [
                {"role": _lc_role(m), "content": m.content}
                for m in messages
            ],
            "temperature": 0.2,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            strategy = self.auth_strategy
            if strategy in ("bearer", "both"):
                headers["Authorization"] = f"Bearer {self.api_key}"
            if strategy in ("litellm", "both"):
                headers["x-litellm-api-key"] = self.api_key

        response = httpx.post(
            self.endpoint,
            json=payload,
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()

        # Parse response — raise ValueError with detail on unexpected structure
        try:
            data = response.json()
            content: str = data["choices"][0]["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            raise ValueError(
                f"Unexpected API response structure ({type(exc).__name__}: {exc}). "
                f"Status={response.status_code}. "
                f"Body={response.text[:300]!r}"
            ) from exc

        tokens_est = _estimate_tokens(messages) + int(len(content.split()) * 1.3)
        return _make_result(content, metadata={
            "model_mode": "live",
            "fallback_used": False,
            "fallback_reason": None,
            "tokens_estimated": tokens_est,
            "external_calls_delta": 1,
        })

    def _template_generate(
        self,
        messages: list[BaseMessage],
        prefix: str = "",
        model_mode: str = "fallback",
        fallback_reason: Optional[str] = None,
        external_calls_delta: int = 0,
    ) -> ChatResult:
        """Return a deterministic response without making any HTTP call."""
        prompt_type = _classify_prompt(messages)
        if prompt_type == "evaluator":
            content = prefix + _template_evaluator_response()
        else:
            content = prefix + _template_planner_response(self.cycle_index)
        return _make_result(content, metadata={
            "model_mode": model_mode,
            "fallback_used": model_mode == "fallback",
            "fallback_reason": fallback_reason,
            "tokens_estimated": 0,
            "external_calls_delta": external_calls_delta,
        })

    # ------------------------------------------------------------------
    # Stream (delegates to _generate for simplicity)
    # ------------------------------------------------------------------

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Iterator[ChatGeneration]:
        result = self._generate(messages, stop=stop, run_manager=run_manager)
        yield from result.generations


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lc_role(message: BaseMessage) -> str:
    role_map = {
        "human": "user",
        "ai": "assistant",
        "system": "system",
    }
    return role_map.get(message.type, "user")


def _make_result(content: str, metadata: dict | None = None) -> ChatResult:
    msg = AIMessage(content=content, response_metadata=metadata or {})
    return ChatResult(generations=[ChatGeneration(message=msg)])


def get_model(cycle_index: int = 0) -> FlockChatModel:
    """Factory that returns a configured FlockChatModel instance."""
    return FlockChatModel(cycle_index=cycle_index)
