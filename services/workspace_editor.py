"""
Workspace editor — safely applies LLM-generated FileChange objects to disk.

Security model:
  - Paths must be under data/websites/<slug>/
  - Only allowlisted file extensions
  - No path traversal
  - Atomic write: .tmp → rename
  - Version backup before any overwrite (via file_persistence)
  - Validation per file type (HTML sanitized; all files size-checked)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Optional

from services.file_persistence import save_website_files

logger = logging.getLogger(__name__)

_ALLOWED_EXTENSIONS = {".html", ".css", ".js", ".jsx", ".ts", ".tsx", ".json", ".md", ".txt", ".svg", ".png", ".webp", ".jpg", ".jpeg"}
_BINARY_EXTENSIONS = {".png", ".webp", ".jpg", ".jpeg", ".gif"}
_ALLOWED_SUBPATHS = {"", "pages", "components", "assets", "data", "scripts", "styles", "src"}


@dataclass
class ChangeResult:
    path: str
    action: str
    status: str    # "applied" | "skipped" | "rejected"
    summary: str = ""
    error: str = ""
    version_id: str = ""


@dataclass
class ApplyResult:
    slug: str
    version_id: str
    applied: list[str] = field(default_factory=list)    # relative paths written
    skipped: list[str] = field(default_factory=list)    # relative paths not written
    results: list[ChangeResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def partition_changes_for_write(
    slug: str,
    changes: list,
) -> tuple[dict[str, str | bytes], list[ChangeResult]]:
    """Resolve FileChange list to a pending write map and one ChangeResult per input change.

    Stops before ``output_validator.validate_files`` — same gating logic as ``apply_changes``.
    """
    safe_slug = _safe_slug(slug)
    results: list[ChangeResult] = []
    files_to_write: dict[str, str | bytes] = {}

    for change in changes:
        path = (change.path or "").strip()
        action = (change.action or "create").lower()
        content = change.content or ""
        summary = change.summary or ""

        rel_path = _extract_relative_path(path, safe_slug)
        if rel_path is None:
            results.append(ChangeResult(
                path=path, action=action, status="rejected",
                error=f"path must be under data/websites/{safe_slug}/",
                summary=summary,
            ))
            continue

        err = _validate_path(rel_path)
        if err:
            results.append(ChangeResult(
                path=path, action=action, status="rejected", error=err, summary=summary,
            ))
            continue

        is_binary = isinstance(content, bytes)
        if is_binary:
            if len(content) == 0:
                results.append(ChangeResult(
                    path=path, action=action, status="skipped", error="empty content", summary=summary,
                ))
                continue
        else:
            if not content.strip():
                results.append(ChangeResult(
                    path=path, action=action, status="skipped", error="empty content", summary=summary,
                ))
                continue

        files_to_write[rel_path] = content
        results.append(ChangeResult(path=path, action=action, status="applied", summary=summary))

    return files_to_write, results


def apply_changes(
    slug: str,
    changes: list,  # list[FileChange] from code_generation_service
) -> ApplyResult:
    """Apply a list of FileChange objects to disk under data/websites/<slug>/.

    Returns ApplyResult describing what was written, skipped, or rejected.
    Content may be str (text files) or bytes (binary images).
    """
    safe_slug = _safe_slug(slug)
    files_to_write, results = partition_changes_for_write(slug, changes)

    if not files_to_write:
        return ApplyResult(slug=safe_slug, version_id="", results=results)

    # Validate all files through output_validator
    from services.output_validator import validate_files
    clean_files, val_warnings = validate_files(files_to_write)
    warnings: list[str] = list(val_warnings)

    # Mark any files that failed validation as rejected
    for rel_path in set(files_to_write.keys()) - set(clean_files.keys()):
        for r in results:
            if _extract_relative_path(r.path, safe_slug) == rel_path:
                r.status = "rejected"
                r.error = "validation failed"

    if not clean_files:
        return ApplyResult(slug=safe_slug, version_id="", results=results, warnings=warnings)

    # Persist (atomic write + version backup)
    save_result = save_website_files(safe_slug, clean_files)
    version_id = save_result.get("version_id", "")

    # Attach version_id to applied results
    for r in results:
        if r.status == "applied":
            r.version_id = version_id

    applied = [
        _extract_relative_path(r.path, safe_slug) or PurePosixPath(r.path).name
        for r in results if r.status == "applied"
    ]
    skipped = [
        _extract_relative_path(r.path, safe_slug) or PurePosixPath(r.path).name
        for r in results if r.status != "applied"
    ]

    return ApplyResult(
        slug=safe_slug,
        version_id=version_id,
        applied=applied,
        skipped=skipped,
        results=results,
        warnings=warnings,
    )


def _extract_relative_path(path: str, slug: str) -> Optional[str]:
    """Extract the relative path component under data/websites/<slug>/."""
    prefix = f"data/websites/{slug}/"
    generic_prefix = "data/websites/"
    if path.startswith(prefix):
        return path[len(prefix):]
    if path.startswith(generic_prefix):
        # Could be data/websites/other-slug/file.html — validate the slug matches
        rest = path[len(generic_prefix):]
        parts = rest.split("/", 1)
        if len(parts) == 2 and parts[0] == slug:
            return parts[1]
        return None
    # Bare filename with no path prefix — treat as relative to slug root
    if "/" not in path and path:
        return path
    return None


def _validate_path(rel_path: str) -> Optional[str]:
    """Return an error string if path is unsafe, else None."""
    if not rel_path:
        return "empty path"

    try:
        parts = PurePosixPath(rel_path).parts
    except Exception:
        return "invalid path"

    if ".." in parts:
        return "path traversal detected"

    ext = PurePosixPath(rel_path).suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        return f"extension {ext!r} not in allowlist"

    # Check subdirectory prefix
    if len(parts) > 1:
        subdir = parts[0]
        if subdir not in _ALLOWED_SUBPATHS:
            return f"subdirectory {subdir!r} not in allowlist"

    return None


def _safe_slug(slug: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", slug.lower()).strip("-") or "site"
