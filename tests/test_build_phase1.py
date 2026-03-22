"""Phase 1: build_project_state + build_validation + workspace partition helper."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_partition_changes_for_write_matches_apply_gating():
    """partition_changes_for_write must produce the same batch apply_changes validates first."""
    from services.code_generation_service import FileChange
    from services.workspace_editor import apply_changes, partition_changes_for_write

    slug = "test-slug"
    changes = [
        FileChange(
            path=f"data/websites/{slug}/index.html",
            action="create",
            content="<!DOCTYPE html><html><head><title>t</title></head><body></body></html>",
            summary="x",
        ),
        FileChange(path="bad/path.html", action="create", content="<html></html>", summary="bad"),
    ]
    batch, pre_results = partition_changes_for_write(slug, changes)
    assert "index.html" in batch
    assert len(pre_results) == 2
    assert pre_results[0].status == "applied"
    assert pre_results[1].status == "rejected"

    with patch("services.workspace_editor.save_website_files", return_value={"version_id": "v-test"}):
        result = apply_changes(slug, changes)
    assert any(r.path.endswith("index.html") and r.status == "applied" for r in result.results)


def test_pre_apply_orchestrate_records_output_warnings():
    from services.code_generation_service import FileChange
    from services.build_validation import pre_apply_orchestrate

    slug = "warn-slug"
    html = "<!DOCTYPE html><html><head><title>x</title></head><body></body></html>"
    changes = [
        FileChange(
            path=f"data/websites/{slug}/index.html",
            action="create",
            content=html,
            summary="",
        )
    ]
    res = pre_apply_orchestrate(slug, changes)
    assert res.ok is True
    assert "index.html" in res.raw.get("clean_paths", [])


def test_pre_apply_orchestrate_invalid_spec_warning():
    from services.code_generation_service import FileChange
    from services.build_validation import pre_apply_orchestrate

    slug = "spec-slug"
    changes = [
        FileChange(
            path=f"data/websites/{slug}/_spec.json",
            action="create",
            content="NOT VALID JSON {{{",
            summary="",
        )
    ]
    res = pre_apply_orchestrate(slug, changes)
    assert any(i.code == "invalid_site_spec" for i in res.spec_issues)


def test_load_build_project_state_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("CEOCLAW_DATABASE_PATH", str(tmp_path / "t.db"))
    import config.settings as cs

    cs.settings = cs.Settings()
    cs.settings.database_path = str(tmp_path / "t.db")
    from data.database import init_db

    init_db()

    from services.build_project_state import load_build_project_state

    state = load_build_project_state(
        session_id="sess-1",
        slug="my-app",
        message="build a thing",
        existing_files=None,
        history=[{"role": "user", "content": "hi"}],
        style_seed={"archetype": "saas"},
        design_system={"design_family": "framer_aura"},
        operation={"type": "general_edit"},
        intent={"product_name": "My App"},
        brand_spec=None,
        scaffold={"file_tree": []},
        is_edit=False,
        include_spec_snapshot=False,
        include_session_row=False,
    )
    assert state.slug == "my-app"
    assert state.is_edit is False
    assert state.to_log_dict()["intent_product"] == "My App"
    log = state.to_log_dict()
    assert log["history_turns"] == 1
    assert log["has_scaffold"] is True
