"""
Read-only context built from a BuildPlan dict for one pipeline run (Phase 3).

Extracted once by generation_pipeline after the build_plan is constructed,
then passed into generate() as a single optional parameter. All fields are
derived from ctx["build_plan"]; nothing here mutates pipeline state.

Phase 5 addition: build_generation_plan_context() accepts an optional
repair_summary_dict (from ctx["repair_summary"]) and populates two additive
soft-hint fields: avoid_paths and repair_hints.  All existing callers that
omit repair_summary_dict continue to work identically.

Public API:
    ctx = build_generation_plan_context(build_plan_dict)
    ctx = build_generation_plan_context(build_plan_dict, repair_summary_dict=d)
    ctx.ordered_create_targets   # tuple[str, ...] — plan-ordered file paths
    ctx.avoid_paths              # tuple[str, ...] — soft hint: paths to deprioritize
    ctx.repair_hints             # tuple[str, ...] — human-readable repair notes
    ctx.log_dict()               # structured log snapshot
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GenerationPlanContext:
    """Lightweight plan snapshot consumed by generate() for ordering/targeting."""

    session_mode: str
    """'new_project' | 'edit'"""

    generation_flavor: str
    """'spec_first_preferred' | 'legacy_per_file' | 'edit_existing' | 'unknown'"""

    has_disk_spec: bool
    """True when a _spec.json was found on disk before this run."""

    ordered_create_targets: tuple[str, ...]
    """
    Paths from generation_tasks with intent=='create' (spec_synthesize excluded),
    in plan order.  When non-empty and plan-aware mode is enabled, the legacy
    per-file loop uses this list instead of brand_spec.pages.
    """

    edit_candidate_paths: tuple[str, ...]
    """Paths tagged as edit candidates (edit mode only)."""

    unchanged_paths: tuple[str, ...]
    """Paths the plan expects to be untouched (binary assets, etc.)."""

    operation_summary: str
    """First non-empty note from the plan, used for debug logging."""

    prompt_snippet: str | None = None
    """Reserved: optional phrase for prompt injection (unused by callers today)."""

    # --- Phase 5: repair feedback (additive, soft hints only) ---

    avoid_paths: tuple[str, ...] = ()
    """
    Soft hint: paths that repeatedly failed repair in this run.
    Callers MAY deprioritize these in future generation retries within the same
    run.  Does not override task ordering; purely advisory.
    """

    repair_hints: tuple[str, ...] = ()
    """
    Human-readable notes derived from RepairSummary for this run.
    Logged to ctx and available for debugging; not injected into LLM prompts.
    """

    def log_dict(self) -> dict:
        d = {
            "session_mode": self.session_mode,
            "generation_flavor": self.generation_flavor,
            "has_disk_spec": self.has_disk_spec,
            "ordered_create_targets": list(self.ordered_create_targets),
            "edit_candidate_paths": list(self.edit_candidate_paths),
            "unchanged_paths": list(self.unchanged_paths),
            "operation_summary": self.operation_summary,
        }
        # Only include repair fields when populated (keeps logs clean on normal runs)
        if self.avoid_paths:
            d["avoid_paths"] = list(self.avoid_paths)
        if self.repair_hints:
            d["repair_hints"] = list(self.repair_hints)
        return d


def build_generation_plan_context(
    build_plan_dict: dict,
    repair_summary_dict: dict | None = None,
) -> GenerationPlanContext:
    """Parse a BuildPlan.to_dict() snapshot into a GenerationPlanContext.

    Defensive — safe to call with a partial or fallback dict.  All missing
    keys default gracefully so the pipeline cannot be broken by a bad plan.

    repair_summary_dict (Phase 5, optional):
        Pass ctx["repair_summary"] (a RepairSummary.to_dict()) to enrich the
        context with avoid_paths and repair_hints for this run.  Omitting it
        preserves identical behavior to pre-Phase-5 callers.
    """
    constraints = build_plan_dict.get("constraints") or {}
    tasks = build_plan_dict.get("generation_tasks") or []
    notes = build_plan_dict.get("notes") or []

    ordered_create: list[str] = []
    edit_candidates: list[str] = []

    for task in tasks:
        intent = task.get("intent", "")
        path = task.get("path", "")
        if not path:
            continue
        if intent == "create":
            ordered_create.append(path)
        elif intent == "edit_candidate":
            edit_candidates.append(path)
        # spec_synthesize, spec_patch intentionally skipped

    unchanged = list(build_plan_dict.get("unchanged_paths") or [])
    operation_summary = next(
        (n for n in notes if isinstance(n, str) and n.strip()), ""
    )

    # Phase 5: derive soft hints from repair outcome (no-op when dict is absent/empty)
    avoid_paths: tuple[str, ...] = ()
    repair_hints: tuple[str, ...] = ()
    if repair_summary_dict:
        _repeated = list(repair_summary_dict.get("repeated_fail_paths") or [])
        _failed = list(repair_summary_dict.get("failed_paths") or [])
        # avoid_paths = union of repeated failures and permanently-failed paths, deduplicated
        _seen: set[str] = set()
        _avoid: list[str] = []
        for p in _repeated + _failed:
            if p and p not in _seen:
                _avoid.append(p)
                _seen.add(p)
        avoid_paths = tuple(_avoid)
        repair_hints = tuple(str(h) for h in (repair_summary_dict.get("hints") or []))

    ctx = GenerationPlanContext(
        session_mode=str(constraints.get("session_mode") or "new_project"),
        generation_flavor=str(constraints.get("generation_flavor") or "unknown"),
        has_disk_spec=bool(constraints.get("has_disk_spec", False)),
        ordered_create_targets=tuple(ordered_create),
        edit_candidate_paths=tuple(edit_candidates),
        unchanged_paths=tuple(unchanged),
        operation_summary=operation_summary,
        avoid_paths=avoid_paths,
        repair_hints=repair_hints,
    )
    logger.debug("GenerationPlanContext built: %s", ctx.log_dict())
    return ctx
