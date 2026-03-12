"""
CEOClaw LangGraph state definition.

CEOClawState is the single typed dict that flows through every node in the
graph.  Import it from here in all agent and core modules.

New in v0.3 (hardening phase):
  - consecutive_failures  – per-executor failure counter for circuit breaker
  - circuit_breaker_active – True when router overrides to ops recovery
  - stagnant_cycles       – cycles with no MRR growth (stagnation detector)
  - last_mrr              – MRR snapshot from previous evaluator pass
  - tokens_used           – approximate cumulative token budget used
  - external_calls        – count of live model HTTP calls this run
  - weighted_score        – composite KPI score (0.0–1.0)
  - trend_direction       – "up" | "down" | "flat" vs previous cycle
  - previous_weighted_score – score from previous cycle for trend computation
  - autonomy_mode         – A_AUTONOMOUS | B_HUMAN_APPROVAL | C_ASSISTED | D_DRY_RUN

New in v0.6 (full-stack AI upgrade):
  - memory_context        – dict of key/value from persistent memory store
  - discovered_prospects  – list of prospect dicts found this cycle
  - research_citations    – list of citation dicts from live web search

New in v0.7 (instruction-driven workflow):
  - product_intent        – parsed intent from user chat message
  - workflow_mode         – "chronological" | "adaptive"
  - workflow_step         – current step in chronological mode
  - quality_audit         – latest quality audit scorecard
  - iteration_tasks       – improvement tasks from audit feedback
"""

from operator import add
from typing import Annotated, Any, Literal, Optional, TypedDict


class CEOClawState(TypedDict, total=False):
    """Typed state shared across all LangGraph nodes.

    ``total=False`` allows individual fields to be absent from partial
    update dicts returned by nodes; call ``.get(key, default)`` defensively.

    The ``errors`` field uses an append reducer so error entries accumulate
    rather than being overwritten as the graph cycles.
    """

    # ------------------------------------------------------------------
    # Identity & progress  (required at run start)
    # ------------------------------------------------------------------
    run_id: str
    cycle_count: int
    goal_mrr: float

    # ------------------------------------------------------------------
    # Business context
    # ------------------------------------------------------------------
    latest_metrics: dict[str, Any]
    active_product: Optional[dict[str, Any]]

    # ------------------------------------------------------------------
    # Planner outputs
    # ------------------------------------------------------------------
    strategy: dict[str, Any]
    selected_action: str
    selected_domain: Literal["product", "marketing", "sales", "ops"]

    # ------------------------------------------------------------------
    # Executor output
    # ------------------------------------------------------------------
    executor_result: dict[str, Any]

    # ------------------------------------------------------------------
    # Evaluator output
    # ------------------------------------------------------------------
    evaluation: dict[str, Any]
    weighted_score: float
    trend_direction: str          # "up" | "down" | "flat"
    previous_weighted_score: float

    # ------------------------------------------------------------------
    # Stagnation detector
    # ------------------------------------------------------------------
    stagnant_cycles: int
    last_mrr: float

    # ------------------------------------------------------------------
    # Circuit breaker
    # ------------------------------------------------------------------
    consecutive_failures: dict[str, int]   # executor_key -> count
    circuit_breaker_active: bool

    # ------------------------------------------------------------------
    # Budget controls
    # ------------------------------------------------------------------
    tokens_used: int
    external_calls: int

    # ------------------------------------------------------------------
    # Model mode / fallback transparency
    # ------------------------------------------------------------------
    model_mode: str        # "live" | "mock" | "fallback" | "unknown"
    fallback_count: int    # accumulated across all model calls this run

    # ------------------------------------------------------------------
    # Accumulated errors  (append reducer)
    # ------------------------------------------------------------------
    errors: Annotated[list[dict[str, Any]], add]

    # ------------------------------------------------------------------
    # Autonomy mode (v0.5)
    # ------------------------------------------------------------------
    autonomy_mode: str   # A_AUTONOMOUS | B_HUMAN_APPROVAL | C_ASSISTED | D_DRY_RUN

    # ------------------------------------------------------------------
    # Cross-run memory (v0.6)
    # ------------------------------------------------------------------
    memory_context: dict[str, str]          # key/value from persistent store

    # ------------------------------------------------------------------
    # Prospects discovered this cycle (v0.6)
    # ------------------------------------------------------------------
    discovered_prospects: list[dict[str, Any]]

    # ------------------------------------------------------------------
    # Live research citations (v0.6)
    # ------------------------------------------------------------------
    research_citations: list[dict[str, Any]]

    # ------------------------------------------------------------------
    # Instruction-driven workflow (v0.7)
    # ------------------------------------------------------------------
    product_intent: dict[str, Any]          # parsed from chat message
    workflow_mode: str                      # "chronological" | "adaptive"
    workflow_step: str                      # current step name
    quality_audit: dict[str, Any]           # latest audit scorecard
    iteration_tasks: list[str]              # improvement tasks from audit

    # ------------------------------------------------------------------
    # Stop signal
    # ------------------------------------------------------------------
    stop_reason: Optional[str]
    should_stop: bool


__all__ = ["CEOClawState"]
