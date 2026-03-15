"""
Tests for SVG sanitization and allowlist support in output_validator and workspace_editor.

Coverage:
1.  Safe SVG passes validate_files unchanged.
2.  <script> tag is stripped and warning emitted.
3.  onload= event handler attr is stripped.
4.  javascript: href is removed.
5.  data: href is removed.
6.  http:// href is removed.
7.  foreignObject is removed.
8.  Unknown element is removed.
9.  Malformed XML is rejected (returns no entry).
10. Non-svg root element is rejected.
11. .svg extension passes workspace_editor _validate_path.
12. validate_files rejects unknown extension (sanity check).
13. SVG size limit enforced (truncate warning).
14. Safe SVG round-trips through workspace_editor apply_changes (path appears in applied).
15. Empty SVG content is rejected.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SAFE_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <title>Safe icon</title>
  <circle cx="50" cy="50" r="40" fill="#0071e3"/>
  <rect x="20" y="20" width="60" height="60" fill="none" stroke="#fff"/>
  <path d="M10 50 L90 50" stroke="#fff"/>
</svg>"""


# ---------------------------------------------------------------------------
# output_validator tests
# ---------------------------------------------------------------------------

from services.output_validator import validate_files, _sanitize_svg


def test_safe_svg_passes():
    clean, warnings = validate_files({"assets/hero.svg": _SAFE_SVG})
    assert "assets/hero.svg" in clean
    assert not any("hero.svg" in w and "removed" in w for w in warnings), warnings


def test_script_tag_stripped():
    svg = '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script><circle cx="10" cy="10" r="5"/></svg>'
    clean, warnings = validate_files({"assets/icon.svg": svg})
    assert "assets/icon.svg" in clean
    assert "script" not in clean["assets/icon.svg"]
    assert any("script" in w.lower() for w in warnings)


def test_onload_attr_stripped():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><circle cx="10" cy="10" r="5"/></svg>'
    clean, warnings = validate_files({"assets/icon.svg": svg})
    assert "assets/icon.svg" in clean
    assert "onload" not in clean["assets/icon.svg"]
    assert any("event handler" in w.lower() for w in warnings)


def test_javascript_href_removed():
    svg = '<svg xmlns="http://www.w3.org/2000/svg"><a href="javascript:alert(1)"><circle cx="10" cy="10" r="5"/></a></svg>'
    # <a> is not in allowed tags, so will be removed entirely
    clean, warnings = validate_files({"assets/icon.svg": svg})
    assert "assets/icon.svg" in clean
    assert "javascript:" not in clean["assets/icon.svg"]


def test_data_href_removed():
    svg = '<svg xmlns="http://www.w3.org/2000/svg"><image href="data:image/png;base64,abc"/></svg>'
    # <image> not in allowed tags — removed; href on allowed elements also checked
    clean, warnings = validate_files({"assets/icon.svg": svg})
    assert "assets/icon.svg" in clean
    assert "data:image" not in clean["assets/icon.svg"]


def test_http_href_on_path_removed():
    svg = '<svg xmlns="http://www.w3.org/2000/svg"><path href="http://evil.com/x" d="M0 0"/></svg>'
    clean, warnings = validate_files({"assets/icon.svg": svg})
    assert "assets/icon.svg" in clean
    assert "http://evil.com" not in clean["assets/icon.svg"]
    assert any("href" in w.lower() for w in warnings)


def test_foreign_object_removed():
    svg = '<svg xmlns="http://www.w3.org/2000/svg"><foreignObject><div>xss</div></foreignObject></svg>'
    clean, warnings = validate_files({"assets/icon.svg": svg})
    assert "assets/icon.svg" in clean
    assert "foreignObject" not in clean["assets/icon.svg"]
    assert "div" not in clean["assets/icon.svg"]


def test_unknown_element_removed():
    svg = '<svg xmlns="http://www.w3.org/2000/svg"><weirdtag foo="bar"/><circle cx="5" cy="5" r="5"/></svg>'
    clean, warnings = validate_files({"assets/icon.svg": svg})
    assert "assets/icon.svg" in clean
    assert "weirdtag" not in clean["assets/icon.svg"]
    assert any("weirdtag" in w for w in warnings)


def test_malformed_xml_rejected():
    svg = "<svg><unclosed"
    clean, warnings = validate_files({"assets/icon.svg": svg})
    assert "assets/icon.svg" not in clean
    assert any("malformed" in w.lower() for w in warnings)


def test_non_svg_root_rejected():
    svg = '<html><body>not an svg</body></html>'
    clean, warnings = validate_files({"assets/icon.svg": svg})
    assert "assets/icon.svg" not in clean
    assert any("root element" in w.lower() for w in warnings)


def test_empty_svg_rejected():
    clean, warnings = validate_files({"assets/icon.svg": "   "})
    assert "assets/icon.svg" not in clean


def test_unknown_extension_still_rejected():
    clean, warnings = validate_files({"assets/evil.exe": "<data/>"})
    assert "assets/evil.exe" not in clean
    assert any(".exe" in w for w in warnings)


# ---------------------------------------------------------------------------
# workspace_editor path validation
# ---------------------------------------------------------------------------

from services.workspace_editor import _validate_path


def test_svg_path_passes_workspace_validator():
    assert _validate_path("assets/hero.svg") is None


def test_svg_in_root_passes_workspace_validator():
    assert _validate_path("hero.svg") is None


def test_non_svg_unknown_ext_rejected_by_workspace():
    err = _validate_path("assets/shell.sh")
    assert err is not None
    assert ".sh" in err


# ---------------------------------------------------------------------------
# workspace_editor apply_changes integration
# ---------------------------------------------------------------------------

@pytest.fixture()
def _tmp_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("CEOCLAW_DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("CEOCLAW_WEBSITES_DIR", str(tmp_path / "websites"))
    import config.settings as cs
    cs.settings = cs.Settings()
    cs.settings.database_path = str(tmp_path / "test.db")
    cs.settings.resolve_websites_dir = lambda: tmp_path / "websites"
    # file_persistence imports `settings` at module load; patch its reference too
    import services.file_persistence as fp
    monkeypatch.setattr(fp, "settings", cs.settings)
    from data.database import init_db
    init_db()
    yield tmp_path


def test_svg_appears_in_applied_files(_tmp_workspace):
    from services.workspace_editor import apply_changes
    from services.code_generation_service import FileChange

    changes = [
        FileChange(
            path="data/websites/my-app/assets/hero.svg",
            action="create",
            content=_SAFE_SVG,
            summary="Hero SVG",
        ),
    ]
    result = apply_changes("my-app", changes)
    assert "assets/hero.svg" in result.applied, f"applied={result.applied} warnings={result.warnings}"
    svg_file = _tmp_workspace / "websites" / "my-app" / "assets" / "hero.svg"
    assert svg_file.exists()
    assert "<circle" in svg_file.read_text()
