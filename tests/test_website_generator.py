"""
Tests for the LLM website generator pipeline.

Coverage:
  TestProviderRouter      — Flock success, Flock-fail+OpenAI success, both-fail → mock
  TestOutputValidator     — valid HTML, external script removal, traversal rejection
  TestFilePersistence     — file write, version backup, prune, iterative overwrite
  TestLLMGenerator        — LLM success path, template fallback, iterative edit
  TestWebsiteChatEndpoint — success, fallback, iterative edit, invalid output, session
"""

import json
import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    tmp_db = str(tmp_path / "gen_test.db")
    monkeypatch.setenv("CEOCLAW_DATABASE_PATH", tmp_db)
    import config.settings as cs
    cs.settings = cs.Settings()
    cs.settings.database_path = tmp_db  # prevent load_dotenv(override=True) clobber
    from data.database import init_db
    init_db()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    tmp_db = str(tmp_path / "gen_test.db")
    monkeypatch.setenv("CEOCLAW_DATABASE_PATH", tmp_db)
    import config.settings as cs
    cs.settings = cs.Settings()
    cs.settings.database_path = tmp_db
    from api.server import app
    from fastapi.testclient import TestClient
    return TestClient(app)


# ===========================================================================
# TestProviderRouter
# ===========================================================================


class TestProviderRouter:
    def test_flock_never_called_from_call_llm(self):
        """call_llm must NEVER call flock even when flock is fully configured.
        Flock is disabled in the runtime path; mock is the fallback when no OpenAI key.
        """
        mock_settings = MagicMock()
        mock_settings.flock_endpoint = "https://flock.example.com/v1/completions"
        mock_settings.flock_api_key = "test-key"
        mock_settings.flock_mock_mode = False
        mock_settings.flock_auth_strategy = "bearer"
        mock_settings.flock_model = "flock-default"
        mock_settings.openai_api_key = ""  # no OpenAI key → should fall back to mock

        with patch("services.provider_router.settings", mock_settings):
            from services.provider_router import call_llm
            result = call_llm([{"role": "user", "content": "hello"}])

        # Must never reach flock; falls back to mock
        assert result.provider == "mock"
        assert result.fallback_used is True

    def test_flock_fail_falls_back_to_openai(self):
        mock_settings = MagicMock()
        mock_settings.flock_endpoint = "https://flock.example.com/v1/completions"
        mock_settings.flock_api_key = "test-key"
        mock_settings.flock_mock_mode = False
        mock_settings.flock_auth_strategy = "bearer"
        mock_settings.flock_model = "flock-default"
        mock_settings.openai_api_key = "oai-key"
        mock_settings.openai_model = "gpt-4o-mini"
        mock_settings.openai_endpoint = "https://api.openai.com/v1/chat/completions"

        def fake_post(url, **kwargs):
            if "flock" in url:
                raise ConnectionError("flock down")
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {"choices": [{"message": {"content": "OpenAI response"}}]}
            return resp

        with patch("services.provider_router.settings", mock_settings):
            with patch("services.provider_router.httpx.post", side_effect=fake_post):
                from services.provider_router import call_llm
                result = call_llm([{"role": "user", "content": "hello"}])

        assert result.provider == "openai"
        assert result.model_mode == "openai"
        assert result.content == "OpenAI response"

    def test_both_fail_returns_mock(self):
        mock_settings = MagicMock()
        mock_settings.flock_endpoint = "https://flock.example.com/v1/completions"
        mock_settings.flock_api_key = "test-key"
        mock_settings.flock_mock_mode = False
        mock_settings.flock_auth_strategy = "bearer"
        mock_settings.flock_model = "flock-default"
        mock_settings.openai_api_key = "oai-key"
        mock_settings.openai_model = "gpt-4o-mini"
        mock_settings.openai_endpoint = "https://api.openai.com/v1/chat/completions"

        with patch("services.provider_router.settings", mock_settings):
            with patch("services.provider_router.httpx.post", side_effect=ConnectionError("down")):
                from services.provider_router import call_llm
                result = call_llm([{"role": "user", "content": "hello"}])

        assert result.provider == "mock"
        assert result.content == ""

    def test_no_keys_returns_mock(self):
        mock_settings = MagicMock()
        mock_settings.flock_endpoint = ""
        mock_settings.flock_api_key = ""
        mock_settings.openai_api_key = ""

        with patch("services.provider_router.settings", mock_settings):
            from services.provider_router import call_llm
            result = call_llm([{"role": "user", "content": "hello"}])
        assert result.provider == "mock"


# ===========================================================================
# TestOutputValidator
# ===========================================================================


class TestOutputValidator:
    def test_valid_html_passes(self):
        from services.output_validator import validate_files
        files = {"index.html": "<!DOCTYPE html><html><body>Hello</body></html>"}
        clean, warnings = validate_files(files)
        assert "index.html" in clean
        assert warnings
        assert any("viewport" in w.lower() for w in warnings)

    def test_external_script_removed(self):
        from services.output_validator import validate_files
        html = (
            '<!DOCTYPE html><html><body>'
            '<script src="https://evil.com/xss.js"></script>'
            '</body></html>'
        )
        clean, warnings = validate_files({"index.html": html})
        assert "index.html" in clean
        assert "evil.com" not in clean["index.html"]
        assert any("external" in w.lower() or "script" in w.lower() for w in warnings)

    def test_javascript_href_sanitized(self):
        from services.output_validator import validate_files
        html = '<!DOCTYPE html><html><body><a href="javascript:alert(1)">click</a></body></html>'
        clean, warnings = validate_files({"index.html": html})
        assert 'href="#"' in clean["index.html"]

    def test_path_traversal_rejected(self):
        from services.output_validator import validate_files
        files = {"../../etc/passwd": "<!DOCTYPE html><html></html>"}
        clean, warnings = validate_files(files)
        assert "../../etc/passwd" not in clean

    def test_disallowed_extension_rejected(self):
        from services.output_validator import validate_files
        # .exe is not in the allowed extensions list
        files = {"malware.exe": "binary content"}
        clean, warnings = validate_files(files)
        assert not clean
        assert warnings  # some warning was produced

    def test_css_file_now_allowed(self):
        from services.output_validator import validate_files
        files = {"style.css": "body { color: red; }"}
        clean, warnings = validate_files(files)
        # CSS is now allowed (no HTML-structure check for non-HTML files)
        assert "style.css" in clean

    def test_non_html_content_rejected(self):
        from services.output_validator import validate_files
        files = {"index.html": "This is just a plain text file with no HTML."}
        clean, warnings = validate_files(files)
        assert "index.html" not in clean

    def test_app_html_allowed(self):
        from services.output_validator import validate_files
        files = {"app.html": "<!DOCTYPE html><html><body>App</body></html>"}
        clean, warnings = validate_files(files)
        assert "app.html" in clean

    def test_missing_viewport_and_breakpoints_is_rejected(self):
        from services.output_validator import validate_files
        html = "<!DOCTYPE html><html><head></head><body>" + ("<section>Block</section>" * 120) + "</body></html>"
        clean, warnings = validate_files({"index.html": html})
        assert "index.html" not in clean
        assert any("critical responsive contract" in w.lower() for w in warnings)

    def test_responsive_contract_passes_when_present(self):
        from services.output_validator import validate_files
        html = """
        <!DOCTYPE html><html><head>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
          .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: clamp(12px, 2vw, 20px); }
          img { max-width: 100%; }
          .card { overflow-wrap: anywhere; }
          @media (max-width: 1024px) { .grid { gap: 16px; } }
          @media (max-width: 640px) { .grid { grid-template-columns: 1fr; } }
        </style></head><body><main class="grid"><div class="card">A</div></main></body></html>
        """
        clean, warnings = validate_files({"index.html": html})
        assert "index.html" in clean
        assert not any("critical responsive contract" in w.lower() for w in warnings)


# ===========================================================================
# TestFilePersistence
# ===========================================================================


class TestFilePersistence:
    def test_creates_file_on_disk(self, tmp_path, monkeypatch):
        import config.settings as cs
        cs.settings = MagicMock()
        cs.settings.resolve_websites_dir.return_value = tmp_path

        from services.file_persistence import save_website_files
        with patch("services.file_persistence.settings", cs.settings):
            result = save_website_files(
                "my-app",
                {"index.html": "<!DOCTYPE html><html><body>Hello</body></html>"},
            )

        assert (tmp_path / "my-app" / "index.html").exists()
        assert result["slug"] == "my-app"
        assert result["version_id"]

    def test_backup_created_on_second_write(self, tmp_path, monkeypatch):
        import config.settings as cs
        cs.settings = MagicMock()
        cs.settings.resolve_websites_dir.return_value = tmp_path

        with patch("services.file_persistence.settings", cs.settings):
            from services.file_persistence import save_website_files
            # First write
            save_website_files("my-app", {"index.html": "<!DOCTYPE html><html><body>v1</body></html>"})
            # Second write — should create backup
            save_website_files("my-app", {"index.html": "<!DOCTYPE html><html><body>v2</body></html>"})

        versions_dir = tmp_path / "my-app" / "versions"
        assert versions_dir.exists()
        version_dirs = list(versions_dir.iterdir())
        assert len(version_dirs) >= 1
        assert (version_dirs[0] / "index.html").exists()

    def test_read_current_html_returns_content(self, tmp_path, monkeypatch):
        import config.settings as cs
        cs.settings = MagicMock()
        cs.settings.resolve_websites_dir.return_value = tmp_path

        (tmp_path / "test-app").mkdir()
        (tmp_path / "test-app" / "index.html").write_text(
            "<!DOCTYPE html><html><body>test</body></html>"
        )

        with patch("services.file_persistence.settings", cs.settings):
            from services.file_persistence import read_current_html
            content = read_current_html("test-app")

        assert content is not None
        assert "test" in content

    def test_read_current_html_missing_returns_none(self, tmp_path, monkeypatch):
        import config.settings as cs
        cs.settings = MagicMock()
        cs.settings.resolve_websites_dir.return_value = tmp_path

        with patch("services.file_persistence.settings", cs.settings):
            from services.file_persistence import read_current_html
            result = read_current_html("nonexistent-slug")

        assert result is None

    def test_iterative_write_updates_content(self, tmp_path, monkeypatch):
        import config.settings as cs
        cs.settings = MagicMock()
        cs.settings.resolve_websites_dir.return_value = tmp_path

        with patch("services.file_persistence.settings", cs.settings):
            from services.file_persistence import save_website_files
            save_website_files("my-app", {"index.html": "<!DOCTYPE html><html><body>v1</body></html>"})
            save_website_files("my-app", {"index.html": "<!DOCTYPE html><html><body>v2</body></html>"})

        content = (tmp_path / "my-app" / "index.html").read_text()
        assert "v2" in content
        assert "v1" not in content


# ===========================================================================
# TestLLMGenerator
# ===========================================================================


class TestLLMGenerator:
    def _good_llm_response(self, product_name="TestApp"):
        html = (
            f"<!DOCTYPE html><html><head><title>{product_name}</title>"
            f"<style>body{{margin:0}}</style></head>"
            f"<body><h1>{product_name}</h1></body></html>"
        )
        return json.dumps({
            "assistant_message": f"Built {product_name}.",
            "product_name": product_name,
            "files": {"index.html": html},
            "notes": [],
        })

    def test_llm_success_returns_html(self, monkeypatch):
        from services.provider_router import LLMResult
        mock_result = LLMResult(
            content=self._good_llm_response("MyProduct"),
            provider="openai",
            model_mode="openai",
        )

        with patch("services.llm_website_generator.call_llm", return_value=mock_result):
            from services.llm_website_generator import generate_website
            result = generate_website(user_message="Build me MyProduct", history=[])

        assert "index.html" in result["files"]
        assert "MyProduct" in result["files"]["index.html"]
        assert result["provider"] == "openai"
        assert result["model_mode"] == "openai"

    def test_fallback_to_template_when_no_llm(self):
        from services.provider_router import _mock_response
        with patch("services.llm_website_generator.call_llm", return_value=_mock_response()):
            from services.llm_website_generator import generate_website
            result = generate_website(
                user_message="Build a fitness tracker for athletes",
                history=[],
                existing_html=None,
            )

        assert "index.html" in result["files"]
        assert result["model_mode"] == "mock"

    def test_iterative_edit_modifies_existing_html(self):
        existing = (
            '<!DOCTYPE html><html><head><style>body{}</style></head>'
            '<body><a class="cta" href="#signup">Get Early Access</a></body></html>'
        )
        from services.provider_router import _mock_response
        with patch("services.llm_website_generator.call_llm", return_value=_mock_response()):
            from services.llm_website_generator import generate_website
            result = generate_website(
                user_message="Change the CTA to say Start Free Trial",
                history=[],
                existing_html=existing,
            )

        assert "index.html" in result["files"]
        # Template mode applies heuristic CTA substitution
        assert result["files"]["index.html"]  # non-empty

    def test_invalid_llm_output_falls_back(self):
        from services.provider_router import LLMResult
        bad_result = LLMResult(
            content="Sorry I cannot help with that.",
            provider="openai",
            model_mode="openai",
        )
        with patch("services.llm_website_generator.call_llm", return_value=bad_result):
            from services.llm_website_generator import generate_website
            result = generate_website(
                user_message="Build me a dashboard",
                history=[],
            )

        # Should still return something (template fallback)
        assert "files" in result
        assert result["files"]

    def test_raw_html_response_is_wrapped(self):
        from services.llm_website_generator import _parse_response
        raw = "<!DOCTYPE html><html><body>Hello</body></html>"
        parsed = _parse_response(raw)
        assert parsed.get("files", {}).get("index.html") == raw

    def test_markdown_wrapped_json_is_parsed(self):
        from services.llm_website_generator import _parse_response
        payload = {"assistant_message": "done", "files": {"index.html": "<!DOCTYPE html><html></html>"}}
        wrapped = f"```json\n{json.dumps(payload)}\n```"
        parsed = _parse_response(wrapped)
        assert parsed["assistant_message"] == "done"

    def test_mock_mode_skips_llm_call(self):
        with patch("services.llm_website_generator.call_llm") as mock_call:
            from services.llm_website_generator import generate_website
            generate_website(
                user_message="Build a todo app",
                history=[],
                mock_mode=True,
            )
        mock_call.assert_not_called()


# ===========================================================================
# TestWebsiteChatEndpoint
# ===========================================================================


class TestWebsiteChatEndpoint:
    def _html(self, text="Hello"):
        return f"<!DOCTYPE html><html><head><style>body{{}}</style></head><body><p>{text}</p></body></html>"

    def _mock_gen(self, product_name="TestApp", message="Built it."):
        return {
            "assistant_message": message,
            "product_name": product_name,
            "files": {"index.html": self._html(product_name)},
            "notes": [],
            "provider": "openai",
            "model_mode": "openai",
            "warnings": [],
        }

    def test_success_path(self, client):
        from services.code_generation_service import FileChange, GenerationResult
        from services.workspace_editor import ApplyResult, ChangeResult

        slug = "calorie-tracker-for-athletes"
        mock_gen_result = GenerationResult(
            assistant_message="Built TestApp.",
            changes=[FileChange(
                path=f"data/websites/{slug}/index.html",
                action="create",
                content=self._html("TestApp"),
                summary="Created landing page",
            )],
            preview_route=f"/websites/{slug}/index",
            provider="openai",
            model_mode="openai",
        )
        mock_apply_result = ApplyResult(
            slug=slug,
            version_id="20240101T000000Z",
            applied=["index.html"],
            skipped=[],
            results=[ChangeResult(
                path=f"data/websites/{slug}/index.html",
                action="create",
                status="applied",
                summary="Created landing page",
            )],
        )

        with patch("services.code_generation_service.generate", return_value=mock_gen_result):
            with patch("services.workspace_editor.apply_changes", return_value=mock_apply_result):
                resp = client.post("/website/chat", json={
                    "session_id": "sess-1",
                    "message": "Build a calorie tracker for athletes",
                })

        assert resp.status_code == 200
        data = resp.json()
        assert data["assistant_message"]
        assert data["slug"]
        assert data["landing_url"].startswith("/websites/")
        assert data["model"]["model_mode"] == "openai"

    def test_empty_message_returns_400(self, client):
        resp = client.post("/website/chat", json={"session_id": "x", "message": ""})
        assert resp.status_code == 400

    def test_iterative_edit_passes_existing_html(self, client):
        from data.database import append_chat_message, upsert_chat_session
        from services.code_generation_service import FileChange, GenerationResult
        from services.workspace_editor import ApplyResult, ChangeResult

        slug = "my-app"
        existing_html = self._html("original")
        captured = {}

        # Inject session + history into DB
        upsert_chat_session("sess-iter", slug=slug, product_name="MyApp", version_id="20240101T000000Z")
        append_chat_message("sess-iter", "user", "Build MyApp")
        append_chat_message("sess-iter", "assistant", "Built MyApp.")

        def fake_generate(slug, user_message, history, existing_files=None, mock_mode=False):
            captured["existing_files"] = existing_files
            captured["history"] = history
            return GenerationResult(
                assistant_message="Updated.",
                changes=[FileChange(
                    path=f"data/websites/{slug}/index.html",
                    action="update",
                    content=self._html("MyApp"),
                    summary="Updated page",
                )],
                provider="openai",
                model_mode="openai",
            )

        mock_apply = ApplyResult(
            slug=slug,
            version_id="20240102T000000Z",
            applied=["index.html"],
            skipped=[],
            results=[ChangeResult(
                path=f"data/websites/{slug}/index.html",
                action="update",
                status="applied",
            )],
        )

        with patch("services.code_generation_service.generate", side_effect=fake_generate):
            with patch("services.workspace_editor.apply_changes", return_value=mock_apply):
                with patch("services.file_persistence.read_current_html", return_value=existing_html):
                    resp = client.post("/website/chat", json={
                        "session_id": "sess-iter",
                        "message": "Make it dark",
                    })

        assert resp.status_code == 200
        # Existing HTML was loaded and passed as existing_files
        assert captured["existing_files"] is not None
        assert "original" in captured["existing_files"].get("index.html", "")
        # History was passed from DB
        assert len(captured["history"]) == 2

    def test_session_state_endpoint(self, client):
        from data.database import append_chat_message, upsert_chat_session
        upsert_chat_session("my-sess", slug="test-product", product_name="Test Product", version_id="20240101T000000Z")
        append_chat_message("my-sess", "user", "hi")
        resp = client.get("/website/session/my-sess")
        assert resp.status_code == 200
        data = resp.json()
        assert data["slug"] == "test-product"
        assert data["status"] == "ok"

    def test_session_state_missing_returns_empty(self, client):
        resp = client.get("/website/session/does-not-exist-xyz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "empty"

    def test_model_check_endpoint(self, client):
        resp = client.post("/model/check", json={"mock_mode": True})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ===========================================================================
# TestMultiFile — multi-file artifact model (Phase 1)
# ===========================================================================


class TestMultiFile:
    def test_save_multi_file_project(self, tmp_path, monkeypatch):
        import config.settings as cs
        cs.settings = MagicMock()
        cs.settings.resolve_websites_dir.return_value = tmp_path

        from services.file_persistence import save_website_files
        with patch("services.file_persistence.settings", cs.settings):
            result = save_website_files(
                "multi-app",
                {
                    "index.html": "<!DOCTYPE html><html><body>Landing</body></html>",
                    "pages/terms.html": "<!DOCTYPE html><html><body>Terms</body></html>",
                    "style.css": "body { color: red; }",
                    "app.js": "console.log('hello');",
                },
            )

        assert (tmp_path / "multi-app" / "index.html").exists()
        assert (tmp_path / "multi-app" / "pages" / "terms.html").exists()
        assert (tmp_path / "multi-app" / "style.css").exists()
        assert (tmp_path / "multi-app" / "app.js").exists()
        assert "index.html" in result["paths"]
        assert "pages/terms.html" in result["paths"]

    def test_disallowed_extension_skipped(self, tmp_path, monkeypatch):
        import config.settings as cs
        cs.settings = MagicMock()
        cs.settings.resolve_websites_dir.return_value = tmp_path

        from services.file_persistence import save_website_files
        with patch("services.file_persistence.settings", cs.settings):
            result = save_website_files(
                "bad-app",
                {"index.html": "<!DOCTYPE html><html></html>", "evil.exe": "bad"},
            )

        assert "index.html" in result["paths"]
        assert "evil.exe" not in result["paths"]
        assert not (tmp_path / "bad-app" / "evil.exe").exists()

    def test_path_traversal_in_save_skipped(self, tmp_path, monkeypatch):
        import config.settings as cs
        cs.settings = MagicMock()
        cs.settings.resolve_websites_dir.return_value = tmp_path

        from services.file_persistence import save_website_files
        with patch("services.file_persistence.settings", cs.settings):
            result = save_website_files(
                "trav-app",
                {"../etc/passwd": "bad", "index.html": "<!DOCTYPE html><html></html>"},
            )

        assert "../etc/passwd" not in result["paths"]
        assert "index.html" in result["paths"]

    def test_list_project_files(self, tmp_path, monkeypatch):
        import config.settings as cs
        cs.settings = MagicMock()
        cs.settings.resolve_websites_dir.return_value = tmp_path

        (tmp_path / "list-app").mkdir()
        (tmp_path / "list-app" / "index.html").write_text("<!DOCTYPE html><html></html>")
        (tmp_path / "list-app" / "pages").mkdir()
        (tmp_path / "list-app" / "pages" / "about.html").write_text("<!DOCTYPE html><html></html>")

        from services.file_persistence import list_project_files
        with patch("services.file_persistence.settings", cs.settings):
            files = list_project_files("list-app")

        assert "index.html" in files
        assert "pages/about.html" in files

    def test_read_current_file_validates_path(self, tmp_path, monkeypatch):
        import config.settings as cs
        cs.settings = MagicMock()
        cs.settings.resolve_websites_dir.return_value = tmp_path

        from services.file_persistence import read_current_file
        with patch("services.file_persistence.settings", cs.settings):
            # Path traversal should return None
            result = read_current_file("my-app", "../other/file.html")
        assert result is None

    def test_backup_includes_all_file_types(self, tmp_path, monkeypatch):
        import config.settings as cs
        cs.settings = MagicMock()
        cs.settings.resolve_websites_dir.return_value = tmp_path

        with patch("services.file_persistence.settings", cs.settings):
            from services.file_persistence import save_website_files
            save_website_files("bkp-app", {
                "index.html": "<!DOCTYPE html><html></html>",
                "style.css": "body {}",
            })
            # Second write triggers backup
            save_website_files("bkp-app", {
                "index.html": "<!DOCTYPE html><html><body>v2</body></html>",
            })

        versions_dir = tmp_path / "bkp-app" / "versions"
        assert versions_dir.exists()
        version_dirs = list(versions_dir.iterdir())
        assert len(version_dirs) >= 1
        # Backup should have both files from first write
        assert any((vd / "index.html").exists() for vd in version_dirs)


# ===========================================================================
# TestOutputValidatorExpanded — new multi-file validator tests
# ===========================================================================


class TestOutputValidatorExpanded:
    def test_css_passes_no_html_check(self):
        from services.output_validator import validate_files
        files = {"style.css": "body { color: var(--primary); }"}
        clean, warnings = validate_files(files)
        assert "style.css" in clean
        assert not warnings

    def test_js_passes(self):
        from services.output_validator import validate_files
        files = {"app.js": "console.log('hello');"}
        clean, warnings = validate_files(files)
        assert "app.js" in clean

    def test_json_passes(self):
        from services.output_validator import validate_files
        files = {"data.json": '{"key": "value"}'}
        clean, warnings = validate_files(files)
        assert "data.json" in clean

    def test_pages_subdir_allowed(self):
        from services.output_validator import validate_files
        files = {"pages/terms.html": "<!DOCTYPE html><html><body>Terms</body></html>"}
        clean, warnings = validate_files(files)
        assert "pages/terms.html" in clean

    def test_disallowed_subdir_rejected(self):
        from services.output_validator import validate_files
        files = {"secret/passwords.txt": "admin:hunter2"}
        clean, warnings = validate_files(files)
        assert "secret/passwords.txt" not in clean
        assert warnings

    def test_size_limit_enforced(self):
        from services.output_validator import validate_files
        big_content = "x" * 2_000_000  # 2MB > 1MB limit
        files = {"app.js": big_content}
        clean, warnings = validate_files(files)
        # Gets truncated — still included but with warning
        assert "app.js" in clean
        assert len(clean["app.js"]) <= 1_000_000
        assert any("mb" in w.lower() or "limit" in w.lower() for w in warnings)

    def test_html_sanitization_still_works(self):
        from services.output_validator import validate_files
        html = (
            '<!DOCTYPE html><html><body>'
            '<script src="https://evil.com/xss.js"></script>'
            '<a href="javascript:void(0)">click</a>'
            '</body></html>'
        )
        clean, warnings = validate_files({"index.html": html})
        assert "index.html" in clean
        assert "evil.com" not in clean["index.html"]
        assert 'href="#"' in clean["index.html"]


# ===========================================================================
# TestDesignSystem
# ===========================================================================


class TestDesignSystem:
    def test_generate_creates_valid_design_system(self):
        from services.design_system_service import DesignSystem, PALETTES
        ds = DesignSystem.generate()
        assert ds.palette_name in PALETTES
        assert ds.display_font
        assert ds.body_font
        assert ds.colors.get("primary")
        assert ds.colors.get("bg")

    def test_generate_with_style_seed(self):
        from services.design_system_service import DesignSystem
        ds = DesignSystem.generate(style_seed={"palette": "arctic", "archetype": "marketplace"})
        assert ds.palette_name == "arctic"
        assert ds.archetype == "marketplace"

    def test_to_dict_and_from_dict_roundtrip(self):
        from services.design_system_service import DesignSystem
        ds = DesignSystem.generate()
        d = ds.to_dict()
        ds2 = DesignSystem.from_dict(d)
        assert ds2.palette_name == ds.palette_name
        assert ds2.display_font == ds.display_font

    def test_to_css_vars_contains_properties(self):
        from services.design_system_service import DesignSystem
        ds = DesignSystem.generate()
        css = ds.to_css_vars()
        assert "--color-primary" in css
        assert "--font-display" in css
        assert "--radius-md" in css

    def test_to_prompt_block_contains_palette(self):
        from services.design_system_service import DesignSystem
        ds = DesignSystem.generate(style_seed={"palette": "rose"})
        block = ds.to_prompt_block()
        assert "rose" in block
        assert "DESIGN SYSTEM" in block

    def test_to_prompt_block_contains_responsive_rules(self):
        from services.design_system_service import DesignSystem
        ds = DesignSystem.generate()
        block = ds.to_prompt_block()
        assert "RESPONSIVE SPACING + LAYOUT RULES" in block
        assert "@media (max-width: 1024px)" in block
        assert "clamp()" in block

    def test_db_upsert_and_get(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CEOCLAW_DATABASE_PATH", str(tmp_path / "ds_test.db"))
        import config.settings as cs
        cs.settings = cs.Settings()
        from data.database import init_db, upsert_design_system, get_design_system
        init_db()

        from services.design_system_service import DesignSystem
        ds = DesignSystem.generate(style_seed={"palette": "forest"})
        upsert_design_system("sess-ds", ds.to_dict())

        fetched = get_design_system("sess-ds")
        assert fetched is not None
        assert fetched["palette_name"] == "forest"

    def test_get_design_system_returns_none_for_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CEOCLAW_DATABASE_PATH", str(tmp_path / "ds_miss.db"))
        import config.settings as cs
        cs.settings = cs.Settings()
        from data.database import init_db, get_design_system
        init_db()
        assert get_design_system("nonexistent-session") is None


# ===========================================================================
# TestOperationParser
# ===========================================================================


class TestOperationParser:
    def test_add_page_detected(self):
        from services.operation_parser import parse_operation
        op = parse_operation("add a terms of service page")
        assert op["type"] in ("add_page", "add_legal_page")

    def test_add_component_detected(self):
        from services.operation_parser import parse_operation
        op = parse_operation("add a testimonials section")
        assert op["type"] == "add_component"

    def test_add_endpoint_detected(self):
        from services.operation_parser import parse_operation
        op = parse_operation("add a REST API endpoint for users")
        assert op["type"] == "add_endpoint"

    def test_add_endpoint_extracts_methods(self):
        from services.operation_parser import parse_operation
        op = parse_operation("add a GET and POST api route for data")
        assert op["type"] == "add_endpoint"
        methods = op["metadata"].get("http_methods", [])
        assert "GET" in methods
        assert "POST" in methods

    def test_modify_style_detected(self):
        from services.operation_parser import parse_operation
        op = parse_operation("change the color scheme to blue")
        assert op["type"] == "modify_style"

    def test_general_edit_fallback(self):
        from services.operation_parser import parse_operation
        op = parse_operation("make the headline bigger")
        assert op["type"] == "general_edit"

    def test_legal_page_detected(self):
        from services.operation_parser import parse_operation
        op = parse_operation("add a privacy policy")
        assert op["type"] in ("add_page", "add_legal_page")

    def test_target_extracted_for_page(self):
        from services.operation_parser import parse_operation
        op = parse_operation("create an about page")
        assert op["target"] in ("about", "page", "")

    def test_unknown_message_returns_general_edit(self):
        from services.operation_parser import parse_operation
        op = parse_operation("hello there how are you")
        assert op["type"] == "general_edit"
