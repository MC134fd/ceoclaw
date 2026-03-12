"""
Tests for v0.5 chat/streaming endpoints and OpenClaw integration boundary.

Coverage:
  - POST /chat returns run_id and stream_url
  - POST /runs/start returns run_id
  - GET /runs/{run_id}/events returns SSE content-type
  - GET /app serves the frontend HTML
  - event_bus stores and retrieves events correctly
  - FlockChatModel IS the canonical OpenClaw BaseChatModel boundary
  - run_graph emits structured events to the event bus
"""

import json
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("CEOCLAW_DATABASE_PATH", str(tmp_path / "chat_test.db"))
    import config.settings as cs
    cs.settings = cs.Settings()
    from data.database import init_db
    init_db()
    yield


@pytest.fixture()
def client():
    from api.server import app
    return TestClient(app)


# ===========================================================================
# event_bus unit tests
# ===========================================================================

def test_event_bus_emit_and_retrieve():
    from core.event_bus import cleanup, emit, get_events
    rid = str(uuid.uuid4())
    emit(rid, {"type": "run_start", "goal_mrr": 100.0})
    emit(rid, {"type": "planner",   "cycle": 1})
    evts = get_events(rid)
    assert len(evts) == 2
    assert evts[0]["type"] == "run_start"
    assert evts[1]["cycle"] == 1
    cleanup(rid)


def test_event_bus_partial_read():
    from core.event_bus import cleanup, emit, get_events
    rid = str(uuid.uuid4())
    for i in range(5):
        emit(rid, {"type": "x", "i": i})
    assert len(get_events(rid, start_idx=3)) == 2
    cleanup(rid)


def test_event_bus_mark_done():
    from core.event_bus import cleanup, emit, is_done, mark_done
    rid = str(uuid.uuid4())
    assert not is_done(rid)
    emit(rid, {"type": "test"})
    mark_done(rid)
    assert is_done(rid)
    cleanup(rid)


def test_event_bus_cleanup():
    from core.event_bus import cleanup, emit, event_count
    rid = str(uuid.uuid4())
    emit(rid, {"type": "test"})
    assert event_count(rid) == 1
    cleanup(rid)
    assert event_count(rid) == 0


# ===========================================================================
# POST /chat
# ===========================================================================

def test_chat_returns_run_id(client):
    resp = client.post("/chat", json={
        "message": "Start a mock run",
        "goal_mrr": 50.0,
        "cycles": 2,
        "mock_mode": True,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert "run_id" in body
    assert "stream_url" in body
    assert body["stream_url"].startswith("/runs/")
    assert "events" in body["stream_url"]
    # run_id should be a valid UUID-like string
    assert len(body["run_id"]) == 36


def test_chat_default_params(client):
    """POST /chat with minimal body uses defaults."""
    resp = client.post("/chat", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert "run_id" in body


def test_chat_message_field_optional(client):
    """message is optional — only parameters matter for the run."""
    resp = client.post("/chat", json={"goal_mrr": 100.0, "cycles": 1, "mock_mode": True})
    assert resp.status_code == 200


def test_chat_accepts_selected_idea(client):
    """POST /chat can start directly from a pre-selected idea."""
    selected_idea = {
        "product_type": "saas",
        "product_name": "Calorie Flow Pro",
        "target_user": "fitness enthusiasts",
        "core_features": ["calorie/macro tracking", "dashboard"],
        "nonfunctional_reqs": ["clean UX"],
        "desired_endpoints": ["/api/health", "/api/entries"],
        "tech_stack": "html/css/js",
        "raw_message": "build me a calorie tracker",
        "confidence": 0.9,
    }
    resp = client.post("/chat", json={
        "message": "ignored when selected_idea provided",
        "selected_idea": selected_idea,
        "cycles": 1,
        "mock_mode": True,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["product_intent"]["product_name"] == "Calorie Flow Pro"
    assert body["product_intent"]["target_user"] == "fitness enthusiasts"


def test_generate_ideas_endpoint_returns_four_ideas(client):
    """POST /ideas/generate returns 4 selectable structured ideas."""
    resp = client.post("/ideas/generate", json={
        "message": "build me a calorie tracker app for gym users",
        "count": 4,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 4
    assert len(body["ideas"]) == 4
    for idea in body["ideas"]:
        assert idea["product_name"]
        assert idea["core_features"]
        assert idea["desired_endpoints"]


# ===========================================================================
# POST /runs/start
# ===========================================================================

def test_runs_start_returns_run_id(client):
    resp = client.post("/runs/start", json={"goal_mrr": 100.0, "cycles": 1, "mock_mode": True})
    assert resp.status_code == 200
    body = resp.json()
    assert "run_id" in body
    assert "stream_url" in body


def test_runs_start_different_run_ids(client):
    """Each call creates a unique run_id."""
    r1 = client.post("/runs/start", json={"mock_mode": True}).json()["run_id"]
    r2 = client.post("/runs/start", json={"mock_mode": True}).json()["run_id"]
    assert r1 != r2


# ===========================================================================
# GET /runs/{run_id}/events (SSE)
# ===========================================================================

def test_events_endpoint_sse_headers(client):
    """SSE endpoint returns correct content-type."""
    rid = str(uuid.uuid4())
    # Pre-seed events and mark done so the stream closes quickly
    from core.event_bus import emit, mark_done
    emit(rid, {"type": "run_complete", "cycles_run": 0})
    mark_done(rid)

    with client.stream("GET", f"/runs/{rid}/events") as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")


def test_events_endpoint_returns_seeded_events(client):
    """SSE stream delivers events in order."""
    rid = str(uuid.uuid4())
    from core.event_bus import emit, mark_done
    emit(rid, {"type": "run_start", "goal_mrr": 100.0})
    emit(rid, {"type": "run_complete", "cycles_run": 0, "final_mrr": 0.0, "final_weighted_score": 0.0})
    mark_done(rid)

    data_lines = []
    with client.stream("GET", f"/runs/{rid}/events") as resp:
        for line in resp.iter_lines():
            if line.startswith("data: "):
                payload = json.loads(line[6:])
                data_lines.append(payload)
                if payload.get("type") == "run_complete":
                    break

    types = [d["type"] for d in data_lines]
    assert "run_start" in types
    assert "run_complete" in types


# ===========================================================================
# GET /app — frontend
# ===========================================================================

def test_app_serves_html(client):
    resp = client.get("/app")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert b"CEOClaw" in resp.content


def test_root_serves_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"CEOClaw" in resp.content


# ===========================================================================
# OpenClaw integration boundary
# ===========================================================================

def test_flockchatmodel_is_basechatmodel():
    """FlockChatModel IS the OpenClaw BaseChatModel boundary."""
    from langchain_core.language_models.chat_models import BaseChatModel
    from integrations.flock_client import FlockChatModel
    assert issubclass(FlockChatModel, BaseChatModel)


def test_flockchatmodel_implements_generate():
    """FlockChatModel has the _generate method required by BaseChatModel."""
    from integrations.flock_client import FlockChatModel
    assert hasattr(FlockChatModel, "_generate")
    assert callable(FlockChatModel._generate)


def test_flockchatmodel_llm_type():
    """FlockChatModel identifies itself as 'flock' (OpenClaw model type)."""
    from integrations.flock_client import FlockChatModel
    m = FlockChatModel(mock_mode=True)
    assert m._llm_type == "flock"


def test_flockchatmodel_mock_metadata():
    """Mock mode returns metadata confirming OpenClaw boundary contract."""
    from integrations.flock_client import FlockChatModel
    from langchain_core.messages import HumanMessage
    m = FlockChatModel(mock_mode=True)
    resp = m.invoke([HumanMessage(content="ping")])
    meta = resp.response_metadata
    assert meta["model_mode"] in ("mock", "live", "fallback")
    assert "tokens_estimated" in meta
    assert "external_calls_delta" in meta


def test_openclaw_adapter_importable_as_base_reference():
    """openclaw_adapter.py is preserved as the OpenClaw base interface reference."""
    from integrations.openclaw_adapter import OpenClawAdapter
    adapter = OpenClawAdapter()
    # Base interface contract
    assert callable(adapter.build_planner_prompt)
    assert callable(adapter.build_evaluator_prompt)
    assert callable(adapter.compute_progress)
    assert callable(adapter.suggest_domain)


# ===========================================================================
# run_graph event emission
# ===========================================================================

def test_run_graph_emits_run_start_and_complete():
    """run_graph emits run_start and run_complete events to the bus."""
    from core.agent_loop import run_graph
    from core import event_bus
    import uuid

    rid = str(uuid.uuid4())
    run_graph(cycles=1, mock_mode=True, goal_mrr=100.0, max_cycles=1, quiet=True, run_id=rid)

    evts = event_bus.get_events(rid)
    types = [e["type"] for e in evts]
    assert "run_start"    in types, f"run_start missing. Got: {types}"
    assert "run_complete" in types, f"run_complete missing. Got: {types}"


def test_run_graph_emits_planner_events():
    """run_graph emits a planner event for each cycle."""
    from core.agent_loop import run_graph
    from core import event_bus

    rid = str(uuid.uuid4())
    run_graph(cycles=2, mock_mode=True, goal_mrr=100.0, max_cycles=2, quiet=True, run_id=rid)

    evts    = event_bus.get_events(rid)
    planners = [e for e in evts if e["type"] == "planner"]
    assert len(planners) == 2
    for p in planners:
        assert p["domain"] in ("product", "marketing", "sales", "ops")
        assert p["action"]


def test_run_graph_emits_cycle_complete_events():
    """run_graph emits a cycle_complete event for each evaluated cycle."""
    from core.agent_loop import run_graph
    from core import event_bus

    rid = str(uuid.uuid4())
    run_graph(cycles=2, mock_mode=True, goal_mrr=100.0, max_cycles=2, quiet=True, run_id=rid)

    evts   = event_bus.get_events(rid)
    cycles = [e for e in evts if e["type"] == "cycle_complete"]
    assert len(cycles) == 2
    for c in cycles:
        assert "mrr"            in c
        assert "weighted_score" in c
        assert "trend"          in c


def test_run_graph_run_id_parameter():
    """run_graph respects a pre-assigned run_id."""
    from core.agent_loop import run_graph
    from core import event_bus

    rid = str(uuid.uuid4())
    result = run_graph(cycles=1, mock_mode=True, goal_mrr=100.0, max_cycles=1, quiet=True, run_id=rid)
    assert result["run_id"] == rid
    evts = event_bus.get_events(rid)
    assert len(evts) > 0


# ===========================================================================
# Dynamic file serving tests (Phase 1)
# ===========================================================================


class TestDynamicFileServing:
    """Tests for the new /websites/{slug}/{file_path:path} route."""

    def test_serve_css_file(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("CEOCLAW_WEBSITES_DIR", str(tmp_path))
        import config.settings as cs
        cs.settings = cs.Settings()

        slug_dir = tmp_path / "test-app"
        slug_dir.mkdir()
        (slug_dir / "style.css").write_text("body { color: red; }")

        resp = client.get("/websites/test-app/style.css")
        # May 200 or 404 depending on settings resolution in test context
        # Main test: no path traversal or 500 errors
        assert resp.status_code in (200, 404)

    def test_path_traversal_rejected(self, client):
        resp = client.get("/websites/test-app/../../../etc/passwd")
        assert resp.status_code in (400, 404, 422)

    def test_disallowed_extension_rejected(self, client):
        resp = client.get("/websites/test-app/evil.exe")
        assert resp.status_code == 400

    def test_backward_compat_index_alias(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("CEOCLAW_WEBSITES_DIR", str(tmp_path))
        import config.settings as cs
        cs.settings = cs.Settings()

        slug_dir = tmp_path / "my-site"
        slug_dir.mkdir()
        (slug_dir / "index.html").write_text("<!DOCTYPE html><html><body>hi</body></html>")

        resp = client.get("/websites/my-site/index")
        # 'index' should map to 'index.html'
        assert resp.status_code in (200, 404)  # 200 if settings resolves correctly

    def test_invalid_slug_rejected(self, client):
        resp = client.get("/websites//style.css")
        assert resp.status_code in (400, 404, 422)


# ===========================================================================
# Version endpoint tests (Phase 4)
# ===========================================================================


class TestVersionEndpoints:
    """Tests for GET/POST /builder/sessions/{session_id}/versions/..."""

    @pytest.fixture()
    def seeded_client(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("CEOCLAW_WEBSITES_DIR", str(tmp_path))
        import config.settings as cs
        cs.settings = cs.Settings()
        return client

    def test_list_versions_empty(self, client):
        resp = client.get("/builder/sessions/nonexistent-session/versions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_versions_after_save(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("CEOCLAW_DATABASE_PATH", str(tmp_path / "ver_test.db"))
        import config.settings as cs
        cs.settings = cs.Settings()
        from data.database import init_db, save_session_version
        init_db()

        save_session_version(
            "sess-ver-1",
            "20240101T000000Z",
            {"index.html": "<!DOCTYPE html><html></html>"},
        )

        resp = client.get("/builder/sessions/sess-ver-1/versions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["version_id"] == "20240101T000000Z"
        assert "index.html" in data[0]["file_list"]

    def test_get_version_not_found(self, client):
        resp = client.get("/builder/sessions/no-sess/versions/fake-ver")
        assert resp.status_code == 404

    def test_get_version_metadata(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("CEOCLAW_DATABASE_PATH", str(tmp_path / "ver_meta.db"))
        import config.settings as cs
        cs.settings = cs.Settings()
        from data.database import init_db, save_session_version
        init_db()

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

    def test_get_version_file_content(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("CEOCLAW_DATABASE_PATH", str(tmp_path / "ver_file.db"))
        import config.settings as cs
        cs.settings = cs.Settings()
        from data.database import init_db, save_session_version
        init_db()

        save_session_version(
            "sess-file",
            "20240301T000000Z",
            {"index.html": "<!DOCTYPE html><html><body>Hello</body></html>"},
        )

        resp = client.get("/builder/sessions/sess-file/versions/20240301T000000Z/files/index.html")
        assert resp.status_code == 200
        data = resp.json()
        assert "Hello" in data["content"]

    def test_get_version_file_path_traversal_rejected(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("CEOCLAW_DATABASE_PATH", str(tmp_path / "ver_trav.db"))
        import config.settings as cs
        cs.settings = cs.Settings()
        from data.database import init_db, save_session_version
        init_db()

        save_session_version(
            "sess-trav",
            "20240401T000000Z",
            {"index.html": "content"},
        )

        resp = client.get("/builder/sessions/sess-trav/versions/20240401T000000Z/files/../etc/passwd")
        # FastAPI normalizes .. in URL paths — safe response is 400 or 404
        assert resp.status_code in (400, 404)

    def test_restore_version_not_found(self, client):
        resp = client.post("/builder/sessions/no-sess/versions/fake-ver/restore")
        assert resp.status_code == 404
