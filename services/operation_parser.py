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
}


def parse_operation(message: str) -> dict:
    """
    Detect operation type and extract relevant metadata.
    Returns {"type": str, "target": str, "metadata": dict}
    """
    msg_lower = message.lower()
    for op_type, patterns in OPERATION_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, msg_lower):
                return {
                    "type": op_type,
                    "target": _extract_target(msg_lower, op_type),
                    "metadata": _extract_metadata(msg_lower, op_type),
                }
    return {"type": "general_edit", "target": "", "metadata": {}}


def _extract_target(msg: str, op_type: str) -> str:
    if op_type == "add_page":
        m = re.search(r"\b(terms|privacy|about|pricing|contact|blog|faq|docs?|landing)\b", msg)
        return m.group(1) if m else "page"
    if op_type == "add_legal_page":
        m = re.search(r"\b(terms|privacy|cookie|gdpr)\b", msg)
        return m.group(1) if m else "legal"
    return ""


def _extract_metadata(msg: str, op_type: str) -> dict:
    if op_type == "add_endpoint":
        methods = [m for m in ["GET", "POST", "PUT", "DELETE", "PATCH"] if m.lower() in msg]
        return {"http_methods": methods or ["GET", "POST"]}
    return {}
