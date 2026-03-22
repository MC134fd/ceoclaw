"""
Link wiring — post-generation pass that normalises href/src references,
scaffolds missing pages, and injects nav links deterministically.

Public API:
    run_link_wiring_pass(slug, changes, operation) -> (updated_changes, warnings)
    normalize_link(href) -> canonical_relative_path
    scaffold_missing_page(slug, page_rel_path) -> FileChange
    _inject_nav_link(html, label, href) -> html
    _repair_html_links(html, available_pages) -> (html, fixes)
    _build_route_graph(slug, changes) -> dict
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.code_generation_service import FileChange

# ---------------------------------------------------------------------------
# href normalisation
# ---------------------------------------------------------------------------

# Maps bare page names to canonical relative paths inside the website dir
_PAGE_NAME_CANONICAL: dict[str, str] = {
    "index": "index.html",
    "home": "index.html",
    "app": "app.html",
    "dashboard": "app.html",
    "pricing": "pages/pricing.html",
    "about": "pages/about.html",
    "contact": "pages/contact.html",
    "blog": "pages/blog.html",
    "faq": "pages/faq.html",
    "terms": "pages/terms.html",
    "privacy": "pages/privacy.html",
    "signup": "pages/signup.html",
    "register": "pages/signup.html",
    "login": "pages/login.html",
    "signin": "pages/login.html",
    "docs": "pages/docs.html",
    "documentation": "pages/docs.html",
    "portfolio": "pages/portfolio.html",
    "gallery": "pages/gallery.html",
    "careers": "pages/careers.html",
    "team": "pages/team.html",
    "landing": "index.html",
}

# href="something" where something starts with /route (absolute route, no extension)
_ROUTE_HREF_RE = re.compile(r'href=["\']/([\w-]+)/?["\']', re.IGNORECASE)


def normalize_link(href: str) -> str:
    """Normalise a bare route or absolute path to a canonical relative HTML path.

    Examples:
        /pricing  → pages/pricing.html
        pricing   → pages/pricing.html
        /app      → app.html
        app.html  → app.html  (unchanged — already has extension)
    """
    stripped = href.strip().lstrip("/")
    # Already has extension — return as-is
    last_part = stripped.split("/")[-1]
    if "." in last_part:
        return stripped
    # Look up in canonical map
    lower = stripped.lower().rstrip("/")
    return _PAGE_NAME_CANONICAL.get(lower, f"pages/{lower}.html")


# ---------------------------------------------------------------------------
# Minimal page scaffold
# ---------------------------------------------------------------------------

_PAGE_SCAFFOLD_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>
    :root {{
      --color-bg: #fff;
      --color-text: #111;
      --color-accent: #2563eb;
      --radius: 0.5rem;
      --space-md: clamp(0.75rem, 1.5vw, 1.25rem);
      --space-xl: clamp(1.5rem, 3vw, 2.5rem);
      --space-2xl: clamp(2rem, 5vw, 4rem);
      --container-width: clamp(320px, 90vw, 1200px);
    }}
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: system-ui, sans-serif; background: var(--color-bg); color: var(--color-text); }}
    nav {{
      padding: 1rem 1.5rem;
      border-bottom: 1px solid #e5e7eb;
      display: flex;
      gap: 1.5rem;
    }}
    nav a {{
      color: var(--color-accent);
      text-decoration: none;
      min-height: 44px;
      display: inline-flex;
      align-items: center;
    }}
    .page-container {{
      max-width: var(--container-width);
      margin-inline: auto;
      padding: var(--space-2xl) var(--space-md);
    }}
    h1 {{
      font-size: clamp(1.75rem, 4vw, 2.5rem);
      margin-bottom: 1rem;
      letter-spacing: -0.02em;
    }}
    p {{ line-height: 1.7; max-width: 65ch; }}
    @media (max-width: 1024px) {{ .page-container {{ padding: var(--space-xl) var(--space-md); }} }}
    @media (max-width: 640px) {{ h1 {{ font-size: 1.5rem; }} }}
  </style>
</head>
<body>
  <nav>
    <a href="../index.html">\u2190 Home</a>
  </nav>
  <main class="page-container">
    <h1>{heading}</h1>
    <p>{body}</p>
  </main>
</body>
</html>"""

_PAGE_COPY: dict[str, tuple[str, str, str]] = {
    "pricing":   ("Pricing",        "Simple, transparent pricing",
                  "Choose the plan that works best for you. All plans include a 14-day free trial with no credit card required."),
    "about":     ("About Us",       "Our story",
                  "We\u2019re on a mission to help people work smarter. Learn about our team, values, and what drives us every day."),
    "contact":   ("Contact",        "Get in touch",
                  "Have a question or need support? We\u2019d love to hear from you. Reach out and we\u2019ll get back to you within 24 hours."),
    "terms":     ("Terms of Service", "Terms of Service",
                  "By using our service, you agree to these terms. Please read them carefully before accessing or using our platform."),
    "privacy":   ("Privacy Policy", "Privacy Policy",
                  "Your privacy matters to us. This policy describes what data we collect, how we use it, and your rights."),
    "signup":    ("Sign Up",        "Create your account",
                  "Join thousands of users already building with us. It\u2019s free to get started."),
    "login":     ("Log In",         "Welcome back",
                  "Log in to your account to continue where you left off."),
    "faq":       ("FAQ",            "Frequently Asked Questions",
                  "Find answers to the most common questions about our product, pricing, and support."),
    "blog":      ("Blog",           "Latest updates",
                  "Stay up to date with the latest product news, tips, and industry insights from our team."),
    "docs":      ("Documentation",  "Documentation",
                  "Everything you need to get started and make the most of our platform."),
    "portfolio": ("Portfolio",      "Our work",
                  "Explore our portfolio of projects, case studies, and success stories."),
    "gallery":   ("Gallery",        "Gallery",
                  "Browse our collection of images, screenshots, and product visuals."),
    "careers":   ("Careers",        "Join our team",
                  "We\u2019re always looking for talented people. See open positions and apply today."),
    "team":      ("Team",           "Meet the team",
                  "The people behind the product. Get to know us."),
}


def scaffold_missing_page(slug: str, page_rel_path: str) -> "FileChange":
    """Return a FileChange that creates a minimal scaffold for a missing page.

    Args:
        slug: Project slug (used to build the full path).
        page_rel_path: Relative path inside the site dir, e.g. "pages/pricing.html".
    """
    from services.code_generation_service import FileChange

    name_stem = PurePosixPath(page_rel_path).stem.lower()
    title, heading, body = _PAGE_COPY.get(
        name_stem,
        (
            name_stem.replace("-", " ").title(),
            name_stem.replace("-", " ").title(),
            "Content coming soon.",
        ),
    )
    content = _PAGE_SCAFFOLD_TEMPLATE.format(title=title, heading=heading, body=body)
    return FileChange(
        path=f"data/websites/{slug}/{page_rel_path}",
        action="create",
        content=content,
        summary=f"Scaffolded missing page: {page_rel_path}",
    )


# ---------------------------------------------------------------------------
# Nav link injection
# ---------------------------------------------------------------------------

_NAV_RE = re.compile(r"(<nav\b[^>]*>)(.*?)(</nav>)", re.IGNORECASE | re.DOTALL)

# Any link that resolves back to index from a pages/* file
_BACK_LINK_RE = re.compile(
    r'href=["\'](\.\./index\.html|\.\./?|index\.html)["\']',
    re.IGNORECASE,
)


def _inject_nav_link(html: str, label: str, href: str) -> str:
    """Inject a nav link into the first <nav> element if not already present.

    Idempotent — if *href* already appears in the nav, returns *html* unchanged.
    """
    # Already present anywhere in the document?
    if href in html:
        return html

    def _inserter(m: re.Match) -> str:  # type: ignore[type-arg]
        open_tag, nav_content, close_tag = m.group(1), m.group(2), m.group(3)
        link = f'<a href="{href}">{label.title()}</a>'
        return open_tag + nav_content.rstrip() + f"\n    {link}\n  " + close_tag

    modified, n = _NAV_RE.subn(_inserter, html, count=1)
    return modified if n else html


# ---------------------------------------------------------------------------
# HTML link repair
# ---------------------------------------------------------------------------


def _repair_html_links(html: str, available_pages: set[str]) -> tuple[str, list[str]]:
    """Rewrite broken absolute-route hrefs to canonical relative paths.

    Only rewrites paths that match /word (no extension) — absolute routes
    like /pricing become pages/pricing.html.

    Returns (repaired_html, list_of_fixes_applied).
    """
    fixes: list[str] = []

    def _replace_route(m: re.Match) -> str:  # type: ignore[type-arg]
        page_name = m.group(1)
        canonical = normalize_link(f"/{page_name}")
        fixes.append(f"Rewrote href='/{page_name}' \u2192 '{canonical}'")
        return f'href="{canonical}"'

    repaired = _ROUTE_HREF_RE.sub(_replace_route, html)
    return repaired, fixes


# ---------------------------------------------------------------------------
# Route graph builder
# ---------------------------------------------------------------------------

_LINK_HREF_RE = re.compile(
    r'href=["\'](?!https?://|//|#|mailto:|tel:|data:)([^"\']+)["\']',
    re.IGNORECASE,
)


def _build_route_graph(slug: str, changes: list["FileChange"]) -> dict:
    """Build a route graph from the generated file changes.

    Returns {"nodes": [...], "edges": [{"from": ..., "to": ..., "label": "link"}]}.
    """
    nodes: list[str] = []
    edges: list[dict] = []
    seen_edges: set[tuple[str, str]] = set()

    html_changes = {
        c.path.split(f"/{slug}/")[-1]: c
        for c in changes
        if c.path.endswith(".html")
    }

    for rel_path, change in html_changes.items():
        if rel_path not in nodes:
            nodes.append(rel_path)
        for m in _LINK_HREF_RE.finditer(change.content):
            href = m.group(1).strip().lstrip("./")
            if href and href != rel_path:
                key = (rel_path, href)
                if key not in seen_edges:
                    seen_edges.add(key)
                    edges.append({"from": rel_path, "to": href, "label": "link"})

    return {"nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# Main pass
# ---------------------------------------------------------------------------


def run_link_wiring_pass(
    slug: str,
    changes: list["FileChange"],
    operation: dict | None,
) -> tuple[list["FileChange"], list[str]]:
    """Run the full link-wiring post-processing pass.

    Steps:
    1. Repair absolute-route hrefs (e.g. /pricing → pages/pricing.html) in all HTML files.
    2. For add_page / cta_target_change / update_nav operations: scaffold any missing
       target pages that appear in navigation_targets or page_targets but are not in changes.
    3. For update_nav operations: inject the nav link into index.html.

    Returns (updated_changes, warnings_and_fixes).
    """
    from services.code_generation_service import FileChange

    warnings: list[str] = []
    op_type = (operation or {}).get("type", "")
    op_target = (operation or {}).get("target", "")
    nav_targets: list[str] = list((operation or {}).get("navigation_targets") or [])
    page_targets: list[str] = list((operation or {}).get("page_targets") or [])

    # Build set of already-present page paths (relative to slug root)
    available_pages: set[str] = {
        c.path.split(f"/{slug}/")[-1]
        for c in changes
        if c.path.endswith(".html")
    }

    updated_changes: list[FileChange] = list(changes)

    # ── Step 1: Repair absolute-route hrefs in all HTML files ────────────────
    for i, change in enumerate(updated_changes):
        if not change.path.endswith(".html"):
            continue
        repaired, fixes = _repair_html_links(change.content, available_pages)
        if fixes:
            updated_changes[i] = FileChange(
                path=change.path,
                action=change.action,
                content=repaired,
                summary=change.summary,
            )
            warnings.extend(fixes)

    # ── Step 1b: Back-link check — every pages/*.html must have a return path ─
    for i, change in enumerate(updated_changes):
        rel_path = change.path.split(f"/{slug}/")[-1]
        if not rel_path.startswith("pages/") or not rel_path.endswith(".html"):
            continue
        html = updated_changes[i].content
        if not _BACK_LINK_RE.search(html):
            warnings.append(
                f"No return path on '{rel_path}' — injecting '← Home' nav link"
            )
            repaired = _inject_nav_link(html, "← Home", "../index.html")
            if repaired != html:
                updated_changes[i] = FileChange(
                    path=change.path,
                    action=change.action,
                    content=repaired,
                    summary=change.summary,
                )

    # ── Step 2: Scaffold missing pages ──────────────────────────────────────
    if op_type in ("add_page", "cta_target_change", "update_nav"):
        candidates: list[str] = []
        for t in nav_targets + page_targets:
            if t:
                candidates.append(t)
        if op_target:
            candidates.append(op_target)

        scaffolded: set[str] = set()
        for raw in candidates:
            # Determine canonical path
            if "/" in raw and "." in raw.split("/")[-1]:
                canonical = raw.lstrip("/")
            else:
                canonical = normalize_link(raw)

            if canonical in available_pages or canonical in scaffolded:
                continue

            scaffold = scaffold_missing_page(slug, canonical)
            updated_changes.append(scaffold)
            available_pages.add(canonical)
            scaffolded.add(canonical)
            warnings.append(f"Scaffolded missing page: {canonical}")

    # ── Step 3: Nav link injection for update_nav operations ────────────────
    if op_type == "update_nav" and nav_targets:
        index_idx = next(
            (i for i, c in enumerate(updated_changes) if c.path.endswith("index.html")),
            None,
        )
        if index_idx is not None:
            change = updated_changes[index_idx]
            html = change.content
            for target in nav_targets:
                canonical = normalize_link(target)
                label = target.replace("-", " ").replace("/", "").title()
                html = _inject_nav_link(html, label, canonical)
            updated_changes[index_idx] = FileChange(
                path=change.path,
                action=change.action,
                content=html,
                summary=change.summary,
            )
            warnings.append(f"Injected nav links for: {nav_targets}")

    return updated_changes, warnings
