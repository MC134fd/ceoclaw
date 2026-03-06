"""
OpenClaw framework adapter.

DEPRECATED — not used in the live runtime.

The prompt templates, parsers, and heuristics here were superseded by
``core/prompts.py``, which adds Pydantic validation, weighted KPI scoring,
stagnation context, and structured error codes.  This file is kept for
reference only.  Do not import ``OpenClawAdapter`` in agent or core modules.

Runtime call stack (canonical):
    PlannerNode   → core/prompts.build_planner_prompt  + safe_parse_planner
    EvaluatorNode → core/prompts.build_evaluator_prompt + safe_parse_evaluator
    Model layer   → integrations/flock_client.FlockChatModel
"""

import json
import re
from typing import Any


# ---------------------------------------------------------------------------
# Prompt templates (OpenClaw canonical format)
# ---------------------------------------------------------------------------

PLANNER_SYSTEM_PROMPT = """You are the CEO of an early-stage startup.
Your goal is to reach {goal_mrr} USD monthly recurring revenue (MRR) as
quickly as possible.

Current state:
- Cycle: {cycle_count}
- MRR: {current_mrr}
- Signups: {signups}
- Traffic: {traffic}
- Active product: {active_product}

Analyse the current state and decide which domain to focus on next.
Reply with ONLY a JSON object matching this schema:
{{
  "selected_domain": "<product|marketing|sales|ops>",
  "selected_action": "<concise action name>",
  "strategy_rationale": "<1-2 sentence rationale>",
  "priority_score": <float 0.0-1.0>
}}"""

EVALUATOR_SYSTEM_PROMPT = """You are a startup metrics analyst.
Evaluate the latest business state and return a structured assessment.

Goal MRR: {goal_mrr}
Current metrics: {metrics_json}
Last executor result: {executor_result_json}
Cycle: {cycle_count}

Reply with ONLY a JSON object matching this schema:
{{
  "kpi_snapshot": {{
    "mrr": <float>,
    "signups": <int>,
    "traffic": <int>
  }},
  "progress_score": <float 0.0-1.0>,
  "recommendation": "<single action sentence>",
  "risk_flags": ["<flag>", ...]
}}"""


# ---------------------------------------------------------------------------
# OpenClaw base adapter
# ---------------------------------------------------------------------------

class OpenClawAdapter:
    """Base planning and evaluation framework extended by CEOClaw agents.

    CEOClaw's PlannerNode and EvaluatorNode delegate prompt construction and
    result parsing to this adapter, keeping node functions thin.
    """

    # ------------------------------------------------------------------
    # Prompt builders
    # ------------------------------------------------------------------

    def build_planner_prompt(
        self,
        cycle_count: int,
        goal_mrr: float,
        latest_metrics: dict[str, Any],
        active_product: dict[str, Any] | None,
    ) -> str:
        """Return the formatted planner system prompt."""
        m = latest_metrics or {}
        return PLANNER_SYSTEM_PROMPT.format(
            goal_mrr=goal_mrr,
            cycle_count=cycle_count,
            current_mrr=m.get("mrr", 0.0),
            signups=m.get("signups", 0),
            traffic=m.get("website_traffic", 0),
            active_product=active_product or "none",
        )

    def build_evaluator_prompt(
        self,
        cycle_count: int,
        goal_mrr: float,
        latest_metrics: dict[str, Any],
        executor_result: dict[str, Any],
    ) -> str:
        """Return the formatted evaluator system prompt."""
        return EVALUATOR_SYSTEM_PROMPT.format(
            goal_mrr=goal_mrr,
            metrics_json=json.dumps(latest_metrics or {}),
            executor_result_json=json.dumps(executor_result or {}),
            cycle_count=cycle_count,
        )

    # ------------------------------------------------------------------
    # Result parsers
    # ------------------------------------------------------------------

    def _extract_json(self, content: str) -> dict[str, Any]:
        """Try to parse JSON from model content, with regex fallback."""
        try:
            return json.loads(content.strip())
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
        return {}

    def parse_planner_response(self, content: str) -> dict[str, Any]:
        """Parse the model's planner JSON with domain validation."""
        data = self._extract_json(content)
        valid_domains = {"product", "marketing", "sales", "ops"}
        domain = data.get("selected_domain", "product")
        if domain not in valid_domains:
            domain = "product"
        return {
            "selected_domain": domain,
            "selected_action": str(data.get("selected_action", "default_action")),
            "strategy_rationale": str(data.get("strategy_rationale", "")),
            "priority_score": float(data.get("priority_score", 0.5)),
        }

    def parse_evaluator_response(
        self,
        content: str,
        current_mrr: float,
        goal_mrr: float,
    ) -> dict[str, Any]:
        """Parse the model's evaluator JSON with a safe numeric fallback."""
        data = self._extract_json(content)
        progress = self.compute_progress(current_mrr, goal_mrr)
        return {
            "kpi_snapshot": data.get("kpi_snapshot", {
                "mrr": current_mrr,
                "signups": 0,
                "traffic": 0,
            }),
            "progress_score": float(data.get("progress_score", progress)),
            "recommendation": str(data.get("recommendation", "Continue iterating.")),
            "risk_flags": list(data.get("risk_flags", [])),
        }

    # ------------------------------------------------------------------
    # Domain priority heuristics
    # ------------------------------------------------------------------

    def suggest_domain(
        self,
        cycle_count: int,
        current_mrr: float,
        has_product: bool,
    ) -> str:
        """Rule-based domain suggestion used as fallback when model fails."""
        if not has_product:
            return "product"
        return ["product", "marketing", "sales", "ops"][cycle_count % 4]

    # ------------------------------------------------------------------
    # Progress computation
    # ------------------------------------------------------------------

    def compute_progress(self, current_mrr: float, goal_mrr: float) -> float:
        """Return a 0.0–1.0 progress score toward the MRR goal."""
        if goal_mrr <= 0:
            return 0.0
        return round(min(current_mrr / goal_mrr, 1.0), 4)
