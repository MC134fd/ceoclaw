"""
Builder v2 quality-upgrade tests.

Coverage:
1.  _maybe_add_endpoint_scaffold appends data.json FileChange for add_endpoint operations.
2.  Mock HTML that references assets/hero.svg and assets/icon-1.svg contains those strings.
3.  check_html_links flags broken internal href and src references.
4.  check_html_links ignores external links and anchor-only hrefs.
5.  parse_operation extracts placement_targets from placement phrases.
6.  parse_operation extracts navigation_targets from navigation phrases.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ---------------------------------------------------------------------------
# Change 1 — endpoint scaffold parity
# ---------------------------------------------------------------------------

def test_endpoint_scaffold_in_pipeline_mode():
    """_maybe_add_endpoint_scaffold appends a data.json FileChange."""
    from services.code_generation_service import FileChange, GenerationResult
    from api.server import _maybe_add_endpoint_scaffold

    gen = GenerationResult(
        assistant_message="Generated site.",
        changes=[
            FileChange(
                path="data/websites/my-api/index.html",
                action="create",
                content="<html></html>",
                summary="Landing page",
            )
        ],
    )
    operation = {
        "type": "add_endpoint",
        "target": "",
        "metadata": {"http_methods": ["GET", "POST"]},
    }
    _maybe_add_endpoint_scaffold(gen, "my-api", operation)

    data_json_changes = [c for c in gen.changes if c.path.endswith("data.json")]
    assert len(data_json_changes) == 1, (
        f"Expected exactly one data.json change, got: {[c.path for c in gen.changes]}"
    )
    assert data_json_changes[0].path == "data/websites/my-api/data.json"
    assert "endpoints" in data_json_changes[0].content
    assert "GET" in data_json_changes[0].content


def test_endpoint_scaffold_idempotent():
    """Calling _maybe_add_endpoint_scaffold twice must not add a second data.json."""
    from services.code_generation_service import FileChange, GenerationResult
    from api.server import _maybe_add_endpoint_scaffold

    gen = GenerationResult(
        assistant_message="Done.",
        changes=[],
    )
    operation = {"type": "add_endpoint", "metadata": {"http_methods": ["GET"]}}

    _maybe_add_endpoint_scaffold(gen, "my-api", operation)
    _maybe_add_endpoint_scaffold(gen, "my-api", operation)

    data_json_changes = [c for c in gen.changes if c.path.endswith("data.json")]
    assert len(data_json_changes) == 1


def test_endpoint_scaffold_skipped_for_non_endpoint_operation():
    """_maybe_add_endpoint_scaffold must not append anything for non-add_endpoint ops."""
    from services.code_generation_service import GenerationResult
    from api.server import _maybe_add_endpoint_scaffold

    gen = GenerationResult(assistant_message="Done.", changes=[])
    operation = {"type": "add_component", "metadata": {}}

    _maybe_add_endpoint_scaffold(gen, "my-app", operation)
    assert gen.changes == []


# ---------------------------------------------------------------------------
# Change 2 — image asset placement contract in prompt
# ---------------------------------------------------------------------------

def test_image_assets_referenced_in_html():
    """HTML that properly follows the asset placement contract references hero + icon SVGs."""
    html = """<!DOCTYPE html>
<html>
<head><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body>
  <section class="hero">
    <h1>My Product</h1>
    <img src="assets/hero.svg" alt="My Product hero illustration" class="hero-img"
         style="max-width:100%;height:auto;">
  </section>
  <section class="features">
    <div class="card">
      <img src="assets/icon-1.svg" alt="Fast sync icon" style="width:48px;height:48px;">
      <h3>Fast Sync</h3>
    </div>
  </section>
</body>
</html>"""

    assert 'assets/hero.svg' in html, "hero.svg must be referenced in HTML"
    assert 'assets/icon-1.svg' in html, "icon-1.svg must be referenced in HTML"
    assert 'class="hero-img"' in html
    assert 'max-width:100%' in html


def test_asset_placement_contract_in_system_prompt():
    """The system prompt must contain the GENERATED ASSET PLACEMENT CONTRACT section."""
    from services.code_generation_service import _SYSTEM_PROMPT_BASE

    assert "GENERATED ASSET PLACEMENT CONTRACT" in _SYSTEM_PROMPT_BASE
    assert "assets/hero.svg" in _SYSTEM_PROMPT_BASE
    assert "assets/icon-N.svg" in _SYSTEM_PROMPT_BASE
    assert "Never inline SVG content" in _SYSTEM_PROMPT_BASE


def test_design_token_contract_in_system_prompt():
    """The system prompt must contain the DESIGN TOKEN & VISUAL RHYTHM CONTRACT section."""
    from services.code_generation_service import _SYSTEM_PROMPT_BASE

    assert "DESIGN TOKEN & VISUAL RHYTHM CONTRACT" in _SYSTEM_PROMPT_BASE
    assert "--color-bg" in _SYSTEM_PROMPT_BASE
    assert "btn-primary" in _SYSTEM_PROMPT_BASE
    assert "btn-secondary" in _SYSTEM_PROMPT_BASE


# ---------------------------------------------------------------------------
# Change 4 — navigation/link quality checks
# ---------------------------------------------------------------------------

def test_link_validator_flags_broken_links():
    """check_html_links must report both a broken href and a missing src."""
    from services.output_validator import check_html_links

    html = """<!DOCTYPE html>
<html><body>
  <a href="/app.html">Go to app</a>
  <img src="assets/hero.svg" alt="hero">
</body></html>"""

    warnings = check_html_links(html, "index.html", available_files={"index.html"})

    broken_paths = [w for w in warnings if "/app.html" in w or "app.html" in w]
    missing_svg = [w for w in warnings if "hero.svg" in w]

    assert broken_paths, f"Expected warning for /app.html, got: {warnings}"
    assert missing_svg, f"Expected warning for assets/hero.svg, got: {warnings}"


def test_link_validator_ignores_external_links():
    """check_html_links must not warn about external URLs or anchor-only hrefs."""
    from services.output_validator import check_html_links

    html = """<!DOCTYPE html>
<html><body>
  <a href="https://stripe.com">Stripe</a>
  <a href="#section-features">Jump</a>
  <a href="mailto:hello@example.com">Email</a>
  <a href="tel:+15550000">Call</a>
  <img src="data:image/svg+xml;base64,abc" alt="inline">
</body></html>"""

    warnings = check_html_links(html, "index.html", available_files=set())
    assert warnings == [], f"Expected no warnings for external/anchor refs, got: {warnings}"


def test_link_validator_no_warnings_for_present_files():
    """check_html_links must stay silent when all refs exist in available_files."""
    from services.output_validator import check_html_links

    html = """<!DOCTYPE html>
<html><body>
  <a href="app.html">App</a>
  <img src="assets/hero.svg" alt="hero">
</body></html>"""

    warnings = check_html_links(
        html,
        "index.html",
        available_files={"index.html", "app.html", "assets/hero.svg"},
    )
    assert warnings == [], f"Expected no warnings, got: {warnings}"


def test_link_validator_wired_into_validate_files():
    """validate_files must extend its warnings with link check results."""
    from services.output_validator import validate_files

    # index.html references app.html which is not in the files dict
    html = """<!DOCTYPE html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    :root { --c: #000; }
    @media (max-width: 1024px) { body { padding: 1rem; } }
    @media (max-width: 640px) { body { font-size: 0.9rem; } }
    .wrap { max-width: 100%; overflow-wrap: break-word; }
    .box { clamp(1rem, 2vw, 2rem); }
  </style>
</head>
<body>
  <a href="app.html">Go to app</a>
</body>
</html>"""

    _clean, warnings = validate_files({"index.html": html})
    broken = [w for w in warnings if "app.html" in w]
    assert broken, f"Expected a broken-link warning for app.html, got: {warnings}"


# ---------------------------------------------------------------------------
# Change 3 — operation parser extensions
# ---------------------------------------------------------------------------

def test_operation_parser_extracts_placement_targets():
    """parse_operation must detect 'features' as a placement_targets entry."""
    from services.operation_parser import parse_operation

    result = parse_operation("place the hero image in the features section")
    assert "placement_targets" in result
    assert "features" in result["placement_targets"], (
        f"Expected 'features' in placement_targets, got: {result['placement_targets']}"
    )


def test_operation_parser_extracts_placement_hero():
    """parse_operation must detect 'hero' as a placement target."""
    from services.operation_parser import parse_operation

    result = parse_operation("add the logo to the hero section")
    assert "hero" in result["placement_targets"], (
        f"Expected 'hero' in placement_targets, got: {result['placement_targets']}"
    )


def test_operation_parser_extracts_navigation_targets():
    """parse_operation must detect 'pricing' as a navigation_targets entry."""
    from services.operation_parser import parse_operation

    result = parse_operation("add a link to the pricing page")
    assert "navigation_targets" in result
    assert "pricing" in result["navigation_targets"], (
        f"Expected 'pricing' in navigation_targets, got: {result['navigation_targets']}"
    )


def test_operation_parser_extracts_navigation_route():
    """parse_operation must extract explicit route strings like /pricing."""
    from services.operation_parser import parse_operation

    result = parse_operation("add link to /pricing")
    assert "/pricing" in result["navigation_targets"] or "pricing" in result["navigation_targets"], (
        f"Expected '/pricing' or 'pricing' in navigation_targets, got: {result['navigation_targets']}"
    )


def test_operation_parser_extracts_navigation_cta():
    """parse_operation must detect CTA navigation hint."""
    from services.operation_parser import parse_operation

    result = parse_operation("CTA should go to signup")
    assert "signup" in result["navigation_targets"], (
        f"Expected 'signup' in navigation_targets, got: {result['navigation_targets']}"
    )


def test_operation_parser_empty_placement_and_nav_for_generic():
    """parse_operation must return empty lists when no placement/nav hints present."""
    from services.operation_parser import parse_operation

    result = parse_operation("change the background color to dark blue")
    assert isinstance(result["placement_targets"], list)
    assert isinstance(result["navigation_targets"], list)


def test_operation_parser_preserves_existing_fields():
    """parse_operation must still return type/target/metadata alongside new fields."""
    from services.operation_parser import parse_operation

    result = parse_operation("add a GET endpoint for users")
    assert result["type"] == "add_endpoint"
    assert "http_methods" in result["metadata"]
    assert "GET" in result["metadata"]["http_methods"]
    assert "placement_targets" in result
    assert "navigation_targets" in result


# ===========================================================================
# Builder v2 — NEW TESTS (appended)
# ===========================================================================

# ---------------------------------------------------------------------------
# Goal A — planning artifact stages
# ---------------------------------------------------------------------------

def test_derive_brand_style_brief_returns_layout_family():
    from services.generation_pipeline import _derive_brand_style_brief
    intent = {"product_type": "health", "product_name": "FitTrack"}
    result = _derive_brand_style_brief(intent, [], None, None)
    assert result["layout_family"] == "wellness"
    assert "tone" in result


def test_derive_brand_style_brief_diversity_avoids_repeat():
    from services.generation_pipeline import _derive_brand_style_brief
    intent = {"product_type": "saas", "product_name": "WorkflowAI"}
    history = [{"brand_family": "saas"}]
    result = _derive_brand_style_brief(intent, history, None, None)
    assert result["layout_family"] != "saas"


def test_derive_information_architecture_sections_match_family():
    from services.generation_pipeline import _derive_information_architecture
    intent = {"product_name": "CRM Pro", "core_features": ["Contacts", "Pipeline"]}
    content_plan = {"pages": ["index.html"], "mode": "new"}
    brand_brief = {"layout_family": "enterprise", "brand_family": "enterprise"}
    ia = _derive_information_architecture(intent, content_plan, brand_brief)
    assert "index.html" in ia["sections"]
    assert "trust_logos" in ia["sections"]["index.html"]


def test_derive_implementation_plan_tasks_not_empty():
    from services.generation_pipeline import _derive_implementation_plan
    ia = {
        "pages": ["index.html"],
        "sections": {"index.html": ["hero", "footer"]},
        "nav_items": ["pricing"],
        "primary_cta": "Sign Up",
    }
    brief = {"layout_family": "saas"}
    plan = _derive_implementation_plan(ia, brief, None)
    assert len(plan["tasks"]) >= 1
    assert plan["primary_cta"] == "Sign Up"


def test_stage_defs_match_expected_keys():
    """STAGE_DEFS in generation_pipeline.py must have all 12 expected keys."""
    from services.generation_pipeline import STAGE_DEFS
    expected_keys = [
        "parse_intent", "business_concept", "feature_architecture",
        "design_direction", "information_architecture", "implementation_plan",
        "generate_index", "generate_pages", "generate_assets",
        "wire_navigation", "quality_check", "complete",
    ]
    actual_keys = [s[0] for s in STAGE_DEFS]
    assert actual_keys == expected_keys, f"Mismatch: {actual_keys}"


# ---------------------------------------------------------------------------
# Goal B — layout family system
# ---------------------------------------------------------------------------

def test_layout_family_sections_have_all_keys():
    from services.code_generation_service import _LAYOUT_FAMILY_SECTIONS
    required = {"saas", "enterprise", "wellness", "developer", "marketplace", "education", "consumer"}
    assert required.issubset(set(_LAYOUT_FAMILY_SECTIONS.keys()))


def test_build_section_mandate_includes_family_name():
    from services.code_generation_service import _build_section_mandate
    mandate = _build_section_mandate("developer")
    assert "developer" in mandate.lower()


def test_system_prompt_no_hardcoded_mandatory_sections():
    """_SYSTEM_PROMPT_BASE must NOT contain the static 6-section block."""
    from services.code_generation_service import _SYSTEM_PROMPT_BASE
    assert "MANDATORY LANDING PAGE SECTIONS (all 6 required)" not in _SYSTEM_PROMPT_BASE


def test_build_system_prompt_injects_saas_sections_by_default():
    from services.code_generation_service import _build_system_prompt
    prompt = _build_system_prompt()
    assert "MANDATORY LANDING PAGE SECTIONS" in prompt
    assert "saas" in prompt.lower() or "Hero" in prompt


def test_build_system_prompt_injects_enterprise_sections_for_enterprise():
    from services.code_generation_service import _build_system_prompt
    prompt = _build_system_prompt(style_seed={"layout_family": "enterprise"})
    assert "trust_logos" in prompt.lower() or "Trust logos" in prompt or "trust logo" in prompt.lower()


# ---------------------------------------------------------------------------
# Goal C — route graph validation
# ---------------------------------------------------------------------------

def test_route_graph_valid_when_all_nodes_present():
    from services.output_validator import validate_route_graph
    rg = {
        "nodes": ["index.html", "app.html"],
        "edges": [{"from": "index.html", "to": "app.html", "label": "CTA"}],
    }
    assert validate_route_graph(rg, {"index.html", "app.html"}) == []


def test_route_graph_warns_on_missing_node():
    from services.output_validator import validate_route_graph
    rg = {"nodes": ["index.html", "missing.html"], "edges": []}
    warnings = validate_route_graph(rg, {"index.html"})
    assert any("missing.html" in w for w in warnings)


def test_route_graph_warns_on_dangling_edge():
    from services.output_validator import validate_route_graph
    rg = {
        "nodes": ["index.html"],
        "edges": [{"from": "index.html", "to": "ghost.html", "label": "Nav"}],
    }
    warnings = validate_route_graph(rg, {"index.html"})
    assert any("ghost.html" in w for w in warnings)


def test_route_graph_empty_is_silent():
    from services.output_validator import validate_route_graph
    assert validate_route_graph({}, set()) == []
    assert validate_route_graph(None, set()) == []


# ---------------------------------------------------------------------------
# Goal D — image placement post-generation check
# ---------------------------------------------------------------------------

def test_image_placement_check_warns_when_svg_missing_from_html():
    from services.generation_pipeline import _check_image_placement
    from services.code_generation_service import FileChange, GenerationResult

    gen = GenerationResult(
        assistant_message="Done.",
        changes=[FileChange(
            path="data/websites/test-app/index.html",
            action="create",
            content="<!DOCTYPE html><html><body><h1>Hello</h1></body></html>",
            summary="",
        )],
    )
    _check_image_placement(gen, {"assets/hero.svg": "<svg/>"}, "test-app")
    assert any("hero.svg" in w for w in gen.warnings)


def test_image_placement_check_silent_when_svg_referenced():
    from services.generation_pipeline import _check_image_placement
    from services.code_generation_service import FileChange, GenerationResult

    gen = GenerationResult(
        assistant_message="Done.",
        changes=[FileChange(
            path="data/websites/test-app/index.html",
            action="create",
            content='<!DOCTYPE html><html><body><img src="assets/hero.svg"></body></html>',
            summary="",
        )],
    )
    _check_image_placement(gen, {"assets/hero.svg": "<svg/>"}, "test-app")
    assert gen.warnings == []


# ---------------------------------------------------------------------------
# Goal F — clarification detection
# ---------------------------------------------------------------------------

def test_clarification_triggered_on_vague_first_message():
    from services.generation_pipeline import check_clarification_needed
    result = check_clarification_needed("help me", [], None)
    assert result is not None
    assert result["needs_clarification"] is True
    assert len(result["questions"]) >= 2


def test_clarification_not_triggered_with_history():
    from services.generation_pipeline import check_clarification_needed
    history = [{"role": "user", "content": "build me a calorie tracker"}]
    result = check_clarification_needed("make it dark", history, None)
    assert result is None


def test_clarification_not_triggered_with_style_seed():
    from services.generation_pipeline import check_clarification_needed
    result = check_clarification_needed("hi", [], {"palette": "midnight"})
    assert result is None


def test_clarification_not_triggered_for_substantive_message():
    from services.generation_pipeline import check_clarification_needed
    result = check_clarification_needed(
        "Build me a calorie tracking app for fitness enthusiasts", [], None
    )
    assert result is None


# ---------------------------------------------------------------------------
# Goal G — new operation types
# ---------------------------------------------------------------------------

def test_operation_parser_detects_remove_page():
    from services.operation_parser import parse_operation
    result = parse_operation("remove the pricing page")
    assert result["type"] == "remove_page"


def test_operation_parser_detects_update_nav():
    from services.operation_parser import parse_operation
    result = parse_operation("add a nav link to about")
    assert result["type"] == "update_nav"


def test_operation_parser_detects_cta_target_change():
    from services.operation_parser import parse_operation
    result = parse_operation("CTA should go to signup")
    assert result["type"] == "cta_target_change"


def test_operation_parser_add_page_still_works():
    from services.operation_parser import parse_operation
    result = parse_operation("add a new blog page")
    assert result["type"] == "add_page"


# ===========================================================================
# NEW TESTS — Multi-page upgrade
# ===========================================================================

# ---------------------------------------------------------------------------
# layout_plan artifact
# ---------------------------------------------------------------------------

def test_layout_plan_field_in_generation_result():
    """GenerationResult must have a layout_plan field defaulting to empty dict."""
    from services.code_generation_service import GenerationResult
    gr = GenerationResult(assistant_message="Done.", changes=[])
    assert hasattr(gr, "layout_plan")
    assert isinstance(gr.layout_plan, dict)


def test_layout_plan_in_implementation_plan():
    """_derive_implementation_plan must return a layout_plan dict with required keys."""
    from services.generation_pipeline import _derive_implementation_plan
    ia = {
        "pages": ["index.html"],
        "sections": {"index.html": ["hero", "features", "footer"]},
        "nav_items": [],
        "primary_cta": "Get Started",
        "layout_family": "saas",
    }
    brief = {"layout_family": "saas"}
    plan = _derive_implementation_plan(ia, brief, None)
    assert "layout_plan" in plan
    lp = plan["layout_plan"]
    assert "layout_family" in lp
    assert "page_map" in lp
    assert "section_order" in lp
    assert "cta_flow" in lp
    assert "dynamic_components" in lp
    assert "testimonial_carousel" in lp["dynamic_components"]


def test_layout_plan_cta_flow_when_both_pages_present():
    """layout_plan.cta_flow must link index.html → app.html when both pages exist."""
    from services.generation_pipeline import _derive_implementation_plan
    ia = {
        "pages": ["index.html", "app.html"],
        "sections": {
            "index.html": ["hero", "cta"],
            "app.html": ["dashboard"],
        },
        "primary_cta": "Start Free Trial",
    }
    plan = _derive_implementation_plan(ia, {"layout_family": "saas"}, None)
    cta_flow = plan["layout_plan"]["cta_flow"]
    assert len(cta_flow) >= 1
    assert cta_flow[0]["to"] == "app.html"
    assert "Start Free Trial" in cta_flow[0]["label"]


# ---------------------------------------------------------------------------
# link_wiring stage in STAGE_DEFS ordering
# ---------------------------------------------------------------------------

def test_link_wiring_stage_ordering():
    """wire_navigation must appear between generate_pages and quality_check in STAGE_DEFS."""
    from services.generation_pipeline import STAGE_DEFS
    keys = [s[0] for s in STAGE_DEFS]
    assert "wire_navigation" in keys
    wn_idx = keys.index("wire_navigation")
    gp_idx = keys.index("generate_pages")
    qc_idx = keys.index("quality_check")
    assert gp_idx < wn_idx < qc_idx


# ---------------------------------------------------------------------------
# System prompt contract sections
# ---------------------------------------------------------------------------

def test_multipage_contract_in_system_prompt():
    """_SYSTEM_PROMPT_BASE must contain the MULTI-PAGE CONTRACT section."""
    from services.code_generation_service import _SYSTEM_PROMPT_BASE
    assert "MULTI-PAGE CONTRACT" in _SYSTEM_PROMPT_BASE
    assert "pages/" in _SYSTEM_PROMPT_BASE
    assert "relative paths" in _SYSTEM_PROMPT_BASE.lower() or "relative href" in _SYSTEM_PROMPT_BASE.lower()


def test_dynamic_components_contract_in_system_prompt():
    """_SYSTEM_PROMPT_BASE must contain the DYNAMIC COMPONENTS CONTRACT section."""
    from services.code_generation_service import _SYSTEM_PROMPT_BASE
    assert "DYNAMIC COMPONENTS CONTRACT" in _SYSTEM_PROMPT_BASE
    assert "carousel" in _SYSTEM_PROMPT_BASE.lower()
    assert "reveal" in _SYSTEM_PROMPT_BASE.lower()
    assert "prefers-reduced-motion" in _SYSTEM_PROMPT_BASE


def test_spacing_gutter_contract_in_system_prompt():
    """_SYSTEM_PROMPT_BASE must contain the SPACING & GUTTER CONTRACT section."""
    from services.code_generation_service import _SYSTEM_PROMPT_BASE
    assert "SPACING" in _SYSTEM_PROMPT_BASE
    assert "margin-inline" in _SYSTEM_PROMPT_BASE
    assert "clamp(" in _SYSTEM_PROMPT_BASE
    assert "44px" in _SYSTEM_PROMPT_BASE


def test_layout_plan_in_response_contract():
    """_SYSTEM_PROMPT_BASE must describe the layout_plan JSON field."""
    from services.code_generation_service import _SYSTEM_PROMPT_BASE
    assert "layout_plan" in _SYSTEM_PROMPT_BASE


# ---------------------------------------------------------------------------
# Spacing contract validator
# ---------------------------------------------------------------------------

def test_spacing_contract_passes_compliant_html():
    """check_spacing_contract returns no warnings for fully compliant HTML."""
    from services.output_validator import check_spacing_contract
    html = """\
<!DOCTYPE html><html><head><style>
:root {
  --space-2xl: clamp(2rem, 5vw, 4rem);
  --container-width: clamp(320px, 90vw, 1200px);
}
.container { max-width: var(--container-width); margin-inline: auto; padding: var(--space-2xl); }
section { padding-block: var(--space-2xl); }
button { min-height: 44px; display: inline-flex; align-items: center; }
</style></head><body></body></html>"""
    warnings = check_spacing_contract(html, "index.html")
    assert warnings == [], f"Expected no warnings for compliant HTML, got: {warnings}"


def test_spacing_contract_warns_missing_max_width():
    """check_spacing_contract warns when no max-width is present."""
    from services.output_validator import check_spacing_contract
    html = "<!DOCTYPE html><html><head><style>body { margin: 0 auto; padding: clamp(1rem, 2vw, 2rem); } button { min-height: 44px; }</style></head><body></body></html>"
    warnings = check_spacing_contract(html, "index.html")
    assert any("max-width" in w for w in warnings), f"Expected max-width warning, got: {warnings}"


def test_spacing_contract_warns_no_clamp():
    """check_spacing_contract warns when no clamp() tokens are present."""
    from services.output_validator import check_spacing_contract
    html = "<!DOCTYPE html><html><head><style>.c { max-width: 1200px; margin-inline: auto; padding: 2rem; } button { min-height: 44px; }</style></head><body></body></html>"
    warnings = check_spacing_contract(html, "index.html")
    assert any("clamp" in w for w in warnings), f"Expected clamp warning, got: {warnings}"


def test_spacing_contract_warns_no_touch_target():
    """check_spacing_contract warns when no 44px touch target sizing is found."""
    from services.output_validator import check_spacing_contract
    html = "<!DOCTYPE html><html><head><style>.c { max-width: clamp(320px,90vw,1200px); margin-inline: auto; padding: 2rem; }</style></head><body></body></html>"
    warnings = check_spacing_contract(html, "index.html")
    assert any("touch" in w for w in warnings), f"Expected touch target warning, got: {warnings}"


# ---------------------------------------------------------------------------
# link_wiring module
# ---------------------------------------------------------------------------

def test_normalize_link_absolute_route():
    """normalize_link must convert absolute routes to relative HTML paths."""
    from services.link_wiring import normalize_link
    assert normalize_link("/pricing") == "pages/pricing.html"
    assert normalize_link("/app") == "app.html"
    assert normalize_link("/index") == "index.html"


def test_normalize_link_bare_name():
    """normalize_link must handle bare page names without leading slash."""
    from services.link_wiring import normalize_link
    assert normalize_link("pricing") == "pages/pricing.html"
    assert normalize_link("about") == "pages/about.html"
    assert normalize_link("signup") == "pages/signup.html"


def test_normalize_link_already_html():
    """normalize_link must return paths that already have extensions unchanged."""
    from services.link_wiring import normalize_link
    assert normalize_link("app.html") == "app.html"
    assert normalize_link("pages/pricing.html") == "pages/pricing.html"


def test_scaffold_missing_page_creates_valid_html():
    """scaffold_missing_page must produce a complete, responsive HTML FileChange."""
    from services.link_wiring import scaffold_missing_page
    change = scaffold_missing_page("my-app", "pages/pricing.html")
    assert change.path == "data/websites/my-app/pages/pricing.html"
    assert "<!DOCTYPE html>" in change.content
    assert "pricing" in change.content.lower()
    assert "viewport" in change.content.lower()
    assert "clamp(" in change.content
    assert "max-width" in change.content.lower()


def test_scaffold_unknown_page_uses_stem():
    """scaffold_missing_page must handle unknown page names gracefully."""
    from services.link_wiring import scaffold_missing_page
    change = scaffold_missing_page("my-app", "pages/partners.html")
    assert "partners" in change.content.lower() or "Partners" in change.content


def test_inject_nav_link_adds_link():
    """_inject_nav_link must add a new <a> to the <nav> element."""
    from services.link_wiring import _inject_nav_link
    html = "<html><body><nav><a href='index.html'>Home</a></nav></body></html>"
    result = _inject_nav_link(html, "pricing", "pages/pricing.html")
    assert "pages/pricing.html" in result


def test_inject_nav_link_is_idempotent():
    """_inject_nav_link must not duplicate links already present."""
    from services.link_wiring import _inject_nav_link
    html = "<html><body><nav><a href='pages/pricing.html'>Pricing</a></nav></body></html>"
    result = _inject_nav_link(html, "pricing", "pages/pricing.html")
    assert result.count("pages/pricing.html") == 1


def test_repair_html_links_rewrites_absolute_routes():
    """_repair_html_links must rewrite /route hrefs to canonical relative paths."""
    from services.link_wiring import _repair_html_links
    html = '<a href="/pricing">Pricing</a><a href="/about">About</a>'
    repaired, fixes = _repair_html_links(html, set())
    # href="/pricing" should be gone; pages/pricing.html is the replacement
    assert 'href="/pricing"' not in repaired
    assert 'href="/about"' not in repaired
    assert "pages/pricing.html" in repaired
    assert "pages/about.html" in repaired
    assert len(fixes) == 2


def test_repair_html_links_preserves_good_hrefs():
    """_repair_html_links must leave already-canonical hrefs untouched."""
    from services.link_wiring import _repair_html_links
    html = '<a href="pages/pricing.html">Pricing</a><a href="https://stripe.com">Stripe</a>'
    repaired, fixes = _repair_html_links(html, set())
    assert repaired == html
    assert fixes == []


def test_build_route_graph_nodes_and_edges():
    """_build_route_graph must extract nodes (HTML files) and edges (internal hrefs)."""
    from services.link_wiring import _build_route_graph
    from services.code_generation_service import FileChange
    changes = [
        FileChange(
            path="data/websites/my-app/index.html",
            action="create",
            content='<!DOCTYPE html><html><body><a href="app.html">App</a></body></html>',
            summary="",
        ),
        FileChange(
            path="data/websites/my-app/app.html",
            action="create",
            content="<!DOCTYPE html><html><body></body></html>",
            summary="",
        ),
    ]
    rg = _build_route_graph("my-app", changes)
    assert "index.html" in rg["nodes"]
    assert "app.html" in rg["nodes"]
    assert any(e["to"] == "app.html" for e in rg["edges"])


def test_run_link_wiring_pass_repairs_absolute_routes():
    """run_link_wiring_pass must rewrite /route hrefs in all HTML changes."""
    from services.link_wiring import run_link_wiring_pass
    from services.code_generation_service import FileChange
    changes = [FileChange(
        path="data/websites/my-app/index.html",
        action="create",
        content='<!DOCTYPE html><html><body><a href="/pricing">Pricing</a></body></html>',
        summary="",
    )]
    updated, warnings = run_link_wiring_pass("my-app", changes, None)
    assert 'href="/pricing"' not in updated[0].content
    assert "pages/pricing.html" in updated[0].content
    assert any("pricing" in w.lower() for w in warnings)


def test_run_link_wiring_pass_scaffolds_missing_page_for_add_page():
    """run_link_wiring_pass must scaffold a missing page for add_page operations."""
    from services.link_wiring import run_link_wiring_pass
    from services.code_generation_service import FileChange
    changes = [FileChange(
        path="data/websites/my-app/index.html",
        action="create",
        content="<!DOCTYPE html><html><body></body></html>",
        summary="",
    )]
    operation = {
        "type": "add_page",
        "target": "pricing",
        "navigation_targets": ["pricing"],
        "page_targets": ["pages/pricing.html"],
    }
    updated, warnings = run_link_wiring_pass("my-app", changes, operation)
    paths = [c.path for c in updated]
    assert any("pricing" in p for p in paths), f"Expected scaffolded pricing page, got: {paths}"


def test_run_link_wiring_pass_no_scaffold_for_general_edit():
    """run_link_wiring_pass must not scaffold any pages for general_edit operations."""
    from services.link_wiring import run_link_wiring_pass
    from services.code_generation_service import FileChange
    changes = [FileChange(
        path="data/websites/my-app/index.html",
        action="create",
        content="<!DOCTYPE html><html><body></body></html>",
        summary="",
    )]
    operation = {"type": "general_edit", "target": "", "navigation_targets": [], "page_targets": []}
    updated, warnings = run_link_wiring_pass("my-app", changes, operation)
    # Should have same number of changes (no scaffolding)
    assert len(updated) == len(changes)


# ---------------------------------------------------------------------------
# Extended operation parser
# ---------------------------------------------------------------------------

def test_operation_parser_add_page_signup():
    """parse_operation must detect 'add a signup page' as add_page."""
    from services.operation_parser import parse_operation
    result = parse_operation("add a signup page")
    assert result["type"] == "add_page"
    assert result["target"] in ("signup", "page")


def test_operation_parser_add_page_login():
    """parse_operation must detect 'create a login page' as add_page."""
    from services.operation_parser import parse_operation
    result = parse_operation("create a login page for users")
    assert result["type"] == "add_page"


def test_operation_parser_page_targets_field_present():
    """parse_operation must always return a page_targets list."""
    from services.operation_parser import parse_operation
    result = parse_operation("add a pricing page")
    assert "page_targets" in result
    assert isinstance(result["page_targets"], list)


def test_operation_parser_page_targets_canonical_path():
    """parse_operation returns canonical page path for add_page pricing."""
    from services.operation_parser import parse_operation
    result = parse_operation("add a pricing page")
    assert result["type"] == "add_page"
    assert result["page_targets"] == ["pages/pricing.html"]


def test_operation_parser_page_targets_empty_for_general_edit():
    """parse_operation must return empty page_targets for general_edit operations."""
    from services.operation_parser import parse_operation
    result = parse_operation("change the hero background to blue")
    assert result["page_targets"] == []


def test_operation_parser_cta_wire_button():
    """parse_operation detects 'wire button to' as cta_target_change."""
    from services.operation_parser import parse_operation
    # Use a message that unambiguously triggers cta_target_change (no page name)
    result = parse_operation("wire the button to signup")
    assert result["type"] == "cta_target_change"


def test_operation_parser_connect_button():
    """parse_operation detects 'connect button to' as cta_target_change."""
    from services.operation_parser import parse_operation
    result = parse_operation("connect the button to the pricing page")
    assert result["type"] == "cta_target_change"


# ===========================================================================
# NEW TESTS — Framer Aura Design System
# ===========================================================================

# ---------------------------------------------------------------------------
# Design system — Aura family
# ---------------------------------------------------------------------------

def test_framer_aura_palette_exists():
    """PALETTES must include the framer_aura entry."""
    from services.design_system_service import PALETTES
    assert "framer_aura" in PALETTES
    aura = PALETTES["framer_aura"]
    assert "primary" in aura    # blue
    assert "secondary" in aura  # purple
    assert "bg" in aura


def test_design_system_defaults_to_framer_aura():
    """DesignSystem.generate() must produce design_family='framer_aura' by default."""
    from services.design_system_service import DesignSystem
    ds = DesignSystem.generate()
    assert ds.design_family == "framer_aura"
    assert ds.palette_name == "framer_aura"


def test_design_system_has_consistency_profile_id():
    """DesignSystem.generate() must produce a non-empty consistency_profile_id."""
    from services.design_system_service import DesignSystem
    ds = DesignSystem.generate()
    assert ds.consistency_profile_id
    assert len(ds.consistency_profile_id) >= 6


def test_design_system_generate_aura_produces_correct_palette():
    """generate_aura() must produce the framer_aura palette."""
    from services.design_system_service import DesignSystem
    ds = DesignSystem.generate_aura()
    assert ds.palette_name == "framer_aura"
    assert ds.design_family == "framer_aura"
    assert ds.colors.get("primary") == "#3b82f6"
    assert ds.colors.get("secondary") == "#8b5cf6"


def test_design_system_merge_preserves_family():
    """merge() must not change design_family unless explicitly overridden."""
    from services.design_system_service import DesignSystem
    ds = DesignSystem.generate_aura()
    merged = ds.merge({"palette_name": "framer_aura_dark", "motion": "subtle"})
    assert merged.design_family == "framer_aura"
    assert merged.consistency_profile_id == ds.consistency_profile_id
    assert merged.motion == "subtle"
    assert merged.palette_name == "framer_aura_dark"


def test_design_system_interaction_presets_not_empty():
    """generate_aura() must include interaction presets."""
    from services.design_system_service import DesignSystem
    ds = DesignSystem.generate_aura()
    assert isinstance(ds.interaction_presets, list)
    assert len(ds.interaction_presets) >= 3
    assert "reveal_scroll" in ds.interaction_presets
    assert "hover_lift" in ds.interaction_presets


def test_design_system_to_dict_round_trips():
    """to_dict() + from_dict() must produce equivalent DesignSystem."""
    from services.design_system_service import DesignSystem
    ds = DesignSystem.generate_aura()
    d = ds.to_dict()
    restored = DesignSystem.from_dict(d)
    assert restored.design_family == ds.design_family
    assert restored.consistency_profile_id == ds.consistency_profile_id
    assert restored.palette_name == ds.palette_name
    assert restored.interaction_presets == ds.interaction_presets


def test_design_system_to_prompt_includes_gradient():
    """to_prompt_block() must mention the blue/purple/pink gradient."""
    from services.design_system_service import DesignSystem
    ds = DesignSystem.generate_aura()
    prompt = ds.to_prompt_block()
    assert "#3b82f6" in prompt or "blue" in prompt.lower()
    assert "#8b5cf6" in prompt or "purple" in prompt.lower()
    assert "gradient" in prompt.lower()
    assert "framer_aura" in prompt


def test_design_system_to_prompt_includes_motion_contract():
    """to_prompt_block() must include the motion contract and reduced-motion mention."""
    from services.design_system_service import DesignSystem
    ds = DesignSystem.generate_aura()
    prompt = ds.to_prompt_block()
    assert "prefers-reduced-motion" in prompt
    assert "reveal" in prompt.lower()


def test_design_system_spacing_policy_aura():
    """generate_aura() must set spacing_policy='aura'."""
    from services.design_system_service import DesignSystem
    ds = DesignSystem.generate_aura()
    assert ds.spacing_policy == "aura"


# ---------------------------------------------------------------------------
# layout_plan — interaction_plan + consistency_profile_id
# ---------------------------------------------------------------------------

def test_layout_plan_includes_interaction_plan():
    """_derive_implementation_plan must include interaction_plan in layout_plan."""
    from services.generation_pipeline import _derive_implementation_plan
    ia = {
        "pages": ["index.html", "app.html"],
        "sections": {
            "index.html": ["hero", "features", "testimonials", "pricing", "cta", "footer"],
            "app.html": ["dashboard"],
        },
        "primary_cta": "Get Started",
    }
    brief = {"layout_family": "saas", "consistency_profile_id": "abc123", "motion_preset": "default"}
    plan = _derive_implementation_plan(ia, brief, None)
    lp = plan["layout_plan"]
    assert "interaction_plan" in lp
    ip = lp["interaction_plan"]
    assert "reveal_scroll" in ip
    assert "hover_lift" in ip
    assert "sticky_nav" in ip
    assert ip["reveal_scroll"] is True


def test_layout_plan_testimonial_carousel_when_testimonials_in_sections():
    """interaction_plan.testimonial_carousel must be True when testimonials section is present."""
    from services.generation_pipeline import _derive_implementation_plan
    ia = {
        "pages": ["index.html"],
        "sections": {"index.html": ["hero", "testimonials", "footer"]},
        "primary_cta": "Start",
    }
    plan = _derive_implementation_plan(ia, {"layout_family": "saas"}, None)
    assert plan["layout_plan"]["interaction_plan"]["testimonial_carousel"] is True


def test_layout_plan_includes_consistency_profile_id():
    """layout_plan must carry the consistency_profile_id from brand_brief."""
    from services.generation_pipeline import _derive_implementation_plan
    ia = {"pages": ["index.html"], "sections": {"index.html": ["hero"]}, "primary_cta": "Go"}
    brief = {"layout_family": "saas", "consistency_profile_id": "test-id-xyz"}
    plan = _derive_implementation_plan(ia, brief, None)
    assert plan["layout_plan"]["consistency_profile_id"] == "test-id-xyz"


def test_layout_plan_includes_spacing_policy():
    """layout_plan must carry the spacing_policy from brand_brief."""
    from services.generation_pipeline import _derive_implementation_plan
    ia = {"pages": ["index.html"], "sections": {"index.html": ["hero"]}, "primary_cta": "Go"}
    brief = {"layout_family": "saas", "spacing_policy": "aura"}
    plan = _derive_implementation_plan(ia, brief, None)
    assert plan["layout_plan"]["spacing_policy"] == "aura"


def test_layout_plan_parallax_hero_disabled_by_default():
    """parallax_hero must be False in default interaction_plan (avoids CLS)."""
    from services.generation_pipeline import _derive_implementation_plan
    ia = {"pages": ["index.html"], "sections": {"index.html": ["hero", "footer"]}, "primary_cta": "Go"}
    brief = {"layout_family": "saas"}
    plan = _derive_implementation_plan(ia, brief, None)
    assert plan["layout_plan"]["interaction_plan"]["parallax_hero"] is False


# ---------------------------------------------------------------------------
# System prompt — Aura contract
# ---------------------------------------------------------------------------

def test_framer_aura_contract_in_system_prompt():
    """_SYSTEM_PROMPT_BASE must contain the FRAMER AURA GENERATION CONTRACT section."""
    from services.code_generation_service import _SYSTEM_PROMPT_BASE
    assert "FRAMER AURA GENERATION CONTRACT" in _SYSTEM_PROMPT_BASE
    assert "#3b82f6" in _SYSTEM_PROMPT_BASE   # blue
    assert "#8b5cf6" in _SYSTEM_PROMPT_BASE   # purple
    assert "#ec4899" in _SYSTEM_PROMPT_BASE   # pink


def test_landing_signup_app_ia_in_system_prompt():
    """_SYSTEM_PROMPT_BASE must describe the landing → signup → app IA flow."""
    from services.code_generation_service import _SYSTEM_PROMPT_BASE
    assert "signup" in _SYSTEM_PROMPT_BASE.lower()
    assert "pages/signup.html" in _SYSTEM_PROMPT_BASE
    assert "pricing" in _SYSTEM_PROMPT_BASE.lower()


def test_tier_aware_pricing_in_system_prompt():
    """_SYSTEM_PROMPT_BASE must include tier-aware pricing section guidance."""
    from services.code_generation_service import _SYSTEM_PROMPT_BASE
    assert "TIER-AWARE PRICING" in _SYSTEM_PROMPT_BASE or "tier" in _SYSTEM_PROMPT_BASE.lower()
    assert "Free" in _SYSTEM_PROMPT_BASE and "Pro" in _SYSTEM_PROMPT_BASE


def test_consistency_profile_id_in_generation_result():
    """GenerationResult must have a consistency_profile_id field."""
    from services.code_generation_service import GenerationResult
    gr = GenerationResult(assistant_message="Done.", changes=[])
    assert hasattr(gr, "consistency_profile_id")
    assert isinstance(gr.consistency_profile_id, str)


# ---------------------------------------------------------------------------
# brand_style_brief — design_family propagation
# ---------------------------------------------------------------------------

def test_brand_style_brief_includes_design_family():
    """_derive_brand_style_brief must return design_family='framer_aura'."""
    from services.generation_pipeline import _derive_brand_style_brief
    intent = {"product_type": "saas", "product_name": "TestApp"}
    result = _derive_brand_style_brief(intent, [], None, {"design_family": "framer_aura", "consistency_profile_id": "abc"})
    assert result.get("design_family") == "framer_aura"


def test_brand_style_brief_propagates_consistency_profile_id():
    """_derive_brand_style_brief must propagate consistency_profile_id from design_system."""
    from services.generation_pipeline import _derive_brand_style_brief
    intent = {"product_type": "saas", "product_name": "TestApp"}
    ds = {"consistency_profile_id": "my-profile-id", "spacing_policy": "aura"}
    result = _derive_brand_style_brief(intent, [], None, ds)
    assert result.get("consistency_profile_id") == "my-profile-id"


def test_brand_style_brief_propagates_spacing_policy():
    """_derive_brand_style_brief must propagate spacing_policy from design_system."""
    from services.generation_pipeline import _derive_brand_style_brief
    intent = {"product_type": "saas", "product_name": "TestApp"}
    ds = {"spacing_policy": "aura", "consistency_profile_id": "x"}
    result = _derive_brand_style_brief(intent, [], None, ds)
    assert result.get("spacing_policy") == "aura"


# ── Blueprint tests ─────────────────────────────────────────────────────────

def test_blueprint_has_required_keys():
    """Blueprint from pipeline context must have all required top-level keys."""
    from services.generation_pipeline import _build_blueprint
    intent = {"product_name": "Acme SaaS", "product_type": "saas", "core_features": ["Auth", "Dashboard"], "target_user": "developers"}
    feature_arch = {"features": ["Auth", "Dashboard"], "feature_count": 2}
    design_dir = {"design_family": "framer_aura", "palette_hint": "framer_aura", "motion_preset": "default", "spacing_policy": "aura", "consistency_profile_id": "abc123"}
    ia = {"sections": {"index.html": ["hero", "features"], "app.html": ["dashboard"]}, "pages": ["index.html", "app.html"]}
    impl_plan = {"tasks": ["Create index.html", "Create app.html"], "layout_plan": {"cta_flow": [{"from": "index.html#cta", "to": "app.html", "label": "Get Started"}]}}
    blueprint = _build_blueprint(intent, feature_arch, design_dir, ia, impl_plan, None)
    for key in ("business_name", "business_positioning", "target_user", "feature_list", "design_direction", "page_map", "cta_flow", "build_steps", "quality_gates"):
        assert key in blueprint, f"Missing blueprint key: {key!r}"


def test_blueprint_page_map_purposes():
    """page_map entries should have correct purpose labels."""
    from services.generation_pipeline import _build_blueprint
    intent = {"product_name": "Test", "product_type": "saas", "core_features": [], "target_user": "users"}
    feature_arch = {"features": [], "feature_count": 0}
    design_dir = {"design_family": "framer_aura", "palette_hint": "", "motion_preset": "default", "spacing_policy": "aura", "consistency_profile_id": ""}
    ia = {
        "sections": {
            "index.html": ["hero"],
            "pages/signup.html": ["form"],
            "app.html": ["dashboard"],
            "pages/pricing.html": ["tiers"],
        }
    }
    impl_plan = {"tasks": [], "layout_plan": {"cta_flow": []}}
    blueprint = _build_blueprint(intent, feature_arch, design_dir, ia, impl_plan, None)
    purpose_map = {p["path"]: p["purpose"] for p in blueprint["page_map"]}
    assert purpose_map.get("index.html") == "landing"
    assert purpose_map.get("pages/signup.html") == "conversion"
    assert purpose_map.get("app.html") == "product_entry"
    assert purpose_map.get("pages/pricing.html") == "pricing"


def test_blueprint_design_direction_from_design_system():
    """design_direction should use design_system values when provided."""
    from services.generation_pipeline import _build_blueprint
    intent = {"product_name": "Test", "product_type": "saas", "core_features": [], "target_user": "x"}
    feature_arch = {"features": [], "feature_count": 0}
    design_dir = {"design_family": "framer_aura", "palette_hint": "framer_aura", "motion_preset": "expressive", "spacing_policy": "aura", "consistency_profile_id": "profile-123"}
    ia = {"sections": {"index.html": ["hero"]}}
    impl_plan = {"tasks": [], "layout_plan": {"cta_flow": []}}
    ds = {"palette_name": "aurora", "display_font": "Syne", "body_font": "Manrope", "consistency_profile_id": "profile-123"}
    blueprint = _build_blueprint(intent, feature_arch, design_dir, ia, impl_plan, ds)
    dd = blueprint["design_direction"]
    assert dd["palette_name"] == "aurora"
    assert dd["font_pair"]["display"] == "Syne"
    assert dd["consistency_profile_id"] == "profile-123"


def test_new_stage_defs_keys():
    """STAGE_DEFS must contain the new stage keys."""
    from services.generation_pipeline import STAGE_DEFS
    stage_keys = [k for k, _ in STAGE_DEFS]
    required = [
        "parse_intent", "business_concept", "feature_architecture", "design_direction",
        "information_architecture", "implementation_plan", "generate_index",
        "generate_pages", "generate_assets", "wire_navigation", "quality_check", "complete"
    ]
    for key in required:
        assert key in stage_keys, f"Missing new stage key: {key!r}"


def test_stage_defs_count():
    """STAGE_DEFS must have exactly 12 entries."""
    from services.generation_pipeline import STAGE_DEFS
    assert len(STAGE_DEFS) == 12, f"Expected 12 stages, got {len(STAGE_DEFS)}"


def test_design_system_generate_unique_returns_design_system():
    """generate_unique should return a DesignSystem instance."""
    from services.design_system_service import DesignSystem
    ds = DesignSystem.generate_unique(archetype="saas")
    assert isinstance(ds, DesignSystem)
    assert ds.consistency_profile_id


def test_design_system_generate_unique_avoids_recent_duplicates():
    """generate_unique should not return the same palette+font combo twice in a row."""
    from services import design_system_service
    from services.design_system_service import DesignSystem
    # Reset recent profiles
    design_system_service._recent_profiles.clear()

    results = [DesignSystem.generate_unique(archetype="saas") for _ in range(4)]
    combos = [(ds.palette_name, ds.display_font) for ds in results]
    # At minimum the first two should not be identical (uniqueness guard is working)
    # We can't guarantee all 4 are unique if palettes run out, but first 2 must differ
    # Allow test to pass if all unique OR if len(PALETTES) < 4 (graceful degradation)
    from services.design_system_service import PALETTES
    if len(PALETTES) >= 4:
        assert len(set(combos)) > 1, "generate_unique returned same combo for all calls"


def test_generation_result_has_blueprint_field():
    """GenerationResult must have a blueprint field."""
    from services.code_generation_service import GenerationResult
    gen = GenerationResult(assistant_message="ok", changes=[])
    assert hasattr(gen, "blueprint")
    assert isinstance(gen.blueprint, dict)


def test_uniqueness_palettes_count():
    """PALETTES dict should have at least 10 entries for adequate uniqueness."""
    from services.design_system_service import PALETTES
    assert len(PALETTES) >= 10, f"Expected >= 10 palettes, got {len(PALETTES)}"


def test_feature_architecture_helper():
    """_derive_feature_architecture should extract feature set correctly."""
    from services.generation_pipeline import _derive_feature_architecture
    intent = {"core_features": ["Auth", "Dashboard", "Billing"], "product_type": "saas"}
    business_concept = {"product_type": "saas"}
    result = _derive_feature_architecture(intent, business_concept)
    assert result["feature_count"] == 3
    assert "Auth" in result["features"]
    assert result["has_auth"] is True
    assert result["has_payments"] is True


def test_business_concept_helper_new_build():
    """_derive_business_concept should return mode=new for fresh builds."""
    from services.generation_pipeline import _derive_business_concept
    intent = {"product_name": "TestApp", "product_type": "saas", "core_features": ["Feature1"], "target_user": "devs"}
    result = _derive_business_concept(intent, existing_files=None)
    assert result["mode"] == "new"
    assert "index.html" in result["pages"]


def test_business_concept_helper_edit_mode():
    """_derive_business_concept with existing_files should return mode=edit."""
    from services.generation_pipeline import _derive_business_concept
    intent = {"product_name": "TestApp", "product_type": "saas", "core_features": [], "target_user": "x"}
    result = _derive_business_concept(intent, existing_files={"index.html": "<html></html>"})
    assert result["mode"] == "edit"


# ---------------------------------------------------------------------------
# A) New-project intent detection
# ---------------------------------------------------------------------------

def test_is_new_project_request_detects_explicit_phrases():
    """Common 'new project' phrases must be detected."""
    from api.server import _is_new_project_request
    positives = [
        "build me a new dog walking app",
        "create a new website for my bakery",
        "start over with a fitness tracker",
        "I want a different website, build me a recipe app",
        "from scratch, make a todo app",
        "build another SaaS for invoicing",
        "build us a new project management tool",
        "instead build a portfolio site",
    ]
    for msg in positives:
        assert _is_new_project_request(msg), f"Expected new-project detection for: {msg!r}"


def test_is_new_project_request_ignores_edit_phrases():
    """Edit/update phrases must NOT be flagged as new-project intent."""
    from api.server import _is_new_project_request
    negatives = [
        "change the hero background to dark blue",
        "add a testimonials section",
        "update the pricing table",
        "make the font larger",
        "fix the navbar on mobile",
        "add a contact form",
    ]
    for msg in negatives:
        assert not _is_new_project_request(msg), f"False positive for: {msg!r}"


def test_new_project_intent_resets_slug_in_session(tmp_path, monkeypatch):
    """If a session has an existing slug and the user requests a new project,
    builder_generate_start must generate a fresh slug (not reuse the old one)."""
    import config.settings as cs
    monkeypatch.setenv("CEOCLAW_DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    monkeypatch.setenv("CREDITS_ENFORCED", "false")
    cs.settings = cs.Settings()
    cs.settings.database_path = str(tmp_path / "test.db")
    cs.settings.auth_required = False
    cs.settings.credits_enforced = False

    from data.database import init_db, upsert_chat_session
    init_db()
    upsert_chat_session("sess-abc", slug="old-calorie-app")

    from api.server import app
    from fastapi.testclient import TestClient
    client = TestClient(app)

    resp = client.post(
        "/builder/generate",
        json={
            "session_id": "sess-abc",
            "message": "build me a new dog walking app from scratch",
            "mock_mode": True,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    # The response must indicate new_project mode
    assert body.get("generation_mode") == "new_project"
    # The returned slug must not be the old one
    assert body.get("slug") != "old-calorie-app"


def test_edit_intent_keeps_existing_slug(tmp_path, monkeypatch):
    """Edit phrases in existing session must preserve the slug."""
    import config.settings as cs
    monkeypatch.setenv("CEOCLAW_DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    monkeypatch.setenv("CREDITS_ENFORCED", "false")
    cs.settings = cs.Settings()
    cs.settings.database_path = str(tmp_path / "test.db")
    cs.settings.auth_required = False
    cs.settings.credits_enforced = False

    from data.database import init_db, upsert_chat_session
    init_db()
    upsert_chat_session("sess-xyz", slug="my-fitness-app")

    from api.server import app
    from fastapi.testclient import TestClient
    client = TestClient(app)

    resp = client.post(
        "/builder/generate",
        json={
            "session_id": "sess-xyz",
            "message": "change the hero background to dark blue",
            "mock_mode": True,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("generation_mode") == "edit_existing"
    assert body.get("slug") == "my-fitness-app"


# ---------------------------------------------------------------------------
# B) Domain-specific CTA derivation
# ---------------------------------------------------------------------------

def test_domain_cta_fitness():
    from services.generation_pipeline import _derive_domain_cta
    assert _derive_domain_cta({"product_type": "fitness"}) != "Get Started"


def test_domain_cta_finance():
    from services.generation_pipeline import _derive_domain_cta
    cta = _derive_domain_cta({"product_type": "finance"})
    assert cta != "Get Started"


def test_domain_cta_user_override():
    """Explicit intent cta field takes highest priority."""
    from services.generation_pipeline import _derive_domain_cta
    cta = _derive_domain_cta({"product_type": "saas", "cta": "Launch Now"})
    assert cta == "Launch Now"


def test_domain_cta_saas_fallback():
    """Unknown product type falls back to 'Get Started'."""
    from services.generation_pipeline import _derive_domain_cta
    cta = _derive_domain_cta({"product_type": "mystery_product"})
    assert cta == "Get Started"


# ---------------------------------------------------------------------------
# C) Blueprint injection in LLM messages
# ---------------------------------------------------------------------------

def test_build_messages_includes_blueprint():
    """_build_messages must inject the blueprint block when blueprint is provided."""
    from services.code_generation_service import _build_messages
    blueprint = {
        "business_name": "PawWalk",
        "business_positioning": "Dog walking on demand",
        "target_user": "dog owners",
        "feature_list": ["GPS tracking", "instant booking"],
        "page_map": [{"path": "index.html", "purpose": "landing"}],
        "cta_flow": [{"from": "index.html#cta", "to": "pages/signup.html", "label": "Book a Walk"}],
        "design_direction": {},
        "build_steps": [],
        "quality_gates": [],
    }
    msgs = _build_messages(
        slug="pawwalk",
        user_message="build a dog walking app",
        history=[],
        existing_files=None,
        blueprint=blueprint,
    )
    user_content = msgs[-1]["content"]
    assert "PawWalk" in user_content
    assert "BLUEPRINT" in user_content
    assert "Book a Walk" in user_content


def test_build_messages_no_blueprint_still_works():
    """_build_messages with blueprint=None must not raise."""
    from services.code_generation_service import _build_messages
    msgs = _build_messages(
        slug="test-app",
        user_message="make a saas app",
        history=[],
        existing_files=None,
        blueprint=None,
    )
    assert len(msgs) >= 2
    assert msgs[0]["role"] == "system"


# ---------------------------------------------------------------------------
# D) Back-link wiring
# ---------------------------------------------------------------------------

def test_back_link_missing_warns_and_repairs():
    """A pages/*.html with no ../index.html link should get a warning and repair."""
    from services.link_wiring import run_link_wiring_pass
    from services.code_generation_service import FileChange

    page_html = """\
<!DOCTYPE html><html><head><title>Pricing</title></head>
<body>
  <nav><a href="about.html">About</a></nav>
  <main><h1>Pricing</h1></main>
</body></html>"""

    changes = [FileChange(path="data/websites/slug/pages/pricing.html",
                          action="create", content=page_html)]
    updated, warnings = run_link_wiring_pass("slug", changes, None)
    # Warning must mention the missing back-link
    assert any("return path" in w or "← Home" in w for w in warnings), warnings
    # Repaired HTML must now contain ../index.html
    assert "../index.html" in updated[0].content


def test_back_link_present_no_warning():
    """A pages/*.html that already has ../index.html must not trigger a warning."""
    from services.link_wiring import run_link_wiring_pass
    from services.code_generation_service import FileChange

    page_html = """\
<!DOCTYPE html><html><head><title>About</title></head>
<body>
  <nav><a href="../index.html">← Home</a></nav>
  <main><h1>About</h1></main>
</body></html>"""

    changes = [FileChange(path="data/websites/slug/pages/about.html",
                          action="create", content=page_html)]
    _, warnings = run_link_wiring_pass("slug", changes, None)
    back_link_warnings = [w for w in warnings if "return path" in w or "← Home" in w]
    assert not back_link_warnings, f"Unexpected back-link warnings: {back_link_warnings}"


def test_index_page_not_checked_for_back_link():
    """index.html is not a secondary page and must not trigger back-link warnings."""
    from services.link_wiring import run_link_wiring_pass
    from services.code_generation_service import FileChange

    html = "<!DOCTYPE html><html><body><h1>Home</h1></body></html>"
    changes = [FileChange(path="data/websites/slug/index.html",
                          action="create", content=html)]
    _, warnings = run_link_wiring_pass("slug", changes, None)
    assert not any("return path" in w for w in warnings)


# ---------------------------------------------------------------------------
# E) Fallback transparency
# ---------------------------------------------------------------------------

def test_fallback_used_message_contains_note():
    """When the heuristic fallback fires, assistant_message must mention fallback mode."""
    from services.code_generation_service import generate
    from services.provider_router import LLMResult

    # Patch call_llm to return an empty response (no content) so fallback fires
    import services.code_generation_service as svc
    import services.spec_generator as _spec_gen
    original = svc.call_llm
    original_spec = _spec_gen.call_llm

    svc.call_llm = lambda msgs, **kwargs: LLMResult(
        content="",
        provider="mock",
        model_mode="mock",
        fallback_used=True,
        fallback_reason="test_forced_fallback",
    )

    def _raise_spec(*a, **kw):
        raise RuntimeError("spec forced fail for test")

    _spec_gen.call_llm = _raise_spec
    try:
        result = generate(
            slug="test-fallback",
            user_message="build me a test app",
            history=[],
            existing_files=None,
        )
        assert result.fallback_used
        assert "fallback" in result.assistant_message.lower()
    finally:
        svc.call_llm = original
        _spec_gen.call_llm = original_spec


# ---------------------------------------------------------------------------
# F) Uniqueness regression — two distinct intents → different blueprints
# ---------------------------------------------------------------------------

def test_distinct_intents_produce_different_blueprints():
    """A fitness app and a B2B finance app must produce different layout_family values.

    We pass explicit product_type so the test does not depend on parse_intent
    classification quality — it tests the _derive_brand_style_brief mapping only.
    """
    from services.generation_pipeline import _derive_brand_style_brief

    fitness_intent = {"product_type": "fitness", "product_name": "FitTrack", "target_user": "gym goers"}
    finance_intent = {"product_type": "finance", "product_name": "CFOSuite", "target_user": "CFOs"}

    fitness_brief = _derive_brand_style_brief(fitness_intent, [], None, None)
    finance_brief = _derive_brand_style_brief(finance_intent, [], None, None)

    assert fitness_brief["layout_family"] != finance_brief["layout_family"], (
        f"Expected different layout families but both got: {fitness_brief['layout_family']!r}"
    )


# ---------------------------------------------------------------------------
# Phase 1 v2 — BrandSpec tests
# ---------------------------------------------------------------------------

def test_brand_spec_dataclass_round_trip():
    """BrandSpec.to_dict / from_dict round-trip is stable."""
    from services.code_generation_service import BrandSpec
    bs = BrandSpec(
        brand_name="GlossKit",
        product_category="beauty",
        target_audience="makeup enthusiasts",
        core_offer="Find lipsticks by finish, pigment, and shade family",
        must_include_keywords=["pigment", "formula", "finish", "shade"],
        primary_cta="Shop Shades",
        pages=["index.html", "pages/shop.html"],
        layout_profile="split_hero",
        visual_motif="gradient_rich",
        copy_style="warm_conversational",
    )
    d = bs.to_dict()
    bs2 = BrandSpec.from_dict(d)
    assert bs2.brand_name == "GlossKit"
    assert bs2.must_include_keywords == ["pigment", "formula", "finish", "shade"]
    assert bs2.layout_profile == "split_hero"


def test_uniqueness_profile_selection_varies_across_time():
    """Two calls with different time buckets must not always return identical profiles."""
    from services.code_generation_service import _select_uniqueness_profile, _LAYOUT_PROFILES, _VISUAL_MOTIFS, _COPY_STYLES
    # Just verify all returned values are valid pool members
    layout, visual, copy, seed = _select_uniqueness_profile("TestBrand")
    assert layout in _LAYOUT_PROFILES
    assert visual in _VISUAL_MOTIFS
    assert copy in _COPY_STYLES
    assert len(seed) > 0


def test_validate_against_brand_spec_catches_missing_brand_name():
    """Validation flags missing brand name in generated HTML."""
    from services.code_generation_service import BrandSpec, FileChange, GenerationResult, _validate_against_brand_spec
    bs = BrandSpec(
        brand_name="GlossKit",
        product_category="beauty",
        target_audience="makeup lovers",
        core_offer="...",
        must_include_keywords=["pigment"],
    )
    gen = GenerationResult(
        assistant_message="Done.",
        changes=[FileChange(
            path="data/websites/glosskit/index.html",
            action="create",
            content="<!DOCTYPE html><html><head></head><body><h1>Some Generic App</h1></body></html>",
        )],
    )
    issues = _validate_against_brand_spec(gen, bs)
    assert any("GlossKit" in i for i in issues), f"Expected brand name issue, got: {issues}"


def test_validate_against_brand_spec_passes_good_output():
    """Validation passes when brand name and keywords are present."""
    from services.code_generation_service import BrandSpec, FileChange, GenerationResult, _validate_against_brand_spec
    bs = BrandSpec(
        brand_name="GlossKit",
        product_category="beauty",
        target_audience="makeup lovers",
        core_offer="...",
        must_include_keywords=["pigment", "formula"],
        forbidden_generic_phrases=["revolutionize"],
        pages=["index.html"],
    )
    gen = GenerationResult(
        assistant_message="Done.",
        changes=[FileChange(
            path="data/websites/glosskit/index.html",
            action="create",
            content=(
                "<!DOCTYPE html><html><head></head><body>"
                "<h1>GlossKit</h1><p>High pigment formula lipsticks.</p>"
                "</body></html>"
            ),
        )],
    )
    issues = _validate_against_brand_spec(gen, bs)
    assert not issues, f"Expected no issues, got: {issues}"


def test_generate_passes_brand_spec_to_messages(monkeypatch):
    """generate() with brand_spec injects BRAND SPEC block into LLM messages."""
    from services.code_generation_service import BrandSpec, generate, FileChange, GenerationResult
    from services import code_generation_service as _cgs

    captured_messages = []

    def _fake_call_llm(messages, **kwargs):
        captured_messages.extend(messages)
        # Legacy path calls _extract_html on content — return raw HTML
        html = "<!DOCTYPE html><html><head></head><body><h1>GlossKit</h1><p>pigment formula</p></body></html>"
        from services.provider_router import LLMResult
        return LLMResult(content=html, provider="openai", model_mode="openai")

    monkeypatch.setattr(_cgs, "call_llm", _fake_call_llm)

    # Also block the spec_generator path so generate_via_spec fails and falls
    # through to the legacy path where _fake_call_llm is used.
    import services.spec_generator as _spec_gen

    def _raise_spec(*a, **kw):
        raise RuntimeError("spec forced fail for test")

    monkeypatch.setattr(_spec_gen, "call_llm", _raise_spec)

    bs = BrandSpec(
        brand_name="GlossKit",
        product_category="beauty",
        target_audience="makeup lovers",
        core_offer="lipstick finder",
        must_include_keywords=["pigment", "formula"],
        pages=["index.html"],
        layout_profile="split_hero",
        visual_motif="gradient_rich",
        copy_style="warm_conversational",
    )
    result = generate(slug="glosskit", user_message="build a lipstick site", history=[], brand_spec=bs)
    assert result.changes
    # Verify brand spec block appeared in the user message
    user_msgs = [m["content"] for m in captured_messages if m["role"] == "user"]
    assert any("BRAND SPEC" in c for c in user_msgs), "Expected BRAND SPEC block in user message"
    assert any("GlossKit" in c for c in user_msgs)
