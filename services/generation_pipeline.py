"""
Orchestrated website generation pipeline.

Stages (in order):
  parse_intent  → validate_idea → content_plan → image_assets →
  generate_code → apply_files   → quality_check → complete

Each stage emits structured events via an `emit` callback.  The caller
(api/server.py) routes those events to the SSE event bus so the frontend
can render a live build log.

Public API:
    result = run_pipeline(
        session_id, slug, message, history, existing_files,
        mock_mode, style_seed, design_system, operation, emit,
    )
    # result keys: intent, validation, content_plan, image_assets, gen, apply, quality
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stage definitions (order matters)
# ---------------------------------------------------------------------------

STAGE_DEFS: list[tuple[str, str]] = [
    ("parse_intent",   "Reading your idea"),
    ("validate_idea",  "Validating concept"),
    ("content_plan",   "Planning content"),
    ("image_assets",   "Creating visual assets"),
    ("generate_code",  "Generating code"),
    ("apply_files",    "Saving to workspace"),
    ("quality_check",  "Quality check"),
    ("complete",       "Complete"),
]

Emit = Callable[[dict[str, Any]], None]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _emit_stage(
    emit: Emit,
    stage_key: str,
    stage_label: str,
    status: str,
    **kwargs: Any,
) -> None:
    evt: dict[str, Any] = {
        "type": "stage_update",
        "stage_key": stage_key,
        "stage_label": stage_label,
        "status": status,
    }
    evt.update(kwargs)
    emit(evt)


def _timed(fn: Callable) -> tuple[Any, int]:
    """Run fn() and return (result, elapsed_ms)."""
    t0 = time.monotonic()
    result = fn()
    return result, int((time.monotonic() - t0) * 1000)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_pipeline(
    session_id: str,
    slug: str,
    message: str,
    history: list[dict[str, Any]],
    existing_files: dict[str, str] | None,
    mock_mode: bool,
    style_seed: dict[str, Any] | None,
    design_system: dict[str, Any] | None,
    operation: dict[str, Any] | None,
    emit: Emit,
) -> dict[str, Any]:
    """
    Execute the full pipeline.  Returns a dict with intermediate artifacts
    plus the final LLM GenerateResult (under key 'gen') and apply result
    (under key 'apply').

    Raises on fatal errors (generate_code / apply_files failure); all other
    stage errors are captured and emitted without aborting the pipeline.
    """
    ctx: dict[str, Any] = {}

    # ── Stage 1: parse_intent ───────────────────────────────────────────────
    _emit_stage(emit, "parse_intent", "Reading your idea", "running")
    try:
        from core.intent_parser import parse_intent
        intent, ms = _timed(lambda: parse_intent(message))
        _emit_stage(emit, "parse_intent", "Reading your idea", "done",
                    duration_ms=ms,
                    artifact_type="intent",
                    artifact_name=intent.get("product_name", ""))
        ctx["intent"] = intent
    except Exception as exc:
        _emit_stage(emit, "parse_intent", "Reading your idea", "error", error=str(exc))
        ctx["intent"] = {"product_name": slug.replace("-", " ").title()}

    # ── Stage 2: validate_idea ──────────────────────────────────────────────
    _emit_stage(emit, "validate_idea", "Validating concept", "running")
    try:
        validation, ms = _timed(lambda: _validate_idea(message, ctx["intent"]))
        _emit_stage(emit, "validate_idea", "Validating concept", "done",
                    duration_ms=ms,
                    artifact_type="validation",
                    artifact_name=validation["verdict"])
        ctx["validation"] = validation
    except Exception as exc:
        _emit_stage(emit, "validate_idea", "Validating concept", "error", error=str(exc))
        ctx["validation"] = {"verdict": "ok"}

    # ── Stage 3: content_plan ───────────────────────────────────────────────
    _emit_stage(emit, "content_plan", "Planning content", "running")
    try:
        plan, ms = _timed(lambda: _derive_content_plan(ctx["intent"], existing_files))
        pages = plan.get("pages", [])
        _emit_stage(emit, "content_plan", "Planning content", "done",
                    duration_ms=ms,
                    artifact_type="content_plan",
                    artifact_name=f"{len(pages)} page{'s' if len(pages) != 1 else ''}")
        ctx["content_plan"] = plan
    except Exception as exc:
        _emit_stage(emit, "content_plan", "Planning content", "error", error=str(exc))
        ctx["content_plan"] = {"pages": ["index.html"]}

    # ── Stage 4: image_assets ───────────────────────────────────────────────
    _emit_stage(emit, "image_assets", "Creating visual assets", "running")
    try:
        assets, ms = _timed(lambda: _generate_image_assets(ctx["intent"], slug))
        _emit_stage(emit, "image_assets", "Creating visual assets", "done",
                    duration_ms=ms,
                    artifact_type="images",
                    artifact_name=f"{len(assets)} SVG asset{'s' if len(assets) != 1 else ''}")
        ctx["image_assets"] = assets
    except Exception as exc:
        _emit_stage(emit, "image_assets", "Creating visual assets", "error", error=str(exc))
        ctx["image_assets"] = {}

    # ── Stage 5: generate_code ──────────────────────────────────────────────
    _emit_stage(emit, "generate_code", "Generating code", "running")
    try:
        from services.code_generation_service import FileChange, generate

        def _gen():
            return generate(
                slug=slug,
                user_message=message,
                history=history,
                existing_files=existing_files,
                mock_mode=mock_mode,
                style_seed=style_seed,
                design_system=design_system,
                operation=operation,
            )

        gen_result, ms = _timed(_gen)

        # Append SVG asset files as extra changes
        for asset_path, svg_content in ctx["image_assets"].items():
            gen_result.changes.append(FileChange(
                path=f"data/websites/{slug}/{asset_path}",
                action="create",
                content=svg_content,
                summary="Generated SVG asset",
            ))

        file_count = len(gen_result.changes)
        _emit_stage(emit, "generate_code", "Generating code", "done",
                    duration_ms=ms,
                    artifact_type="code",
                    artifact_name=f"{file_count} file{'s' if file_count != 1 else ''}")
        ctx["gen"] = gen_result
    except Exception as exc:
        _emit_stage(emit, "generate_code", "Generating code", "error", error=str(exc))
        raise  # fatal — cannot continue without generated code

    # ── Stage 6: apply_files ────────────────────────────────────────────────
    _emit_stage(emit, "apply_files", "Saving to workspace", "running")
    try:
        from services.workspace_editor import apply_changes

        apply_result, ms = _timed(lambda: apply_changes(slug=slug, changes=ctx["gen"].changes))
        applied_names = ", ".join(apply_result.applied[:3]) or "0 files"
        if len(apply_result.applied) > 3:
            applied_names += f" +{len(apply_result.applied) - 3} more"
        _emit_stage(emit, "apply_files", "Saving to workspace", "done",
                    duration_ms=ms,
                    artifact_type="files",
                    artifact_name=applied_names)
        ctx["apply"] = apply_result
    except Exception as exc:
        _emit_stage(emit, "apply_files", "Saving to workspace", "error", error=str(exc))
        raise  # fatal

    # ── Stage 7: quality_check ──────────────────────────────────────────────
    _emit_stage(emit, "quality_check", "Quality check", "running")
    try:
        quality, ms = _timed(lambda: _run_quality_check(slug, ctx["apply"]))
        _emit_stage(emit, "quality_check", "Quality check", "done",
                    duration_ms=ms,
                    artifact_type="quality",
                    artifact_name=quality["summary"])
        ctx["quality"] = quality
    except Exception as exc:
        _emit_stage(emit, "quality_check", "Quality check", "error", error=str(exc))
        ctx["quality"] = {"summary": "check skipped"}

    # ── Stage 8: complete ───────────────────────────────────────────────────
    _emit_stage(emit, "complete", "Complete", "done", duration_ms=0)

    return ctx


# ---------------------------------------------------------------------------
# Stage implementations
# ---------------------------------------------------------------------------

def _validate_idea(message: str, intent: dict[str, Any]) -> dict[str, Any]:
    """Heuristic idea validation — no LLM required."""
    msg = message.strip()
    if len(msg) < 5:
        return {"verdict": "too_short",
                "suggestion": "Tell me more about your product idea."}
    product_name = intent.get("product_name", "")
    features = intent.get("core_features") or []
    if not product_name and not features:
        return {"verdict": "vague",
                "suggestion": "What problem does your product solve, and for whom?"}
    return {"verdict": "ok", "product_name": product_name, "features": features}


def _derive_content_plan(
    intent: dict[str, Any],
    existing_files: dict[str, str] | None,
) -> dict[str, Any]:
    """Plan pages and sections based on intent."""
    if existing_files:
        return {"mode": "edit", "pages": list(existing_files.keys())}

    product_type = (intent.get("product_type") or "saas").lower()
    features = intent.get("core_features") or []

    pages = ["index.html"]
    sections: dict[str, list[str]] = {
        "index.html": ["hero", "features", "social_proof", "pricing", "cta", "footer"],
    }
    # Add app page for products with dashboards / data
    if product_type in ("saas", "app", "tool", "platform") or len(features) > 2:
        pages.append("app.html")
        sections["app.html"] = ["sidebar", "dashboard", "metrics_row", "data_table", "settings"]

    return {
        "mode": "new",
        "pages": pages,
        "sections": sections,
        "product_type": product_type,
        "feature_count": len(features),
    }


def _generate_image_assets(
    intent: dict[str, Any],
    slug: str,
) -> dict[str, str]:
    """Generate SVG placeholder assets for the product."""
    from services.image_adapter import generate_feature_icon_svg, generate_hero_svg

    assets: dict[str, str] = {}
    try:
        assets["assets/hero.svg"] = generate_hero_svg(intent)
    except Exception as exc:
        logger.warning("Hero SVG generation failed: %s", exc)

    features = (intent.get("core_features") or [])[:3]
    for i, feature in enumerate(features):
        try:
            assets[f"assets/icon-{i + 1}.svg"] = generate_feature_icon_svg(feature)
        except Exception as exc:
            logger.warning("Feature icon SVG failed (feature=%r): %s", feature, exc)

    return assets


def _run_quality_check(slug: str, apply_result: Any) -> dict[str, Any]:
    """Basic structural quality check on applied HTML files."""
    from services.file_persistence import read_current_file

    issues: list[str] = []
    html_files = [p for p in apply_result.applied if p.endswith(".html")]

    for path in html_files:
        try:
            content = read_current_file(slug, path) or ""
            if "<!DOCTYPE" not in content[:200]:
                issues.append(f"{path}: missing DOCTYPE")
            if "<title>" not in content.lower()[:2000]:
                issues.append(f"{path}: missing <title>")
        except Exception:
            pass

    checked = len(apply_result.applied)
    issue_note = f", {len(issues)} issue{'s' if len(issues) != 1 else ''}" if issues else ""
    return {
        "files_checked": checked,
        "issues": issues,
        "summary": f"✓ {checked} file{'s' if checked != 1 else ''}{issue_note}",
    }
