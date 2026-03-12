"""
Tests for the DB-backed chat memory system and new API endpoints.

Coverage:
  TestChatDB            — DB helpers: upsert, append, get_history, list_sessions
  TestWorkspaceEditor   — path validation, apply_changes, version backup
  TestCodeGenService    — changes[] schema, template fallback, iterative edit
  TestChatAPIEndpoints  — /website/chat (DB round-trip), /website/sessions,
                          /website/session/{id}/history
"""

import json
import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ===========================================================================
# Shared fixtures
# ===========================================================================


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("CEOCLAW_DATABASE_PATH", str(tmp_path / "mem_test.db"))
    import config.settings as cs
    cs.settings = cs.Settings()
    from data.database import init_db
    init_db()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CEOCLAW_DATABASE_PATH", str(tmp_path / "mem_test.db"))
    import config.settings as cs
    cs.settings = cs.Settings()
    from api.server import app
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c


# ===========================================================================
# TestChatDB
# ===========================================================================


class TestChatDB:
    def test_upsert_creates_session(self):
        from data.database import get_chat_session, upsert_chat_session
        sid = str(uuid.uuid4())
        upsert_chat_session(sid, slug="my-app", product_name="My App")
        row = get_chat_session(sid)
        assert row is not None
        assert row["slug"] == "my-app"
        assert row["product_name"] == "My App"

    def test_upsert_is_idempotent(self):
        from data.database import get_chat_session, upsert_chat_session
        sid = str(uuid.uuid4())
        upsert_chat_session(sid, slug="v1")
        upsert_chat_session(sid, slug="v2")
        row = get_chat_session(sid)
        assert row["slug"] == "v2"

    def test_append_message_creates_session_implicitly(self):
        from data.database import append_chat_message, get_chat_history, get_chat_session
        sid = str(uuid.uuid4())
        append_chat_message(sid, "user", "Hello world")
        session = get_chat_session(sid)
        assert session is not None
        history = get_chat_history(sid)
        assert len(history) == 1
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "Hello world"

    def test_history_order_is_insertion_order(self):
        from data.database import append_chat_message, get_chat_history
        sid = str(uuid.uuid4())
        for i in range(5):
            role = "user" if i % 2 == 0 else "assistant"
            append_chat_message(sid, role, f"msg {i}")
        history = get_chat_history(sid)
        assert [m["content"] for m in history] == [f"msg {i}" for i in range(5)]

    def test_history_limit_respected(self):
        from data.database import append_chat_message, get_chat_history
        sid = str(uuid.uuid4())
        for i in range(10):
            append_chat_message(sid, "user", f"msg {i}")
        history = get_chat_history(sid, limit=3)
        # Should return the FIRST 3 (oldest-first)
        assert len(history) == 3
        assert history[0]["content"] == "msg 0"

    def test_list_sessions_returns_newest_first(self):
        from data.database import append_chat_message, list_chat_sessions, upsert_chat_session
        sid1, sid2 = str(uuid.uuid4()), str(uuid.uuid4())
        upsert_chat_session(sid1, slug="first")
        upsert_chat_session(sid2, slug="second")
        # Touch sid1 after sid2
        append_chat_message(sid1, "user", "hi")
        sessions = list_chat_sessions(limit=10)
        session_ids = [s["session_id"] for s in sessions]
        assert session_ids.index(sid1) < session_ids.index(sid2)

    def test_list_sessions_includes_message_count(self):
        from data.database import append_chat_message, list_chat_sessions, upsert_chat_session
        sid = str(uuid.uuid4())
        upsert_chat_session(sid, slug="x")
        append_chat_message(sid, "user", "a")
        append_chat_message(sid, "assistant", "b")
        sessions = list_chat_sessions()
        match = next((s for s in sessions if s["session_id"] == sid), None)
        assert match is not None
        assert match["message_count"] == 2

    def test_history_persists_across_separate_calls(self):
        """Simulates page reload: separate DB calls still return full history."""
        from data.database import append_chat_message, get_chat_history
        sid = str(uuid.uuid4())
        append_chat_message(sid, "user", "first message")
        append_chat_message(sid, "assistant", "first reply")
        # Simulate reload — fresh call
        history = get_chat_history(sid, limit=100)
        assert len(history) == 2
        assert history[0]["content"] == "first message"
        assert history[1]["content"] == "first reply"


# ===========================================================================
# TestWorkspaceEditor
# ===========================================================================


class TestWorkspaceEditor:
    def _make_change(self, path, content, action="create"):
        from services.code_generation_service import FileChange
        return FileChange(path=path, action=action, content=content, summary="test")

    def test_valid_html_applied(self, tmp_path):
        import config.settings as cs
        cs.settings = MagicMock()
        cs.settings.resolve_websites_dir.return_value = tmp_path

        with patch("services.file_persistence.settings", cs.settings):
            from services.workspace_editor import apply_changes
            change = self._make_change(
                "data/websites/my-app/index.html",
                "<!DOCTYPE html><html><body>Hi</body></html>",
            )
            result = apply_changes("my-app", [change])

        assert "index.html" in result.applied
        assert (tmp_path / "my-app" / "index.html").exists()

    def test_path_traversal_rejected(self, tmp_path):
        import config.settings as cs
        cs.settings = MagicMock()
        cs.settings.resolve_websites_dir.return_value = tmp_path

        with patch("services.file_persistence.settings", cs.settings):
            from services.workspace_editor import apply_changes
            change = self._make_change(
                "data/websites/../../../etc/passwd",
                "<!DOCTYPE html><html></html>",
            )
            result = apply_changes("my-app", [change])

        assert not result.applied
        assert any(r.status == "rejected" for r in result.results)

    def test_disallowed_extension_rejected(self, tmp_path):
        import config.settings as cs
        cs.settings = MagicMock()
        cs.settings.resolve_websites_dir.return_value = tmp_path

        with patch("services.file_persistence.settings", cs.settings):
            from services.workspace_editor import apply_changes
            change = self._make_change(
                "data/websites/my-app/exploit.sh",
                "rm -rf /",
            )
            result = apply_changes("my-app", [change])

        assert not result.applied
        assert any(r.status == "rejected" for r in result.results)

    def test_invalid_html_not_written(self, tmp_path):
        import config.settings as cs
        cs.settings = MagicMock()
        cs.settings.resolve_websites_dir.return_value = tmp_path

        with patch("services.file_persistence.settings", cs.settings):
            from services.workspace_editor import apply_changes
            change = self._make_change(
                "data/websites/my-app/index.html",
                "This is not HTML at all",
            )
            result = apply_changes("my-app", [change])

        assert "index.html" not in result.applied
        assert not (tmp_path / "my-app" / "index.html").exists()

    def test_multiple_files_applied_together(self, tmp_path):
        import config.settings as cs
        cs.settings = MagicMock()
        cs.settings.resolve_websites_dir.return_value = tmp_path

        with patch("services.file_persistence.settings", cs.settings):
            from services.workspace_editor import apply_changes
            changes = [
                self._make_change(
                    "data/websites/x/index.html",
                    "<!DOCTYPE html><html><body>Landing</body></html>",
                ),
                self._make_change(
                    "data/websites/x/app.html",
                    "<!DOCTYPE html><html><body>App</body></html>",
                ),
            ]
            result = apply_changes("x", changes)

        assert set(result.applied) == {"index.html", "app.html"}

    def test_version_backup_created(self, tmp_path):
        import config.settings as cs
        cs.settings = MagicMock()
        cs.settings.resolve_websites_dir.return_value = tmp_path

        # Pre-create file
        (tmp_path / "my-app").mkdir()
        (tmp_path / "my-app" / "index.html").write_text(
            "<!DOCTYPE html><html><body>v1</body></html>"
        )

        with patch("services.file_persistence.settings", cs.settings):
            from services.workspace_editor import apply_changes
            change = self._make_change(
                "data/websites/my-app/index.html",
                "<!DOCTYPE html><html><body>v2</body></html>",
                action="update",
            )
            apply_changes("my-app", [change])

        versions_dir = tmp_path / "my-app" / "versions"
        assert versions_dir.exists()
        assert any(versions_dir.iterdir())


# ===========================================================================
# TestCodeGenService
# ===========================================================================


class TestCodeGenService:
    def _llm_response(self, slug="test-app", product_name="TestApp"):
        html = (
            f"<!DOCTYPE html><html><head><title>{product_name}</title>"
            f"<style>body{{margin:0}}</style></head>"
            f"<body><h1>{product_name}</h1></body></html>"
        )
        return json.dumps({
            "assistant_message": f"Built {product_name}.",
            "changes": [
                {
                    "path": f"data/websites/{slug}/index.html",
                    "action": "create",
                    "content": html,
                    "summary": "Created landing page",
                }
            ],
            "preview": {"primary_route": f"/websites/{slug}/index", "notes": []},
        })

    def test_llm_success_returns_changes(self):
        from services.provider_router import LLMResult
        mock_result = LLMResult(
            content=self._llm_response("my-app", "MyApp"),
            provider="openai",
            model_mode="openai",
        )
        with patch("services.code_generation_service.call_llm", return_value=mock_result):
            from services.code_generation_service import generate
            result = generate(
                slug="my-app",
                user_message="Build me MyApp",
                history=[],
            )

        assert result.changes
        assert result.changes[0].path == "data/websites/my-app/index.html"
        assert "MyApp" in result.changes[0].content
        assert result.provider == "openai"

    def test_prompt_a_differs_from_prompt_b(self):
        """Different prompts yield different generated paths/product names."""
        from services.provider_router import LLMResult

        result_a_content = self._llm_response("fitness-tracker", "FitTrack")
        result_b_content = self._llm_response("recipe-app", "RecipeBox")

        call_count = {"n": 0}
        responses = [result_a_content, result_b_content]

        def rotate(_):
            r = LLMResult(content=responses[call_count["n"] % 2],
                          provider="openai", model_mode="openai")
            call_count["n"] += 1
            return r

        with patch("services.code_generation_service.call_llm", side_effect=rotate):
            from services.code_generation_service import generate
            r_a = generate(slug="fitness-tracker", user_message="Build a fitness tracker", history=[])
            r_b = generate(slug="recipe-app", user_message="Build a recipe app", history=[])

        assert r_a.changes[0].path != r_b.changes[0].path

    def test_template_fallback_when_no_llm(self):
        from services.provider_router import _mock_response
        with patch("services.code_generation_service.call_llm", return_value=_mock_response()):
            from services.code_generation_service import generate
            result = generate(
                slug="my-app",
                user_message="Build a task manager for teams",
                history=[],
            )

        assert result.changes
        assert result.model_mode == "mock"

    def test_iterative_edit_passes_existing_files(self):
        existing = {
            "index.html": "<!DOCTYPE html><html><body>v1</body></html>"
        }
        captured = {}

        def fake_call(messages, **kw):
            captured["messages"] = messages
            from services.provider_router import _mock_response
            return _mock_response()

        with patch("services.code_generation_service.call_llm", side_effect=fake_call):
            from services.code_generation_service import generate
            generate(
                slug="my-app",
                user_message="Add dark mode",
                history=[{"role": "user", "content": "Build it"},
                          {"role": "assistant", "content": "Built it."}],
                existing_files=existing,
            )

        # Last user message contains the current turn (with existing HTML appended)
        user_msgs = [m for m in captured["messages"] if m["role"] == "user"]
        last_user_msg = user_msgs[-1]
        assert "v1" in last_user_msg["content"]  # existing HTML included in current turn

    def test_mock_mode_skips_llm(self):
        with patch("services.code_generation_service.call_llm") as mock_call:
            from services.code_generation_service import generate
            generate(slug="x", user_message="Build something", history=[], mock_mode=True)
        mock_call.assert_not_called()

    def test_malformed_json_falls_back_to_template(self):
        from services.provider_router import LLMResult
        bad = LLMResult(content="I cannot do that sorry.", provider="openai", model_mode="openai")
        with patch("services.code_generation_service.call_llm", return_value=bad):
            from services.code_generation_service import generate
            result = generate(slug="x", user_message="Build a dashboard", history=[])

        assert result.changes  # template fallback
        assert result.model_mode == "openai"

    def test_raw_html_wrapped_as_change(self):
        from services.code_generation_service import _parse_response
        raw_html = "<!DOCTYPE html><html><body>Hello</body></html>"
        parsed = _parse_response(raw_html)
        assert parsed.get("changes")
        assert parsed["changes"][0]["content"] == raw_html


# ===========================================================================
# TestChatAPIEndpoints
# ===========================================================================


class TestChatAPIEndpoints:
    def _mock_gen(self, slug="test-app"):
        from services.code_generation_service import FileChange, GenerationResult
        return GenerationResult(
            assistant_message="Built it.",
            changes=[FileChange(
                path=f"data/websites/{slug}/index.html",
                action="create",
                content="<!DOCTYPE html><html><body>Test</body></html>",
                summary="Created page",
            )],
            preview_route=f"/websites/{slug}/index",
            provider="openai",
            model_mode="openai",
        )

    def test_chat_persists_to_db(self, client, tmp_path, monkeypatch):
        import config.settings as cs
        cs.settings.resolve_websites_dir = lambda: tmp_path

        sid = str(uuid.uuid4())

        with patch("services.code_generation_service.generate", return_value=self._mock_gen()):
            with patch("services.file_persistence.settings") as ms:
                ms.resolve_websites_dir.return_value = tmp_path
                resp = client.post("/website/chat", json={
                    "session_id": sid,
                    "message": "Build a calorie counter for athletes",
                })

        assert resp.status_code == 200

        # Verify history was saved
        from data.database import get_chat_history
        history = get_chat_history(sid)
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "assistant"

    def test_history_survives_restart(self, client, tmp_path, monkeypatch):
        """DB history is available across separate test calls (simulating restart)."""
        import config.settings as cs
        cs.settings.resolve_websites_dir = lambda: tmp_path
        sid = str(uuid.uuid4())

        with patch("services.code_generation_service.generate", return_value=self._mock_gen()):
            with patch("services.file_persistence.settings") as ms:
                ms.resolve_websites_dir.return_value = tmp_path
                client.post("/website/chat", json={"session_id": sid, "message": "Build it"})

        # Separate read
        resp = client.get(f"/website/session/{sid}/history")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["messages"]) == 2

    def test_iterative_call_passes_db_history(self, tmp_path, monkeypatch):
        import config.settings as cs
        cs.settings.resolve_websites_dir = lambda: tmp_path

        from data.database import append_chat_message, upsert_chat_session
        sid = str(uuid.uuid4())
        upsert_chat_session(sid, slug="test-app")
        append_chat_message(sid, "user", "Build me a thing")
        append_chat_message(sid, "assistant", "Built it.")

        # Create existing index.html
        (tmp_path / "test-app").mkdir()
        (tmp_path / "test-app" / "index.html").write_text(
            "<!DOCTYPE html><html><body>Existing</body></html>"
        )

        captured = {}
        def fake_gen(slug, user_message, history, existing_files=None, mock_mode=False):
            captured["history"] = history
            captured["existing_files"] = existing_files
            return self._mock_gen(slug)

        from api.server import app
        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            with patch("services.code_generation_service.generate", side_effect=fake_gen):
                with patch("services.file_persistence.settings") as ms:
                    ms.resolve_websites_dir.return_value = tmp_path
                    c.post("/website/chat", json={"session_id": sid, "message": "Add dark mode"})

        assert len(captured["history"]) == 2  # existing 2 messages loaded from DB
        assert captured["existing_files"]  # existing HTML passed

    def test_sessions_endpoint(self, client, tmp_path, monkeypatch):
        import config.settings as cs
        cs.settings.resolve_websites_dir = lambda: tmp_path

        with patch("services.code_generation_service.generate", return_value=self._mock_gen()):
            with patch("services.file_persistence.settings") as ms:
                ms.resolve_websites_dir.return_value = tmp_path
                sid = str(uuid.uuid4())
                client.post("/website/chat", json={"session_id": sid, "message": "Build something"})

        resp = client.get("/website/sessions")
        assert resp.status_code == 200
        sessions = resp.json()
        assert any(s["session_id"] == sid for s in sessions)

    def test_session_history_endpoint(self, client, tmp_path, monkeypatch):
        import config.settings as cs
        cs.settings.resolve_websites_dir = lambda: tmp_path

        with patch("services.code_generation_service.generate", return_value=self._mock_gen()):
            with patch("services.file_persistence.settings") as ms:
                ms.resolve_websites_dir.return_value = tmp_path
                sid = str(uuid.uuid4())
                client.post("/website/chat", json={"session_id": sid, "message": "Build it"})

        resp = client.get(f"/website/session/{sid}/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == sid
        assert len(data["messages"]) >= 2

    def test_session_history_404_for_unknown(self, client):
        resp = client.get("/website/session/does-not-exist-xyz/history")
        assert resp.status_code == 404

    def test_empty_message_returns_400(self, client):
        resp = client.post("/website/chat", json={"session_id": "x", "message": ""})
        assert resp.status_code == 400

    def test_response_includes_changes_summary(self, client, tmp_path, monkeypatch):
        import config.settings as cs
        cs.settings.resolve_websites_dir = lambda: tmp_path

        with patch("services.code_generation_service.generate", return_value=self._mock_gen()):
            with patch("services.file_persistence.settings") as ms:
                ms.resolve_websites_dir.return_value = tmp_path
                resp = client.post("/website/chat", json={
                    "session_id": str(uuid.uuid4()),
                    "message": "Build a todo app",
                })

        assert resp.status_code == 200
        data = resp.json()
        assert "changes" in data
        assert "files_applied" in data
        assert "model" in data
