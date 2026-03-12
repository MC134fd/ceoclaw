"""
QualityAuditorNode  – v0.7.

Runs the quality_audit_tool against the current product's landing page,
persists the scorecard, writes learnings to memory, and returns prioritised
iteration tasks for the next cycle.

Node contract output keys:
    executor_result, quality_audit, iteration_tasks, consecutive_failures
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.runnables import RunnableConfig

from agents import CEOClawState
from core.prompts import ExecutorOutput
from data.database import log_node_finish, log_node_start, utc_now
from tools.quality_audit_tool import quality_audit_tool

_EXECUTOR_KEY = "quality_auditor"


def quality_auditor_node(state: CEOClawState, config: RunnableConfig) -> dict[str, Any]:
    """QualityAuditorNode: audit product page and produce improvement plan."""
    action = "quality_audit"
    cycle_count = state.get("cycle_count", 0)
    run_id = state["run_id"]

    exec_id = log_node_start(
        run_id=run_id,
        cycle_count=cycle_count,
        node_name="quality_auditor",
        input_summary=f"action={action} cycle={cycle_count}",
    )

    failures: dict[str, int] = dict(state.get("consecutive_failures") or {})

    try:
        result = _dispatch(state, run_id, cycle_count)
        failures[_EXECUTOR_KEY] = 0
        log_node_finish(
            exec_id,
            output_summary=result["executor_result"]["execution_status"],
        )
        return {**result, "consecutive_failures": failures}
    except Exception as exc:  # noqa: BLE001
        failures[_EXECUTOR_KEY] = failures.get(_EXECUTOR_KEY, 0) + 1
        error_entry = {"node": "quality_auditor", "error": str(exc), "timestamp": utc_now()}
        log_node_finish(exec_id, output_summary=f"error:{exc}", status="failed")
        return {
            "errors": [error_entry],
            "executor_result": ExecutorOutput(
                action_taken=action, execution_status="failed", error_code=str(exc)
            ).model_dump(),
            "consecutive_failures": failures,
        }


def _dispatch(
    state: CEOClawState, run_id: str, cycle_count: int
) -> dict[str, Any]:
    product_name = _resolve_product_name(state)

    raw = quality_audit_tool.invoke({
        "product_name": product_name,
        "run_id": run_id,
        "cycle_count": cycle_count,
    })
    audit = json.loads(raw)

    score = audit.get("score", 0)
    grade = audit.get("grade", "F")
    defects = audit.get("critical_defects", [])
    improvement_plan = audit.get("improvement_plan", [])

    # Write audit learnings to persistent memory so next planner cycle can use them
    _write_audit_memory(run_id, score, grade, defects, improvement_plan)

    # Build iteration tasks from improvement plan
    iteration_tasks = [
        f"[quality_fix] {task}" for task in improvement_plan[:5]
    ]

    er = ExecutorOutput(
        action_taken="quality_audit",
        artifacts_created=["quality_audit_report"],
        metrics_delta={"quality_score": score, "premium_score": audit.get("premium_score", 0)},
        execution_status="completed",
        detail={
            "score": score,
            "grade": grade,
            "critical_defects": defects,
            "improvement_plan": improvement_plan,
            "scorecard": audit.get("scorecard", {}),
        },
    )

    return {
        "executor_result": er.model_dump(),
        "quality_audit": audit,
        "iteration_tasks": iteration_tasks,
    }


def _resolve_product_name(state: CEOClawState) -> str:
    intent = state.get("product_intent") or {}
    if intent.get("product_name"):
        return intent["product_name"]
    if state.get("active_product"):
        return state["active_product"].get("name", "CEOClaw MVP")
    return "CEOClaw MVP"


def _write_audit_memory(
    run_id: str,
    score: int,
    grade: str,
    defects: list[str],
    improvements: list[str],
) -> None:
    """Persist audit insights so the planner can reference them next cycle."""
    try:
        from core.memory_store import build_memory_store
        store = build_memory_store()
        store.set(
            "last_quality_score",
            f"{score}/100 grade={grade}",
            namespace=run_id,
        )
        if defects:
            store.set(
                "critical_defects",
                "; ".join(defects[:3]),
                namespace=run_id,
            )
        if improvements:
            store.set(
                "top_improvement",
                improvements[0],
                namespace=run_id,
            )
    except Exception:
        pass  # Memory failures must never break the node
