"""
Startup idea generator for chat-first product selection.

Generates four structured product intents from a user's high-level request.
This stays deterministic and model-free to avoid extra API cost before the
run starts.
"""

from __future__ import annotations

from typing import Any

from core.intent_parser import parse_intent


_ANGLE_TEMPLATES: list[dict[str, Any]] = [
    {
        "suffix": "Lite",
        "positioning": "simple MVP for fast launch",
        "feature_prefix": "fast setup",
        "extra_endpoints": ["/api/onboarding/checklist"],
    },
    {
        "suffix": "Pro",
        "positioning": "power-user workflow with automation",
        "feature_prefix": "automation workflows",
        "extra_endpoints": ["/api/automation/rules", "/api/automation/runs"],
    },
    {
        "suffix": "Team",
        "positioning": "collaboration-first product for teams",
        "feature_prefix": "team collaboration",
        "extra_endpoints": ["/api/team/invite", "/api/team/roles"],
    },
    {
        "suffix": "AI",
        "positioning": "AI-assisted product with smart recommendations",
        "feature_prefix": "AI recommendations",
        "extra_endpoints": ["/api/insights/recommendations"],
    },
]


def generate_ideas(message: str, count: int = 4) -> list[dict[str, Any]]:
    """
    Generate structured startup ideas from a user message.

    Each returned idea is a valid product_intent-like dict that can be passed
    directly into the graph run as selected intent.
    """
    base = parse_intent(message or "build me a startup app")
    ideas: list[dict[str, Any]] = []

    for idx, template in enumerate(_ANGLE_TEMPLATES[: max(1, min(count, 4))], start=1):
        product_name = f"{base['product_name']} {template['suffix']}".strip()
        features = _merge_unique(
            [template["feature_prefix"]],
            base.get("core_features") or [],
        )[:8]
        endpoints = _merge_unique(
            base.get("desired_endpoints") or [],
            template["extra_endpoints"],
        )[:10]

        ideas.append({
            "idea_index": idx,
            "title": product_name,
            "positioning": template["positioning"],
            "product_type": base.get("product_type", "saas"),
            "product_name": product_name,
            "target_user": base.get("target_user", "general users"),
            "core_features": features,
            "nonfunctional_reqs": base.get("nonfunctional_reqs") or [],
            "desired_endpoints": endpoints,
            "tech_stack": base.get("tech_stack", "html/css/js"),
            "raw_message": message,
            "confidence": round(min((base.get("confidence", 0.5) + 0.05), 1.0), 2),
        })

    return ideas


def _merge_unique(primary: list[str], secondary: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for item in [*primary, *secondary]:
        norm = item.strip().lower()
        if not norm or norm in seen:
            continue
        seen.add(norm)
        merged.append(item)
    return merged

