"""
CEOClaw LangGraph agent loop  (v0.3 – hardened).

Graph topology (unchanged):
    START -> PlannerNode -> RouterNode -> ExecutorNode
          -> EvaluatorNode -> StopCheckNode -> (END | PlannerNode)

v0.3 additions:
  - RouterNode: circuit breaker (3 consecutive failures → ops recovery)
  - EvaluatorNode: weighted KPI score, stagnation tracking, cycle_score persistence
  - Mock evaluator: uses real metrics from state instead of hard-coded 0.0
  - Budget tracking: tokens_used, external_calls
  - export_run_summary(): markdown run report
"""

import hashlib
import uuid
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from agents import CEOClawState
from agents.ceo_agent import planner_node
from agents.marketing_agent import marketing_executor_node
from agents.ops_agent import ops_executor_node
from agents.product_agent import product_executor_node
from agents.sales_agent import sales_executor_node
from core.prompts import (
    EvaluatorOutput,
    build_evaluator_prompt,
    compute_progress_score,
    compute_trend,
    compute_weighted_score,
    safe_parse_evaluator,
)
from data.database import (
    finish_graph_run,
    init_db,
    log_node_finish,
    log_node_start,
    persist_cycle_score,
    save_checkpoint,
    start_graph_run,
    utc_now,
)
from integrations.flock_client import get_model

# Circuit-breaker threshold: consecutive failures before ops recovery
_CB_THRESHOLD = 3

# Stagnation threshold: cycles with no MRR growth before forced domain switch
_STAGNATION_THRESHOLD = 3


# ---------------------------------------------------------------------------
# RouterNode  (circuit breaker)
# ---------------------------------------------------------------------------

def router_node(state: CEOClawState, config: RunnableConfig) -> dict[str, Any]:
    """RouterNode: validate domain and enforce circuit breaker.

    If any executor has failed ``_CB_THRESHOLD`` consecutive times, override
    the domain to ``ops`` for a recovery cycle.
    """
    cycle_count = state.get("cycle_count", 0)
    domain = state.get("selected_domain", "product")
    consecutive_failures: dict[str, int] = state.get("consecutive_failures", {})

    exec_id = log_node_start(
        run_id=state["run_id"],
        cycle_count=cycle_count,
        node_name="router",
        input_summary=f"domain={domain}",
    )

    valid = {"product", "marketing", "sales", "ops"}
    if domain not in valid:
        domain = "product"

    # Circuit breaker check
    executor_key = f"{domain}_executor"
    cb_active = consecutive_failures.get(executor_key, 0) >= _CB_THRESHOLD
    if cb_active:
        domain = "ops"
        log_node_finish(exec_id, output_summary="circuit_breaker→ops_recovery")
        return {
            "selected_domain": "ops",
            "selected_action": "circuit_breaker_recovery",
            "circuit_breaker_active": True,
        }

    log_node_finish(exec_id, output_summary=f"routed_to={domain}_executor")
    return {"selected_domain": domain, "circuit_breaker_active": False}


def _route_from_router(state: CEOClawState) -> str:
    return f"{state.get('selected_domain', 'product')}_executor"


# ---------------------------------------------------------------------------
# EvaluatorNode
# ---------------------------------------------------------------------------

def evaluator_node(state: CEOClawState, config: RunnableConfig) -> dict[str, Any]:
    """EvaluatorNode: weighted KPI scoring, stagnation tracking, cycle persistence."""
    cfg = config.get("configurable", {})
    mock_mode: bool = cfg.get("mock_mode", False)
    cycle_count = state.get("cycle_count", 0)

    exec_id = log_node_start(
        run_id=state["run_id"],
        cycle_count=cycle_count,
        node_name="evaluator",
        input_summary=f"cycle={cycle_count} mock={mock_mode}",
    )

    metrics = state.get("latest_metrics") or {}
    current_mrr = metrics.get("mrr", 0.0)
    goal_mrr = state.get("goal_mrr", 100.0)
    prev_weighted = state.get("weighted_score", 0.0)
    last_mrr = state.get("last_mrr", 0.0)

    try:
        evaluation = _run_evaluator(state, mock_mode, prev_weighted)

        new_weighted = evaluation.get("weighted_score", 0.0)
        trend = evaluation.get("trend_direction", "flat")

        # Stagnation tracking
        if current_mrr <= last_mrr and cycle_count > 0:
            stagnant_cycles = state.get("stagnant_cycles", 0) + 1
        else:
            stagnant_cycles = 0

        # Risk flag for long stagnation
        if stagnant_cycles >= _STAGNATION_THRESHOLD:
            evaluation.setdefault("risk_flags", [])
            flag = f"stagnant_{stagnant_cycles}_cycles"
            if flag not in evaluation["risk_flags"]:
                evaluation["risk_flags"].append(flag)

        # Persist cycle score
        persist_cycle_score(
            run_id=state["run_id"],
            cycle_count=cycle_count,
            domain=state.get("selected_domain", "?"),
            action=state.get("selected_action", "?"),
            progress_score=evaluation.get("progress_score", 0.0),
            weighted_score=new_weighted,
            trend_direction=trend,
            mrr=current_mrr,
            traffic=metrics.get("website_traffic", 0),
            signups=metrics.get("signups", 0),
            stagnant_cycles=stagnant_cycles,
        )

        # State checkpoint
        save_checkpoint(
            run_id=state["run_id"],
            cycle_count=cycle_count,
            state={
                "cycle_count": cycle_count,
                "selected_domain": state.get("selected_domain"),
                "selected_action": state.get("selected_action"),
                "evaluation": evaluation,
                "latest_metrics": metrics,
                "weighted_score": new_weighted,
                "stagnant_cycles": stagnant_cycles,
            },
        )

        log_node_finish(
            exec_id,
            output_summary=(
                f"progress={evaluation.get('progress_score', 0):.3f} "
                f"weighted={new_weighted:.3f} trend={trend}"
            ),
        )

        return {
            "evaluation": evaluation,
            "weighted_score": new_weighted,
            "previous_weighted_score": prev_weighted,
            "trend_direction": trend,
            "stagnant_cycles": stagnant_cycles,
            "last_mrr": current_mrr,
        }

    except Exception as exc:  # noqa: BLE001
        error_entry = {"node": "evaluator", "error": str(exc), "timestamp": utc_now()}
        progress = compute_progress_score(current_mrr, goal_mrr)
        weighted = compute_weighted_score(metrics, goal_mrr)
        fallback = {
            "kpi_snapshot": {
                "mrr": current_mrr,
                "signups": metrics.get("signups", 0),
                "traffic": metrics.get("website_traffic", 0),
                "revenue": metrics.get("revenue", 0.0),
            },
            "progress_score": progress,
            "weighted_score": weighted,
            "trend_direction": "flat",
            "recommendation": "Continue iterating (evaluator fallback).",
            "risk_flags": [f"evaluator_error: {exc}"],
        }
        log_node_finish(exec_id, output_summary=f"fallback error:{exc}", status="failed")
        return {
            "evaluation": fallback,
            "errors": [error_entry],
            "weighted_score": weighted,
            "trend_direction": "flat",
        }


def _run_evaluator(
    state: CEOClawState, mock_mode: bool, prev_weighted: float
) -> dict[str, Any]:
    """Run the evaluator — deterministically in mock mode, via model otherwise."""
    metrics = state.get("latest_metrics") or {}
    current_mrr = metrics.get("mrr", 0.0)
    goal_mrr = state.get("goal_mrr", 100.0)
    cycle_count = state.get("cycle_count", 0)

    weighted = compute_weighted_score(metrics, goal_mrr)
    progress = compute_progress_score(current_mrr, goal_mrr)
    trend = compute_trend(weighted, prev_weighted)

    if mock_mode:
        # Deterministic evaluation from real state metrics — no model call
        risk_flags: list[str] = []
        stagnant = state.get("stagnant_cycles", 0)
        if stagnant >= _STAGNATION_THRESHOLD:
            risk_flags.append(f"stagnant_{stagnant}_cycles")
        if current_mrr == 0.0 and cycle_count > 4:
            risk_flags.append("no_revenue_after_4_cycles")

        rec = _recommendation(progress, trend)
        return EvaluatorOutput(
            kpi_snapshot={
                "mrr": current_mrr,
                "signups": metrics.get("signups", 0),
                "traffic": metrics.get("website_traffic", 0),
                "revenue": metrics.get("revenue", 0.0),
            },
            progress_score=progress,
            weighted_score=weighted,
            trend_direction=trend,
            recommendation=rec,
            risk_flags=risk_flags,
        ).model_dump()

    # Live model path
    model = get_model(mock_mode=False, cycle_index=cycle_count)
    prompt = build_evaluator_prompt(
        cycle_count=cycle_count,
        goal_mrr=goal_mrr,
        latest_metrics=metrics,
        executor_result=state.get("executor_result", {}),
        weighted_score=weighted,
        prev_score=prev_weighted,
        trend=trend,
    )
    response = model.invoke([
        SystemMessage(content=prompt),
        HumanMessage(content="Evaluate business state. Reply with JSON only."),
    ])

    result = safe_parse_evaluator(
        response.content,
        current_mrr=current_mrr,
        goal_mrr=goal_mrr,
        current_metrics=metrics,
    )
    # Ensure weighted_score is always set from our computation if model omitted it
    data = result.data
    if not data.get("weighted_score"):
        data["weighted_score"] = weighted
    if not data.get("trend_direction"):
        data["trend_direction"] = trend
    return data


def _recommendation(progress: float, trend: str) -> str:
    if progress >= 0.9:
        return "Almost at goal — push sales hard this cycle."
    if trend == "up":
        return "Momentum building — double down on what's working."
    if trend == "down":
        return "Scores declining — consider switching domain strategy."
    if progress < 0.05:
        return "Early stage — focus on product and outreach."
    return "Steady — continue iterating across domains."


# ---------------------------------------------------------------------------
# StopCheckNode
# ---------------------------------------------------------------------------

def stop_check_node(state: CEOClawState, config: RunnableConfig) -> dict[str, Any]:
    """StopCheckNode: the only node allowed to terminate the run.

    Stop conditions (checked in order):
      1. Weighted score >= 1.0  (full KPI goal reached)
      2. MRR progress >= 1.0   (MRR goal reached)
      3. cycle_count >= max_cycles
      4. error_count >= 10
    """
    cfg = config.get("configurable", {})
    max_cycles: int = cfg.get("max_cycles", 20)
    cycle_count = state.get("cycle_count", 0)

    exec_id = log_node_start(
        run_id=state["run_id"],
        cycle_count=cycle_count,
        node_name="stop_check",
        input_summary=f"cycle={cycle_count} max={max_cycles}",
    )

    evaluation = state.get("evaluation", {})
    progress = evaluation.get("progress_score", 0.0)
    weighted = state.get("weighted_score", 0.0)
    error_count = len(state.get("errors", []))

    should_stop = False
    stop_reason: str | None = None

    if progress >= 1.0:
        should_stop, stop_reason = True, "goal_mrr_reached"
    elif weighted >= 1.0:
        should_stop, stop_reason = True, "full_kpi_score_reached"
    elif cycle_count >= max_cycles:
        should_stop, stop_reason = True, f"max_cycles_reached({max_cycles})"
    elif error_count >= 10:
        should_stop, stop_reason = True, f"too_many_errors({error_count})"

    log_node_finish(exec_id, output_summary=f"stop={should_stop} reason={stop_reason}")
    return {"should_stop": should_stop, "stop_reason": stop_reason}


def _route_from_stop_check(state: CEOClawState) -> str:
    return "stop" if state.get("should_stop", False) else "continue"


# ---------------------------------------------------------------------------
# Graph compilation
# ---------------------------------------------------------------------------

def build_graph() -> Any:
    """Build and compile the CEOClaw StateGraph."""
    workflow = StateGraph(CEOClawState)

    workflow.add_node("planner", planner_node)
    workflow.add_node("router", router_node)
    workflow.add_node("product_executor", product_executor_node)
    workflow.add_node("marketing_executor", marketing_executor_node)
    workflow.add_node("sales_executor", sales_executor_node)
    workflow.add_node("ops_executor", ops_executor_node)
    workflow.add_node("evaluator", evaluator_node)
    workflow.add_node("stop_check", stop_check_node)

    workflow.add_edge(START, "planner")
    workflow.add_edge("planner", "router")

    workflow.add_conditional_edges(
        "router",
        _route_from_router,
        {
            "product_executor": "product_executor",
            "marketing_executor": "marketing_executor",
            "sales_executor": "sales_executor",
            "ops_executor": "ops_executor",
        },
    )

    for executor in [
        "product_executor", "marketing_executor", "sales_executor", "ops_executor"
    ]:
        workflow.add_edge(executor, "evaluator")

    workflow.add_edge("evaluator", "stop_check")
    workflow.add_conditional_edges(
        "stop_check",
        _route_from_stop_check,
        {"stop": END, "continue": "planner"},
    )

    return workflow.compile(checkpointer=MemorySaver())


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------

def _initial_state(run_id: str, goal_mrr: float) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "cycle_count": 0,
        "goal_mrr": goal_mrr,
        "latest_metrics": {},
        "active_product": None,
        "strategy": {},
        "selected_action": "",
        "selected_domain": "product",
        "executor_result": {},
        "evaluation": {},
        "weighted_score": 0.0,
        "previous_weighted_score": 0.0,
        "trend_direction": "flat",
        "stagnant_cycles": 0,
        "last_mrr": 0.0,
        "consecutive_failures": {},
        "circuit_breaker_active": False,
        "tokens_used": 0,
        "external_calls": 0,
        "errors": [],
        "stop_reason": None,
        "should_stop": False,
    }


# ---------------------------------------------------------------------------
# Console output
# ---------------------------------------------------------------------------

def _print_cycle_summary(state: dict[str, Any]) -> None:
    cycle = state.get("cycle_count", 0)
    evaluation = state.get("evaluation", {})
    mrr = state.get("latest_metrics", {}).get("mrr", 0.0)
    cb = "⚡CB" if state.get("circuit_breaker_active") else "   "
    stag = state.get("stagnant_cycles", 0)
    stag_mark = f"⏸{stag}" if stag >= _STAGNATION_THRESHOLD else f"  {stag}"
    print(
        f"  {cb} Cycle {cycle:>3} | "
        f"domain={state.get('selected_domain','?'):<12} "
        f"action={state.get('selected_action','?'):<28} "
        f"mrr=${mrr:>7.2f} "
        f"w={state.get('weighted_score', 0):.3f} "
        f"trend={evaluation.get('trend_direction','flat'):<5} "
        f"stag={stag_mark}"
    )


# ---------------------------------------------------------------------------
# Public run entry point
# ---------------------------------------------------------------------------

def run_graph(
    cycles: int = 1,
    continuous: bool = False,
    goal_mrr: float = 100.0,
    mock_mode: bool = False,
    max_cycles: int = 20,
    quiet: bool = False,
) -> dict[str, Any]:
    """Run the CEOClaw LangGraph.

    Args:
        cycles:     Number of cycles (ignored when continuous=True).
        continuous: Run until goal or max_cycles.
        goal_mrr:   MRR target in USD.
        mock_mode:  Deterministic responses, no HTTP calls.
        max_cycles: Hard stop.
        quiet:      Suppress per-cycle streaming output (demo mode).

    Returns:
        Final state dict.
    """
    init_db()

    run_id = str(uuid.uuid4())
    start_graph_run(run_id=run_id, goal_mrr=goal_mrr)

    effective_max = max_cycles if continuous else min(cycles, max_cycles)
    graph = build_graph()
    config: RunnableConfig = {
        "configurable": {
            "thread_id": run_id,
            "mock_mode": mock_mode,
            "max_cycles": effective_max,
            "stagnation_threshold": _STAGNATION_THRESHOLD,
        }
    }

    if not quiet:
        print(
            f"\nCEOClaw {run_id[:8]}… | goal=${goal_mrr} | "
            f"mock={mock_mode} | max={effective_max}"
        )
        print("-" * 100)

    final_state: dict[str, Any] = {}
    _last_printed: tuple[int, float] = (-1, -1.0)  # (cycle_count, weighted_score)
    try:
        for event in graph.stream(
            _initial_state(run_id, goal_mrr), config=config, stream_mode="values"
        ):
            final_state = event
            if not quiet and final_state.get("cycle_count", 0) > 0 and final_state.get("evaluation"):
                key = (final_state["cycle_count"], final_state.get("weighted_score", -1.0))
                if key != _last_printed:
                    _last_printed = key
                    _print_cycle_summary(final_state)

        stop_reason = final_state.get("stop_reason")
        finish_graph_run(
            run_id=run_id,
            cycles_run=final_state.get("cycle_count", 0),
            stop_reason=stop_reason,
            status="completed",
        )
        if not quiet:
            print("-" * 100)
            print(
                f"Finished. stop_reason={stop_reason or 'n/a'} | "
                f"errors={len(final_state.get('errors', []))}"
            )
    except Exception as exc:
        finish_graph_run(
            run_id=run_id,
            cycles_run=final_state.get("cycle_count", 0),
            stop_reason=f"exception:{exc}",
            status="failed",
        )
        raise

    # Always ensure run_id is present in the returned state
    final_state.setdefault("run_id", run_id)
    return final_state


# ---------------------------------------------------------------------------
# Export run summary as Markdown
# ---------------------------------------------------------------------------

def export_run_summary(run_id: str, output_dir: str | None = None) -> Path:
    """Generate a Markdown summary for *run_id* and write it to disk.

    Sections:
        - Run metadata
        - Per-cycle KPI timeline (domain/action/MRR/weighted/trend/stagnation)
        - Artifacts created
        - Risk events (stagnation, no-revenue flags)
        - Node execution stats
        - Confidence note

    Args:
        run_id:     The graph run UUID.
        output_dir: Directory to write the file.  Defaults to ``data/exports/``.

    Returns:
        Path to the written Markdown file.
    """
    from data.database import get_connection
    from config.settings import settings

    exports_dir = Path(output_dir) if output_dir else (
        settings.resolve_db_path().parent / "exports"
    )
    exports_dir.mkdir(parents=True, exist_ok=True)
    out_path = exports_dir / f"{run_id[:8]}_summary.md"

    with get_connection() as conn:
        run_row = conn.execute(
            "SELECT * FROM graph_runs WHERE run_id = ?", (run_id,)
        ).fetchone()

        if not run_row:
            raise ValueError(f"run_id {run_id!r} not found in graph_runs")

        cycle_rows = conn.execute(
            "SELECT * FROM cycle_scores WHERE run_id = ? ORDER BY cycle_count ASC",
            (run_id,),
        ).fetchall()

        artifact_rows = conn.execute(
            "SELECT * FROM artifacts WHERE run_id = ? ORDER BY created_at ASC",
            (run_id,),
        ).fetchall()

        node_stats = conn.execute(
            """
            SELECT node_name,
                   COUNT(*)                                    AS exec_count,
                   SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed_count,
                   CAST(AVG(duration_ms) AS INTEGER)           AS avg_ms
            FROM   node_executions
            WHERE  run_id = ?
            GROUP  BY node_name
            ORDER  BY exec_count DESC
            """,
            (run_id,),
        ).fetchall()

    # ------------------------------------------------------------------ #
    # Run metadata
    # ------------------------------------------------------------------ #
    final_weighted = cycle_rows[-1]["weighted_score"] if cycle_rows else 0.0
    confidence = _confidence_note(
        final_weighted,
        run_row["cycles_run"] or 0,
        run_row["goal_mrr"],
    )

    lines: list[str] = [
        "# CEOClaw Run Summary",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| Run ID | `{run_id}` |",
        f"| Started | {run_row['started_at'][:19]} UTC |",
        f"| Finished | {(run_row['finished_at'] or 'n/a')[:19]} UTC |",
        f"| Goal MRR | ${run_row['goal_mrr']:.2f} |",
        f"| Cycles Run | {run_row['cycles_run']} |",
        f"| Stop Reason | {run_row['stop_reason'] or 'n/a'} |",
        f"| Status | {run_row['status']} |",
        f"| Final Weighted Score | {final_weighted:.3f} / 1.000 |",
        f"| Confidence | {confidence} |",
        "",
    ]

    # ------------------------------------------------------------------ #
    # KPI timeline
    # ------------------------------------------------------------------ #
    lines += [
        "## KPI Timeline",
        "",
        "| Cycle | Domain | Action | MRR | Traffic | Signups | Weighted | Trend | Stagnant |",
        "|-------|--------|--------|-----|---------|---------|----------|-------|----------|",
    ]
    for r in cycle_rows:
        stag_mark = f"⏸ {r['stagnant_cycles']}" if r["stagnant_cycles"] >= 3 else str(r["stagnant_cycles"])
        lines.append(
            f"| {r['cycle_count']} "
            f"| {r['domain']} "
            f"| {r['action']} "
            f"| ${r['mrr']:.2f} "
            f"| {r['traffic']} "
            f"| {r['signups']} "
            f"| {r['weighted_score']:.3f} "
            f"| {r['trend_direction']} "
            f"| {stag_mark} |"
        )

    # ------------------------------------------------------------------ #
    # Artifacts
    # ------------------------------------------------------------------ #
    lines += ["", "## Artifacts", ""]
    if artifact_rows:
        lines += [
            "| Cycle | Type | Node | Summary | Created |",
            "|-------|------|------|---------|---------|",
        ]
        for a in artifact_rows:
            summary = a["path_or_hash"] or a["content_summary"] or "–"
            lines.append(
                f"| {a['cycle_count']} "
                f"| {a['artifact_type']} "
                f"| {a['node_name']} "
                f"| {summary} "
                f"| {a['created_at'][:19]} |"
            )
    else:
        lines.append("_No artifacts recorded._")

    # ------------------------------------------------------------------ #
    # Risk events
    # ------------------------------------------------------------------ #
    lines += ["", "## Risk Events", ""]
    risk_lines: list[str] = []
    prev_stag = 0
    for r in cycle_rows:
        s = r["stagnant_cycles"]
        if s >= 3 and s != prev_stag:
            risk_lines.append(
                f"| {r['cycle_count']} | stagnation | "
                f"{s} consecutive cycles with no MRR growth |"
            )
        if r["mrr"] == 0.0 and r["cycle_count"] > 4:
            risk_lines.append(
                f"| {r['cycle_count']} | no_revenue | "
                f"MRR still $0 after cycle 4 |"
            )
        prev_stag = s

    if risk_lines:
        lines += [
            "| Cycle | Type | Detail |",
            "|-------|------|--------|",
        ] + risk_lines
    else:
        lines.append("_No risk events detected._")

    # ------------------------------------------------------------------ #
    # Node execution stats
    # ------------------------------------------------------------------ #
    lines += ["", "## Node Execution Stats", ""]
    if node_stats:
        lines += [
            "| Node | Executions | Failures | Avg ms |",
            "|------|-----------|---------|--------|",
        ]
        for n in node_stats:
            lines.append(
                f"| {n['node_name']} "
                f"| {n['exec_count']} "
                f"| {n['failed_count']} "
                f"| {n['avg_ms'] or 0} |"
            )
    else:
        lines.append("_No node execution data._")

    # ------------------------------------------------------------------ #
    # Confidence note
    # ------------------------------------------------------------------ #
    lines += ["", "## Confidence Note", "", f"> {confidence}", ""]

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def _confidence_note(weighted: float, cycles_run: int, goal_mrr: float) -> str:
    """Single-sentence confidence assessment for the run summary."""
    g = f"${goal_mrr:.0f}"
    if weighted >= 0.8:
        return (
            f"High confidence — weighted KPI {weighted:.3f} indicates strong traction "
            f"toward {g} MRR goal."
        )
    if weighted >= 0.5:
        return (
            f"Moderate confidence — score {weighted:.3f} shows meaningful progress; "
            f"additional cycles will close the gap to {g} MRR."
        )
    if weighted >= 0.2:
        return (
            f"Early traction — score {weighted:.3f} after {cycles_run} cycles; "
            f"SEO and outreach impact is visible."
        )
    return (
        f"Early stage — score {weighted:.3f} after {cycles_run} cycles; "
        f"product-market fit still being established toward {g} MRR."
    )
