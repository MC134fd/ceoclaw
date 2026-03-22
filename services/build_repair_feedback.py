"""
Repair feedback layer (Phase 5).

Derives a per-run RepairSummary from ctx["repair_trace"] and makes it available
as ctx["repair_summary"].  The summary is consumed by the generation-plan-context
builder to enrich the context snapshot with lightweight soft hints.

This is strictly per-run:
  - No disk persistence.
  - No cross-run learning.
  - No mutation of BuildPlan.

Public API:
    summary = build_repair_summary(repair_trace)  # list of dicts from ctx["repair_trace"]
    summary.to_dict()                              # JSON-serializable snapshot
"""

from __future__ import annotations

import logging
import re as _re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Regex to extract the path value from repair error/message strings.
# Error format (from build_repair.py):  round=N path='REL_PATH' strategy=... — ...
_PATH_RE = _re.compile(r"""path='([^']+)'|path="([^"]+)" """, _re.VERBOSE)


@dataclass(frozen=True)
class RepairSummary:
    """Serializable summary of all repair activity in one pipeline run.

    Derived from ctx["repair_trace"]; never contains file contents.
    """

    repaired_paths: tuple[str, ...]
    """Paths where at least one repair round produced a successful patch."""

    failed_paths: tuple[str, ...]
    """Paths where repair was attempted but produced no content change,
    excluding paths that were also successfully repaired in another round."""

    strategies_used: tuple[str, ...]
    """Unique RepairStrategy values that produced at least one patch."""

    repeated_fail_paths: tuple[str, ...]
    """Paths that appear in error entries across two or more separate rounds."""

    total_rounds: int
    """Number of repair rounds that ran (may be 0 if flag was off)."""

    hints: tuple[str, ...]
    """Human-readable soft hints derived from what broke and what was fixed.
    Consumed by build_generation_plan_context() to enrich repair_hints."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "repaired_paths": list(self.repaired_paths),
            "failed_paths": list(self.failed_paths),
            "strategies_used": list(self.strategies_used),
            "repeated_fail_paths": list(self.repeated_fail_paths),
            "total_rounds": self.total_rounds,
            "hints": list(self.hints),
        }


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_repair_summary(repair_trace: list[dict]) -> RepairSummary:
    """Derive a RepairSummary from the repair_trace list in ctx.

    Safe to call with an empty or missing list — returns an all-empty summary.
    Does not raise; logs warnings on unexpected data.
    """
    if not repair_trace:
        return RepairSummary(
            repaired_paths=(),
            failed_paths=(),
            strategies_used=(),
            repeated_fail_paths=(),
            total_rounds=0,
            hints=(),
        )

    repaired: set[str] = set()
    all_strategies: set[str] = set()

    # per-path fail counts across rounds (for repeated_fail_paths)
    fail_rounds: dict[str, set[int]] = {}

    for attempt in repair_trace:
        if not isinstance(attempt, dict):
            logger.warning("Unexpected repair_trace entry type: %r", type(attempt))
            continue

        round_idx = attempt.get("round_index", 0)

        for p in attempt.get("paths_touched") or []:
            if isinstance(p, str):
                repaired.add(p)

        for s in attempt.get("strategies_used") or []:
            if isinstance(s, str):
                all_strategies.add(s)

        for err in attempt.get("errors") or []:
            p = _extract_path(err)
            if p:
                fail_rounds.setdefault(p, set()).add(round_idx)

        # Unrecoverable items are logged in messages as "UNRECOVERABLE (skipped)"
        for msg in attempt.get("messages") or []:
            if "UNRECOVERABLE" in msg:
                p = _extract_path(msg)
                if p:
                    fail_rounds.setdefault(p, set()).add(round_idx)

    # failed_paths = paths that only ever failed (never repaired)
    ever_failed = set(fail_rounds.keys())
    failed = tuple(sorted(ever_failed - repaired))

    repeated = tuple(
        sorted(p for p, rounds in fail_rounds.items() if len(rounds) > 1)
    )

    hints = _derive_hints(all_strategies, repaired, set(failed))

    return RepairSummary(
        repaired_paths=tuple(sorted(repaired)),
        failed_paths=failed,
        strategies_used=tuple(sorted(all_strategies)),
        repeated_fail_paths=repeated,
        total_rounds=len(repair_trace),
        hints=hints,
    )


# ---------------------------------------------------------------------------
# Hint derivation (soft, human-readable)
# ---------------------------------------------------------------------------

_STRATEGY_HINTS: dict[str, str] = {
    "deterministic_doctype_inject": (
        "HTML preamble or missing DOCTYPE detected; "
        "LLM output may need explicit '<!DOCTYPE html>' instruction"
    ),
    "deterministic_viewport_inject": (
        "Responsive contract violation repaired (missing viewport meta); "
        "consider reinforcing responsive rules in prompt"
    ),
    "deterministic_title_inject": (
        "Missing <title> repaired; LLM may be omitting head boilerplate"
    ),
    "targeted_llm_html_fix": (
        "LLM repair used for unstructured output; "
        "spec-first generation may produce more reliable HTML"
    ),
}


def _derive_hints(
    strategies: set[str],
    repaired: set[str],
    failed: set[str],
) -> tuple[str, ...]:
    hints: list[str] = []

    for strategy, hint in _STRATEGY_HINTS.items():
        if strategy in strategies:
            hints.append(hint)

    if repaired:
        hints.append(
            f"{len(repaired)} path(s) auto-repaired: {', '.join(sorted(repaired))}"
        )
    if failed:
        hints.append(
            f"{len(failed)} path(s) could not be auto-repaired: {', '.join(sorted(failed))}"
        )

    return tuple(hints)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_path(text: str) -> str | None:
    """Extract a rel_path from a repair message/error string, or None."""
    m = _PATH_RE.search(text)
    if not m:
        return None
    return m.group(1) or m.group(2) or None
