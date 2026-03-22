"""
Orchestrated website generation pipeline (simplified).

Stages:
  1. plan        — BrandSpec synthesis (LLM call 1)
  2. generate    — Per-file code generation (LLM calls 2+), plus image assets
  3. apply       — Write files to disk, wire navigation, quality check

Each stage emits structured events via an `emit` callback so the frontend
can render a live build log.

Public API:
    result = run_pipeline(
        session_id, slug, message, history, existing_files,
        style_seed, design_system, operation, emit,
    )
"""
from __future__ import annotations

import logging
import re
import time
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stage definitions
# ---------------------------------------------------------------------------

STAGE_DEFS: list[tuple[str, str]] = [
    ("parse_intent",             "Understanding your idea"),
    ("business_concept",         "Defining business concept"),
    ("feature_architecture",     "Architecting features"),
    ("design_direction",         "Crafting design direction"),
    ("information_architecture", "Planning information architecture"),
    ("implementation_plan",      "Building implementation plan"),
    ("generate_index",           "Generating landing page"),
    ("generate_pages",           "Generating additional pages"),
    ("generate_assets",          "Generating images and icons"),
    ("wire_navigation",          "Wiring navigation links"),
    ("quality_check",            "Validating quality"),
    ("complete",                 "Complete"),
]

# Backward-compat aliases so old frontend stage keys still resolve
_STAGE_KEY_ALIASES: dict[str, str] = {
    "validate_idea":             "business_concept",
    "content_plan":              "business_concept",
    "brand_style_brief":         "design_direction",
    "brand_design":              "design_direction",
    "file_structure":            "implementation_plan",
    "generate_files":            "generate_index",
    "generate_code":             "generate_index",
    "apply_files":               "complete",
    "plan":                      "business_concept",
    "link_wiring":               "wire_navigation",
}

Emit = Callable[[dict[str, Any]], None]


# ---------------------------------------------------------------------------
# Planning helper functions
# ---------------------------------------------------------------------------

# Product type → layout family mapping
_PRODUCT_TYPE_TO_LAYOUT_FAMILY: dict[str, str] = {
    "health":       "wellness",
    "fitness":      "wellness",
    "wellness":     "wellness",
    "healthcare":   "wellness",
    "saas":         "saas",
    "saas_b2b":     "enterprise",
    "saas_b2c":     "saas",
    "enterprise":   "enterprise",
    "finance":      "enterprise",
    "devtools":     "developer",
    "developer":    "developer",
    "education":    "education",
    "edtech":       "education",
    "marketplace":  "marketplace",
    "ecommerce":    "marketplace",
    "consumer":     "consumer",
    "consumer_app": "consumer",
    "beauty":       "consumer",
    "food":         "consumer",
    "travel":       "consumer",
    "social":       "consumer",
}

# All layout families in priority rotation order
_ALL_LAYOUT_FAMILIES = [
    "saas", "enterprise", "wellness", "developer",
    "marketplace", "education", "consumer",
]

# Domain-specific CTAs
_DOMAIN_CTAS: dict[str, str] = {
    "fitness":   "Start Your Journey",
    "health":    "Start Your Journey",
    "wellness":  "Start Your Journey",
    "finance":   "Request Demo",
    "enterprise":"Request Demo",
    "saas_b2b":  "Request Demo",
    "education": "Enroll Now",
    "edtech":    "Enroll Now",
    "marketplace": "Browse Now",
    "ecommerce": "Shop Now",
    "beauty":    "Shop Now",
    "consumer":  "Download Free",
    "devtools":  "View Docs",
    "developer": "View Docs",
}


def _derive_domain_cta(intent: dict[str, Any]) -> str:
    """Derive a domain-appropriate CTA from intent.

    Respects intent['cta'] override. Falls back to 'Get Started'.
    """
    if intent.get("cta"):
        return intent["cta"]
    product_type = (intent.get("product_type") or "").lower()
    return _DOMAIN_CTAS.get(product_type, "Get Started")


def _derive_brand_style_brief(
    intent: dict[str, Any],
    history: list[dict],
    style_seed: dict | None,
    design_system: dict | None,
) -> dict[str, Any]:
    """Derive brand style brief from intent.

    Returns dict with keys: layout_family, tone, design_family,
    consistency_profile_id, spacing_policy.

    Avoids repeating the same layout_family as recent history entries.
    """
    product_type = (intent.get("product_type") or "saas").lower()
    layout_family = _PRODUCT_TYPE_TO_LAYOUT_FAMILY.get(product_type, "saas")

    # Diversity: avoid repeating the same family as recent history
    recent_families = set()
    for h in (history or []):
        if isinstance(h, dict):
            bf = h.get("brand_family") or h.get("layout_family")
            if bf:
                recent_families.add(bf)

    if layout_family in recent_families:
        # Pick the next available family
        for candidate in _ALL_LAYOUT_FAMILIES:
            if candidate not in recent_families:
                layout_family = candidate
                break

    # Tone derived from product type
    tone_map = {
        "wellness": "warm",
        "developer": "technical",
        "enterprise": "authoritative",
        "education": "warm",
        "marketplace": "playful",
        "consumer": "playful",
    }
    tone = tone_map.get(layout_family, "professional")

    # Pull design system values when provided
    ds = design_system or {}
    design_family = ds.get("design_family", "framer_aura")
    consistency_profile_id = ds.get("consistency_profile_id", "")
    spacing_policy = ds.get("spacing_policy", "aura")

    return {
        "layout_family":          layout_family,
        "tone":                   tone,
        "design_family":          design_family,
        "consistency_profile_id": consistency_profile_id,
        "spacing_policy":         spacing_policy,
    }


def _derive_business_concept(
    intent: dict[str, Any],
    existing_files: dict[str, str] | None,
) -> dict[str, Any]:
    """Derive business concept from intent and existing files.

    Returns dict with keys: mode ('new' | 'edit'), pages (list of page paths).
    """
    is_edit = bool(existing_files)
    mode = "edit" if is_edit else "new"

    if is_edit:
        pages = list(existing_files.keys()) if existing_files else []
    else:
        pages = ["index.html", "pages/signup.html", "app.html"]

    return {
        "mode":  mode,
        "pages": pages,
    }


def _derive_feature_architecture(
    intent: dict[str, Any],
    business_concept: dict[str, Any],
) -> dict[str, Any]:
    """Derive feature architecture from intent.

    Returns dict with keys: feature_count, features, has_auth, has_payments.
    """
    features = list(intent.get("core_features") or [])
    combined = " ".join(features).lower()

    has_auth = bool(re.search(r'\b(auth|login|authentication|signin|sign.in)\b', combined))
    has_payments = bool(re.search(r'\b(billing|payment|stripe|checkout|subscribe)\b', combined))

    return {
        "feature_count": len(features),
        "features":      features,
        "has_auth":      has_auth,
        "has_payments":  has_payments,
    }


def _derive_information_architecture(
    intent: dict[str, Any],
    content_plan: dict[str, Any],
    brand_brief: dict[str, Any],
) -> dict[str, Any]:
    """Derive information architecture from intent and brand brief.

    Returns dict with keys: sections (dict keyed by page), pages, nav_items, primary_cta.
    """
    layout_family = brand_brief.get("layout_family", "saas")
    pages = content_plan.get("pages", ["index.html"])

    # Base sections by layout family
    _family_sections: dict[str, list[str]] = {
        "saas":       ["hero", "features", "testimonials", "pricing", "cta", "footer"],
        "enterprise": ["hero", "trust_logos", "features", "case_studies", "pricing", "cta", "footer"],
        "wellness":   ["hero", "benefits", "how_it_works", "testimonials", "pricing", "cta", "footer"],
        "developer":  ["hero", "code_demo", "features", "integrations", "pricing", "cta", "footer"],
        "marketplace":["hero", "categories", "featured_listings", "how_it_works", "testimonials", "cta", "footer"],
        "education":  ["hero", "course_overview", "curriculum", "instructor", "testimonials", "pricing", "cta", "footer"],
        "consumer":   ["hero", "features", "social_proof", "how_it_works", "testimonials", "cta", "footer"],
    }
    base_sections = _family_sections.get(layout_family, _family_sections["saas"])

    sections: dict[str, list[str]] = {}
    for page in pages:
        if page == "index.html":
            sections[page] = list(base_sections)
        elif "signup" in page:
            sections[page] = ["form"]
        elif page == "app.html":
            sections[page] = ["dashboard", "metrics", "features_panel"]
        elif "pricing" in page:
            sections[page] = ["pricing_tiers", "faq", "cta"]
        else:
            sections[page] = ["hero", "content", "cta", "footer"]

    primary_cta = _derive_domain_cta(intent)

    return {
        "sections":    sections,
        "pages":       pages,
        "nav_items":   [p.replace("pages/", "").replace(".html", "") for p in pages if p != "index.html"],
        "primary_cta": primary_cta,
        "layout_family": layout_family,
    }


def _derive_implementation_plan(
    ia: dict[str, Any],
    brief: dict[str, Any],
    design_system: dict | None,
) -> dict[str, Any]:
    """Derive implementation plan from information architecture and brand brief.

    Returns dict with keys: tasks, primary_cta, layout_plan.
    layout_plan includes: layout_family, page_map, section_order, cta_flow,
    dynamic_components, interaction_plan, consistency_profile_id, spacing_policy.
    """
    layout_family = brief.get("layout_family", "saas")
    pages = ia.get("pages", ["index.html"])
    sections = ia.get("sections", {})
    primary_cta = ia.get("primary_cta", "Get Started")
    consistency_profile_id = brief.get("consistency_profile_id", "")
    spacing_policy = brief.get("spacing_policy", "aura")

    # Build tasks
    tasks: list[str] = []
    for page in pages:
        tasks.append(f"Generate {page}")

    # Build page_map with purpose labels
    _purpose_map = {
        "index.html":         "landing",
        "pages/signup.html":  "conversion",
        "app.html":           "product_entry",
        "pages/pricing.html": "pricing",
    }
    page_map = [
        {"path": p, "purpose": _purpose_map.get(p, "secondary")}
        for p in pages
    ]

    # Build section_order from all pages
    section_order = []
    for p in pages:
        for s in sections.get(p, []):
            if s not in section_order:
                section_order.append(s)

    # Build cta_flow — link index.html → app.html when both present
    cta_flow = []
    has_index = "index.html" in pages
    has_app = "app.html" in pages
    has_signup = any("signup" in p for p in pages)
    if has_index and (has_app or has_signup):
        dest = "app.html" if has_app else "pages/signup.html"
        cta_flow.append({
            "from":  "index.html#cta",
            "to":    dest,
            "label": primary_cta,
        })

    # Check if any page has testimonials section
    all_sections_flat = [s for secs in sections.values() for s in secs]
    has_testimonials = "testimonials" in all_sections_flat

    # Dynamic components
    dynamic_components = {
        "testimonial_carousel": has_testimonials,
    }

    # Interaction plan
    interaction_plan = {
        "reveal_scroll":        True,
        "hover_lift":           True,
        "sticky_nav":           True,
        "testimonial_carousel": has_testimonials,
        "parallax_hero":        False,
    }

    layout_plan = {
        "layout_family":          layout_family,
        "page_map":               page_map,
        "section_order":          section_order,
        "cta_flow":               cta_flow,
        "dynamic_components":     dynamic_components,
        "interaction_plan":       interaction_plan,
        "consistency_profile_id": consistency_profile_id,
        "spacing_policy":         spacing_policy,
    }

    return {
        "tasks":       tasks,
        "primary_cta": primary_cta,
        "layout_plan": layout_plan,
    }


def _check_image_placement(
    gen: Any,
    existing_files: dict[str, str],
    slug: str,
) -> None:
    """Check that SVG files in existing_files are referenced in HTML changes.

    Adds warnings to gen.warnings if any SVGs are not referenced.
    """
    svg_files = [path for path in (existing_files or {}) if path.endswith(".svg")]
    if not svg_files:
        return

    # Get all HTML content from changes
    html_contents = [
        c.content for c in gen.changes
        if c.path.endswith(".html") and isinstance(c.content, str)
    ]
    combined_html = " ".join(html_contents)

    for svg_path in svg_files:
        # Check by filename (the path part after any directory prefix)
        filename = svg_path.split("/")[-1]
        if filename not in combined_html and svg_path not in combined_html:
            gen.warnings.append(
                f"SVG asset '{svg_path}' was generated but not referenced in any HTML file"
            )


def _build_blueprint(
    intent: dict[str, Any],
    feature_arch: dict[str, Any],
    design_dir: dict[str, Any],
    ia: dict[str, Any],
    impl_plan: dict[str, Any],
    design_system: dict | None,
) -> dict[str, Any]:
    """Build a structured blueprint for the project.

    Returns dict with keys: business_name, business_positioning, target_user,
    feature_list, design_direction, page_map, cta_flow, build_steps, quality_gates.
    """
    ds = design_system or {}

    # Design direction
    design_direction = {
        "palette_name":          ds.get("palette_name", design_dir.get("palette_hint", "framer_aura")),
        "font_pair": {
            "display": ds.get("display_font", "Syne"),
            "body":    ds.get("body_font", "Manrope"),
        },
        "consistency_profile_id": ds.get(
            "consistency_profile_id",
            design_dir.get("consistency_profile_id", ""),
        ),
        "motion_preset":  design_dir.get("motion_preset", "default"),
        "spacing_policy": design_dir.get("spacing_policy", "aura"),
        "design_family":  design_dir.get("design_family", "framer_aura"),
    }

    # Page map with purpose labels
    _purpose_map = {
        "index.html":         "landing",
        "pages/signup.html":  "conversion",
        "app.html":           "product_entry",
        "pages/pricing.html": "pricing",
    }
    sections = ia.get("sections", {})
    pages_in_ia = list(sections.keys()) if sections else ["index.html"]
    page_map = [
        {"path": p, "purpose": _purpose_map.get(p, "secondary")}
        for p in pages_in_ia
    ]

    # CTA flow from impl_plan
    cta_flow = impl_plan.get("layout_plan", {}).get("cta_flow", [])

    # Build steps
    build_steps = [f"Generate {p}" for p in pages_in_ia]

    # Quality gates
    quality_gates = [
        "All pages have DOCTYPE and title",
        "All internal links use relative paths",
        "Brand name appears in all HTML pages",
        "All generated assets are referenced in HTML",
    ]

    return {
        "business_name":        intent.get("product_name", ""),
        "business_positioning": f"{intent.get('product_name', '')} for {intent.get('target_user', 'users')}",
        "target_user":          intent.get("target_user", ""),
        "feature_list":         feature_arch.get("features", []),
        "design_direction":     design_direction,
        "page_map":             page_map,
        "cta_flow":             cta_flow,
        "build_steps":          build_steps,
        "quality_gates":        quality_gates,
    }


# ---------------------------------------------------------------------------
# Clarification detection (deterministic — no LLM)
# ---------------------------------------------------------------------------

def check_clarification_needed(
    message: str,
    history: list[dict],
    style_seed: dict | None,
) -> dict | None:
    """Return a clarification dict if intent is too vague, else None."""
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
    style_seed: dict[str, Any] | None,
    design_system: dict[str, Any] | None,
    operation: dict[str, Any] | None,
    emit: Emit,
    brand_spec: Any | None = None,
) -> dict[str, Any]:
    """Execute the generation pipeline. Returns dict with gen and apply results.

    Edit mode  (existing_files truthy): brand_design/file_structure skipped, uses
                                         existing generate() for speed.
    New project (existing_files empty):  full 3-phase pipeline with per-file generation.
    """
    ctx: dict[str, Any] = {}
    is_edit = bool(existing_files)

    # ── Stage 1: parse_intent ────────────────────────────────────────────
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

    # Populate backward-compat context keys
    ctx["validation"] = {"verdict": "ok"}
    ctx["content_plan"] = {"mode": "edit" if is_edit else "new"}
    ctx["business_concept"] = {"mode": ctx["content_plan"]["mode"], "verdict": "ok"}
    ctx["feature_architecture"] = {"features": ctx["intent"].get("core_features", []), "feature_count": 0}
    ctx["design_direction"] = {
        "layout_family": "saas",
        "design_family": "framer_aura",
        "consistency_profile_id": (design_system or {}).get("consistency_profile_id", ""),
    }
    ctx["information_architecture"] = {"pages": ["index.html"], "sections": {}}
    ctx["implementation_plan"] = {"tasks": []}
    ctx["blueprint"] = {}

    # ── Stage 2: brand_design ────────────────────────────────────────────
    if is_edit:
        # Skip for edits — emit instantly
        _emit_stage(emit, "brand_design", "Crafting brand and design", "done",
                    duration_ms=0, artifact_type="brand_spec",
                    artifact_name=getattr(brand_spec, "brand_name", "(edit)"))
        ctx["brand_spec"] = brand_spec
    else:
        _emit_stage(emit, "brand_design", "Crafting brand and design", "running")
        try:
            if brand_spec:
                ctx["brand_spec"] = brand_spec
                _emit_stage(emit, "brand_design", "Crafting brand and design", "done",
                            duration_ms=0, artifact_type="brand_spec",
                            artifact_name=f"{brand_spec.brand_name} — {brand_spec.tone} tone, {brand_spec.visual_motif} style")
            else:
                from services.code_generation_service import synthesize_brand_spec
                bs, ms = _timed(lambda: synthesize_brand_spec(message, history, slug, design_system))
                ctx["brand_spec"] = bs
                _emit_stage(emit, "brand_design", "Crafting brand and design", "done",
                            duration_ms=ms, artifact_type="brand_spec",
                            artifact_name=f"{bs.brand_name} — {bs.tone} tone, {bs.visual_motif} style")
        except Exception as exc:
            _emit_stage(emit, "brand_design", "Crafting brand and design", "error", error=str(exc))
            from services.code_generation_service import _minimal_brand_spec
            ctx["brand_spec"] = _minimal_brand_spec(slug, message)

    # ── Stage 3: file_structure ──────────────────────────────────────────
    if is_edit:
        _emit_stage(emit, "file_structure", "Planning file structure", "done",
                    duration_ms=0, artifact_type="scaffold", artifact_name="(edit — skipped)")
        ctx["scaffold"] = None
    else:
        _emit_stage(emit, "file_structure", "Planning file structure", "running")
        try:
            from services.code_generation_service import generate_file_structure
            scaffold, ms = _timed(lambda: generate_file_structure(
                ctx["brand_spec"], message, design_system
            ))
            ctx["scaffold"] = scaffold
            file_count = len(scaffold.get("file_tree", []))
            _emit_stage(emit, "file_structure", "Planning file structure", "done",
                        duration_ms=ms, artifact_type="scaffold",
                        artifact_name=f"{file_count} files planned")
        except Exception as exc:
            _emit_stage(emit, "file_structure", "Planning file structure", "error", error=str(exc))
            ctx["scaffold"] = {
                "project_type": "static_site",
                "file_tree": [
                    {"path": "styles/globals.css", "purpose": "Shared design tokens", "depends_on": []},
                    {"path": "index.html", "purpose": "Landing page", "depends_on": ["styles/globals.css"]},
                    {"path": "pages/signup.html", "purpose": "Signup page", "depends_on": ["styles/globals.css"]},
                    {"path": "app.html", "purpose": "App dashboard", "depends_on": ["styles/globals.css"]},
                ],
                "generation_order": ["styles/globals.css", "index.html", "pages/signup.html", "app.html"],
                "design_notes": "",
            }

    # ── Canonical project state (read-only DTO for downstream layers) ────
    from services.build_project_state import load_build_project_state
    ctx["project_state"] = load_build_project_state(
        session_id=session_id,
        slug=slug,
        message=message,
        existing_files=existing_files,
        history=history,
        style_seed=style_seed,
        design_system=design_system,
        operation=operation,
        intent=ctx["intent"],
        brand_spec=ctx.get("brand_spec"),
        scaffold=ctx.get("scaffold"),
        is_edit=is_edit,
    )

    # ── Build plan (structured intent; generate() unchanged this phase) ──
    from services.build_plan import build_plan_fallback, build_plan_from_project_state
    try:
        _bp = build_plan_from_project_state(ctx["project_state"])
        ctx["build_plan"] = _bp.to_dict()
    except Exception as bp_exc:
        logger.warning("BuildPlan construction failed (non-fatal): %s", bp_exc)
        ctx["build_plan"] = build_plan_fallback(
            slug=slug,
            is_edit=is_edit,
            has_disk_spec=getattr(ctx["project_state"], "spec_snapshot", None) is not None,
        ).to_dict()

    # ── Generation plan context (plan-aware ordering helper) ────────────
    from services.generation_plan_context import build_generation_plan_context
    import config.settings as _settings_pipeline
    _plan_ctx = (
        build_generation_plan_context(ctx["build_plan"])
        if _settings_pipeline.settings.plan_aware_generation
        else None
    )
    ctx["generation_plan_context"] = _plan_ctx.log_dict() if _plan_ctx else None

    # ── Stage 4: generate_assets ─────────────────────────────────────────
    _emit_stage(emit, "generate_assets", "Generating images and icons", "running")
    try:
        assets, ms = _timed(lambda: _generate_image_assets(ctx["intent"], slug))
        png_count = sum(1 for k in assets if k.endswith(".png") or k.endswith(".jpg"))
        svg_count = sum(1 for k in assets if k.endswith(".svg"))
        parts = []
        if png_count:
            parts.append(f"{png_count} AI image{'s' if png_count != 1 else ''}")
        if svg_count:
            parts.append(f"{svg_count} SVG{'s' if svg_count != 1 else ''}")
        _emit_stage(emit, "generate_assets", "Generating images and icons", "done",
                    duration_ms=ms, artifact_type="images",
                    artifact_name=", ".join(parts) or "no assets")
        ctx["image_assets"] = assets
    except Exception as exc:
        _emit_stage(emit, "generate_assets", "Generating images and icons", "error", error=str(exc))
        ctx["image_assets"] = {}

    # ── Stage 5: generate_files ──────────────────────────────────────────
    _emit_stage(emit, "generate_files", "Building website files", "running")
    try:
        from services.code_generation_service import FileChange, GenerationResult, generate

        gen_done = threading.Event()
        def _progress_emitter():
            tick = 0
            while not gen_done.wait(timeout=12):
                tick += 1
                _emit_stage(emit, "generate_files", "Building website files", "running",
                            artifact_name=f"{'Editing' if is_edit else 'Generating'}... {tick * 12}s")
        prog_thread = threading.Thread(target=_progress_emitter, daemon=True)
        prog_thread.start()

        asset_paths = list(ctx.get("image_assets", {}).keys())
        try:
            gen_result, ms = _timed(lambda: generate(
                slug=slug,
                user_message=message,
                history=history,
                existing_files=existing_files,
                style_seed=style_seed,
                design_system=design_system,
                operation=operation,
                blueprint=ctx.get("blueprint"),
                brand_spec=brand_spec,
                available_assets=asset_paths,
                generation_plan_context=_plan_ctx,
            ))
        finally:
            gen_done.set()
            prog_thread.join(timeout=1)

        # Append image asset FileChanges (skip if spec pipeline already handled rendering)
        if gen_result.model_mode not in ("spec_pipeline", "spec_edit"):
            for asset_path, asset_content in ctx["image_assets"].items():
                is_png = asset_path.endswith(".png") or asset_path.endswith(".webp") or asset_path.endswith(".jpg")
                gen_result.changes.append(FileChange(
                    path=f"data/websites/{slug}/{asset_path}",
                    action="create",
                    content=asset_content,
                    summary=f"Generated {'AI image' if is_png else 'SVG'} asset",
                ))

        page_count = sum(1 for c in gen_result.changes if c.path.endswith(".html"))
        pipeline_type = "spec" if gen_result.model_mode in ("spec_pipeline", "spec_edit") else "llm"
        _emit_stage(emit, "generate_files", "Building website files", "done",
                    duration_ms=ms, artifact_type="code",
                    artifact_name=f"{page_count} page{'s' if page_count != 1 else ''} ({pipeline_type})")
        ctx["gen"] = gen_result
        ctx["blueprint"] = getattr(gen_result, "blueprint", {})
    except Exception as exc:
        _emit_stage(emit, "generate_files", "Building website files", "error", error=str(exc))
        raise

    # ── Pre-apply validation orchestration (observability; apply unchanged) ─
    from services.build_validation import pre_apply_orchestrate
    ctx["pre_apply_validation"] = pre_apply_orchestrate(
        slug, ctx["gen"].changes
    ).to_dict()

    # ── Repair loop (bounded; default off via BUILDER_REPAIR_ENABLED) ───
    # Placement: after first pre_apply_orchestrate, before apply_files.
    # Trigger: skipped_by_output_validator (non-binary) OR pending_html_issues
    #          (missing_doctype / missing_title) on clean paths.
    # Loop is a plain for-range — no unbounded while True.
    # ctx["gen"].changes is mutated in place (targeted indices only).
    # ctx["repair_trace"] accumulates one dict per round for observability.
    import config.settings as _settings_repair_mod
    from services.build_repair import run_repair_round, should_repair

    ctx["repair_trace"] = []
    if _settings_repair_mod.settings.builder_repair_enabled:
        _repair_max_rounds = _settings_repair_mod.settings.builder_repair_max_rounds
        _repair_max_files = _settings_repair_mod.settings.builder_repair_max_files_per_round

        for _repair_round in range(_repair_max_rounds):
            if not should_repair(ctx["pre_apply_validation"]):
                break
            _attempt = run_repair_round(
                slug=slug,
                changes=ctx["gen"].changes,
                validation_dict=ctx["pre_apply_validation"],
                round_index=_repair_round,
                max_files=_repair_max_files,
                user_message=message,
            )
            ctx["repair_trace"].append(_attempt.to_dict())
            if not _attempt.paths_touched:
                break  # nothing actionable — stop to avoid wasted rounds
            # Recompute validation with patched changes
            ctx["pre_apply_validation"] = pre_apply_orchestrate(
                slug, ctx["gen"].changes
            ).to_dict()

    # ── Repair feedback summary (Phase 5) ───────────────────────────────
    # Build a per-run RepairSummary from ctx["repair_trace"] (always present,
    # may be [] if repair was disabled or no trigger fired).
    # If repair touched anything, refresh ctx["generation_plan_context"] with
    # avoid_paths and repair_hints so downstream logging/debugging is richer.
    # generate() has already run — this does NOT re-invoke generation.
    from services.build_repair_feedback import build_repair_summary as _build_repair_summary
    _repair_summary_obj = _build_repair_summary(ctx["repair_trace"])
    ctx["repair_summary"] = _repair_summary_obj.to_dict()

    if _repair_summary_obj.repaired_paths or _repair_summary_obj.failed_paths:
        from services.generation_plan_context import build_generation_plan_context as _rebuild_gpc
        _enriched_plan_ctx = _rebuild_gpc(
            ctx["build_plan"],
            repair_summary_dict=ctx["repair_summary"],
        )
        ctx["generation_plan_context"] = _enriched_plan_ctx.log_dict()
        logger.info(
            "Repair feedback: repaired=%s failed=%s avoid_paths=%s",
            list(_repair_summary_obj.repaired_paths),
            list(_repair_summary_obj.failed_paths),
            list(_enriched_plan_ctx.avoid_paths),
        )

    # ── Stage 6: apply_files ─────────────────────────────────────────────
    _emit_stage(emit, "apply_files", "Saving files", "running")
    try:
        from services.workspace_editor import apply_changes
        apply_result, ms = _timed(lambda: apply_changes(slug=slug, changes=ctx["gen"].changes))
        ctx["apply"] = apply_result

        # Persist text files to project_files DB table
        try:
            from data.database import upsert_project_file
            prefix = f"data/websites/{slug}/"
            for change in ctx["gen"].changes:
                if isinstance(change.content, str):
                    rel_path = change.path
                    if rel_path.startswith(prefix):
                        rel_path = rel_path[len(prefix):]
                    upsert_project_file(session_id, rel_path, change.content)
        except Exception as db_exc:
            logger.warning("project_files DB upsert failed (non-fatal): %s", db_exc)

        _emit_stage(emit, "apply_files", "Saving files", "done", duration_ms=ms,
                    artifact_type="files",
                    artifact_name=f"{len(apply_result.applied)} file{'s' if len(apply_result.applied) != 1 else ''} saved")
    except Exception as exc:
        _emit_stage(emit, "apply_files", "Saving files", "error", error=str(exc))
        raise

    # ── Stage 7: wire_navigation ─────────────────────────────────────────
    _emit_stage(emit, "wire_navigation", "Wiring navigation links", "running")
    try:
        from services.link_wiring import run_link_wiring_pass
        (wired_changes, lw_warnings), ms = _timed(
            lambda: run_link_wiring_pass(slug, ctx["gen"].changes, operation)
        )
        ctx["gen"].changes = wired_changes
        ctx["gen"].warnings.extend(lw_warnings)
        fix_count = len(lw_warnings)
        _emit_stage(emit, "wire_navigation", "Wiring navigation links", "done",
                    duration_ms=ms, artifact_type="links",
                    artifact_name=f"{fix_count} link{'s' if fix_count != 1 else ''} wired")
    except Exception as exc:
        _emit_stage(emit, "wire_navigation", "Wiring navigation links", "error", error=str(exc))

    # ── Stage 8: quality_check ───────────────────────────────────────────
    _emit_stage(emit, "quality_check", "Validating quality", "running")
    try:
        quality, ms = _timed(lambda: _run_quality_check(slug, ctx["apply"]))
        _emit_stage(emit, "quality_check", "Validating quality", "done",
                    duration_ms=ms, artifact_type="quality",
                    artifact_name=quality["summary"])
        ctx["quality"] = quality
    except Exception as exc:
        _emit_stage(emit, "quality_check", "Validating quality", "error", error=str(exc))
        ctx["quality"] = {"summary": "check skipped"}

    # ── Stage 9: complete ────────────────────────────────────────────────
    _emit_stage(emit, "complete", "Complete", "done", duration_ms=0)

    return ctx


# ---------------------------------------------------------------------------
# Stage implementations
# ---------------------------------------------------------------------------

def _generate_image_assets(
    intent: dict[str, Any],
    slug: str,
) -> dict[str, str | bytes]:
    """Generate image assets (DALL-E with auto-compression, or fallback SVG).

    DALL-E hero images (1024x1024) are ~3MB raw PNG, which exceeds the 1MB
    pipeline limit. The adapter auto-compresses to JPEG when needed, so the
    returned keys may have .jpg or .png extensions depending on compression.
    """
    from services.image_adapter import (
        generate_all_images,
        generate_feature_icon_svg,
        generate_hero_svg,
    )
    import re as _re

    assets: dict[str, str | bytes] = {}
    features = (intent.get("core_features") or [])[:3]

    dalle_images: dict[str, bytes] = {}
    try:
        dalle_images = generate_all_images(intent)
        if dalle_images:
            logger.info("DALL-E generated %d image(s) for slug=%r: %s",
                        len(dalle_images), slug, list(dalle_images.keys()))
    except Exception as exc:
        logger.warning("DALL-E batch generation failed, falling back to SVG: %s", exc)

    # Hero — check for any raster format the adapter may have produced
    hero_key = next((k for k in dalle_images if k.startswith("assets/hero.")), None)
    if hero_key:
        assets[hero_key] = dalle_images[hero_key]
    else:
        try:
            assets["assets/hero.svg"] = generate_hero_svg(intent)
        except Exception as exc:
            logger.warning("Hero SVG generation failed: %s", exc)

    # Feature icons — check for any raster format
    for i, feature in enumerate(features):
        feature_slug = _re.sub(r'[^a-z0-9]+', '-', feature.lower()).strip('-')
        numbered_key = next(
            (k for k in dalle_images if k.startswith(f"assets/icon-{i + 1}.")), None
        )
        slug_key = next(
            (k for k in dalle_images if k.startswith(f"assets/icon-{feature_slug}.")), None
        )

        if numbered_key:
            assets[numbered_key] = dalle_images[numbered_key]
            if slug_key:
                assets[slug_key] = dalle_images[slug_key]
        else:
            try:
                svg_content = generate_feature_icon_svg(feature)
                assets[f"assets/icon-{i + 1}.svg"] = svg_content
                assets[f"assets/icon-{feature_slug}.svg"] = svg_content
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
        "summary": f"{checked} file{'s' if checked != 1 else ''}{issue_note}",
    }
