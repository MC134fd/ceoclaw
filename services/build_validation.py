"""
Validation orchestration for builder runs.

Wraps existing validators (output, site spec, lightweight HTML checks) without
duplicating their rules. Phase 1 runs pre-apply analysis alongside the existing
apply path — results are recorded for observability; ``apply_changes`` remains
the authority for what is written.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ValidationIssue:
    """Single normalized validation finding."""

    code: str
    message: str
    path: str = ""
    severity: str = "info"  # "info" | "warning" | "error"


@dataclass
class BuildValidationResult:
    """Aggregated outcome of pre-apply validation orchestration."""

    ok: bool
    pre_partition_issues: tuple[ValidationIssue, ...] = ()
    output_warnings: tuple[str, ...] = ()
    spec_issues: tuple[ValidationIssue, ...] = ()
    pending_html_issues: tuple[ValidationIssue, ...] = ()
    skipped_by_output_validator: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "pre_partition_issues": [asdict(i) for i in self.pre_partition_issues],
            "output_warnings": list(self.output_warnings),
            "spec_issues": [asdict(i) for i in self.spec_issues],
            "pending_html_issues": [asdict(i) for i in self.pending_html_issues],
            "skipped_by_output_validator": list(self.skipped_by_output_validator),
        }


def _issues_from_partition_results(pre_results: list) -> list[ValidationIssue]:
    from services.workspace_editor import ChangeResult

    out: list[ValidationIssue] = []
    for r in pre_results:
        if not isinstance(r, ChangeResult):
            continue
        if r.status == "applied":
            continue
        code = "rejected_path" if r.status == "rejected" else "skipped_empty"
        sev = "error" if r.status == "rejected" else "warning"
        msg = r.error or r.status
        out.append(ValidationIssue(code=code, message=msg, path=r.path, severity=sev))
    return out


def _validate_spec_json_if_present(rel_path: str, content: str) -> list[ValidationIssue]:
    if not rel_path.endswith("_spec.json"):
        return []
    try:
        from services.site_spec import validate_spec

        raw = json.loads(content)
        validate_spec(raw)
    except Exception as exc:
        return [
            ValidationIssue(
                code="invalid_site_spec",
                message=str(exc),
                path=rel_path,
                severity="warning",
            )
        ]
    return []


def _pending_html_quality(rel_path: str, html: str) -> list[ValidationIssue]:
    """Mirror lightweight checks from generation_pipeline._run_quality_check (pre-apply)."""
    if not rel_path.endswith(".html"):
        return []
    issues: list[ValidationIssue] = []
    head = html[:200]
    if "<!DOCTYPE" not in head:
        issues.append(
            ValidationIssue(
                code="missing_doctype",
                message="missing DOCTYPE in first 200 chars",
                path=rel_path,
                severity="info",
            )
        )
    lower = html.lower()[:2000]
    if "<title>" not in lower:
        issues.append(
            ValidationIssue(
                code="missing_title",
                message="missing <title> in first 2000 chars",
                path=rel_path,
                severity="info",
            )
        )
    return issues


def pre_apply_orchestrate(slug: str, changes: list[Any]) -> BuildValidationResult:
    """Run consolidated validation for pending FileChanges before disk apply.

    Uses the same partition + ``validate_files`` path as ``apply_changes`` for
    the pending batch. Does not modify ``changes``.
    """
    from services.output_validator import validate_files
    from services.workspace_editor import partition_changes_for_write

    files_to_write, pre_results = partition_changes_for_write(slug, changes)
    pre_issues = tuple(_issues_from_partition_results(pre_results))

    if not files_to_write:
        ok = not any(i.severity == "error" for i in pre_issues)
        return BuildValidationResult(
            ok=ok,
            pre_partition_issues=pre_issues,
            raw={"pending_paths": []},
        )

    clean_files, val_warnings = validate_files(files_to_write)
    skipped = tuple(sorted(set(files_to_write.keys()) - set(clean_files.keys())))

    spec_issues: list[ValidationIssue] = []
    for rel_path, body in files_to_write.items():
        if isinstance(body, str) and rel_path.endswith("_spec.json"):
            spec_issues.extend(_validate_spec_json_if_present(rel_path, body))

    html_issues: list[ValidationIssue] = []
    for rel_path, body in clean_files.items():
        if isinstance(body, str):
            html_issues.extend(_pending_html_quality(rel_path, body))

    spec_t = tuple(spec_issues)
    html_t = tuple(html_issues)
    warn_t = tuple(val_warnings)

    blocking = any(i.severity == "error" for i in pre_issues)
    ok = not blocking

    if skipped or spec_issues or any("critical" in w.lower() for w in val_warnings):
        logger.info(
            "pre_apply_orchestrate slug=%r skipped_paths=%s spec_warnings=%d",
            slug,
            skipped,
            len(spec_issues),
        )

    return BuildValidationResult(
        ok=ok,
        pre_partition_issues=pre_issues,
        output_warnings=warn_t,
        spec_issues=spec_t,
        pending_html_issues=html_t,
        skipped_by_output_validator=skipped,
        raw={
            "pending_paths": sorted(files_to_write.keys()),
            "clean_paths": sorted(clean_files.keys()),
        },
    )
