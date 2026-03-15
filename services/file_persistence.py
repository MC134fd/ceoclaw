"""
File persistence manager for LLM-generated website files.

Writes to  data/websites/<slug>/
Backs up existing files to  data/websites/<slug>/versions/<timestamp>/
Keeps the last _MAX_VERSIONS backups per slug.

Supports a multi-file project tree — any file extension in _ALLOWED_EXTENSIONS
under an allowed subdirectory prefix is accepted.
"""

import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Optional

from config.settings import settings

logger = logging.getLogger(__name__)

_MAX_VERSIONS = 10

# Security allowlists
_ALLOWED_EXTENSIONS = {".html", ".css", ".js", ".json", ".md", ".txt", ".svg"}
_ALLOWED_SUBPATHS = {"", "pages", "components", "assets", "data", "scripts"}

# Max file size: 1 MB
_MAX_FILE_SIZE = 1_000_000

# Backward-compat: kept for any code that references it directly
_ALLOWED_FILENAMES = {"index.html", "app.html"}


def save_website_files(slug: str, files: dict[str, str]) -> dict:
    """Write files to disk under data/websites/<slug>/.

    files: {relative_path: content}  e.g. {"index.html": "...", "pages/terms.html": "..."}

    - Validates each path's extension and subdir against allowlists
    - Creates slug dir and any needed subdirs
    - Backs up ALL existing files (any extension) before writing
    - Atomic write via .tmp
    - Returns {"slug", "version_id", "paths": {rel_path: abs_path}, "backed_up": bool}
    """
    safe_slug = _safe_slug(slug)
    websites_dir = settings.resolve_websites_dir()
    page_dir = websites_dir / safe_slug
    page_dir.mkdir(parents=True, exist_ok=True)

    version_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backed_up = _backup_existing(page_dir, version_id)

    saved_paths: dict[str, str] = {}
    for rel_path, content in files.items():
        err = _validate_relative_path(rel_path)
        if err:
            logger.warning("file_persistence: skipping %r — %s", rel_path, err)
            continue
        if len(content.encode("utf-8")) > _MAX_FILE_SIZE:
            logger.warning("file_persistence: skipping %r — exceeds 1 MB size limit", rel_path)
            continue

        dest = page_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(dest)

        # relative to project root for logging/response
        try:
            rel = str(dest.relative_to(websites_dir.parent.parent))
        except ValueError:
            rel = str(dest)
        saved_paths[rel_path] = rel

    _prune_versions(page_dir)

    return {
        "slug": safe_slug,
        "version_id": version_id,
        "paths": saved_paths,
        "backed_up": backed_up,
    }


def read_current_file(slug: str, relative_path: str) -> Optional[str]:
    """Read any file from slug dir. Validates path safety."""
    safe_slug = _safe_slug(slug)
    err = _validate_relative_path(relative_path)
    if err:
        logger.warning("read_current_file: rejected path %r — %s", relative_path, err)
        return None
    path = settings.resolve_websites_dir() / safe_slug / relative_path
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def read_current_html(slug: str, filename: str = "index.html") -> Optional[str]:
    """Backward-compat alias for read_current_file."""
    return read_current_file(slug, filename)


def list_project_files(slug: str) -> list[str]:
    """Return all relative paths of files under slug dir (excluding versions/)."""
    safe_slug = _safe_slug(slug)
    page_dir = settings.resolve_websites_dir() / safe_slug
    if not page_dir.exists():
        return []
    result: list[str] = []
    versions_dir = page_dir / "versions"
    for f in page_dir.rglob("*"):
        if f.is_file() and not f.is_relative_to(versions_dir):
            try:
                result.append(str(f.relative_to(page_dir)))
            except ValueError:
                pass
    return sorted(result)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_relative_path(rel_path: str) -> Optional[str]:
    """Return error string if path is unsafe, else None."""
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
    # Check subdir prefix
    if len(parts) > 1:
        subdir = parts[0]
        if subdir not in _ALLOWED_SUBPATHS:
            return f"subdirectory {subdir!r} not in allowlist"
    return None


def _backup_existing(page_dir: Path, version_id: str) -> bool:
    """Back up all non-versions files under page_dir."""
    versions_dir = page_dir / "versions"
    existing = [
        f for f in page_dir.rglob("*")
        if f.is_file() and not f.is_relative_to(versions_dir)
    ]
    if not existing:
        return False
    backup_dir = versions_dir / version_id
    backup_dir.mkdir(parents=True, exist_ok=True)
    for src in existing:
        rel = src.relative_to(page_dir)
        dest = backup_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    return True


def _prune_versions(page_dir: Path) -> None:
    versions_dir = page_dir / "versions"
    if not versions_dir.exists():
        return
    dirs = sorted(
        [d for d in versions_dir.iterdir() if d.is_dir()],
        key=lambda d: d.name,
    )
    for old_dir in dirs[:-_MAX_VERSIONS]:
        shutil.rmtree(old_dir, ignore_errors=True)


def _safe_slug(slug: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", slug.lower()).strip("-") or "site"
