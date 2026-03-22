"""
Structured build plan for one pipeline run (Phase 2 — planning layer).

Deterministic, serializable summary of intended file work and generation ordering.
Does not replace BrandSpec, site_spec, or generate(); it documents intent for
debugging and future tighter orchestration.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)

SessionMode = Literal["new_project", "edit"]
GenerationFlavor = Literal[
    "spec_first_preferred",
    "legacy_per_file",
    "edit_existing",
    "unknown",
]


@dataclass(frozen=True)
class FileOperationIntent:
    """Per-path intent for this run (not a guarantee of what generate() will touch)."""

    path: str
    intent: Literal["create", "update", "unchanged"]
    notes: str = ""


@dataclass(frozen=True)
class BuildPlanTask:
    """One ordered unit of generation work (legacy/scaffold) or a spec-phase label."""

    task_id: str
    path: str
    intent: Literal["create", "update", "spec_synthesize", "spec_patch", "edit_candidate"]
    depends_on: tuple[str, ...] = ()
    notes: str = ""


@dataclass(frozen=True)
class PlanConstraints:
    """High-level constraints for this run."""

    session_mode: SessionMode
    generation_flavor: GenerationFlavor
    has_disk_spec: bool = False


@dataclass(frozen=True)
class BuildPlan:
    """Full plan: file intents, ordered tasks, untouched paths, and notes."""

    constraints: PlanConstraints
    file_intents: tuple[FileOperationIntent, ...]
    generation_tasks: tuple[BuildPlanTask, ...]
    unchanged_paths: tuple[str, ...]
    notes: tuple[str, ...] = ()
    refs: tuple[tuple[str, Any], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "constraints": {
                "session_mode": self.constraints.session_mode,
                "generation_flavor": self.constraints.generation_flavor,
                "has_disk_spec": self.constraints.has_disk_spec,
            },
            "file_intents": [
                {"path": i.path, "intent": i.intent, "notes": i.notes}
                for i in self.file_intents
            ],
            "generation_tasks": [
                {
                    "task_id": t.task_id,
                    "path": t.path,
                    "intent": t.intent,
                    "depends_on": list(t.depends_on),
                    "notes": t.notes,
                }
                for t in self.generation_tasks
            ],
            "unchanged_paths": list(self.unchanged_paths),
            "notes": list(self.notes),
            "refs": dict(self.refs),
        }


_ASSET_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico", ".svg")


def _is_probably_binary_asset(path: str) -> bool:
    lower = path.lower()
    return any(lower.endswith(s) for s in _ASSET_SUFFIXES)


def _brand_pages(brand_spec: Any | None) -> list[str]:
    if brand_spec is None:
        return []
    pages = getattr(brand_spec, "pages", None) or []
    return [p for p in pages if isinstance(p, str) and p.strip()]


def _brand_name(brand_spec: Any | None) -> str:
    if brand_spec is None:
        return ""
    return str(getattr(brand_spec, "brand_name", "") or "")


def _scaffold_as_dict(scaffold: Mapping[str, Any] | dict[str, Any] | None) -> dict[str, Any]:
    if scaffold is None:
        return {}
    if isinstance(scaffold, dict):
        return scaffold
    return dict(scaffold)


def _tasks_from_scaffold(scaffold: dict[str, Any]) -> tuple[BuildPlanTask, ...]:
    order = list(scaffold.get("generation_order") or [])
    if not order:
        for entry in scaffold.get("file_tree") or []:
            if isinstance(entry, dict) and entry.get("path"):
                order.append(entry["path"])

    tree_entries: dict[str, dict[str, Any]] = {}
    for entry in scaffold.get("file_tree") or []:
        if isinstance(entry, dict) and entry.get("path"):
            tree_entries[str(entry["path"])] = entry

    tasks: list[BuildPlanTask] = []
    order_set = set(order)
    for i, path in enumerate(order):
        entry = tree_entries.get(path, {})
        raw_deps = entry.get("depends_on") or []
        deps = tuple(str(d) for d in raw_deps if isinstance(d, str) and d in order_set)
        purpose = entry.get("purpose") if isinstance(entry.get("purpose"), str) else ""
        notes = purpose[:240] if purpose else ""
        tasks.append(
            BuildPlanTask(
                task_id=f"create-{i + 1}",
                path=str(path),
                intent="create",
                depends_on=deps,
                notes=notes,
            )
        )
    return tuple(tasks)


def build_plan_from_project_state(state: Any) -> BuildPlan:
    """Derive a BuildPlan from ``BuildProjectState`` (read-only)."""
    is_edit = bool(getattr(state, "is_edit", False))
    has_disk_spec = getattr(state, "spec_snapshot", None) is not None

    if is_edit:
        return _plan_edit_mode(state, has_disk_spec)

    return _plan_new_project(state, has_disk_spec)


def _plan_edit_mode(state: Any, has_disk_spec: bool) -> BuildPlan:
    existing = getattr(state, "existing_files", None)
    paths = sorted(existing.keys()) if existing else []

    unchanged = tuple(p for p in paths if _is_probably_binary_asset(p))
    unchanged_set = set(unchanged)
    update_paths = tuple(p for p in paths if p not in unchanged_set)

    intents = tuple(
        FileOperationIntent(
            path=p,
            intent="unchanged" if p in unchanged_set else "update",
            notes="asset — not a primary text-edit target" if p in unchanged_set else "in scope for spec/CSS/LLM edit pipeline",
        )
        for p in paths
    )

    tasks = tuple(
        BuildPlanTask(
            task_id=f"edit-{i + 1}",
            path=p,
            intent="edit_candidate",
            depends_on=(),
            notes="Candidate target; actual target chosen inside generate()",
        )
        for i, p in enumerate(update_paths)
    )

    notes = (
        "Edit pipeline order: spec patch (if _spec.json) → direct CSS → single-file LLM.",
        "Multiple HTML files may update for sitewide CSS heuristics.",
    )

    op = getattr(state, "operation", None)
    op_type = dict(op).get("type", "") if op is not None else ""

    refs = (
        ("brand_name", _brand_name(getattr(state, "brand_spec", None))),
        ("existing_path_count", len(paths)),
        ("operation_type", op_type),
    )

    return BuildPlan(
        constraints=PlanConstraints(
            session_mode="edit",
            generation_flavor="edit_existing",
            has_disk_spec=has_disk_spec,
        ),
        file_intents=intents,
        generation_tasks=tasks,
        unchanged_paths=unchanged,
        notes=notes,
        refs=refs,
    )


def _plan_new_project(state: Any, has_disk_spec: bool) -> BuildPlan:
    scaffold = _scaffold_as_dict(getattr(state, "scaffold", None))
    order = list(scaffold.get("generation_order") or [])
    if not order:
        for entry in scaffold.get("file_tree") or []:
            if isinstance(entry, dict) and entry.get("path"):
                order.append(str(entry["path"]))

    tasks_scaffold = _tasks_from_scaffold(scaffold)
    intents = tuple(FileOperationIntent(p, "create", "") for p in order)

    spec_task = BuildPlanTask(
        task_id="spec-1",
        path="_spec.json",
        intent="spec_synthesize",
        depends_on=(),
        notes="Preferred path: SiteSpec JSON via LLM then render derived HTML (generate_via_spec).",
    )
    # Spec task first conceptually; legacy tasks still describe fallback ordering.
    generation_tasks = (spec_task,) + tasks_scaffold

    brand_pages = _brand_pages(getattr(state, "brand_spec", None))
    extra_pages = [p for p in brand_pages if p not in set(order)]
    notes_list = [
        "New project: generate() tries spec-first; legacy per-file order follows scaffold when spec fails.",
    ]
    if extra_pages:
        notes_list.append(f"BrandSpec.pages not listed in scaffold order (informational): {extra_pages}")

    refs = (
        ("brand_name", _brand_name(getattr(state, "brand_spec", None))),
        ("scaffold_project_type", str(scaffold.get("project_type", "") or "")),
        ("scaffold_ordered_paths", tuple(order)),
        ("brand_pages", tuple(brand_pages)),
    )

    return BuildPlan(
        constraints=PlanConstraints(
            session_mode="new_project",
            generation_flavor="spec_first_preferred",
            has_disk_spec=has_disk_spec,
        ),
        file_intents=intents,
        generation_tasks=generation_tasks,
        unchanged_paths=(),
        notes=tuple(notes_list),
        refs=refs,
    )


def build_plan_fallback(*, slug: str, is_edit: bool, has_disk_spec: bool = False) -> BuildPlan:
    """Minimal plan if primary construction must not fail the pipeline."""
    mode: SessionMode = "edit" if is_edit else "new_project"
    flavor: GenerationFlavor = "edit_existing" if is_edit else "unknown"
    return BuildPlan(
        constraints=PlanConstraints(
            session_mode=mode,
            generation_flavor=flavor,
            has_disk_spec=has_disk_spec,
        ),
        file_intents=(),
        generation_tasks=(),
        unchanged_paths=(),
        notes=("Fallback plan — detailed scaffold/state unavailable.",),
        refs=(("slug", slug),),
    )
