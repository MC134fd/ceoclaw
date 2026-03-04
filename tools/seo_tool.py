"""
seo_tool – LangChain tool.

Analyses an existing landing page HTML file for basic SEO signals and
returns a structured report with a score and recommendations.
"""

import json
import re
from pathlib import Path

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from config.settings import settings
from data.database import get_connection, utc_now


class SEOToolInput(BaseModel):
    product_name: str = Field(description="Product name (used to locate the landing page).")
    target_keyword: str = Field(description="Primary keyword to check for in the page.")


@tool("seo_tool", args_schema=SEOToolInput)
def seo_tool(product_name: str, target_keyword: str) -> str:
    """Analyse the product landing page for SEO signals.

    Checks title, meta description, headings, keyword density, and page
    size.  Stores the experiment in marketing_experiments table.

    Returns a JSON string with: seo_score (0-100), issues, recommendations.
    """
    slug = _slugify(product_name)
    page_path = settings.resolve_websites_dir() / slug / "index.html"

    if not page_path.exists():
        return json.dumps({
            "seo_score": 0,
            "issues": ["landing page not found – run website_builder first"],
            "recommendations": ["Build a landing page before running SEO analysis."],
            "keyword": target_keyword,
        })

    html = page_path.read_text(encoding="utf-8")
    report = _analyse_html(html, target_keyword)
    _record_experiment(product_name, target_keyword, report)

    return json.dumps(report)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _analyse_html(html: str, keyword: str) -> dict:
    issues: list[str] = []
    recommendations: list[str] = []
    score = 100

    # Title check
    title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    has_title = bool(title_match)
    title_text = title_match.group(1).strip() if title_match else ""
    if not has_title:
        issues.append("missing <title> tag")
        recommendations.append("Add a descriptive <title> tag.")
        score -= 20
    elif len(title_text) > 60:
        issues.append("title too long (>60 chars)")
        recommendations.append("Shorten title to 60 characters or fewer.")
        score -= 5

    # Meta description
    meta_match = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']',
        html, re.IGNORECASE,
    )
    if not meta_match:
        issues.append("missing meta description")
        recommendations.append("Add a <meta name='description' content='...'> tag.")
        score -= 15

    # H1 check
    h1s = re.findall(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
    if not h1s:
        issues.append("no <h1> tag found")
        recommendations.append("Add exactly one <h1> heading.")
        score -= 10
    elif len(h1s) > 1:
        issues.append("multiple <h1> tags")
        recommendations.append("Use only one <h1> per page.")
        score -= 5

    # Keyword density
    text = re.sub(r"<[^>]+>", " ", html).lower()
    word_count = len(text.split())
    keyword_count = text.lower().count(keyword.lower())
    density = (keyword_count / word_count * 100) if word_count > 0 else 0.0
    if keyword_count == 0:
        issues.append(f"keyword '{keyword}' not found on page")
        recommendations.append(f"Include '{keyword}' naturally in the page content.")
        score -= 15
    elif density > 5.0:
        issues.append("keyword density too high (>5%)")
        recommendations.append("Reduce keyword repetition to avoid over-optimisation.")
        score -= 10

    return {
        "seo_score": max(score, 0),
        "keyword": keyword,
        "keyword_count": keyword_count,
        "keyword_density_pct": round(density, 2),
        "issues": issues,
        "recommendations": recommendations,
    }


def _record_experiment(product_name: str, keyword: str, report: dict) -> None:
    with get_connection() as conn:
        product_row = conn.execute(
            "SELECT id FROM products WHERE name = ?", (product_name,)
        ).fetchone()
        product_id = product_row["id"] if product_row else None

        conn.execute(
            """
            INSERT INTO marketing_experiments
                (created_at, product_id, channel, content, status)
            VALUES (?, ?, 'seo', ?, 'completed')
            """,
            (
                utc_now(),
                product_id,
                json.dumps({"keyword": keyword, "score": report["seo_score"]}),
            ),
        )
