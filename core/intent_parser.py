"""
Intent parser — extracts structured product intent from a raw chat message.

No model call required: uses regex + keyword heuristics so it works in
mock mode and doesn't burn API budget for intent extraction.

Returns a ProductIntent dict that is persisted into CEOClawState and
available to every downstream node.
"""

from __future__ import annotations

import re
from typing import Any


# ---------------------------------------------------------------------------
# Keyword maps
# ---------------------------------------------------------------------------

_TYPE_KEYWORDS: dict[str, list[str]] = {
    "saas": ["saas", "subscription", "platform", "dashboard", "tracker", "manager",
             "scheduler", "planner", "crm", "analytics", "monitoring"],
    "marketplace": ["marketplace", "directory", "listing", "connect buyers", "two-sided"],
    "tool": ["tool", "utility", "generator", "converter", "calculator", "extension"],
    "app": ["app", "mobile", "ios", "android", "pwa"],
    "api": ["api", "sdk", "integration", "webhook", "service"],
    "content": ["blog", "newsletter", "community", "forum", "course", "learning"],
}

_USER_KEYWORDS: dict[str, list[str]] = {
    "founders": ["founder", "startup", "entrepreneur", "indie hacker", "bootstrapper"],
    "developers": ["developer", "engineer", "programmer", "coder", "devops", "dev"],
    "fitness enthusiasts": ["fitness", "gym", "workout", "health", "exercise", "athlete"],
    "consumers": ["calorie", "diet", "food", "weight", "personal", "everyday", "user"],
    "small businesses": ["small business", "smb", "freelancer", "consultant", "agency"],
    "enterprises": ["enterprise", "team", "company", "b2b", "corporate"],
    "students": ["student", "education", "learning", "school", "university"],
}

_FEATURE_KEYWORDS: list[tuple[str, str]] = [
    (r"track\w*", "tracking"),
    (r"dashboard", "dashboard"),
    (r"analytic\w*", "analytics"),
    (r"notif\w*", "notifications"),
    (r"auth\w*|login|signup", "authentication"),
    (r"payment\w*|billing|stripe|subscription", "payments"),
    (r"search\w*", "search"),
    (r"export\w*|import\w*", "data import/export"),
    (r"api\b", "API access"),
    (r"mobil\w*|responsive", "mobile-friendly"),
    (r"ai\b|automat\w*|smart", "AI/automation"),
    (r"report\w*|insight\w*", "reporting"),
    (r"team\w*|collaborat\w*", "team collaboration"),
    (r"calori\w*|nutri\w*|macro\w*", "calorie/macro tracking"),
    (r"goa\w*", "goal setting"),
    (r"progress", "progress tracking"),
    (r"remind\w*", "reminders"),
    (r"integrat\w*", "third-party integrations"),
]

_ENDPOINT_TEMPLATES: dict[str, list[str]] = {
    "saas": ["/api/health", "/api/auth/signup", "/api/auth/login", "/api/user/profile",
             "/api/data", "/api/settings"],
    "tracker": ["/api/health", "/api/entries", "/api/entries/{id}", "/api/goals",
                "/api/reports/daily", "/api/reports/weekly"],
    "marketplace": ["/api/health", "/api/listings", "/api/listings/{id}",
                    "/api/users", "/api/search", "/api/transactions"],
    "tool": ["/api/health", "/api/process", "/api/results/{id}"],
    "default": ["/api/health", "/api/data", "/api/user"],
}

_STACK_KEYWORDS: dict[str, list[str]] = {
    "react": ["react", "nextjs", "next.js"],
    "python": ["python", "fastapi", "django", "flask"],
    "node": ["node", "express", "javascript", "typescript"],
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_intent(message: str) -> dict[str, Any]:
    """
    Parse a raw chat message into a structured ProductIntent.

    Returns a dict with:
      product_type, product_name, target_user, core_features,
      nonfunctional_reqs, desired_endpoints, tech_stack, raw_message,
      confidence (0.0-1.0)
    """
    msg = message.strip()
    msg_lower = msg.lower()

    product_type = _detect_type(msg_lower)
    product_name = _extract_product_name(msg, msg_lower)
    target_user = _detect_user(msg_lower)
    core_features = _extract_features(msg_lower)
    nonfunctional = _extract_nonfunctional(msg_lower)
    endpoints = _resolve_endpoints(msg_lower, product_type)
    tech_stack = _detect_stack(msg_lower)

    # confidence: higher if we found explicit signals
    confidence = min(
        0.4
        + (0.15 if product_name != _default_name(msg_lower) else 0.0)
        + (0.15 if core_features else 0.0)
        + (0.15 if target_user != "general users" else 0.0)
        + (0.15 if product_type != "saas" else 0.0),
        1.0,
    )

    return {
        "product_type": product_type,
        "product_name": product_name,
        "target_user": target_user,
        "core_features": core_features or ["core functionality", "user dashboard", "data export"],
        "nonfunctional_reqs": nonfunctional,
        "desired_endpoints": endpoints,
        "tech_stack": tech_stack,
        "raw_message": msg,
        "confidence": round(confidence, 2),
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _detect_type(msg: str) -> str:
    for ptype, keywords in _TYPE_KEYWORDS.items():
        if any(k in msg for k in keywords):
            return ptype
    return "saas"


def _extract_product_name(raw: str, msg: str) -> str:
    """Try to extract a product name from common patterns."""
    # Pattern: "build me a <name> saas/app/tool"
    m = re.search(
        r"(?:build|create|make|launch|start)\s+(?:me\s+)?(?:a|an)\s+([\w\s]+?)\s+"
        r"(?:saas|app|tool|platform|tracker|manager|dashboard|service|startup)",
        msg, re.IGNORECASE,
    )
    if m:
        name = m.group(1).strip().title()
        if 2 <= len(name.split()) <= 4:
            return name

    # Pattern: "<name> tracker/dashboard/app"
    m2 = re.search(
        r"([\w\s]+?)\s+(?:tracker|dashboard|app|platform|tool|manager)\b",
        msg, re.IGNORECASE,
    )
    if m2:
        candidate = m2.group(1).strip().title()
        if 1 <= len(candidate.split()) <= 3 and len(candidate) > 3:
            return f"{candidate} App"

    return _default_name(msg)


def _default_name(msg: str) -> str:
    """Fallback product name from first noun-like words."""
    words = [w.capitalize() for w in msg.split()
             if len(w) > 3 and w.isalpha() and w not in
             ("build", "make", "create", "want", "need", "with", "that", "this",
              "have", "will", "just", "like", "very", "really")]
    if words:
        return " ".join(words[:2]) + " App"
    return "My Startup App"


def _detect_user(msg: str) -> str:
    for user, keywords in _USER_KEYWORDS.items():
        if any(k in msg for k in keywords):
            return user
    return "general users"


def _extract_features(msg: str) -> list[str]:
    features = []
    for pattern, label in _FEATURE_KEYWORDS:
        if re.search(pattern, msg, re.IGNORECASE):
            if label not in features:
                features.append(label)
    return features[:8]


def _extract_nonfunctional(msg: str) -> list[str]:
    reqs = []
    if any(w in msg for w in ["fast", "speed", "performance", "quick"]):
        reqs.append("high performance (<200ms API response)")
    if any(w in msg for w in ["secure", "security", "private", "privacy"]):
        reqs.append("security & data privacy")
    if any(w in msg for w in ["mobile", "responsive", "phone"]):
        reqs.append("mobile-responsive design")
    if any(w in msg for w in ["simple", "easy", "clean", "minimal"]):
        reqs.append("clean minimal UX")
    if any(w in msg for w in ["scale", "scalable", "large", "enterprise"]):
        reqs.append("horizontal scalability")
    if not reqs:
        reqs = ["clean UX", "fast load time", "mobile-friendly"]
    return reqs


def _resolve_endpoints(msg: str, product_type: str) -> list[str]:
    if "track" in msg or "calori" in msg or "log" in msg:
        return _ENDPOINT_TEMPLATES["tracker"]
    if "marketplac" in msg or "listing" in msg:
        return _ENDPOINT_TEMPLATES["marketplace"]
    if product_type in _ENDPOINT_TEMPLATES:
        return _ENDPOINT_TEMPLATES[product_type]
    return _ENDPOINT_TEMPLATES["default"]


def _detect_stack(msg: str) -> str:
    for stack, keywords in _STACK_KEYWORDS.items():
        if any(k in msg for k in keywords):
            return stack
    return "html/css/js"  # default: pure HTML for max portability
