"""
SalesExecutorNode  – v0.3 hardened.

Permitted tools: outreach_tool.
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
from tools.outreach_tool import outreach_tool

_EXECUTOR_KEY = "sales_executor"

_DEFAULT_TARGETS = [
    "indie hackers community",
    "product hunt followers",
    "startup founders on Twitter",
    "YC alumni network",
    "early adopter mailing list",
]

_DEFAULT_MESSAGE = (
    "Hi {target}, I'm building {product} — a tool for founders to hit "
    "$100 MRR autonomously. Would love your feedback. Reply to learn more!"
)


def sales_executor_node(state: CEOClawState, config: RunnableConfig) -> dict[str, Any]:
    """SalesExecutorNode: create and persist outreach messages."""
    action = state.get("selected_action", "create_outreach_campaign")
    cycle_count = state.get("cycle_count", 0)
    run_id = state["run_id"]

    exec_id = log_node_start(
        run_id=run_id, cycle_count=cycle_count,
        node_name="sales_executor", input_summary=f"action={action}",
    )

    failures: dict[str, int] = dict(state.get("consecutive_failures") or {})

    try:
        result = _dispatch(state, action, run_id, cycle_count)
        failures[_EXECUTOR_KEY] = 0
        log_node_finish(exec_id, output_summary=result["executor_result"]["execution_status"])
        return {**result, "consecutive_failures": failures}
    except Exception as exc:  # noqa: BLE001
        failures[_EXECUTOR_KEY] = failures.get(_EXECUTOR_KEY, 0) + 1
        error_entry = {"node": "sales_executor", "error": str(exc), "timestamp": utc_now()}
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
    offset = max((cycle_count - 1) % len(_DEFAULT_TARGETS), 0)
    targets = _DEFAULT_TARGETS[offset: offset + 2] or _DEFAULT_TARGETS[:2]

    raw = outreach_tool.invoke({
        "product_name": product_name,
        "targets": targets,
        "message_template": _DEFAULT_MESSAGE,
        "channel": "email",
    })
    data = json.loads(raw)

    persist_artifact(
        run_id=run_id, cycle_count=cycle_count,
        node_name="sales_executor", artifact_type="outreach_batch",
        content_summary=f"count={data.get('created_count')} targets={targets}",
    )

    er = ExecutorOutput(
        action_taken=action,
        artifacts_created=[f"outreach:{t}" for t in targets],
        metrics_delta={"outreach_sent": data.get("created_count", 0)},
        execution_status="completed",
        detail=data,
    )
    return {"executor_result": er.model_dump()}


def _resolve_product_name(state: CEOClawState) -> str:
    if state.get("active_product"):
        return state["active_product"].get("name", "CEOClaw MVP")
    return "CEOClaw MVP"


def _error_result(action: str, error: str) -> dict[str, Any]:
    return ExecutorOutput(
        action_taken=action, execution_status="failed", error_code=error
    ).model_dump()
