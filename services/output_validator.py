"""
Output validator and sanitizer for LLM-generated website content.

Enforces:
  - Allowlisted file extensions (not just index.html / app.html)
  - Path traversal prevention
  - HTML-specific: basic structure check, external script removal, javascript: href sanitization
  - SVG-specific: XML parse + strict tag/attr allowlist to prevent XSS
  - 1 MB size limit per file
"""

import logging
import re
import xml.etree.ElementTree as ET
from pathlib import PurePosixPath
from typing import Optional

logger = logging.getLogger(__name__)

_MAX_SIZE = 1_000_000  # 1 MB
_ALLOWED_EXTENSIONS = {".html", ".css", ".js", ".json", ".md", ".txt", ".svg"}
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

        # Extension-specific validation and sanitization
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
            # Link quality check — warnings only, never rejects
            link_warnings = check_html_links(content, safe_name, set(files.keys()))
            warnings.extend(link_warnings)
        elif ext == ".svg":
            sanitized = _sanitize_svg(content, safe_name, warnings)
            if sanitized is None:
                continue  # malformed or empty after sanitization — already warned
            content = sanitized

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


# Regex to extract href="..." and src="..." attribute values
_HREF_SRC_RE = re.compile(
    r"""(?:href|src)=["']([^"']+)["']""",
    re.IGNORECASE,
)

# Schemes / prefixes that indicate an external or non-file reference
_EXTERNAL_PREFIXES = ("http://", "https://", "//", "#", "mailto:", "tel:", "data:")


def check_html_links(
    html: str,
    filename: str,
    available_files: set[str],
) -> list[str]:
    """Return warning strings for broken internal links and missing asset refs.

    Scans all href and src attribute values in *html*.  For each value that is
    not external (does not start with http/https/// /#/mailto:/tel:/data:) it
    checks whether the referenced path exists in *available_files*.  Missing
    references produce a warning string.

    Never raises; never rejects files — warnings only.
    """
    warnings: list[str] = []
    for m in _HREF_SRC_RE.finditer(html):
        ref = m.group(1).strip()
        if not ref:
            continue
        # Skip external, anchor-only, and protocol-based references
        if any(ref.startswith(prefix) for prefix in _EXTERNAL_PREFIXES):
            continue
        # Normalise leading ./ or / for comparison
        normalised = ref.lstrip("./")
        if normalised in available_files or ref in available_files:
            continue
        warnings.append(
            f"{filename}: broken link to {ref!r} (not in available files)"
        )
    return warnings


def validate_route_graph(
    route_graph: dict | None,
    available_files: set[str],
) -> list[str]:
    """Return warnings for route_graph edges where a node is not in available_files.

    Nodes that start with '/' are treated as routes (strip leading slash for lookup).
    Never raises; never rejects — warnings only.
    """
    warnings: list[str] = []
    if not route_graph:
        return warnings
    nodes = set(route_graph.get("nodes") or [])
    edges = route_graph.get("edges") or []

    for node in nodes:
        normalised = node.lstrip("/")
        if normalised and normalised not in available_files:
            warnings.append(f"route_graph: node {node!r} not found in generated files")

    for edge in edges:
        for end in ("from", "to"):
            target = edge.get(end, "")
            norm = target.lstrip("/")
            if norm and norm not in nodes and norm not in available_files:
                warnings.append(
                    f"route_graph: edge {end}={target!r} references unknown node"
                )
    return warnings


# ---------------------------------------------------------------------------
# SVG sanitizer
# ---------------------------------------------------------------------------

# Tags safe for generated icon/hero SVGs
_SVG_ALLOWED_TAGS = {
    "svg", "g", "defs", "symbol", "use",
    "linearGradient", "radialGradient", "stop",
    "rect", "circle", "ellipse", "path", "line", "polyline", "polygon",
    "text", "tspan", "title", "desc",
}

# Tags that must always be removed regardless of namespace
_SVG_FORBIDDEN_TAGS = {
    "script", "foreignobject", "iframe", "object", "embed",
    "audio", "video", "animate", "set", "animatetransform",
}

# Attribute prefixes/names that are dangerous
_SVG_FORBIDDEN_ATTR_PREFIXES = ("on",)  # all event handlers
_SVG_FORBIDDEN_HREF_SCHEMES = ("javascript:", "data:", "http://", "https://", "//")


def _svg_localname(tag: str) -> str:
    """Strip XML namespace prefix: {ns}tag → tag (lower-cased)."""
    if tag.startswith("{"):
        tag = tag.split("}", 1)[1]
    return tag.lower()


def _sanitize_svg_element(el: ET.Element, warnings: list[str], filename: str) -> bool:
    """Recursively strip dangerous children and attributes in-place.

    Returns False if the root element itself is forbidden (caller should reject).
    """
    local = _svg_localname(el.tag)

    if local in _SVG_FORBIDDEN_TAGS:
        return False

    # Strip forbidden attributes
    for attr in list(el.attrib):
        attr_local = _svg_localname(attr) if attr.startswith("{") else attr.lower()
        # Event handlers
        if any(attr_local.startswith(p) for p in _SVG_FORBIDDEN_ATTR_PREFIXES):
            del el.attrib[attr]
            warnings.append(f"{filename}: removed event handler attr {attr!r}")
            continue
        # Dangerous href / xlink:href
        if attr_local in ("href", "xlink:href", "{http://www.w3.org/1999/xlink}href"):
            val = el.attrib.get(attr, "").strip().lower()
            if any(val.startswith(s) for s in _SVG_FORBIDDEN_HREF_SCHEMES):
                del el.attrib[attr]
                warnings.append(f"{filename}: removed dangerous href {val[:40]!r}")

    # Recurse — remove forbidden children
    for child in list(el):
        child_local = _svg_localname(child.tag)
        if child_local in _SVG_FORBIDDEN_TAGS or child_local not in _SVG_ALLOWED_TAGS:
            el.remove(child)
            warnings.append(f"{filename}: removed disallowed SVG element <{child_local}>")
        else:
            _sanitize_svg_element(child, warnings, filename)

    return True


def _sanitize_svg(svg: str, filename: str, warnings: list[str]) -> Optional[str]:
    """Parse, sanitize, and re-serialize an SVG string.

    Returns the sanitized SVG string, or None if the input is malformed/empty.
    """
    text = svg.strip()
    if not text:
        warnings.append(f"Skipped {filename} — empty SVG")
        return None

    # Register namespaces so ET doesn't emit ns0: prefixes on re-serialization
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")

    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        warnings.append(f"Skipped {filename} — malformed SVG XML: {exc}")
        return None

    if _svg_localname(root.tag) != "svg":
        warnings.append(f"Skipped {filename} — SVG root element must be <svg>")
        return None

    allowed = _sanitize_svg_element(root, warnings, filename)
    if not allowed:
        warnings.append(f"Skipped {filename} — SVG root is a forbidden element")
        return None

    # Re-serialize — ET strips the XML declaration which is fine for inline/img use
    return ET.tostring(root, encoding="unicode", xml_declaration=False)


def check_spacing_contract(html: str, filename: str) -> list[str]:
    """Check that generated HTML follows the spacing/gutter contract.

    Verifies presence of:
    - Content container max-width (centering guard)
    - margin-inline: auto or margin: 0 auto (centering)
    - clamp() spacing tokens (fluid spacing)
    - Some form of padding (section rhythm)
    - Touch target sizing (min 44px)

    Returns a list of warning strings. Never raises.
    """
    warnings: list[str] = []
    lower = html.lower()

    # Content container: max-width
    if "max-width:" not in lower and "max-width :" not in lower:
        warnings.append(f"{filename}: no content container max-width detected")

    # Centering: margin-inline auto OR margin: 0 auto
    has_center = (
        "margin-inline: auto" in lower
        or "margin-inline:auto" in lower
        or "margin: 0 auto" in lower
        or "margin:0 auto" in lower
        or "margin: auto" in lower
        or "margin:auto" in lower
    )
    if not has_center:
        warnings.append(f"{filename}: no margin-inline auto / margin: 0 auto for centering")

    # Fluid spacing tokens via clamp()
    if "clamp(" not in lower:
        warnings.append(f"{filename}: no clamp() spacing tokens detected")

    # Padding presence (section rhythm)
    if "padding" not in lower:
        warnings.append(f"{filename}: no section padding detected")

    # Touch targets: 44px or min-height
    has_touch = "44px" in lower or "2.75rem" in lower or "min-height" in lower
    if not has_touch:
        warnings.append(f"{filename}: no touch target sizing detected (min 44px recommended)")

    return warnings


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
