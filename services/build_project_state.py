"""
Read-only builder project state for a single generation run.

Centralizes inputs that are otherwise threaded through the pipeline so planning
and future repair layers can consume one DTO. This module does not mutate disk
or the database.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Mapping

logger = logging.getLogger(__name__)


def _freeze_dict(d: dict[str, Any] | None) -> Mapping[str, Any] | None:
    if d is None:
        return None
    return MappingProxyType(dict(d))


def _copy_history(history: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    return tuple(dict(m) for m in history)


@dataclass(frozen=True)
class BuildProjectState:
    """Immutable snapshot of builder context for one pipeline run."""

    session_id: str
    slug: str
    message: str
    is_edit: bool
    intent: Mapping[str, Any]
    existing_files: Mapping[str, str] | None
    history: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    style_seed: Mapping[str, Any] | None = None
    design_system: Mapping[str, Any] | None = None
    operation: Mapping[str, Any] | None = None
    brand_spec: Any | None = None
    scaffold: Mapping[str, Any] | None = None
    spec_snapshot: Mapping[str, Any] | None = None
    session_metadata: Mapping[str, Any] | None = None

    def with_brand_and_scaffold(
        self,
        *,
        brand_spec: Any | None,
        scaffold: dict[str, Any] | None,
    ) -> BuildProjectState:
        """Return a copy with brand/scaffold filled (typically after those stages)."""
        return replace(self, brand_spec=brand_spec, scaffold=_freeze_dict(scaffold) if scaffold else None)

    def to_log_dict(self) -> dict[str, Any]:
        """JSON-friendly summary for logs or debug (no large file bodies)."""
        existing = self.existing_files
        existing_meta: dict[str, Any] | None = None
        if existing is not None:
            existing_meta = {
                "file_count": len(existing),
                "paths": sorted(existing.keys()),
            }
        brand = self.brand_spec
        brand_name = getattr(brand, "brand_name", None) if brand is not None else None
        return {
            "session_id": self.session_id,
            "slug": self.slug,
            "is_edit": self.is_edit,
            "intent_product": (self.intent or {}).get("product_name"),
            "existing": existing_meta,
            "history_turns": len(self.history),
            "has_design_system": self.design_system is not None,
            "has_style_seed": self.style_seed is not None,
            "operation_type": (self.operation or {}).get("type") if self.operation else None,
            "brand_name": brand_name,
            "has_scaffold": self.scaffold is not None,
            "has_spec_snapshot": self.spec_snapshot is not None,
            "session_version_id": (self.session_metadata or {}).get("version_id"),
        }


def _session_meta_subset(row: dict[str, Any] | None) -> Mapping[str, Any] | None:
    if not row:
        return None
    keys = (
        "session_id",
        "slug",
        "product_name",
        "version_id",
        "created_at",
        "updated_at",
        "owner_user_id",
    )
    slim = {k: row[k] for k in keys if k in row}
    return MappingProxyType(slim) if slim else None


def _spec_snapshot_for_slug(slug: str) -> Mapping[str, Any] | None:
    try:
        from services.site_spec import load_spec

        spec = load_spec(slug)
        if spec is None:
            return None
        raw = json.loads(spec.model_dump_json())
        return MappingProxyType(raw)
    except Exception as exc:
        logger.warning("build_project_state: spec snapshot skipped for slug=%r: %s", slug, exc)
        return None


def load_build_project_state(
    *,
    session_id: str,
    slug: str,
    message: str,
    existing_files: dict[str, str] | None,
    history: list[dict[str, Any]],
    style_seed: dict[str, Any] | None,
    design_system: dict[str, Any] | None,
    operation: dict[str, Any] | None,
    intent: dict[str, Any],
    brand_spec: Any | None,
    scaffold: dict[str, Any] | None,
    is_edit: bool,
    include_spec_snapshot: bool = True,
    include_session_row: bool = True,
) -> BuildProjectState:
    """Assemble the canonical read-only state after intent/brand/scaffold stages."""
    session_meta: Mapping[str, Any] | None = None
    if include_session_row:
        try:
            from data.database import get_chat_session

            session_meta = _session_meta_subset(get_chat_session(session_id))
        except Exception as exc:
            logger.warning("build_project_state: session metadata skipped: %s", exc)

    spec_snap: Mapping[str, Any] | None = None
    if include_spec_snapshot:
        spec_snap = _spec_snapshot_for_slug(slug)

    existing_proxy: Mapping[str, str] | None = None
    if existing_files is not None:
        existing_proxy = MappingProxyType(dict(existing_files))

    return BuildProjectState(
        session_id=session_id,
        slug=slug,
        message=message,
        is_edit=is_edit,
        intent=MappingProxyType(dict(intent)),
        existing_files=existing_proxy,
        history=_copy_history(history),
        style_seed=_freeze_dict(style_seed),
        design_system=_freeze_dict(design_system),
        operation=_freeze_dict(operation),
        brand_spec=brand_spec,
        scaffold=_freeze_dict(scaffold) if scaffold else None,
        spec_snapshot=spec_snap,
        session_metadata=session_meta,
    )
