"""
MarketingExecutorNode  – v0.3 hardened.

Permitted tools: seo_tool, analytics_tool.
Persists artifacts.  Updates consecutive_failures circuit-breaker state.

Node contract output keys:
    executor_result, consecutive_failures
"""

import json
from typing import Any

from langchain_core.runnables import RunnableConfig

from agents import CEOClawState
from core.prompts import ExecutorOutput
from data.database import log_node_finish, log_node_start, persist_artifact, utc_now
from tools.analytics_tool import analytics_tool
from tools.seo_tool import seo_tool

_EXECUTOR_KEY = "marketing_executor"


def marketing_executor_node(state: CEOClawState, config: RunnableConfig) -> dict[str, Any]:
    """MarketingExecutorNode: run SEO and analytics experiments."""
    action = state.get("selected_action", "run_seo_analysis")
    cycle_count = state.get("cycle_count", 0)
    run_id = state["run_id"]

    exec_id = log_node_start(
        run_id=run_id, cycle_count=cycle_count,
        node_name="marketing_executor", input_summary=f"action={action}",
    )

    failures: dict[str, int] = dict(state.get("consecutive_failures") or {})

    try:
        result = _dispatch(state, action, run_id, cycle_count)
        failures[_EXECUTOR_KEY] = 0
        log_node_finish(exec_id, output_summary=result["executor_result"]["execution_status"])
        return {**result, "consecutive_failures": failures}
    except Exception as exc:  # noqa: BLE001
        failures[_EXECUTOR_KEY] = failures.get(_EXECUTOR_KEY, 0) + 1
        error_entry = {"node": "marketing_executor", "error": str(exc), "timestamp": utc_now()}
        log_node_finish(exec_id, output_summary=f"error:{exc}", status="failed")
        return {
            "errors": [error_entry],
            "executor_result": _error_result(action, str(exc)),
            "consecutive_failures": failures,
        }


def _dispatch(
    state: CEOClawState, action: str, run_id: str, cycle_count: int
) -> dict[str, Any]:
    product_name = _resolve_product_name(state)
    artifacts: list[str] = []
    metrics_delta: dict[str, Any] = {}
    seo_data: dict[str, Any] = {}

    if state.get("active_product"):
        raw_seo = seo_tool.invoke({
            "product_name": product_name,
            "target_keyword": product_name.lower().replace(" ", "-"),
        })
        seo_data = json.loads(raw_seo)
        metrics_delta["seo_score"] = seo_data.get("seo_score", 0)
        artifacts.append("seo_report")
        persist_artifact(
            run_id=run_id, cycle_count=cycle_count,
            node_name="marketing_executor", artifact_type="seo_report",
            content_summary=f"score={seo_data.get('seo_score')} issues={len(seo_data.get('issues',[]))}",
        )

    raw_analytics = analytics_tool.invoke({"lookback": 3, "record_snapshot": False})
    analytics_data = json.loads(raw_analytics)
    analytics_latest = analytics_data.get("latest") or {}
    metrics_delta["traffic"] = analytics_latest.get("website_traffic", 0)

    persist_artifact(
        run_id=run_id, cycle_count=cycle_count,
        node_name="marketing_executor", artifact_type="analytics_snapshot",
        content_summary=analytics_data.get("summary", "no summary"),
    )
    artifacts.append("analytics_snapshot")

    er = ExecutorOutput(
        action_taken=action,
        artifacts_created=artifacts,
        metrics_delta=metrics_delta,
        execution_status="completed",
        detail={"seo": seo_data, "analytics_summary": analytics_data.get("summary", "")},
    )
    result: dict[str, Any] = {"executor_result": er.model_dump()}

    # Refresh latest_metrics from the analytics snapshot so evaluator sees
    # current DB state without requiring a full ops cycle.
    if analytics_latest:
        prev = state.get("latest_metrics") or {}
        result["latest_metrics"] = {
            "website_traffic": analytics_latest.get("website_traffic",
                                                     prev.get("website_traffic", 0)),
            "signups": analytics_latest.get("signups", prev.get("signups", 0)),
            "mrr": analytics_latest.get("mrr", prev.get("mrr", 0.0)),
            "conversion_rate": analytics_latest.get("conversion_rate",
                                                     prev.get("conversion_rate", 0.0)),
            "revenue": analytics_latest.get("revenue", prev.get("revenue", 0.0)),
        }

    return result


def _resolve_product_name(state: CEOClawState) -> str:
    if state.get("active_product"):
        return state["active_product"].get("name", "CEOClaw MVP")
    return "CEOClaw MVP"


def _error_result(action: str, error: str) -> dict[str, Any]:
    return ExecutorOutput(
        action_taken=action, execution_status="failed", error_code=error
    ).model_dump()
