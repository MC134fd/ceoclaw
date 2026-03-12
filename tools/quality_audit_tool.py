"""
quality_audit_tool – LangChain tool.

Performs a heuristic design + quality audit on a generated HTML product page.
Evaluates against Apple/Google/high-end SaaS standards.

Scoring dimensions (total 100):
  - Visual hierarchy     (20)  heading structure, whitespace, contrast
  - Typography           (15)  font stack, line-height, size scale
  - CTA clarity          (15)  button prominence, copy quality
  - Mobile responsiveness(15)  viewport meta, responsive CSS
  - Trust signals        (15)  social proof, privacy, contact
  - Performance basics   (10)  image optimization hints, script defer
  - Accessibility        (10)  alt text, aria roles, colour contrast hints

Returns JSON: score, grade, scorecard, critical_defects, improvement_plan
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from config.settings import settings
from data.database import persist_artifact


class QualityAuditInput(BaseModel):
    product_name: str = Field(description="Product name (used to locate generated HTML).")
    run_id: str = Field(default="", description="Run ID for artifact persistence.")
    cycle_count: int = Field(default=0, description="Cycle number.")


@tool("quality_audit_tool", args_schema=QualityAuditInput)
def quality_audit_tool(
    product_name: str,
    run_id: str = "",
    cycle_count: int = 0,
) -> str:
    """Audit a generated product page for design quality and UX polish.

    Returns JSON with: score (0-100), grade, scorecard, critical_defects,
    improvement_plan, premium_score.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", product_name.lower()).strip("-")
    page_path = settings.resolve_websites_dir() / slug / "index.html"

    if not page_path.exists():
        result = {
            "score": 0,
            "grade": "F",
            "error": "landing page not found — run product_build first",
            "scorecard": {},
            "critical_defects": ["landing_page_missing"],
            "improvement_plan": ["Build a landing page before auditing."],
            "premium_score": 0,
        }
        return json.dumps(result)

    html = page_path.read_text(encoding="utf-8")
    report = _audit_html(html, product_name)

    if run_id:
        try:
            persist_artifact(
                run_id=run_id,
                cycle_count=cycle_count,
                node_name="quality_auditor",
                artifact_type="quality_audit",
                content_summary=(
                    f"score={report['score']} grade={report['grade']} "
                    f"defects={len(report['critical_defects'])}"
                ),
            )
        except Exception:
            pass

    return json.dumps(report)


# ---------------------------------------------------------------------------
# Audit engine
# ---------------------------------------------------------------------------

def _audit_html(html: str, product_name: str) -> dict[str, Any]:
    scorecard: dict[str, dict[str, Any]] = {}
    defects: list[str] = []
    improvements: list[str] = []

    # ── Visual hierarchy (20) ────────────────────────────────────────────────
    vh_score = 20
    h1s = re.findall(r"<h1[^>]*>", html, re.IGNORECASE)
    h2s = re.findall(r"<h2[^>]*>", html, re.IGNORECASE)
    if len(h1s) != 1:
        deduct = 8
        vh_score -= deduct
        defects.append(f"h1_count={len(h1s)}_expected_1")
        improvements.append("Use exactly one <h1> as the hero headline.")
    if not h2s:
        vh_score -= 5
        improvements.append("Add <h2> section headings to create visual hierarchy.")
    if "margin" not in html and "padding" not in html:
        vh_score -= 4
        defects.append("no_whitespace_css")
        improvements.append("Add generous margin/padding (≥1.5rem) around sections.")
    # Check for dark/light contrast hint
    if "color:" not in html.lower() and "colour:" not in html.lower():
        vh_score -= 3
    scorecard["visual_hierarchy"] = {"score": max(vh_score, 0), "max": 20}

    # ── Typography (15) ─────────────────────────────────────────────────────
    ty_score = 15
    if "font-family" not in html.lower():
        ty_score -= 6
        defects.append("no_custom_font_family")
        improvements.append(
            "Set a premium font stack: e.g. font-family: 'Inter', system-ui, sans-serif"
        )
    if "line-height" not in html.lower():
        ty_score -= 4
        improvements.append("Set line-height: 1.6 for body text readability.")
    if "font-size" not in html.lower():
        ty_score -= 3
        improvements.append("Define a clear type scale (1rem body, 2.5rem h1, 1.5rem h2).")
    if "font-weight" not in html.lower():
        ty_score -= 2
    scorecard["typography"] = {"score": max(ty_score, 0), "max": 15}

    # ── CTA clarity (15) ────────────────────────────────────────────────────
    cta_score = 15
    buttons = re.findall(r"<(?:a|button)[^>]*class=[\"'][^\"']*cta[^\"']*[\"'][^>]*>", html, re.IGNORECASE)
    all_buttons = re.findall(r"<(?:a|button)[^>]*>", html, re.IGNORECASE)
    if not buttons and not all_buttons:
        cta_score -= 10
        defects.append("no_cta_button")
        improvements.append("Add a prominent CTA button above the fold.")
    elif not buttons:
        cta_score -= 4
        improvements.append("Style your CTA button with a distinct .cta class and high-contrast color.")
    # Check CTA is early in page (above fold)
    cta_pos = html.lower().find("cta")
    body_pos = html.lower().find("<body")
    if cta_pos > 0 and body_pos > 0 and (cta_pos - body_pos) > 2000:
        cta_score -= 4
        improvements.append("Move primary CTA above the fold (within first 600px).")
    if "free" not in html.lower() and "try" not in html.lower() and "start" not in html.lower():
        cta_score -= 2
        improvements.append("CTA copy should use action words: 'Start free', 'Try now', 'Get started'.")
    scorecard["cta_clarity"] = {"score": max(cta_score, 0), "max": 15}

    # ── Mobile responsiveness (15) ──────────────────────────────────────────
    mob_score = 15
    lower = html.lower()
    has_viewport = 'name="viewport"' in lower
    media_breakpoints = [int(v) for v in re.findall(r"@media\s*\(\s*max-width\s*:\s*(\d+)px\s*\)", lower)]
    has_media = bool(media_breakpoints)
    has_1024 = any(px <= 1024 for px in media_breakpoints)
    has_640 = any(px <= 640 for px in media_breakpoints)
    has_fluid = "clamp(" in lower or "minmax(" in lower or "vw" in lower
    has_anti_squish = (
        "flex-wrap" in lower
        or "minmax(" in lower
        or "overflow-wrap" in lower
        or "word-break" in lower
    )
    has_media_safe = "max-width: 100%" in lower
    has_overflow_guard = "overflow-x: hidden" in lower or "overflow-wrap" in lower

    if not has_viewport:
        mob_score -= 6
        defects.append("missing_viewport_meta")
        improvements.append('Add <meta name="viewport" content="width=device-width, initial-scale=1.0">.')
    if not has_media:
        mob_score -= 5
        defects.append("missing_breakpoints")
        improvements.append("Add responsive breakpoints for tablet and mobile views.")
    else:
        if not has_1024:
            mob_score -= 2
            improvements.append("Add a tablet breakpoint near max-width: 1024px.")
        if not has_640:
            mob_score -= 2
            improvements.append("Add a phone breakpoint near max-width: 640px.")
    if not has_fluid:
        mob_score -= 2
        defects.append("missing_fluid_sizing")
        improvements.append("Use fluid spacing/type tokens with clamp() and responsive units.")
    if not has_anti_squish:
        mob_score -= 2
        defects.append("missing_non_squish_rules")
        improvements.append("Use auto-fit/minmax grids or flex-wrap to prevent card/container squishing.")
    if not has_media_safe:
        mob_score -= 1
        defects.append("missing_media_max_width_guard")
        improvements.append("Set max-width: 100% for images/iframes/media elements.")
    if not has_overflow_guard:
        mob_score -= 1
        defects.append("possible_horizontal_overflow")
        improvements.append("Add overflow-safe text wrapping or overflow-x protection to avoid horizontal scroll.")

    fixed_width_risk = len(re.findall(r"\bwidth\s*:\s*(\d{3,4})px", lower))
    if fixed_width_risk >= 3:
        mob_score -= 2
        defects.append("fixed_width_layout_risk")
        improvements.append("Replace repeated fixed pixel widths with fluid widths and minmax constraints.")

    scorecard["mobile_responsiveness"] = {"score": max(mob_score, 0), "max": 15}

    # ── Trust signals (15) ─────────────────────────────────────────────────
    tr_score = 15
    trust_patterns = ["privacy", "secure", "trusted", "customer", "review", "testimonial",
                      "guarantee", "refund", "contact", "about"]
    found_trust = sum(1 for p in trust_patterns if p in html.lower())
    if found_trust == 0:
        tr_score -= 8
        defects.append("no_trust_signals")
        improvements.append("Add social proof: testimonials, user count, or a privacy statement.")
    elif found_trust < 2:
        tr_score -= 4
        improvements.append("Add more trust signals: logo bar, guarantees, or customer stats.")
    if "©" not in html and "copyright" not in html.lower():
        tr_score -= 3
        improvements.append("Add footer with copyright and privacy policy link.")
    if "https" not in html.lower():
        tr_score -= 2
    scorecard["trust_signals"] = {"score": max(tr_score, 0), "max": 15}

    # ── Performance basics (10) ─────────────────────────────────────────────
    perf_score = 10
    inline_scripts = re.findall(r"<script[^>]*>(?!.*src)", html, re.IGNORECASE)
    if len(inline_scripts) > 2:
        perf_score -= 3
        improvements.append("Minimize inline JS; prefer external scripts with defer/async.")
    inline_styles_count = len(re.findall(r"style=[\"']", html, re.IGNORECASE))
    if inline_styles_count > 10:
        perf_score -= 2
        improvements.append("Move inline styles to a <style> block or external CSS.")
    if "<img" in html.lower():
        if "loading=" not in html.lower():
            perf_score -= 3
            improvements.append("Add loading='lazy' to <img> tags.")
        if "alt=" not in html.lower():
            perf_score -= 2
    scorecard["performance"] = {"score": max(perf_score, 0), "max": 10}

    # ── Accessibility (10) ──────────────────────────────────────────────────
    a11y_score = 10
    if "lang=" not in html.lower():
        a11y_score -= 3
        defects.append("missing_lang_attribute")
        improvements.append('Add lang="en" to <html> element.')
    if "role=" not in html.lower() and "<nav" not in html.lower():
        a11y_score -= 3
        improvements.append("Add ARIA roles (role='main', role='navigation') for screen readers.")
    if "<input" in html.lower() and "<label" not in html.lower():
        a11y_score -= 4
        defects.append("inputs_without_labels")
        improvements.append("Associate every <input> with a <label> element.")
    scorecard["accessibility"] = {"score": max(a11y_score, 0), "max": 10}

    # ── Final tallying ───────────────────────────────────────────────────────
    total = sum(v["score"] for v in scorecard.values())
    grade = _grade(total)

    # Premium polish score: heavier weight on typography + visual hierarchy
    premium = int(
        scorecard["visual_hierarchy"]["score"] * 1.5
        + scorecard["typography"]["score"] * 1.8
        + scorecard["cta_clarity"]["score"] * 1.2
        + scorecard.get("trust_signals", {}).get("score", 0) * 1.0
    ) // 5

    # Prioritize improvements by severity
    priority_plan = _prioritize(improvements, defects)

    return {
        "score": total,
        "grade": grade,
        "premium_score": min(premium, 100),
        "scorecard": scorecard,
        "critical_defects": defects[:6],
        "improvement_plan": priority_plan[:8],
        "product_name": product_name,
    }


def _grade(score: int) -> str:
    if score >= 90: return "A+"
    if score >= 80: return "A"
    if score >= 70: return "B"
    if score >= 60: return "C"
    if score >= 50: return "D"
    return "F"


def _prioritize(improvements: list[str], defects: list[str]) -> list[str]:
    """Return improvements sorted: critical defect fixes first."""
    critical_fixes = [i for i in improvements if any(d.replace("_", " ") in i.lower() for d in defects)]
    rest = [i for i in improvements if i not in critical_fixes]
    return critical_fixes + rest
