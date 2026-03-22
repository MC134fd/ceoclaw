"""
End-to-end tests for the website generation pipeline flow.

The user-described flow is:
  1. User sends app idea (text)
  2. AI parses intent → extracts product name, type, features
  3. AI synthesizes brand spec → colors, design direction, tone
  4. AI generates file structure → JSON tree of files with purposes
  5. AI generates files one-by-one in dependency order, emitting progress per file
  6. Files are saved to disk + DB
  7. Navigation links are wired across pages
  8. Quality check validates the output
  9. Complete — user sees the result

These tests mock only the LLM calls (call_llm) and image generation,
verifying the real pipeline orchestration, event emission, and data flow.
"""

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    """Spin up a fresh SQLite DB for every test."""
    tmp_db = str(tmp_path / "flow_test.db")
    monkeypatch.setenv("CEOCLAW_DATABASE_PATH", tmp_db)
    import config.settings as cs
    cs.settings = cs.Settings()
    cs.settings.database_path = tmp_db
    from data.database import init_db
    init_db()


@pytest.fixture()
def emit_log():
    """Collect all events emitted by the pipeline."""
    events: list[dict[str, Any]] = []
    return events


@pytest.fixture()
def emit_fn(emit_log):
    def _emit(event: dict[str, Any]):
        emit_log.append(event)
    return _emit


@pytest.fixture()
def websites_dir(tmp_path):
    return tmp_path / "websites"


@pytest.fixture()
def mock_llm_for_brand():
    """Returns an LLM mock that produces valid BrandSpec JSON."""
    def _make_result(content: str):
        from services.provider_router import LLMResult
        return LLMResult(content=content, provider="openai", model_mode="openai")
    return _make_result


def _passthrough_wiring(slug, changes, operation):
    """Mock for run_link_wiring_pass that passes changes through unmodified."""
    return (changes, [])


# ===========================================================================
# 1. PIPELINE STAGE DEFINITIONS
# ===========================================================================


class TestPipelineStageDefinitions:
    """The pipeline must declare exactly the stages the user expects."""

    def test_stage_keys_match_expected_flow(self):
        from services.generation_pipeline import STAGE_DEFS
        keys = [k for k, _ in STAGE_DEFS]
        expected = [
            "parse_intent",
            "brand_design",
            "file_structure",
            "generate_assets",
            "generate_files",
            "apply_files",
            "wire_navigation",
            "quality_check",
            "complete",
        ]
        assert keys == expected

    def test_stage_count_is_nine(self):
        from services.generation_pipeline import STAGE_DEFS
        assert len(STAGE_DEFS) == 9

    def test_every_stage_has_a_human_label(self):
        from services.generation_pipeline import STAGE_DEFS
        for key, label in STAGE_DEFS:
            assert label, f"Stage {key!r} has empty label"
            assert len(label) > 3


# ===========================================================================
# 2. INTENT PARSING (stage 1)
# ===========================================================================


class TestIntentParsingStage:
    """parse_intent extracts structured data from a raw user message."""

    def test_extracts_product_name_from_idea(self):
        from core.intent_parser import parse_intent
        result = parse_intent("Build me a calorie tracker for fitness enthusiasts")
        assert result["product_name"]
        assert result["product_name"] != "My Startup App"

    def test_extracts_core_features(self):
        from core.intent_parser import parse_intent
        result = parse_intent("Build a project management tool with kanban boards and time tracking")
        features_str = " ".join(result["core_features"]).lower()
        assert "kanban" in features_str or "project" in features_str or "tracking" in features_str

    def test_extracts_target_user(self):
        from core.intent_parser import parse_intent
        result = parse_intent("Build a recipe app for home cooks")
        assert result["target_user"]
        assert len(result["target_user"]) > 0

    def test_returns_confidence_score(self):
        from core.intent_parser import parse_intent
        specific = parse_intent("Build me a calorie tracker SaaS for fitness enthusiasts with tracking and analytics")
        vague = parse_intent("build something")
        assert specific["confidence"] > vague["confidence"]

    def test_vague_message_triggers_clarification(self):
        from services.generation_pipeline import check_clarification_needed
        result = check_clarification_needed("help me", [], None)
        assert result is not None
        assert result["needs_clarification"] is True
        assert len(result["questions"]) >= 2

    def test_specific_message_skips_clarification(self):
        from services.generation_pipeline import check_clarification_needed
        result = check_clarification_needed(
            "Build me a calorie tracking app for fitness enthusiasts", [], None
        )
        assert result is None


# ===========================================================================
# 3. BRAND & DESIGN SYNTHESIS (stage 2)
# ===========================================================================


class TestBrandDesignStage:
    """synthesize_brand_spec produces a structured brand identity."""

    def test_brand_spec_has_required_fields(self):
        from services.code_generation_service import BrandSpec
        bs = BrandSpec(
            brand_name="FitTrack",
            product_category="fitness",
            target_audience="gym goers",
            core_offer="Track calories and macros",
            must_include_keywords=["calorie", "macros"],
            primary_cta="Start Tracking",
            pages=["index.html"],
        )
        assert bs.brand_name == "FitTrack"
        assert bs.primary_cta == "Start Tracking"
        assert "calorie" in bs.must_include_keywords

    def test_brand_spec_round_trips_through_dict(self):
        from services.code_generation_service import BrandSpec
        bs = BrandSpec(
            brand_name="PawWalk",
            product_category="pets",
            target_audience="dog owners",
            core_offer="Dog walking on demand",
            must_include_keywords=["walk", "dog"],
            primary_cta="Book a Walk",
            pages=["index.html", "pages/signup.html"],
            layout_profile="split_hero",
            visual_motif="gradient_rich",
            copy_style="warm_conversational",
        )
        d = bs.to_dict()
        bs2 = BrandSpec.from_dict(d)
        assert bs2.brand_name == "PawWalk"
        assert bs2.pages == ["index.html", "pages/signup.html"]
        assert bs2.layout_profile == "split_hero"

    def test_brand_spec_to_dict_contains_all_key_fields(self):
        from services.code_generation_service import BrandSpec
        bs = BrandSpec(
            brand_name="GlossKit",
            product_category="beauty",
            target_audience="makeup lovers",
            core_offer="Find lipsticks",
            must_include_keywords=["pigment"],
            primary_cta="Shop Now",
        )
        d = bs.to_dict()
        assert d["brand_name"] == "GlossKit"
        assert d["product_category"] == "beauty"
        assert d["primary_cta"] == "Shop Now"
        assert "pigment" in d["must_include_keywords"]


# ===========================================================================
# 4. FILE STRUCTURE GENERATION (stage 3)
# ===========================================================================


class TestFileStructureStage:
    """generate_file_structure returns a scaffold with file tree + order."""

    def test_scaffold_has_required_keys(self):
        from services.code_generation_service import BrandSpec
        bs = BrandSpec(
            brand_name="TestApp",
            product_category="saas",
            target_audience="developers",
            core_offer="Code review automation",
        )

        def fake_call_llm(msgs, **kw):
            from services.provider_router import LLMResult
            scaffold = {
                "project_type": "static_site",
                "file_tree": [
                    {"path": "styles/globals.css", "purpose": "Design tokens", "depends_on": []},
                    {"path": "index.html", "purpose": "Landing page", "depends_on": ["styles/globals.css"]},
                    {"path": "app.html", "purpose": "App dashboard", "depends_on": ["styles/globals.css"]},
                ],
                "generation_order": ["styles/globals.css", "index.html", "app.html"],
                "design_notes": "Dark theme, developer-focused",
            }
            return LLMResult(content=json.dumps(scaffold), provider="openai", model_mode="openai")

        with patch("services.code_generation_service.call_llm", side_effect=fake_call_llm):
            from services.code_generation_service import generate_file_structure
            scaffold = generate_file_structure(bs, "Build me a code review tool", None)

        assert "file_tree" in scaffold
        assert "generation_order" in scaffold
        assert len(scaffold["file_tree"]) >= 1
        assert len(scaffold["generation_order"]) >= 1

    def test_generation_order_respects_dependencies(self):
        """CSS/shared files must appear before HTML files that depend on them."""
        from services.code_generation_service import BrandSpec

        bs = BrandSpec(brand_name="T", product_category="saas", target_audience="x", core_offer="y")

        def fake_call_llm(msgs, **kw):
            from services.provider_router import LLMResult
            scaffold = {
                "project_type": "static_site",
                "file_tree": [
                    {"path": "styles/globals.css", "purpose": "tokens", "depends_on": []},
                    {"path": "index.html", "purpose": "Landing", "depends_on": ["styles/globals.css"]},
                ],
                "generation_order": ["styles/globals.css", "index.html"],
            }
            return LLMResult(content=json.dumps(scaffold), provider="openai", model_mode="openai")

        with patch("services.code_generation_service.call_llm", side_effect=fake_call_llm):
            from services.code_generation_service import generate_file_structure
            scaffold = generate_file_structure(bs, "build an app", None)

        order = scaffold["generation_order"]
        css_idx = order.index("styles/globals.css")
        html_idx = order.index("index.html")
        assert css_idx < html_idx


# ===========================================================================
# 5. PER-FILE GENERATION WITH PROGRESS (stage 5)
# ===========================================================================


class TestPerFileGeneration:
    """Files are generated one-by-one with file_progress events emitted."""

    def test_file_progress_events_emitted_for_each_file(self, emit_fn, emit_log, tmp_path, monkeypatch):
        """The pipeline must emit file_progress events for every file in generation_order."""
        import config.settings as cs
        cs.settings.resolve_websites_dir = MagicMock(return_value=tmp_path)

        from services.code_generation_service import BrandSpec

        bs = BrandSpec(
            brand_name="ProgressTest",
            product_category="saas",
            target_audience="devs",
            core_offer="testing",
            pages=["index.html", "app.html"],
        )

        scaffold = {
            "project_type": "static_site",
            "file_tree": [
                {"path": "styles/globals.css", "purpose": "tokens", "depends_on": []},
                {"path": "index.html", "purpose": "Landing", "depends_on": ["styles/globals.css"]},
                {"path": "app.html", "purpose": "App", "depends_on": ["styles/globals.css"]},
            ],
            "generation_order": ["styles/globals.css", "index.html", "app.html"],
        }

        file_counter = {"n": 0}

        def fake_single_file(**kw):
            file_counter["n"] += 1
            fp = kw.get("file_path", "unknown")
            if fp.endswith(".css"):
                return ":root { --color-primary: #3b82f6; }"
            return f"<!DOCTYPE html><html><head><title>{fp}</title></head><body><h1>{fp}</h1></body></html>"

        def fake_synthesize(*a, **kw):
            return bs

        def fake_scaffold(*a, **kw):
            return scaffold

        def fake_assets(*a, **kw):
            return {}

        with patch("services.generation_pipeline._generate_image_assets", side_effect=fake_assets), \
             patch("services.code_generation_service.generate_file_structure", side_effect=fake_scaffold), \
             patch("services.code_generation_service.synthesize_brand_spec", side_effect=fake_synthesize), \
             patch("services.code_generation_service.generate_single_file", side_effect=fake_single_file), \
             patch("services.workspace_editor.apply_changes") as mock_apply, \
             patch("services.link_wiring.run_link_wiring_pass", side_effect=_passthrough_wiring), \
             patch("services.generation_pipeline._run_quality_check", return_value={"summary": "ok", "issues": [], "files_checked": 3}):

            from services.workspace_editor import ApplyResult
            mock_apply.return_value = ApplyResult(
                slug="progress-test", version_id="v1",
                applied=["styles/globals.css", "index.html", "app.html"],
                skipped=[], results=[],
            )

            from services.generation_pipeline import run_pipeline
            run_pipeline(
                session_id="test-sess",
                slug="progress-test",
                message="Build me a test app",
                history=[],
                existing_files=None,
                style_seed=None,
                design_system=None,
                operation=None,
                emit=emit_fn,
            )

        # Check file_progress events
        progress_events = [e for e in emit_log if e.get("type") == "file_progress"]
        generating_events = [e for e in progress_events if e["status"] == "generating"]
        done_events = [e for e in progress_events if e["status"] == "done"]

        assert len(generating_events) == 3, f"Expected 3 generating events, got {len(generating_events)}"
        assert len(done_events) == 3, f"Expected 3 done events, got {len(done_events)}"

        # Verify correct file paths in order
        gen_paths = [e["file_path"] for e in generating_events]
        assert gen_paths == ["styles/globals.css", "index.html", "app.html"]

        # Verify file indices are 1-based and total is correct
        for e in progress_events:
            assert e["total_files"] == 3
        assert generating_events[0]["file_index"] == 1
        assert generating_events[2]["file_index"] == 3

    def test_failed_file_emits_error_progress(self, emit_fn, emit_log, tmp_path, monkeypatch):
        """If a single file fails, an error progress event is emitted but pipeline continues."""
        import config.settings as cs
        cs.settings.resolve_websites_dir = MagicMock(return_value=tmp_path)

        from services.code_generation_service import BrandSpec

        bs = BrandSpec(brand_name="FailTest", product_category="saas", target_audience="x", core_offer="y")

        scaffold = {
            "file_tree": [
                {"path": "index.html", "purpose": "Landing", "depends_on": []},
                {"path": "broken.html", "purpose": "Broken page", "depends_on": []},
            ],
            "generation_order": ["index.html", "broken.html"],
        }

        call_count = {"n": 0}

        def fake_single_file(**kw):
            call_count["n"] += 1
            if kw.get("file_path") == "broken.html":
                raise RuntimeError("LLM refused")
            return "<!DOCTYPE html><html><body>OK</body></html>"

        with patch("services.generation_pipeline._generate_image_assets", return_value={}), \
             patch("services.code_generation_service.generate_file_structure", return_value=scaffold), \
             patch("services.code_generation_service.synthesize_brand_spec", return_value=bs), \
             patch("services.code_generation_service.generate_single_file", side_effect=fake_single_file), \
             patch("services.workspace_editor.apply_changes") as mock_apply, \
             patch("services.link_wiring.run_link_wiring_pass", side_effect=_passthrough_wiring), \
             patch("services.generation_pipeline._run_quality_check", return_value={"summary": "ok", "issues": [], "files_checked": 1}):

            from services.workspace_editor import ApplyResult
            mock_apply.return_value = ApplyResult(
                slug="fail-test", version_id="v1",
                applied=["index.html"], skipped=[], results=[],
            )

            from services.generation_pipeline import run_pipeline
            run_pipeline(
                session_id="fail-sess", slug="fail-test",
                message="build", history=[], existing_files=None,
                style_seed=None, design_system=None, operation=None,
                emit=emit_fn,
            )

        progress_events = [e for e in emit_log if e.get("type") == "file_progress"]
        error_events = [e for e in progress_events if e["status"] == "error"]
        assert len(error_events) == 1
        assert error_events[0]["file_path"] == "broken.html"


# ===========================================================================
# 6. FULL PIPELINE STAGE EMISSION ORDER
# ===========================================================================


class TestFullPipelineEventFlow:
    """The complete pipeline emits stage_update events in the correct sequence."""

    def test_all_stages_emitted_in_order_for_new_project(self, emit_fn, emit_log, tmp_path, monkeypatch):
        import config.settings as cs
        cs.settings.resolve_websites_dir = MagicMock(return_value=tmp_path)

        from services.code_generation_service import BrandSpec

        bs = BrandSpec(brand_name="FlowTest", product_category="saas", target_audience="x", core_offer="y")

        scaffold = {
            "file_tree": [{"path": "index.html", "purpose": "Landing", "depends_on": []}],
            "generation_order": ["index.html"],
        }

        def fake_single_file(**kw):
            return "<!DOCTYPE html><html><body>Hello</body></html>"

        with patch("services.generation_pipeline._generate_image_assets", return_value={}), \
             patch("services.code_generation_service.generate_file_structure", return_value=scaffold), \
             patch("services.code_generation_service.synthesize_brand_spec", return_value=bs), \
             patch("services.code_generation_service.generate_single_file", side_effect=fake_single_file), \
             patch("services.workspace_editor.apply_changes") as mock_apply, \
             patch("services.link_wiring.run_link_wiring_pass", side_effect=_passthrough_wiring), \
             patch("services.generation_pipeline._run_quality_check", return_value={"summary": "ok", "issues": [], "files_checked": 1}):

            from services.workspace_editor import ApplyResult
            mock_apply.return_value = ApplyResult(
                slug="flow-test", version_id="v1",
                applied=["index.html"], skipped=[], results=[],
            )

            from services.generation_pipeline import run_pipeline
            ctx = run_pipeline(
                session_id="flow-sess", slug="flow-test",
                message="Build a SaaS app", history=[], existing_files=None,
                style_seed=None, design_system=None, operation=None,
                emit=emit_fn,
            )

        stage_events = [e for e in emit_log if e.get("type") == "stage_update"]
        stage_keys = [e["stage_key"] for e in stage_events]

        expected_stages = [
            "parse_intent", "brand_design", "file_structure",
            "generate_assets", "generate_files", "apply_files",
            "wire_navigation", "quality_check", "complete",
        ]
        for stage in expected_stages:
            assert stage in stage_keys, f"Missing stage event: {stage!r}"

        # Verify ordering: each stage's first appearance is after the previous
        first_idx = {}
        for i, key in enumerate(stage_keys):
            if key not in first_idx:
                first_idx[key] = i

        for i in range(len(expected_stages) - 1):
            current = expected_stages[i]
            nxt = expected_stages[i + 1]
            assert first_idx[current] < first_idx[nxt], (
                f"Stage {current!r} (idx {first_idx[current]}) should come before "
                f"{nxt!r} (idx {first_idx[nxt]})"
            )

    def test_each_stage_has_running_and_done(self, emit_fn, emit_log, tmp_path, monkeypatch):
        """Every stage except 'complete' should have both a 'running' and 'done' event."""
        import config.settings as cs
        cs.settings.resolve_websites_dir = MagicMock(return_value=tmp_path)

        from services.code_generation_service import BrandSpec
        bs = BrandSpec(brand_name="X", product_category="saas", target_audience="x", core_offer="y")

        scaffold = {
            "file_tree": [{"path": "index.html", "purpose": "Landing", "depends_on": []}],
            "generation_order": ["index.html"],
        }

        with patch("services.generation_pipeline._generate_image_assets", return_value={}), \
             patch("services.code_generation_service.generate_file_structure", return_value=scaffold), \
             patch("services.code_generation_service.synthesize_brand_spec", return_value=bs), \
             patch("services.code_generation_service.generate_single_file", return_value="<!DOCTYPE html><html><body>Hi</body></html>"), \
             patch("services.workspace_editor.apply_changes") as mock_apply, \
             patch("services.link_wiring.run_link_wiring_pass", side_effect=_passthrough_wiring), \
             patch("services.generation_pipeline._run_quality_check", return_value={"summary": "ok", "issues": [], "files_checked": 1}):

            from services.workspace_editor import ApplyResult
            mock_apply.return_value = ApplyResult(
                slug="x", version_id="v1", applied=["index.html"], skipped=[], results=[],
            )

            from services.generation_pipeline import run_pipeline
            run_pipeline(
                session_id="s", slug="x", message="build", history=[],
                existing_files=None, style_seed=None, design_system=None,
                operation=None, emit=emit_fn,
            )

        stage_events = [e for e in emit_log if e.get("type") == "stage_update"]
        stages_with_running = {
            "parse_intent", "brand_design", "file_structure",
            "generate_assets", "generate_files", "apply_files",
            "wire_navigation", "quality_check",
        }

        for stage_key in stages_with_running:
            statuses = [e["status"] for e in stage_events if e["stage_key"] == stage_key]
            assert "running" in statuses, f"Stage {stage_key!r} missing 'running' status"
            assert "done" in statuses or "error" in statuses, (
                f"Stage {stage_key!r} missing terminal status (done/error), got: {statuses}"
            )


# ===========================================================================
# 7. EDIT MODE (existing project)
# ===========================================================================


class TestEditModeFlow:
    """When editing an existing project, brand_design and file_structure are skipped."""

    def test_edit_skips_brand_and_scaffold_stages(self, emit_fn, emit_log, tmp_path, monkeypatch):
        import config.settings as cs
        cs.settings.resolve_websites_dir = MagicMock(return_value=tmp_path)

        existing_html = "<!DOCTYPE html><html><body>Original</body></html>"

        def fake_generate(**kw):
            from services.code_generation_service import FileChange, GenerationResult
            return GenerationResult(
                assistant_message="Updated.",
                changes=[FileChange(
                    path=f"data/websites/edit-app/index.html",
                    action="update",
                    content="<!DOCTYPE html><html><body>Updated</body></html>",
                    summary="Updated page",
                )],
                provider="openai", model_mode="openai",
            )

        with patch("services.generation_pipeline._generate_image_assets", return_value={}), \
             patch("services.code_generation_service.generate", side_effect=fake_generate), \
             patch("services.workspace_editor.apply_changes") as mock_apply, \
             patch("services.link_wiring.run_link_wiring_pass", side_effect=_passthrough_wiring), \
             patch("services.generation_pipeline._run_quality_check", return_value={"summary": "ok", "issues": [], "files_checked": 1}):

            from services.workspace_editor import ApplyResult
            mock_apply.return_value = ApplyResult(
                slug="edit-app", version_id="v2",
                applied=["index.html"], skipped=[], results=[],
            )

            from services.generation_pipeline import run_pipeline
            run_pipeline(
                session_id="edit-sess", slug="edit-app",
                message="Change the background to dark blue",
                history=[{"role": "user", "content": "build me a fitness app"}],
                existing_files={"index.html": existing_html},
                style_seed=None, design_system=None, operation=None,
                emit=emit_fn,
            )

        stage_events = [e for e in emit_log if e.get("type") == "stage_update"]

        # brand_design and file_structure should still appear but complete instantly (0ms)
        brand_events = [e for e in stage_events if e["stage_key"] == "brand_design"]
        scaffold_events = [e for e in stage_events if e["stage_key"] == "file_structure"]

        assert any(e["status"] == "done" for e in brand_events)
        assert any(e["status"] == "done" for e in scaffold_events)
        # In edit mode, they should NOT have a 'running' phase (instant skip)
        assert not any(e["status"] == "running" for e in brand_events)
        assert not any(e["status"] == "running" for e in scaffold_events)


# ===========================================================================
# 8. FILES SAVED TO DATABASE
# ===========================================================================


class TestFilesPersistence:
    """Generated files are persisted to the project_files DB table."""

    def test_generated_files_stored_in_db(self, emit_fn, emit_log, tmp_path, monkeypatch):
        import config.settings as cs
        cs.settings.resolve_websites_dir = MagicMock(return_value=tmp_path)

        from data.database import upsert_chat_session
        upsert_chat_session("db-sess", slug="db-test", product_name="DbTest", version_id="v0")

        from services.code_generation_service import BrandSpec
        bs = BrandSpec(brand_name="DbTest", product_category="saas", target_audience="x", core_offer="y")

        scaffold = {
            "file_tree": [
                {"path": "style.css", "purpose": "Styles", "depends_on": []},
                {"path": "index.html", "purpose": "Landing", "depends_on": ["style.css"]},
            ],
            "generation_order": ["style.css", "index.html"],
        }

        def fake_single_file(**kw):
            fp = kw.get("file_path", "")
            if fp.endswith(".css"):
                return "body { color: red; }"
            return "<!DOCTYPE html><html><body>DB test</body></html>"

        with patch("services.generation_pipeline._generate_image_assets", return_value={}), \
             patch("services.code_generation_service.generate_file_structure", return_value=scaffold), \
             patch("services.code_generation_service.synthesize_brand_spec", return_value=bs), \
             patch("services.code_generation_service.generate_single_file", side_effect=fake_single_file), \
             patch("services.workspace_editor.apply_changes") as mock_apply, \
             patch("services.link_wiring.run_link_wiring_pass", side_effect=_passthrough_wiring), \
             patch("services.generation_pipeline._run_quality_check", return_value={"summary": "ok", "issues": [], "files_checked": 2}):

            from services.workspace_editor import ApplyResult
            mock_apply.return_value = ApplyResult(
                slug="db-test", version_id="v1",
                applied=["style.css", "index.html"], skipped=[], results=[],
            )

            from services.generation_pipeline import run_pipeline
            run_pipeline(
                session_id="db-sess", slug="db-test",
                message="build app", history=[], existing_files=None,
                style_seed=None, design_system=None, operation=None,
                emit=emit_fn,
            )

        from data.database import list_project_files_for_session, get_project_file
        files = list_project_files_for_session("db-sess")
        file_paths = [f["file_path"] for f in files]

        assert "style.css" in file_paths
        assert "index.html" in file_paths

        content = get_project_file("db-sess", "index.html")
        assert content is not None
        assert "DB test" in content["content"]


# ===========================================================================
# 9. PIPELINE RESULT STRUCTURE
# ===========================================================================


class TestPipelineResult:
    """run_pipeline returns a context dict with gen + apply results."""

    def test_result_has_gen_and_apply(self, emit_fn, emit_log, tmp_path, monkeypatch):
        import config.settings as cs
        cs.settings.resolve_websites_dir = MagicMock(return_value=tmp_path)

        from services.code_generation_service import BrandSpec
        bs = BrandSpec(brand_name="Result", product_category="saas", target_audience="x", core_offer="y")

        scaffold = {
            "file_tree": [{"path": "index.html", "purpose": "Landing", "depends_on": []}],
            "generation_order": ["index.html"],
        }

        with patch("services.generation_pipeline._generate_image_assets", return_value={}), \
             patch("services.code_generation_service.generate_file_structure", return_value=scaffold), \
             patch("services.code_generation_service.synthesize_brand_spec", return_value=bs), \
             patch("services.code_generation_service.generate_single_file", return_value="<!DOCTYPE html><html><body>R</body></html>"), \
             patch("services.workspace_editor.apply_changes") as mock_apply, \
             patch("services.link_wiring.run_link_wiring_pass", side_effect=_passthrough_wiring), \
             patch("services.generation_pipeline._run_quality_check", return_value={"summary": "ok", "issues": [], "files_checked": 1}):

            from services.workspace_editor import ApplyResult
            mock_apply.return_value = ApplyResult(
                slug="result", version_id="v1",
                applied=["index.html"], skipped=[], results=[],
            )

            from services.generation_pipeline import run_pipeline
            ctx = run_pipeline(
                session_id="r-sess", slug="result",
                message="build", history=[], existing_files=None,
                style_seed=None, design_system=None, operation=None,
                emit=emit_fn,
            )

        assert "gen" in ctx
        assert "apply" in ctx
        assert ctx["gen"].assistant_message
        assert ctx["gen"].changes
        assert ctx["apply"].slug == "result"
        assert ctx["apply"].version_id == "v1"

    def test_result_gen_message_contains_brand_name(self, emit_fn, emit_log, tmp_path, monkeypatch):
        """The assistant message should mention the brand name."""
        import config.settings as cs
        cs.settings.resolve_websites_dir = MagicMock(return_value=tmp_path)

        from services.code_generation_service import BrandSpec
        bs = BrandSpec(brand_name="AquaFlow", product_category="saas", target_audience="x", core_offer="y")

        scaffold = {
            "file_tree": [{"path": "index.html", "purpose": "Landing", "depends_on": []}],
            "generation_order": ["index.html"],
        }

        with patch("services.generation_pipeline._generate_image_assets", return_value={}), \
             patch("services.code_generation_service.generate_file_structure", return_value=scaffold), \
             patch("services.code_generation_service.synthesize_brand_spec", return_value=bs), \
             patch("services.code_generation_service.generate_single_file", return_value="<!DOCTYPE html><html><body>AquaFlow</body></html>"), \
             patch("services.workspace_editor.apply_changes") as mock_apply, \
             patch("services.link_wiring.run_link_wiring_pass", side_effect=_passthrough_wiring), \
             patch("services.generation_pipeline._run_quality_check", return_value={"summary": "ok", "issues": [], "files_checked": 1}):

            from services.workspace_editor import ApplyResult
            mock_apply.return_value = ApplyResult(
                slug="aquaflow", version_id="v1",
                applied=["index.html"], skipped=[], results=[],
            )

            from services.generation_pipeline import run_pipeline
            ctx = run_pipeline(
                session_id="aq-sess", slug="aquaflow",
                message="build a water app", history=[], existing_files=None,
                style_seed=None, design_system=None, operation=None,
                emit=emit_fn,
            )

        assert "AquaFlow" in ctx["gen"].assistant_message


# ===========================================================================
# 10. ACTIVE FILE TARGETING (chat sends active_file to backend)
# ===========================================================================


class TestActiveFileTargeting:
    """The /builder/generate endpoint accepts active_file for AI-targeted edits."""

    def test_generate_endpoint_accepts_active_file(self, tmp_path, monkeypatch):
        import config.settings as cs
        monkeypatch.setenv("CEOCLAW_DATABASE_PATH", str(tmp_path / "af.db"))
        monkeypatch.setenv("AUTH_REQUIRED", "false")
        monkeypatch.setenv("CREDITS_ENFORCED", "false")
        cs.settings = cs.Settings()
        cs.settings.database_path = str(tmp_path / "af.db")
        cs.settings.auth_required = False
        cs.settings.credits_enforced = False

        from data.database import init_db
        init_db()

        from api.server import app
        from fastapi.testclient import TestClient
        client = TestClient(app)

        resp = client.post("/builder/generate", json={
            "session_id": "af-sess",
            "message": "change the hero color",
            "active_file": "index.html",
            "mock_mode": True,
        })
        assert resp.status_code == 200
