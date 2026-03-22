"""Build plan (Phase 2) construction and pipeline context."""

from __future__ import annotations

import sys
from pathlib import Path
from types import MappingProxyType
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    tmp_db = str(tmp_path / "plan_test.db")
    monkeypatch.setenv("CEOCLAW_DATABASE_PATH", tmp_db)
    import config.settings as cs

    cs.settings = cs.Settings()
    cs.settings.database_path = tmp_db
    from data.database import init_db

    init_db()


def test_build_plan_new_project_from_scaffold():
    from services.build_plan import build_plan_from_project_state
    from services.build_project_state import load_build_project_state

    scaffold = {
        "project_type": "static_site",
        "generation_order": ["styles/a.css", "index.html"],
        "file_tree": [
            {"path": "styles/a.css", "purpose": "tokens", "depends_on": []},
            {"path": "index.html", "purpose": "Landing", "depends_on": ["styles/a.css"]},
        ],
    }
    brand = type("B", (), {"brand_name": "Acme", "pages": ["index.html", "app.html"]})()

    state = load_build_project_state(
        session_id="s1",
        slug="acme",
        message="go",
        existing_files=None,
        history=[],
        style_seed=None,
        design_system=None,
        operation=None,
        intent={"product_name": "Acme"},
        brand_spec=brand,
        scaffold=scaffold,
        is_edit=False,
        include_spec_snapshot=False,
        include_session_row=False,
    )
    plan = build_plan_from_project_state(state)
    assert plan.constraints.session_mode == "new_project"
    assert plan.constraints.generation_flavor == "spec_first_preferred"
    assert plan.generation_tasks[0].intent == "spec_synthesize"
    create_paths = [t.path for t in plan.generation_tasks if t.intent == "create"]
    assert create_paths == ["styles/a.css", "index.html"]
    assert plan.generation_tasks[-1].depends_on == ("styles/a.css",)
    d = plan.to_dict()
    assert d["constraints"]["session_mode"] == "new_project"
    assert any("BrandSpec.pages" in n for n in d["notes"])


def test_build_plan_edit_marks_assets_unchanged():
    from services.build_plan import build_plan_from_project_state
    from services.build_project_state import load_build_project_state

    existing = {
        "index.html": "<html></html>",
        "assets/x.png": "binary",
        "styles/x.css": "body{}",
    }
    state = load_build_project_state(
        session_id="s2",
        slug="ed",
        message="tweak",
        existing_files=existing,
        history=[],
        style_seed=None,
        design_system=None,
        operation=MappingProxyType({"type": "general_edit"}),
        intent={"product_name": "Ed"},
        brand_spec=None,
        scaffold=None,
        is_edit=True,
        include_spec_snapshot=False,
        include_session_row=False,
    )
    plan = build_plan_from_project_state(state)
    assert plan.constraints.session_mode == "edit"
    assert "assets/x.png" in plan.unchanged_paths
    by_path = {i.path: i.intent for i in plan.file_intents}
    assert by_path["assets/x.png"] == "unchanged"
    assert by_path["index.html"] == "update"
    assert dict(plan.refs).get("operation_type") == "general_edit"


def test_build_plan_fallback():
    from services.build_plan import build_plan_fallback

    p = build_plan_fallback(slug="z", is_edit=True)
    assert p.constraints.session_mode == "edit"
    assert p.generation_tasks == ()


def test_run_pipeline_includes_build_plan_in_context(tmp_path, monkeypatch):
    import config.settings as cs

    cs.settings.resolve_websites_dir = MagicMock(return_value=tmp_path)

    from services.code_generation_service import BrandSpec, FileChange, GenerationResult

    bs = BrandSpec(
        brand_name="PlanCo",
        product_category="saas",
        target_audience="t",
        core_offer="o",
        pages=["index.html"],
    )
    scaffold = {
        "file_tree": [{"path": "index.html", "purpose": "L", "depends_on": []}],
        "generation_order": ["index.html"],
    }

    def fake_gen(**kw):
        return GenerationResult(
            assistant_message="ok",
            changes=[
                FileChange(
                    path="data/websites/plan-co/index.html",
                    action="create",
                    content="<!DOCTYPE html><html><head><title>t</title></head><body></body></html>",
                    summary="",
                )
            ],
            model_mode="openai",
        )

    events: list = []

    def emit_fn(ev: dict):
        events.append(ev)

    with patch("services.generation_pipeline._generate_image_assets", return_value={}), \
         patch("services.code_generation_service.generate_file_structure", return_value=scaffold), \
         patch("services.code_generation_service.synthesize_brand_spec", return_value=bs), \
         patch("services.code_generation_service.generate", side_effect=fake_gen), \
         patch("services.workspace_editor.apply_changes") as mock_apply, \
         patch("services.link_wiring.run_link_wiring_pass", return_value=([], [])), \
         patch("services.generation_pipeline._run_quality_check", return_value={"summary": "ok", "issues": []}):

        from services.workspace_editor import ApplyResult

        mock_apply.return_value = ApplyResult(
            slug="plan-co", version_id="v1", applied=["index.html"], skipped=[], results=[]
        )

        from services.generation_pipeline import run_pipeline

        ctx = run_pipeline(
            session_id="sess-plan",
            slug="plan-co",
            message="Build PlanCo",
            history=[],
            existing_files=None,
            style_seed=None,
            design_system=None,
            operation=None,
            emit=emit_fn,
            brand_spec=bs,
        )

    assert "build_plan" in ctx
    bp = ctx["build_plan"]
    assert isinstance(bp, dict)
    assert bp["constraints"]["session_mode"] == "new_project"
    assert any(t.get("intent") == "spec_synthesize" for t in bp["generation_tasks"])
    # Phase 3: generation_plan_context must also be populated
    assert "generation_plan_context" in ctx


# ---------------------------------------------------------------------------
# Phase 3: GenerationPlanContext tests
# ---------------------------------------------------------------------------


def test_build_generation_plan_context_from_dict():
    """Context parsed from a sample BuildPlan dict has correct fields."""
    from services.generation_plan_context import build_generation_plan_context

    plan_dict = {
        "constraints": {
            "session_mode": "new_project",
            "generation_flavor": "spec_first_preferred",
            "has_disk_spec": False,
        },
        "generation_tasks": [
            {"task_id": "spec-1", "path": "_spec.json", "intent": "spec_synthesize", "depends_on": [], "notes": ""},
            {"task_id": "create-1", "path": "styles/globals.css", "intent": "create", "depends_on": [], "notes": "tokens"},
            {"task_id": "create-2", "path": "index.html", "intent": "create", "depends_on": ["styles/globals.css"], "notes": "landing"},
            {"task_id": "create-3", "path": "app.html", "intent": "create", "depends_on": [], "notes": ""},
        ],
        "unchanged_paths": [],
        "notes": ["New project: generate() tries spec-first; legacy per-file order follows scaffold."],
        "refs": {},
    }

    ctx = build_generation_plan_context(plan_dict)
    assert ctx.session_mode == "new_project"
    assert ctx.generation_flavor == "spec_first_preferred"
    assert ctx.has_disk_spec is False
    # spec_synthesize must be excluded from ordered_create_targets
    assert "_spec.json" not in ctx.ordered_create_targets
    assert ctx.ordered_create_targets == ("styles/globals.css", "index.html", "app.html")
    assert ctx.edit_candidate_paths == ()
    assert "spec-first" in ctx.operation_summary


def test_build_generation_plan_context_edit_mode():
    """Edit-mode plan yields edit_candidate_paths, not ordered_create_targets."""
    from services.generation_plan_context import build_generation_plan_context

    plan_dict = {
        "constraints": {
            "session_mode": "edit",
            "generation_flavor": "edit_existing",
            "has_disk_spec": True,
        },
        "generation_tasks": [
            {"task_id": "edit-1", "path": "index.html", "intent": "edit_candidate", "depends_on": [], "notes": ""},
            {"task_id": "edit-2", "path": "styles/x.css", "intent": "edit_candidate", "depends_on": [], "notes": ""},
        ],
        "unchanged_paths": ["assets/hero.png"],
        "notes": ["Edit pipeline order."],
        "refs": {},
    }

    ctx = build_generation_plan_context(plan_dict)
    assert ctx.session_mode == "edit"
    assert ctx.ordered_create_targets == ()
    assert ctx.edit_candidate_paths == ("index.html", "styles/x.css")
    assert ctx.unchanged_paths == ("assets/hero.png",)
    d = ctx.log_dict()
    assert d["session_mode"] == "edit"
    assert "assets/hero.png" in d["unchanged_paths"]


def test_build_generation_plan_context_empty_dict():
    """Graceful handling of a minimal/fallback dict."""
    from services.generation_plan_context import build_generation_plan_context

    ctx = build_generation_plan_context({})
    assert ctx.session_mode == "new_project"
    assert ctx.ordered_create_targets == ()
    assert ctx.operation_summary == ""


def test_generate_legacy_uses_plan_ordering(monkeypatch):
    """Legacy per-file loop uses plan-ordered targets when plan_aware flag is on."""
    import config.settings as cs
    monkeypatch.setattr(cs.settings, "plan_aware_generation", True)

    from services.generation_plan_context import GenerationPlanContext
    from services.code_generation_service import BrandSpec, generate

    plan_ctx = GenerationPlanContext(
        session_mode="new_project",
        generation_flavor="legacy_per_file",
        has_disk_spec=False,
        ordered_create_targets=("custom.html",),
        edit_candidate_paths=(),
        unchanged_paths=(),
        operation_summary="test",
    )

    brand = BrandSpec(
        brand_name="Test",
        product_category="saas_b2c",
        target_audience="devs",
        core_offer="testing",
        pages=["index.html", "pages/signup.html", "app.html"],  # should be overridden
    )

    called_paths: list[str] = []

    from services.provider_router import LLMResult

    def fake_call_llm(messages, **kw):
        # Capture which page is being requested
        user_content = next((m["content"] for m in messages if m["role"] == "user"), "")
        for line in user_content.splitlines():
            if line.startswith("Generate the complete HTML file for:"):
                called_paths.append(line.split(":", 1)[1].strip())
        return LLMResult(
            content="<!DOCTYPE html><html><head><title>t</title></head><body></body></html>",
            provider="openai",
            model_mode="openai",
            fallback_used=False,
            fallback_reason="",
        )

    # Force spec pipeline to fail so we hit the legacy path
    def fake_spec_fail(*a, **kw):
        raise RuntimeError("forced spec failure")

    monkeypatch.setattr("services.code_generation_service.generate_via_spec", fake_spec_fail)
    monkeypatch.setattr("services.code_generation_service.call_llm", fake_call_llm)

    result = generate(
        slug="test-plan",
        user_message="build test",
        history=[],
        brand_spec=brand,
        generation_plan_context=plan_ctx,
    )

    # Only custom.html should have been generated — NOT brand_spec.pages
    assert called_paths == ["custom.html"]
    assert any("custom.html" in c.path for c in result.changes)
    assert not any("index.html" in c.path for c in result.changes)
    assert not any("signup.html" in c.path for c in result.changes)


def test_generate_legacy_falls_back_to_brand_spec_pages_when_no_plan_targets(monkeypatch):
    """When plan context has no create targets, brand_spec.pages is used (flag on)."""
    import config.settings as cs
    monkeypatch.setattr(cs.settings, "plan_aware_generation", True)

    from services.generation_plan_context import GenerationPlanContext
    from services.code_generation_service import BrandSpec, generate

    # Empty ordered_create_targets → should fall back to brand_spec.pages
    plan_ctx = GenerationPlanContext(
        session_mode="new_project",
        generation_flavor="unknown",
        has_disk_spec=False,
        ordered_create_targets=(),  # empty!
        edit_candidate_paths=(),
        unchanged_paths=(),
        operation_summary="",
    )

    brand = BrandSpec(
        brand_name="Fallback",
        product_category="saas_b2c",
        target_audience="devs",
        core_offer="testing",
        pages=["index.html"],
    )

    called_paths: list[str] = []

    from services.provider_router import LLMResult

    def fake_call_llm(messages, **kw):
        user_content = next((m["content"] for m in messages if m["role"] == "user"), "")
        for line in user_content.splitlines():
            if line.startswith("Generate the complete HTML file for:"):
                called_paths.append(line.split(":", 1)[1].strip())
        return LLMResult(
            content="<!DOCTYPE html><html><head><title>t</title></head><body></body></html>",
            provider="openai",
            model_mode="openai",
            fallback_used=False,
            fallback_reason="",
        )

    def fake_spec_fail(*a, **kw):
        raise RuntimeError("forced")

    monkeypatch.setattr("services.code_generation_service.generate_via_spec", fake_spec_fail)
    monkeypatch.setattr("services.code_generation_service.call_llm", fake_call_llm)

    generate(
        slug="fallback-test",
        user_message="build it",
        history=[],
        brand_spec=brand,
        generation_plan_context=plan_ctx,
    )

    # brand_spec.pages = ["index.html"] should be used
    assert called_paths == ["index.html"]


def test_generate_plan_aware_off_uses_brand_spec_pages(monkeypatch):
    """When plan_aware_generation=False, brand_spec.pages is always used regardless of plan."""
    import config.settings as cs
    monkeypatch.setattr(cs.settings, "plan_aware_generation", False)

    from services.generation_plan_context import GenerationPlanContext
    from services.code_generation_service import BrandSpec, generate

    plan_ctx = GenerationPlanContext(
        session_mode="new_project",
        generation_flavor="legacy_per_file",
        has_disk_spec=False,
        ordered_create_targets=("should-not-appear.html",),
        edit_candidate_paths=(),
        unchanged_paths=(),
        operation_summary="",
    )

    brand = BrandSpec(
        brand_name="FlagOff",
        product_category="saas_b2c",
        target_audience="devs",
        core_offer="testing",
        pages=["index.html"],
    )

    called_paths: list[str] = []

    from services.provider_router import LLMResult

    def fake_call_llm(messages, **kw):
        user_content = next((m["content"] for m in messages if m["role"] == "user"), "")
        for line in user_content.splitlines():
            if line.startswith("Generate the complete HTML file for:"):
                called_paths.append(line.split(":", 1)[1].strip())
        return LLMResult(
            content="<!DOCTYPE html><html><head><title>t</title></head><body></body></html>",
            provider="openai",
            model_mode="openai",
            fallback_used=False,
            fallback_reason="",
        )

    def fake_spec_fail(*a, **kw):
        raise RuntimeError("forced")

    monkeypatch.setattr("services.code_generation_service.generate_via_spec", fake_spec_fail)
    monkeypatch.setattr("services.code_generation_service.call_llm", fake_call_llm)

    # Pipeline didn't pass plan_ctx (flag=False means pipeline passes None)
    generate(
        slug="flag-off-test",
        user_message="build it",
        history=[],
        brand_spec=brand,
        generation_plan_context=None,  # flag off → pipeline passes None
    )

    assert "should-not-appear.html" not in called_paths
    assert called_paths == ["index.html"]
