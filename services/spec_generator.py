"""
Spec generator — LLM produces ONLY structured JSON, never HTML/CSS/JS.

The system prompt constrains the model to output a strict SiteSpec JSON.
The output is validated by site_spec.validate_spec() before it ever
reaches the renderer.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from services.provider_router import call_llm
from services.site_spec import SiteSpec, validate_spec

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt — forces JSON-only output
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a website content architect.  Your ONLY job is to produce a \
structured JSON specification for a website.

ABSOLUTE RULES:
- Return ONLY valid JSON.  No markdown fences.  No commentary.  No HTML.
- Your entire response must be parseable by JSON.parse().
- You must NOT generate any HTML, CSS, or JavaScript.  Only JSON.

OUTPUT SCHEMA (follow exactly):
{
  "site": {
    "title":          "string — the website/product name",
    "description":    "string — one sentence meta description",
    "theme":          "light" or "dark",
    "primaryColor":   "#hex — brand primary color",
    "secondaryColor": "#hex — secondary accent color",
    "accentColor":    "#hex — tertiary accent (optional, defaults to #ec4899)",
    "displayFont":    "Google Font name for headings (e.g. Space Grotesk, Syne, Outfit)",
    "bodyFont":       "Google Font name for body (e.g. Inter, DM Sans, Manrope)",
    "logoText":       "string — brand name shown in navbar"
  },
  "navigation": {
    "links": [
      { "label": "Features", "href": "#features" },
      { "label": "Pricing", "href": "#pricing" }
    ],
    "ctaButton": { "label": "Get Started", "href": "pages/signup.html" }
  },
  "pages": [
    {
      "path":     "index.html",
      "title":    "string — page title",
      "type":     "landing",
      "sections": [ ... ]
    },
    {
      "path":  "pages/signup.html",
      "title": "Sign Up",
      "type":  "auth",
      "props": {
        "formType":    "signup",
        "heading":     "Create your account",
        "fields":      ["name", "email", "password"],
        "submitText":  "Get Started",
        "altLinkText": "Already have an account? Sign in",
        "altLinkHref": "../index.html"
      }
    },
    {
      "path":  "app.html",
      "title": "Dashboard",
      "type":  "dashboard",
      "props": {
        "welcomeHeading": "Welcome to [Product]",
        "metrics": [
          { "label": "Active Users", "value": "1,234", "icon": "👥" },
          { "label": "Revenue",      "value": "$12.5k", "icon": "💰" },
          { "label": "Growth",       "value": "+23%",   "icon": "📈" },
          { "label": "Rating",       "value": "4.9",    "icon": "⭐" }
        ],
        "sidebarLinks": [
          { "label": "Dashboard",  "href": "#", "icon": "📊" },
          { "label": "Analytics",  "href": "#", "icon": "📈" },
          { "label": "Settings",   "href": "#", "icon": "⚙️" }
        ]
      }
    }
  ]
}

SECTION TYPES AND THEIR PROPS (use these for "landing" page sections):

"hero":
{
  "headline":         "string — bold value proposition, NOT generic",
  "subheadline":      "string — one sentence elaboration",
  "ctaText":          "string — action verb (e.g. Start Free, Try Now)",
  "ctaHref":          "pages/signup.html",
  "secondaryCtaText": "string (optional — e.g. Learn More)",
  "secondaryCtaHref": "#features"
}

"features":
{
  "heading":    "string",
  "subheading": "string (optional)",
  "items": [
    { "icon": "emoji", "title": "string", "description": "string" }
  ]
}
Provide 3-6 feature items.  Each must be specific to THIS product.

"cta":
{
  "heading":    "string — compelling call to action",
  "description":"string",
  "buttonText": "string",
  "buttonHref": "pages/signup.html"
}

"testimonials":
{
  "heading": "string",
  "items": [
    { "name": "string", "role": "string (e.g. CEO at Company)", "quote": "string" }
  ]
}
Provide 3 testimonials with realistic names and specific product praise.

"pricing":
{
  "heading":    "string",
  "subheading": "string (optional)",
  "tiers": [
    {
      "name":        "Free",
      "price":       "$0",
      "period":      "/mo",
      "description": "string",
      "features":    ["feature 1", "feature 2"],
      "ctaText":     "Start Free",
      "highlighted": false
    }
  ]
}
Provide exactly 3 tiers.  Mark the middle tier as highlighted: true.

"faq":
{
  "heading": "string",
  "items": [
    { "question": "string", "answer": "string" }
  ]
}
Provide 4-6 FAQ items.

"stats":
{
  "heading": "string (optional)",
  "items": [
    { "value": "10K+", "label": "Active Users" }
  ]
}

"how_it_works":
{
  "heading": "string",
  "steps": [
    { "step": 1, "title": "string", "description": "string" }
  ]
}

"footer":
{
  "brand":     "string — brand name",
  "tagline":   "string (optional)",
  "links":     [{ "label": "string", "href": "string" }],
  "copyright": "© 2026 Brand. All rights reserved."
}

HARD CONSTRAINTS:
- The landing page (index.html) MUST contain at minimum: hero, features, cta.
- Recommended order: hero → stats/how_it_works → features → testimonials → pricing → cta → faq → footer.
- No empty strings for required fields.
- No fields outside the schema.
- All copy must be specific to the product — no generic placeholder text.
- BANNED phrases: "revolutionize", "game-changer", "seamlessly", "cutting-edge", \
"next-level", "supercharge", "unlock your potential", "leverage", "synergy".
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_spec(
    message: str,
    history: list[dict[str, str]],
    slug: str,
    design_system: dict[str, Any] | None = None,
) -> SiteSpec:
    """Generate a validated SiteSpec from user message via LLM.

    The LLM is constrained to output ONLY JSON.  The response is validated
    and normalised before returning.
    """
    messages: list[dict[str, str]] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
    ]

    # Trim history to last 6 messages
    for msg in history[-6:]:
        content = msg.get("content", "")
        if msg.get("role") == "assistant" and len(content) > 200:
            content = content[:200] + "\n[...]"
        messages.append({"role": msg["role"], "content": content})

    user_prompt = (
        f"Product slug: {slug}\n\n"
        f"User description:\n{message}\n\n"
        "Generate the complete SiteSpec JSON now.  "
        "Include at least: index.html (landing), pages/signup.html (auth), app.html (dashboard).  "
        "JSON only — no other text."
    )

    # Inject design hints if available
    if design_system:
        colors = design_system.get("colors", {})
        if colors:
            user_prompt += (
                f"\n\nDesign hints (use these colors):\n"
                f"  primary: {colors.get('primary', '#3b82f6')}\n"
                f"  secondary: {colors.get('secondary', '#8b5cf6')}\n"
                f"  theme: {'dark' if 'dark' in design_system.get('palette_name', '') else 'light'}\n"
                f"  display font: {design_system.get('display_font', 'Space Grotesk')}\n"
                f"  body font: {design_system.get('body_font', 'Inter')}\n"
            )

    messages.append({"role": "user", "content": user_prompt})

    llm_result = call_llm(messages, max_tokens=4000)

    if llm_result.fallback_used or not llm_result.content:
        logger.warning("Spec generation LLM call failed: %s", llm_result.fallback_reason)
        return _fallback_spec(slug, message)

    raw = _extract_json(llm_result.content)
    if not raw:
        logger.warning("Could not parse JSON from LLM output (len=%d)", len(llm_result.content))
        return _fallback_spec(slug, message)

    try:
        spec = validate_spec(raw)
        logger.info("Spec generated: title=%r, %d pages", spec.site.title, len(spec.pages))
        return spec
    except Exception as exc:
        logger.warning("Spec validation failed: %s — using fallback", exc)
        return _fallback_spec(slug, message)


# ---------------------------------------------------------------------------
# JSON extraction from LLM output
# ---------------------------------------------------------------------------

def _extract_json(content: str) -> dict[str, Any] | None:
    """Robustly extract a JSON object from LLM output."""
    text = content.strip()

    # Try 1: direct parse
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    # Try 2: markdown fences
    md = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if md:
        try:
            return json.loads(md.group(1))
        except json.JSONDecodeError:
            pass

    # Try 3: first { to last }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    return None


# ---------------------------------------------------------------------------
# Fallback spec (when LLM fails)
# ---------------------------------------------------------------------------

def _fallback_spec(slug: str, message: str) -> SiteSpec:
    """Build a minimal but valid spec from the slug and message."""
    brand = slug.replace("-", " ").title()
    raw: dict[str, Any] = {
        "site": {
            "title": brand,
            "description": f"{brand} — {message[:80]}",
            "theme": "light",
            "primaryColor": "#3b82f6",
            "secondaryColor": "#8b5cf6",
            "accentColor": "#ec4899",
            "displayFont": "Space Grotesk",
            "bodyFont": "Inter",
            "logoText": brand,
        },
        "navigation": {
            "links": [
                {"label": "Features", "href": "#features"},
                {"label": "Pricing", "href": "#pricing"},
            ],
            "ctaButton": {"label": "Get Started", "href": "pages/signup.html"},
        },
        "pages": [
            {
                "path": "index.html",
                "title": brand,
                "type": "landing",
                "sections": [
                    {
                        "type": "hero",
                        "props": {
                            "headline": f"Welcome to {brand}",
                            "subheadline": message[:120] if message else f"{brand} helps you get things done.",
                            "ctaText": "Get Started",
                            "ctaHref": "pages/signup.html",
                            "secondaryCtaText": "Learn More",
                            "secondaryCtaHref": "#features",
                        },
                    },
                    {
                        "type": "features",
                        "props": {
                            "heading": f"Why {brand}?",
                            "items": [
                                {"icon": "🚀", "title": "Fast Setup", "description": "Get started in minutes, not hours."},
                                {"icon": "🔒", "title": "Secure", "description": "Enterprise-grade security built in."},
                                {"icon": "📊", "title": "Analytics", "description": "Real-time insights at your fingertips."},
                            ],
                        },
                    },
                    {
                        "type": "cta",
                        "props": {
                            "heading": f"Ready to try {brand}?",
                            "description": "Start your free trial today.",
                            "buttonText": "Get Started Free",
                            "buttonHref": "pages/signup.html",
                        },
                    },
                    {
                        "type": "footer",
                        "props": {
                            "brand": brand,
                            "copyright": f"© 2026 {brand}. All rights reserved.",
                        },
                    },
                ],
            },
            {
                "path": "pages/signup.html",
                "title": "Sign Up",
                "type": "auth",
                "props": {
                    "formType": "signup",
                    "heading": "Create your account",
                    "fields": ["name", "email", "password"],
                    "submitText": "Get Started",
                    "altLinkText": "Already have an account? Sign in",
                    "altLinkHref": "../index.html",
                },
            },
            {
                "path": "app.html",
                "title": "Dashboard",
                "type": "dashboard",
                "props": {
                    "welcomeHeading": f"Welcome to {brand}",
                    "metrics": [
                        {"label": "Users", "value": "0", "icon": "👥"},
                        {"label": "Revenue", "value": "$0", "icon": "💰"},
                        {"label": "Growth", "value": "0%", "icon": "📈"},
                        {"label": "Rating", "value": "5.0", "icon": "⭐"},
                    ],
                    "sidebarLinks": [
                        {"label": "Dashboard", "href": "#", "icon": "📊"},
                        {"label": "Settings", "href": "#", "icon": "⚙️"},
                    ],
                },
            },
        ],
    }
    return validate_spec(raw)
