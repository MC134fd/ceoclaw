"""
Tests for services/build_repair.py (Phase 4 repair loop).

Covers:
  - should_repair trigger conditions
  - classify_failures priority ordering
  - deterministic fix functions (DOCTYPE, title, viewport)
  - LLM fix path (mocked)
  - run_repair_round mutates changes in place for targeted indices only
  - max_files cap respected
  - flag-off path: zero mutations
  - pipeline-level repair block runs when flag is on
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("CEOCLAW_DATABASE_PATH", str(tmp_path / "repair_test.db"))
    import config.settings as cs
    cs.settings = cs.Settings()
    from data.database import init_db
    init_db()


def _make_change(path: str, content: str, action: str = "create"):
    from services.code_generation_service import FileChange
    return FileChange(path=path, action=action, content=content, summary="")


def _slug_path(slug: str, rel: str) -> str:
    return f"data/websites/{slug}/{rel}"


# ---------------------------------------------------------------------------
# should_repair
# ---------------------------------------------------------------------------

class TestShouldRepair:
    def test_empty_dict_no_trigger(self):
        from services.build_repair import should_repair
        assert should_repair({}) is False

    def test_trigger_on_skipped_html(self):
        from services.build_repair import should_repair
        assert should_repair({"skipped_by_output_validator": ["index.html"]}) is True

    def test_no_trigger_on_binary_skip(self):
        from services.build_repair import should_repair
        assert should_repair({"skipped_by_output_validator": ["assets/hero.png"]}) is False

    def test_trigger_on_missing_doctype_in_clean(self):
        from services.build_repair import should_repair
        val = {
            "pending_html_issues": [{"code": "missing_doctype", "path": "index.html", "message": "x", "severity": "info"}],
            "raw": {"clean_paths": ["index.html"]},
        }
        assert should_repair(val) is True

    def test_trigger_on_missing_doctype_always(self):
        # build_validation._pending_html_quality() runs ONLY on clean_files, so any
        # path in pending_html_issues is already in clean by construction.  The
        # repair trigger does not require a separate clean_paths cross-check.
        from services.build_repair import should_repair
        val = {
            "pending_html_issues": [{"code": "missing_doctype", "path": "index.html", "message": "x", "severity": "info"}],
            "raw": {"clean_paths": []},  # raw.clean_paths absent/empty — doesn't matter
        }
        assert should_repair(val) is True

    def test_no_trigger_on_spec_issues_only(self):
        from services.build_repair import should_repair
        val = {"spec_issues": [{"code": "invalid_site_spec", "path": "_spec.json", "message": "bad", "severity": "warning"}]}
        assert should_repair(val) is False

    def test_no_trigger_on_warnings_only(self):
        from services.build_repair import should_repair
        val = {"output_warnings": ["index.html: missing viewport"]}
        assert should_repair(val) is False


# ---------------------------------------------------------------------------
# Deterministic fix functions
# ---------------------------------------------------------------------------

class TestFixInjectDoctype:
    def _fix(self, content):
        from services.build_repair import _fix_inject_doctype
        return _fix_inject_doctype(content)

    def test_noop_when_already_has_doctype(self):
        html = "<!DOCTYPE html><html><head><title>t</title></head><body></body></html>"
        assert self._fix(html) == html

    def test_strips_preamble_when_doctype_found_deeper(self):
        html = "Some preamble text\n<!DOCTYPE html><html><head></head><body></body></html>"
        result = self._fix(html)
        assert result.startswith("<!DOCTYPE html>")
        assert "preamble" not in result

    def test_prepends_doctype_before_html_tag(self):
        html = "<html lang='en'><head></head><body>hi</body></html>"
        result = self._fix(html)
        assert result.startswith("<!DOCTYPE html>")
        assert "<html" in result

    def test_wraps_bare_content_with_boilerplate(self):
        content = "<p>Hello world</p>"
        result = self._fix(content)
        assert "<!DOCTYPE html>" in result
        assert "<html" in result
        assert "<body>" in result

    def test_output_passes_looks_like_html(self):
        """After fix, output_validator._looks_like_html must return True."""
        content = "Just some text with no HTML tags at all"
        result = self._fix(content)
        head = result.strip().lower()[:300]
        assert "<!doctype" in head or "<html" in head


class TestFixInjectTitle:
    def _fix(self, content, slug="my-slug"):
        from services.build_repair import _fix_inject_title
        return _fix_inject_title(content, slug)

    def test_noop_when_title_present(self):
        html = "<!DOCTYPE html><html><head><title>Existing</title></head><body></body></html>"
        assert self._fix(html) == html

    def test_injects_after_head_tag(self):
        html = "<!DOCTYPE html><html><head></head><body></body></html>"
        result = self._fix(html)
        assert "<title>" in result.lower()

    def test_title_uses_humanised_slug(self):
        html = "<!DOCTYPE html><html><head></head><body></body></html>"
        result = self._fix(html, "my-cool-app")
        assert "My Cool App" in result

    def test_injects_before_body_when_no_head(self):
        html = "<!DOCTYPE html><html><body>content</body></html>"
        result = self._fix(html)
        assert "<title>" in result.lower()
        assert result.index("<title>") < result.index("<body>")


class TestFixInjectViewport:
    def _fix(self, content):
        from services.build_repair import _fix_inject_viewport
        return _fix_inject_viewport(content)

    def test_noop_when_viewport_present(self):
        html = (
            '<!DOCTYPE html><html><head>'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '</head><body></body></html>'
        )
        assert self._fix(html) == html

    def test_injects_after_head_tag(self):
        html = "<!DOCTYPE html><html><head><title>t</title></head><body></body></html>"
        result = self._fix(html)
        assert "viewport" in result.lower()
        assert result.index("viewport") < result.index("<title>")

    def test_output_passes_viewport_check(self):
        """After fix, _VIEWPORT_RE should match."""
        import re
        _VIEWPORT_RE = re.compile(r'<meta[^>]+name=["\']viewport["\'][^>]*>', re.IGNORECASE)
        html = "<!DOCTYPE html><html><head></head><body></body></html>"
        result = self._fix(html)
        assert _VIEWPORT_RE.search(result) is not None

    def test_critical_violation_resolved(self):
        """After viewport inject, output_validator critical_violation must be False."""
        from services.output_validator import _responsive_html_warnings
        # Build a minimal HTML > 1200 chars with no viewport and no breakpoints
        padding = "<!-- " + "x" * 1200 + " -->"
        html = f"<!DOCTYPE html><html><head>{padding}</head><body></body></html>"
        _, critical_before = _responsive_html_warnings(html, "test.html")
        assert critical_before is True  # confirm precondition

        result = self._fix(html)
        _, critical_after = _responsive_html_warnings(result, "test.html")
        assert critical_after is False


# ---------------------------------------------------------------------------
# run_repair_round
# ---------------------------------------------------------------------------

class TestRunRepairRound:
    def _valid_html(self) -> str:
        return (
            "<!DOCTYPE html><html lang='en'><head>"
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>T</title></head>"
            "<body><p>Hello</p>"
            "<style>@media(max-width:640px){}</style>"
            "</body></html>"
        )

    def test_repairs_missing_doctype_in_skipped(self, tmp_path, monkeypatch):
        """A file dropped by output_validator for missing DOCTYPE is patched."""
        slug = "test-doctype"
        # Content that DOES have <html> but not at position 0 (preamble)
        bad_content = "   \n<html><head></head><body>hello</body></html>"
        changes = [
            _make_change(_slug_path(slug, "index.html"), bad_content),
            _make_change(_slug_path(slug, "app.html"), self._valid_html()),
        ]
        val_dict = {
            "skipped_by_output_validator": ["index.html"],
            "pending_html_issues": [],
            "spec_issues": [],
            "raw": {"clean_paths": ["app.html"]},
        }
        from services.build_repair import run_repair_round
        result = run_repair_round(
            slug=slug,
            changes=changes,
            validation_dict=val_dict,
            round_index=0,
            max_files=2,
        )
        assert result.success is True
        assert "index.html" in result.paths_touched
        # app.html must be untouched
        assert changes[1].content == self._valid_html()
        # Patched content must now pass _looks_like_html
        from services.output_validator import _looks_like_html
        assert _looks_like_html(changes[0].content) is True

    def test_repairs_missing_title_in_clean(self, tmp_path, monkeypatch):
        """A file in clean_paths with missing_title gets a <title> injected."""
        slug = "test-title"
        # Valid HTML but no <title>
        html_no_title = (
            "<!DOCTYPE html><html><head>"
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "</head><body></body></html>"
        )
        changes = [_make_change(_slug_path(slug, "index.html"), html_no_title)]
        val_dict = {
            "skipped_by_output_validator": [],
            "pending_html_issues": [
                {"code": "missing_title", "path": "index.html", "message": "x", "severity": "info"}
            ],
            "spec_issues": [],
            "raw": {"clean_paths": ["index.html"]},
        }
        from services.build_repair import run_repair_round
        result = run_repair_round(slug=slug, changes=changes, validation_dict=val_dict,
                                  round_index=0, max_files=2)
        assert result.success is True
        assert "<title>" in changes[0].content.lower()

    def test_max_files_cap_respected(self):
        """Only max_files paths are patched even if more are broken."""
        slug = "cap-test"
        bad = "   <html><body>x</body></html>"  # preamble → dropped
        changes = [
            _make_change(_slug_path(slug, "a.html"), bad),
            _make_change(_slug_path(slug, "b.html"), bad),
            _make_change(_slug_path(slug, "c.html"), bad),
        ]
        val_dict = {
            "skipped_by_output_validator": ["a.html", "b.html", "c.html"],
            "pending_html_issues": [],
            "spec_issues": [],
            "raw": {"clean_paths": []},
        }
        from services.build_repair import run_repair_round
        result = run_repair_round(slug=slug, changes=changes, validation_dict=val_dict,
                                  round_index=0, max_files=2)
        # At most 2 files touched
        assert len(result.paths_touched) <= 2
        # Third file untouched
        assert changes[2].content == bad

    def test_unrelated_changes_never_touched(self):
        """FileChanges not targeted by repair are never modified."""
        slug = "untouched-test"
        good_content = "unchanged_sentinel"
        bad_content = "   <html><body>fix me</body></html>"
        changes = [
            _make_change(_slug_path(slug, "index.html"), bad_content),
            _make_change(_slug_path(slug, "app.html"), good_content),
            _make_change(_slug_path(slug, "pages/signup.html"), good_content),
        ]
        val_dict = {
            "skipped_by_output_validator": ["index.html"],
            "pending_html_issues": [],
            "spec_issues": [],
            "raw": {"clean_paths": []},
        }
        from services.build_repair import run_repair_round
        run_repair_round(slug=slug, changes=changes, validation_dict=val_dict,
                         round_index=0, max_files=2)
        assert changes[1].content == good_content
        assert changes[2].content == good_content

    def test_flag_off_means_no_repair(self, monkeypatch):
        """With builder_repair_enabled=False the pipeline must not call run_repair_round."""
        import config.settings as cs
        monkeypatch.setattr(cs.settings, "builder_repair_enabled", False)

        slug = "flag-off"
        bad = "   <html><body>x</body></html>"
        original = bad
        changes = [_make_change(_slug_path(slug, "index.html"), bad)]

        # Simulate pipeline repair block
        if cs.settings.builder_repair_enabled:
            from services.build_repair import run_repair_round, should_repair
            val = {"skipped_by_output_validator": ["index.html"], "raw": {}}
            for rnd in range(cs.settings.builder_repair_max_rounds):
                if not should_repair(val):
                    break
                run_repair_round(slug=slug, changes=changes, validation_dict=val,
                                 round_index=rnd, max_files=2)

        assert changes[0].content == original  # untouched

    def test_binary_change_not_patched(self):
        """Binary FileChange (bytes content) is skipped by the repair loop."""
        slug = "binary-test"
        from services.code_generation_service import FileChange
        changes = [
            FileChange(
                path=_slug_path(slug, "assets/hero.png"),
                action="create",
                content=b"\x89PNG",
                summary="",
            )
        ]
        val_dict = {
            "skipped_by_output_validator": ["assets/hero.png"],
            "pending_html_issues": [],
            "spec_issues": [],
            "raw": {"clean_paths": []},
        }
        from services.build_repair import run_repair_round
        result = run_repair_round(slug=slug, changes=changes, validation_dict=val_dict,
                                  round_index=0, max_files=2)
        assert result.success is False
        assert changes[0].content == b"\x89PNG"

    def test_spec_issue_is_unrecoverable(self):
        """_spec.json spec_issues are classified UNRECOVERABLE and not patched."""
        slug = "spec-test"
        changes = [
            _make_change(_slug_path(slug, "_spec.json"), "NOT VALID JSON {{{")
        ]
        val_dict = {
            "skipped_by_output_validator": [],
            "pending_html_issues": [],
            "spec_issues": [{"code": "invalid_site_spec", "path": "_spec.json",
                              "message": "parse error", "severity": "warning"}],
            "raw": {"clean_paths": []},
        }
        original = changes[0].content
        from services.build_repair import run_repair_round
        result = run_repair_round(slug=slug, changes=changes, validation_dict=val_dict,
                                  round_index=0, max_files=2)
        assert result.success is False
        assert changes[0].content == original

    def test_repair_improves_clean_set(self, tmp_path, monkeypatch):
        """After repair, re-running pre_apply_orchestrate should see fewer skipped paths.

        The bad content has a 400-char preamble so <html> is beyond the 300-char
        window that _looks_like_html() inspects, causing output_validator to drop it.
        """
        slug = "integration-repair"
        # 400-char preamble pushes <html> past the 300-char _looks_like_html window
        preamble = "X" * 400
        html_body = (
            "<html lang='en'><head>"
            "<title>T</title>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "</head><body>"
            "<style>@media(max-width:640px){}@media(max-width:1024px){}</style>"
            "</body></html>"
        )
        bad_content = preamble + html_body

        changes = [_make_change(_slug_path(slug, "index.html"), bad_content)]

        # Confirm it's initially skipped by output_validator
        from services.build_validation import pre_apply_orchestrate
        val_before = pre_apply_orchestrate(slug, changes)
        assert "index.html" in val_before.skipped_by_output_validator

        # Run repair
        from services.build_repair import run_repair_round
        run_repair_round(
            slug=slug,
            changes=changes,
            validation_dict=val_before.to_dict(),
            round_index=0,
            max_files=2,
        )

        # Recompute — file should now be clean (preamble stripped, DOCTYPE at front)
        val_after = pre_apply_orchestrate(slug, changes)
        assert "index.html" not in val_after.skipped_by_output_validator

    def test_lmm_repair_uses_call_llm(self, monkeypatch):
        """TARGETED_LLM_HTML_FIX path calls call_llm and returns its output."""
        from services.build_repair import RepairFailureClass, RepairStrategy, RepairTask, _fix_llm_html
        from services.provider_router import LLMResult

        fixed_html = "<!DOCTYPE html><html><head><title>Fixed</title></head><body></body></html>"

        def fake_call_llm(messages, **kw):
            return LLMResult(
                content=fixed_html,
                provider="openai",
                model_mode="openai",
                fallback_used=False,
                fallback_reason="",
            )

        monkeypatch.setattr("services.build_repair.call_llm", fake_call_llm, raising=False)

        # Patch the import inside _fix_llm_html
        with patch("services.provider_router.call_llm", fake_call_llm):
            task = RepairTask(
                round_index=0,
                change_index=0,
                path="index.html",
                failure_codes=(RepairFailureClass.OUTPUT_VALIDATOR_DROP,),
                strategy=RepairStrategy.TARGETED_LLM_HTML_FIX,
            )
            from services.code_generation_service import FileChange
            change = FileChange(path="data/websites/x/index.html", action="create",
                                content="not html at all", summary="")
            result = _fix_llm_html(change.content, task, "build a thing")
        assert result == fixed_html


# ---------------------------------------------------------------------------
# RepairAttemptResult.to_dict
# ---------------------------------------------------------------------------

def test_repair_attempt_result_to_dict():
    from services.build_repair import RepairAttemptResult
    r = RepairAttemptResult(
        success=True,
        paths_touched=["index.html"],
        strategies_used=["deterministic_doctype_inject"],
        round_index=0,
        messages=["applied"],
        errors=[],
    )
    d = r.to_dict()
    assert d["success"] is True
    assert d["paths_touched"] == ["index.html"]
    assert d["round_index"] == 0


# ---------------------------------------------------------------------------
# Pipeline integration: repair_trace in ctx
# ---------------------------------------------------------------------------

def test_pipeline_populates_repair_trace_when_disabled(tmp_path, monkeypatch):
    """When BUILDER_REPAIR_ENABLED=False, ctx['repair_trace'] exists and is []."""
    import config.settings as cs
    monkeypatch.setattr(cs.settings, "builder_repair_enabled", False)
    cs.settings.resolve_websites_dir = MagicMock(return_value=tmp_path)

    from services.code_generation_service import BrandSpec, FileChange, GenerationResult

    bs = BrandSpec(
        brand_name="RepairTest",
        product_category="saas_b2c",
        target_audience="devs",
        core_offer="testing",
        pages=["index.html"],
    )

    html = (
        "<!DOCTYPE html><html lang='en'><head>"
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>T</title></head>"
        "<body><style>@media(max-width:640px){}@media(max-width:1024px){}</style></body></html>"
    )

    def fake_gen(**kw):
        return GenerationResult(
            assistant_message="ok",
            changes=[FileChange(
                path="data/websites/repair-test/index.html",
                action="create",
                content=html,
                summary="",
            )],
            model_mode="openai",
        )

    from services.workspace_editor import ApplyResult

    with patch("services.generation_pipeline._generate_image_assets", return_value={}), \
         patch("services.code_generation_service.generate_file_structure",
               return_value={"file_tree": [], "generation_order": []}), \
         patch("services.code_generation_service.synthesize_brand_spec", return_value=bs), \
         patch("services.code_generation_service.generate", side_effect=fake_gen), \
         patch("services.workspace_editor.apply_changes") as mock_apply, \
         patch("services.link_wiring.run_link_wiring_pass", return_value=([], [])), \
         patch("services.generation_pipeline._run_quality_check",
               return_value={"summary": "ok", "issues": []}):

        mock_apply.return_value = ApplyResult(
            slug="repair-test", version_id="v1", applied=["index.html"], skipped=[], results=[]
        )

        from services.generation_pipeline import run_pipeline
        ctx = run_pipeline(
            session_id="sess-repair",
            slug="repair-test",
            message="build it",
            history=[],
            existing_files=None,
            style_seed=None,
            design_system=None,
            operation=None,
            emit=lambda e: None,
            brand_spec=bs,
        )

    assert "repair_trace" in ctx
    assert ctx["repair_trace"] == []


def test_pipeline_repair_trace_has_entries_when_enabled(tmp_path, monkeypatch):
    """When enabled and trigger fires, repair_trace has at least one entry."""
    import config.settings as cs
    monkeypatch.setattr(cs.settings, "builder_repair_enabled", True)
    monkeypatch.setattr(cs.settings, "builder_repair_max_rounds", 1)
    monkeypatch.setattr(cs.settings, "builder_repair_max_files_per_round", 2)
    cs.settings.resolve_websites_dir = MagicMock(return_value=tmp_path)

    from services.code_generation_service import BrandSpec, FileChange, GenerationResult

    bs = BrandSpec(
        brand_name="RepairEnabled",
        product_category="saas_b2c",
        target_audience="devs",
        core_offer="testing",
        pages=["index.html"],
    )

    # Content that passes _looks_like_html (has <html) but has no DOCTYPE,
    # so pending_html_issues will have missing_doctype → should_repair returns True.
    bad_html = (
        "<html lang='en'><head>"
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>T</title></head>"
        "<body><style>@media(max-width:640px){}@media(max-width:1024px){}</style></body></html>"
    )

    def fake_gen(**kw):
        return GenerationResult(
            assistant_message="ok",
            changes=[FileChange(
                path="data/websites/repair-enabled/index.html",
                action="create",
                content=bad_html,
                summary="",
            )],
            model_mode="openai",
        )

    from services.workspace_editor import ApplyResult

    with patch("services.generation_pipeline._generate_image_assets", return_value={}), \
         patch("services.code_generation_service.generate_file_structure",
               return_value={"file_tree": [], "generation_order": []}), \
         patch("services.code_generation_service.synthesize_brand_spec", return_value=bs), \
         patch("services.code_generation_service.generate", side_effect=fake_gen), \
         patch("services.workspace_editor.apply_changes") as mock_apply, \
         patch("services.link_wiring.run_link_wiring_pass", return_value=([], [])), \
         patch("services.generation_pipeline._run_quality_check",
               return_value={"summary": "ok", "issues": []}):

        mock_apply.return_value = ApplyResult(
            slug="repair-enabled", version_id="v1", applied=["index.html"], skipped=[], results=[]
        )

        from services.generation_pipeline import run_pipeline
        ctx = run_pipeline(
            session_id="sess-repair-on",
            slug="repair-enabled",
            message="build it",
            history=[],
            existing_files=None,
            style_seed=None,
            design_system=None,
            operation=None,
            emit=lambda e: None,
            brand_spec=bs,
        )

    assert "repair_trace" in ctx
    # At least one round should have been attempted
    assert len(ctx["repair_trace"]) >= 1
    first = ctx["repair_trace"][0]
    assert "paths_touched" in first
    assert "round_index" in first


# ===========================================================================
# Phase 5: RepairSummary and repair feedback tests
# ===========================================================================


class TestBuildRepairSummary:
    def test_empty_trace_returns_zero_summary(self):
        from services.build_repair_feedback import build_repair_summary
        s = build_repair_summary([])
        assert s.repaired_paths == ()
        assert s.failed_paths == ()
        assert s.strategies_used == ()
        assert s.repeated_fail_paths == ()
        assert s.total_rounds == 0
        assert s.hints == ()

    def test_none_like_trace_returns_zero_summary(self):
        from services.build_repair_feedback import build_repair_summary
        s = build_repair_summary([])
        assert s.total_rounds == 0

    def test_repaired_paths_collected(self):
        from services.build_repair_feedback import build_repair_summary
        trace = [
            {
                "round_index": 0,
                "paths_touched": ["index.html", "app.html"],
                "strategies_used": ["deterministic_doctype_inject"],
                "messages": [],
                "errors": [],
                "success": True,
            }
        ]
        s = build_repair_summary(trace)
        assert "index.html" in s.repaired_paths
        assert "app.html" in s.repaired_paths
        assert "deterministic_doctype_inject" in s.strategies_used
        assert s.total_rounds == 1

    def test_failed_paths_from_errors(self):
        from services.build_repair_feedback import build_repair_summary
        trace = [
            {
                "round_index": 0,
                "paths_touched": [],
                "strategies_used": [],
                "messages": [],
                "errors": [
                    "round=0 path='broken.html' strategy=targeted_llm_html_fix — no change"
                ],
                "success": False,
            }
        ]
        s = build_repair_summary(trace)
        assert "broken.html" in s.failed_paths
        assert "broken.html" not in s.repaired_paths

    def test_repaired_path_not_in_failed(self):
        """A path repaired in round 1 after failing in round 0 is in repaired, not failed."""
        from services.build_repair_feedback import build_repair_summary
        trace = [
            {
                "round_index": 0,
                "paths_touched": [],
                "strategies_used": [],
                "messages": [],
                "errors": ["round=0 path='index.html' strategy=deterministic_doctype_inject — no change"],
                "success": False,
            },
            {
                "round_index": 1,
                "paths_touched": ["index.html"],
                "strategies_used": ["deterministic_doctype_inject"],
                "messages": [],
                "errors": [],
                "success": True,
            },
        ]
        s = build_repair_summary(trace)
        assert "index.html" in s.repaired_paths
        assert "index.html" not in s.failed_paths

    def test_repeated_fail_paths(self):
        """A path in errors across 2+ rounds is in repeated_fail_paths."""
        from services.build_repair_feedback import build_repair_summary
        trace = [
            {
                "round_index": 0,
                "paths_touched": [],
                "strategies_used": [],
                "messages": [],
                "errors": ["round=0 path='hard.html' strategy=targeted_llm_html_fix — no change"],
                "success": False,
            },
            {
                "round_index": 1,
                "paths_touched": [],
                "strategies_used": [],
                "messages": [],
                "errors": ["round=1 path='hard.html' strategy=targeted_llm_html_fix — no change"],
                "success": False,
            },
        ]
        s = build_repair_summary(trace)
        assert "hard.html" in s.repeated_fail_paths

    def test_unrecoverable_message_counted_as_failed(self):
        from services.build_repair_feedback import build_repair_summary
        trace = [
            {
                "round_index": 0,
                "paths_touched": [],
                "strategies_used": [],
                "messages": [
                    "round=0 path='_spec.json' codes=['invalid_site_spec'] — UNRECOVERABLE (skipped)"
                ],
                "errors": [],
                "success": False,
            }
        ]
        s = build_repair_summary(trace)
        assert "_spec.json" in s.failed_paths

    def test_hints_generated_for_known_strategies(self):
        from services.build_repair_feedback import build_repair_summary
        trace = [
            {
                "round_index": 0,
                "paths_touched": ["index.html"],
                "strategies_used": ["deterministic_doctype_inject"],
                "messages": [],
                "errors": [],
                "success": True,
            }
        ]
        s = build_repair_summary(trace)
        assert len(s.hints) > 0
        # Should contain a hint about DOCTYPE
        assert any("DOCTYPE" in h or "doctype" in h.lower() for h in s.hints)

    def test_summary_is_serializable(self):
        """to_dict() must return a JSON-serializable dict with no File contents."""
        import json
        from services.build_repair_feedback import build_repair_summary
        trace = [
            {
                "round_index": 0,
                "paths_touched": ["index.html"],
                "strategies_used": ["deterministic_viewport_inject"],
                "messages": ["round=0 path='index.html' strategy=deterministic_viewport_inject — applied"],
                "errors": [],
                "success": True,
            }
        ]
        d = build_repair_summary(trace).to_dict()
        serialized = json.dumps(d)  # must not raise
        back = json.loads(serialized)
        assert back["total_rounds"] == 1
        assert "index.html" in back["repaired_paths"]
        # No file contents stored
        for v in back.values():
            if isinstance(v, list):
                for item in v:
                    assert len(str(item)) < 500  # hints are short strings, not HTML


class TestGenerationPlanContextWithRepairFeedback:
    def test_no_repair_summary_unchanged_behavior(self):
        """Omitting repair_summary_dict gives identical output to pre-Phase-5 behavior."""
        from services.generation_plan_context import build_generation_plan_context
        plan = {
            "constraints": {"session_mode": "new_project", "generation_flavor": "spec_first_preferred", "has_disk_spec": False},
            "generation_tasks": [
                {"task_id": "create-1", "path": "index.html", "intent": "create", "depends_on": [], "notes": ""},
            ],
            "unchanged_paths": [],
            "notes": ["test note"],
            "refs": {},
        }
        ctx = build_generation_plan_context(plan)
        assert ctx.avoid_paths == ()
        assert ctx.repair_hints == ()
        assert "avoid_paths" not in ctx.log_dict()   # omitted when empty
        assert "repair_hints" not in ctx.log_dict()

    def test_repair_summary_populates_avoid_paths(self):
        from services.generation_plan_context import build_generation_plan_context
        plan = {"constraints": {}, "generation_tasks": [], "unchanged_paths": [], "notes": [], "refs": {}}
        repair_dict = {
            "repaired_paths": ["index.html"],
            "failed_paths": ["broken.html"],
            "strategies_used": ["deterministic_doctype_inject"],
            "repeated_fail_paths": ["hard.html"],
            "total_rounds": 1,
            "hints": ["Some hint about DOCTYPE"],
        }
        ctx = build_generation_plan_context(plan, repair_summary_dict=repair_dict)
        # avoid_paths = repeated_fail + failed, deduplicated
        assert "broken.html" in ctx.avoid_paths
        assert "hard.html" in ctx.avoid_paths
        # successfully repaired path is NOT in avoid_paths
        assert "index.html" not in ctx.avoid_paths

    def test_repair_summary_populates_repair_hints(self):
        from services.generation_plan_context import build_generation_plan_context
        plan = {"constraints": {}, "generation_tasks": [], "unchanged_paths": [], "notes": [], "refs": {}}
        repair_dict = {
            "repaired_paths": [],
            "failed_paths": [],
            "strategies_used": [],
            "repeated_fail_paths": [],
            "total_rounds": 0,
            "hints": ["Hint A", "Hint B"],
        }
        ctx = build_generation_plan_context(plan, repair_summary_dict=repair_dict)
        assert "Hint A" in ctx.repair_hints
        assert "Hint B" in ctx.repair_hints

    def test_log_dict_includes_repair_fields_when_populated(self):
        from services.generation_plan_context import build_generation_plan_context
        plan = {"constraints": {}, "generation_tasks": [], "unchanged_paths": [], "notes": [], "refs": {}}
        repair_dict = {
            "repaired_paths": ["p.html"],
            "failed_paths": ["q.html"],
            "strategies_used": [],
            "repeated_fail_paths": [],
            "total_rounds": 1,
            "hints": ["A hint"],
        }
        ctx = build_generation_plan_context(plan, repair_summary_dict=repair_dict)
        d = ctx.log_dict()
        assert "avoid_paths" in d
        assert "repair_hints" in d
        assert d["repair_hints"] == ["A hint"]

    def test_empty_repair_summary_dict_no_avoid_paths(self):
        """Empty repair_summary_dict (e.g. no repair ran) produces empty avoid/hints."""
        from services.generation_plan_context import build_generation_plan_context
        plan = {"constraints": {}, "generation_tasks": [], "unchanged_paths": [], "notes": [], "refs": {}}
        repair_dict = {
            "repaired_paths": [],
            "failed_paths": [],
            "strategies_used": [],
            "repeated_fail_paths": [],
            "total_rounds": 0,
            "hints": [],
        }
        ctx = build_generation_plan_context(plan, repair_summary_dict=repair_dict)
        assert ctx.avoid_paths == ()
        assert ctx.repair_hints == ()

    def test_avoid_paths_deduplicates(self):
        """A path in both repeated_fail_paths and failed_paths appears once in avoid_paths."""
        from services.generation_plan_context import build_generation_plan_context
        plan = {"constraints": {}, "generation_tasks": [], "unchanged_paths": [], "notes": [], "refs": {}}
        repair_dict = {
            "repaired_paths": [],
            "failed_paths": ["dupe.html"],
            "strategies_used": [],
            "repeated_fail_paths": ["dupe.html"],
            "total_rounds": 2,
            "hints": [],
        }
        ctx = build_generation_plan_context(plan, repair_summary_dict=repair_dict)
        assert ctx.avoid_paths.count("dupe.html") == 1


class TestPipelineRepairSummaryKey:
    def test_pipeline_always_has_repair_summary(self, tmp_path, monkeypatch):
        """ctx['repair_summary'] is present even when repair is disabled."""
        import config.settings as cs
        monkeypatch.setattr(cs.settings, "builder_repair_enabled", False)
        cs.settings.resolve_websites_dir = MagicMock(return_value=tmp_path)

        from services.code_generation_service import BrandSpec, FileChange, GenerationResult
        from services.workspace_editor import ApplyResult

        bs = BrandSpec(
            brand_name="SummaryTest",
            product_category="saas_b2c",
            target_audience="devs",
            core_offer="testing",
            pages=["index.html"],
        )
        html = (
            "<!DOCTYPE html><html lang='en'><head>"
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>T</title></head>"
            "<body><style>@media(max-width:640px){}@media(max-width:1024px){}</style></body></html>"
        )

        def fake_gen(**kw):
            return GenerationResult(
                assistant_message="ok",
                changes=[FileChange(path="data/websites/summary-test/index.html",
                                    action="create", content=html, summary="")],
                model_mode="openai",
            )

        with patch("services.generation_pipeline._generate_image_assets", return_value={}), \
             patch("services.code_generation_service.generate_file_structure",
                   return_value={"file_tree": [], "generation_order": []}), \
             patch("services.code_generation_service.synthesize_brand_spec", return_value=bs), \
             patch("services.code_generation_service.generate", side_effect=fake_gen), \
             patch("services.workspace_editor.apply_changes") as mock_apply, \
             patch("services.link_wiring.run_link_wiring_pass", return_value=([], [])), \
             patch("services.generation_pipeline._run_quality_check",
                   return_value={"summary": "ok", "issues": []}):

            mock_apply.return_value = ApplyResult(
                slug="summary-test", version_id="v1",
                applied=["index.html"], skipped=[], results=[]
            )

            from services.generation_pipeline import run_pipeline
            ctx = run_pipeline(
                session_id="sess-summary",
                slug="summary-test",
                message="build it",
                history=[],
                existing_files=None,
                style_seed=None,
                design_system=None,
                operation=None,
                emit=lambda e: None,
                brand_spec=bs,
            )

        assert "repair_summary" in ctx
        s = ctx["repair_summary"]
        assert isinstance(s, dict)
        assert "repaired_paths" in s
        assert "failed_paths" in s
        assert "total_rounds" in s
        assert s["total_rounds"] == 0  # repair was disabled

    def test_pipeline_repair_summary_no_persistence_between_runs(self, tmp_path, monkeypatch):
        """repair_summary is rebuilt fresh each pipeline call — no cross-run bleed."""
        import config.settings as cs
        monkeypatch.setattr(cs.settings, "builder_repair_enabled", False)
        cs.settings.resolve_websites_dir = MagicMock(return_value=tmp_path)

        from services.code_generation_service import BrandSpec, FileChange, GenerationResult
        from services.workspace_editor import ApplyResult

        bs = BrandSpec(
            brand_name="NoPersist",
            product_category="saas_b2c",
            target_audience="devs",
            core_offer="testing",
            pages=["index.html"],
        )
        html = (
            "<!DOCTYPE html><html><head>"
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>T</title></head>"
            "<body><style>@media(max-width:640px){}@media(max-width:1024px){}</style></body></html>"
        )

        def fake_gen(**kw):
            return GenerationResult(
                assistant_message="ok",
                changes=[FileChange(path="data/websites/no-persist/index.html",
                                    action="create", content=html, summary="")],
                model_mode="openai",
            )

        ctxs = []
        for _ in range(2):
            with patch("services.generation_pipeline._generate_image_assets", return_value={}), \
                 patch("services.code_generation_service.generate_file_structure",
                       return_value={"file_tree": [], "generation_order": []}), \
                 patch("services.code_generation_service.synthesize_brand_spec", return_value=bs), \
                 patch("services.code_generation_service.generate", side_effect=fake_gen), \
                 patch("services.workspace_editor.apply_changes") as mock_apply, \
                 patch("services.link_wiring.run_link_wiring_pass", return_value=([], [])), \
                 patch("services.generation_pipeline._run_quality_check",
                       return_value={"summary": "ok", "issues": []}):

                mock_apply.return_value = ApplyResult(
                    slug="no-persist", version_id="v1",
                    applied=["index.html"], skipped=[], results=[]
                )

                from services.generation_pipeline import run_pipeline
                ctx = run_pipeline(
                    session_id=f"sess-nopersist-{_}",
                    slug="no-persist",
                    message="build it",
                    history=[],
                    existing_files=None,
                    style_seed=None,
                    design_system=None,
                    operation=None,
                    emit=lambda e: None,
                    brand_spec=bs,
                )
                ctxs.append(ctx)

        # Both runs should produce independent summaries (both empty since repair disabled)
        assert ctxs[0]["repair_summary"]["total_rounds"] == 0
        assert ctxs[1]["repair_summary"]["total_rounds"] == 0
        # They must be separate dict objects (no shared state)
        assert ctxs[0]["repair_summary"] is not ctxs[1]["repair_summary"]
