"""
ProductExecutorNode  – v0.3 hardened.

Permitted tools: website_builder, seo_tool.
Persists artifacts to SQLite.  Updates consecutive_failures circuit-breaker state.

Node contract output keys:
    executor_result, active_product, consecutive_failures
"""

import json
from typing import Any

from langchain_core.runnables import RunnableConfig

from agents import CEOClawState
from core.prompts import ExecutorOutput
from data.database import log_node_finish, log_node_start, persist_artifact, utc_now
from tools.seo_tool import seo_tool
from tools.website_builder import website_builder_tool

_EXECUTOR_KEY = "product_executor"


def product_executor_node(state: CEOClawState, config: RunnableConfig) -> dict[str, Any]:
    """ProductExecutorNode: build or refine the product."""
    action = state.get("selected_action", "build_landing_page")
    cycle_count = state.get("cycle_count", 0)
    run_id = state["run_id"]

    exec_id = log_node_start(
        run_id=run_id, cycle_count=cycle_count,
        node_name="product_executor", input_summary=f"action={action}",
    )

    failures: dict[str, int] = dict(state.get("consecutive_failures") or {})

    try:
        result = _dispatch(state, action, run_id, cycle_count)
        failures[_EXECUTOR_KEY] = 0  # reset on success
        log_node_finish(exec_id, output_summary=result["executor_result"]["execution_status"])
        return {**result, "consecutive_failures": failures}
    except Exception as exc:  # noqa: BLE001
        failures[_EXECUTOR_KEY] = failures.get(_EXECUTOR_KEY, 0) + 1
        error_entry = {"node": "product_executor", "error": str(exc), "timestamp": utc_now()}
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

    if "seo" in action.lower() or "optimis" in action.lower():
        raw = seo_tool.invoke({
            "product_name": product_name,
            "target_keyword": product_name.lower().replace(" ", "-"),
        })
        data = json.loads(raw)
        # Persist artifact
        persist_artifact(
            run_id=run_id, cycle_count=cycle_count,
            node_name="product_executor", artifact_type="seo_report",
            content_summary=f"score={data.get('seo_score')} keyword={data.get('keyword')}",
        )
        er = ExecutorOutput(
            action_taken=action,
            artifacts_created=["seo_report"],
            metrics_delta={"seo_score": data.get("seo_score", 0)},
            execution_status="completed",
            detail=data,
        )
        return {"executor_result": er.model_dump()}

    # Default: build/rebuild landing page
    raw = website_builder_tool.invoke({
        "product_name": product_name,
        "tagline": f"The smart way to solve your problem with {product_name}.",
        "features": ["Instant setup", "No credit card required", "Cancel anytime"],
        "cta_text": "Get Early Access",
    })
    data = json.loads(raw)
    page_path = data.get("path", "")

    # Persist artifact
    persist_artifact(
        run_id=run_id, cycle_count=cycle_count,
        node_name="product_executor", artifact_type="landing_page",
        path_or_hash=page_path,
        content_summary=f"product={product_name} slug={data.get('slug')}",
    )

    active_product = {"name": product_name, "landing_page_path": page_path, "status": "active"}
    er = ExecutorOutput(
        action_taken=action,
        artifacts_created=[page_path],
        metrics_delta={},
        execution_status="completed",
        detail=data,
    )
    return {"executor_result": er.model_dump(), "active_product": active_product}


def _resolve_product_name(state: CEOClawState) -> str:
    if state.get("active_product"):
        return state["active_product"].get("name", "CEOClaw MVP")
    return "CEOClaw MVP"


def _error_result(action: str, error: str) -> dict[str, Any]:
    return ExecutorOutput(
        action_taken=action, execution_status="failed", error_code=error
    ).model_dump()
