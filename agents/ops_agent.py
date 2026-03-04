"""
OpsExecutorNode  – v0.3 hardened.

Permitted tools: analytics_tool.
Acts as both routine ops and circuit-breaker recovery node.
Persists artifacts.  Updates consecutive_failures (resets all on recovery).

Node contract output keys:
    executor_result, latest_metrics, consecutive_failures
"""

import json
from typing import Any

from langchain_core.runnables import RunnableConfig

from agents import CEOClawState
from core.prompts import ExecutorOutput
from data.database import log_node_finish, log_node_start, persist_artifact, utc_now
from tools.analytics_tool import analytics_tool

_EXECUTOR_KEY = "ops_executor"


def ops_executor_node(state: CEOClawState, config: RunnableConfig) -> dict[str, Any]:
    """OpsExecutorNode: record metrics, produce analytics summary.

    Also acts as the circuit-breaker recovery node when ``circuit_breaker_active``
    is True — in which case all consecutive failure counters are reset.
    """
    action = state.get("selected_action", "record_baseline_metrics")
    cycle_count = state.get("cycle_count", 0)
    run_id = state["run_id"]
    cb_recovery = state.get("circuit_breaker_active", False)

    exec_id = log_node_start(
        run_id=run_id, cycle_count=cycle_count,
        node_name="ops_executor",
        input_summary=f"action={action} cb_recovery={cb_recovery}",
    )

    failures: dict[str, int] = dict(state.get("consecutive_failures") or {})

    try:
        result = _dispatch(state, action, run_id, cycle_count)
        failures[_EXECUTOR_KEY] = 0
        if cb_recovery:
            # Full reset of all circuit-breaker counters on recovery
            failures = {k: 0 for k in failures}
        log_node_finish(exec_id, output_summary=result["executor_result"]["execution_status"])
        return {**result, "consecutive_failures": failures, "circuit_breaker_active": False}
    except Exception as exc:  # noqa: BLE001
        failures[_EXECUTOR_KEY] = failures.get(_EXECUTOR_KEY, 0) + 1
        error_entry = {"node": "ops_executor", "error": str(exc), "timestamp": utc_now()}
        log_node_finish(exec_id, output_summary=f"error:{exc}", status="failed")
        return {
            "errors": [error_entry],
            "executor_result": _error_result(action, str(exc)),
            "consecutive_failures": failures,
        }


def _dispatch(
    state: CEOClawState, action: str, run_id: str, cycle_count: int
) -> dict[str, Any]:
    prev = state.get("latest_metrics") or {}

    base_traffic = prev.get("website_traffic", 0)
    base_signups = prev.get("signups", 0)
    base_mrr = prev.get("mrr", 0.0)

    new_traffic = base_traffic + (cycle_count * 10)
    new_signups = base_signups + max(cycle_count - 1, 0)
    new_mrr = round(base_mrr + (max(cycle_count - 2, 0) * 5.0), 2)

    raw = analytics_tool.invoke({
        "lookback": 5,
        "record_snapshot": True,
        "new_traffic": new_traffic,
        "new_signups": new_signups,
        "new_mrr": new_mrr,
    })
    data = json.loads(raw)
    latest = data.get("latest") or {}

    refreshed = {
        "website_traffic": latest.get("website_traffic", new_traffic),
        "signups": latest.get("signups", new_signups),
        "mrr": latest.get("mrr", new_mrr),
        "conversion_rate": latest.get("conversion_rate", 0.0),
        "revenue": latest.get("revenue", new_mrr),
    }

    persist_artifact(
        run_id=run_id, cycle_count=cycle_count,
        node_name="ops_executor", artifact_type="metrics_snapshot",
        content_summary=(
            f"traffic={refreshed['website_traffic']} "
            f"signups={refreshed['signups']} "
            f"mrr={refreshed['mrr']}"
        ),
    )

    er = ExecutorOutput(
        action_taken=action,
        artifacts_created=["metrics_snapshot"],
        metrics_delta=data.get("trend", {}),
        execution_status="completed",
        detail={"summary": data.get("summary", ""), "trend": data.get("trend", {})},
    )
    return {"latest_metrics": refreshed, "executor_result": er.model_dump()}


def _error_result(action: str, error: str) -> dict[str, Any]:
    return ExecutorOutput(
        action_taken=action, execution_status="failed", error_code=error
    ).model_dump()
