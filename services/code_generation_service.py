"""
LLM code generation service — simplified per-file pipeline.

Flow:
  1. synthesize_brand_spec() — Call 1: extract brand/product info from user message
  2. generate()             — Call 2+: generate each page as a separate LLM call
  3. generate_edit()        — Edit path: modify a single file via focused prompt

Each LLM call asks for raw HTML output (no JSON wrapping), which eliminates
the #1 parsing failure mode of the old system.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

from services.provider_router import LLMResult, call_llm

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures (unchanged — public API contract)
# ---------------------------------------------------------------------------

@dataclass
class FileChange:
    path: str
    action: str              # "create" | "update"
    content: str | bytes
    summary: str = ""


@dataclass
class GenerationResult:
    assistant_message: str
    changes: list[FileChange]
    preview_route: str = ""
    preview_notes: list[str] = field(default_factory=list)
    provider: str = "openai"
    model_mode: str = "openai"
    warnings: list[str] = field(default_factory=list)
    raw_llm_content: str = ""
    fallback_used: bool = False
    fallback_reason: str = ""
    operation_type: str = ""
    route_graph: dict = field(default_factory=dict)
    layout_plan: dict = field(default_factory=dict)
    blueprint: dict = field(default_factory=dict)
    consistency_profile_id: str = ""


# ---------------------------------------------------------------------------
# BrandSpec
# ---------------------------------------------------------------------------

@dataclass
class BrandSpec:
    """Structured brand specification derived from user message."""
    brand_name: str
    product_category: str
    target_audience: str
    core_offer: str
    differentiators: list[str] = field(default_factory=list)
    tone: str = "professional"
    required_sections: list[str] = field(default_factory=list)
    must_include_keywords: list[str] = field(default_factory=list)
    forbidden_generic_phrases: list[str] = field(default_factory=list)
    visual_direction: str = ""
    interaction_direction: str = ""
    primary_cta: str = "Get Started"
    pages: list[str] = field(default_factory=list)
    layout_profile: str = ""
    visual_motif: str = ""
    copy_style: str = ""
    uniqueness_seed: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "BrandSpec":
        known = {f.name for f in BrandSpec.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return BrandSpec(**{k: v for k, v in d.items() if k in known})


# Uniqueness pools
_LAYOUT_PROFILES = [
    "wide_hero_centered", "split_hero", "editorial_bold",
    "bento_grid", "scroll_story",
]
_VISUAL_MOTIFS = [
    "glass_morphism", "flat_outlined", "gradient_rich",
    "mono_accent", "organic_soft",
]
_COPY_STYLES = [
    "punchy_direct", "warm_conversational", "technical_precise",
    "bold_declarative", "storytelling",
]


def _select_uniqueness_profile(brand_name: str) -> tuple[str, str, str, str]:
    name_hash = int(hashlib.md5(brand_name.encode()).hexdigest()[:8], 16)
    time_bucket = int(time.time()) // 300
    combined = name_hash ^ time_bucket
    layout = _LAYOUT_PROFILES[combined % len(_LAYOUT_PROFILES)]
    visual = _VISUAL_MOTIFS[(combined // len(_LAYOUT_PROFILES)) % len(_VISUAL_MOTIFS)]
    copy = _COPY_STYLES[(combined // (len(_LAYOUT_PROFILES) * len(_VISUAL_MOTIFS))) % len(_COPY_STYLES)]
    return layout, visual, copy, f"{combined:x}"


# ---------------------------------------------------------------------------
# BrandSpec synthesis (Call 1) — kept from original
# ---------------------------------------------------------------------------

_BRAND_SPEC_SYSTEM_PROMPT = """\
You are a brand strategist specialising in tech products and SaaS.
Your job: read the user's product description and extract a precise BrandSpec JSON.

Return ONLY valid JSON — no markdown fences, no preamble, no trailing text.

Schema (every key required):
{
  "brand_name": "The product name exactly as the user stated it",
  "product_category": "One of: ecommerce, beauty, fitness, finance, devtools, edtech, \
marketplace, consumer_app, saas_b2b, saas_b2c, healthcare, food, travel, social, other",
  "target_audience": "One specific sentence: who are the users, what situation they are in",
  "core_offer": "One sentence: what the product does and the primary outcome it delivers",
  "differentiators": ["3-5 specific things that make this product unique"],
  "tone": "One of: warm, playful, professional, authoritative, edgy, technical, luxurious",
  "required_sections": ["hero", "features", "..."],
  "must_include_keywords": ["5-8 domain-specific words/phrases that MUST appear in the copy"],
  "forbidden_generic_phrases": ["revolutionize", "game-changer", "seamlessly", "cutting-edge", \
"next-level", "supercharge", "unlock your potential"],
  "visual_direction": "One sentence describing the right visual feel",
  "interaction_direction": "One sentence on interaction feel",
  "primary_cta": "The most fitting CTA verb phrase for this product",
  "pages": ["index.html", "pages/signup.html", "app.html"]
}

Rules:
- brand_name: use the exact name from the user message; do NOT invent a new name
- product_category: pick the single closest match
- must_include_keywords: pick real domain words, NOT generic "product", "solution", "platform"
- pages: adjust to fit the product category
"""


def synthesize_brand_spec(
    message: str,
    history: list[dict],
    slug: str,
    design_system: dict | None = None,
) -> BrandSpec:
    """Call 1: synthesise a structured BrandSpec from the user's message."""
    from core.intent_parser import parse_intent

    try:
        messages: list[dict] = [{"role": "system", "content": _BRAND_SPEC_SYSTEM_PROMPT}]
        for msg in history[-6:]:
            content = msg.get("content", "")
            if msg.get("role") == "assistant" and len(content) > 200:
                content = content[:200] + "\n[...]"
            messages.append({"role": msg["role"], "content": content})
        messages.append({"role": "user", "content": (
            f"Product slug: {slug}\n\nUser description:\n{message}\n\n"
            "Extract the BrandSpec JSON now."
        )})

        llm_result = call_llm(messages, max_tokens=1200)
        if llm_result.content:
            parsed = _parse_response(llm_result.content)
            if parsed and parsed.get("brand_name"):
                brand_name = parsed["brand_name"]
                layout, visual, copy, seed = _select_uniqueness_profile(brand_name)
                return BrandSpec(
                    brand_name=brand_name,
                    product_category=parsed.get("product_category", "saas_b2c"),
                    target_audience=parsed.get("target_audience", ""),
                    core_offer=parsed.get("core_offer", ""),
                    differentiators=parsed.get("differentiators") or [],
                    tone=parsed.get("tone", "professional"),
                    required_sections=parsed.get("required_sections") or ["hero", "features", "pricing", "footer"],
                    must_include_keywords=parsed.get("must_include_keywords") or [],
                    forbidden_generic_phrases=parsed.get("forbidden_generic_phrases") or [
                        "revolutionize", "game-changer", "seamlessly", "cutting-edge", "next-level",
                    ],
                    visual_direction=parsed.get("visual_direction", ""),
                    interaction_direction=parsed.get("interaction_direction", ""),
                    primary_cta=parsed.get("primary_cta", "Get Started"),
                    pages=parsed.get("pages") or ["index.html", "pages/signup.html", "app.html"],
                    layout_profile=layout, visual_motif=visual,
                    copy_style=copy, uniqueness_seed=seed,
                )
    except Exception as exc:
        logger.warning("BrandSpec synthesis LLM call failed: %s", exc)

    # Heuristic fallback
    logger.info("Falling back to heuristic BrandSpec for slug=%r", slug)
    intent = parse_intent(message)
    brand_name = intent.get("product_name") or slug.replace("-", " ").title()
    layout, visual, copy, seed = _select_uniqueness_profile(brand_name)
    return BrandSpec(
        brand_name=brand_name,
        product_category=intent.get("product_type") or "saas_b2c",
        target_audience=intent.get("target_user") or "teams and individuals",
        core_offer=f"{brand_name} — a {intent.get('product_type', 'product')} for {intent.get('target_user', 'users')}",
        differentiators=intent.get("core_features") or [],
        tone="professional",
        required_sections=["hero", "features", "pricing", "footer"],
        must_include_keywords=intent.get("core_features") or [],
        forbidden_generic_phrases=[
            "revolutionize", "game-changer", "seamlessly", "cutting-edge",
            "next-level", "supercharge", "unlock your potential",
        ],
        primary_cta=intent.get("cta") or "Get Started",
        pages=["index.html", "pages/signup.html", "app.html"],
        layout_profile=layout, visual_motif=visual,
        copy_style=copy, uniqueness_seed=seed,
    )


# ---------------------------------------------------------------------------
# Per-file generation prompt (replaces the 500-line system prompt)
# ---------------------------------------------------------------------------

_PAGE_SYSTEM_PROMPT = """\
You are a senior web developer. You generate complete, production-quality HTML pages.

RULES:
- Return ONLY the raw HTML file — from <!DOCTYPE html> to </html>
- No markdown fences, no commentary, no JSON wrapping
- All colors via CSS custom properties in a :root block (use the provided design tokens exactly)
- Google Fonts via @import in <style>
- Responsive: viewport meta, clamp() spacing, @media breakpoints at 1024px and 640px
- Fluid grid: repeat(auto-fit, minmax(min(100%, 280px), 1fr))
- All buttons: min-height 44px, hover/active transitions
- Reveal-on-scroll: .reveal class + IntersectionObserver JS
- Sticky navbar: .scrolled class on scroll > 14px
- All internal links use RELATIVE paths (href="pages/signup.html", not "/signup")
- From pages/* back to root: href="../index.html"
- No lorem ipsum. All copy must be specific to the product domain.
- No external JS dependencies. Vanilla JS only.

LAYOUT CONSTRAINTS:
- Hero section: min-height: 480px; max-height: 700px (never full-viewport-height)
- Hero headline: font-size: clamp(2rem, 5vw, 3.5rem) — no larger
- Hero subheadline: font-size: clamp(1rem, 2.5vw, 1.25rem)
- Content sections: max-width: 1100px; margin: 0 auto; padding: 0 clamp(1rem, 4vw, 2rem)
- Section vertical padding: clamp(3rem, 6vw, 5rem) top/bottom
- Feature grid: max 3 columns on desktop, 1 on mobile
- Body copy: font-size: clamp(0.9rem, 1.5vw, 1rem); line-height: 1.6

IMAGE ASSETS:
- The user prompt lists AVAILABLE IMAGE ASSETS with exact file paths.
- Use ONLY paths from that list — do NOT invent or change file extensions.
- Hero image: <img src="[exact path]" alt="..." class="hero-img" style="max-width:100%;height:auto;">
- Feature icons: <img src="[exact path]" alt="..." style="width:48px;height:48px;">
- Always include descriptive alt text on every image.
- Never leave a listed asset unreferenced in the HTML.
"""

# ---------------------------------------------------------------------------
# Extended system prompt base with all contracts (used by tests and _build_system_prompt)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_BASE = _PAGE_SYSTEM_PROMPT + """
GENERATED ASSET PLACEMENT CONTRACT:
- All generated image assets MUST be referenced in the HTML via <img> tags.
- Hero image path: assets/hero.svg (or the exact path from the asset list)
- Feature icon paths: assets/icon-N.svg (N = 1, 2, 3...)
- Never inline SVG content — always use <img src="assets/...">
- Every listed asset must appear at least once in the HTML output.

DESIGN TOKEN & VISUAL RHYTHM CONTRACT:
- All colors must be defined as CSS custom properties in :root: --color-bg, --color-surface,
  --color-text, --color-muted, --color-primary, --color-primary-dark, --color-border
- All buttons must use class btn-primary or btn-secondary (defined in :root or global styles)
- Never use hard-coded hex values outside :root

MULTI-PAGE CONTRACT:
- All internal navigation must use relative paths (href="pages/signup.html" not "/signup")
- From pages/* back to root: href="../index.html"
- The site must include pages/signup.html as the primary conversion page
- Pricing section links must point to pages/pricing.html when a pricing page exists

DYNAMIC COMPONENTS CONTRACT:
- Testimonial carousel: use a CSS-only or minimal-JS carousel (class="carousel")
- Reveal-on-scroll: add class="reveal" + IntersectionObserver script
- prefers-reduced-motion: wrap all transitions in @media (prefers-reduced-motion: no-preference)
- Sticky navbar: add .scrolled class on scroll > 14px via JS

SPACING & GUTTER CONTRACT:
- All horizontal centering: margin-inline: auto
- Container max-width: max-width: clamp(320px, 90vw, 1200px)
- Section vertical rhythm: padding-block: clamp(3rem, 6vw, 5rem)
- Button touch targets: min-height: 44px
- Fluid typography: font-size: clamp(min, preferred, max)

FRAMER AURA GENERATION CONTRACT:
- Primary palette: #3b82f6 (blue), #8b5cf6 (purple), #ec4899 (pink)
- Background gradient: linear-gradient(135deg, #3b82f6, #8b5cf6, #ec4899)
- Use glass morphism cards: backdrop-filter: blur(12px); background: rgba(255,255,255,0.1)
- Motion: reveal_scroll, hover_lift, sticky_nav

INFORMATION ARCHITECTURE:
- Landing page: index.html (hero, features, testimonials, pricing, CTA, footer)
- Conversion page: pages/signup.html (signup form)
- App entry: app.html (dashboard)
- Pricing: pages/pricing.html

TIER-AWARE PRICING:
- Always include 3 pricing tiers: Free, Pro, Enterprise
- Each tier must have a feature list and a CTA button linking to pages/signup.html
- Highlight the Pro tier as "Most Popular"

layout_plan: When generating a multi-page site, include a JSON comment at the end
<!-- layout_plan: {"layout_family": "saas", "page_map": [...], "section_order": [...]} -->
"""

# ---------------------------------------------------------------------------
# Layout family section definitions
# ---------------------------------------------------------------------------

_LAYOUT_FAMILY_SECTIONS: dict[str, list[str]] = {
    "saas": ["hero", "features", "testimonials", "pricing", "cta", "footer"],
    "enterprise": ["hero", "trust_logos", "features", "case_studies", "pricing", "cta", "footer"],
    "wellness": ["hero", "benefits", "how_it_works", "testimonials", "pricing", "cta", "footer"],
    "developer": ["hero", "code_demo", "features", "integrations", "pricing", "cta", "footer"],
    "marketplace": ["hero", "categories", "featured_listings", "how_it_works", "testimonials", "cta", "footer"],
    "education": ["hero", "course_overview", "curriculum", "instructor", "testimonials", "pricing", "cta", "footer"],
    "consumer": ["hero", "features", "social_proof", "how_it_works", "testimonials", "cta", "footer"],
}


def _build_section_mandate(layout_family: str) -> str:
    """Build a section mandate string for the given layout family."""
    sections = _LAYOUT_FAMILY_SECTIONS.get(layout_family, _LAYOUT_FAMILY_SECTIONS["saas"])
    section_list = "\n".join(f"  {i + 1}. {s}" for i, s in enumerate(sections))
    return (
        f"MANDATORY LANDING PAGE SECTIONS for {layout_family} layout "
        f"(all {len(sections)} required):\n{section_list}"
    )


def _build_system_prompt(style_seed: dict | None = None) -> str:
    """Build the full system prompt, injecting layout-family section mandate."""
    layout_family = (style_seed or {}).get("layout_family", "saas")
    mandate = _build_section_mandate(layout_family)
    return _SYSTEM_PROMPT_BASE + "\n\n" + mandate + "\n"


def _build_messages(
    slug: str,
    user_message: str,
    history: list[dict],
    existing_files: dict[str, str] | None,
    blueprint: dict | None = None,
) -> list[dict]:
    """Build the LLM messages list for code generation.

    Returns a list of message dicts with role/content. The system prompt is
    always first. If blueprint is provided, it is injected as a BLUEPRINT block
    in the user message.
    """
    system_prompt = _build_system_prompt()
    messages: list[dict] = [{"role": "system", "content": system_prompt}]

    # Include recent conversation history (last 6 turns)
    for msg in (history or [])[-6:]:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "assistant" and len(content) > 300:
            content = content[:300] + "\n[...]"
        messages.append({"role": role, "content": content})

    # Build user message with optional blueprint injection
    user_content = user_message
    if blueprint:
        bp_json = json.dumps(blueprint, indent=2)
        user_content = (
            f"BLUEPRINT:\n{bp_json}\n\n"
            f"Project slug: {slug}\n\n"
            f"{user_message}"
        )
    elif slug:
        user_content = f"Project slug: {slug}\n\n{user_message}"

    # Add existing files context if editing
    if existing_files:
        file_summary = "\n".join(
            f"  - {path}: {len(content)} chars"
            for path, content in list(existing_files.items())[:10]
        )
        user_content += f"\n\nEXISTING FILES:\n{file_summary}"

    messages.append({"role": "user", "content": user_content})
    return messages


def _validate_against_brand_spec(gen: "GenerationResult", brand_spec: "BrandSpec") -> list[str]:
    """Validate generated HTML changes against the brand spec.

    Returns a list of issue strings. Empty list means validation passed.
    """
    issues: list[str] = []
    html_changes = [c for c in gen.changes if c.path.endswith(".html") and isinstance(c.content, str)]

    if not html_changes:
        return issues

    # Combine all HTML content for validation
    combined_html = " ".join(c.content for c in html_changes)

    # Check brand name presence
    if brand_spec.brand_name and brand_spec.brand_name not in combined_html:
        issues.append(f"Brand name '{brand_spec.brand_name}' not found in generated HTML")

    # Check required keywords
    for keyword in (brand_spec.must_include_keywords or []):
        if keyword and keyword.lower() not in combined_html.lower():
            issues.append(f"Required keyword '{keyword}' missing from generated HTML")

    return issues


def _build_page_prompt(
    page_path: str,
    brand_spec: BrandSpec,
    design_system: dict | None,
    all_pages: list[str],
    available_assets: list[str] | None = None,
) -> str:
    """Build a focused prompt for generating one specific page."""
    from services.design_system_service import DesignSystem

    ds = DesignSystem.from_dict(design_system) if design_system else DesignSystem.generate_aura()
    css_vars = ds.to_css_vars()
    font_import = (
        f"https://fonts.googleapis.com/css2?family={ds.display_font.replace(' ', '+')}:wght@300;400;600;700"
        f"&family={ds.body_font.replace(' ', '+')}:wght@300;400;500;600&display=swap"
    )

    nav_links = ", ".join(all_pages)
    keywords = ", ".join(brand_spec.must_include_keywords[:6]) if brand_spec.must_include_keywords else "N/A"

    page_type_guidance = _get_page_guidance(page_path, brand_spec)

    asset_block = ""
    if available_assets:
        asset_list = "\n".join(f"  - {a}" for a in sorted(available_assets))
        asset_block = f"""
AVAILABLE IMAGE ASSETS (reference these EXACT paths in your HTML):
{asset_list}
Use <img src="EXACT_PATH_FROM_LIST_ABOVE"> — do NOT change the file extension."""

    return f"""\
Generate the complete HTML file for: {page_path}

PRODUCT: {brand_spec.brand_name}
Category: {brand_spec.product_category}
Audience: {brand_spec.target_audience}
Core offer: {brand_spec.core_offer}
Tone: {brand_spec.tone}
Primary CTA: "{brand_spec.primary_cta}"
Domain keywords (use naturally in copy): {keywords}
Layout style: {brand_spec.layout_profile}
Visual style: {brand_spec.visual_motif}
Copy style: {brand_spec.copy_style}

DESIGN TOKENS (use these EXACTLY in your :root block):
{css_vars}

Font import URL: {font_import}

ALL PAGES IN THIS SITE (wire navigation to all of them): {nav_links}
{asset_block}

{page_type_guidance}

Return the complete HTML file now. Raw HTML only, no wrapping."""


def _get_page_guidance(page_path: str, brand_spec: BrandSpec) -> str:
    """Return page-type-specific generation guidance."""
    sections = ", ".join(brand_spec.required_sections) if brand_spec.required_sections else "hero, features, pricing, footer"

    if page_path == "index.html":
        return f"""\
PAGE TYPE: Landing page (index.html)
Required sections: {sections}
- Sticky translucent navbar with brand name, nav links to all pages, and primary CTA button
- Hero section with display-font heading, specific subheading about the product, dual CTAs
- Features section with 3-5 cards (icon + title + description specific to this product)
- Social proof / testimonials (3 quotes referencing this product's domain)
- Pricing section with 3 tiers (Free / Pro / Enterprise)
- Pre-footer CTA section
- Footer with brand, nav links, copyright
- Primary CTA links to pages/signup.html"""

    if "signup" in page_path:
        return """\
PAGE TYPE: Signup page
- Centered card layout, minimal design
- Brand name at top
- Form: full name, email, password fields with labels and aria-labels
- Submit button with the primary CTA text
- Client-side validation (required fields, email format, password min 8 chars)
- Link back to ../index.html ("Already have an account? Sign in")
- Form action submits to ../app.html"""

    if page_path == "app.html":
        return f"""\
PAGE TYPE: App dashboard
- Sidebar with brand name, nav links (Dashboard, Features, Settings, Back to site)
- Main content area with welcome heading
- Metrics row: 4 metric cards (domain-specific to {brand_spec.product_category})
- Feature list card showing platform capabilities
- "Connect your API" card with token input field
- Sidebar collapses on mobile (hidden below 640px)"""

    if "pricing" in page_path:
        return """\
PAGE TYPE: Pricing page
- Navbar consistent with index.html
- 3-tier pricing cards (Free / Pro / Enterprise)
- Feature comparison for each tier
- Primary CTA buttons linking to pages/signup.html
- Footer consistent with index.html"""

    return f"""\
PAGE TYPE: {page_path}
- Navbar consistent with index.html (same nav links)
- Content appropriate for this page type
- Footer consistent with index.html
- All links use relative paths"""


# ---------------------------------------------------------------------------
# Edit prompt (for modifying existing files)
# ---------------------------------------------------------------------------

_EDIT_SYSTEM_PROMPT = """\
You are a senior web developer. You modify existing HTML files based on user requests.

RULES:
- Return ONLY the complete modified HTML file — from <!DOCTYPE html> to </html>
- No markdown fences, no commentary, no JSON wrapping
- Apply EXACTLY what was requested — no more, no less
- NEVER remove or rewrite sections not mentioned in the request
- For color changes: update :root custom properties only
- For font changes: update :root --font-display/--font-body AND the @import URL
- For adding sections: insert at the natural document position
- Preserve ALL existing content, styles, and functionality not being changed
"""


# ---------------------------------------------------------------------------
# Direct CSS edits (no LLM needed)
# ---------------------------------------------------------------------------

_COLOR_NAMES: dict[str, str] = {
    "red": "#ef4444", "blue": "#3b82f6", "green": "#10b981", "purple": "#8b5cf6",
    "pink": "#ec4899", "orange": "#f97316", "yellow": "#eab308", "teal": "#14b8a6",
    "cyan": "#06b6d4", "indigo": "#6366f1", "violet": "#7c3aed", "rose": "#f43f5e",
    "emerald": "#10b981", "amber": "#f59e0b", "lime": "#84cc16", "sky": "#0ea5e9",
    "slate": "#64748b", "gray": "#6b7280", "grey": "#6b7280", "zinc": "#71717a",
    "stone": "#78716c", "neutral": "#737373",
    "dark blue": "#1e3a5f", "dark green": "#064e3b", "dark red": "#7f1d1d",
    "dark purple": "#4c1d95", "light blue": "#93c5fd", "light green": "#86efac",
    "navy": "#1e3a5f", "black": "#0a0a0a", "white": "#ffffff",
}

_HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}")


def try_direct_css_edit(html: str, message: str) -> str | None:
    """Attempt a direct regex-based CSS edit. Returns modified HTML or None if not applicable."""
    msg_lower = message.lower().strip()

    # --- Color change ---
    color_match = re.search(
        r"(?:change|set|make|update)\s+(?:the\s+)?(?:primary\s+)?(?:color|colour)\s+(?:to\s+)?(.+)",
        msg_lower,
    )
    if color_match:
        target_color = color_match.group(1).strip().rstrip(".")
        hex_val = _resolve_color(target_color)
        if hex_val:
            return _replace_css_var(html, "--color-primary", hex_val)

    # --- Background color ---
    bg_match = re.search(
        r"(?:change|set|make|update)\s+(?:the\s+)?(?:background|bg)\s+(?:color\s+)?(?:to\s+)?(.+)",
        msg_lower,
    )
    if bg_match:
        target = bg_match.group(1).strip().rstrip(".")
        hex_val = _resolve_color(target)
        if hex_val:
            return _replace_css_var(html, "--color-bg", hex_val)

    # --- Dark mode ---
    if re.search(r"\bdark\s*(?:mode|theme)\b", msg_lower) or (
        re.search(r"\bmake\b.*\bdark\b", msg_lower)
    ):
        return _apply_dark_mode(html)

    # --- Light mode ---
    if re.search(r"\blight\s*(?:mode|theme)\b", msg_lower) or (
        re.search(r"\bmake\b.*\blight\b", msg_lower)
    ):
        return _apply_light_mode(html)

    # --- Font change ---
    font_match = re.search(
        r"(?:change|set|use|switch)\s+(?:the\s+)?(?:font|typeface)\s+(?:to\s+)?['\"]?([^'\"]+?)['\"]?\s*$",
        msg_lower,
    )
    if font_match:
        font_name = font_match.group(1).strip().title()
        return _replace_font(html, font_name)

    # --- Generic "make it <color>" / "make the website <color> [now]" ---
    if re.search(r"\b(?:make|turn)\b", msg_lower):
        stripped = re.sub(r"\s*(?:now|please|!|\.)+\s*$", "", msg_lower).strip()
        words = stripped.split()
        for n in (2, 1):
            if len(words) >= n:
                candidate = " ".join(words[-n:])
                hex_val = _resolve_color(candidate)
                if hex_val:
                    return _replace_css_var(html, "--color-primary", hex_val)

    # --- "change/switch [something] to <color>" ---
    to_color_match = re.search(
        r"(?:change|switch)\s+.*?\s+to\s+(\w+(?:\s+\w+)?)\s*(?:now|please|!|\.)*\s*$",
        msg_lower,
    )
    if to_color_match:
        candidate = to_color_match.group(1).strip()
        hex_val = _resolve_color(candidate)
        if hex_val:
            return _replace_css_var(html, "--color-primary", hex_val)

    # --- "change X to Y" pattern ---
    change_match = re.search(
        r"change\s+['\"]?(.+?)['\"]?\s+to\s+['\"]?(.+?)['\"]?\s*$",
        message, re.IGNORECASE,
    )
    if change_match:
        old_t, new_t = change_match.group(1).strip(), change_match.group(2).strip()
        modified = re.sub(re.escape(old_t), new_t, html, count=5, flags=re.IGNORECASE)
        if modified != html:
            return modified

    return None


def _resolve_color(text: str) -> str | None:
    text = text.strip().lower()
    hex_m = _HEX_RE.search(text)
    if hex_m:
        return hex_m.group(0)
    return _COLOR_NAMES.get(text)


def _replace_css_var(html: str, var_name: str, new_value: str) -> str:
    pattern = re.compile(
        rf"({re.escape(var_name)}\s*:\s*)([^;]+)(;)",
        re.IGNORECASE,
    )
    result, count = pattern.subn(rf"\g<1>{new_value}\3", html)
    if count > 0:
        return result
    return html


def _replace_font(html: str, font_name: str) -> str:
    html = _replace_css_var(html, "--font-display", f"'{font_name}', sans-serif")
    old_import = re.search(
        r"(@import\s+url\(['\"])([^'\"]+)(['\"])", html,
    )
    if old_import:
        new_url = re.sub(
            r"family=[^&]+",
            f"family={font_name.replace(' ', '+')}:wght@300;400;600;700",
            old_import.group(2),
            count=1,
        )
        html = html.replace(old_import.group(2), new_url, 1)
    return html


def _apply_dark_mode(html: str) -> str:
    replacements = {
        "--color-bg": "#0f0f14",
        "--color-surface": "#1a1a24",
        "--color-text": "#f0f0f5",
        "--color-muted": "#94a3b8",
        "--color-border": "#2d2d3a",
    }
    for var, val in replacements.items():
        html = _replace_css_var(html, var, val)
    # Fix navbar background for dark
    html = re.sub(
        r"rgba\(248,250,252,[.\d]+\)",
        "rgba(15,15,20,0.85)",
        html,
    )
    return html


def _apply_light_mode(html: str) -> str:
    replacements = {
        "--color-bg": "#f8fafc",
        "--color-surface": "#ffffff",
        "--color-text": "#0f172a",
        "--color-muted": "#64748b",
        "--color-border": "#e2e8f0",
    }
    for var, val in replacements.items():
        html = _replace_css_var(html, var, val)
    html = re.sub(
        r"rgba\(15,15,20,[.\d]+\)",
        "rgba(248,250,252,0.85)",
        html,
    )
    return html


def _is_sitewide_style_change(message: str) -> bool:
    """Return True if the change should apply to all pages (color, theme, font)."""
    msg = message.lower().strip()
    if re.search(r"\b(?:color|colour|theme|dark\s*mode|light\s*mode|font|typeface)\b", msg):
        return True
    if re.search(r"\b(?:make|turn)\b.*\b(?:dark|light)\b", msg):
        return True
    stripped = re.sub(r"\s*(?:now|please|!|\.)+\s*$", "", msg).strip()
    words = stripped.split()
    if re.search(r"\b(?:make|turn|change|switch)\b", msg) and words:
        for n in (2, 1):
            if len(words) >= n:
                candidate = " ".join(words[-n:])
                if _resolve_color(candidate):
                    return True
    return False


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def _parse_response(content: str) -> dict:
    """Robustly extract JSON from LLM output."""
    text = content.strip()
    text = text.replace("\\'", "'")

    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    md = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if md:
        try:
            return json.loads(md.group(1))
        except json.JSONDecodeError:
            pass

    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if brace:
        try:
            return json.loads(brace.group(0))
        except json.JSONDecodeError:
            pass

    if "<!doctype" in text.lower()[:200] or "<html" in text.lower()[:300]:
        return {
            "assistant_message": "Generated website.",
            "changes": [{"path": "index.html", "action": "create",
                          "content": text, "summary": "Raw HTML from model"}],
        }

    logger.warning("Could not parse LLM response (len=%d preview=%r)", len(text), text[:80])
    return {}


def _extract_html(content: str) -> str | None:
    """Extract raw HTML from LLM output, stripping any markdown fences."""
    text = content.strip()

    # Strip markdown code fences if present
    fence_match = re.search(r"```(?:html)?\s*\n?(<!DOCTYPE.*?</html>)\s*```", text, re.DOTALL | re.IGNORECASE)
    if fence_match:
        return fence_match.group(1).strip()

    # Already raw HTML
    if text.lower().startswith("<!doctype") or text.lower().startswith("<html"):
        # Trim any trailing non-HTML
        end = text.rfind("</html>")
        if end != -1:
            return text[:end + 7]
        return text

    return None


# ---------------------------------------------------------------------------
# Public API — generate (new project)
# ---------------------------------------------------------------------------

def generate(
    slug: str,
    user_message: str,
    history: list[dict],
    existing_files: dict[str, str] | None = None,
    style_seed: dict | None = None,
    design_system: dict | None = None,
    operation: dict | None = None,
    blueprint: dict | None = None,
    brand_spec: Optional[BrandSpec] = None,
    available_assets: list[str] | None = None,
    generation_plan_context: Optional[object] = None,
) -> GenerationResult:
    """Generate or edit website files via LLM.

    For new projects (no existing_files): uses spec pipeline (JSON→render).
    For edits (existing_files present): tries spec edit first, then direct CSS, then LLM.
    available_assets: list of asset paths generated (e.g. ["assets/hero.jpg", "assets/icon-1.png"]).
    generation_plan_context: optional GenerationPlanContext from the pipeline build_plan;
        when supplied and ordered_create_targets is non-empty, the legacy per-file loop
        uses that order instead of brand_spec.pages (plan-aware mode).
        Spec-first paths (generate_via_spec / edit_via_spec) are not changed.
    """
    operation_type = (operation or {}).get("type", "")

    # --- EDIT PATH: existing files → spec edit first, then legacy ---
    if existing_files:
        # Try spec-based edit first (deterministic, no content loss)
        try:
            spec_result = edit_via_spec(
                slug=slug,
                user_message=user_message,
                history=history,
                design_system=design_system,
            )
            if spec_result is not None and spec_result.changes:
                spec_result.operation_type = operation_type
                return spec_result
        except Exception as exc:
            logger.warning("Spec-based edit failed, falling back to legacy: %s", exc)

        return _generate_edit(
            slug=slug,
            user_message=user_message,
            history=history,
            existing_files=existing_files,
            design_system=design_system,
            operation=operation,
            brand_spec=brand_spec,
        )

    # --- NEW PROJECT PATH: spec pipeline (JSON → validate → render) ---
    try:
        result = generate_via_spec(
            slug=slug,
            user_message=user_message,
            history=history,
            design_system=design_system,
        )
        if result.changes:
            result.operation_type = operation_type
            return result
    except Exception as exc:
        logger.warning("Spec pipeline failed, falling back to legacy: %s", exc)

    # --- LEGACY FALLBACK: per-file LLM generation ---
    if not brand_spec:
        brand_spec = _minimal_brand_spec(slug, user_message)

    pages = brand_spec.pages or ["index.html", "pages/signup.html", "app.html"]

    # Plan-aware ordering: use scaffold-derived order when available.
    # Excludes binary assets (no HTML generator for those) and only triggers
    # when the context supplies at least one create target.
    _plan_targets = getattr(generation_plan_context, "ordered_create_targets", None)
    if _plan_targets:
        # Filter to HTML/CSS targets only; assets are handled separately
        _html_targets = [
            p for p in _plan_targets
            if not p.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico", ".svg"))
        ]
        if _html_targets:
            logger.info(
                "generate(): plan-aware ordering active — %d targets from plan "
                "(was %d from brand_spec.pages): %s",
                len(_html_targets), len(pages), _html_targets,
            )
            pages = _html_targets

    changes: list[FileChange] = []
    warnings: list[str] = []
    last_provider = "openai"
    last_mode = "openai"
    any_fallback = False
    fallback_reason = ""

    for page_path in pages:
        prompt = _build_page_prompt(page_path, brand_spec, design_system, pages, available_assets)

        # Build messages — include BRAND SPEC block if brand_spec provided
        if brand_spec:
            brand_spec_block = (
                f"BRAND SPEC:\n"
                f"  Name: {brand_spec.brand_name}\n"
                f"  Category: {brand_spec.product_category}\n"
                f"  Audience: {brand_spec.target_audience}\n"
                f"  Core offer: {brand_spec.core_offer}\n"
                f"  Tone: {brand_spec.tone}\n"
                f"  Keywords: {', '.join(brand_spec.must_include_keywords[:6])}\n"
                f"  Primary CTA: {brand_spec.primary_cta}\n"
            )
            user_content = brand_spec_block + "\n" + prompt
        else:
            user_content = prompt

        messages = [
            {"role": "system", "content": _PAGE_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        llm_result = call_llm(messages, max_tokens=16000)
        last_provider = llm_result.provider
        last_mode = llm_result.model_mode

        if llm_result.fallback_used:
            any_fallback = True
            fallback_reason = llm_result.fallback_reason
            warnings.append(f"LLM fallback for {page_path}: {llm_result.fallback_reason}")
            continue

        html = _extract_html(llm_result.content) if llm_result.content else None
        if not html:
            any_fallback = True
            fallback_reason = "no_html_content"
            warnings.append(f"LLM returned no usable HTML for {page_path}")
            # Retry once
            llm_result = call_llm(messages, max_tokens=16000)
            html = _extract_html(llm_result.content) if llm_result.content else None
            if not html:
                warnings.append(f"Retry also failed for {page_path}")
                continue

        full_path = f"data/websites/{slug}/{page_path}"
        changes.append(FileChange(
            path=full_path,
            action="create",
            content=html,
            summary=f"Generated {page_path}",
        ))

    if not changes:
        # Return a graceful fallback result instead of raising
        fallback_msg = (
            f"Generation used fallback mode — no HTML was produced by the LLM. "
            f"Reason: {fallback_reason or 'LLM returned no content'}. "
            "This is a fallback result; check your API key configuration."
        )
        return GenerationResult(
            assistant_message=fallback_msg,
            changes=[],
            preview_route=f"/websites/{slug}/index",
            provider=last_provider,
            model_mode=last_mode,
            warnings=warnings,
            fallback_used=True,
            fallback_reason=fallback_reason or "no_html_content",
            operation_type=operation_type,
        )

    page_names = [c.path.split("/")[-1] for c in changes]
    assistant_msg = (
        f"Built **{brand_spec.brand_name}** — "
        f"{', '.join(page_names)} {'are' if len(page_names) > 1 else 'is'} ready."
    )

    return GenerationResult(
        assistant_message=assistant_msg,
        changes=changes,
        preview_route=f"/websites/{slug}/index",
        provider=last_provider,
        model_mode=last_mode,
        warnings=warnings,
        fallback_used=any_fallback,
        fallback_reason=fallback_reason,
        operation_type=operation_type,
        blueprint={
            "business_name": brand_spec.brand_name,
            "business_positioning": brand_spec.core_offer,
            "target_user": brand_spec.target_audience,
            "feature_list": brand_spec.differentiators,
            "page_map": [{"path": p, "purpose": _page_purpose(p)} for p in pages],
        },
        consistency_profile_id=(design_system or {}).get("consistency_profile_id", ""),
    )


def _page_purpose(path: str) -> str:
    if "index" in path:
        return "landing"
    if "signup" in path:
        return "conversion"
    if "app" in path:
        return "product_entry"
    if "pricing" in path:
        return "pricing"
    return "secondary"


# ---------------------------------------------------------------------------
# Edit path
# ---------------------------------------------------------------------------

def _generate_edit(
    slug: str,
    user_message: str,
    history: list[dict],
    existing_files: dict[str, str],
    design_system: dict | None = None,
    operation: dict | None = None,
    brand_spec: Optional[BrandSpec] = None,
) -> GenerationResult:
    """Edit existing files: try direct CSS edit first, then LLM."""
    operation_type = (operation or {}).get("type", "")

    # Determine which file to edit (default: index.html)
    target_file = _detect_edit_target(user_message, existing_files)
    target_html = existing_files.get(target_file, "")

    if not target_html:
        # Fall back to first available file
        target_file = next(iter(existing_files))
        target_html = existing_files[target_file]

    # --- Try direct CSS edit (instant, no LLM) ---
    direct_result = try_direct_css_edit(target_html, user_message)
    if direct_result is not None and direct_result != target_html:
        changes = [FileChange(
            path=f"data/websites/{slug}/{target_file}",
            action="update",
            content=direct_result,
            summary=f"Direct CSS edit on {target_file}",
        )]

        # For sitewide style changes (color, theme, font), apply to ALL HTML files
        if _is_sitewide_style_change(user_message):
            for fname, fhtml in existing_files.items():
                if fname != target_file and fname.endswith(".html") and fhtml:
                    other_result = try_direct_css_edit(fhtml, user_message)
                    if other_result is not None and other_result != fhtml:
                        changes.append(FileChange(
                            path=f"data/websites/{slug}/{fname}",
                            action="update",
                            content=other_result,
                            summary=f"Direct CSS edit on {fname}",
                        ))

        file_names = [c.path.rsplit("/", 1)[-1] for c in changes]
        assistant_msg = (
            f"Updated {', '.join(file_names)} as requested."
            if len(file_names) > 1
            else f"Applied your change to {target_file}."
        )

        return GenerationResult(
            assistant_message=assistant_msg,
            changes=changes,
            preview_route=f"/websites/{slug}/index",
            provider="direct",
            model_mode="direct_edit",
            operation_type=operation_type,
        )

    # --- LLM edit: send the target file + edit instruction ---
    messages = [
        {"role": "system", "content": _EDIT_SYSTEM_PROMPT},
    ]

    # Include brief history for context
    for msg in history[-4:]:
        content = msg.get("content", "")
        if msg.get("role") == "assistant" and len(content) > 300:
            content = content[:300] + "\n[...]"
        messages.append({"role": msg["role"], "content": content})

    # Truncate very large files to avoid token overflow
    file_content = target_html
    if len(file_content) > 40000:
        file_content = file_content[:40000] + "\n<!-- ... file truncated ... -->"

    user_prompt = (
        f"Here is the current {target_file}:\n\n"
        f"{file_content}\n\n"
        f"USER REQUEST: {user_message}\n\n"
        "Apply the requested change and return the complete modified HTML file. "
        "Raw HTML only, no wrapping."
    )
    messages.append({"role": "user", "content": user_prompt})

    llm_result = call_llm(messages, max_tokens=16000)

    if llm_result.content:
        html = _extract_html(llm_result.content)
        if html:
            return GenerationResult(
                assistant_message=f"Updated {target_file} as requested.",
                changes=[FileChange(
                    path=f"data/websites/{slug}/{target_file}",
                    action="update",
                    content=html,
                    summary=f"LLM edit on {target_file}",
                )],
                preview_route=f"/websites/{slug}/index",
                provider=llm_result.provider,
                model_mode=llm_result.model_mode,
                raw_llm_content=llm_result.content,
                operation_type=operation_type,
            )

    # LLM failed — return unchanged with warning
    return GenerationResult(
        assistant_message="I wasn't able to apply that change. Could you rephrase your request?",
        changes=[],
        preview_route=f"/websites/{slug}/index",
        provider=llm_result.provider if llm_result else "openai",
        model_mode=llm_result.model_mode if llm_result else "fallback",
        warnings=["LLM edit returned no usable HTML"],
        fallback_used=True,
        fallback_reason=llm_result.fallback_reason if llm_result else "no_content",
        operation_type=operation_type,
    )


def _detect_edit_target(message: str, existing_files: dict[str, str]) -> str:
    """Determine which file the user wants to edit based on their message."""
    msg_lower = message.lower()

    if any(w in msg_lower for w in ["signup", "sign up", "register", "registration"]):
        for f in existing_files:
            if "signup" in f:
                return f

    if any(w in msg_lower for w in ["app", "dashboard"]):
        if "app.html" in existing_files:
            return "app.html"

    if any(w in msg_lower for w in ["pricing", "price", "plan", "tier"]):
        for f in existing_files:
            if "pricing" in f:
                return f

    if any(w in msg_lower for w in ["about"]):
        for f in existing_files:
            if "about" in f:
                return f

    return "index.html"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_brand_spec(slug: str, message: str) -> BrandSpec:
    """Build a minimal BrandSpec from intent parser when no spec was synthesised."""
    from core.intent_parser import parse_intent
    intent = parse_intent(message)
    brand_name = intent.get("product_name") or slug.replace("-", " ").title()
    layout, visual, copy, seed = _select_uniqueness_profile(brand_name)
    return BrandSpec(
        brand_name=brand_name,
        product_category=intent.get("product_type") or "saas_b2c",
        target_audience=intent.get("target_user") or "teams",
        core_offer=f"{brand_name} helps {intent.get('target_user', 'users')} with {intent.get('product_type', 'their work')}",
        differentiators=intent.get("core_features") or [],
        tone="professional",
        required_sections=["hero", "features", "pricing", "footer"],
        must_include_keywords=intent.get("core_features") or [],
        primary_cta=intent.get("cta") or "Get Started",
        pages=["index.html", "pages/signup.html", "app.html"],
        layout_profile=layout, visual_motif=visual,
        copy_style=copy, uniqueness_seed=seed,
    )


# ---------------------------------------------------------------------------
# Phase B — File structure generation (Call 2 of new pipeline)
# ---------------------------------------------------------------------------

_SCAFFOLD_SYSTEM_PROMPT = """\
You are a senior front-end architect. Given a brand specification and product description, \
you design the complete file structure for a production-quality static website.

Return ONLY valid JSON — no markdown fences, no explanation, no trailing text.

TECHNOLOGY CONSTRAINTS — YOU MUST FOLLOW THESE:
- Every page is a self-contained .html file with its own <style> and <script> blocks
- You MAY also produce a shared styles.css that pages @import or <link>
- JavaScript is vanilla ES2020+ only — no frameworks, no npm, no bundler, no React, no Vue
- "Backend" features (auth, saved data) are mocked with localStorage
- The website must work by opening index.html directly in a browser — no server required

STRUCTURE RULES:
- index.html is always the landing/home page and always exists
- Sub-pages go in pages/ (e.g. pages/pricing.html, pages/about.html)
- Shared CSS goes in styles/ (e.g. styles/globals.css)
- JavaScript utility files go in scripts/ (e.g. scripts/main.js)
- Image assets go in assets/ (provided separately — do not generate these)
- Maximum 15 files total for initial scaffold
- Minimum 4 files (index.html + at least 1 sub-page + styles + one more)
- Every file's purpose must be specific to THIS product — never generic

FILE SELECTION LOGIC — choose pages based on the product category:
- SaaS/B2B: index.html, pages/features.html, pages/pricing.html, pages/signup.html, app.html
- E-commerce: index.html, pages/products.html, pages/product-detail.html, pages/cart.html, pages/checkout.html
- Portfolio/Agency: index.html, pages/work.html, pages/about.html, pages/contact.html
- Blog/Content: index.html, pages/blog.html, pages/post.html, pages/about.html
- Marketplace: index.html, pages/browse.html, pages/listing.html, pages/dashboard.html, pages/signup.html
- Community/Social: index.html, pages/feed.html, pages/profile.html, pages/signup.html
- For any other category: add pages that make sense for the specific product

OUTPUT FORMAT:
{
  "project_type": "static_site",
  "file_tree": [
    {
      "path": "index.html",
      "purpose": "Landing page with hero section showcasing [specific product feature], \
feature grid, testimonials from [target audience], and pricing preview",
      "depends_on": ["styles/globals.css"]
    }
  ],
  "generation_order": ["styles/globals.css", "index.html", "pages/signup.html"],
  "design_notes": "Paragraph describing the specific visual approach for this brand"
}

generation_order MUST list files in dependency order — files that others depend on come first \
(shared CSS, shared JS, then pages).
"""


def generate_file_structure(
    brand_spec: BrandSpec,
    user_message: str,
    design_system: dict | None = None,
) -> dict:
    """Phase B: generate the project file tree from a BrandSpec (1 LLM call).

    Returns a dict with keys: project_type, file_tree, generation_order, design_notes.
    Falls back to a hardcoded minimal structure on any parse failure.
    """
    from services.design_system_service import DesignSystem

    ds = DesignSystem.from_dict(design_system) if design_system else DesignSystem.generate_aura()
    css_vars = ds.to_css_vars()

    user_prompt = (
        f"PRODUCT: {brand_spec.brand_name}\n"
        f"Category: {brand_spec.product_category}\n"
        f"Audience: {brand_spec.target_audience}\n"
        f"Core Offer: {brand_spec.core_offer}\n"
        f"Tone: {brand_spec.tone}\n"
        f"Differentiators: {', '.join(brand_spec.differentiators[:4])}\n"
        f"Required Sections: {', '.join(brand_spec.required_sections)}\n"
        f"Primary CTA: \"{brand_spec.primary_cta}\"\n\n"
        f"DESIGN TOKENS:\n{css_vars}\n\n"
        f"USER DESCRIPTION:\n{user_message}\n\n"
        "Design the file structure now. JSON only."
    )

    messages = [
        {"role": "system", "content": _SCAFFOLD_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    _FALLBACK_STRUCTURE: dict = {
        "project_type": "static_site",
        "file_tree": [
            {"path": "styles/globals.css", "purpose": "Shared design tokens and base styles", "depends_on": []},
            {"path": "index.html", "purpose": "Landing page", "depends_on": ["styles/globals.css"]},
            {"path": "pages/signup.html", "purpose": "Signup page", "depends_on": ["styles/globals.css"]},
            {"path": "app.html", "purpose": "App dashboard", "depends_on": ["styles/globals.css"]},
        ],
        "generation_order": ["styles/globals.css", "index.html", "pages/signup.html", "app.html"],
        "design_notes": "",
    }

    llm_result = call_llm(messages, max_tokens=2000)
    if not llm_result.content:
        logger.warning("generate_file_structure: LLM returned no content — using fallback")
        return _FALLBACK_STRUCTURE

    content = llm_result.content.strip()
    parsed: dict | None = None

    # Try 1: raw JSON
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        pass

    # Try 2: markdown fence
    if parsed is None:
        md = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if md:
            try:
                parsed = json.loads(md.group(1))
            except json.JSONDecodeError:
                pass

    # Try 3: first { to last }
    if parsed is None:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1:
            try:
                parsed = json.loads(content[start:end + 1])
            except json.JSONDecodeError:
                pass

    if not parsed:
        logger.warning("generate_file_structure: all parse attempts failed — using fallback")
        return _FALLBACK_STRUCTURE

    # Validate: ensure index.html is in generation_order
    order: list[str] = parsed.get("generation_order", [])
    if "index.html" not in order:
        order = ["index.html"] + order
        parsed["generation_order"] = order

    # Validate: drop orphans from generation_order not in file_tree
    tree_paths = {entry["path"] for entry in parsed.get("file_tree", [])}
    parsed["generation_order"] = [p for p in order if p in tree_paths]
    if "index.html" not in parsed["generation_order"]:
        parsed["generation_order"] = ["index.html"] + parsed["generation_order"]

    return parsed


# ---------------------------------------------------------------------------
# Phase C — Single-file generation (Call N of new pipeline)
# ---------------------------------------------------------------------------

_FILE_GEN_SYSTEM_PROMPT = """\
You are a senior web developer. You write one file at a time for a website project. \
The other files in the project are listed for context — your file must be consistent with them.

Return ONLY the raw file content. No markdown fences, no commentary, no preamble. \
Start with the first line of code and end with the last.

FOR .html FILES:
- Complete document from <!DOCTYPE html> to </html>
- CSS custom properties in :root using the exact design tokens provided
- Google Fonts via <link> in <head>
- Responsive: <meta name="viewport">, clamp() spacing, @media at 1024px and 640px
- Fluid grid: repeat(auto-fit, minmax(min(100%, 280px), 1fr))
- All buttons: min-height 44px, padding 12px 24px, border-radius 8px, cursor pointer, transition 150ms
- Scroll reveal: elements with class .reveal, IntersectionObserver in <script> that adds .revealed
- Sticky navbar: add class .scrolled when scrollY > 20
- Navigation: link to ALL other pages using correct relative paths
  - From root files: href="pages/pricing.html"
  - From pages/ files: href="../index.html" for root, href="pricing.html" for sibling pages
- If a shared styles.css exists in the project, <link> to it with correct relative path
- No lorem ipsum — every word specific to this product and audience
- No external JS dependencies

FOR .css FILES:
- :root block with all provided design tokens
- @import for Google Fonts
- Base reset (*, *::before, *::after { box-sizing: border-box; margin: 0; })
- Body defaults using the design tokens
- Utility classes: .container, .reveal/.revealed, .btn-primary, .btn-secondary
- Responsive utilities
- Component styles that pages will use

FOR .js FILES:
- Vanilla ES2020+ only
- 'use strict' at top
- DOMContentLoaded wrapper
- All DOM queries null-checked
- No global variable pollution (use IIFE or module pattern)

COPY QUALITY:
- Every headline: specific value proposition for THIS product
- Every feature description: a concrete capability, not a vague promise
- Every CTA: action verb matching what the user actually gets
- Every testimonial: realistic person name, specific praise referencing an actual feature
- Pricing tiers: realistic numbers, features that match the product
- BANNED PHRASES: "revolutionize", "game-changer", "seamlessly", "cutting-edge", "next-level", \
"supercharge", "unlock your potential", "leverage", "synergy", "streamline", "empower", \
"robust solution", "holistic approach"

IMAGE ASSETS:
- If AVAILABLE ASSETS are listed below, use ONLY those exact paths — do not invent filenames
- If no assets are listed, use CSS gradients, SVG shapes, or emoji as visual elements — \
do NOT use <img> with made-up src paths
"""


def generate_single_file(
    file_path: str,
    file_purpose: str,
    brand_spec: BrandSpec,
    design_system: dict | None,
    file_tree: list[dict],
    already_generated: dict[str, str],
    available_assets: list[str] | None = None,
) -> str | None:
    """Phase C: generate the complete content for one file.

    Returns the file content string, or None on failure.
    """
    from services.design_system_service import DesignSystem

    ds = DesignSystem.from_dict(design_system) if design_system else DesignSystem.generate_aura()
    css_vars = ds.to_css_vars()
    font_import = (
        f"https://fonts.googleapis.com/css2?family={ds.display_font.replace(' ', '+')}:wght@300;400;600;700"
        f"&family={ds.body_font.replace(' ', '+')}:wght@300;400;500;600&display=swap"
    )

    keywords = ", ".join(brand_spec.must_include_keywords[:8]) if brand_spec.must_include_keywords else "N/A"

    # File tree section
    tree_lines = "\n".join(f"  - {e['path']} — {e['purpose']}" for e in file_tree)

    # Build the context from already-generated files:
    # include depends_on files + last 2 generated, truncated to 50 lines each
    current_entry = next((e for e in file_tree if e["path"] == file_path), {})
    depends_on: list[str] = current_entry.get("depends_on", [])

    # Last 2 generated keys
    gen_keys = list(already_generated.keys())
    recent_keys = gen_keys[-2:] if len(gen_keys) >= 2 else gen_keys

    context_paths: list[str] = []
    for p in depends_on:
        if p in already_generated and p not in context_paths:
            context_paths.append(p)
    for p in recent_keys:
        if p not in context_paths and p in already_generated:
            context_paths.append(p)

    # Also include shared CSS if it exists
    shared_css = next((p for p in already_generated if p.endswith(".css")), None)
    if shared_css and shared_css not in context_paths:
        context_paths.append(shared_css)

    if context_paths:
        context_parts: list[str] = []
        for p in context_paths:
            content = already_generated[p]
            lines = content.splitlines()
            shown = lines[:50]
            truncation = f"\n... ({len(lines) - 50} more lines)" if len(lines) > 50 else ""
            context_parts.append(f"── {p} ──\n" + "\n".join(shown) + truncation + "\n── end ──")
        already_section = "\n\n".join(context_parts)
    else:
        already_section = "None yet — this is the first file."

    asset_section = (
        "\n".join(f"  - {a}" for a in available_assets)
        if available_assets
        else "None — use CSS-only decorative elements."
    )

    user_prompt = (
        f"PRODUCT: {brand_spec.brand_name}\n"
        f"Category: {brand_spec.product_category}\n"
        f"Audience: {brand_spec.target_audience}\n"
        f"Core Offer: {brand_spec.core_offer}\n"
        f"Tone: {brand_spec.tone}\n"
        f"Primary CTA: \"{brand_spec.primary_cta}\"\n"
        f"Keywords: {keywords}\n"
        f"Layout style: {brand_spec.layout_profile}\n"
        f"Visual motif: {brand_spec.visual_motif}\n"
        f"Copy style: {brand_spec.copy_style}\n\n"
        f"DESIGN TOKENS:\n{css_vars}\n\n"
        f"FONT IMPORT URL:\n{font_import}\n\n"
        f"PROJECT FILE TREE:\n{tree_lines}\n\n"
        f"ALREADY GENERATED FILES:\n{already_section}\n\n"
        f"AVAILABLE IMAGE ASSETS:\n{asset_section}\n\n"
        f"─────────────\n"
        f"NOW GENERATE: {file_path}\n"
        f"PURPOSE: {file_purpose}\n"
        f"─────────────"
    )

    messages = [
        {"role": "system", "content": _FILE_GEN_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    llm_result = call_llm(messages, max_tokens=16000)
    if not llm_result.content:
        logger.warning("generate_single_file: no content from LLM for %s", file_path)
        return None

    content = llm_result.content

    if file_path.endswith(".html"):
        extracted = _extract_html(content)
        if extracted is None:
            extracted = _extract_html(content.strip())
        return extracted

    if file_path.endswith((".css", ".js")):
        content = re.sub(r"^```\w*\n?", "", content.strip())
        content = content.rstrip("`").strip()

    if not content:
        return None

    return content


# ---------------------------------------------------------------------------
# Spec-based pipeline (v2) — deterministic rendering
# ---------------------------------------------------------------------------

def generate_via_spec(
    slug: str,
    user_message: str,
    history: list[dict],
    design_system: dict | None = None,
) -> GenerationResult:
    """Generate a website via the spec pipeline: LLM→JSON→validate→render.

    The LLM produces ONLY structured JSON.  Rendering is deterministic.
    The spec is saved alongside the HTML files for future edits.
    """
    from services.spec_generator import generate_spec
    from services.spec_renderer import render_site
    from services.site_spec import save_spec

    spec = generate_spec(
        message=user_message,
        history=history,
        slug=slug,
        design_system=design_system,
    )

    rendered = render_site(spec)
    save_spec(slug, spec)

    changes: list[FileChange] = []
    for path, html in rendered.items():
        changes.append(FileChange(
            path=f"data/websites/{slug}/{path}",
            action="create",
            content=html,
            summary=f"Rendered {path} from spec",
        ))

    page_names = [c.path.split("/")[-1] for c in changes]
    assistant_msg = (
        f"Built **{spec.site.title}** — "
        f"{', '.join(page_names)} {'are' if len(page_names) > 1 else 'is'} ready."
    )

    return GenerationResult(
        assistant_message=assistant_msg,
        changes=changes,
        preview_route=f"/websites/{slug}/index",
        provider="spec_renderer",
        model_mode="spec_pipeline",
        blueprint={
            "business_name": spec.site.title,
            "spec_version": "2.0",
            "page_count": len(spec.pages),
            "section_count": sum(len(p.sections) for p in spec.pages),
        },
    )


def edit_via_spec(
    slug: str,
    user_message: str,
    history: list[dict],
    design_system: dict | None = None,
) -> GenerationResult | None:
    """Edit a website by mutating its spec, then re-rendering.

    Returns None if no spec exists (caller should fall back to legacy edit).
    """
    from services.spec_editor import edit_spec
    from services.spec_renderer import render_site
    from services.site_spec import load_spec, save_spec

    spec = load_spec(slug)
    if spec is None:
        return None

    edited_spec = edit_spec(spec, user_message, history)
    rendered = render_site(edited_spec)
    save_spec(slug, edited_spec)

    changes: list[FileChange] = []
    for path, html in rendered.items():
        changes.append(FileChange(
            path=f"data/websites/{slug}/{path}",
            action="update",
            content=html,
            summary=f"Re-rendered {path} from spec",
        ))

    assistant_msg = f"Updated {len(changes)} file{'s' if len(changes) != 1 else ''} as requested."

    return GenerationResult(
        assistant_message=assistant_msg,
        changes=changes,
        preview_route=f"/websites/{slug}/index",
        provider="spec_renderer",
        model_mode="spec_edit",
    )
