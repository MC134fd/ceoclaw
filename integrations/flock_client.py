"""
FLock LangChain-compatible chat model adapter.

FlockChatModel wraps the FLock HTTP API as a LangChain BaseChatModel so
it can be used interchangeably with any other LangChain LLM.  When
``mock_mode=True`` (or when the endpoint is unreachable), deterministic
fallback responses are returned and tagged with ``[MOCK]`` in the content.
"""

import json
import time
from typing import Any, Iterator, Optional

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from config.settings import settings


# ---------------------------------------------------------------------------
# Deterministic mock response library
# ---------------------------------------------------------------------------

_DOMAIN_CYCLE = ["product", "marketing", "sales", "ops"]

_MOCK_PLANNER_TEMPLATES = [
    {
        "selected_domain": "product",
        "selected_action": "build_landing_page",
        "strategy_rationale": "[MOCK] Build a landing page to establish online presence.",
        "priority_score": 0.90,
    },
    {
        "selected_domain": "marketing",
        "selected_action": "run_seo_analysis",
        "strategy_rationale": "[MOCK] Optimise landing page for organic search traffic.",
        "priority_score": 0.80,
    },
    {
        "selected_domain": "sales",
        "selected_action": "create_outreach_campaign",
        "strategy_rationale": "[MOCK] Reach out to early adopters to generate first MRR.",
        "priority_score": 0.85,
    },
    {
        "selected_domain": "ops",
        "selected_action": "record_baseline_metrics",
        "strategy_rationale": "[MOCK] Capture baseline metrics before next growth cycle.",
        "priority_score": 0.70,
    },
]

_MOCK_EVALUATOR_TEMPLATE = {
    "kpi_snapshot": {"mrr": 0.0, "signups": 0, "traffic": 0},
    "progress_score": 0.0,
    "recommendation": "[MOCK] Continue iterating — no revenue yet.",
    "risk_flags": [],
}


def _mock_planner_response(cycle_index: int) -> str:
    template = _MOCK_PLANNER_TEMPLATES[cycle_index % len(_MOCK_PLANNER_TEMPLATES)]
    return json.dumps(template)


def _mock_evaluator_response(progress_score: float = 0.0) -> str:
    payload = dict(_MOCK_EVALUATOR_TEMPLATE)
    payload["progress_score"] = round(progress_score, 4)
    return json.dumps(payload)


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
        endpoint:    FLock chat completions URL.
        api_key:     API key sent in the Authorization header.
        timeout:     HTTP request timeout in seconds.
        max_retries: Number of retries on transient failures.
        mock_mode:   When True, skip HTTP and return deterministic responses.
        cycle_index: Tracks which mock template to use (incremented externally).
    """

    endpoint: str = Field(default_factory=lambda: settings.flock_endpoint)
    api_key: str = Field(default_factory=lambda: settings.flock_api_key)
    timeout: int = Field(default_factory=lambda: settings.flock_timeout)
    max_retries: int = Field(default_factory=lambda: settings.flock_max_retries)
    mock_mode: bool = Field(default_factory=lambda: settings.flock_mock_mode)
    cycle_index: int = Field(default=0)

    @property
    def _llm_type(self) -> str:
        return "flock"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {
            "model_name": "flock",
            "endpoint": self.endpoint,
            "mock_mode": self.mock_mode,
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
        if self.mock_mode:
            return self._mock_generate(messages)

        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                return self._http_generate(messages)
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                last_error = exc
                if attempt < self.max_retries - 1:
                    time.sleep(0.5 * (attempt + 1))

        # All retries exhausted – fall back to mock with warning marker
        return self._mock_generate(messages, prefix="[FALLBACK] ")

    def _http_generate(self, messages: list[BaseMessage]) -> ChatResult:
        """Call the FLock HTTP endpoint."""
        payload = {
            "model": "flock-default",
            "messages": [
                {"role": _lc_role(m), "content": m.content}
                for m in messages
            ],
            "temperature": 0.2,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        response = httpx.post(
            self.endpoint,
            json=payload,
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        content: str = data["choices"][0]["message"]["content"]
        return _make_result(content)

    def _mock_generate(
        self,
        messages: list[BaseMessage],
        prefix: str = "",
    ) -> ChatResult:
        """Return a deterministic response without making any HTTP call."""
        prompt_type = _classify_prompt(messages)
        if prompt_type == "evaluator":
            content = prefix + _mock_evaluator_response()
        else:
            content = prefix + _mock_planner_response(self.cycle_index)
        return _make_result(content)

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


def _make_result(content: str) -> ChatResult:
    return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])


def get_model(mock_mode: bool = False, cycle_index: int = 0) -> FlockChatModel:
    """Factory that returns a configured FlockChatModel instance."""
    return FlockChatModel(mock_mode=mock_mode, cycle_index=cycle_index)
