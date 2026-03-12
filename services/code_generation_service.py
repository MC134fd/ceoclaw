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

MANDATORY LANDING PAGE SECTIONS (all 6 required):
1. Sticky translucent navbar: backdrop-filter blur, brand + nav links + primary CTA button
2. Hero: display-font heading, domain-specific subheading, DUAL CTAs (filled + outlined),
   decorative radial gradient or mesh background element
3. Features: 3–5 cards with emoji icon + feature title (h3) + 2-sentence description
4. Social proof: 3 testimonial cards (avatar initials, name, role, domain-specific quote)
   OR a metrics strip with 3 domain-specific animated counters
5. Pre-footer CTA: bold headline + primary action (signup form or button)
6. Footer: brand, nav links, copyright with current year

INTERACTIVITY (vanilla JS, no external deps):
- Reveal-on-scroll for cards (.reveal class + IntersectionObserver)
- Sticky navbar scroll state (.scrolled class on scroll > 14px)
- Animated counters on proof stats (if metric strip included)
- If auth form: basic client-side validation (required fields, email format check)

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
"""

# Keep legacy alias for backward compat
_SYSTEM_PROMPT = _SYSTEM_PROMPT_BASE


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
            )
        else:
            logger.warning("LLM returned no usable changes (len=%d)", len(llm_result.content))

    # Heuristic fallback
    result = _template_generate(slug, user_message, existing_files, llm_result)
    result.operation_type = operation_type
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
# Heuristic template fallback
# ---------------------------------------------------------------------------


def _template_generate(
    slug: str,
    user_message: str,
    existing_files: dict[str, str] | None,
    llm_result: LLMResult,
) -> GenerationResult:
    """Used when LLM is unavailable or returns unparse-able output."""
    mode_label = llm_result.model_mode
    if llm_result.error:
        mode_label += f" ({llm_result.error[:60]})"
    provider_hint = _provider_setup_hint(llm_result)

    if existing_files and "index.html" in existing_files:
        modified = _apply_simple_edits(existing_files["index.html"], user_message)
        return GenerationResult(
            assistant_message=(
                f"Applied edit in template mode ({mode_label}). "
                f"{provider_hint}"
            ),
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

    # Fresh site
    from core.intent_parser import parse_intent
    from tools.website_builder import _render_app_page, _render_html

    intent = parse_intent(user_message)
    product_name = intent.get("product_name") or slug.replace("-", " ").title()
    features = intent.get("core_features") or ["Core feature", "Dashboard", "Analytics"]
    target_user = intent.get("target_user") or "users"
    tagline = f"The smarter {features[0].lower()} platform built for {target_user}."
    cta = _extract_cta(user_message) or "Get Started"

    return GenerationResult(
        assistant_message=(
            f"Built **{product_name}** from template ({mode_label}). "
            f"{provider_hint}"
        ),
        changes=[
            FileChange(
                path=f"data/websites/{slug}/index.html",
                action="create",
                content=_render_html(product_name, tagline, features[:5], cta, target_user),
                summary="Created landing page from template",
            ),
            FileChange(
                path=f"data/websites/{slug}/app.html",
                action="create",
                content=_render_app_page(product_name, features[:5]),
                summary="Created app scaffold from template",
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
