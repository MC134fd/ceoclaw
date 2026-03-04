"""
CEOClaw centralized prompt templates and structured output parsers.

All node prompts live here.  Pydantic models enforce output shape;
safe_parse_* functions provide error-coded fallback on bad model output.
"""

import json
import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# KPI weighting constants
# ---------------------------------------------------------------------------

KPI_WEIGHTS: dict[str, float] = {
    "traffic": 0.10,
    "signups": 0.20,
    "revenue": 0.25,
    "mrr": 0.45,
}

# Normalization ceilings (what counts as "100%" for each non-MRR metric)
KPI_CEILINGS: dict[str, int] = {
    "traffic": 1000,
    "signups": 100,
}


# ---------------------------------------------------------------------------
# Error codes
# ---------------------------------------------------------------------------

class ParseErrorCode:
    OK = "OK"
    JSON_DECODE = "ERR_JSON_DECODE"
    VALIDATION = "ERR_VALIDATION"
    REGEX_FALLBACK = "ERR_REGEX_FALLBACK"
    TOTAL_FAILURE = "ERR_TOTAL_FAILURE"


# ---------------------------------------------------------------------------
# Pydantic output models
# ---------------------------------------------------------------------------

class PlannerOutput(BaseModel):
    """Structured output contract for PlannerNode."""

    selected_domain: Literal["product", "marketing", "sales", "ops"] = "product"
    selected_action: str = "default_action"
    strategy_rationale: str = ""
    priority_score: float = Field(default=0.5, ge=0.0, le=1.0)
    stagnation_override: Optional[str] = None


class ExecutorOutput(BaseModel):
    """Structured output contract for all ExecutorNodes."""

    action_taken: str = ""
    artifacts_created: list[str] = Field(default_factory=list)
    metrics_delta: dict[str, Any] = Field(default_factory=dict)
    execution_status: Literal["completed", "failed", "partial"] = "completed"
    error_code: Optional[str] = None
    detail: dict[str, Any] = Field(default_factory=dict)


class EvaluatorOutput(BaseModel):
    """Structured output contract for EvaluatorNode."""

    kpi_snapshot: dict[str, Any] = Field(default_factory=dict)
    progress_score: float = Field(default=0.0, ge=0.0, le=1.0)
    weighted_score: float = Field(default=0.0, ge=0.0, le=1.0)
    trend_direction: Literal["up", "down", "flat"] = "flat"
    recommendation: str = ""
    risk_flags: list[str] = Field(default_factory=list)


class StopCheckOutput(BaseModel):
    """Structured output contract for StopCheckNode."""

    should_stop: bool = False
    stop_reason: Optional[str] = None


class ParseResult(BaseModel):
    """Result envelope returned by all safe_parse_* functions."""

    success: bool
    error_code: str = ParseErrorCode.OK
    data: dict[str, Any] = Field(default_factory=dict)
    raw: str = ""


# ---------------------------------------------------------------------------
# JSON extraction helper
# ---------------------------------------------------------------------------

def _extract_json(content: str) -> tuple[bool, dict[str, Any]]:
    """Try to extract a JSON object from *content*.

    First attempts a direct ``json.loads``; if that fails, searches for the
    first ``{...}`` block using a regex and parses that.

    Returns:
        (success: bool, data: dict)
    """
    stripped = content.strip()
    try:
        return True, json.loads(stripped)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", stripped, re.DOTALL)
    if match:
        try:
            return True, json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return False, {}


# ---------------------------------------------------------------------------
# Safe parsers
# ---------------------------------------------------------------------------

def safe_parse_planner(content: str) -> ParseResult:
    """Parse PlannerOutput from raw model content.

    Falls back to regex domain extraction, then to default PlannerOutput.
    Always returns a ParseResult with ``data`` populated.
    """
    ok, raw_data = _extract_json(content)

    if not ok:
        # Try extracting domain keyword from free text
        domain_match = re.search(r"\b(product|marketing|sales|ops)\b", content.lower())
        domain = domain_match.group(1) if domain_match else "product"
        fallback = PlannerOutput(selected_domain=domain)  # type: ignore[arg-type]
        return ParseResult(
            success=False,
            error_code=ParseErrorCode.JSON_DECODE,
            data=fallback.model_dump(),
            raw=content,
        )

    try:
        output = PlannerOutput.model_validate(raw_data)
        return ParseResult(
            success=True,
            error_code=ParseErrorCode.OK,
            data=output.model_dump(),
            raw=content,
        )
    except Exception:
        # Partial extraction: use what we can from the raw dict
        domain = raw_data.get("selected_domain", "product")
        valid = {"product", "marketing", "sales", "ops"}
        if domain not in valid:
            domain = "product"
        fallback = PlannerOutput(
            selected_domain=domain,  # type: ignore[arg-type]
            selected_action=str(raw_data.get("selected_action", "default_action")),
            strategy_rationale=str(raw_data.get("strategy_rationale", "")),
            priority_score=float(raw_data.get("priority_score", 0.5)),
        )
        return ParseResult(
            success=False,
            error_code=ParseErrorCode.REGEX_FALLBACK,
            data=fallback.model_dump(),
            raw=content,
        )


def safe_parse_evaluator(
    content: str,
    current_mrr: float = 0.0,
    goal_mrr: float = 100.0,
    current_metrics: Optional[dict[str, Any]] = None,
) -> ParseResult:
    """Parse EvaluatorOutput from raw model content.

    Always populates ``weighted_score`` and ``trend_direction`` even on
    partial parse.
    """
    metrics = current_metrics or {}
    progress = compute_progress_score(current_mrr, goal_mrr)
    weighted = compute_weighted_score(metrics, goal_mrr)

    ok, raw_data = _extract_json(content)

    if not ok:
        fallback = EvaluatorOutput(
            kpi_snapshot={"mrr": current_mrr, "signups": 0, "traffic": 0, "revenue": 0.0},
            progress_score=progress,
            weighted_score=weighted,
        )
        return ParseResult(
            success=False,
            error_code=ParseErrorCode.JSON_DECODE,
            data=fallback.model_dump(),
            raw=content,
        )

    try:
        output = EvaluatorOutput.model_validate(raw_data)
        return ParseResult(
            success=True,
            error_code=ParseErrorCode.OK,
            data=output.model_dump(),
            raw=content,
        )
    except Exception:
        fallback = EvaluatorOutput(
            kpi_snapshot=raw_data.get(
                "kpi_snapshot",
                {"mrr": current_mrr, "signups": 0, "traffic": 0, "revenue": 0.0},
            ),
            progress_score=float(raw_data.get("progress_score", progress)),
            weighted_score=float(raw_data.get("weighted_score", weighted)),
            trend_direction=raw_data.get("trend_direction", "flat"),
            recommendation=str(raw_data.get("recommendation", "Continue iterating.")),
            risk_flags=list(raw_data.get("risk_flags", [])),
        )
        return ParseResult(
            success=False,
            error_code=ParseErrorCode.VALIDATION,
            data=fallback.model_dump(),
            raw=content,
        )


# ---------------------------------------------------------------------------
# KPI computation
# ---------------------------------------------------------------------------

def compute_weighted_score(metrics: dict[str, Any], goal_mrr: float) -> float:
    """Return a weighted 0.0–1.0 KPI progress score.

    Weights defined in ``KPI_WEIGHTS``.  Traffic and signups are normalized
    against ``KPI_CEILINGS``; revenue and MRR against ``goal_mrr``.
    """
    if goal_mrr <= 0:
        return 0.0

    traffic_score = min(
        metrics.get("website_traffic", 0) / KPI_CEILINGS["traffic"], 1.0
    )
    signup_score = min(metrics.get("signups", 0) / KPI_CEILINGS["signups"], 1.0)
    revenue_score = min(metrics.get("revenue", 0.0) / goal_mrr, 1.0)
    mrr_score = min(metrics.get("mrr", 0.0) / goal_mrr, 1.0)

    score = (
        traffic_score * KPI_WEIGHTS["traffic"]
        + signup_score * KPI_WEIGHTS["signups"]
        + revenue_score * KPI_WEIGHTS["revenue"]
        + mrr_score * KPI_WEIGHTS["mrr"]
    )
    return round(min(score, 1.0), 4)


def compute_progress_score(current_mrr: float, goal_mrr: float) -> float:
    """Return a simple 0.0–1.0 MRR-only progress score."""
    if goal_mrr <= 0:
        return 0.0
    return round(min(current_mrr / goal_mrr, 1.0), 4)


def compute_trend(
    current_score: float, previous_score: float
) -> Literal["up", "down", "flat"]:
    """Determine trend direction from two consecutive weighted scores."""
    delta = current_score - previous_score
    if delta > 0.005:
        return "up"
    if delta < -0.005:
        return "down"
    return "flat"


# ---------------------------------------------------------------------------
# Centralized prompt templates
# ---------------------------------------------------------------------------

PLANNER_SYSTEM_PROMPT = """\
You are the CEO of an early-stage startup.
Your goal is to reach {goal_mrr} USD monthly recurring revenue (MRR) as quickly as possible.

Current state:
- Cycle          : {cycle_count}
- MRR            : ${current_mrr:.2f} / ${goal_mrr:.2f}  ({progress_pct:.1f}% of goal)
- Weighted Score : {weighted_score:.3f}
- Signups        : {signups}
- Traffic        : {traffic}
- Active product : {active_product}
- Stagnant cycles: {stagnant_cycles}{stagnation_note}

Analyse the current state and decide which domain to focus on next.
Reply with ONLY a valid JSON object — no markdown, no prose:
{{
  "selected_domain": "<product|marketing|sales|ops>",
  "selected_action": "<concise snake_case action name>",
  "strategy_rationale": "<1-2 sentence rationale>",
  "priority_score": <float 0.0-1.0>
}}\
"""

EVALUATOR_SYSTEM_PROMPT = """\
You are a startup metrics analyst.
Evaluate the business state and return a structured assessment.

Goal MRR        : ${goal_mrr:.2f}
Current metrics : {metrics_json}
Weighted score  : {weighted_score:.4f}  (prev: {prev_score:.4f}, trend: {trend})
Executor result : {executor_result_json}
Cycle           : {cycle_count}

Reply with ONLY a valid JSON object — no markdown, no prose:
{{
  "kpi_snapshot": {{
    "mrr": <float>,
    "signups": <int>,
    "traffic": <int>,
    "revenue": <float>
  }},
  "progress_score": <float 0.0-1.0>,
  "weighted_score": <float 0.0-1.0>,
  "trend_direction": "<up|down|flat>",
  "recommendation": "<single action sentence>",
  "risk_flags": ["<flag>", ...]
}}\
"""


def build_planner_prompt(
    cycle_count: int,
    goal_mrr: float,
    latest_metrics: dict[str, Any],
    active_product: Any,
    stagnant_cycles: int = 0,
    stagnation_threshold: int = 3,
    weighted_score: float = 0.0,
) -> str:
    """Return a formatted planner system prompt."""
    m = latest_metrics or {}
    current_mrr = m.get("mrr", 0.0)
    progress_pct = (current_mrr / goal_mrr * 100) if goal_mrr > 0 else 0.0

    stagnation_note = ""
    if stagnant_cycles >= stagnation_threshold:
        stagnation_note = (
            f"\n⚠ STAGNATION ALERT: {stagnant_cycles} cycles with no MRR growth. "
            "You MUST choose a different domain than your last pick."
        )

    return PLANNER_SYSTEM_PROMPT.format(
        goal_mrr=goal_mrr,
        cycle_count=cycle_count,
        current_mrr=current_mrr,
        progress_pct=progress_pct,
        weighted_score=weighted_score,
        signups=m.get("signups", 0),
        traffic=m.get("website_traffic", 0),
        active_product=active_product or "none",
        stagnant_cycles=stagnant_cycles,
        stagnation_note=stagnation_note,
    )


def build_evaluator_prompt(
    cycle_count: int,
    goal_mrr: float,
    latest_metrics: dict[str, Any],
    executor_result: dict[str, Any],
    weighted_score: float = 0.0,
    prev_score: float = 0.0,
    trend: str = "flat",
) -> str:
    """Return a formatted evaluator system prompt."""
    return EVALUATOR_SYSTEM_PROMPT.format(
        goal_mrr=goal_mrr,
        metrics_json=json.dumps(latest_metrics or {}),
        executor_result_json=json.dumps(executor_result or {}),
        cycle_count=cycle_count,
        weighted_score=weighted_score,
        prev_score=prev_score,
        trend=trend,
    )
