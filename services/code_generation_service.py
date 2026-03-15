"""
LLM code generation service — Lovable/Base44-style iterative editor.

Sends system prompt + conversation history + current file contents to the LLM.
Receives a structured JSON response with a `changes[]` array.
Returns a GenerationResult that the caller can pass to workspace_editor.apply_changes().

Response contract (model must return ONLY this JSON):
{
  "assistant_message": "plain-text summary of what changed",
  "changes": [
    {
      "path": "data/websites/<slug>/index.html",
      "action": "create" | "update",
      "content": "<complete file content>",
      "summary": "one-sentence description of this file change"
    }
  ],
  "preview": {
    "primary_route": "/websites/<slug>/index",
    "notes": ["optional notes"]
  },
  "route_graph": {
    "nodes": ["index.html", "app.html"],
    "edges": [{"from": "index.html", "to": "app.html", "label": "CTA"}]
  },
  "layout_plan": {
    "layout_family": "saas",
    "page_map": {"index.html": ["hero", "features", "pricing", "footer"]},
    "section_order": ["hero", "features", "pricing", "footer"],
    "cta_flow": [{"from": "index.html#cta", "to": "app.html", "label": "Get Started"}],
    "dynamic_components": ["testimonial_carousel", "reveal_scroll", "animated_counters"]
  },
  "blueprint": {
    "business_name": "Product name",
    "business_positioning": "One sentence positioning",
    "target_user": "Who this is for",
    "feature_list": ["Feature A", "Feature B"],
    "design_direction": {
      "design_family": "framer_aura",
      "palette_name": "framer_aura",
      "font_pair": {"display": "Space Grotesk", "body": "Inter"},
      "motion_preset": "default",
      "spacing_policy": "aura",
      "consistency_profile_id": "PROFILE_ID"
    },
    "page_map": [
      {"path": "index.html", "purpose": "landing"},
      {"path": "pages/signup.html", "purpose": "conversion"},
      {"path": "app.html", "purpose": "product_entry"}
    ],
    "cta_flow": [
      {"from": "index.html#hero-primary-cta", "to": "pages/signup.html", "label": "Start Free Trial"}
    ],
    "build_steps": ["Create landing page with hero, features, pricing", "..."],
    "quality_gates": ["responsive_contract", "link_integrity", "design_consistency"]
  }
}
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from services.provider_router import LLMResult, _mock_response, call_llm

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class FileChange:
    path: str           # relative path, e.g. data/websites/my-app/index.html
    action: str         # "create" | "update"
    content: str        # complete file content
    summary: str = ""   # human-readable description


@dataclass
class GenerationResult:
    assistant_message: str
    changes: list[FileChange]
    preview_route: str = ""
    preview_notes: list[str] = field(default_factory=list)
    provider: str = "mock"
    model_mode: str = "mock"
    warnings: list[str] = field(default_factory=list)
    raw_llm_content: str = ""  # for debugging malformed responses
    fallback_used: bool = False
    fallback_reason: str = ""
    operation_type: str = ""   # detected operation type
    route_graph: dict = field(default_factory=dict)
    layout_plan: dict = field(default_factory=dict)
    blueprint: dict = field(default_factory=dict)
    consistency_profile_id: str = ""


# ---------------------------------------------------------------------------
# System prompt (luxury modern)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_BASE = """\
You are a principal full-stack engineer and product designer working as an AI product builder \
(Lovable/Base44 caliber). You translate user descriptions into production-quality web products \
through conversation. Your outputs are visually premium, technically sound, and feel \
bespoke — never recycled from a generic template.

OUTPUT FORMAT — return ONLY this JSON object, no markdown fences, no text before or after:

{
  "assistant_message": "Clear 1-3 sentence summary of what you built or changed",
  "changes": [
    {
      "path": "data/websites/SLUG/index.html",
      "action": "create",
      "content": "<!DOCTYPE html>...complete file content...",
      "summary": "Created landing page with hero, features, CTA"
    }
  ],
  "preview": {
    "primary_route": "/websites/SLUG/index",
    "notes": []
  },
  "route_graph": {
    "nodes": ["index.html", "app.html"],
    "edges": [{"from": "index.html", "to": "app.html", "label": "CTA"}]
  },
  "layout_plan": {
    "layout_family": "saas",
    "page_map": {"index.html": ["hero", "features", "pricing", "footer"]},
    "section_order": ["hero", "features", "pricing", "footer"],
    "cta_flow": [{"from": "index.html#cta", "to": "app.html", "label": "Get Started"}],
    "dynamic_components": ["testimonial_carousel", "reveal_scroll", "animated_counters"]
  }
}

WORKSPACE RULES:
- SLUG is provided by the system. Always use paths under data/websites/SLUG/
- Allowed files: index.html, app.html, pages/*.html, style.css, app.js, data.json, README.md
- Return COMPLETE file content for every changed file (never a diff or fragment)
- When modifying an existing file: keep ALL working sections, apply ONLY the requested change

══════════════════════════════════════════════════════════
QUALITY MANDATE — EVERY OUTPUT MUST MEET THIS BAR
══════════════════════════════════════════════════════════

FIRST OUTPUT STANDARD:
- Treat every initial build as if it ships live immediately to real users
- Make it feel purpose-built for THIS product — not recycled from a prior product
- Hero copy, feature names, testimonials, proof stats must all reference the product's
  specific domain (e.g. for a calorie tracker: macros, meals, nutrition goals — NOT
  generic "productivity" or "workflow" copy)
- Choose a visual identity appropriate to the product category:
    · Health/fitness: greens/teals/energetic accents, clean rounded shapes
    · Finance/B2B SaaS: deep navy/slate, high contrast, crisp typography
    · Consumer/lifestyle: vibrant, warm, playful palette
    · Developer tools: dark, monospace accents, terminal-green or electric blue hints
    · Education/learning: warm yellows/oranges, friendly sans-serif

PRODUCT-SPECIFIC COPY REQUIREMENTS:
- Feature titles: short, action-oriented, product-domain nouns (NOT generic "Feature 1")
- Testimonial quotes: must mention the specific pain point this product solves
- Proof stats: domain-specific numbers (e.g. "12,000 calories tracked daily" not "87% faster")
- Hero subheading: one specific sentence about the product's core workflow or key outcome
- NEVER use lorem ipsum, "coming soon", "your content here", or "placeholder text"

INTEGRATION-READY PLACEHOLDERS — include where contextually appropriate:
- Auth signup: styled HTML form with input[type=email] + input[type=password] + submit button,
  proper labels, aria-label attributes, client-side required validation
- Paid SaaS pricing: 3-tier pricing cards (Free/Pro/Enterprise) before footer CTA
- Data connection: in app.html, include a styled "Connect your account" card with
  a labelled API token input field (type=password, placeholder="sk-...")
- Payments CTA: "Start free trial" / "Upgrade to Pro" button with Stripe-ready class name

DESIGN SYSTEM REQUIREMENTS:
- All colors exclusively via CSS custom properties (:root block) — no hardcoded hex values
- Google Fonts: @import inside <style> block, choose fonts that match product personality
- Fluid spacing: all major spacing values use clamp()
- Use glass-morphism cards (backdrop-filter: blur + semi-transparent bg) for feature/pricing cards
- Letter-spacing: -0.02em to -0.03em on large display headings
- Smooth micro-interactions: transition: all 0.2s ease on hover states

RESPONSIVE-FIRST CONTRACT (mandatory for every generated page):
- <meta name="viewport" content="width=device-width, initial-scale=1.0">
- Fluid tokens with clamp() for typography and spacing
- Breakpoints: @media (max-width: 1024px) and @media (max-width: 640px) minimum
- Grid: repeat(auto-fit, minmax(min(100%, Xpx), 1fr)) — NO fixed-column-count grids
- No horizontal overflow: overflow-wrap: break-word on text, max-width: 100% on media

INTERACTIVITY (vanilla JS, no external deps):
- Reveal-on-scroll for cards (.reveal class + IntersectionObserver)
- Sticky navbar scroll state (.scrolled class on scroll > 14px)
- Animated counters on proof stats (if metric strip included)
- If auth form: basic client-side validation (required fields, email format check)

══════════════════════════════════════════════════════════
GENERATED ASSET PLACEMENT CONTRACT (mandatory)
══════════════════════════════════════════════════════════

When assets/hero.svg exists in the project:
- Reference it in the hero section as: <img src="assets/hero.svg" alt="[product] hero illustration" class="hero-img" style="max-width:100%;height:auto;">
- Place it visually adjacent to the hero headline

When assets/icon-*.svg files exist:
- Use each icon-N.svg inside feature card N as: <img src="assets/icon-N.svg" alt="[feature name] icon" style="width:48px;height:48px;">
- Never leave a generated asset unreferenced in the HTML

Image rules (all generated assets):
- Always include descriptive alt text
- Always include style="max-width:100%;height:auto;" or equivalent CSS class
- Never inline SVG content; always reference via <img src="...">

══════════════════════════════════════════════════════════
DESIGN TOKEN & VISUAL RHYTHM CONTRACT (mandatory)
══════════════════════════════════════════════════════════

CSS TOKENS (required in every generated page):
- Define ALL colors as :root custom properties (e.g. --color-bg, --color-text, --color-accent)
- Define spacing scale: --space-xs through --space-2xl using clamp()
- Define type scale: --text-sm through --text-4xl using clamp()
- NO hardcoded hex/rgb values outside :root block

BUTTON VARIANTS (required):
- .btn-primary: filled accent background, white text, border-radius var(--radius)
- .btn-secondary: transparent, border 1.5px solid accent, accent text
- Both variants: focus-visible outline, hover state (darken/lighten 8%), active state (scale 0.97)
- transition: all 0.15s ease on all interactive elements

SECTION HIERARCHY:
- Consistent vertical rhythm: use var(--space-*) for section padding, not px values
- Each major section must have a distinct visual treatment (bg color, border, shadow, or gradient variation)
- Headings: use clamp()-based font-size, letter-spacing: -0.02em on display sizes

══════════════════════════════════════════════════════════
ITERATION RULES — EDITING EXISTING FILES
══════════════════════════════════════════════════════════

When the user asks to change something:
1. Read the current file carefully — understand what exists before touching it
2. Apply EXACTLY what was requested: no more, no less
3. NEVER remove or rewrite sections not mentioned in the request
4. Color changes: update :root custom properties only — do NOT rewrite component CSS
5. Adding a section: insert at the natural document position, keep surrounding sections intact
6. Style requests ("make it darker", "change font"): update :root tokens, not component rules
7. Return the COMPLETE modified file — the full HTML from <!DOCTYPE html> to </html>

══════════════════════════════════════════════════════════
FRAMER AURA GENERATION CONTRACT (mandatory)
══════════════════════════════════════════════════════════

DESIGN IDENTITY:
- Every generated site must follow the Framer Aura design language:
  neutral slate base + blue/purple/pink gradient accent ramp
- Define in :root:
    --color-primary: #3b82f6;
    --color-secondary: #8b5cf6;
    --color-accent-pink: #ec4899;
    --accent-gradient: linear-gradient(135deg, #3b82f6 0%, #8b5cf6 50%, #ec4899 100%);
- Apply --accent-gradient to: hero CTAs, section dividers, active nav underlines,
  gradient text headings (background-clip: text), and pricing card highlights
- Use --color-secondary (#8b5cf6) for interactive focus rings and accent highlights

LANDING → SIGNUP → APP IA FLOW:
For new product builds, always generate this page graph unless user specifies otherwise:
  1. index.html    — Landing: hero, proof, features, testimonials, pricing, CTA → signup
  2. pages/signup.html — Signup: conversion-focused, minimal, one-column form
  3. app.html      — App: project dashboard or builder entry, sidebar + content area
  4. pages/pricing.html — (linked from landing, pre-footer CTA)

Nav wiring:
  - index.html nav: Home | Features | Pricing | Sign up (CTA button)
  - Primary landing CTA → pages/signup.html
  - Pricing section CTA → pages/pricing.html or pages/signup.html
  - Signup form submit → app.html

TIER-AWARE PRICING SECTION:
When generating a pricing section, always include 3 tiers:
  Free: limited features, "Get started free" CTA (href="pages/signup.html")
  Pro ($XX/mo): primary tier with gradient border + highlight, "Start free trial" CTA
  Enterprise: "Contact us" CTA
The Pro tier card must use: border: 2px solid transparent; background: var(--accent-gradient);
(gradient border via background-clip trick or outline pseudo-element approach)

══════════════════════════════════════════════════════════
MULTI-PAGE CONTRACT (mandatory when generating multiple pages)
══════════════════════════════════════════════════════════

PAGE STRUCTURE:
- index.html: primary landing page — always at the root
- app.html: app/dashboard page — at the root
- pages/*.html: additional pages (e.g. pages/pricing.html, pages/about.html, pages/signup.html)
- All internal links MUST use relative paths — NEVER absolute routes like "/pricing"
  Correct: href="pages/pricing.html"   Wrong: href="/pricing"

NAV LINK WIRING:
- Every page's <nav> must include links to all other top-level pages
- CTA buttons must use relative hrefs matching the actual file path
- Links from index.html to sub-pages: href="pages/[name].html"
- Links from pages/* back to root: href="../index.html"

PAGE CONTINUITY:
- Each turn must preserve all pages from the previous turn in the changes[] array
- When adding a new page: also update the nav on ALL existing pages to link to it
- When removing a page: remove all nav links pointing to it in all remaining pages

LAYOUT PLAN (include in every response):
Add a "layout_plan" key alongside "route_graph" at the top level of your JSON:
{
  "layout_plan": {
    "layout_family": "saas",
    "page_map": {"index.html": ["hero", "features", "pricing", "footer"]},
    "section_order": ["hero", "features", "pricing", "footer"],
    "cta_flow": [{"from": "index.html#cta", "to": "app.html", "label": "Get Started"}],
    "dynamic_components": ["testimonial_carousel", "reveal_scroll", "animated_counters"]
  }
}

══════════════════════════════════════════════════════════
SPACING & GUTTER CONTRACT (mandatory)
══════════════════════════════════════════════════════════

CONTENT CONTAINER (required on every page):
- Define in :root: --container-width: clamp(320px, 90vw, 1200px)
- Every section's content wrapper: max-width: var(--container-width); margin-inline: auto;
- NO section content touches viewport edges; minimum side padding: var(--space-md)

SPACING TOKENS (required in :root):
- --space-xs:  clamp(0.25rem, 0.5vw, 0.5rem)
- --space-sm:  clamp(0.5rem, 1vw, 0.75rem)
- --space-md:  clamp(0.75rem, 1.5vw, 1.25rem)
- --space-lg:  clamp(1rem, 2vw, 1.75rem)
- --space-xl:  clamp(1.5rem, 3vw, 2.5rem)
- --space-2xl: clamp(2rem, 5vw, 4rem)

SECTION RHYTHM:
- Section padding: padding-block: var(--space-2xl)
- Gap between cards/items: gap: var(--space-lg)
- NEVER set section padding in raw px values — always use var(--space-*)

TOUCH TARGETS:
- All buttons and links: min-height: 44px; min-width: 44px; display: inline-flex; align-items: center;

ANTI-EDGE RULES:
- Content wrappers: padding-inline: var(--space-md) on mobile
- All <img> and <video>: max-width: 100%; height: auto;

══════════════════════════════════════════════════════════
DYNAMIC COMPONENTS CONTRACT (mandatory for new builds)
══════════════════════════════════════════════════════════

TESTIMONIAL CAROUSEL (required when building a testimonials section):
- 3-5 testimonial cards; only one visible at a time (CSS transform slide)
- Navigation: prev/next buttons (aria-label="Previous testimonial" / "Next testimonial")
  + dot indicators (aria-label="Go to testimonial N")
- Keyboard accessible: ArrowLeft/ArrowRight advance slides; focus follows the active card
- @media (prefers-reduced-motion: reduce): disable transitions, show all cards stacked vertically
- No autoplay — never auto-advance slides without user action
- Root markup: <div role="region" aria-label="Testimonials" class="carousel">

REVEAL-ON-SCROLL:
- Feature cards, testimonial cards, and section headings: add class="reveal"
- Vanilla JS IntersectionObserver: threshold 0.15, adds class "visible" on entry
- CSS:
    .reveal { opacity: 0; transform: translateY(20px); transition: opacity 0.4s ease, transform 0.4s ease; }
    .reveal.visible { opacity: 1; transform: none; }
- @media (prefers-reduced-motion: reduce): .reveal, .reveal.visible { opacity: 1; transform: none; transition: none; }

ANIMATED COUNTERS:
- On metric/stat strips: <span class="counter" data-target="[number]">0</span>
- JS: count from 0 → data-target over 1.2s using requestAnimationFrame, triggered on viewport entry
- @media (prefers-reduced-motion: reduce): display final number immediately, skip animation

STICKY NAV:
- Navbar receives class "scrolled" when window.scrollY > 14
- CSS: nav.scrolled { backdrop-filter: blur(12px); box-shadow: 0 2px 8px rgba(0,0,0,0.08); }

HOVER MICRO-INTERACTIONS:
- Feature cards: transform: translateY(-4px) on :hover; box-shadow deepens
- Buttons: transform: scale(1.02) on :hover; scale(0.97) on :active
- All interactive elements: transition: all 0.2s ease

══════════════════════════════════════════════════════════
BLUEPRINT CONTRACT (mandatory — include in every response)
══════════════════════════════════════════════════════════

Include a "blueprint" key at the top level of your JSON response:
{
  "blueprint": {
    "business_name": "Product name",
    "business_positioning": "One sentence positioning statement",
    "target_user": "Who this is for",
    "feature_list": ["Feature A", "Feature B"],
    "design_direction": {
      "design_family": "framer_aura",
      "palette_name": "framer_aura",
      "font_pair": {"display": "Space Grotesk", "body": "Inter"},
      "motion_preset": "default",
      "spacing_policy": "aura",
      "consistency_profile_id": "PROFILE_ID"
    },
    "page_map": [
      {"path": "index.html", "purpose": "landing"},
      {"path": "pages/signup.html", "purpose": "conversion"},
      {"path": "app.html", "purpose": "product_entry"}
    ],
    "cta_flow": [
      {"from": "index.html#hero-primary-cta", "to": "pages/signup.html", "label": "Start Free Trial"}
    ],
    "build_steps": ["Create landing page with hero, features, pricing", "..."],
    "quality_gates": ["responsive_contract", "link_integrity", "design_consistency"]
  }
}
- Use the CONSISTENCY_PROFILE_ID from the design system block verbatim
- page_map must list every page included in changes[]
- cta_flow must reflect actual href targets in the generated HTML

══════════════════════════════════════════════════════════
UNIQUENESS MANDATE
══════════════════════════════════════════════════════════
Every generated site MUST feel purpose-built, not recycled:
- Use the CONSISTENCY_PROFILE_ID from the design system block — never change it
- Use domain-specific product copy — no generic "Feature 1" / "Lorem ipsum"
- Color tokens: follow the design system palette exactly, do NOT use generic blue/white defaults
- Font: use the specified display+body font pair from the design system
- Section patterns: choose section configurations from the layout_family mandate
- Navigation: wire all pages correctly with relative hrefs per the MULTI-PAGE CONTRACT
- CTA labels: use action verbs specific to this product's domain (NOT "Get Started" generically)
- Proof stats: domain-specific numbers, not generic "10x faster" copy
"""

# Keep legacy alias for backward compat
_SYSTEM_PROMPT = _SYSTEM_PROMPT_BASE


# ---------------------------------------------------------------------------
# Layout family section mandate (injected dynamically per call)
# ---------------------------------------------------------------------------

_LAYOUT_FAMILY_SECTIONS: dict[str, list[str]] = {
    "saas": [
        "1. Sticky translucent navbar: backdrop-filter blur, brand + nav links + primary CTA",
        "2. Hero: display-font heading, domain-specific subheading, DUAL CTAs (filled + outlined), radial gradient bg",
        "3. Features: 3–5 cards with icon + h3 title + 2-sentence description",
        "4. Social proof: 3 testimonials OR animated metrics strip",
        "5. Pre-footer CTA: bold headline + primary action",
        "6. Footer: brand, nav links, copyright",
    ],
    "enterprise": [
        "1. Sticky navbar: logo + text nav links + demo-request CTA",
        "2. Hero: authoritative headline, one-line subheading, single primary CTA, trust logos row",
        "3. Trust logos: 5–6 recognizable brand logos",
        "4. Features / capabilities: icon + title + short description (3–4 items)",
        "5. Case study highlight: company name, metric achieved, 1-sentence quote",
        "6. Pricing: 3-tier table with feature comparison rows",
        "7. Footer: columns (product / company / legal), copyright",
    ],
    "wellness": [
        "1. Navbar: logo + minimal nav + CTA",
        "2. Hero: warm headline, empathetic subheading, single primary CTA, lifestyle image slot",
        "3. Benefits: 3 cards with benefit title + 1-sentence",
        "4. How it works: 3-step numbered flow",
        "5. Testimonials: 3 first-person quotes with name + outcome",
        "6. Pre-footer CTA",
        "7. Footer",
    ],
    "developer": [
        "1. Navbar: logo + docs/GitHub links + CTA",
        "2. Hero: technical headline, one-liner pitch, code snippet, dual CTAs",
        "3. Quick-start: 3-step code block walkthrough",
        "4. Features: 3–4 cards with icon + feature name + technical description",
        "5. Integrations: logo grid (4–8 icons)",
        "6. Pre-footer CTA",
        "7. Footer",
    ],
    "marketplace": [
        "1. Navbar: logo + search bar + categories + CTA",
        "2. Hero: value prop headline, category quick-links, search CTA",
        "3. Featured categories: grid of 4–6 category cards",
        "4. Featured items: horizontal scroll or 3-column grid",
        "5. Social proof / stats strip",
        "6. Footer",
    ],
    "education": [
        "1. Navbar: logo + courses + pricing + CTA",
        "2. Hero: outcome-focused headline, subheading, enrollment CTA",
        "3. Course catalog: 3–4 course cards (title, description, instructor, price)",
        "4. Features: 3 learning benefits",
        "5. Testimonials: 3 student outcomes",
        "6. Pricing: 3 tiers",
        "7. Footer",
    ],
    "consumer": [
        "1. Navbar: logo + minimal links",
        "2. Hero: vibrant headline + subheading + CTA",
        "3. Gallery / showcase: product or lifestyle image grid (6 slots)",
        "4. Features: 3 cards",
        "5. Testimonials: 3 user quotes",
        "6. Pre-footer CTA",
        "7. Footer",
    ],
}


def _build_section_mandate(layout_family: str) -> str:
    """Return the section mandate block for the given layout family."""
    sections = _LAYOUT_FAMILY_SECTIONS.get(layout_family, _LAYOUT_FAMILY_SECTIONS["saas"])
    lines = [
        "MANDATORY LANDING PAGE SECTIONS — ALL REQUIRED:",
        f"(Layout family: {layout_family})",
    ] + sections
    return "\n".join(lines)


def _build_system_prompt(
    style_seed: dict | None = None,
    design_system: dict | None = None,
) -> str:
    """Build the system prompt, optionally injecting design system or style directives."""
    prompt = _SYSTEM_PROMPT_BASE

    # Inject full design system if available
    if design_system:
        try:
            from services.design_system_service import DesignSystem
            ds = DesignSystem.from_dict(design_system)
            prompt = prompt.rstrip() + "\n\n" + ds.to_prompt_block() + "\n"
            return prompt
        except Exception as e:
            logger.warning("Failed to inject design system: %s", e)

    # Fall back to style seed hints
    if style_seed:
        seed_lines = ["", "STYLE SEED (follow strictly, do not use generic template defaults):"]
        if style_seed.get("archetype"):
            seed_lines.append(f"- Archetype: {style_seed['archetype']}")
        if style_seed.get("palette"):
            seed_lines.append(f"- Palette: {style_seed['palette']}")
        if style_seed.get("density"):
            seed_lines.append(f"- Density: {style_seed['density']}")
        if style_seed.get("motion"):
            seed_lines.append(f"- Motion: {style_seed['motion']}")
        prompt = prompt.rstrip() + "\n" + "\n".join(seed_lines) + "\n"

    # Inject layout-family-specific section mandate
    if not design_system:
        layout_family = (style_seed or {}).get("layout_family") or "saas"
        section_block = _build_section_mandate(layout_family)
        prompt = prompt.rstrip() + "\n\n" + section_block + "\n"

    return prompt


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate(
    slug: str,
    user_message: str,
    history: list[dict],
    existing_files: dict[str, str] | None = None,
    mock_mode: bool = False,
    style_seed: dict | None = None,
    design_system: dict | None = None,    # persisted design system
    operation: dict | None = None,        # structured operation hint
) -> GenerationResult:
    """Generate or update website files via LLM.

    Args:
        slug:           Project slug, e.g. "my-app"
        user_message:   Latest user message
        history:        [{"role": "user"|"assistant", "content": str}, ...]
        existing_files: {relative_path: content} — current disk content
        mock_mode:      Skip real LLM calls entirely
        style_seed:     Optional style directives dict (archetype, palette, density, motion)
        design_system:  Persisted design system dict from DB
        operation:      Detected operation hint {"type", "target", "metadata"}

    Returns:
        GenerationResult with changes[] ready for workspace_editor.apply_changes()
    """
    operation_type = (operation or {}).get("type", "")

    if mock_mode:
        llm_result = _mock_response()
    else:
        messages = _build_messages(
            slug, user_message, history, existing_files,
            style_seed=style_seed, design_system=design_system, operation=operation,
        )
        llm_result = call_llm(messages)

    if llm_result.content:
        parsed = _parse_response(llm_result.content)
        changes = _extract_changes(parsed, slug)
        if changes:
            return GenerationResult(
                assistant_message=parsed.get("assistant_message", "Done."),
                changes=changes,
                preview_route=parsed.get("preview", {}).get("primary_route", f"/websites/{slug}/index"),
                preview_notes=parsed.get("preview", {}).get("notes", []),
                provider=llm_result.provider,
                model_mode=llm_result.model_mode,
                raw_llm_content=llm_result.content,
                fallback_used=llm_result.fallback_used,
                fallback_reason=llm_result.fallback_reason,
                operation_type=operation_type,
                route_graph=parsed.get("route_graph", {}),
                layout_plan=parsed.get("layout_plan", {}),
                blueprint=parsed.get("blueprint", {}),
                consistency_profile_id=(design_system or {}).get("consistency_profile_id", ""),
            )
        else:
            logger.warning("LLM returned no usable changes (len=%d)", len(llm_result.content))

    # Heuristic fallback
    result = _template_generate(slug, user_message, existing_files, llm_result)
    result.operation_type = operation_type
    result.consistency_profile_id = (design_system or {}).get("consistency_profile_id", "")
    result.blueprint = {}
    return result


# ---------------------------------------------------------------------------
# Message construction
# ---------------------------------------------------------------------------


def _build_messages(
    slug: str,
    user_message: str,
    history: list[dict],
    existing_files: dict[str, str] | None,
    style_seed: dict | None = None,
    design_system: dict | None = None,
    operation: dict | None = None,
) -> list[dict]:
    system = _build_system_prompt(style_seed, design_system).replace("SLUG", slug)
    messages: list[dict] = [{"role": "system", "content": system}]

    # Include recent history (last 10 turns), pruning long assistant messages
    for msg in history[-10:]:
        content = msg.get("content", "")
        if msg.get("role") == "assistant" and len(content) > 600:
            content = content[:600] + "\n[... truncated ...]"
        messages.append({"role": msg["role"], "content": content})

    # Build user turn: operation hint + message + current file context
    parts: list[str] = []

    # Operation type hint for structured edits
    if operation and operation.get("type") and operation["type"] != "general_edit":
        op_tag = f"[OPERATION: {operation['type']}"
        if operation.get("target"):
            op_tag += f" target={operation['target']!r}"
        if operation.get("metadata"):
            for k, v in operation["metadata"].items():
                op_tag += f" {k}={v!r}"
        op_tag += "]"
        parts.append(op_tag)

    parts.append(user_message)

    # For iterative edits, add an explicit preservation reminder
    is_edit = bool(existing_files)
    if is_edit:
        parts.append(
            "\n[EDIT MODE] The current file(s) are provided below. "
            "Apply ONLY the requested change. Preserve all other sections exactly. "
            "Return the complete file from <!DOCTYPE html> to </html>."
        )
        parts.append("")
        for rel_path, fcontent in existing_files.items():
            snippet = fcontent[:6000]
            if len(fcontent) > 6000:
                snippet += "\n<!-- ... file truncated at 6000 chars ... -->"
            parts.append(f"--- CURRENT data/websites/{slug}/{rel_path} ---\n{snippet}")
    else:
        # Fresh generation — remind about product-specific copy
        parts.append(
            "\n[NEW BUILD] Generate a complete, polished, product-specific website. "
            "All copy must reference this exact product's domain — no generic placeholder text."
        )

    messages.append({"role": "user", "content": "\n".join(parts)})
    return messages


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _parse_response(content: str) -> dict:
    """Robustly extract JSON from LLM output."""
    text = content.strip()

    # Some models escape single quotes as \' which is invalid JSON — strip it
    text = text.replace("\\'", "'")

    # 1. Direct JSON
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    # 2. JSON inside markdown fences
    md = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if md:
        try:
            return json.loads(md.group(1))
        except json.JSONDecodeError:
            pass

    # 3. Largest { ... } span
    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if brace:
        try:
            return json.loads(brace.group(0))
        except json.JSONDecodeError:
            pass

    # 4. Raw HTML — model ignored format instructions
    if "<!doctype" in text.lower()[:200] or "<html" in text.lower()[:300]:
        logger.warning("LLM returned raw HTML — wrapping as change")
        return {
            "assistant_message": "Generated website.",
            "changes": [{"path": "index.html", "action": "create",
                          "content": text, "summary": "Model returned raw HTML"}],
            "preview": {},
        }

    logger.warning("Could not parse LLM response (len=%d preview=%r)", len(text), text[:80])
    return {}


def _extract_changes(parsed: dict, slug: str) -> list[FileChange]:
    """Convert parsed JSON changes list into FileChange objects."""
    raw_changes = parsed.get("changes") or []
    if not isinstance(raw_changes, list):
        return []

    result: list[FileChange] = []
    for item in raw_changes:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", "")).strip()
        action = str(item.get("action", "create")).strip().lower()
        content = str(item.get("content", "")).strip()
        summary = str(item.get("summary", ""))

        # If path is just a filename, prefix with the slug dir
        if "/" not in path:
            path = f"data/websites/{slug}/{path}"

        if not path or not content:
            continue

        result.append(FileChange(path=path, action=action, content=content, summary=summary))

    return result


# ---------------------------------------------------------------------------
# Heuristic template fallback — helpers
# ---------------------------------------------------------------------------


def _extract_product_name(message: str, intent: dict, slug: str) -> str:
    """Extract product name from message, intent, or slug — in priority order."""
    # Look for "called X" or "named X" patterns
    m = re.search(r'\b(?:called|named)\s+([A-Z][A-Za-z0-9\s]{1,20})', message)
    if m:
        return m.group(1).strip()
    name = intent.get("product_name", "")
    if name and name.lower() not in ("app", "website", "site", "product"):
        return name
    return slug.replace("-", " ").title()


def _render_aura_landing(name: str, tagline: str, features: list, cta: str, slug: str) -> str:
    feat_cards = ""
    icons = ["⚡", "🎯", "🔒", "📊", "🚀", "💡"]
    for i, f in enumerate(features[:6]):
        feat_cards += f"""
        <div class="card reveal">
          <div class="card-icon">{icons[i % len(icons)]}</div>
          <h3>{f}</h3>
          <p>Powerful {f.lower()} capabilities built for modern teams.</p>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{name} — {tagline[:60]}</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@300;400;500&display=swap');
    :root {{
      --color-primary: #3b82f6;
      --color-secondary: #8b5cf6;
      --color-accent: #ec4899;
      --accent-gradient: linear-gradient(135deg,#3b82f6 0%,#8b5cf6 50%,#ec4899 100%);
      --color-bg: #f8fafc; --color-surface: #fff; --color-text: #0f172a; --color-muted: #64748b;
      --color-border: #e2e8f0;
      --font-display: 'Space Grotesk',sans-serif; --font-body: 'Inter',sans-serif;
      --radius-sm:6px; --radius-md:12px; --radius-lg:20px;
      --shadow-md:0 4px 24px rgba(0,0,0,.08);
      --container: clamp(320px,90vw,1200px);
      --space-xs:clamp(.25rem,.5vw,.5rem); --space-sm:clamp(.5rem,1vw,.75rem);
      --space-md:clamp(.75rem,1.5vw,1.25rem); --space-lg:clamp(1rem,2vw,1.75rem);
      --space-xl:clamp(1.5rem,3vw,2.5rem); --space-2xl:clamp(2rem,5vw,4rem);
    }}
    *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:var(--font-body);background:var(--color-bg);color:var(--color-text);line-height:1.6}}
    nav{{position:sticky;top:0;z-index:100;padding:.75rem var(--space-md);display:flex;align-items:center;justify-content:space-between;background:rgba(248,250,252,.85);backdrop-filter:blur(12px);border-bottom:1px solid var(--color-border);transition:all .3s}}
    nav.scrolled{{box-shadow:0 2px 16px rgba(0,0,0,.08)}}
    .nav-brand{{font-family:var(--font-display);font-weight:700;font-size:1.2rem;background:var(--accent-gradient);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}}
    .nav-links{{display:flex;gap:var(--space-lg);list-style:none}}
    .nav-links a{{text-decoration:none;color:var(--color-muted);font-size:.9rem;transition:color .2s}}
    .nav-links a:hover{{color:var(--color-text)}}
    .btn{{display:inline-flex;align-items:center;justify-content:center;min-height:44px;padding:.625rem 1.25rem;border-radius:var(--radius-md);font-weight:600;font-size:.9rem;text-decoration:none;transition:all .2s;cursor:pointer;border:none}}
    .btn-primary{{background:var(--accent-gradient);color:#fff;box-shadow:0 2px 12px rgba(139,92,246,.3)}}
    .btn-primary:hover{{transform:scale(1.02);box-shadow:0 4px 20px rgba(139,92,246,.4)}}
    .btn-secondary{{background:transparent;border:1.5px solid var(--color-primary);color:var(--color-primary)}}
    .btn-secondary:hover{{background:rgba(59,130,246,.06)}}
    .container{{max-width:var(--container);margin-inline:auto;padding-inline:var(--space-md)}}
    section{{padding-block:var(--space-2xl)}}
    .hero{{padding-block:clamp(3rem,8vw,6rem);text-align:center;background:linear-gradient(180deg,rgba(59,130,246,.04) 0%,transparent 100%)}}
    .hero h1{{font-family:var(--font-display);font-size:clamp(2rem,5vw,3.5rem);font-weight:700;letter-spacing:-.02em;line-height:1.15;margin-bottom:var(--space-md)}}
    .hero h1 span{{background:var(--accent-gradient);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}}
    .hero p{{font-size:clamp(1rem,2vw,1.15rem);color:var(--color-muted);max-width:560px;margin-inline:auto;margin-bottom:var(--space-xl)}}
    .hero-actions{{display:flex;gap:var(--space-md);justify-content:center;flex-wrap:wrap}}
    .features h2{{font-family:var(--font-display);font-size:clamp(1.5rem,3vw,2.25rem);font-weight:700;text-align:center;margin-bottom:var(--space-xl);letter-spacing:-.01em}}
    .cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr));gap:var(--space-lg)}}
    .card{{background:var(--color-surface);border:1px solid var(--color-border);border-radius:var(--radius-lg);padding:var(--space-lg);transition:transform .2s,box-shadow .2s;opacity:0;transform:translateY(20px)}}
    .card.visible{{opacity:1;transform:none}}
    .card:hover{{transform:translateY(-4px);box-shadow:var(--shadow-md)}}
    .card-icon{{font-size:2rem;margin-bottom:var(--space-sm)}}
    .card h3{{font-family:var(--font-display);font-size:1.1rem;font-weight:600;margin-bottom:.5rem}}
    .card p{{font-size:.9rem;color:var(--color-muted)}}
    .cta-section{{background:var(--accent-gradient);border-radius:var(--radius-lg);padding:var(--space-2xl);text-align:center;color:#fff;margin-block:var(--space-2xl)}}
    .cta-section h2{{font-family:var(--font-display);font-size:clamp(1.5rem,3vw,2rem);font-weight:700;margin-bottom:var(--space-md)}}
    .btn-white{{background:#fff;color:var(--color-secondary);font-weight:700}}
    .btn-white:hover{{transform:scale(1.02);box-shadow:0 4px 20px rgba(0,0,0,.2)}}
    footer{{border-top:1px solid var(--color-border);padding-block:var(--space-xl);text-align:center;color:var(--color-muted);font-size:.875rem}}
    @media(max-width:1024px){{.nav-links{{display:none}}}}
    @media(max-width:640px){{.hero-actions{{flex-direction:column;align-items:center}}}}
    @media(prefers-reduced-motion:reduce){{.card,.card.visible{{opacity:1;transform:none;transition:none}}}}
  </style>
</head>
<body>
  <nav id="navbar">
    <div class="nav-brand">{name}</div>
    <ul class="nav-links">
      <li><a href="#features">Features</a></li>
      <li><a href="#pricing">Pricing</a></li>
    </ul>
    <a href="pages/signup.html" class="btn btn-primary">Get Started</a>
  </nav>
  <section class="hero">
    <div class="container">
      <h1>The <span>{name}</span> way to work smarter</h1>
      <p>{tagline}</p>
      <div class="hero-actions">
        <a href="pages/signup.html" class="btn btn-primary">{cta}</a>
        <a href="app.html" class="btn btn-secondary">Live Demo</a>
      </div>
    </div>
  </section>
  <section class="features" id="features">
    <div class="container">
      <h2>Everything you need to succeed</h2>
      <div class="cards">{feat_cards}
      </div>
    </div>
  </section>
  <div class="container">
    <div class="cta-section">
      <h2>Ready to get started?</h2>
      <p style="margin-bottom:var(--space-lg);opacity:.9">Join thousands of teams using {name} today.</p>
      <a href="pages/signup.html" class="btn btn-white">{cta}</a>
    </div>
  </div>
  <footer>
    <div class="container">&copy; 2026 {name}. Built with CEOClaw.</div>
  </footer>
  <script>
    const nav=document.getElementById('navbar');
    window.addEventListener('scroll',()=>nav.classList.toggle('scrolled',scrollY>14));
    const obs=new IntersectionObserver(es=>es.forEach(e=>e.isIntersecting&&e.target.classList.add('visible')),{{threshold:.15}});
    document.querySelectorAll('.reveal').forEach(el=>obs.observe(el));
    document.querySelectorAll('.card').forEach(el=>obs.observe(el));
  </script>
</body>
</html>"""


def _render_aura_signup(name: str, slug: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Sign Up — {name}</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;600;700&family=Inter:wght@300;400;500&display=swap');
    :root{{--accent-gradient:linear-gradient(135deg,#3b82f6 0%,#8b5cf6 50%,#ec4899 100%);--color-bg:#f8fafc;--color-surface:#fff;--color-text:#0f172a;--color-muted:#64748b;--color-border:#e2e8f0;--color-primary:#3b82f6;--font-display:'Space Grotesk',sans-serif;--font-body:'Inter',sans-serif;--radius-md:12px;--radius-lg:20px;--space-md:clamp(.75rem,1.5vw,1.25rem);--space-lg:clamp(1rem,2vw,1.75rem);--space-xl:clamp(1.5rem,3vw,2.5rem);}}
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:var(--font-body);background:var(--color-bg);color:var(--color-text);min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:var(--space-xl)}}
    .brand{{font-family:var(--font-display);font-weight:700;font-size:1.3rem;background:var(--accent-gradient);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;margin-bottom:var(--space-xl);text-align:center}}
    .card{{background:var(--color-surface);border:1px solid var(--color-border);border-radius:var(--radius-lg);padding:var(--space-xl);width:100%;max-width:420px;box-shadow:0 4px 24px rgba(0,0,0,.07)}}
    h1{{font-family:var(--font-display);font-size:1.5rem;font-weight:700;margin-bottom:.5rem}}
    .subtitle{{color:var(--color-muted);font-size:.9rem;margin-bottom:var(--space-lg)}}
    label{{display:block;font-size:.85rem;font-weight:500;margin-bottom:.35rem}}
    input{{width:100%;padding:.625rem .875rem;border:1.5px solid var(--color-border);border-radius:var(--radius-md);font-family:var(--font-body);font-size:.9rem;transition:border-color .2s;min-height:44px}}
    input:focus{{outline:none;border-color:var(--color-primary);box-shadow:0 0 0 3px rgba(59,130,246,.1)}}
    .field{{margin-bottom:var(--space-md)}}
    .btn{{width:100%;min-height:44px;padding:.75rem;background:var(--accent-gradient);color:#fff;border:none;border-radius:var(--radius-md);font-family:var(--font-display);font-size:1rem;font-weight:600;cursor:pointer;transition:all .2s;margin-top:var(--space-sm)}}
    .btn:hover{{transform:scale(1.01);box-shadow:0 4px 20px rgba(139,92,246,.3)}}
    .footer-link{{text-align:center;margin-top:var(--space-md);font-size:.85rem;color:var(--color-muted)}}
    .footer-link a{{color:var(--color-primary);text-decoration:none;font-weight:500}}
  </style>
</head>
<body>
  <div class="brand">{name}</div>
  <div class="card">
    <h1>Create your account</h1>
    <p class="subtitle">Start your free trial — no credit card required.</p>
    <form id="signup-form" action="../app.html" method="get" onsubmit="return validateForm()">
      <div class="field">
        <label for="name">Full name</label>
        <input type="text" id="name" name="name" placeholder="Jane Smith" required aria-label="Full name">
      </div>
      <div class="field">
        <label for="email">Email address</label>
        <input type="email" id="email" name="email" placeholder="jane@company.com" required aria-label="Email address">
      </div>
      <div class="field">
        <label for="password">Password</label>
        <input type="password" id="password" name="password" placeholder="Min. 8 characters" required minlength="8" aria-label="Password">
      </div>
      <button type="submit" class="btn">Create free account</button>
    </form>
    <p class="footer-link">Already have an account? <a href="../index.html">Sign in</a></p>
  </div>
  <script>
    function validateForm(){{
      const e=document.getElementById('email'),p=document.getElementById('password');
      if(!e.value.includes('@')){{e.focus();return false;}}
      if(p.value.length<8){{p.focus();return false;}}
      return true;
    }}
  </script>
</body>
</html>"""


def _render_aura_app(name: str, features: list) -> str:
    feat_items = "".join(f"<li>&#10003; {f}</li>" for f in features[:5])
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{name} — Dashboard</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;600;700&family=Inter:wght@300;400;500&display=swap');
    :root{{--accent-gradient:linear-gradient(135deg,#3b82f6 0%,#8b5cf6 50%,#ec4899 100%);--color-bg:#f1f5f9;--color-surface:#fff;--color-sidebar:#0f172a;--color-text:#0f172a;--color-muted:#64748b;--color-border:#e2e8f0;--color-primary:#3b82f6;--font-display:'Space Grotesk',sans-serif;--font-body:'Inter',sans-serif;--radius-md:12px;--space-md:1rem;--space-lg:1.5rem;}}
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:var(--font-body);background:var(--color-bg);color:var(--color-text);min-height:100vh;display:flex}}
    .sidebar{{width:240px;background:var(--color-sidebar);color:#f8fafc;padding:var(--space-lg);display:flex;flex-direction:column;gap:var(--space-lg);min-height:100vh;flex-shrink:0}}
    .sidebar-brand{{font-family:var(--font-display);font-weight:700;font-size:1.1rem;background:var(--accent-gradient);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}}
    .sidebar-nav{{list-style:none;display:flex;flex-direction:column;gap:.5rem}}
    .sidebar-nav a{{display:flex;align-items:center;gap:.5rem;padding:.5rem .75rem;border-radius:8px;color:rgba(248,250,252,.7);text-decoration:none;font-size:.875rem;transition:all .2s;min-height:44px}}
    .sidebar-nav a:hover,.sidebar-nav a.active{{background:rgba(255,255,255,.1);color:#fff}}
    .main{{flex:1;padding:var(--space-lg);overflow-y:auto}}
    .top-bar{{display:flex;align-items:center;justify-content:space-between;margin-bottom:var(--space-lg)}}
    .top-bar h1{{font-family:var(--font-display);font-size:1.4rem;font-weight:700}}
    .metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:var(--space-md);margin-bottom:var(--space-lg)}}
    .metric-card{{background:var(--color-surface);border:1px solid var(--color-border);border-radius:var(--radius-md);padding:var(--space-md)}}
    .metric-label{{font-size:.8rem;color:var(--color-muted);margin-bottom:.25rem}}
    .metric-value{{font-family:var(--font-display);font-size:1.75rem;font-weight:700}}
    .metric-value.accent{{background:var(--accent-gradient);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}}
    .card{{background:var(--color-surface);border:1px solid var(--color-border);border-radius:var(--radius-md);padding:var(--space-lg)}}
    .card h2{{font-family:var(--font-display);font-size:1rem;font-weight:600;margin-bottom:var(--space-md)}}
    .feature-list{{list-style:none;display:flex;flex-direction:column;gap:.5rem}}
    .feature-list li{{font-size:.9rem;color:var(--color-muted);padding:.25rem 0}}
    .connect-card{{border:2px dashed var(--color-border);border-radius:var(--radius-md);padding:var(--space-lg);text-align:center;margin-top:var(--space-md)}}
    .connect-card input[type=password]{{width:100%;max-width:320px;padding:.5rem .75rem;border:1.5px solid var(--color-border);border-radius:8px;font-family:var(--font-body);margin-bottom:.75rem;min-height:44px}}
    @media(max-width:640px){{.sidebar{{display:none}}.main{{padding:var(--space-md)}}.metrics{{grid-template-columns:1fr 1fr}}}}
  </style>
</head>
<body>
  <aside class="sidebar">
    <div class="sidebar-brand">{name}</div>
    <ul class="sidebar-nav">
      <li><a href="#" class="active">&#128202; Dashboard</a></li>
      <li><a href="#">&#9889; Features</a></li>
      <li><a href="#">&#9881;&#65039; Settings</a></li>
      <li><a href="index.html">&#8592; Back to site</a></li>
    </ul>
  </aside>
  <main class="main">
    <div class="top-bar">
      <h1>Welcome to {name}</h1>
    </div>
    <div class="metrics">
      <div class="metric-card"><div class="metric-label">Active Users</div><div class="metric-value accent">0</div></div>
      <div class="metric-card"><div class="metric-label">This Week</div><div class="metric-value">—</div></div>
      <div class="metric-card"><div class="metric-label">Revenue</div><div class="metric-value">$0</div></div>
      <div class="metric-card"><div class="metric-label">Status</div><div class="metric-value" style="font-size:1rem;color:#10b981">&#9679; Live</div></div>
    </div>
    <div class="card">
      <h2>Platform features</h2>
      <ul class="feature-list">{feat_items}</ul>
    </div>
    <div class="connect-card">
      <p style="margin-bottom:.75rem;font-size:.9rem;color:var(--color-muted)">Connect your API to get started</p>
      <input type="password" placeholder="sk-..." aria-label="API token">
      <br><button style="padding:.5rem 1.25rem;background:var(--accent-gradient);color:#fff;border:none;border-radius:8px;font-weight:600;cursor:pointer;min-height:44px">Connect</button>
    </div>
  </main>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Heuristic template fallback
# ---------------------------------------------------------------------------


def _template_generate(
    slug: str,
    user_message: str,
    existing_files: dict[str, str] | None,
    llm_result: LLMResult,
) -> GenerationResult:
    """Used when LLM is unavailable or returns un-parseable output."""
    mode_label = llm_result.model_mode
    if llm_result.error:
        mode_label += f" ({llm_result.error[:60]})"

    from core.intent_parser import parse_intent
    intent = parse_intent(user_message)
    product_name = _extract_product_name(user_message, intent, slug)
    features = intent.get("core_features") or ["Dashboard", "Analytics", "Integrations"]
    target_user = intent.get("target_user") or "teams"
    cta = _extract_cta(user_message) or "Get Started Free"

    if existing_files and "index.html" in existing_files:
        modified = _apply_simple_edits(existing_files["index.html"], user_message)
        return GenerationResult(
            assistant_message=f"Applied edit. (Model: {mode_label})",
            changes=[FileChange(
                path=f"data/websites/{slug}/index.html",
                action="update",
                content=modified,
                summary="Heuristic edit applied",
            )],
            preview_route=f"/websites/{slug}/index",
            provider=llm_result.provider,
            model_mode=llm_result.model_mode,
        )

    tagline = f"The smart {(intent.get('product_type') or 'productivity').lower()} platform for {target_user}."

    return GenerationResult(
        assistant_message=f"Built **{product_name}** — landing page, signup, and app dashboard are ready.",
        changes=[
            FileChange(
                path=f"data/websites/{slug}/index.html",
                action="create",
                content=_render_aura_landing(product_name, tagline, features, cta, slug),
                summary="Created Aura landing page",
            ),
            FileChange(
                path=f"data/websites/{slug}/pages/signup.html",
                action="create",
                content=_render_aura_signup(product_name, slug),
                summary="Created signup page",
            ),
            FileChange(
                path=f"data/websites/{slug}/app.html",
                action="create",
                content=_render_aura_app(product_name, features),
                summary="Created app dashboard",
            ),
        ],
        preview_route=f"/websites/{slug}/index",
        provider=llm_result.provider,
        model_mode=llm_result.model_mode,
    )


def _provider_setup_hint(llm_result: LLMResult) -> str:
    """Return user-facing guidance based on fallback reason."""
    reason = (llm_result.fallback_reason or "").lower()
    if reason == "no_providers_configured":
        return "Add OPENAI_API_KEY or FLOCK_API_KEY for full LLM-powered editing."
    return (
        "LLM provider appears configured but request failed. "
        "Check API key validity, billing/quota, and network/endpoint settings."
    )


# ---------------------------------------------------------------------------
# Heuristic edit helpers
# ---------------------------------------------------------------------------


def _apply_simple_edits(html: str, message: str) -> str:
    msg_lower = message.lower()

    # "change X to Y"
    m = re.search(r"change\s+['\"]?(.+?)['\"]?\s+to\s+['\"]?(.+?)['\"]?\s*$",
                  message, re.IGNORECASE)
    if m:
        old_t, new_t = m.group(1).strip(), m.group(2).strip()
        modified = re.sub(re.escape(old_t), new_t, html, count=3, flags=re.IGNORECASE)
        if modified != html:
            return modified

    # CTA substitution
    cta_m = re.search(
        r"(?:cta|button|call.to.action)[^.]*?(?:say|to|as)\s+['\"]?([^'\"]+)['\"]?",
        msg_lower,
    )
    if cta_m:
        new_cta = cta_m.group(1).strip()
        html = re.sub(
            r'(<a[^>]+class=["\'][^"\']*cta[^"\']*["\'][^>]*>)([^<]+)(</a>)',
            lambda mx: mx.group(1) + new_cta + mx.group(3),
            html, flags=re.IGNORECASE,
        )

    if re.search(r"\bdark\b", msg_lower) and re.search(r"\b(mode|theme|make|style)\b", msg_lower):
        html = _inject_dark_mode(html)

    return html


def _inject_dark_mode(html: str) -> str:
    dark_css = (
        "\n    /* Dark mode */\n"
        "    body { background: #0f0f0f !important; color: #e5e7eb !important; }\n"
        "    header, nav { background: #1a1a1a !important; border-color: #2d2d2d !important; }\n"
        "    .feature-item, .card { background: #1e1e1e !important; border-color: #2d2d2d !important; }\n"
        "    .hero p, .audience { color: #9ca3af !important; }\n"
        "    footer { border-color: #2d2d2d !important; color: #6b7280 !important; }\n"
    )
    return html.replace("</style>", dark_css + "  </style>", 1) if "</style>" in html else html


def _extract_cta(message: str) -> Optional[str]:
    m = re.search(r"cta\s+(?:say|to|as|text)[:\s]+['\"]?([^'\"]+)['\"]?", message, re.IGNORECASE)
    return m.group(1).strip() if m else None
