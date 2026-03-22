"""
Spec editor — handles all edits by mutating the JSON spec, NOT the HTML.

Edit types:
  1. Direct style mutations  (color, font, theme) → zero LLM involvement
  2. Direct content mutations (headline text, CTA text) → zero LLM involvement
  3. LLM-assisted mutations   (add section, rewrite copy) → LLM outputs JSON patch

After every edit the spec is re-validated and the renderer produces
fresh HTML deterministically.
"""
from __future__ import annotations

import json
import logging
import re
from copy import deepcopy
from typing import Any

from services.provider_router import call_llm
from services.site_spec import (
    SECTION_TYPES,
    Section,
    SiteSpec,
    validate_spec,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Color name → hex lookup
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

_DARK_PALETTE = {
    "bgColor": "#0f172a", "surfaceColor": "#1e293b", "textColor": "#f8fafc",
    "mutedColor": "#94a3b8", "borderColor": "#334155",
}
_LIGHT_PALETTE = {
    "bgColor": "#f8fafc", "surfaceColor": "#ffffff", "textColor": "#0f172a",
    "mutedColor": "#64748b", "borderColor": "#e2e8f0",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def edit_spec(
    spec: SiteSpec,
    message: str,
    history: list[dict[str, str]] | None = None,
) -> SiteSpec:
    """Apply an edit to the spec based on the user's message.

    Tries direct mutations first (instant, deterministic).
    Falls back to LLM-assisted patch for complex edits.
    Always returns a validated spec.
    """
    # Try direct mutations first — zero LLM cost, zero latency
    result = _try_direct_edit(spec, message)
    if result is not None:
        logger.info("Direct spec edit applied for: %s", message[:60])
        return result

    # LLM-assisted edit — generates a JSON patch
    result = _llm_assisted_edit(spec, message, history or [])
    if result is not None:
        logger.info("LLM-assisted spec edit applied for: %s", message[:60])
        return result

    logger.warning("No edit applied for: %s", message[:60])
    return spec


# ---------------------------------------------------------------------------
# Direct edits (no LLM)
# ---------------------------------------------------------------------------

def _try_direct_edit(spec: SiteSpec, message: str) -> SiteSpec | None:
    """Attempt a direct spec mutation. Returns None if not applicable."""
    msg = message.lower().strip()
    new_spec = deepcopy(spec)

    # ── Primary color change ──
    color = _detect_color_change(msg)
    if color:
        new_spec.site.primaryColor = color
        return _revalidate(new_spec)

    # ── Background color change ──
    bg_match = re.search(
        r"(?:change|set|make|update)\s+(?:the\s+)?(?:background|bg)\s+(?:color\s+)?(?:to\s+)?(.+)",
        msg,
    )
    if bg_match:
        hex_val = _resolve_color(bg_match.group(1).strip().rstrip("."))
        if hex_val:
            new_spec.site.bgColor = hex_val
            return _revalidate(new_spec)

    # ── Dark mode ──
    if re.search(r"\bdark\s*(?:mode|theme)\b", msg) or re.search(r"\bmake\b.*\bdark\b", msg):
        new_spec.site.theme = "dark"
        for key, val in _DARK_PALETTE.items():
            setattr(new_spec.site, key, val)
        return _revalidate(new_spec)

    # ── Light mode ──
    if re.search(r"\blight\s*(?:mode|theme)\b", msg) or re.search(r"\bmake\b.*\blight\b", msg):
        new_spec.site.theme = "light"
        for key, val in _LIGHT_PALETTE.items():
            setattr(new_spec.site, key, val)
        return _revalidate(new_spec)

    # ── Font change ──
    font_match = re.search(
        r"(?:change|set|use|switch)\s+(?:the\s+)?(?:font|typeface)\s+(?:to\s+)?['\"]?([^'\"]+?)['\"]?\s*$",
        msg,
    )
    if font_match:
        font_name = font_match.group(1).strip().title()
        new_spec.site.displayFont = font_name
        return _revalidate(new_spec)

    # ── Change title / brand name ──
    title_match = re.search(
        r"(?:change|set|rename|update)\s+(?:the\s+)?(?:title|name|brand)\s+(?:to\s+)['\"]?(.+?)['\"]?\s*$",
        message, re.IGNORECASE,
    )
    if title_match:
        new_title = title_match.group(1).strip()
        new_spec.site.title = new_title
        new_spec.site.logoText = new_title
        return _revalidate(new_spec)

    # ── Change headline ──
    headline_match = re.search(
        r"(?:change|set|update)\s+(?:the\s+)?(?:hero\s+)?(?:headline|heading|title)\s+(?:to\s+)['\"]?(.+?)['\"]?\s*$",
        message, re.IGNORECASE,
    )
    if headline_match:
        new_headline = headline_match.group(1).strip()
        for page in new_spec.pages:
            for section in page.sections:
                if section.type == "hero":
                    section.props["headline"] = new_headline
                    return _revalidate(new_spec)

    # ── Change CTA text ──
    cta_match = re.search(
        r"(?:change|set|update)\s+(?:the\s+)?(?:cta|button)\s+(?:text\s+)?(?:to\s+)['\"]?(.+?)['\"]?\s*$",
        message, re.IGNORECASE,
    )
    if cta_match:
        new_cta = cta_match.group(1).strip()
        for page in new_spec.pages:
            for section in page.sections:
                if section.type == "hero":
                    section.props["ctaText"] = new_cta
                elif section.type == "cta":
                    section.props["buttonText"] = new_cta
        new_spec.navigation.ctaButton.label = new_cta
        return _revalidate(new_spec)

    # ── Remove a section ──
    remove_match = re.search(
        r"(?:remove|delete|drop)\s+(?:the\s+)?(" + "|".join(SECTION_TYPES) + r")\s*(?:section)?",
        msg,
    )
    if remove_match:
        target = remove_match.group(1)
        for page in new_spec.pages:
            page.sections = [s for s in page.sections if s.type != target]
        return _revalidate(new_spec)

    # ── Generic "make it <color>" ──
    if re.search(r"\b(?:make|turn)\b", msg):
        stripped = re.sub(r"\s*(?:now|please|!|\.)+\s*$", "", msg).strip()
        words = stripped.split()
        for n in (2, 1):
            if len(words) >= n:
                candidate = " ".join(words[-n:])
                hex_val = _resolve_color(candidate)
                if hex_val:
                    new_spec.site.primaryColor = hex_val
                    return _revalidate(new_spec)

    return None


def _detect_color_change(msg: str) -> str | None:
    """Detect a primary color change request, return hex or None."""
    patterns = [
        r"(?:change|set|make|update)\s+(?:the\s+)?(?:primary\s+)?(?:color|colour)\s+(?:to\s+)?(.+)",
        r"(?:change|switch)\s+.*?\s+to\s+(\w+(?:\s+\w+)?)\s*(?:now|please|!|\.)*\s*$",
    ]
    for pattern in patterns:
        m = re.search(pattern, msg)
        if m:
            target = m.group(1).strip().rstrip(".")
            hex_val = _resolve_color(target)
            if hex_val:
                return hex_val
    return None


def _resolve_color(text: str) -> str | None:
    text = text.strip().lower()
    hex_m = _HEX_RE.search(text)
    if hex_m:
        return hex_m.group(0)
    return _COLOR_NAMES.get(text)


def _revalidate(spec: SiteSpec) -> SiteSpec:
    """Re-validate a mutated spec through the normalisation pipeline."""
    return validate_spec(spec.model_dump())


# ---------------------------------------------------------------------------
# LLM-assisted edits (for complex changes)
# ---------------------------------------------------------------------------

_EDIT_SYSTEM_PROMPT = """\
You are a website spec editor.  You modify a structured JSON website specification \
based on user requests.

You receive the CURRENT spec and a user edit request.
You MUST return the COMPLETE updated spec as valid JSON.

RULES:
- Return ONLY valid JSON.  No markdown, no commentary.
- Apply EXACTLY what was requested — no more, no less.
- NEVER remove sections that were not mentioned in the request.
- NEVER change colors, fonts, or other design tokens unless explicitly asked.
- For "add a section" requests: insert the new section at the natural position.
- For content changes: update only the specific text fields mentioned.
- Preserve ALL existing structure, sections, and content not being changed.
- The output must follow the exact same schema as the input.
"""


def _llm_assisted_edit(
    spec: SiteSpec,
    message: str,
    history: list[dict[str, str]],
) -> SiteSpec | None:
    """Use LLM to generate a spec patch for complex edits."""
    current_spec_json = spec.model_dump_json(indent=2)

    # Truncate if very large (shouldn't be, specs are compact)
    if len(current_spec_json) > 15000:
        current_spec_json = current_spec_json[:15000] + "\n... (truncated)"

    messages: list[dict[str, str]] = [
        {"role": "system", "content": _EDIT_SYSTEM_PROMPT},
    ]

    for msg in history[-4:]:
        content = msg.get("content", "")
        if msg.get("role") == "assistant" and len(content) > 200:
            content = content[:200] + "\n[...]"
        messages.append({"role": msg["role"], "content": content})

    user_prompt = (
        f"CURRENT SPEC:\n{current_spec_json}\n\n"
        f"USER REQUEST: {message}\n\n"
        "Apply the requested change to the spec and return the COMPLETE updated JSON.  "
        "Do NOT remove any sections, pages, or content not mentioned in the request.  "
        "JSON only."
    )
    messages.append({"role": "user", "content": user_prompt})

    llm_result = call_llm(messages, max_tokens=6000)
    if llm_result.fallback_used or not llm_result.content:
        logger.warning("LLM edit failed: %s", llm_result.fallback_reason)
        return None

    raw = _extract_json(llm_result.content)
    if not raw:
        logger.warning("Could not parse JSON from LLM edit output")
        return None

    try:
        edited = validate_spec(raw)
        # Safety check: don't accept edits that remove too many sections
        orig_section_count = sum(len(p.sections) for p in spec.pages)
        new_section_count = sum(len(p.sections) for p in edited.pages)
        if orig_section_count > 0 and new_section_count < orig_section_count * 0.5:
            logger.warning(
                "LLM edit removed too many sections (%d → %d), rejecting",
                orig_section_count, new_section_count,
            )
            return None
        return edited
    except Exception as exc:
        logger.warning("Spec validation failed after LLM edit: %s", exc)
        return None


def _extract_json(content: str) -> dict[str, Any] | None:
    """Extract JSON from LLM output."""
    text = content.strip()
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
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    return None
