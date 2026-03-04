"""
website_builder – LangChain tool.

Generates a minimal HTML landing page for a product and writes it to the
data/websites/ directory.  Records the landing page path in the products
table.
"""

import json
from pathlib import Path

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from config.settings import settings
from data.database import get_connection, utc_now


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------

class WebsiteBuilderInput(BaseModel):
    product_name: str = Field(description="URL-safe product name (slug).")
    tagline: str = Field(description="One-sentence value proposition.")
    features: list[str] = Field(
        default_factory=list,
        description="Up to five bullet-point features.",
    )
    cta_text: str = Field(default="Get Early Access", description="Call-to-action button text.")


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------

@tool("website_builder", args_schema=WebsiteBuilderInput)
def website_builder_tool(
    product_name: str,
    tagline: str,
    features: list[str],
    cta_text: str = "Get Early Access",
) -> str:
    """Build or update an HTML landing page for a product.

    Writes the page to data/websites/<product_name>/index.html and
    upserts a record in the products table.

    Returns a JSON string with keys: status, path, product_name.
    """
    websites_dir = settings.resolve_websites_dir()
    slug = _slugify(product_name)
    page_dir = websites_dir / slug
    page_dir.mkdir(parents=True, exist_ok=True)
    page_path = page_dir / "index.html"

    html = _render_html(product_name, tagline, features[:5], cta_text)
    page_path.write_text(html, encoding="utf-8")

    relative_path = str(page_path.relative_to(settings.resolve_websites_dir().parent.parent))
    _upsert_product(product_name, relative_path)

    return json.dumps({
        "status": "success",
        "path": relative_path,
        "product_name": product_name,
        "slug": slug,
    })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify(name: str) -> str:
    """Convert a product name to a lowercase hyphenated slug."""
    import re
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _render_html(
    product_name: str,
    tagline: str,
    features: list[str],
    cta_text: str,
) -> str:
    features_html = "\n".join(f"  <li>{f}</li>" for f in features)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="{tagline}">
  <title>{product_name}</title>
  <style>
    body {{ font-family: sans-serif; max-width: 640px; margin: 4rem auto; padding: 0 1rem; }}
    h1   {{ font-size: 2rem; }}
    ul   {{ line-height: 2; }}
    .cta {{ display: inline-block; margin-top: 2rem; padding: 0.75rem 2rem;
             background: #0070f3; color: #fff; border-radius: 6px;
             text-decoration: none; font-weight: bold; }}
  </style>
</head>
<body>
  <h1>{product_name}</h1>
  <p>{tagline}</p>
  <ul>
{features_html}
  </ul>
  <a class="cta" href="#signup">{cta_text}</a>
  <form id="signup" style="margin-top:2rem;">
    <input type="email" placeholder="your@email.com" required>
    <button type="submit">Join</button>
  </form>
</body>
</html>
"""


def _upsert_product(product_name: str, landing_page_path: str) -> None:
    """Insert a products row if none exists for this name."""
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM products WHERE name = ?", (product_name,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE products SET landing_page_path = ?, status = 'active' WHERE name = ?",
                (landing_page_path, product_name),
            )
        else:
            conn.execute(
                """
                INSERT INTO products (created_at, name, landing_page_path, status)
                VALUES (?, ?, ?, 'active')
                """,
                (utc_now(), product_name, landing_page_path),
            )
