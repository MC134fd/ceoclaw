"""
Output validator and sanitizer for LLM-generated website content.

Enforces:
  - Allowlisted file extensions (not just index.html / app.html)
  - Path traversal prevention
  - HTML-specific: basic structure check, external script removal, javascript: href sanitization
  - 1 MB size limit per file
"""

import logging
import re
from pathlib import PurePosixPath
from typing import Optional

logger = logging.getLogger(__name__)

_MAX_SIZE = 1_000_000  # 1 MB
_ALLOWED_EXTENSIONS = {".html", ".css", ".js", ".json", ".md", ".txt"}
_ALLOWED_SUBPATHS = {"", "pages", "components", "assets", "data", "scripts"}

# Remove <script src="https?://...">...</script>  (external scripts)
_EXTERNAL_SCRIPT_RE = re.compile(
    r'<script[^>]+src=["\']https?://[^"\']+["\'][^>]*>.*?</script>',
    re.IGNORECASE | re.DOTALL,
)
# Replace javascript: href with #
_JS_HREF_RE = re.compile(r'href=["\']javascript:[^"\']*["\']', re.IGNORECASE)
_VIEWPORT_RE = re.compile(
    r'<meta[^>]+name=["\']viewport["\'][^>]*>',
    re.IGNORECASE,
)
_MEDIA_BREAKPOINT_RE = re.compile(
    r"@media\s*\(\s*max-width\s*:\s*(\d+)px\s*\)",
    re.IGNORECASE,
)


def validate_files(files: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """Validate and sanitize a files dict from LLM output.

    Accepts {relative_path: content} for any allowlisted extension.
    HTML files: run sanitization (remove external scripts, sanitize js: hrefs).
    All files: enforce size limit.
    Returns (clean_files, warnings).
    """
    warnings: list[str] = []
    clean: dict[str, str] = {}

    for raw_path, content in (files or {}).items():
        # Path safety check
        path_err = _validate_path(raw_path)
        if path_err:
            warnings.append(f"Skipped {raw_path!r}: {path_err}")
            continue

        # Use the safe name (last component) for display
        safe_name = PurePosixPath(raw_path).name
        ext = PurePosixPath(raw_path).suffix.lower()

        if not isinstance(content, str) or not content.strip():
            warnings.append(f"Skipped empty content for {safe_name}")
            continue

        if len(content.encode("utf-8")) > _MAX_SIZE:
            warnings.append(f"Truncated {safe_name} — exceeded 1 MB limit")
            content = content[:_MAX_SIZE]

        # HTML-specific validation and sanitization
        if ext == ".html":
            if not _looks_like_html(content):
                warnings.append(f"Skipped {safe_name} — content does not look like HTML")
                continue
            html_warnings, critical_violation = _responsive_html_warnings(content, safe_name)
            warnings.extend(html_warnings)
            if critical_violation:
                warnings.append(
                    f"Skipped {safe_name} — missing critical responsive contract (viewport + breakpoints)"
                )
                continue
            content = _sanitize_html(content, safe_name, warnings)

        clean[raw_path] = content

    return clean, warnings


def _validate_path(relative_path: str) -> Optional[str]:
    """Return error string if path is unsafe, else None.
    Checks: no .., only allowlisted extensions, only allowlisted subdir prefixes.
    """
    if not relative_path:
        return "empty path"
    try:
        parts = PurePosixPath(relative_path).parts
    except Exception:
        return "invalid path"

    if ".." in parts:
        return "path traversal detected"

    ext = PurePosixPath(relative_path).suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        return f"extension {ext!r} not in allowlist"

    # Check subdir prefix (only first path component)
    if len(parts) > 1:
        subdir = parts[0]
        if subdir not in _ALLOWED_SUBPATHS:
            return f"subdirectory {subdir!r} not in allowlist"

    return None


def _looks_like_html(content: str) -> bool:
    head = content.strip().lower()[:300]
    return "<!doctype" in head or "<html" in head


def _sanitize_html(html: str, filename: str, warnings: list[str]) -> str:
    cleaned, n = _EXTERNAL_SCRIPT_RE.subn("", html)
    if n:
        warnings.append(f"{filename}: removed {n} external <script> tag(s)")

    cleaned, n = _JS_HREF_RE.subn('href="#"', cleaned)
    if n:
        warnings.append(f"{filename}: sanitized {n} javascript: href(s)")

    return cleaned


def _responsive_html_warnings(html: str, filename: str) -> tuple[list[str], bool]:
    """Responsive quality checks; return (warnings, critical_violation)."""
    warnings: list[str] = []
    lower = html.lower()

    has_viewport = bool(_VIEWPORT_RE.search(html))
    breakpoints = [int(match) for match in _MEDIA_BREAKPOINT_RE.findall(html)]
    has_1024 = any(px <= 1024 for px in breakpoints)
    has_640 = any(px <= 640 for px in breakpoints)
    has_fluid = "clamp(" in lower or "minmax(" in lower or "vw" in lower
    has_anti_squish = (
        "flex-wrap" in lower
        or "minmax(" in lower
        or "overflow-wrap" in lower
        or "word-break" in lower
    )
    has_media_safe = "max-width: 100%" in lower

    if not has_viewport:
        warnings.append(
            f"{filename}: missing viewport meta tag for mobile layout."
        )
    if not breakpoints:
        warnings.append(
            f"{filename}: missing responsive @media breakpoints."
        )
    else:
        if not has_1024:
            warnings.append(
                f"{filename}: missing tablet breakpoint around 1024px."
            )
        if not has_640:
            warnings.append(
                f"{filename}: missing mobile breakpoint around 640px."
            )

    if not has_fluid:
        warnings.append(
            f"{filename}: no fluid sizing tokens detected (clamp/minmax/vw)."
        )
    if not has_anti_squish:
        warnings.append(
            f"{filename}: no anti-squish rules detected (flex-wrap/minmax/overflow-wrap/word-break)."
        )
    if not has_media_safe:
        warnings.append(
            f"{filename}: expected max-width: 100% guard for media/content."
        )

    # Reject only substantial page outputs; keep lightweight snippets permissive.
    critical_violation = not has_viewport and not breakpoints and len(html) > 1200
    return warnings, critical_violation
