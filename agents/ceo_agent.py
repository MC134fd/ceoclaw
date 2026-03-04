"""
PlannerNode (CEO agent)  – v0.3 hardened.

Uses centralized prompts from core/prompts.py and structured Pydantic parsing.
Implements stagnation override: if stagnant_cycles >= threshold, forces a
domain rotation away from the model's suggestion.

Node contract output keys:
    selected_domain, selected_action, strategy, cycle_count
"""

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from agents import CEOClawState
from core.prompts import (
    PlannerOutput,
    build_planner_prompt,
    safe_parse_planner,
)
from data.database import log_node_finish, log_node_start, utc_now
from integrations.flock_client import get_model

# Ordered domain rotation for stagnation override
_DOMAIN_CYCLE = ["product", "marketing", "sales", "ops"]


def planner_node(state: CEOClawState, config: RunnableConfig) -> dict[str, Any]:
    """PlannerNode: select the next domain and action.

    Invokes the FLock model with a rich context prompt, parses output via
    Pydantic, then applies stagnation override if applicable.
    """
    cfg = config.get("configurable", {})
    mock_mode: bool = cfg.get("mock_mode", False)
    stagnation_threshold: int = cfg.get("stagnation_threshold", 3)
    cycle_count: int = state.get("cycle_count", 0)
    stagnant_cycles: int = state.get("stagnant_cycles", 0)

    exec_id = log_node_start(
        run_id=state["run_id"],
        cycle_count=cycle_count,
        node_name="planner",
        input_summary=f"cycle={cycle_count} stagnant={stagnant_cycles} mock={mock_mode}",
    )

    try:
        result = _run_planner(state, mock_mode, cycle_count, stagnant_cycles, stagnation_threshold)
        log_node_finish(exec_id, output_summary=str(result.get("selected_action")))
        return result
    except Exception as exc:  # noqa: BLE001
        error_entry = {
            "node": "planner",
            "error": str(exc),
            "timestamp": utc_now(),
            "cycle": cycle_count,
        }
        fallback_domain = _stagnation_domain(stagnant_cycles, stagnation_threshold, "product")
        log_node_finish(exec_id, output_summary=f"fallback:{fallback_domain}", status="failed")
        return {
            "errors": [error_entry],
            "selected_domain": fallback_domain,
            "selected_action": "fallback_action",
            "strategy": {
                "strategy_rationale": f"Fallback due to planner error: {exc}",
                "priority_score": 0.5,
            },
            "cycle_count": cycle_count + 1,
        }


def _run_planner(
    state: CEOClawState,
    mock_mode: bool,
    cycle_count: int,
    stagnant_cycles: int,
    stagnation_threshold: int,
) -> dict[str, Any]:
    model = get_model(mock_mode=mock_mode, cycle_index=cycle_count)

    prompt = build_planner_prompt(
        cycle_count=cycle_count,
        goal_mrr=state.get("goal_mrr", 100.0),
        latest_metrics=state.get("latest_metrics", {}),
        active_product=state.get("active_product"),
        stagnant_cycles=stagnant_cycles,
        stagnation_threshold=stagnation_threshold,
        weighted_score=state.get("weighted_score", 0.0),
    )

    response = model.invoke([
        SystemMessage(content=prompt),
        HumanMessage(content="What should we do next? Reply with JSON only."),
    ])

    parse_result = safe_parse_planner(response.content)
    parsed: PlannerOutput = PlannerOutput.model_validate(parse_result.data)

    # Stagnation override: force a different domain if growth has stalled
    domain = parsed.selected_domain
    override_note: str | None = None
    if stagnant_cycles >= stagnation_threshold:
        rotated = _stagnation_domain(stagnant_cycles, stagnation_threshold, domain)
        if rotated != domain:
            override_note = (
                f"Stagnation override: switched {domain}→{rotated} "
                f"after {stagnant_cycles} stagnant cycles"
            )
            domain = rotated

    return {
        "selected_domain": domain,
        "selected_action": parsed.selected_action,
        "strategy": {
            "strategy_rationale": parsed.strategy_rationale,
            "priority_score": parsed.priority_score,
            "stagnation_override": override_note,
            "parse_error_code": parse_result.error_code,
        },
        "cycle_count": cycle_count + 1,
    }


def _stagnation_domain(
    stagnant_cycles: int, threshold: int, current_domain: str
) -> str:
    """Return an alternative domain when growth has stalled.

    Rotates through domains in order, skipping the current one.
    """
    if stagnant_cycles < threshold:
        return current_domain
    other = [d for d in _DOMAIN_CYCLE if d != current_domain]
    return other[stagnant_cycles % len(other)]
