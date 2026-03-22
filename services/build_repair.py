"""
Bounded repair loop for the builder pipeline (Phase 4).

Attempts targeted, strictly-capped fixes on a pending FileChange batch when
pre-apply validation indicates recoverable problems.  This is NOT an open-ended
agent — the loop is a plain ``for range(max_rounds)`` with a hard file cap per
round and a conservative default-off flag.

Public API:
    should_repair(validation_dict)  -> bool
    run_repair_round(slug, changes, validation_dict, round_index, max_files, user_message)
        -> RepairAttemptResult

Mutations:
    run_repair_round mutates ``changes[i].content`` IN PLACE for targeted indices.
    Unrelated FileChange entries are never touched.
    The batch order is preserved.

Trigger conditions (all three checked in priority order):
    1. skipped_by_output_validator contains a non-binary text/HTML path
       (output_validator.validate_files dropped the file).
    2. pending_html_issues contains missing_doctype or missing_title
       for a path that is still in clean_paths (passed validate_files).
    3. spec_issues present — classified as UNRECOVERABLE in v1; does NOT trigger repair.

Success criterion (evaluated by caller after recomputing pre_apply_orchestrate):
    The targeted path is no longer in skipped_by_output_validator / pending_html_issues
    AND no new pre_partition_issues with severity "error" were introduced for it.
"""

from __future__ import annotations

import logging
import re as _re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class RepairFailureClass(str, Enum):
    """Classifies why a file failed pre-apply validation."""

    OUTPUT_VALIDATOR_DROP = "output_validator_drop"
    """validate_files dropped the file (not HTML, or missing critical responsive contract)."""

    PARTITION_REJECT = "partition_reject"
    """workspace_editor rejected the path (bad extension, traversal, etc.) — UNRECOVERABLE."""

    MISSING_DOCTYPE = "missing_doctype"
    """HTML file is in clean_paths but lacks <!DOCTYPE html>."""

    MISSING_TITLE = "missing_title"
    """HTML file is in clean_paths but lacks <title>."""

    INVALID_SITE_SPEC = "invalid_site_spec"
    """_spec.json failed schema validation — UNRECOVERABLE in v1."""

    UNRECOVERABLE = "unrecoverable"
    """Cannot be fixed deterministically or via a single targeted LLM call in v1."""


class RepairStrategy(str, Enum):
    """Strategy applied to one FileChange to correct a specific failure."""

    DETERMINISTIC_DOCTYPE_INJECT = "deterministic_doctype_inject"
    """Prepend <!DOCTYPE html> (+ minimal <html> wrapper if content lacks HTML tags)."""

    DETERMINISTIC_TITLE_INJECT = "deterministic_title_inject"
    """Inject <title> into <head> of an otherwise-valid HTML file."""

    DETERMINISTIC_VIEWPORT_INJECT = "deterministic_viewport_inject"
    """Inject viewport <meta> tag to satisfy the responsive critical_violation check."""

    TARGETED_LLM_HTML_FIX = "targeted_llm_html_fix"
    """Single focused LLM call (≤8 k tokens output) to repair an HTML file."""

    UNRECOVERABLE = "unrecoverable"
    """No safe strategy available; change is left untouched."""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RepairTask:
    """One unit of repair work targeting a single FileChange."""

    round_index: int
    change_index: int           # index into the changes list
    path: str                   # rel_path (relative to website root)
    failure_codes: tuple[RepairFailureClass, ...]
    strategy: RepairStrategy


@dataclass
class RepairAttemptResult:
    """Outcome of one repair round (may cover up to max_files paths)."""

    success: bool               # True if ≥1 path was patched
    paths_touched: list[str]    # rel_paths that were actually mutated
    strategies_used: list[str]  # strategy.value for each touched path
    round_index: int
    messages: list[str]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "paths_touched": self.paths_touched,
            "strategies_used": self.strategies_used,
            "round_index": self.round_index,
            "messages": self.messages,
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# Public: trigger check
# ---------------------------------------------------------------------------

# Binary extensions that output_validator correctly skips — not repairable via HTML fix.
_BINARY_EXTS = frozenset((".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico"))


def should_repair(validation_dict: dict) -> bool:
    """Return True if any repairable condition is present in the validation dict.

    Trigger 1: a non-binary path was dropped by output_validator.
    Trigger 2: a path in clean_paths has missing_doctype or missing_title.
    Does NOT trigger on: spec_issues, partition_reject errors, or warning-only output.
    """
    # Trigger 1
    skipped = validation_dict.get("skipped_by_output_validator") or []
    for p in skipped:
        if not any(p.lower().endswith(ext) for ext in _BINARY_EXTS):
            return True

    # Trigger 2: pending_html_issues for missing_doctype / missing_title.
    # build_validation._pending_html_quality() runs only on clean_files, so any
    # path that appears here already passed validate_files — no need to cross-check
    # raw.clean_paths (which is not present in to_dict() output).
    html_issues = validation_dict.get("pending_html_issues") or []
    for issue in html_issues:
        code = _field(issue, "code")
        if code in ("missing_doctype", "missing_title"):
            return True

    return False


# ---------------------------------------------------------------------------
# Public: repair round
# ---------------------------------------------------------------------------

def run_repair_round(
    slug: str,
    changes: list,
    validation_dict: dict,
    round_index: int,
    max_files: int,
    user_message: str = "",
) -> RepairAttemptResult:
    """Attempt to repair up to *max_files* failing paths.

    Mutates ``changes[i].content`` in place for targeted indices only.
    All other entries in *changes* are untouched.
    Returns a RepairAttemptResult describing what happened.
    """
    tasks = _classify_failures(validation_dict, changes, slug, round_index)

    # Only process tasks we can actually fix; cap at max_files
    actionable = [t for t in tasks if t.strategy != RepairStrategy.UNRECOVERABLE][:max_files]

    paths_touched: list[str] = []
    strategies_used: list[str] = []
    messages: list[str] = []
    errors: list[str] = []

    for task in actionable:
        change = changes[task.change_index]
        if not isinstance(change.content, str):
            errors.append(
                f"round={round_index} path={task.path} — binary content; cannot repair"
            )
            continue

        fixed = _apply_strategy(task, change, slug, user_message)
        if fixed is not None and fixed != change.content:
            change.content = fixed  # mutate in place
            paths_touched.append(task.path)
            strategies_used.append(task.strategy.value)
            messages.append(
                f"round={round_index} path={task.path!r} strategy={task.strategy.value} — applied"
            )
            logger.info(
                "Repair round=%d path=%r strategy=%s — content patched (%d→%d chars)",
                round_index, task.path, task.strategy.value,
                len(change.content), len(fixed),
            )
        else:
            errors.append(
                f"round={round_index} path={task.path!r} strategy={task.strategy.value} — no change"
            )
            logger.debug(
                "Repair round=%d path=%r strategy=%s — no change produced",
                round_index, task.path, task.strategy.value,
            )

    # Log UNRECOVERABLE tasks for observability (not touched)
    for task in tasks:
        if task.strategy == RepairStrategy.UNRECOVERABLE:
            messages.append(
                f"round={round_index} path={task.path!r} codes={[c.value for c in task.failure_codes]} — UNRECOVERABLE (skipped)"
            )

    return RepairAttemptResult(
        success=bool(paths_touched),
        paths_touched=paths_touched,
        strategies_used=strategies_used,
        round_index=round_index,
        messages=messages,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# Failure classification
# ---------------------------------------------------------------------------

def _classify_failures(
    validation_dict: dict,
    changes: list,
    slug: str,
    round_index: int,
) -> list[RepairTask]:
    """Produce a RepairTask list from a validation_dict snapshot.

    Priority order:
      1. skipped_by_output_validator (text/HTML drops)
      2. pending_html_issues (missing_doctype, missing_title) on clean paths
      3. spec_issues → UNRECOVERABLE
    """
    tasks: list[RepairTask] = []
    seen_indices: set[int] = set()

    # Build lookup: rel_path -> change_index
    path_to_idx = _build_path_index(changes, slug)

    # --- Priority 1: output_validator drops ---
    skipped = validation_dict.get("skipped_by_output_validator") or []
    for rel_path in skipped:
        if any(rel_path.lower().endswith(ext) for ext in _BINARY_EXTS):
            continue  # binary — not repairable here
        idx = path_to_idx.get(rel_path)
        if idx is None or idx in seen_indices:
            continue
        change = changes[idx]
        if not isinstance(change.content, str):
            continue
        if rel_path.endswith(".html"):
            strategy = _strategy_for_html_drop(change.content)
        else:
            strategy = RepairStrategy.UNRECOVERABLE
        tasks.append(RepairTask(
            round_index=round_index,
            change_index=idx,
            path=rel_path,
            failure_codes=(RepairFailureClass.OUTPUT_VALIDATOR_DROP,),
            strategy=strategy,
        ))
        seen_indices.add(idx)

    # --- Priority 2: pending_html_issues ---
    # These paths passed validate_files by construction (pending_html_quality
    # runs only on clean_files), so no clean_paths cross-check needed.
    html_issues = validation_dict.get("pending_html_issues") or []
    for issue in html_issues:
        code = _field(issue, "code")
        rel_path = _field(issue, "path")
        if not rel_path:
            continue
        idx = path_to_idx.get(rel_path)
        if idx is None or idx in seen_indices:
            continue
        if code == "missing_doctype":
            fc = (RepairFailureClass.MISSING_DOCTYPE,)
            strategy = RepairStrategy.DETERMINISTIC_DOCTYPE_INJECT
        elif code == "missing_title":
            fc = (RepairFailureClass.MISSING_TITLE,)
            strategy = RepairStrategy.DETERMINISTIC_TITLE_INJECT
        else:
            continue
        tasks.append(RepairTask(
            round_index=round_index,
            change_index=idx,
            path=rel_path,
            failure_codes=fc,
            strategy=strategy,
        ))
        seen_indices.add(idx)

    # --- Priority 3: spec_issues → UNRECOVERABLE in v1 ---
    spec_issues = validation_dict.get("spec_issues") or []
    for issue in spec_issues:
        rel_path = _field(issue, "path")
        if not rel_path:
            continue
        idx = path_to_idx.get(rel_path)
        if idx is None or idx in seen_indices:
            continue
        tasks.append(RepairTask(
            round_index=round_index,
            change_index=idx,
            path=rel_path,
            failure_codes=(RepairFailureClass.INVALID_SITE_SPEC,),
            strategy=RepairStrategy.UNRECOVERABLE,
        ))
        seen_indices.add(idx)

    return tasks


def _strategy_for_html_drop(content: str) -> RepairStrategy:
    """Determine which deterministic or LLM strategy can fix an HTML drop.

    Distinction:
      - _looks_like_html() False → "does not look like HTML" warning → DOCTYPE inject
      - _looks_like_html() True  → "missing critical responsive contract" warning → viewport inject
    """
    head = content.strip().lower()[:300]
    already_looks_html = "<!doctype" in head or "<html" in head
    if already_looks_html:
        # Passed _looks_like_html but dropped for responsive critical_violation.
        # Injecting viewport meta makes has_viewport=True → critical_violation=False.
        return RepairStrategy.DETERMINISTIC_VIEWPORT_INJECT
    else:
        # Check if HTML tags exist deeper in content (preamble/whitespace issue)
        lower_full = content.lower()
        has_doctype_deep = "<!doctype" in lower_full
        has_html_deep = "<html" in lower_full
        if has_doctype_deep or has_html_deep:
            # Structural HTML exists but not at start — prepend / strip preamble
            return RepairStrategy.DETERMINISTIC_DOCTYPE_INJECT
        # No HTML structure at all — single LLM call to reconstruct
        return RepairStrategy.TARGETED_LLM_HTML_FIX


# ---------------------------------------------------------------------------
# Strategy implementations
# ---------------------------------------------------------------------------

def _apply_strategy(
    task: RepairTask,
    change: Any,
    slug: str,
    user_message: str,
) -> str | None:
    """Dispatch to the appropriate fix function. Returns patched content or None."""
    content: str = change.content
    s = task.strategy

    if s == RepairStrategy.DETERMINISTIC_DOCTYPE_INJECT:
        return _fix_inject_doctype(content)
    if s == RepairStrategy.DETERMINISTIC_TITLE_INJECT:
        return _fix_inject_title(content, slug)
    if s == RepairStrategy.DETERMINISTIC_VIEWPORT_INJECT:
        return _fix_inject_viewport(content)
    if s == RepairStrategy.TARGETED_LLM_HTML_FIX:
        return _fix_llm_html(content, task, user_message)
    return None  # UNRECOVERABLE


_VIEWPORT_RE = _re.compile(
    r'<meta[^>]+name=["\']viewport["\'][^>]*>',
    _re.IGNORECASE,
)


def _fix_inject_doctype(content: str) -> str:
    """Prepend <!DOCTYPE html> so _looks_like_html() returns True.

    Cases handled:
      1. DOCTYPE exists deeper → strip leading preamble
      2. <html> tag exists deeper → prepend DOCTYPE before it
      3. No HTML structure → wrap in minimal boilerplate
    """
    stripped = content.strip()
    lower = stripped.lower()

    # Already fine — guard (shouldn't happen but be safe)
    if lower.startswith("<!doctype"):
        return content

    # DOCTYPE exists deeper in the file — strip leading preamble
    dt_idx = lower.find("<!doctype")
    if dt_idx > 0:
        return stripped[dt_idx:]

    # <html> exists deeper — prepend DOCTYPE before it
    html_idx = lower.find("<html")
    if html_idx >= 0:
        return "<!DOCTYPE html>\n" + stripped[html_idx:]

    # No HTML structure — wrap in minimal boilerplate
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>Page</title>\n"
        "</head>\n"
        "<body>\n"
        f"{stripped}\n"
        "</body>\n"
        "</html>"
    )


def _fix_inject_title(content: str, slug: str) -> str:
    """Inject <title> into <head> if the file lacks one."""
    if "<title>" in content.lower()[:2000]:
        return content  # already present

    title_text = slug.replace("-", " ").title()

    # Inject after <head>
    m = _re.search(r"(<head[^>]*>)", content, _re.IGNORECASE)
    if m:
        return content[: m.end()] + f"\n  <title>{title_text}</title>" + content[m.end():]

    # Fall back: inject before <body>
    m = _re.search(r"<body", content, _re.IGNORECASE)
    if m:
        return (
            content[: m.start()]
            + f"<head>\n  <title>{title_text}</title>\n</head>\n"
            + content[m.start():]
        )

    return content


def _fix_inject_viewport(content: str) -> str:
    """Inject viewport <meta> tag to satisfy the responsive critical_violation check.

    Injecting viewport alone is sufficient because:
        critical_violation = not has_viewport AND not breakpoints AND len > 1200
    Once has_viewport is True the whole expression is False.
    """
    if _VIEWPORT_RE.search(content):
        return content  # already present

    vp = '<meta name="viewport" content="width=device-width, initial-scale=1">'

    # Inject after <head>
    m = _re.search(r"(<head[^>]*>)", content, _re.IGNORECASE)
    if m:
        return content[: m.end()] + f"\n  {vp}" + content[m.end():]

    # Inject before <title> if no <head>
    m = _re.search(r"<title", content, _re.IGNORECASE)
    if m:
        return content[: m.start()] + f"{vp}\n  " + content[m.start():]

    return content


_REPAIR_SYSTEM_PROMPT = """\
You are a web developer fixing a broken HTML file. Return ONLY the corrected,
complete HTML file — from <!DOCTYPE html> to </html>. No commentary, no fences.

Apply ONLY the following fixes:
- Add <!DOCTYPE html> at the very start if missing.
- Add <html lang="en"> wrapper if missing.
- Add <meta charset="utf-8"> in <head> if missing.
- Add <meta name="viewport" content="width=device-width, initial-scale=1"> if missing.
- Add at least one @media (max-width: 640px) { } breakpoint in <style> if missing.
- Add <title> in <head> if missing.

Do NOT change any existing content, colors, layout, copy, or structure.
"""


def _fix_llm_html(content: str, task: RepairTask, user_message: str) -> str | None:
    """Single focused LLM call to fix an HTML file. Returns fixed HTML or None."""
    try:
        from services.provider_router import call_llm

        failure_summary = ", ".join(c.value for c in task.failure_codes)
        prompt = (
            f"Original user request (context only): {user_message[:300]}\n\n"
            f"Failure reason: {failure_summary}\n\n"
            f"Fix this HTML file:\n\n{content[:10000]}"
        )
        messages = [
            {"role": "system", "content": _REPAIR_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        result = call_llm(messages, max_tokens=8000)
        if result.fallback_used or not result.content:
            logger.warning("LLM repair got fallback/empty for path=%r", task.path)
            return None
        return _extract_html_from_llm(result.content)
    except Exception as exc:
        logger.warning("LLM repair failed for path=%r: %s", task.path, exc)
        return None


def _extract_html_from_llm(content: str) -> str | None:
    """Extract raw HTML from an LLM response (strips markdown fences if present)."""
    text = content.strip()
    fence = _re.search(
        r"```(?:html)?\s*\n?(<!DOCTYPE.*?</html>)\s*```",
        text,
        _re.DOTALL | _re.IGNORECASE,
    )
    if fence:
        return fence.group(1).strip()
    if text.lower().startswith("<!doctype") or text.lower().startswith("<html"):
        end = text.rfind("</html>")
        if end != -1:
            return text[: end + 7]
        return text
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_path_index(changes: list, slug: str) -> dict[str, int]:
    """Return {rel_path: change_index} for all changes in the batch."""
    prefix = f"data/websites/{slug}/"
    idx: dict[str, int] = {}
    for i, ch in enumerate(changes):
        path = getattr(ch, "path", "") or ""
        if path.startswith(prefix):
            rel = path[len(prefix):]
        elif "/" not in path and path:
            rel = path  # bare filename
        else:
            rel = None
        if rel:
            idx[rel] = i
            idx[path] = i  # also index by full path
    return idx


def _field(obj: Any, name: str) -> str:
    """Safe field accessor for dict or dataclass-like objects."""
    if isinstance(obj, dict):
        return str(obj.get(name) or "")
    return str(getattr(obj, name, "") or "")
