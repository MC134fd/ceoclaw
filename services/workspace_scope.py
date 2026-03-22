"""
WorkspaceScope — safe file access boundary for a session/project workspace.

Design principles:
  - All file operations scoped to data/websites/<slug>/
  - Path traversal prevention via realpath comparison
  - Extension allowlist enforced on every write
  - Read/write/list operations with audit trail
  - Future autonomous agents MUST use WorkspaceScope; direct filesystem
    access outside the boundary is prohibited.

Lifecycle example:
    scope = WorkspaceScope(slug="my-app")
    if scope.is_permitted("pages/about.html"):
        scope.write("pages/about.html", content)
    scope.list_files()   # -> ["index.html", "app.html", "pages/about.html"]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ALLOWED_EXTENSIONS: frozenset[str] = frozenset({
    ".html", ".css", ".js", ".json", ".md", ".txt", ".svg",
})

_ALLOWED_SUBDIRS: frozenset[str] = frozenset({
    "",          # root of slug dir (index.html, app.html)
    "pages",     # additional HTML pages
    "assets",    # static assets (SVG, etc.)
})

_MAX_FILE_SIZE_BYTES: int = 2 * 1024 * 1024   # 2 MB safety cap


# ---------------------------------------------------------------------------
# Audit trace
# ---------------------------------------------------------------------------

@dataclass
class ScopeOperation:
    """A single file-access operation recorded in the scope audit log."""
    kind: str           # "read" | "write" | "list" | "check"
    path: str           # relative path within the slug directory
    permitted: bool
    reason: str = ""    # why it was blocked (empty if permitted)
    bytes_written: int = 0


# ---------------------------------------------------------------------------
# WorkspaceScope
# ---------------------------------------------------------------------------

@dataclass
class WorkspaceScope:
    """
    Enforces the workspace boundary for all file operations in a project slug.

    Extension points for future agents:
      - override `_base_dir` to support remote / cloud-backed workspaces
      - override `_is_extension_allowed` for project-specific extension rules
      - subscribe to `operations` list for post-hoc audit / tracing
    """
    slug: str
    _base_dir: Optional[Path] = field(default=None, repr=False)
    operations: list[ScopeOperation] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if self._base_dir is None:
            from config.settings import settings
            self._base_dir = settings.resolve_websites_dir() / self.slug
        # Ensure the workspace directory exists
        self._base_dir.mkdir(parents=True, exist_ok=True)

    # ── Public API ──────────────────────────────────────────────────────────

    def resolve(self, relative_path: str) -> Optional[Path]:
        """
        Return the safe absolute Path for a relative workspace path.
        Returns None if the path would escape the workspace boundary.
        """
        op = self._check(relative_path)
        if not op.permitted:
            logger.warning("[WorkspaceScope] Blocked path %r: %s", relative_path, op.reason)
            return None
        return self._base_dir / relative_path

    def is_permitted(self, relative_path: str) -> bool:
        """Return True if the path is within the workspace boundary and has an allowed extension."""
        return self._check(relative_path).permitted

    def read(self, relative_path: str) -> Optional[str]:
        """Read a workspace file. Returns None if not found or path not permitted."""
        safe_path = self.resolve(relative_path)
        if safe_path is None:
            return None
        op = ScopeOperation(kind="read", path=relative_path, permitted=True)
        self.operations.append(op)
        try:
            return safe_path.read_text(encoding="utf-8")
        except (FileNotFoundError, UnicodeDecodeError):
            return None

    def write(self, relative_path: str, content: str) -> bool:
        """
        Write content to a workspace file atomically (.tmp → rename).
        Returns True on success, False if blocked or failed.
        """
        safe_path = self.resolve(relative_path)
        if safe_path is None:
            return False

        encoded = content.encode("utf-8")
        if len(encoded) > _MAX_FILE_SIZE_BYTES:
            op = ScopeOperation(
                kind="write", path=relative_path, permitted=False,
                reason=f"file too large ({len(encoded)} bytes > {_MAX_FILE_SIZE_BYTES})",
            )
            self.operations.append(op)
            logger.warning("[WorkspaceScope] Write blocked for %r: %s", relative_path, op.reason)
            return False

        safe_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = safe_path.with_suffix(safe_path.suffix + ".tmp")
        try:
            tmp.write_bytes(encoded)
            tmp.replace(safe_path)
            op = ScopeOperation(
                kind="write", path=relative_path, permitted=True,
                bytes_written=len(encoded),
            )
            self.operations.append(op)
            return True
        except OSError as exc:
            logger.error("[WorkspaceScope] Write failed for %r: %s", relative_path, exc)
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            return False

    def list_files(self, extension: Optional[str] = None) -> list[str]:
        """
        List all permitted files in the workspace, relative to slug root.
        Optionally filter by extension (e.g. ".html").
        """
        op = ScopeOperation(kind="list", path=".", permitted=True)
        self.operations.append(op)
        result: list[str] = []
        if not self._base_dir.exists():
            return result
        for p in sorted(self._base_dir.rglob("*")):
            if not p.is_file():
                continue
            if extension and p.suffix != extension:
                continue
            rel = str(p.relative_to(self._base_dir))
            if self.is_permitted(rel):
                result.append(rel)
        return result

    def audit_log(self) -> list[dict]:
        """Return the audit log as a list of dicts for serialisation."""
        return [
            {
                "kind": op.kind,
                "path": op.path,
                "permitted": op.permitted,
                "reason": op.reason,
                "bytes_written": op.bytes_written,
            }
            for op in self.operations
        ]

    # ── Internal ────────────────────────────────────────────────────────────

    def _check(self, relative_path: str) -> ScopeOperation:
        """Validate a relative path against workspace boundary rules."""
        # Extension check
        p = Path(relative_path)
        if p.suffix.lower() not in _ALLOWED_EXTENSIONS:
            return ScopeOperation(
                kind="check", path=relative_path, permitted=False,
                reason=f"extension {p.suffix!r} not in allowlist",
            )

        # Subdirectory check
        parts = p.parts
        subdir = str(parts[0]) if len(parts) > 1 else ""
        if subdir not in _ALLOWED_SUBDIRS:
            return ScopeOperation(
                kind="check", path=relative_path, permitted=False,
                reason=f"subdirectory {subdir!r} not in allowlist",
            )

        # Realpath traversal check
        try:
            candidate = (self._base_dir / relative_path).resolve()
            base_resolved = self._base_dir.resolve()
            candidate.relative_to(base_resolved)   # raises ValueError if outside
        except (ValueError, OSError):
            return ScopeOperation(
                kind="check", path=relative_path, permitted=False,
                reason="path traversal detected",
            )

        return ScopeOperation(kind="check", path=relative_path, permitted=True)
