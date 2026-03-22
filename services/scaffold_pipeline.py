"""
Scaffold pipeline — 3-stage pipeline for the React app builder.

Stages:
  1. thinking  — parse intent, derive app name (fast, deterministic)
  2. building  — generate React scaffold (1 LLM call via scaffold_generator)
  3. complete  — save files to disk (file_persistence, bypasses HTML sanitizer)

Replaces generation_pipeline.run_pipeline() for new / edit builds.
Returns the same ctx structure (gen, apply, blueprint, intent) that
api/server.py:_run_pipeline_bg already expects — no server.py changes to the
result-processing path.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

STAGE_DEFS: list[tuple[str, str]] = [
    ("thinking", "Planning your app"),
    ("building", "Building your app"),
    ("complete", "Complete"),
]

Emit = Callable[[dict[str, Any]], None]


# ---------------------------------------------------------------------------
# Clarification detection (kept lean — same logic as generation_pipeline)
# ---------------------------------------------------------------------------

def check_clarification_needed(
    message: str,
    history: list,
    style_seed: Any,
) -> dict | None:
    """Return a clarification dict if the prompt is too vague, else None."""
    import re
    msg = message.strip()
    is_first = not history
    too_short = len(msg) < 15
    no_action = not re.search(
        r'\b(build|make|create|design|add|launch|start|i want|help me|generate|write)\b',
        msg, re.IGNORECASE,
    )
    no_noun = not re.search(r'\b\w{4,}\b', msg)
    if is_first and not style_seed and (too_short or (no_action and no_noun)):
        return {
            "needs_clarification": True,
            "questions": [
                "What is the name and one-sentence description of your app?",
                "Who is the primary user, and what should the app do?",
            ],
            "reason": "too_vague",
        }
    return None


# ---------------------------------------------------------------------------
# Pipeline helpers
# ---------------------------------------------------------------------------

def _emit(emit: Emit, key: str, label: str, status: str, **kw: Any) -> None:
    emit({"type": "stage_update", "stage_key": key, "stage_label": label, "status": status, **kw})


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_scaffold_pipeline(
    session_id: str,
    slug: str,
    message: str,
    history: list[dict[str, Any]],
    existing_files: dict[str, str] | None,
    style_seed: dict[str, Any] | None,
    design_system: dict[str, Any] | None,
    operation: dict[str, Any] | None,
    emit: Emit,
    brand_spec: Any | None = None,
) -> dict[str, Any]:
    """Execute the 3-stage scaffold pipeline.

    Returns ctx dict with keys gen, apply, blueprint, intent —
    compatible with api/server.py:_run_pipeline_bg.
    """
    from services.code_generation_service import GenerationResult
    from services.workspace_editor import ApplyResult, ChangeResult
    from services.file_persistence import save_website_files

    ctx: dict[str, Any] = {}

    # ── Stage 1: thinking ────────────────────────────────────────────────
    _emit(emit, "thinking", "Planning your app", "running")
    t0 = time.monotonic()
    try:
        from core.intent_parser import parse_intent
        intent = parse_intent(message)
        ctx["intent"] = intent
        app_name = intent.get("product_name") or slug.replace("-", " ").title()
    except Exception as exc:
        logger.debug("intent_parser failed (non-fatal): %s", exc)
        ctx["intent"] = {"product_name": slug.replace("-", " ").title()}
        app_name = slug.replace("-", " ").title()
    _emit(emit, "thinking", "Planning your app", "done",
          duration_ms=_ms(t0), artifact_type="intent", artifact_name=app_name)

    # ── Stage 2: building ────────────────────────────────────────────────
    _emit(emit, "building", "Building your app", "running")
    t1 = time.monotonic()
    try:
        from services.scaffold_generator import generate_scaffold
        changes, meta = generate_scaffold(
            slug=slug,
            message=message,
            existing_files=existing_files or None,
        )
        file_count = len(changes)
        _emit(emit, "building", "Building your app", "done",
              duration_ms=_ms(t1), artifact_type="code",
              artifact_name=f"{file_count} file{'s' if file_count != 1 else ''}")
    except Exception as exc:
        _emit(emit, "building", "Building your app", "error", error=str(exc))
        raise

    # Build GenerationResult (compatible with server.py expectations)
    gen = GenerationResult(
        assistant_message=meta.get("assistant_message", f"Built **{app_name}**."),
        changes=changes,
        preview_route=f"/websites/{slug}/index",
        provider=meta.get("provider", "scaffold"),
        model_mode=meta.get("model_mode", "scaffold"),
        fallback_used=meta.get("fallback_used", False),
        warnings=[],
        blueprint={},
    )
    ctx["gen"] = gen
    ctx["blueprint"] = {}

    # ── Stage 3: complete (save files to disk) ────────────────────────────
    # Use file_persistence directly — bypasses output_validator so CDN
    # scripts and .jsx files are preserved without sanitization.
    prefix = f"data/websites/{slug}/"
    files_to_save: dict[str, str] = {}
    for change in changes:
        rel = change.path
        if rel.startswith(prefix):
            rel = rel[len(prefix):]
        if isinstance(change.content, str) and change.content.strip():
            files_to_save[rel] = change.content

    t2 = time.monotonic()
    save_result = save_website_files(slug, files_to_save)
    saved_paths: dict[str, str] = save_result.get("paths", {})
    version_id: str = save_result.get("version_id", "")
    applied = list(saved_paths.keys())

    _emit(emit, "complete", "Complete", "done",
          duration_ms=_ms(t2), artifact_type="files",
          artifact_name=f"{len(applied)} file{'s' if len(applied) != 1 else ''} saved")

    # Construct ApplyResult so server.py result-processing works unchanged
    results = [
        ChangeResult(
            path=f"{prefix}{rel}",
            action="create",
            status="applied",
            summary=f"Generated {rel}",
            version_id=version_id,
        )
        for rel in applied
    ]
    apply_result = ApplyResult(
        slug=slug,
        version_id=version_id,
        applied=applied,
        skipped=[],
        results=results,
        warnings=[],
    )
    ctx["apply"] = apply_result

    return ctx
