"""
website_builder – LangChain tool.

Generates a polished HTML landing page + app scaffold for a product and writes it to the
data/websites/ directory.  Records the landing page path in the products table.

Template design principles:
- Product-specific copy derived from product name / tagline / features
- Category-aware color palette (health, finance, devtools, edtech, consumer, saas)
- Integration-ready placeholders (auth form, API token card)
- Emoji feature icons + titles — no generic numbered cards
- Responsive from 320px up with clamp()-based spacing
"""

import json
import re
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
    target_user: str = Field(default="", description="Target user persona.")
    endpoint_manifest: list[str] = Field(
        default_factory=list,
        description="API endpoint paths to display in the app page.",
    )


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------

@tool("website_builder", args_schema=WebsiteBuilderInput)
def website_builder_tool(
    product_name: str,
    tagline: str,
    features: list[str],
    cta_text: str = "Get Early Access",
    target_user: str = "",
    endpoint_manifest: list[str] | None = None,
) -> str:
    """Build or update an HTML landing page + app scaffold for a product.

    Writes:
      data/websites/<slug>/index.html  — landing page
      data/websites/<slug>/app.html    — basic app page
      data/websites/<slug>/endpoints.json — API endpoint manifest

    Upserts a record in the products table.

    Returns a JSON string with keys: status, path, app_path,
    endpoint_manifest, product_name, slug.
    """
    websites_dir = settings.resolve_websites_dir()
    slug = _slugify(product_name)
    page_dir = websites_dir / slug
    page_dir.mkdir(parents=True, exist_ok=True)

    # Landing page
    page_path = page_dir / "index.html"
    html = _render_html(product_name, tagline, features[:5], cta_text, target_user)
    page_path.write_text(html, encoding="utf-8")

    # App page
    app_path = page_dir / "app.html"
    app_html = _render_app_page(product_name, features[:5])
    app_path.write_text(app_html, encoding="utf-8")

    # Endpoint manifest
    endpoints = endpoint_manifest or ["/api/health", "/api/data"]
    manifest_path = page_dir / "endpoints.json"
    manifest_path.write_text(
        json.dumps({"product": product_name, "endpoints": endpoints}, indent=2),
        encoding="utf-8",
    )

    base = settings.resolve_websites_dir().parent.parent
    relative_path = str(page_path.relative_to(base))
    relative_app = str(app_path.relative_to(base))

    _upsert_product(product_name, relative_path)

    return json.dumps({
        "status": "success",
        "path": relative_path,
        "app_path": relative_app,
        "endpoint_manifest": endpoints,
        "product_name": product_name,
        "slug": slug,
    })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify(name: str) -> str:
    """Convert a product name to a lowercase hyphenated slug."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


# ---------------------------------------------------------------------------
# Product category detection + visual identity
# ---------------------------------------------------------------------------

def _detect_category(product_name: str, tagline: str, features: list[str]) -> str:
    """Classify product into a visual-identity category from keywords."""
    combined = (product_name + " " + tagline + " " + " ".join(features)).lower()
    if any(w in combined for w in [
        "calorie", "food", "nutrition", "health", "fitness", "workout",
        "diet", "macro", "meal", "weight", "exercise", "wellness",
    ]):
        return "health"
    if any(w in combined for w in [
        "finance", "invoice", "accounting", "expense", "budget",
        "payment", "money", "tax", "ledger", "bookkeeping",
    ]):
        return "finance"
    if any(w in combined for w in [
        "crm", "lead", "sales", "pipeline", "deal", "contact",
        "customer", "prospect", "outreach",
    ]):
        return "crm"
    if any(w in combined for w in [
        "code", "developer", "api", "deploy", "github", "ci",
        "devops", "cli", "terminal", "cloud", "infra",
    ]):
        return "devtools"
    if any(w in combined for w in [
        "learn", "course", "education", "tutorial", "student",
        "teacher", "quiz", "lms", "lesson", "classroom",
    ]):
        return "edtech"
    if any(w in combined for w in [
        "ecommerce", "shop", "store", "cart", "marketplace",
        "product", "inventory", "order",
    ]):
        return "ecommerce"
    return "saas"


def _category_palette(category: str) -> dict:
    """Return CSS variable values for a product category's visual identity."""
    palettes = {
        "health": {
            "primary": "#10b981", "secondary": "#34d399", "tertiary": "#6ee7b7",
            "bg": "#030d08", "surface": "#0a1a10", "border": "rgba(16,185,129,0.12)",
            "text": "#ecfdf5", "muted": "#6b9980",
            "font_display": "DM Serif Display", "font_body": "Inter",
            "gradient": "radial-gradient(ellipse 70% 50% at 50% -10%, rgba(16,185,129,0.22) 0%, transparent 65%)",
            "hero_sub_prefix": "Track every",
        },
        "finance": {
            "primary": "#3b82f6", "secondary": "#60a5fa", "tertiary": "#93c5fd",
            "bg": "#060914", "surface": "#0c1022", "border": "rgba(59,130,246,0.12)",
            "text": "#f0f4ff", "muted": "#6b7ca8",
            "font_display": "Sora", "font_body": "Inter",
            "gradient": "radial-gradient(ellipse 70% 50% at 50% -10%, rgba(59,130,246,0.18) 0%, transparent 65%)",
            "hero_sub_prefix": "Manage every",
        },
        "crm": {
            "primary": "#8b5cf6", "secondary": "#a78bfa", "tertiary": "#c4b5fd",
            "bg": "#09060f", "surface": "#100d1a", "border": "rgba(139,92,246,0.12)",
            "text": "#f5f0ff", "muted": "#7c6aaa",
            "font_display": "Outfit", "font_body": "Inter",
            "gradient": "radial-gradient(ellipse 70% 50% at 50% -10%, rgba(139,92,246,0.2) 0%, transparent 65%)",
            "hero_sub_prefix": "Close every",
        },
        "devtools": {
            "primary": "#22d3ee", "secondary": "#67e8f9", "tertiary": "#a5f3fc",
            "bg": "#030712", "surface": "#0a0f1e", "border": "rgba(34,211,238,0.1)",
            "text": "#e0f7fa", "muted": "#4d7a88",
            "font_display": "JetBrains Mono", "font_body": "Inter",
            "gradient": "radial-gradient(ellipse 70% 50% at 50% -10%, rgba(34,211,238,0.15) 0%, transparent 65%)",
            "hero_sub_prefix": "Ship every",
        },
        "edtech": {
            "primary": "#f59e0b", "secondary": "#fbbf24", "tertiary": "#fde68a",
            "bg": "#0c0a03", "surface": "#18140a", "border": "rgba(245,158,11,0.12)",
            "text": "#fffbeb", "muted": "#8a7a44",
            "font_display": "Nunito", "font_body": "Inter",
            "gradient": "radial-gradient(ellipse 70% 50% at 50% -10%, rgba(245,158,11,0.18) 0%, transparent 65%)",
            "hero_sub_prefix": "Master every",
        },
        "ecommerce": {
            "primary": "#ec4899", "secondary": "#f472b6", "tertiary": "#f9a8d4",
            "bg": "#0f030a", "surface": "#1a0812", "border": "rgba(236,72,153,0.12)",
            "text": "#fdf2f8", "muted": "#8a5070",
            "font_display": "Playfair Display", "font_body": "Inter",
            "gradient": "radial-gradient(ellipse 70% 50% at 50% -10%, rgba(236,72,153,0.18) 0%, transparent 65%)",
            "hero_sub_prefix": "Sell every",
        },
    }
    return palettes.get(category, {
        "primary": "#6366f1", "secondary": "#a78bfa", "tertiary": "#c4b5fd",
        "bg": "#0a0a0f", "surface": "#12121a", "border": "rgba(255,255,255,0.06)",
        "text": "#f0f0ff", "muted": "#6b7280",
        "font_display": "Playfair Display", "font_body": "Inter",
        "gradient": "radial-gradient(ellipse 70% 50% at 50% -10%, rgba(99,102,241,0.2) 0%, transparent 65%)",
        "hero_sub_prefix": "Build every",
    })


_FEATURE_ICON_MAP = [
    # (keyword_list, emoji)
    (["track", "log", "record", "monitor"], "📊"),
    (["analyze", "insight", "report", "dashboard", "stat", "metric"], "📈"),
    (["goal", "target", "achieve", "progress"], "🎯"),
    (["meal", "food", "nutrition", "calorie", "diet", "macro"], "🥗"),
    (["workout", "exercise", "fitness", "train", "gym"], "💪"),
    (["plan", "schedule", "calendar", "remind"], "📅"),
    (["pay", "payment", "billing", "stripe", "invoice", "subscri"], "💳"),
    (["connect", "integration", "sync", "api", "webhook"], "🔗"),
    (["team", "collab", "share", "member", "role"], "👥"),
    (["ai", "smart", "auto", "machine", "learn", "predict"], "🤖"),
    (["security", "auth", "login", "permission", "role", "access"], "🔐"),
    (["search", "filter", "find", "discov"], "🔍"),
    (["message", "chat", "notif", "alert", "email"], "💬"),
    (["export", "download", "import", "upload", "file"], "📁"),
    (["lead", "prospect", "customer", "contact", "crm"], "🤝"),
    (["deploy", "ship", "release", "publish", "ci"], "🚀"),
    (["code", "develop", "build", "test", "debug"], "⚙️"),
    (["learn", "course", "lesson", "quiz", "skill"], "📚"),
    (["shop", "store", "product", "cart", "order"], "🛒"),
    (["speed", "fast", "performa", "optim", "cache"], "⚡"),
]


def _feature_icon(feature_text: str) -> str:
    """Map a feature description to an emoji icon."""
    text = feature_text.lower()
    for keywords, emoji in _FEATURE_ICON_MAP:
        if any(kw in text for kw in keywords):
            return emoji
    return "✦"


def _feature_title(feature_text: str) -> str:
    """Extract a short title from a feature description (first 4 words max)."""
    words = feature_text.strip().split()
    title = " ".join(words[:4])
    # Capitalise first letter
    return title[0].upper() + title[1:] if title else feature_text


def _hero_subheading(tagline: str, product_name: str, features: list[str], category: str) -> str:
    """Generate a product-specific one-sentence hero subheading."""
    palette = _category_palette(category)
    prefix = palette["hero_sub_prefix"]
    # Use first feature if available
    if features:
        first = features[0].lower().rstrip(".")
        return f"{prefix} {first} — then see exactly where you stand with {product_name}."
    return f"{prefix} detail of your {tagline.rstrip('.')} experience, beautifully."


def _render_html(
    product_name: str,
    tagline: str,
    features: list[str],
    cta_text: str,
    target_user: str = "",
) -> str:
    category = _detect_category(product_name, tagline, features)
    p = _category_palette(category)

    features_cards = "\n".join(
        f"""      <div class="feature-card reveal" style="transition-delay:{(i + 1) * 70}ms">
        <div class="feature-icon" aria-hidden="true">{_feature_icon(f)}</div>
        <h3 class="feature-title">{_feature_title(f)}</h3>
        <p class="feature-text">{f}</p>
      </div>"""
        for i, f in enumerate(features)
    )
    audience_note = f'<p class="audience-note">Built for {target_user}</p>' if target_user else ""
    hero_sub = _hero_subheading(tagline, product_name, features, category)
    font_import = (
        f"'https://fonts.googleapis.com/css2?"
        f"family={p['font_display'].replace(' ', '+')}:wght@400;700"
        f"&family={p['font_body']}:wght@300;400;500;600&display=swap'"
    )

    # Integration-ready auth signup form in the CTA section
    signup_form = f"""
          <form class="signup-form" onsubmit="return handleSignup(event)">
            <div class="form-row">
              <label for="email" class="sr-only">Email address</label>
              <input id="email" type="email" name="email" class="form-input"
                placeholder="Enter your email" autocomplete="email" required
                aria-label="Email address" />
              <button type="submit" class="btn-primary form-btn">{cta_text}</button>
            </div>
            <p class="form-note">No credit card required. Cancel anytime.</p>
          </form>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="{tagline}">
  <title>{product_name}</title>
  <style>
    @import url({font_import});

    /* ── Design tokens ─────────────────────────────────────────────────── */
    :root {{
      /* Colors — category: {category} */
      --color-primary: {p['primary']};
      --color-secondary: {p['secondary']};
      --color-tertiary: {p['tertiary']};
      --color-bg: {p['bg']};
      --color-surface: {p['surface']};
      --color-border: {p['border']};
      --color-text: {p['text']};
      --color-muted: {p['muted']};

      /* Typography */
      --font-display: '{p['font_display']}', Georgia, serif;
      --font-body: '{p['font_body']}', system-ui, sans-serif;

      /* Radii */
      --radius-sm: 4px;
      --radius-md: 10px;
      --radius-lg: 20px;

      /* Shadows */
      --shadow-sm: 0 1px 3px rgba(0,0,0,.4);
      --shadow-md: 0 4px 24px rgba(0,0,0,.5);
      --shadow-lg: 0 16px 48px rgba(0,0,0,.6);

      /* Spacing scale */
      --space-1: 0.25rem;   /*  4px */
      --space-2: 0.5rem;    /*  8px */
      --space-3: 0.75rem;   /* 12px */
      --space-4: 1rem;      /* 16px */
      --space-5: 1.5rem;    /* 24px */
      --space-6: 2rem;      /* 32px */
      --space-8: 3rem;      /* 48px */

      /* Layout */
      --max-content-width: 1240px;
      --space-container-x: clamp(1.25rem, 5vw, 2.5rem);
      --space-section: clamp(4rem, 8vw, 6.75rem);
      --space-stack-sm: var(--space-3);
      --space-stack-md: var(--space-5);
      --space-stack-lg: clamp(2rem, 4vw, 3rem);
      --hero-text-width: 660px;
      --card-pad: clamp(1.5rem, 3vw, 2rem);
      --grid-gap: clamp(1rem, 2vw, 1.5rem);
    }}

    /* ── Reset ─────────────────────────────────────────────────────────── */
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html {{ scroll-behavior: smooth; -webkit-font-smoothing: antialiased; }}
    body {{
      font-family: var(--font-body);
      font-size: 1rem;
      line-height: 1.6;
      color: var(--color-text);
      background: var(--color-bg);
    }}

    /* ── Layout ────────────────────────────────────────────────────────── */
    .container {{
      max-width: var(--max-content-width);
      margin-inline: auto;
      padding-inline: var(--space-container-x);
    }}

    /* ── Navbar ────────────────────────────────────────────────────────── */
    .navbar {{
      position: sticky;
      top: 0;
      z-index: 100;
      padding-block: var(--space-4);
      background: rgba(10,10,15,0.75);
      backdrop-filter: blur(20px);
      -webkit-backdrop-filter: blur(20px);
      border-bottom: 1px solid var(--color-border);
      transition: background 0.25s ease, border-color 0.25s ease, padding 0.25s ease;
    }}
    .navbar.scrolled {{
      background: rgba(10,10,15,0.92);
      border-bottom-color: rgba(255,255,255,0.12);
      padding-block: var(--space-3);
    }}
    .navbar-inner {{ display: flex; align-items: center; justify-content: space-between; gap: var(--space-5); }}
    .brand {{
      font-family: var(--font-display);
      font-weight: 700;
      font-size: 1.15rem;
      color: var(--color-text);
      text-decoration: none;
      flex-shrink: 0;
    }}
    .nav-links {{ display: flex; gap: var(--space-6); list-style: none; }}
    .nav-links a {{
      color: var(--color-muted);
      text-decoration: none;
      font-size: 0.875rem;
      transition: color 0.2s;
    }}
    .nav-links a:hover {{ color: var(--color-text); }}
    .nav-cta {{
      padding: var(--space-2) var(--space-5);
      background: var(--color-primary);
      color: #fff;
      border-radius: var(--radius-sm);
      text-decoration: none;
      font-size: 0.875rem;
      font-weight: 600;
      white-space: nowrap;
      transition: opacity 0.2s;
    }}
    .nav-cta:hover {{ opacity: 0.85; }}

    /* ── Hero ──────────────────────────────────────────────────────────── */
    .hero {{
      padding-block: clamp(5rem, 10vw, 9rem) clamp(4rem, 7vw, 7rem);
      text-align: center;
      position: relative;
      overflow: hidden;
    }}
    .hero-gradient {{
      position: absolute;
      inset: 0;
      background: {p['gradient']};
      pointer-events: none;
      transform: translateY(0);
      transition: transform 0.35s ease;
    }}
    .hero-inner {{
      position: relative;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: var(--space-stack-md);
    }}
    .hero h1 {{
      font-family: var(--font-display);
      font-size: clamp(2.4rem, 6vw, 4.75rem);
      font-weight: 700;
      letter-spacing: -0.03em;
      line-height: 1.08;
      max-width: var(--hero-text-width);
    }}
    .hero-sub {{
      font-size: clamp(1rem, 2vw, 1.2rem);
      color: var(--color-muted);
      max-width: 520px;
      line-height: 1.65;
    }}
    .audience-note {{
      font-size: 0.875rem;
      color: var(--color-secondary);
      letter-spacing: 0.01em;
    }}
    .hero-ctas {{
      display: flex;
      gap: var(--space-3);
      justify-content: center;
      flex-wrap: wrap;
      margin-top: var(--space-2);
    }}

    .proof-strip {{
      padding-block: 0 var(--space-section);
    }}
    .proof-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: var(--grid-gap);
    }}
    .proof-card {{
      border: 1px solid var(--color-border);
      border-radius: var(--radius-lg);
      background: linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.01));
      padding: var(--card-pad);
      text-align: left;
    }}
    .proof-value {{
      display: block;
      font-family: var(--font-display);
      font-size: clamp(1.75rem, 4vw, 2.5rem);
      line-height: 1.1;
      letter-spacing: -0.02em;
      margin-bottom: var(--space-2);
      color: var(--color-text);
    }}
    .proof-label {{
      color: var(--color-muted);
      font-size: 0.875rem;
      letter-spacing: 0.01em;
    }}

    /* ── Buttons ───────────────────────────────────────────────────────── */
    .btn-primary {{
      display: inline-flex;
      align-items: center;
      padding: 0.8125rem 2rem;
      background: var(--color-primary);
      color: #fff;
      border-radius: var(--radius-md);
      text-decoration: none;
      font-weight: 600;
      font-size: 0.9375rem;
      letter-spacing: -0.01em;
      box-shadow: var(--shadow-md);
      transition: opacity 0.2s, transform 0.2s;
    }}
    .btn-primary:hover {{ opacity: 0.88; transform: translateY(-1px); }}
    .btn-secondary {{
      display: inline-flex;
      align-items: center;
      padding: 0.8125rem 2rem;
      background: transparent;
      color: var(--color-text);
      border: 1px solid rgba(255,255,255,0.14);
      border-radius: var(--radius-md);
      text-decoration: none;
      font-weight: 500;
      font-size: 0.9375rem;
      transition: border-color 0.2s, color 0.2s;
    }}
    .btn-secondary:hover {{ border-color: var(--color-primary); color: var(--color-primary); }}

    /* ── Section heading system ────────────────────────────────────────── */
    .section-header {{ margin-bottom: var(--space-stack-lg); }}
    .section-label {{
      display: block;
      font-size: 0.7rem;
      font-weight: 700;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--color-primary);
      margin-bottom: var(--space-stack-sm);
    }}
    .section-title {{
      font-family: var(--font-display);
      font-size: clamp(1.75rem, 3.5vw, 2.6rem);
      font-weight: 700;
      letter-spacing: -0.025em;
      line-height: 1.15;
    }}
    .section-intro {{
      margin-top: var(--space-stack-sm);
      font-size: 1rem;
      color: var(--color-muted);
      max-width: 520px;
      line-height: 1.65;
    }}

    /* ── Features ──────────────────────────────────────────────────────── */
    .features {{ padding-block: var(--space-section); }}
    .features-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr));
      gap: var(--grid-gap);
    }}
    .feature-card {{
      background: var(--color-surface);
      border: 1px solid var(--color-border);
      border-radius: var(--radius-lg);
      padding: var(--card-pad);
      transition: border-color 0.2s, box-shadow 0.2s;
    }}
    .feature-card:hover {{
      border-color: color-mix(in srgb, var(--color-primary) 40%, transparent);
      box-shadow: var(--shadow-sm);
    }}
    .feature-icon {{
      font-size: 1.75rem;
      line-height: 1;
      margin-bottom: var(--space-3);
    }}
    .feature-title {{
      font-size: 0.9375rem;
      font-weight: 600;
      color: var(--color-text);
      margin-bottom: var(--space-2);
      line-height: 1.4;
    }}
    .feature-text {{ color: var(--color-muted); font-size: 0.875rem; line-height: 1.65; }}

    /* ── Signup form ────────────────────────────────────────────────────── */
    .signup-form {{ width: 100%; max-width: 480px; margin-inline: auto; }}
    .form-row {{
      display: flex;
      gap: var(--space-2);
      flex-wrap: wrap;
    }}
    .form-input {{
      flex: 1;
      min-width: 0;
      padding: 0.8125rem 1rem;
      border-radius: var(--radius-md);
      border: 1px solid var(--color-border);
      background: rgba(255,255,255,0.04);
      color: var(--color-text);
      font-size: 0.9375rem;
      font-family: var(--font-body);
      outline: none;
      transition: border-color 0.2s;
    }}
    .form-input::placeholder {{ color: var(--color-muted); }}
    .form-input:focus {{ border-color: var(--color-primary); }}
    .form-btn {{ flex-shrink: 0; }}
    .form-note {{ margin-top: var(--space-2); font-size: 0.8125rem; color: var(--color-muted); }}
    .sr-only {{ position: absolute; width: 1px; height: 1px; padding: 0; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }}

    /* ── Testimonials ──────────────────────────────────────────────────── */
    .testimonials {{ padding-block: var(--space-section); }}
    .testimonials-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(100%, 260px), 1fr));
      gap: var(--grid-gap);
    }}
    .testimonial-card {{
      background: var(--color-surface);
      border: 1px solid var(--color-border);
      border-radius: var(--radius-lg);
      padding: var(--card-pad);
      display: flex;
      flex-direction: column;
      gap: var(--space-5);
    }}
    .testimonial-quote {{
      font-size: 0.9375rem;
      color: var(--color-muted);
      line-height: 1.7;
      flex: 1;
    }}
    .testimonial-author {{ display: flex; align-items: center; gap: var(--space-3); }}
    .avatar {{
      width: 38px;
      height: 38px;
      border-radius: 50%;
      background: var(--color-primary);
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 700;
      font-size: 0.8125rem;
      color: #fff;
      flex-shrink: 0;
      letter-spacing: 0.02em;
    }}
    .author-name {{ font-weight: 600; font-size: 0.875rem; line-height: 1.3; }}
    .author-role {{ font-size: 0.75rem; color: var(--color-muted); margin-top: var(--space-1); }}

    /* ── CTA section ───────────────────────────────────────────────────── */
    .cta-section {{ padding-block: var(--space-section); text-align: center; }}
    .cta-box {{
      background: var(--color-surface);
      border: 1px solid rgba(99,102,241,0.22);
      border-radius: var(--radius-lg);
      padding: clamp(3rem, 7vw, 5rem) var(--space-container-x);
      position: relative;
      overflow: hidden;
    }}
    .cta-box::before {{
      content: '';
      position: absolute;
      inset: 0;
      background: radial-gradient(ellipse 60% 55% at 50% 50%, rgba(99,102,241,0.09) 0%, transparent 70%);
      pointer-events: none;
    }}
    .cta-box h2 {{
      font-family: var(--font-display);
      font-size: clamp(1.75rem, 3.5vw, 2.6rem);
      font-weight: 700;
      letter-spacing: -0.025em;
      margin-bottom: var(--space-stack-sm);
      position: relative;
    }}
    .cta-box p {{
      color: var(--color-muted);
      margin-bottom: var(--space-stack-lg);
      position: relative;
      font-size: 1rem;
      max-width: 440px;
      margin-inline: auto;
    }}
    .cta-box .btn-primary {{ position: relative; }}

    /* ── Footer ────────────────────────────────────────────────────────── */
    footer {{
      border-top: 1px solid var(--color-border);
      padding-block: clamp(2rem, 4vw, 3rem);
      font-size: 0.875rem;
      color: var(--color-muted);
    }}
    .footer-inner {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: var(--space-4);
    }}
    .footer-links {{ display: flex; gap: var(--space-5); list-style: none; }}
    .footer-links a {{ color: var(--color-muted); text-decoration: none; transition: color 0.2s; }}
    .footer-links a:hover {{ color: var(--color-text); }}

    .reveal {{
      opacity: 0;
      transform: translateY(14px);
      transition: opacity 0.45s ease, transform 0.45s ease;
      will-change: opacity, transform;
    }}
    .reveal.is-visible {{
      opacity: 1;
      transform: translateY(0);
    }}

    /* ── Responsive ────────────────────────────────────────────────────── */
    @media (max-width: 768px) {{
      .nav-links {{ display: none; }}
      .proof-grid {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 480px) {{
      .hero-ctas {{ flex-direction: column; align-items: center; }}
      .btn-primary, .btn-secondary {{ width: 100%; max-width: 320px; justify-content: center; }}
      .footer-inner {{ flex-direction: column; text-align: center; }}
      .footer-links {{ justify-content: center; }}
    }}
  </style>
</head>
<body>
  <header class="navbar">
    <div class="container">
      <div class="navbar-inner">
        <a class="brand" href="/">{product_name}</a>
        <nav aria-label="Primary">
          <ul class="nav-links">
            <li><a href="#features">Features</a></li>
            <li><a href="#testimonials">Reviews</a></li>
            <li><a href="#signup">{cta_text}</a></li>
          </ul>
        </nav>
        <a class="nav-cta" href="#signup">{cta_text}</a>
      </div>
    </div>
  </header>

  <main>
    <section class="hero" aria-labelledby="hero-heading">
      <div class="hero-gradient" aria-hidden="true"></div>
      <div class="container">
        <div class="hero-inner">
          <p class="section-label">{product_name}</p>
          <h1 id="hero-heading">{tagline}</h1>
          <p class="hero-sub">{hero_sub}</p>
          {audience_note}
          <div class="hero-ctas">
            <a class="btn-primary" href="#signup">{cta_text}</a>
            <a class="btn-secondary" href="#features">See how it works</a>
          </div>
        </div>
      </div>
    </section>

    <section class="proof-strip" aria-label="Performance highlights">
      <div class="container">
        <div class="proof-grid">
          <article class="proof-card reveal">
            <strong class="proof-value"><span data-count="87">0</span>%</strong>
            <p class="proof-label">Teams report faster release cycles in the first month.</p>
          </article>
          <article class="proof-card reveal">
            <strong class="proof-value"><span data-count="320">0</span>K+</strong>
            <p class="proof-label">Automated actions executed across production workflows.</p>
          </article>
          <article class="proof-card reveal">
            <strong class="proof-value"><span data-count="4">0</span>.9/5</strong>
            <p class="proof-label">Average user satisfaction from product and growth teams.</p>
          </article>
        </div>
      </div>
    </section>

    <section class="features" id="features" aria-labelledby="features-heading">
      <div class="container">
        <div class="section-header">
          <span class="section-label">Features</span>
          <h2 class="section-title" id="features-heading">Everything you need to succeed</h2>
        </div>
        <div class="features-grid">
{features_cards}
        </div>
      </div>
    </section>

    <section class="testimonials" id="testimonials" aria-labelledby="testimonials-heading">
      <div class="container">
        <div class="section-header">
          <span class="section-label">Testimonials</span>
          <h2 class="section-title" id="testimonials-heading">Loved by teams worldwide</h2>
        </div>
        <div class="testimonials-grid">
          <div class="testimonial-card reveal">
            <p class="testimonial-quote">"This completely changed how our team operates. The ROI was immediately apparent within the first week of use."</p>
            <div class="testimonial-author">
              <div class="avatar" aria-hidden="true">AK</div>
              <div><div class="author-name">Alex Kim</div><div class="author-role">Head of Product, Nexus</div></div>
            </div>
          </div>
          <div class="testimonial-card reveal" style="transition-delay:80ms">
            <p class="testimonial-quote">"We evaluated a dozen tools and nothing came close. Onboarding took minutes and the results speak for themselves."</p>
            <div class="testimonial-author">
              <div class="avatar" aria-hidden="true">SL</div>
              <div><div class="author-name">Sofia Laurent</div><div class="author-role">CTO, Meridian Labs</div></div>
            </div>
          </div>
          <div class="testimonial-card reveal" style="transition-delay:140ms">
            <p class="testimonial-quote">"I was skeptical at first, but after one month our productivity increased by 40%. Genuinely impressive."</p>
            <div class="testimonial-author">
              <div class="avatar" aria-hidden="true">MR</div>
              <div><div class="author-name">Marcus Reid</div><div class="author-role">Founder, Orbit</div></div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="cta-section" id="signup" aria-labelledby="cta-heading">
      <div class="container">
        <div class="cta-box">
          <h2 id="cta-heading">Start your free trial today</h2>
          <p>Join thousands of people already using {product_name}. Set up in under 2 minutes.</p>
          {signup_form}
        </div>
      </div>
    </section>
  </main>

  <footer>
    <div class="container">
      <div class="footer-inner">
        <span>&copy; <span id="year">2025</span> {product_name}. All rights reserved.</span>
        <ul class="footer-links">
          <li><a href="/privacy">Privacy</a></li>
          <li><a href="/terms">Terms</a></li>
          <li><a href="mailto:hello@{product_name.lower().replace(' ', '')}.com">Contact</a></li>
        </ul>
      </div>
    </div>
  </footer>
  <script>
    (() => {{
      const navbar = document.querySelector(".navbar");
      const heroGradient = document.querySelector(".hero-gradient");
      const revealables = document.querySelectorAll(".reveal");
      const counters = document.querySelectorAll("[data-count]");
      let countersStarted = false;

      const setNavState = () => {{
        if (!navbar) return;
        navbar.classList.toggle("scrolled", window.scrollY > 14);
      }};

      const observer = new IntersectionObserver((entries) => {{
        entries.forEach((entry) => {{
          if (entry.isIntersecting) {{
            entry.target.classList.add("is-visible");
            observer.unobserve(entry.target);
          }}
        }});
      }}, {{ threshold: 0.2 }});

      revealables.forEach((el) => observer.observe(el));

      const animateCounters = () => {{
        if (countersStarted) return;
        countersStarted = true;
        counters.forEach((node) => {{
          const target = Number(node.getAttribute("data-count") || "0");
          let current = 0;
          const step = Math.max(1, Math.ceil(target / 36));
          const tick = () => {{
            current = Math.min(target, current + step);
            node.textContent = String(current);
            if (current < target) requestAnimationFrame(tick);
          }};
          requestAnimationFrame(tick);
        }});
      }};

      const counterSection = document.querySelector(".proof-strip");
      if (counterSection) {{
        const counterObserver = new IntersectionObserver((entries) => {{
          if (entries.some((entry) => entry.isIntersecting)) {{
            animateCounters();
            counterObserver.disconnect();
          }}
        }}, {{ threshold: 0.35 }});
        counterObserver.observe(counterSection);
      }}

      window.addEventListener("scroll", () => {{
        setNavState();
        if (heroGradient) {{
          const shift = Math.min(window.scrollY * 0.12, 36);
          heroGradient.style.transform = `translateY(${{shift}}px)`;
        }}
      }}, {{ passive: true }});

      const yearNode = document.getElementById("year");
      if (yearNode) yearNode.textContent = String(new Date().getFullYear());
      setNavState();
    }})();

    function handleSignup(e) {{
      e.preventDefault();
      const form = e.target;
      const email = form.querySelector('input[type="email"]');
      if (!email || !email.value.includes('@')) {{
        email && (email.style.borderColor = '#ef4444');
        return false;
      }}
      const btn = form.querySelector('button[type="submit"]');
      if (btn) {{ btn.textContent = 'Check your email ✓'; btn.disabled = true; }}
      return false;
    }}
  </script>
</body>
</html>
"""


def _render_app_page(product_name: str, features: list[str]) -> str:
    features_nav = "\n".join(
        f'        <li><a href="#feat-{i}">{_feature_icon(f)} {_feature_title(f)}</a></li>'
        for i, f in enumerate(features)
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{product_name} — App</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    /* ── Design tokens ─────────────────────────────────────────────────── */
    :root {{
      --color-bg: #0a0a0f;
      --color-surface: #12121a;
      --color-surface-2: #1a1a24;
      --color-border: rgba(255,255,255,0.07);
      --color-text: #f0f0ff;
      --color-muted: #6b7280;
      --color-primary: #6366f1;
      --font-body: 'Inter', system-ui, sans-serif;
      --radius-sm: 6px;
      --radius-md: 10px;
      --nav-width: 224px;
      --space-container-x: clamp(1.25rem, 3vw, 2rem);
      --card-pad: clamp(1.25rem, 2.5vw, 1.75rem);
      --card-gap: clamp(0.75rem, 1.5vw, 1.25rem);
    }}

    /* ── Reset ─────────────────────────────────────────────────────────── */
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html {{ -webkit-font-smoothing: antialiased; }}
    body {{
      font-family: var(--font-body);
      display: flex;
      min-height: 100vh;
      background: var(--color-bg);
      color: var(--color-text);
      font-size: 0.9375rem;
      line-height: 1.55;
    }}

    /* ── Sidebar nav ───────────────────────────────────────────────────── */
    .sidebar {{
      width: var(--nav-width);
      background: var(--color-surface);
      border-right: 1px solid var(--color-border);
      padding: clamp(1.25rem, 2.5vw, 1.75rem) clamp(0.75rem, 1.5vw, 1rem);
      flex-shrink: 0;
      display: flex;
      flex-direction: column;
      gap: 1.75rem;
    }}
    .sidebar-logo {{
      font-weight: 700;
      font-size: 0.9375rem;
      color: var(--color-text);
      letter-spacing: -0.01em;
      text-decoration: none;
    }}
    .nav-list {{ list-style: none; display: flex; flex-direction: column; gap: 2px; }}
    .nav-list a {{
      display: block;
      padding: 0.5rem 0.75rem;
      border-radius: var(--radius-sm);
      text-decoration: none;
      color: var(--color-muted);
      font-size: 0.875rem;
      font-weight: 500;
      transition: background 0.15s, color 0.15s;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .nav-list a:hover {{
      background: rgba(255,255,255,0.05);
      color: var(--color-text);
    }}
    .nav-divider {{
      height: 1px;
      background: var(--color-border);
      margin-block: 0.5rem;
    }}

    /* ── Main content ──────────────────────────────────────────────────── */
    .main-content {{
      flex: 1;
      padding: var(--space-container-x);
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: var(--card-gap);
    }}
    .page-header {{
      padding-bottom: var(--card-gap);
      border-bottom: 1px solid var(--color-border);
      margin-bottom: calc(var(--card-gap) * 0.25);
    }}
    .page-title {{
      font-size: clamp(1.25rem, 2.5vw, 1.5rem);
      font-weight: 700;
      letter-spacing: -0.02em;
    }}

    /* ── Cards ─────────────────────────────────────────────────────────── */
    .card {{
      background: var(--color-surface);
      border: 1px solid var(--color-border);
      border-radius: var(--radius-md);
      padding: var(--card-pad);
    }}
    .card-title {{
      font-size: 0.9375rem;
      font-weight: 600;
      margin-bottom: var(--card-gap);
      color: var(--color-text);
    }}
    .placeholder {{
      min-height: 110px;
      background: var(--color-surface-2);
      border-radius: var(--radius-sm);
      display: flex;
      align-items: center;
      justify-content: center;
      color: var(--color-muted);
      font-size: 0.875rem;
      border: 1px dashed var(--color-border);
    }}

    /* ── Dashboard extras ──────────────────────────────────────────────── */
    .page-subtitle {{ font-size: 0.875rem; color: var(--color-muted); margin-top: 4px; }}
    .metrics-row {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(100%, 140px), 1fr));
      gap: var(--card-gap);
    }}
    .metric-card {{
      background: var(--color-surface-2);
      border-radius: var(--radius-sm);
      padding: 0.875rem 1rem;
      display: flex;
      flex-direction: column;
      gap: 4px;
    }}
    .metric-value {{ font-size: 1.5rem; font-weight: 700; color: var(--color-text); }}
    .metric-label {{ font-size: 0.75rem; color: var(--color-muted); }}
    .card-desc {{ font-size: 0.875rem; color: var(--color-muted); margin-bottom: 1rem; }}
    .integration-card {{ border-color: rgba(99,102,241,0.2); }}
    .form-group {{ display: flex; flex-direction: column; gap: 0.5rem; }}
    .form-label {{ font-size: 0.8125rem; font-weight: 500; color: var(--color-text); }}
    .token-row {{ display: flex; gap: 0.5rem; flex-wrap: wrap; }}
    .form-input-dark {{
      flex: 1;
      min-width: 0;
      padding: 0.625rem 0.875rem;
      background: var(--color-surface-2);
      border: 1px solid var(--color-border);
      border-radius: var(--radius-sm);
      color: var(--color-text);
      font-family: var(--font-body);
      font-size: 0.875rem;
      outline: none;
    }}
    .form-input-dark:focus {{ border-color: var(--color-primary); }}
    .form-hint {{ font-size: 0.75rem; color: var(--color-muted); }}
    .btn-connect {{
      padding: 0.625rem 1rem;
      background: var(--color-primary);
      color: #fff;
      border: none;
      border-radius: var(--radius-sm);
      font-size: 0.875rem;
      font-weight: 600;
      cursor: pointer;
      font-family: var(--font-body);
      white-space: nowrap;
      transition: opacity 0.2s;
    }}
    .btn-connect:hover {{ opacity: 0.85; }}
    .actions-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(100%, 140px), 1fr));
      gap: var(--card-gap);
    }}
    .action-btn {{
      padding: 0.75rem 1rem;
      background: var(--color-surface-2);
      border: 1px solid var(--color-border);
      border-radius: var(--radius-sm);
      color: var(--color-text);
      font-family: var(--font-body);
      font-size: 0.875rem;
      font-weight: 500;
      cursor: pointer;
      text-align: left;
      transition: background 0.15s, border-color 0.15s;
    }}
    .action-btn:hover {{
      background: rgba(255,255,255,0.06);
      border-color: var(--color-primary);
    }}

    /* ── Responsive ────────────────────────────────────────────────────── */
    @media (max-width: 640px) {{
      body {{ flex-direction: column; }}
      .sidebar {{
        width: 100%;
        flex-direction: row;
        align-items: center;
        flex-wrap: wrap;
        gap: var(--card-gap);
        border-right: none;
        border-bottom: 1px solid var(--color-border);
      }}
      .nav-list {{ flex-direction: row; flex-wrap: wrap; gap: 2px; }}
      .nav-divider {{ display: none; }}
    }}
  </style>
</head>
<body>
  <nav class="sidebar" aria-label="App navigation">
    <a class="sidebar-logo" href="/">{product_name}</a>
    <ul class="nav-list">
{features_nav}
      <li><div class="nav-divider" aria-hidden="true"></div></li>
      <li><a href="/">← Back to site</a></li>
    </ul>
  </nav>
  <div class="main-content">
    <div class="page-header">
      <h1 class="page-title">{product_name} Dashboard</h1>
      <p class="page-subtitle">Welcome back. Here's what's happening today.</p>
    </div>

    <!-- Overview metrics -->
    <div class="card">
      <h2 class="card-title">Overview</h2>
      <div class="metrics-row">
        <div class="metric-card">
          <span class="metric-value">—</span>
          <span class="metric-label">Total this week</span>
        </div>
        <div class="metric-card">
          <span class="metric-value">—</span>
          <span class="metric-label">Daily average</span>
        </div>
        <div class="metric-card">
          <span class="metric-value">—</span>
          <span class="metric-label">Goal progress</span>
        </div>
      </div>
    </div>

    <!-- Connect account / API integration placeholder -->
    <div class="card integration-card">
      <h2 class="card-title">🔗 Connect your account</h2>
      <p class="card-desc">Link your data source to start tracking automatically.</p>
      <div class="form-group">
        <label for="api-token" class="form-label">API Token</label>
        <div class="token-row">
          <input id="api-token" type="password" class="form-input-dark"
            placeholder="sk-..." autocomplete="off"
            aria-label="API token" />
          <button class="btn-connect" onclick="connectAccount(this)">Connect</button>
        </div>
        <p class="form-hint">Find your token in Settings → API Keys.</p>
      </div>
    </div>

    <!-- Quick actions -->
    <div class="card">
      <h2 class="card-title">Quick Actions</h2>
      <div class="actions-grid">
        <button class="action-btn">+ New entry</button>
        <button class="action-btn">📤 Export data</button>
        <button class="action-btn">⚙️ Settings</button>
        <button class="action-btn">📊 Full report</button>
      </div>
    </div>
  </div>
  <script>
    function connectAccount(btn) {{
      const input = document.getElementById('api-token');
      if (!input || !input.value.trim()) {{
        input && (input.style.borderColor = '#ef4444');
        return;
      }}
      btn.textContent = 'Connected ✓';
      btn.disabled = true;
      btn.style.background = '#10b981';
    }}
  </script>
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
