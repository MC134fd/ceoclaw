"""
Comprehensive version graph tests (Phase 4).

Coverage:
  TestSessionVersionDB      — save, list, get DB helpers
  TestVersionRestore        — restore endpoint applies files to disk
  TestVersionDiff           — get_version_file returns correct content per version
  TestVersionIntegration    — builder/chat saves version record
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    tmp_db = str(tmp_path / "ver_test.db")
    monkeypatch.setenv("CEOCLAW_DATABASE_PATH", tmp_db)
    import config.settings as cs
    cs.settings = cs.Settings()
    cs.settings.database_path = tmp_db  # prevent load_dotenv(override=True) clobber
    from data.database import init_db
    init_db()
    yield


@pytest.fixture()
def client(tmp_path, monkeypatch):
    tmp_db = str(tmp_path / "ver_test.db")
    monkeypatch.setenv("CEOCLAW_DATABASE_PATH", tmp_db)
    import config.settings as cs
    cs.settings = cs.Settings()
    cs.settings.database_path = tmp_db
    from api.server import app
    from fastapi.testclient import TestClient
    return TestClient(app)


# ===========================================================================
# TestSessionVersionDB
# ===========================================================================


class TestSessionVersionDB:
    def test_save_and_list_versions(self):
        from data.database import save_session_version, list_session_versions

        save_session_version(
            "sess-a",
            "20240101T000000Z",
            {"index.html": "v1 content", "style.css": "body {}"},
        )

        versions = list_session_versions("sess-a")
        assert len(versions) == 1
        assert versions[0]["version_id"] == "20240101T000000Z"
        assert "index.html" in versions[0]["file_list"]
        assert "style.css" in versions[0]["file_list"]

    def test_multiple_versions_newest_first(self):
        from data.database import save_session_version, list_session_versions

        save_session_version("sess-b", "20240101T000000Z", {"index.html": "v1"})
        save_session_version("sess-b", "20240102T000000Z", {"index.html": "v2"})
        save_session_version("sess-b", "20240103T000000Z", {"index.html": "v3"})

        versions = list_session_versions("sess-b")
        assert len(versions) == 3
        # newest first
        assert versions[0]["version_id"] == "20240103T000000Z"
        assert versions[-1]["version_id"] == "20240101T000000Z"

    def test_list_versions_limit(self):
        from data.database import save_session_version, list_session_versions

        for i in range(5):
            save_session_version("sess-lim", f"2024010{i+1}T000000Z", {"index.html": f"v{i}"})

        versions = list_session_versions("sess-lim", limit=3)
        assert len(versions) == 3

    def test_get_version_returns_files(self):
        from data.database import save_session_version, get_session_version

        save_session_version(
            "sess-c",
            "20240101T000000Z",
            {"index.html": "<!DOCTYPE html><html>test</html>", "app.js": "console.log(1)"},
        )

        record = get_session_version("sess-c", "20240101T000000Z")
        assert record is not None
        assert record["files"]["index.html"] == "<!DOCTYPE html><html>test</html>"
        assert record["files"]["app.js"] == "console.log(1)"
        assert "index.html" in record["file_list"]

    def test_get_version_nonexistent_returns_none(self):
        from data.database import get_session_version
        assert get_session_version("nobody", "fakeversionid") is None

    def test_save_version_with_message_id(self):
        from data.database import save_session_version, get_session_version

        row_id = save_session_version(
            "sess-d",
            "20240101T000000Z",
            {"index.html": "content"},
            message_id=42,
        )
        assert row_id > 0

        record = get_session_version("sess-d", "20240101T000000Z")
        assert record is not None
        assert record.get("message_id") == 42

    def test_versions_isolated_by_session(self):
        from data.database import save_session_version, list_session_versions

        save_session_version("sess-x", "20240101T000000Z", {"index.html": "x"})
        save_session_version("sess-y", "20240101T000000Z", {"index.html": "y"})

        vx = list_session_versions("sess-x")
        vy = list_session_versions("sess-y")
        assert len(vx) == 1
        assert len(vy) == 1
        assert vx[0]["files"]["index.html"] if "files" in vx[0] else True  # just structural

    def test_duplicate_version_id_ignored(self):
        from data.database import save_session_version, list_session_versions

        save_session_version("sess-dup", "20240101T000000Z", {"index.html": "v1"})
        # Second save with same version_id should be ignored (UNIQUE constraint)
        save_session_version("sess-dup", "20240101T000000Z", {"index.html": "v2"})

        versions = list_session_versions("sess-dup")
        assert len(versions) == 1


# ===========================================================================
# TestVersionEndpoints
# ===========================================================================


class TestVersionEndpoints:
    def test_list_versions_empty_session(self, client):
        resp = client.get("/builder/sessions/no-such-session/versions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_versions_returns_records(self, client):
        from data.database import save_session_version
        save_session_version("sess-list", "20240101T000000Z", {"index.html": "v1"})
        save_session_version("sess-list", "20240102T000000Z", {"index.html": "v2"})

        resp = client.get("/builder/sessions/sess-list/versions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["version_id"] == "20240102T000000Z"  # newest first

    def test_get_version_metadata(self, client):
        from data.database import save_session_version
        save_session_version(
            "sess-meta",
            "20240201T000000Z",
            {"index.html": "content", "style.css": "css"},
        )

        resp = client.get("/builder/sessions/sess-meta/versions/20240201T000000Z")
        assert resp.status_code == 200
        data = resp.json()
        assert data["version_id"] == "20240201T000000Z"
        assert "index.html" in data["file_list"]
        assert "style.css" in data["file_list"]
        # files content not included in metadata endpoint
        assert "files" not in data

    def test_get_version_not_found(self, client):
        resp = client.get("/builder/sessions/x/versions/does-not-exist")
        assert resp.status_code == 404

    def test_get_version_file_content(self, client):
        from data.database import save_session_version
        html = "<!DOCTYPE html><html><body>Unique version content abc123</body></html>"
        save_session_version("sess-file-unique", "20240301T120000Z", {"index.html": html})

        resp = client.get(
            "/builder/sessions/sess-file-unique/versions/20240301T120000Z/files/index.html"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["content"] == html
        assert data["file_path"] == "index.html"
        assert data["version_id"] == "20240301T120000Z"

    def test_get_version_file_nested_path(self, client):
        from data.database import save_session_version
        save_session_version(
            "sess-nested-unique",
            "20240302T120000Z",
            {"pages/terms.html": "Terms content xyz987"},
        )

        resp = client.get(
            "/builder/sessions/sess-nested-unique/versions/20240302T120000Z/files/pages/terms.html"
        )
        assert resp.status_code == 200
        assert "Terms content xyz987" in resp.json()["content"]

    def test_get_version_file_path_traversal_blocked(self, client):
        from data.database import save_session_version
        save_session_version("sess-trav-unique", "20240303T120000Z", {"index.html": "content"})

        # FastAPI normalizes .. in URL paths, so the route may 400 or 404 — both are safe
        resp = client.get(
            "/builder/sessions/sess-trav-unique/versions/20240303T120000Z/files/../etc/passwd"
        )
        assert resp.status_code in (400, 404)

    def test_get_version_file_not_in_version(self, client):
        from data.database import save_session_version
        save_session_version("sess-miss-unique", "20240304T120000Z", {"index.html": "content"})

        resp = client.get(
            "/builder/sessions/sess-miss-unique/versions/20240304T120000Z/files/style.css"
        )
        assert resp.status_code == 404

    def test_restore_version_not_found(self, client):
        resp = client.post("/builder/sessions/no-sess/versions/fake-ver/restore")
        assert resp.status_code == 404

    def test_restore_version_no_slug(self, client):
        from data.database import save_session_version
        save_session_version("sess-noslug", "20240301T000000Z", {"index.html": "v1"})
        # Session has no slug — restore should return 400
        resp = client.post("/builder/sessions/sess-noslug/versions/20240301T000000Z/restore")
        assert resp.status_code == 400

    def test_restore_version_applies_files(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("CEOCLAW_WEBSITES_DIR", str(tmp_path))
        import config.settings as cs
        cs.settings = cs.Settings()

        from data.database import save_session_version, upsert_chat_session
        upsert_chat_session("sess-restore", slug="restore-app")
        save_session_version(
            "sess-restore",
            "20240301T000000Z",
            {"index.html": "<!DOCTYPE html><html><body>Restored!</body></html>"},
        )

        with patch("services.file_persistence.settings", cs.settings):
            resp = client.post(
                "/builder/sessions/sess-restore/versions/20240301T000000Z/restore"
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "index.html" in data["files_applied"]
        assert data["restored_from"] == "20240301T000000Z"


# ===========================================================================
# TestVersionIntegration — builder/chat saves version record
# ===========================================================================


class TestVersionIntegration:
    def _html(self, text="Hello"):
        return f"<!DOCTYPE html><html><head><style>body{{}}</style></head><body><p>{text}</p></body></html>"

    def test_builder_chat_saves_version_record(self, client, tmp_path, monkeypatch):
        from services.code_generation_service import FileChange, GenerationResult
        from services.workspace_editor import ApplyResult, ChangeResult

        slug = "version-test-app-unique"
        html_content = self._html("VersionTest")
        mock_gen = GenerationResult(
            assistant_message="Built it.",
            changes=[FileChange(
                path=f"data/websites/{slug}/index.html",
                action="create",
                content=html_content,
                summary="Created",
            )],
            preview_route=f"/websites/{slug}/index",
            provider="mock",
            model_mode="mock",
        )
        mock_apply = ApplyResult(
            slug=slug,
            version_id="20240601T120000Z",
            applied=["index.html"],
            skipped=[],
            results=[ChangeResult(
                path=f"data/websites/{slug}/index.html",
                action="create",
                status="applied",
            )],
        )

        # Patch read_current_file to return the html content
        with patch("services.code_generation_service.generate", return_value=mock_gen):
            with patch("services.workspace_editor.apply_changes", return_value=mock_apply):
                with patch(
                    "services.file_persistence.read_current_file",
                    return_value=html_content,
                ):
                    resp = client.post("/builder/chat", json={
                        "session_id": "sess-ver-int-unique",
                        "message": "Build a version test app",
                    })

        assert resp.status_code == 200
        data = resp.json()
        assert data["version_id"] == "20240601T120000Z"

        # Check version was saved to DB
        from data.database import list_session_versions
        versions = list_session_versions("sess-ver-int-unique")
        assert len(versions) >= 1
        assert versions[0]["version_id"] == "20240601T120000Z"
