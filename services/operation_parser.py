"""
Operation parser — detects structured operation intent from user messages.
Operations are additive hints that guide LLM + routing logic.
"""
from __future__ import annotations

import re

OPERATION_PATTERNS: dict[str, list[str]] = {
    "add_page": [
        r"\badd\b.*\bpage\b",
        r"\bcreate\b.*\bpage\b",
        r"\bnew page\b",
        r"\bterms\b.*\bpage\b",
        r"\bprivacy\b.*\bpage\b",
        r"\babout\b.*\bpage\b",
        r"\bpricin\b.*\bpage\b",
        r"\badd\b.*\bsignup\b",
        r"\bcreate\b.*\bsignup\b",
        r"\badd\b.*\blogin\b",
        r"\bcreate\b.*\blogin\b",
        r"\badd\b.*\bcontact\b.*\bpage\b",
        r"\badd\b.*\bdashboard\b.*\bpage\b",
        r"\badd\b.*\bblog\b",
        r"\badd\b.*\bportfolio\b",
        r"\badd\b.*\bgallery\b",
        r"\badd\b.*\bcareers?\b",
        r"\badd\b.*\bteam\b.*\bpage\b",
    ],
    "add_component": [
        r"\badd\b.*\bsection\b",
        r"\badd\b.*\bcomponent\b",
        r"\badd\b.*\bblock\b",
        r"\badd\b.*\btestimonial\b",
        r"\badd\b.*\bfaq\b",
        r"\badd\b.*\bnavbar\b",
        r"\badd\b.*\bfooter\b",
        r"\badd\b.*\bpricing\b",
        r"\badd\b.*\bhero\b",
    ],
    "add_endpoint": [
        r"\badd\b.*\bendpoint\b",
        r"\bapi\b.*\broute\b",
        r"\bbackend\b.*\bapi\b",
        r"\brest\b.*\bapi\b",
        r"\bpost\b.*\bapi\b",
        r"\bget\b.*\bapi\b",
    ],
    "cta_target_change": [
        r"\bcta\b.*\bshould\b.*\bgo\b",
        r"\bcta\b.*\blink\b.*\bto\b",
        r"\bcta\b.*\bpoint\b.*\bto\b",
        r"\bbutton\b.*\bshould\b.*\bgo\b",
        r"\bchange\b.*\bcta\b.*\bto\b",
        r"\bconnect\b.*\bbutton\b.*\bto\b",
        r"\bwire\b.*\bbutton\b.*\bto\b",
        r"\bbutton\b.*\bshould\b.*\blink\b",
        r"\bbutton\b.*\bshould\b.*\bopen\b",
    ],
    "add_feature": [
        r"\badd\b.*\bfeature\b",
        r"\bbuild\b.*\bfeature\b",
        r"\bimplement\b.*\bfeature\b",
        r"\bcalculator\b",
        r"\bform\b",
        r"\bsearch\b",
        r"\bauth\b",
        r"\blogin\b",
        r"\bsignup\b",
    ],
    "add_legal_page": [
        r"\bterms\b",
        r"\bprivacy policy\b",
        r"\bterms of service\b",
        r"\bterms and conditions\b",
        r"\bcookie policy\b",
        r"\bgdpr\b",
    ],
    "modify_style": [
        r"\bchange\b.*\bcolor\b",
        r"\bchange\b.*\bstyle\b",
        r"\bmake\b.*\bdark\b",
        r"\bmake\b.*\blight\b",
        r"\bupdate\b.*\bdesign\b",
        r"\bredesign\b",
        r"\bnew color\b",
        r"\bnew font\b",
        r"\btheme\b",
    ],
    "remove_page": [
        r"\bremove\b.*\bpage\b",
        r"\bdelete\b.*\bpage\b",
        r"\bdrop\b.*\bpage\b",
    ],
    "update_nav": [
        r"\bupdate\b.*\bnav\b",
        r"\badd\b.*\bnav\b.*\blink\b",
        r"\bremove\b.*\bnav\b.*\blink\b",
        r"\bchange\b.*\bnav\b",
        r"\bnavbar\b.*\badd\b",
        r"\bnavbar\b.*\bremove\b",
        r"\bnavigation\b.*\bupdate\b",
    ],
}


def parse_operation(message: str) -> dict:
    """
    Detect operation type and extract relevant metadata.
    Returns {
        "type": str,
        "target": str,
        "metadata": dict,
        "placement_targets": list[str],
        "navigation_targets": list[str],
        "page_targets": list[str],  # canonical paths e.g. ["pages/pricing.html"]
    }
    """
    msg_lower = message.lower()
    op_type = "general_edit"
    target = ""
    metadata: dict = {}

    for detected_type, patterns in OPERATION_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, msg_lower):
                op_type = detected_type
                target = _extract_target(msg_lower, detected_type)
                metadata = _extract_metadata(msg_lower, detected_type)
                break
        if op_type != "general_edit":
            break

    return {
        "type": op_type,
        "target": target,
        "metadata": metadata,
        "placement_targets": _extract_placement_targets(msg_lower),
        "navigation_targets": _extract_navigation_targets(msg_lower),
        "page_targets": _extract_page_targets(target, op_type),
    }


_PAGE_NAMES_RE = re.compile(
    r"\b(terms|privacy|about|pricing|contact|blog|faq|docs?|landing|app"
    r"|signup|register|login|signin|dashboard|portfolio|gallery|careers?|team)\b"
)


def _extract_target(msg: str, op_type: str) -> str:
    if op_type in ("add_page", "remove_page", "update_nav"):
        m = _PAGE_NAMES_RE.search(msg)
        if m:
            name = m.group(1)
            # Normalise aliases
            if name in ("register",):
                name = "signup"
            elif name in ("signin",):
                name = "login"
            elif name in ("docs",):
                name = "docs"
            return name
        return "page" if op_type == "add_page" else ""
    if op_type == "add_legal_page":
        m = re.search(r"\b(terms|privacy|cookie|gdpr)\b", msg)
        return m.group(1) if m else "legal"
    if op_type == "cta_target_change":
        targets = _extract_navigation_targets(msg)
        return targets[0] if targets else ""
    return ""


# Canonical page path map (mirrors link_wiring._PAGE_NAME_CANONICAL without import)
_TARGET_CANONICAL: dict[str, str] = {
    "index": "index.html",
    "home": "index.html",
    "app": "app.html",
    "dashboard": "app.html",
    "landing": "index.html",
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
    "doc": "pages/docs.html",
    "docs": "pages/docs.html",
    "portfolio": "pages/portfolio.html",
    "gallery": "pages/gallery.html",
    "career": "pages/careers.html",
    "careers": "pages/careers.html",
    "team": "pages/team.html",
}


def _extract_page_targets(target: str, op_type: str) -> list[str]:
    """Return canonical page paths for the detected operation target.

    E.g. target="pricing", op_type="add_page" → ["pages/pricing.html"]
    Returns empty list for non-page operations or unknown targets.
    """
    if op_type not in ("add_page", "remove_page", "update_nav", "add_legal_page"):
        return []
    if not target or target == "page":
        return []
    canonical = _TARGET_CANONICAL.get(target.lower(), f"pages/{target.lower()}.html")
    return [canonical]


def _extract_metadata(msg: str, op_type: str) -> dict:
    if op_type == "add_endpoint":
        methods = [m for m in ["GET", "POST", "PUT", "DELETE", "PATCH"] if m.lower() in msg]
        return {"http_methods": methods or ["GET", "POST"]}
    return {}


# Section name keywords recognisable as placement targets
_SECTION_KEYWORDS = [
    "hero", "features", "feature", "footer", "header", "navbar",
    "pricing", "testimonials", "testimonial", "faq", "cta",
    "about", "contact", "blog", "sidebar", "banner", "gallery",
]

# Placement trigger phrases — "place in X", "add to X section", "put in X"
_PLACEMENT_RE = re.compile(
    r"(?:place|put|add|insert|move)\b.*?\bin\b.*?\b(" + "|".join(_SECTION_KEYWORDS) + r")\b",
    re.IGNORECASE,
)
# Bare "… <section> section" pattern (e.g. "add to features section")
_PLACEMENT_SECTION_RE = re.compile(
    r"\b(" + "|".join(_SECTION_KEYWORDS) + r")\s+section\b",
    re.IGNORECASE,
)


def _extract_placement_targets(msg: str) -> list[str]:
    """Return section names mentioned as placement destinations."""
    found: list[str] = []
    seen: set[str] = set()

    for m in _PLACEMENT_RE.finditer(msg):
        name = m.group(1).lower()
        if name not in seen:
            seen.add(name)
            found.append(name)

    for m in _PLACEMENT_SECTION_RE.finditer(msg):
        name = m.group(1).lower()
        if name not in seen:
            seen.add(name)
            found.append(name)

    return found


# Navigation trigger patterns — extract page/route names
_NAV_EXPLICIT_ROUTE_RE = re.compile(
    r"(?:add\s+(?:a\s+)?link\s+to|navigate\s+to|goes?\s+to|link\s+to)\s+(?:the\s+)?(/[^\s,]+)",
    re.IGNORECASE,
)
# "CTA should go to signup", "add link to the pricing page", "add link to contact page"
_NAV_PAGE_NAME_RE = re.compile(
    r"(?:add\s+(?:a\s+)?link\s+to|navigate\s+to|goes?\s+to|link\s+to|cta\s+(?:should\s+)?(?:go\s+to|link\s+to))\s+(?:the\s+)?(\w+)(?:\s+page)?",
    re.IGNORECASE,
)
# "new X page" — treat as navigation target too
_NAV_NEW_PAGE_RE = re.compile(r"\bnew\s+(\w+)\s+page\b", re.IGNORECASE)


def _extract_navigation_targets(msg: str) -> list[str]:
    """Return page/route strings mentioned as navigation targets."""
    found: list[str] = []
    seen: set[str] = set()

    def _add(val: str) -> None:
        v = val.strip().lower().rstrip("/")
        if v and v not in seen:
            seen.add(v)
            found.append(v)

    for m in _NAV_EXPLICIT_ROUTE_RE.finditer(msg):
        _add(m.group(1))

    for m in _NAV_PAGE_NAME_RE.finditer(msg):
        name = m.group(1).lower()
        # skip generic stop words
        if name not in {"the", "a", "an", "my", "our", "your", "this", "that"}:
            _add(name)

    for m in _NAV_NEW_PAGE_RE.finditer(msg):
        _add(m.group(1))

    return found
