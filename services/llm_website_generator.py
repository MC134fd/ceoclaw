"""
LLM-driven website generator.

Flow:
  1. Build system + history messages for the provider
  2. Call provider_router (Flock → OpenAI → mock)
  3. Parse structured JSON response  {assistant_message, product_name, files, notes}
  4. Validate / sanitize HTML via output_validator
  5. If LLM unavailable or output invalid → heuristic template fallback

The caller (api/server.py) is responsible for persisting files and
updating the session store.
"""

import json
import logging
import re
from typing import Optional

from services.output_validator import validate_files
from services.provider_router import LLMResult, _mock_response, call_llm

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert full-stack web developer and UX designer. \
You generate beautiful, production-quality, self-contained websites on demand.

OUTPUT FORMAT — return ONLY the following JSON object. \
No markdown fences, no prose outside the JSON:

{
  "assistant_message": "Brief 1-2 sentence description of what you built or changed",
  "product_name": "ShortProductName",
  "files": {
    "index.html": "<!DOCTYPE html>...complete self-contained HTML..."
  },
  "notes": ["optional technical note"]
}

REQUIREMENTS for generated HTML:
- Valid, complete HTML5 starting with <!DOCTYPE html>
- ALL CSS inline inside one <style> tag in <head> — no external stylesheets
- ALL JS inline in <script> tags — no external CDN required for core functionality
- Google Fonts may be loaded via @import inside the <style> block
- Mobile-first responsive design with CSS media queries
- Semantic HTML5: <header>, <main>, <section>, <nav>, <footer>, <article>
- Prominent, clearly labelled call-to-action button
- Professional, modern, visually polished design
- Good colour contrast (WCAG AA), readable typography, breathing whitespace

When MODIFYING existing HTML (provided in the user message):
- Apply the requested change precisely
- Preserve all working sections not mentioned in the request
- Return the COMPLETE modified HTML file — not a diff or a fragment
"""

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_website(
    user_message: str,
    history: list[dict],
    existing_html: Optional[str] = None,
    mock_mode: bool = False,
) -> dict:
    """Generate or update a website.

    Returns:
    {
        "assistant_message": str,
        "product_name": str,
        "files": {"index.html": str, ...},
        "notes": list[str],
        "provider": str,
        "model_mode": str,
        "warnings": list[str],
    }
    """
    if mock_mode:
        llm_result = _mock_response()
    else:
        messages = _build_messages(user_message, history, existing_html)
        llm_result = call_llm(messages)

    # If the LLM returned content, try to parse it
    if llm_result.content:
        parsed = _parse_response(llm_result.content)
        raw_files = parsed.get("files") or {}
        if raw_files:
            clean_files, warnings = validate_files(raw_files)
            if clean_files:
                return {
                    "assistant_message": parsed.get("assistant_message", "Website generated."),
                    "product_name": parsed.get("product_name", ""),
                    "files": clean_files,
                    "notes": parsed.get("notes", []),
                    "provider": llm_result.provider,
                    "model_mode": llm_result.model_mode,
                    "warnings": warnings,
                }
            logger.warning("LLM files failed validation: %s", warnings)

    # Heuristic template fallback
    return _template_generate(user_message, existing_html, llm_result)


# ---------------------------------------------------------------------------
# Message construction
# ---------------------------------------------------------------------------


def _build_messages(
    user_message: str,
    history: list[dict],
    existing_html: Optional[str],
) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": _SYSTEM_PROMPT}]

    # Include recent conversation history (last 10 turns = 5 exchanges)
    # Strip any existing-HTML blocks from old history to save tokens
    for msg in history[-10:]:
        content = msg["content"]
        # Trim long user messages that contained HTML context
        if msg["role"] == "user" and len(content) > 800:
            content = content[:800] + "\n[... prior HTML context truncated ...]"
        messages.append({"role": msg["role"], "content": content})

    # Build current user turn
    user_content = user_message
    if existing_html:
        html_snippet = existing_html[:6000]
        if len(existing_html) > 6000:
            html_snippet += "\n<!-- ... truncated ... -->"
        user_content = (
            f"{user_message}\n\n"
            f"--- CURRENT index.html (modify this per the request above) ---\n"
            f"{html_snippet}"
        )

    messages.append({"role": "user", "content": user_content})
    return messages


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _parse_response(content: str) -> dict:
    """Robustly extract JSON from LLM output."""
    content = content.strip()

    # 1. Direct JSON
    if content.startswith("{"):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

    # 2. Markdown code block  ```json {...} ```
    md = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if md:
        try:
            return json.loads(md.group(1))
        except json.JSONDecodeError:
            pass

    # 3. Largest { ... } span
    brace = re.search(r"\{.*\}", content, re.DOTALL)
    if brace:
        try:
            return json.loads(brace.group(0))
        except json.JSONDecodeError:
            pass

    # 4. Raw HTML fallback — model ignored format instructions
    if "<!doctype" in content.lower()[:100] or "<html" in content.lower()[:200]:
        logger.warning("LLM returned raw HTML; wrapping in expected schema")
        return {
            "assistant_message": "Generated website.",
            "product_name": "",
            "files": {"index.html": content},
            "notes": ["Model returned raw HTML — wrapped automatically."],
        }

    logger.warning("Could not parse LLM response (len=%d)", len(content))
    return {}


# ---------------------------------------------------------------------------
# Heuristic template fallback
# ---------------------------------------------------------------------------


def _template_generate(
    user_message: str,
    existing_html: Optional[str],
    llm_result: LLMResult,
) -> dict:
    """Used when LLM is unavailable or output fails validation."""
    mode_note = llm_result.model_mode
    if llm_result.error:
        mode_note += f" ({llm_result.error[:80]})"
    provider_hint = _provider_setup_hint(llm_result)

    # Iterative edit on existing HTML — apply simple substitutions
    if existing_html:
        modified = _apply_simple_edits(existing_html, user_message)
        return {
            "assistant_message": (
                f"Applied your edit in template mode ({mode_note}). "
                f"{provider_hint}"
            ),
            "product_name": "",
            "files": {"index.html": modified},
            "notes": ["Heuristic substitution — no LLM available."],
            "provider": llm_result.provider,
            "model_mode": llm_result.model_mode,
            "warnings": [],
        }

    # Fresh site from intent
    from core.intent_parser import parse_intent
    from tools.website_builder import _render_app_page, _render_html

    intent = parse_intent(user_message)
    product_name = intent.get("product_name") or "My App"
    features = intent.get("core_features") or ["Core feature", "Dashboard", "Analytics"]
    target_user = intent.get("target_user") or "users"
    tagline = f"The smarter {features[0].lower()} platform built for {target_user}."
    cta = _extract_cta(user_message) or "Get Started"

    html = _render_html(product_name, tagline, features[:5], cta, target_user)
    app_html = _render_app_page(product_name, features[:5])

    return {
        "assistant_message": (
            f"Built **{product_name}** from template ({mode_note}). "
            f"{provider_hint}"
        ),
        "product_name": product_name,
        "files": {"index.html": html, "app.html": app_html},
        "notes": [f"Template mode — {llm_result.model_mode}."],
        "provider": llm_result.provider,
        "model_mode": llm_result.model_mode,
        "warnings": [],
    }


def _provider_setup_hint(llm_result: LLMResult) -> str:
    """Return user-facing guidance based on fallback reason."""
    reason = (llm_result.fallback_reason or "").lower()
    if reason == "no_providers_configured":
        return "Set OPENAI_API_KEY or FLOCK_API_KEY for fully custom LLM-generated pages."
    return (
        "LLM provider appears configured but request failed. "
        "Check API key validity, billing/quota, and network/endpoint settings."
    )


# ---------------------------------------------------------------------------
# Simple edit helpers (template/mock mode only)
# ---------------------------------------------------------------------------


def _apply_simple_edits(html: str, message: str) -> str:
    """Heuristic text substitutions for common edit instructions."""
    msg_lower = message.lower()

    # "change X to Y"
    m = re.search(
        r"change\s+['\"]?(.+?)['\"]?\s+to\s+['\"]?(.+?)['\"]?\s*$",
        message,
        re.IGNORECASE,
    )
    if m:
        old_text, new_text = m.group(1).strip(), m.group(2).strip()
        modified = re.sub(re.escape(old_text), new_text, html, count=3, flags=re.IGNORECASE)
        if modified != html:
            return modified

    # CTA text: "CTA to X" / "button say X" / "CTA say X"
    cta_m = re.search(
        r"(?:cta|button|call.to.action)[^.]*?(?:say|to|as)\s+['\"]?([^'\"]+)['\"]?",
        msg_lower,
    )
    if cta_m:
        new_cta = cta_m.group(1).strip()
        html = re.sub(
            r'(<a[^>]+class=["\'][^"\']*cta[^"\']*["\'][^>]*>)([^<]+)(</a>)',
            lambda m: m.group(1) + new_cta + m.group(3),
            html,
            flags=re.IGNORECASE,
        )

    # Dark mode
    if re.search(r"\bdark\b", msg_lower) and re.search(
        r"\b(mode|theme|background|style|make)\b", msg_lower
    ):
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
        "    .signup-form input { background: #1e1e1e !important; border-color: #444 !important;"
        " color: #e5e7eb !important; }\n"
    )
    if "</style>" in html:
        return html.replace("</style>", dark_css + "  </style>", 1)
    return html


def _extract_cta(message: str) -> Optional[str]:
    m = re.search(
        r"cta\s+(?:say|to|as|text)[:\s]+['\"]?([^'\"]+)['\"]?", message, re.IGNORECASE
    )
    return m.group(1).strip() if m else None
