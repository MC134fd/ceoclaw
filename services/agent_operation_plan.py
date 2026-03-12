"""
AgentOperationPlan — structured plan and execution trace for autonomous agents.

Supports the full agent lifecycle:
  observe → plan → validate → apply → verify

Each plan is a sequence of OperationSteps.  Steps execute serially; a step failure
stops the plan by default (unless step.continue_on_failure is True).

Design goals:
  - Typed, inspectable, serialisable to JSON (for audit logs and UI display)
  - Safe by default: every destructive step must be validated before apply
  - Workspace-scoped: all paths routed through WorkspaceScope
  - Extension-ready: add new step types without changing the runner contract

Example usage (future agent runner will do this automatically):

    plan = AgentOperationPlan.build(
        session_id="abc123",
        slug="calorie-app",
        objective="Add a pricing section to index.html",
    )
    plan.add_step(OperationStep(
        capability="edit_section",
        params={"relative_path": "index.html", "section": "cta", "instruction": "..."},
        description="Insert pricing table before CTA",
    ))
    plan.add_step(OperationStep(
        capability="save_version",
        params={"label": "added-pricing"},
        description="Snapshot workspace after change",
    ))
    # plan.to_dict() → JSON-serialisable dict for persistence / UI
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Step status
# ---------------------------------------------------------------------------

class StepStatus(str, Enum):
    PENDING   = "pending"
    VALIDATING = "validating"
    APPLYING  = "applying"
    DONE      = "done"
    FAILED    = "failed"
    SKIPPED   = "skipped"


# ---------------------------------------------------------------------------
# OperationStep
# ---------------------------------------------------------------------------

@dataclass
class OperationStep:
    """
    One discrete action within an AgentOperationPlan.

    Fields:
        capability:          Name of the AgentCapability to invoke
        params:              Arguments passed to the capability
        description:         Human-readable summary shown in UI
        status:              Current execution status
        result:              Output from the capability (set after apply)
        error:               Error message if status == FAILED
        continue_on_failure: If True, plan continues even if this step fails
        requires_validation: If True, runner must call validate() before apply()
        validation_result:   Output from pre-apply validation
    """
    capability: str
    params: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    status: StepStatus = StepStatus.PENDING
    result: Optional[Any] = None
    error: Optional[str] = None
    continue_on_failure: bool = False
    requires_validation: bool = True
    validation_result: Optional[dict] = None
    _started_at: Optional[str] = field(default=None, repr=False)
    _finished_at: Optional[str] = field(default=None, repr=False)

    def mark_validating(self) -> None:
        self.status = StepStatus.VALIDATING
        self._started_at = _utc_now()

    def mark_applying(self) -> None:
        self.status = StepStatus.APPLYING

    def mark_done(self, result: Any = None) -> None:
        self.status = StepStatus.DONE
        self.result = result
        self._finished_at = _utc_now()

    def mark_failed(self, error: str) -> None:
        self.status = StepStatus.FAILED
        self.error = error
        self._finished_at = _utc_now()

    def mark_skipped(self, reason: str = "") -> None:
        self.status = StepStatus.SKIPPED
        self.error = reason

    def to_dict(self) -> dict:
        return {
            "capability": self.capability,
            "params": self.params,
            "description": self.description,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "continue_on_failure": self.continue_on_failure,
            "requires_validation": self.requires_validation,
            "validation_result": self.validation_result,
            "started_at": self._started_at,
            "finished_at": self._finished_at,
        }


# ---------------------------------------------------------------------------
# AgentOperationPlan
# ---------------------------------------------------------------------------

class PlanStatus(str, Enum):
    DRAFT    = "draft"      # not yet started
    RUNNING  = "running"    # executing steps
    DONE     = "done"       # all steps completed successfully
    FAILED   = "failed"     # a step failed and the plan was aborted
    ABORTED  = "aborted"    # manually stopped before completion


@dataclass
class AgentOperationPlan:
    """
    A complete, ordered execution plan for an autonomous agent.

    Lifecycle:
        DRAFT → RUNNING → DONE
                        ↘ FAILED
                  ABORTED (any time)

    The plan runner (future) will iterate steps, calling:
        step.mark_validating()
        validate(step)             # capability-specific checks
        step.mark_applying()
        apply(step)                # actually executes the capability
        step.mark_done(result)

    On failure:
        step.mark_failed(error)
        if not step.continue_on_failure:
            plan.status = PlanStatus.FAILED
            break
    """
    plan_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    slug: str = ""
    objective: str = ""
    steps: list[OperationStep] = field(default_factory=list)
    status: PlanStatus = PlanStatus.DRAFT
    created_at: str = field(default_factory=_utc_now)
    completed_at: Optional[str] = None
    abort_reason: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def build(cls, session_id: str, slug: str, objective: str) -> "AgentOperationPlan":
        """Factory: create a new draft plan."""
        return cls(session_id=session_id, slug=slug, objective=objective)

    def add_step(self, step: OperationStep) -> "AgentOperationPlan":
        """Append a step and return self (chainable)."""
        self.steps.append(step)
        return self

    # ── Status helpers ───────────────────────────────────────────────────────

    def mark_running(self) -> None:
        self.status = PlanStatus.RUNNING

    def mark_done(self) -> None:
        self.status = PlanStatus.DONE
        self.completed_at = _utc_now()

    def mark_failed(self) -> None:
        self.status = PlanStatus.FAILED
        self.completed_at = _utc_now()

    def abort(self, reason: str = "") -> None:
        self.status = PlanStatus.ABORTED
        self.abort_reason = reason
        self.completed_at = _utc_now()

    # ── Introspection ────────────────────────────────────────────────────────

    @property
    def is_terminal(self) -> bool:
        return self.status in (PlanStatus.DONE, PlanStatus.FAILED, PlanStatus.ABORTED)

    @property
    def current_step(self) -> Optional[OperationStep]:
        for s in self.steps:
            if s.status in (StepStatus.PENDING, StepStatus.VALIDATING, StepStatus.APPLYING):
                return s
        return None

    @property
    def pending_steps(self) -> list[OperationStep]:
        return [s for s in self.steps if s.status == StepStatus.PENDING]

    @property
    def failed_steps(self) -> list[OperationStep]:
        return [s for s in self.steps if s.status == StepStatus.FAILED]

    @property
    def completed_steps(self) -> list[OperationStep]:
        return [s for s in self.steps if s.status == StepStatus.DONE]

    def progress(self) -> tuple[int, int]:
        """Return (completed_count, total_count)."""
        done = sum(1 for s in self.steps if s.status in (StepStatus.DONE, StepStatus.SKIPPED))
        return done, len(self.steps)

    def summary(self) -> str:
        """One-line human-readable plan summary for logging."""
        done, total = self.progress()
        return (
            f"Plan[{self.plan_id[:8]}] {self.status.value} "
            f"{done}/{total} steps | objective={self.objective!r}"
        )

    # ── Serialisation ────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """JSON-serialisable representation for persistence and UI."""
        done, total = self.progress()
        return {
            "plan_id": self.plan_id,
            "session_id": self.session_id,
            "slug": self.slug,
            "objective": self.objective,
            "status": self.status.value,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "abort_reason": self.abort_reason,
            "progress": {"done": done, "total": total},
            "steps": [s.to_dict() for s in self.steps],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgentOperationPlan":
        """Deserialise from a dict (e.g. loaded from DB JSON column)."""
        plan = cls(
            plan_id=data.get("plan_id", str(uuid.uuid4())),
            session_id=data.get("session_id", ""),
            slug=data.get("slug", ""),
            objective=data.get("objective", ""),
            status=PlanStatus(data.get("status", "draft")),
            created_at=data.get("created_at", _utc_now()),
            completed_at=data.get("completed_at"),
            abort_reason=data.get("abort_reason"),
            metadata=data.get("metadata", {}),
        )
        for sd in data.get("steps", []):
            step = OperationStep(
                capability=sd["capability"],
                params=sd.get("params", {}),
                description=sd.get("description", ""),
                status=StepStatus(sd.get("status", "pending")),
                result=sd.get("result"),
                error=sd.get("error"),
                continue_on_failure=sd.get("continue_on_failure", False),
                requires_validation=sd.get("requires_validation", True),
                validation_result=sd.get("validation_result"),
            )
            step._started_at = sd.get("started_at")
            step._finished_at = sd.get("finished_at")
            plan.steps.append(step)
        return plan


# ---------------------------------------------------------------------------
# Common plan factory helpers
# ---------------------------------------------------------------------------

def plan_add_page(session_id: str, slug: str, page_name: str, description: str) -> AgentOperationPlan:
    """Build a plan to generate a new page and snapshot the workspace."""
    return (
        AgentOperationPlan.build(session_id, slug, f"Add page: {page_name}")
        .add_step(OperationStep(
            capability="generate_page",
            params={"slug": slug, "page_name": page_name, "description": description},
            description=f"Generate {page_name}.html",
        ))
        .add_step(OperationStep(
            capability="validate_html",
            params={"slug": slug, "relative_path": f"pages/{page_name}.html"},
            description=f"Validate {page_name}.html accessibility",
            requires_validation=False,
        ))
        .add_step(OperationStep(
            capability="save_version",
            params={"session_id": session_id, "label": f"add-page-{page_name}"},
            description="Snapshot workspace",
            requires_validation=False,
        ))
    )


def plan_edit_section(
    session_id: str, slug: str, relative_path: str,
    section: str, instruction: str,
) -> AgentOperationPlan:
    """Build a plan to edit a section of an existing page with a rollback snapshot."""
    return (
        AgentOperationPlan.build(session_id, slug, f"Edit {section} in {relative_path}")
        .add_step(OperationStep(
            capability="save_version",
            params={"session_id": session_id, "label": f"pre-edit-{section}"},
            description="Pre-edit snapshot (rollback point)",
            requires_validation=False,
        ))
        .add_step(OperationStep(
            capability="edit_section",
            params={
                "slug": slug,
                "relative_path": relative_path,
                "section": section,
                "instruction": instruction,
            },
            description=f"Apply edit to {section} section",
        ))
        .add_step(OperationStep(
            capability="validate_html",
            params={"slug": slug, "relative_path": relative_path},
            description="Validate result",
            requires_validation=False,
            continue_on_failure=True,  # validation failure is non-blocking
        ))
    )


def plan_restore(session_id: str, slug: str, version_id: str) -> AgentOperationPlan:
    """Build a plan to restore a workspace to a previous version."""
    return (
        AgentOperationPlan.build(session_id, slug, f"Restore to version {version_id[:8]}")
        .add_step(OperationStep(
            capability="restore_version",
            params={"session_id": session_id, "version_id": version_id},
            description=f"Restore workspace snapshot {version_id[:8]}",
            requires_validation=True,
        ))
    )


