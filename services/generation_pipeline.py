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
import re
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stage definitions (order matters)
# ---------------------------------------------------------------------------

STAGE_DEFS: list[tuple[str, str]] = [
    ("parse_intent",             "Understanding your idea"),
    ("business_concept",         "Defining business concept"),
    ("feature_architecture",     "Planning feature architecture"),
    ("design_direction",         "Selecting visual direction"),
    ("information_architecture", "Mapping pages and user flow"),
    ("implementation_plan",      "Preparing implementation plan"),
    ("generate_index",           "Generating index page"),
    ("generate_pages",           "Generating additional pages"),
    ("generate_assets",          "Generating icons/visual assets"),
    ("wire_navigation",          "Wiring buttons and navigation"),
    ("quality_check",            "Validating quality and responsiveness"),
    ("complete",                 "Complete"),
]

# Backward-compat aliases: old stage keys → nearest new stage key
_STAGE_KEY_ALIASES: dict[str, str] = {
    "validate_idea":    "business_concept",
    "content_plan":     "business_concept",
    "brand_style_brief":"design_direction",
    "image_assets":     "generate_assets",
    "generate_code":    "generate_index",
    "apply_files":      "generate_pages",
    "link_wiring":      "wire_navigation",
}

Emit = Callable[[dict[str, Any]], None]


# ---------------------------------------------------------------------------
# Clarification detection (deterministic — no LLM)
# ---------------------------------------------------------------------------

def check_clarification_needed(
    message: str,
    history: list[dict],
    style_seed: dict | None,
) -> dict | None:
    """Return a clarification dict if intent is too vague, else None.

    Triggers when ALL of:
      - message is short (< 20 chars) OR has no meaningful noun/verb signal
      - no existing session history (first turn)
      - no style_seed provided
    """
    msg = message.strip()
    is_first_turn = not history

    has_noun = bool(re.search(r'\b[A-Z][a-z]+\b|\b\w{5,}\b', msg))
    too_short = len(msg) < 20
    no_action = not re.search(
        r'\b(build|make|create|design|add|launch|start|i want|help me)\b',
        msg, re.IGNORECASE,
    )

    if is_first_turn and not style_seed and (too_short or (not has_noun and no_action)):
        return {
            "needs_clarification": True,
            "questions": [
                "What is the name and one-sentence description of your product?",
                "Who is the primary user, and what problem does it solve?",
                "What style are you going for? (e.g. dark SaaS, minimal, vibrant, B2B)",
            ],
            "reason": "too_vague",
        }
    return None


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

    Raises on fatal errors (generate_index / apply_files failure); all other
    stage errors are captured and emitted without aborting the pipeline.
    """
    ctx: dict[str, Any] = {}

    # ── Stage 1: parse_intent ───────────────────────────────────────────────
    _emit_stage(emit, "parse_intent", "Understanding your idea", "running")
    try:
        from core.intent_parser import parse_intent
        intent, ms = _timed(lambda: parse_intent(message))
        _emit_stage(emit, "parse_intent", "Understanding your idea", "done",
                    duration_ms=ms,
                    artifact_type="intent",
                    artifact_name=intent.get("product_name", ""))
        ctx["intent"] = intent
    except Exception as exc:
        _emit_stage(emit, "parse_intent", "Understanding your idea", "error", error=str(exc))
        ctx["intent"] = {"product_name": slug.replace("-", " ").title()}

    # ── Stage 2: business_concept (combines validate_idea + content_plan) ───
    _emit_stage(emit, "business_concept", "Defining business concept", "running")
    try:
        bc, ms = _timed(lambda: _derive_business_concept(ctx["intent"], existing_files))
        product_type = bc.get("product_type", "saas")
        target_user = bc.get("target_user", "")
        bc_name = f"{product_type} for {target_user}" if target_user else product_type
        _emit_stage(emit, "business_concept", "Defining business concept", "done",
                    duration_ms=ms,
                    artifact_type="business_concept",
                    artifact_name=bc_name)
        ctx["business_concept"] = bc
        # backward-compat aliases
        ctx["validation"] = {"verdict": bc.get("verdict", "ok")}
        ctx["content_plan"] = {"mode": bc.get("mode", "new"), "pages": bc.get("pages", ["index.html"])}
    except Exception as exc:
        _emit_stage(emit, "business_concept", "Defining business concept", "error", error=str(exc))
        ctx["business_concept"] = {"mode": "new", "verdict": "ok", "product_type": "saas", "pages": ["index.html"], "feature_count": 0, "target_user": ""}
        ctx["validation"] = {"verdict": "ok"}
        ctx["content_plan"] = {"pages": ["index.html"]}

    # ── Stage 3: feature_architecture ───────────────────────────────────────
    _emit_stage(emit, "feature_architecture", "Planning feature architecture", "running")
    try:
        fa, ms = _timed(lambda: _derive_feature_architecture(ctx["intent"], ctx["business_concept"]))
        _emit_stage(emit, "feature_architecture", "Planning feature architecture", "done",
                    duration_ms=ms,
                    artifact_type="feature_architecture",
                    artifact_name=f"{fa.get('feature_count', 0)} features")
        ctx["feature_architecture"] = fa
    except Exception as exc:
        _emit_stage(emit, "feature_architecture", "Planning feature architecture", "error", error=str(exc))
        ctx["feature_architecture"] = {"features": [], "feature_count": 0, "product_type": "saas",
                                        "has_auth": False, "has_payments": False, "has_dashboard": False}

    # ── Stage 4: design_direction (replaces brand_style_brief) ──────────────
    _emit_stage(emit, "design_direction", "Selecting visual direction", "running")
    try:
        brief, ms = _timed(lambda: _derive_brand_style_brief(
            ctx["intent"], history, style_seed, design_system
        ))
        palette_name = brief.get("palette_hint") or (design_system or {}).get("palette_name", "framer_aura")
        display_font = (design_system or {}).get("display_font", "Space Grotesk")
        dd_name = f"{palette_name} / {display_font}"
        _emit_stage(emit, "design_direction", "Selecting visual direction", "done",
                    duration_ms=ms,
                    artifact_type="design_direction",
                    artifact_name=dd_name)
        ctx["design_direction"] = brief
        ctx["brand_style_brief"] = brief  # backward-compat alias
    except Exception as exc:
        _emit_stage(emit, "design_direction", "Selecting visual direction", "error", error=str(exc))
        ctx["design_direction"] = {"layout_family": "saas", "tone": "professional", "brand_family": "saas"}
        ctx["brand_style_brief"] = ctx["design_direction"]

    # ── Stage 5: information_architecture ───────────────────────────────────
    _emit_stage(emit, "information_architecture", "Mapping pages and user flow", "running")
    try:
        ia, ms = _timed(lambda: _derive_information_architecture(
            ctx["intent"], ctx["content_plan"], ctx["design_direction"]
        ))
        page_count = len(ia.get("pages", []))
        section_count = sum(len(v) for v in ia.get("sections", {}).values())
        _emit_stage(emit, "information_architecture", "Mapping pages and user flow", "done",
                    duration_ms=ms,
                    artifact_type="ia",
                    artifact_name=f"{page_count} pages, {section_count} sections")
        ctx["information_architecture"] = ia
    except Exception as exc:
        _emit_stage(emit, "information_architecture", "Mapping pages and user flow", "error", error=str(exc))
        ctx["information_architecture"] = {"pages": ["index.html"], "sections": {}, "nav_items": [], "primary_cta": "Get Started", "layout_family": "saas"}

    # ── Stage 6: implementation_plan + blueprint building ───────────────────
    _emit_stage(emit, "implementation_plan", "Preparing implementation plan", "running")
    try:
        impl_plan, ms = _timed(lambda: _derive_implementation_plan(
            ctx["information_architecture"], ctx["design_direction"], operation
        ))
        # Build blueprint from all planning artifacts
        blueprint = _build_blueprint(
            intent=ctx["intent"],
            feature_arch=ctx["feature_architecture"],
            design_dir=ctx["design_direction"],
            ia=ctx["information_architecture"],
            impl_plan=impl_plan,
            design_system=design_system,
        )
        ctx["blueprint"] = blueprint
        task_count = len(impl_plan.get("tasks", []))
        _emit_stage(emit, "implementation_plan", "Preparing implementation plan", "done",
                    duration_ms=ms,
                    artifact_type="plan",
                    artifact_name=f"blueprint ready, {task_count} tasks")
        ctx["implementation_plan"] = impl_plan
    except Exception as exc:
        _emit_stage(emit, "implementation_plan", "Preparing implementation plan", "error", error=str(exc))
        ctx["implementation_plan"] = {"tasks": [], "layout_family": "saas", "primary_cta": "Get Started"}
        ctx["blueprint"] = {}

    # ── Stage 7: generate_assets (before LLM call) ──────────────────────────
    _emit_stage(emit, "generate_assets", "Generating icons/visual assets", "running")
    try:
        assets, ms = _timed(lambda: _generate_image_assets(ctx["intent"], slug))
        _emit_stage(emit, "generate_assets", "Generating icons/visual assets", "done",
                    duration_ms=ms,
                    artifact_type="images",
                    artifact_name=f"{len(assets)} SVG asset{'s' if len(assets) != 1 else ''}")
        ctx["image_assets"] = assets
    except Exception as exc:
        _emit_stage(emit, "generate_assets", "Generating icons/visual assets", "error", error=str(exc))
        ctx["image_assets"] = {}

    # ── Stage 8: generate_index (LLM call — generates ALL pages) ────────────
    _emit_stage(emit, "generate_index", "Generating index page", "running")
    try:
        from services.code_generation_service import FileChange, generate

        # Merge layout_family from planning artifacts into style_seed
        effective_style_seed = dict(style_seed or {})
        brief = ctx.get("design_direction", {})
        if brief.get("layout_family"):
            effective_style_seed["layout_family"] = brief["layout_family"]

        import threading as _threading

        def _gen():
            return generate(
                slug=slug,
                user_message=message,
                history=history,
                existing_files=existing_files,
                mock_mode=mock_mode,
                style_seed=effective_style_seed,
                design_system=design_system,
                operation=operation,
            )

        # Emit periodic "still generating" progress events so the SSE stream
        # doesn't time out while the LLM (especially reasoning models) works.
        _gen_done = _threading.Event()
        def _progress_emitter():
            tick = 0
            while not _gen_done.wait(timeout=12):
                tick += 1
                secs = tick * 12
                _emit_stage(emit, "generate_index", "Generating index page", "running",
                            artifact_name=f"Building… {secs}s")
        _prog_thread = _threading.Thread(target=_progress_emitter, daemon=True)
        _prog_thread.start()
        try:
            gen_result, ms = _timed(_gen)
        finally:
            _gen_done.set()
            _prog_thread.join(timeout=1)

        # Append SVG asset files as extra changes
        for asset_path, svg_content in ctx["image_assets"].items():
            gen_result.changes.append(FileChange(
                path=f"data/websites/{slug}/{asset_path}",
                action="create",
                content=svg_content,
                summary="Generated SVG asset",
            ))

        # Post-generate image placement check
        _check_image_placement(gen_result, ctx.get("image_assets", {}), slug)

        # Route graph validation
        if gen_result.route_graph:
            from services.output_validator import validate_route_graph
            available = {c.path.split(f"/{slug}/")[-1] for c in gen_result.changes}
            rg_warnings = validate_route_graph(gen_result.route_graph, available)
            if rg_warnings:
                gen_result.warnings.extend(rg_warnings)

        # Merge pipeline blueprint into gen result if LLM didn't supply one
        if not gen_result.blueprint:
            gen_result.blueprint = ctx.get("blueprint", {})

        _emit_stage(emit, "generate_index", "Generating index page", "done",
                    duration_ms=ms,
                    artifact_type="code",
                    artifact_name="index.html")
        ctx["gen"] = gen_result
    except Exception as exc:
        _emit_stage(emit, "generate_index", "Generating index page", "error", error=str(exc))
        raise  # fatal — cannot continue without generated code

    # ── Stage 9: generate_pages (reflect additional pages count) ────────────
    additional_pages = [
        c for c in ctx["gen"].changes
        if c.path.endswith(".html") and "index.html" not in c.path
    ]
    _emit_stage(emit, "generate_pages", "Generating additional pages", "done",
                duration_ms=0,
                artifact_type="pages",
                artifact_name=f"{len(additional_pages)} pages")

    # ── Stage 10: apply_files (silent — no stage emit) ──────────────────────
    try:
        from services.workspace_editor import apply_changes

        apply_result, ms = _timed(lambda: apply_changes(slug=slug, changes=ctx["gen"].changes))
        ctx["apply"] = apply_result
    except Exception as exc:
        raise  # fatal

    # ── Stage 11: wire_navigation ────────────────────────────────────────────
    _emit_stage(emit, "wire_navigation", "Wiring buttons and navigation", "running")
    try:
        from services.link_wiring import run_link_wiring_pass

        def _wire():
            return run_link_wiring_pass(slug, ctx["gen"].changes, operation)

        (wired_changes, lw_warnings), ms = _timed(_wire)
        ctx["gen"].changes = wired_changes
        ctx["gen"].warnings.extend(lw_warnings)
        fix_count = len(lw_warnings)
        _emit_stage(emit, "wire_navigation", "Wiring buttons and navigation", "done",
                    duration_ms=ms,
                    artifact_type="links",
                    artifact_name=f"{fix_count} link{'s' if fix_count != 1 else ''} wired")
        ctx["wire_navigation"] = {"fixes": lw_warnings}
        # backward-compat alias
        ctx["link_wiring"] = ctx["wire_navigation"]
    except Exception as exc:
        _emit_stage(emit, "wire_navigation", "Wiring buttons and navigation", "error", error=str(exc))
        ctx["wire_navigation"] = {"fixes": []}
        ctx["link_wiring"] = ctx["wire_navigation"]

    # ── Stage 12: quality_check ──────────────────────────────────────────────
    _emit_stage(emit, "quality_check", "Validating quality and responsiveness", "running")
    try:
        quality, ms = _timed(lambda: _run_quality_check(slug, ctx["apply"]))
        _emit_stage(emit, "quality_check", "Validating quality and responsiveness", "done",
                    duration_ms=ms,
                    artifact_type="quality",
                    artifact_name=quality["summary"])
        ctx["quality"] = quality
    except Exception as exc:
        _emit_stage(emit, "quality_check", "Validating quality and responsiveness", "error", error=str(exc))
        ctx["quality"] = {"summary": "check skipped"}

    # ── Stage 13: complete ───────────────────────────────────────────────────
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


def _derive_business_concept(
    intent: dict[str, Any],
    existing_files: dict[str, str] | None,
) -> dict[str, Any]:
    """Combine validation and content planning into business concept."""
    msg_based_verdict = "ok"
    product_name = intent.get("product_name", "")
    features = intent.get("core_features") or []
    product_type = (intent.get("product_type") or "saas").lower()

    if existing_files:
        mode = "edit"
        pages = list(existing_files.keys())
    else:
        mode = "new"
        pages = ["index.html"]
        if product_type in ("saas", "app", "tool", "platform") or len(features) > 2:
            pages.append("app.html")

    return {
        "mode": mode,
        "verdict": msg_based_verdict,
        "product_name": product_name,
        "product_type": product_type,
        "pages": pages,
        "feature_count": len(features),
        "target_user": intent.get("target_user", ""),
    }


def _derive_feature_architecture(
    intent: dict[str, Any],
    business_concept: dict[str, Any],
) -> dict[str, Any]:
    """Extract and structure feature set."""
    features = intent.get("core_features") or []
    product_type = business_concept.get("product_type", "saas")
    return {
        "features": features,
        "feature_count": len(features),
        "product_type": product_type,
        "has_auth": any(
            f.lower() in ("auth", "login", "signup", "authentication") for f in features
        ),
        "has_payments": any(
            f.lower() in ("payments", "billing", "stripe", "subscription") for f in features
        ),
        "has_dashboard": any(
            "dashboard" in f.lower() or "analytics" in f.lower() for f in features
        ),
    }


def _build_blueprint(
    intent: dict[str, Any],
    feature_arch: dict[str, Any],
    design_dir: dict[str, Any],
    ia: dict[str, Any],
    impl_plan: dict[str, Any],
    design_system: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build structured blueprint from planning artifacts."""
    features = feature_arch.get("features") or intent.get("core_features") or []
    pages_raw = ia.get("sections", {})

    def _page_purpose(path: str) -> str:
        if "index" in path:
            return "landing"
        if "signup" in path or "register" in path:
            return "conversion"
        if "app" in path or "dashboard" in path:
            return "product_entry"
        if "pricing" in path:
            return "pricing"
        if "about" in path:
            return "about"
        if "login" in path or "signin" in path:
            return "auth"
        return "secondary"

    page_map = [
        {"path": page, "purpose": _page_purpose(page)}
        for page in pages_raw.keys()
    ]
    cta_flow = impl_plan.get("layout_plan", {}).get("cta_flow", [])
    ds = design_system or {}
    return {
        "business_name": intent.get("product_name", ""),
        "business_positioning": (
            intent.get("tagline")
            or f"The smart {intent.get('product_type', 'SaaS').lower()} platform for {intent.get('target_user', 'teams')}"
        ),
        "target_user": intent.get("target_user", ""),
        "feature_list": features[:6],
        "design_direction": {
            "design_family": design_dir.get("design_family", "framer_aura"),
            "palette_name": ds.get("palette_name", design_dir.get("palette_hint", "")),
            "font_pair": {
                "display": ds.get("display_font", "Space Grotesk"),
                "body": ds.get("body_font", "Inter"),
            },
            "motion_preset": design_dir.get("motion_preset", "default"),
            "spacing_policy": design_dir.get("spacing_policy", "aura"),
            "consistency_profile_id": design_dir.get("consistency_profile_id", ""),
        },
        "page_map": page_map,
        "cta_flow": cta_flow,
        "build_steps": impl_plan.get("tasks", []),
        "quality_gates": ["responsive_contract", "link_integrity", "design_consistency"],
    }


def _generate_image_assets(
    intent: dict[str, Any],
    slug: str,
) -> dict[str, str]:
    """Generate SVG placeholder assets for the product."""
    from services.image_adapter import generate_feature_icon_svg, generate_hero_svg
    import re as _re

    assets: dict[str, str] = {}
    try:
        assets["assets/hero.svg"] = generate_hero_svg(intent)
    except Exception as exc:
        logger.warning("Hero SVG generation failed: %s", exc)

    features = (intent.get("core_features") or [])[:3]
    for i, feature in enumerate(features):
        try:
            # Generate BOTH numbered AND slug-based names so LLM can reference either
            feature_slug = _re.sub(r'[^a-z0-9]+', '-', feature.lower()).strip('-')
            svg_content = generate_feature_icon_svg(feature)
            assets[f"assets/icon-{i + 1}.svg"] = svg_content          # icon-1.svg
            assets[f"assets/icon-{feature_slug}.svg"] = svg_content    # icon-gps-tracking.svg
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


# ---------------------------------------------------------------------------
# Planning artifact stage implementations
# ---------------------------------------------------------------------------

_PRODUCT_TYPE_LAYOUT_MAP: dict[str, str] = {
    "health": "wellness",
    "fitness": "wellness",
    "finance": "enterprise",
    "b2b": "enterprise",
    "devtools": "developer",
    "ecommerce": "marketplace",
    "edtech": "education",
    "social": "consumer",
    "saas": "saas",
}

_LAYOUT_FAMILY_SECTION_MAP: dict[str, list[str]] = {
    "saas":       ["hero", "features", "social_proof", "pricing", "cta", "footer"],
    "enterprise": ["hero", "trust_logos", "features", "case_study", "pricing", "cta", "footer"],
    "wellness":   ["hero", "benefits", "how_it_works", "testimonials", "cta", "footer"],
    "developer":  ["hero", "quickstart", "features", "integrations", "cta", "footer"],
    "marketplace":["hero", "categories", "featured_items", "social_proof", "cta", "footer"],
    "education":  ["hero", "courses", "features", "testimonials", "pricing", "cta", "footer"],
    "consumer":   ["hero", "gallery", "features", "testimonials", "cta", "footer"],
}


def _derive_brand_style_brief(
    intent: dict[str, Any],
    history: list[dict[str, Any]],
    style_seed: dict[str, Any] | None,
    design_system: dict[str, Any] | None,
) -> dict[str, Any]:
    """Deterministic brand style brief — no LLM calls."""
    product_type = (intent.get("product_type") or "saas").lower()
    layout_family = _PRODUCT_TYPE_LAYOUT_MAP.get(product_type, "saas")

    # Diversity: avoid repeating last used family from history
    used_families = [
        m.get("brand_family")
        for m in history
        if isinstance(m, dict) and "brand_family" in m
    ]
    if used_families and layout_family == used_families[-1]:
        alternatives = [f for f in _PRODUCT_TYPE_LAYOUT_MAP.values() if f != layout_family]
        if alternatives:
            import hashlib as _h
            idx = int(_h.md5((intent.get("product_name") or "x").encode()).hexdigest()[:2], 16)
            layout_family = alternatives[idx % len(alternatives)]

    palette_hint = (style_seed or {}).get("palette") or (design_system or {}).get("palette_name") or ""
    tone = "professional" if layout_family in ("enterprise", "developer") else "friendly"
    return {
        "layout_family": layout_family,
        "palette_hint": palette_hint,
        "tone": tone,
        "brand_family": layout_family,
        "design_family": "framer_aura",
        "consistency_profile_id": (design_system or {}).get("consistency_profile_id", ""),
        "spacing_policy": (design_system or {}).get("spacing_policy", "aura"),
        "motion_preset": (design_system or {}).get("motion_preset", "default"),
    }


def _derive_information_architecture(
    intent: dict[str, Any],
    content_plan: dict[str, Any],
    brand_brief: dict[str, Any],
) -> dict[str, Any]:
    """Map pages → sections deterministically from brand brief."""
    pages = content_plan.get("pages", ["index.html"])
    layout_family = brand_brief.get("layout_family", "saas")
    sections: dict[str, list[str]] = {}

    for page in pages:
        if "index" in page:
            sections[page] = _LAYOUT_FAMILY_SECTION_MAP.get(
                layout_family, _LAYOUT_FAMILY_SECTION_MAP["saas"]
            )
        elif "app" in page:
            sections[page] = ["sidebar", "dashboard", "metrics_row", "data_table"]
        else:
            sections[page] = ["content", "cta", "footer"]

    features = intent.get("core_features") or []
    nav_items = [f.replace(" ", "_").lower() for f in features[:4]] + ["pricing", "about"]

    return {
        "pages": pages,
        "sections": sections,
        "nav_items": nav_items,
        "primary_cta": intent.get("cta") or "Get Started",
        "layout_family": layout_family,
    }


def _derive_implementation_plan(
    ia: dict[str, Any],
    brand_brief: dict[str, Any],
    operation: dict[str, Any] | None,
) -> dict[str, Any]:
    """Produce a concrete task list for the code generation step."""
    tasks: list[str] = []
    for page in ia.get("pages", ["index.html"]):
        section_list = ia.get("sections", {}).get(page, [])
        tasks.append(f"Create {page} with sections: {', '.join(section_list)}")

    if (operation or {}).get("type") == "add_endpoint":
        tasks.append("Scaffold data.json with endpoint definitions")

    if (operation or {}).get("type") == "add_page":
        target = (operation or {}).get("target", "new_page")
        tasks.append(f"Create pages/{target}.html")

    layout_family = brand_brief.get("layout_family", "saas")
    page_sections = ia.get("sections", {})
    # Derive primary page section order (index.html first, else first page)
    primary_page_sections: list[str] = []
    for pg in ("index.html", *ia.get("pages", [])):
        if pg in page_sections:
            primary_page_sections = page_sections[pg]
            break

    # Build CTA flow from index → app if both pages exist
    cta_flow: list[dict[str, str]] = []
    pages = ia.get("pages", [])
    if "index.html" in pages and "app.html" in pages:
        cta_flow.append({
            "from": "index.html#cta",
            "to": "app.html",
            "label": ia.get("primary_cta", "Get Started"),
        })

    # Derive interaction plan from operation and brand brief
    motion_preset = (brand_brief or {}).get("motion_preset", "default")
    interaction_plan = {
        "reveal_scroll": True,
        "hover_lift": True,
        "sticky_nav": True,
        "animated_counters": bool(ia.get("sections", {}).get("index.html")),
        "testimonial_carousel": "testimonials" in primary_page_sections
            or "testimonial" in primary_page_sections,
        "parallax_hero": False,  # disabled by default (can cause CLS)
        "motion_preset": motion_preset,
        "prefers_reduced_motion": "opacity-only fallback, no transform travel",
    }

    consistency_profile_id = (brand_brief or {}).get("consistency_profile_id", "")

    layout_plan = {
        "layout_family": layout_family,
        "page_map": page_sections,
        "section_order": primary_page_sections,
        "cta_flow": cta_flow,
        "dynamic_components": ["testimonial_carousel", "reveal_scroll", "animated_counters"],
        "interaction_plan": interaction_plan,
        "consistency_profile_id": consistency_profile_id,
        "spacing_policy": (brand_brief or {}).get("spacing_policy", "aura"),
    }

    return {
        "tasks": tasks,
        "layout_family": layout_family,
        "section_order": page_sections,
        "primary_cta": ia.get("primary_cta", "Get Started"),
        "layout_plan": layout_plan,
    }


def _check_image_placement(
    gen_result: Any,
    image_assets: dict[str, str],
    slug: str,
) -> None:
    """Warn if generated HTML doesn't reference expected SVG assets."""
    if not image_assets:
        return
    html_changes = [c for c in gen_result.changes if c.path.endswith(".html")]
    if not html_changes:
        return
    all_html = "\n".join(c.content for c in html_changes)
    for asset_rel_path in image_assets:
        if asset_rel_path not in all_html:
            msg = (
                f"Image placement check: {asset_rel_path!r} generated "
                f"but not referenced in any HTML. Ensure GENERATED ASSET PLACEMENT CONTRACT is followed."
            )
            logger.warning(msg)
            gen_result.warnings.append(msg)
