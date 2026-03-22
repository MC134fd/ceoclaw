"""
Deterministic spec→HTML renderer.

Pure function: SiteSpec in → dict[path, html_string] out.
Zero AI involvement.  Zero randomness.  Always produces complete,
renderable, responsive HTML.
"""
from __future__ import annotations

import html as html_mod
from typing import Any

from services.site_spec import (
    AuthPageProps,
    DashboardMetric,
    DashboardPageProps,
    DashboardSidebarLink,
    Page,
    SiteDesign,
    SiteSpec,
    Navigation,
)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_site(spec: SiteSpec) -> dict[str, str]:
    """Render every page in the spec. Returns {relative_path: html_string}."""
    results: dict[str, str] = {}
    for page in spec.pages:
        html = render_page(page, spec.site, spec.navigation, spec.pages)
        results[page.path] = html
    return results


def render_page(
    page: Page,
    site: SiteDesign,
    nav: Navigation,
    all_pages: list[Page],
) -> str:
    """Render a single page to a complete HTML document."""
    if page.type == "auth":
        return _render_auth_page(page, site, nav)
    if page.type == "dashboard":
        return _render_dashboard_page(page, site)

    # Landing / content pages — section-based rendering
    sections_html = "\n".join(
        _render_section(s.type, s.props, site) for s in page.sections
    )
    nav_html = _render_navbar(site, nav, page.path)
    is_subpage = "/" in page.path
    css = _base_css(site)
    font_url = _font_import_url(site)
    js = _base_js()

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{_e(page.title or site.title)}</title>
  <meta name="description" content="{_e(site.description)}">
  <style>
    @import url('{font_url}');
{css}
  </style>
</head>
<body>
{nav_html}
<main>
{sections_html}
</main>
{js}
</body>
</html>"""


# ---------------------------------------------------------------------------
# CSS generation
# ---------------------------------------------------------------------------

def _base_css(site: SiteDesign) -> str:
    bg_rgb = _hex_to_rgb_str(site.bgColor)
    return f"""    :root {{
      --color-primary: {site.primaryColor};
      --color-secondary: {site.secondaryColor};
      --color-accent: {site.accentColor};
      --color-bg: {site.bgColor};
      --color-surface: {site.surfaceColor};
      --color-text: {site.textColor};
      --color-muted: {site.mutedColor};
      --color-border: {site.borderColor};
      --font-display: '{site.displayFont}', sans-serif;
      --font-body: '{site.bodyFont}', sans-serif;
      --radius-sm: 6px;
      --radius-md: 12px;
      --radius-lg: 20px;
      --shadow-sm: 0 1px 3px rgba(0,0,0,.08);
      --shadow-md: 0 4px 12px rgba(0,0,0,.1);
      --shadow-lg: 0 8px 30px rgba(0,0,0,.12);
      --bg-rgb: {bg_rgb};
    }}

    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      font-family: var(--font-body);
      color: var(--color-text);
      background: var(--color-bg);
      line-height: 1.6;
      -webkit-font-smoothing: antialiased;
    }}

    h1, h2, h3, h4 {{ font-family: var(--font-display); line-height: 1.2; }}
    h1 {{ font-size: clamp(2.2rem, 5vw, 3.5rem); font-weight: 700; }}
    h2 {{ font-size: clamp(1.6rem, 3.5vw, 2.5rem); font-weight: 700; }}
    h3 {{ font-size: clamp(1.1rem, 2vw, 1.4rem); font-weight: 600; }}
    p {{ max-width: 65ch; }}
    a {{ color: var(--color-primary); text-decoration: none; }}

    img {{ max-width: 100%; height: auto; display: block; }}

    .container {{
      max-width: clamp(320px, 90vw, 1200px);
      margin-inline: auto;
      padding-inline: clamp(1rem, 3vw, 2rem);
    }}

    .section {{
      padding: clamp(3rem, 8vw, 6rem) 0;
    }}

    .section-header {{
      text-align: center;
      margin-bottom: clamp(2rem, 4vw, 3.5rem);
    }}
    .section-header h2 {{ margin-bottom: 0.75rem; }}
    .section-header p {{ color: var(--color-muted); margin-inline: auto; }}

    .btn {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 12px 28px;
      border-radius: var(--radius-md);
      font-family: var(--font-body);
      font-weight: 600;
      font-size: 0.95rem;
      text-decoration: none;
      cursor: pointer;
      transition: all 200ms ease;
      min-height: 44px;
      border: none;
      gap: 8px;
    }}
    .btn-primary {{
      background: var(--color-primary);
      color: #fff;
    }}
    .btn-primary:hover {{ opacity: 0.9; transform: translateY(-1px); box-shadow: var(--shadow-md); }}
    .btn-secondary {{
      background: transparent;
      color: var(--color-primary);
      border: 2px solid var(--color-primary);
    }}
    .btn-secondary:hover {{ background: var(--color-primary); color: #fff; }}

    .card {{
      background: var(--color-surface);
      border: 1px solid var(--color-border);
      border-radius: var(--radius-lg);
      padding: clamp(1.5rem, 3vw, 2rem);
      transition: all 200ms ease;
    }}
    .card:hover {{ transform: translateY(-4px); box-shadow: var(--shadow-md); }}

    .grid {{
      display: grid;
      gap: clamp(1rem, 3vw, 1.5rem);
    }}
    .grid-2 {{ grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr)); }}
    .grid-3 {{ grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 1fr)); }}
    .grid-4 {{ grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr)); }}

    /* ── Navbar ── */
    .navbar {{
      position: fixed; top: 0; left: 0; right: 0; z-index: 1000;
      background: rgba({bg_rgb}, 0.85);
      backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
      border-bottom: 1px solid var(--color-border);
      transition: box-shadow 200ms ease;
    }}
    .navbar.scrolled {{ box-shadow: var(--shadow-sm); }}
    .nav-inner {{
      max-width: 1200px; margin: 0 auto;
      padding: 0 clamp(1rem, 3vw, 2rem);
      display: flex; align-items: center; justify-content: space-between;
      height: 64px;
    }}
    .nav-brand {{
      font-family: var(--font-display); font-weight: 700;
      font-size: 1.25rem; color: var(--color-text); text-decoration: none;
    }}
    .nav-links {{ display: flex; align-items: center; gap: clamp(1rem, 2vw, 2rem); }}
    .nav-links a {{ color: var(--color-muted); text-decoration: none; font-size: 0.9rem; transition: color 200ms; }}
    .nav-links a:hover {{ color: var(--color-text); }}
    .nav-links .btn {{ font-size: 0.85rem; padding: 8px 20px; }}
    .nav-toggle {{
      display: none; background: none; border: none;
      font-size: 1.5rem; cursor: pointer; color: var(--color-text);
    }}

    /* ── Hero ── */
    .hero {{
      padding: clamp(7rem, 14vw, 10rem) 0 clamp(4rem, 8vw, 6rem);
      text-align: center;
    }}
    .hero h1 {{ margin-bottom: 1.25rem; }}
    .hero-sub {{
      font-size: clamp(1rem, 2vw, 1.25rem);
      color: var(--color-muted);
      margin-inline: auto;
      margin-bottom: 2rem;
    }}
    .hero-ctas {{ display: flex; gap: 1rem; justify-content: center; flex-wrap: wrap; }}

    /* ── Features ── */
    .feature-icon {{
      display: inline-flex; align-items: center; justify-content: center;
      width: 48px; height: 48px; border-radius: var(--radius-md);
      background: color-mix(in srgb, var(--color-primary) 12%, transparent);
      font-size: 1.5rem; margin-bottom: 1rem;
    }}
    .feature-card h3 {{ margin-bottom: 0.5rem; }}
    .feature-card p {{ color: var(--color-muted); font-size: 0.95rem; }}

    /* ── Testimonials ── */
    .testimonial-card {{ text-align: center; }}
    .testimonial-card blockquote {{
      font-style: italic; font-size: 1.05rem; color: var(--color-text);
      margin-bottom: 1rem; line-height: 1.6;
    }}
    .testimonial-card blockquote::before {{ content: "\\201C"; font-size: 2rem; color: var(--color-primary); display: block; }}
    .testimonial-name {{ font-weight: 600; }}
    .testimonial-role {{ color: var(--color-muted); font-size: 0.85rem; }}

    /* ── Pricing ── */
    .pricing-card {{ text-align: center; position: relative; }}
    .pricing-card.highlighted {{
      border-color: var(--color-primary);
      box-shadow: 0 0 0 2px var(--color-primary), var(--shadow-lg);
    }}
    .pricing-badge {{
      position: absolute; top: -12px; left: 50%; transform: translateX(-50%);
      background: var(--color-primary); color: #fff; font-size: 0.75rem;
      padding: 4px 16px; border-radius: 999px; font-weight: 600;
    }}
    .pricing-price {{
      font-family: var(--font-display); font-size: 2.5rem; font-weight: 700;
      margin: 1rem 0 0.25rem;
    }}
    .pricing-period {{ color: var(--color-muted); font-size: 0.85rem; margin-bottom: 1rem; }}
    .pricing-features {{ list-style: none; padding: 0; margin: 1.5rem 0; text-align: left; }}
    .pricing-features li {{
      padding: 0.5rem 0; border-bottom: 1px solid var(--color-border);
      font-size: 0.9rem; display: flex; align-items: center; gap: 8px;
    }}
    .pricing-features li::before {{ content: "\\2713"; color: var(--color-primary); font-weight: 700; }}

    /* ── Stats ── */
    .stat-item {{ text-align: center; }}
    .stat-value {{
      font-family: var(--font-display); font-size: clamp(2rem, 4vw, 3rem);
      font-weight: 700; color: var(--color-primary);
    }}
    .stat-label {{ color: var(--color-muted); font-size: 0.9rem; margin-top: 0.25rem; }}

    /* ── How It Works ── */
    .steps-grid {{ counter-reset: step-counter; }}
    .step-card {{ position: relative; padding-left: 4rem; }}
    .step-card::before {{
      counter-increment: step-counter;
      content: counter(step-counter);
      position: absolute; left: 0; top: 0;
      width: 48px; height: 48px; border-radius: 50%;
      background: var(--color-primary); color: #fff;
      display: flex; align-items: center; justify-content: center;
      font-family: var(--font-display); font-weight: 700; font-size: 1.25rem;
    }}
    .step-card h3 {{ margin-bottom: 0.5rem; }}
    .step-card p {{ color: var(--color-muted); }}

    /* ── CTA Section ── */
    .cta-section {{
      text-align: center;
      background: var(--color-surface);
      border-radius: var(--radius-lg);
      padding: clamp(2.5rem, 5vw, 4rem);
      border: 1px solid var(--color-border);
    }}
    .cta-section h2 {{ margin-bottom: 1rem; }}
    .cta-section p {{ color: var(--color-muted); margin-inline: auto; margin-bottom: 2rem; }}

    /* ── FAQ ── */
    .faq-item {{
      border-bottom: 1px solid var(--color-border);
      padding: 1.25rem 0;
    }}
    .faq-question {{
      font-weight: 600; font-size: 1.05rem; cursor: pointer;
      display: flex; justify-content: space-between; align-items: center;
    }}
    .faq-question::after {{ content: "+"; font-size: 1.25rem; color: var(--color-muted); transition: transform 200ms; }}
    .faq-item.open .faq-question::after {{ transform: rotate(45deg); }}
    .faq-answer {{
      max-height: 0; overflow: hidden; transition: max-height 300ms ease;
      color: var(--color-muted); line-height: 1.6;
    }}
    .faq-item.open .faq-answer {{ max-height: 500px; padding-top: 0.75rem; }}

    /* ── Footer ── */
    .site-footer {{
      padding: clamp(2rem, 5vw, 3rem) 0;
      border-top: 1px solid var(--color-border);
      text-align: center;
      color: var(--color-muted);
      font-size: 0.85rem;
    }}
    .footer-brand {{ font-family: var(--font-display); font-weight: 700; font-size: 1.1rem; color: var(--color-text); margin-bottom: 0.5rem; }}
    .footer-links {{ display: flex; gap: 1.5rem; justify-content: center; margin: 1rem 0; flex-wrap: wrap; }}
    .footer-links a {{ color: var(--color-muted); font-size: 0.85rem; }}
    .footer-links a:hover {{ color: var(--color-text); }}

    /* ── Reveal ── */
    .reveal {{ opacity: 0; transform: translateY(20px); transition: opacity 0.6s ease, transform 0.6s ease; }}
    .reveal.revealed {{ opacity: 1; transform: translateY(0); }}

    /* ── Responsive ── */
    @media (max-width: 1024px) {{
      .grid-3 {{ grid-template-columns: repeat(auto-fit, minmax(min(100%, 260px), 1fr)); }}
    }}
    @media (max-width: 640px) {{
      .nav-links {{ display: none; }}
      .nav-toggle {{ display: block; }}
      .nav-links.open {{
        display: flex; flex-direction: column;
        position: absolute; top: 64px; left: 0; right: 0;
        background: var(--color-bg); border-bottom: 1px solid var(--color-border);
        padding: 1rem; gap: 0.75rem;
      }}
      .hero {{ padding: clamp(5rem, 10vw, 7rem) 0 clamp(2rem, 5vw, 3rem); }}
      .hero-ctas {{ flex-direction: column; align-items: center; }}
      .pricing-card {{ padding: 1.5rem; }}
      .step-card {{ padding-left: 3.5rem; }}
    }}
    @media (prefers-reduced-motion: reduce) {{
      .reveal, .reveal.revealed {{ opacity: 1; transform: none; transition: none; }}
    }}"""


def _font_import_url(site: SiteDesign) -> str:
    d = site.displayFont.replace(" ", "+")
    b = site.bodyFont.replace(" ", "+")
    return (
        f"https://fonts.googleapis.com/css2?family={d}:wght@300;400;600;700"
        f"&family={b}:wght@300;400;500;600&display=swap"
    )


# ---------------------------------------------------------------------------
# Navbar renderer
# ---------------------------------------------------------------------------

def _render_navbar(site: SiteDesign, nav: Navigation, current_path: str) -> str:
    is_sub = "/" in current_path
    prefix = "../" if is_sub else ""

    links_html = ""
    for link in nav.links:
        href = _resolve_href(link.href, is_sub)
        links_html += f'    <a href="{_e(href)}">{_e(link.label)}</a>\n'
    cta = nav.ctaButton
    cta_href = _resolve_href(cta.href, is_sub)
    links_html += f'    <a href="{_e(cta_href)}" class="btn btn-primary">{_e(cta.label)}</a>\n'

    home_href = f"{prefix}index.html"
    return f"""<nav class="navbar" role="navigation">
  <div class="nav-inner">
    <a href="{home_href}" class="nav-brand">{_e(site.logoText)}</a>
    <div class="nav-links">
{links_html}    </div>
    <button class="nav-toggle" aria-label="Toggle menu">&#9776;</button>
  </div>
</nav>"""


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------

def _render_section(section_type: str, props: dict[str, Any], site: SiteDesign) -> str:
    renderer = _SECTION_RENDERERS.get(section_type)
    if not renderer:
        return f"<!-- unknown section type: {section_type} -->"
    return renderer(props, site)


def _render_hero(props: dict[str, Any], site: SiteDesign) -> str:
    ctas = f'<a href="{_e(props.get("ctaHref", "#"))}" class="btn btn-primary">{_e(props.get("ctaText", "Get Started"))}</a>'
    sec_text = props.get("secondaryCtaText", "")
    if sec_text:
        ctas += f'\n      <a href="{_e(props.get("secondaryCtaHref", "#"))}" class="btn btn-secondary">{_e(sec_text)}</a>'
    return f"""<section class="hero reveal">
  <div class="container">
    <h1>{_e(props.get("headline", ""))}</h1>
    <p class="hero-sub">{_e(props.get("subheadline", ""))}</p>
    <div class="hero-ctas">
      {ctas}
    </div>
  </div>
</section>"""


def _render_features(props: dict[str, Any], site: SiteDesign) -> str:
    items = props.get("items", [])
    cards = ""
    for item in items:
        icon = item.get("icon", "") or "&#10024;"
        cards += f"""    <div class="card feature-card reveal">
      <div class="feature-icon">{icon}</div>
      <h3>{_e(item.get("title", ""))}</h3>
      <p>{_e(item.get("description", ""))}</p>
    </div>
"""
    return f"""<section class="section">
  <div class="container">
    <div class="section-header">
      <h2>{_e(props.get("heading", "Features"))}</h2>
      <p>{_e(props.get("subheading", ""))}</p>
    </div>
    <div class="grid grid-3">
{cards}    </div>
  </div>
</section>"""


def _render_cta(props: dict[str, Any], site: SiteDesign) -> str:
    return f"""<section class="section reveal">
  <div class="container">
    <div class="cta-section">
      <h2>{_e(props.get("heading", "Ready to get started?"))}</h2>
      <p>{_e(props.get("description", ""))}</p>
      <a href="{_e(props.get("buttonHref", "#"))}" class="btn btn-primary">{_e(props.get("buttonText", "Get Started"))}</a>
    </div>
  </div>
</section>"""


def _render_testimonials(props: dict[str, Any], site: SiteDesign) -> str:
    items = props.get("items", [])
    cards = ""
    for item in items:
        cards += f"""    <div class="card testimonial-card reveal">
      <blockquote>{_e(item.get("quote", ""))}</blockquote>
      <div class="testimonial-name">{_e(item.get("name", ""))}</div>
      <div class="testimonial-role">{_e(item.get("role", ""))}</div>
    </div>
"""
    return f"""<section class="section">
  <div class="container">
    <div class="section-header">
      <h2>{_e(props.get("heading", "What people say"))}</h2>
    </div>
    <div class="grid grid-3">
{cards}    </div>
  </div>
</section>"""


def _render_pricing(props: dict[str, Any], site: SiteDesign) -> str:
    tiers = props.get("tiers", [])
    cards = ""
    for tier in tiers:
        hl = " highlighted" if tier.get("highlighted") else ""
        badge = '<div class="pricing-badge">Most Popular</div>' if tier.get("highlighted") else ""
        features = ""
        for feat in tier.get("features", []):
            features += f"        <li>{_e(feat)}</li>\n"
        cards += f"""    <div class="card pricing-card{hl} reveal">
      {badge}
      <h3>{_e(tier.get("name", ""))}</h3>
      <div class="pricing-price">{_e(tier.get("price", "$0"))}</div>
      <div class="pricing-period">{_e(tier.get("period", "/mo"))}</div>
      <p>{_e(tier.get("description", ""))}</p>
      <ul class="pricing-features">
{features}      </ul>
      <a href="pages/signup.html" class="btn btn-primary" style="width:100%">{_e(tier.get("ctaText", "Choose Plan"))}</a>
    </div>
"""
    return f"""<section class="section" id="pricing">
  <div class="container">
    <div class="section-header">
      <h2>{_e(props.get("heading", "Pricing"))}</h2>
      <p>{_e(props.get("subheading", ""))}</p>
    </div>
    <div class="grid grid-3">
{cards}    </div>
  </div>
</section>"""


def _render_faq(props: dict[str, Any], site: SiteDesign) -> str:
    items = props.get("items", [])
    faq_html = ""
    for item in items:
        faq_html += f"""    <div class="faq-item">
      <div class="faq-question">{_e(item.get("question", ""))}</div>
      <div class="faq-answer">{_e(item.get("answer", ""))}</div>
    </div>
"""
    return f"""<section class="section">
  <div class="container">
    <div class="section-header">
      <h2>{_e(props.get("heading", "FAQ"))}</h2>
    </div>
    <div style="max-width:720px;margin-inline:auto">
{faq_html}    </div>
  </div>
</section>"""


def _render_footer(props: dict[str, Any], site: SiteDesign) -> str:
    links_html = ""
    for link in props.get("links", []):
        links_html += f'    <a href="{_e(link.get("href", "#"))}">{_e(link.get("label", ""))}</a>\n'
    tagline = props.get("tagline", "")
    tagline_html = f"<p>{_e(tagline)}</p>" if tagline else ""
    return f"""<footer class="site-footer">
  <div class="container">
    <div class="footer-brand">{_e(props.get("brand", site.logoText))}</div>
    {tagline_html}
    <div class="footer-links">
{links_html}    </div>
    <p>{_e(props.get("copyright", ""))}</p>
  </div>
</footer>"""


def _render_stats(props: dict[str, Any], site: SiteDesign) -> str:
    items = props.get("items", [])
    stats_html = ""
    for item in items:
        stats_html += f"""    <div class="stat-item reveal">
      <div class="stat-value">{_e(item.get("value", "0"))}</div>
      <div class="stat-label">{_e(item.get("label", ""))}</div>
    </div>
"""
    heading = props.get("heading", "")
    header = f'<div class="section-header"><h2>{_e(heading)}</h2></div>' if heading else ""
    return f"""<section class="section">
  <div class="container">
    {header}
    <div class="grid grid-4">
{stats_html}    </div>
  </div>
</section>"""


def _render_how_it_works(props: dict[str, Any], site: SiteDesign) -> str:
    steps = props.get("steps", [])
    steps_html = ""
    for step in steps:
        steps_html += f"""    <div class="step-card reveal">
      <h3>{_e(step.get("title", ""))}</h3>
      <p>{_e(step.get("description", ""))}</p>
    </div>
"""
    return f"""<section class="section">
  <div class="container">
    <div class="section-header">
      <h2>{_e(props.get("heading", "How it works"))}</h2>
    </div>
    <div class="steps-grid" style="display:grid;gap:2rem;max-width:640px;margin-inline:auto">
{steps_html}    </div>
  </div>
</section>"""


_SECTION_RENDERERS = {
    "hero": _render_hero,
    "features": _render_features,
    "cta": _render_cta,
    "testimonials": _render_testimonials,
    "pricing": _render_pricing,
    "faq": _render_faq,
    "footer": _render_footer,
    "stats": _render_stats,
    "how_it_works": _render_how_it_works,
}


# ---------------------------------------------------------------------------
# Auth page renderer
# ---------------------------------------------------------------------------

def _render_auth_page(page: Page, site: SiteDesign, nav: Navigation) -> str:
    raw = page.props or {}
    try:
        p = AuthPageProps.model_validate(raw)
    except Exception:
        p = AuthPageProps()

    fields_html = ""
    for f in p.fields:
        input_type = "password" if f == "password" else ("email" if f == "email" else "text")
        label = f.replace("_", " ").title()
        fields_html += f"""      <div class="form-group">
        <label for="{_e(f)}">{_e(label)}</label>
        <input type="{input_type}" id="{_e(f)}" name="{_e(f)}" required
               aria-label="{_e(label)}" placeholder="Enter your {_e(f)}">
      </div>
"""
    css = _base_css(site)
    font_url = _font_import_url(site)
    auth_css = """
    .auth-page {
      min-height: 100vh; display: flex; align-items: center; justify-content: center;
      padding: 2rem 1rem;
    }
    .auth-card {
      background: var(--color-surface); border: 1px solid var(--color-border);
      border-radius: var(--radius-lg); padding: clamp(2rem, 5vw, 3rem);
      width: 100%; max-width: 440px; box-shadow: var(--shadow-lg);
    }
    .auth-card h1 { font-size: 1.5rem; text-align: center; margin-bottom: 0.5rem; }
    .auth-brand { text-align: center; margin-bottom: 2rem; }
    .auth-brand a {
      font-family: var(--font-display); font-weight: 700; font-size: 1.1rem;
      color: var(--color-text); text-decoration: none;
    }
    .form-group { margin-bottom: 1.25rem; }
    .form-group label { display: block; margin-bottom: 0.4rem; font-size: 0.9rem; font-weight: 500; }
    .form-group input {
      width: 100%; padding: 10px 14px; border: 1px solid var(--color-border);
      border-radius: var(--radius-sm); font-size: 0.95rem; font-family: var(--font-body);
      background: var(--color-bg); color: var(--color-text);
      transition: border-color 200ms;
    }
    .form-group input:focus { outline: none; border-color: var(--color-primary); }
    .auth-submit { width: 100%; margin-top: 0.5rem; }
    .auth-alt { text-align: center; margin-top: 1.5rem; font-size: 0.9rem; color: var(--color-muted); }
    .auth-alt a { color: var(--color-primary); }"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{_e(page.title or p.heading)} — {_e(site.title)}</title>
  <style>
    @import url('{font_url}');
{css}
{auth_css}
  </style>
</head>
<body>
<div class="auth-page">
  <div class="auth-card">
    <div class="auth-brand"><a href="../index.html">{_e(site.logoText)}</a></div>
    <h1>{_e(p.heading)}</h1>
    <form action="../app.html" method="get" style="margin-top:1.5rem">
{fields_html}
      <button type="submit" class="btn btn-primary auth-submit">{_e(p.submitText)}</button>
    </form>
    <div class="auth-alt"><a href="{_e(p.altLinkHref)}">{_e(p.altLinkText)}</a></div>
  </div>
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Dashboard page renderer
# ---------------------------------------------------------------------------

def _render_dashboard_page(page: Page, site: SiteDesign) -> str:
    raw = page.props or {}
    try:
        p = DashboardPageProps.model_validate(raw)
    except Exception:
        p = DashboardPageProps(welcomeHeading=f"Welcome to {site.logoText}")

    sidebar_links = ""
    for link in p.sidebarLinks:
        icon = link.icon or "&#128196;"
        sidebar_links += f'    <a href="{_e(link.href)}">{icon} {_e(link.label)}</a>\n'

    metrics_html = ""
    for m in p.metrics:
        icon = m.icon or "&#128200;"
        metrics_html += f"""      <div class="card metric-card">
        <div style="font-size:1.5rem;margin-bottom:0.5rem">{icon}</div>
        <div class="stat-value" style="font-size:1.75rem">{_e(m.value)}</div>
        <div class="stat-label">{_e(m.label)}</div>
      </div>
"""

    css = _base_css(site)
    font_url = _font_import_url(site)
    dash_css = """
    .dash-layout { display: flex; min-height: 100vh; }
    .dash-sidebar {
      width: 260px; background: var(--color-surface);
      border-right: 1px solid var(--color-border);
      padding: 1.5rem 1rem; display: flex; flex-direction: column; gap: 0.25rem;
    }
    .dash-sidebar .sidebar-brand {
      font-family: var(--font-display); font-weight: 700;
      font-size: 1.15rem; padding: 0.5rem; margin-bottom: 1rem; color: var(--color-text);
    }
    .dash-sidebar a {
      display: flex; align-items: center; gap: 10px;
      padding: 10px 12px; border-radius: var(--radius-sm);
      color: var(--color-muted); text-decoration: none; font-size: 0.9rem;
      transition: all 150ms;
    }
    .dash-sidebar a:hover { background: var(--color-bg); color: var(--color-text); }
    .dash-main { flex: 1; padding: clamp(1.5rem, 3vw, 2.5rem); overflow-y: auto; }
    .dash-main h1 { font-size: 1.5rem; margin-bottom: 1.5rem; }
    .metric-card { text-align: center; }
    @media (max-width: 640px) {
      .dash-sidebar { display: none; }
      .dash-main { padding: 1rem; }
    }"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{_e(page.title or "Dashboard")} — {_e(site.title)}</title>
  <style>
    @import url('{font_url}');
{css}
{dash_css}
  </style>
</head>
<body>
<div class="dash-layout">
  <aside class="dash-sidebar">
    <div class="sidebar-brand">{_e(site.logoText)}</div>
{sidebar_links}
    <a href="index.html" style="margin-top:auto">&#8592; Back to site</a>
  </aside>
  <main class="dash-main">
    <h1>{_e(p.welcomeHeading)}</h1>
    <div class="grid grid-4" style="margin-bottom:2rem">
{metrics_html}    </div>
    <div class="card" style="padding:2rem">
      <h3 style="margin-bottom:1rem">Connect your API</h3>
      <p style="color:var(--color-muted);margin-bottom:1rem">Paste your API token below to connect.</p>
      <input type="text" placeholder="sk-..." style="width:100%;max-width:400px;padding:10px 14px;border:1px solid var(--color-border);border-radius:var(--radius-sm);font-family:var(--font-body);background:var(--color-bg);color:var(--color-text)">
    </div>
  </main>
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# JS (shared across landing/content pages)
# ---------------------------------------------------------------------------

def _base_js() -> str:
    return """<script>
'use strict';
document.addEventListener('DOMContentLoaded', function() {
  // Scroll reveal
  var reveals = document.querySelectorAll('.reveal');
  if (reveals.length && 'IntersectionObserver' in window) {
    var obs = new IntersectionObserver(function(entries) {
      entries.forEach(function(e) { if (e.isIntersecting) { e.target.classList.add('revealed'); obs.unobserve(e.target); } });
    }, { threshold: 0.1 });
    reveals.forEach(function(el) { obs.observe(el); });
  } else {
    reveals.forEach(function(el) { el.classList.add('revealed'); });
  }

  // Sticky navbar
  var nav = document.querySelector('.navbar');
  if (nav) {
    window.addEventListener('scroll', function() {
      nav.classList.toggle('scrolled', window.scrollY > 20);
    }, { passive: true });
  }

  // Mobile toggle
  var toggle = document.querySelector('.nav-toggle');
  var links = document.querySelector('.nav-links');
  if (toggle && links) {
    toggle.addEventListener('click', function() { links.classList.toggle('open'); });
  }

  // FAQ accordion
  document.querySelectorAll('.faq-question').forEach(function(q) {
    q.addEventListener('click', function() { q.parentElement.classList.toggle('open'); });
  });
});
</script>"""


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _e(text: str) -> str:
    """HTML-escape text."""
    return html_mod.escape(str(text or ""))


def _resolve_href(href: str, from_subpage: bool) -> str:
    """Adjust relative href based on whether we're rendering a subpage."""
    if href.startswith(("http://", "https://", "#", "mailto:", "tel:")):
        return href
    if from_subpage:
        if href.startswith("pages/"):
            return href.replace("pages/", "", 1)
        if not href.startswith("../"):
            return f"../{href}"
    return href


def _hex_to_rgb_str(hex_color: str) -> str:
    """Convert #rrggbb to 'r, g, b' string for rgba() usage."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = h[0]*2 + h[1]*2 + h[2]*2
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"{r},{g},{b}"
    except (ValueError, IndexError):
        return "248,250,252"
