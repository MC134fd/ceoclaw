"""
Tests for api/server.py FastAPI endpoints  – v0.3

v0.2 endpoints (backward-compatible):
1.  GET /health → 200.
2.  GET /status → 200 with app metadata.
3.  GET /metrics/latest → 404 when empty.
4.  GET /metrics/latest → 200 after recording metrics.
5.  GET /runs/recent → 200 list.
6.  GET /runs/recent?limit=5 → at most 5 items.

v0.3 new endpoints:
7.  GET /runs/{run_id} → 200 for existing run.
8.  GET /runs/{run_id} → 404 for unknown run_id.
9.  GET /runs/{run_id}/timeline → 200 list (may be empty).
10. GET /runs/{run_id}/timeline → 404 for unknown run_id.
11. GET /artifacts/recent → 200 list.
12. GET /kpi/trend → 200 list.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    tmp_db_path = str(tmp_path / "test_api.db")
    monkeypatch.setenv("CEOCLAW_DATABASE_PATH", tmp_db_path)
    import config.settings as cs
    cs.settings = cs.Settings()
    # load_dotenv(override=True) inside Settings.reload() re-reads .env and
    # clobbers the monkeypatched env var.  Directly set the path on the live
    # singleton so _db_path() resolves to our temp file.
    cs.settings.database_path = tmp_db_path
    from data.database import init_db
    init_db()
    yield


@pytest.fixture()
def client():
    from api.server import app
    return TestClient(app)


@pytest.fixture()
def seeded_run_id(tmp_path):
    """Run one mock cycle and return its run_id for use in v0.3 endpoint tests."""
    from core.agent_loop import run_graph
    final = run_graph(cycles=1, mock_mode=True, goal_mrr=100.0, max_cycles=1)
    return final["run_id"]


# ---------------------------------------------------------------------------
# v0.2 endpoints
# ---------------------------------------------------------------------------

def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "app" in body


def test_status(client):
    resp = client.get("/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "app_name" in body
    assert "goal_mrr" in body


def test_metrics_latest_404_when_empty(client):
    resp = client.get("/metrics/latest")
    assert resp.status_code == 404


def test_metrics_latest_200_after_record(client):
    from core.state_manager import StateManager
    StateManager().record_metrics(website_traffic=10, signups=1, mrr=5.0)
    resp = client.get("/metrics/latest")
    assert resp.status_code == 200
    assert resp.json()["mrr"] == 5.0


def test_runs_recent_returns_list(client):
    resp = client.get("/runs/recent")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_runs_recent_respects_limit(client, seeded_run_id):
    resp = client.get("/runs/recent?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) <= 5


# ---------------------------------------------------------------------------
# v0.3 – /runs/{run_id}
# ---------------------------------------------------------------------------

def test_get_run_existing(client, seeded_run_id):
    resp = client.get(f"/runs/{seeded_run_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == seeded_run_id


def test_get_run_not_found(client):
    resp = client.get("/runs/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# v0.3 – /runs/{run_id}/timeline
# ---------------------------------------------------------------------------

def test_run_timeline_existing(client, seeded_run_id):
    resp = client.get(f"/runs/{seeded_run_id}/timeline")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_run_timeline_not_found(client):
    resp = client.get("/runs/00000000-0000-0000-0000-000000000000/timeline")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# v0.3 – /artifacts/recent
# ---------------------------------------------------------------------------

def test_artifacts_recent_returns_list(client):
    resp = client.get("/artifacts/recent")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_artifacts_recent_after_run(client, seeded_run_id):
    resp = client.get("/artifacts/recent?limit=50")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    # At least one artifact should exist (ops_executor writes metrics_snapshot)
    assert len(data) >= 1


# ---------------------------------------------------------------------------
# v0.3 – /kpi/trend
# ---------------------------------------------------------------------------

def test_kpi_trend_returns_list(client):
    resp = client.get("/kpi/trend")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_kpi_trend_after_run(client, seeded_run_id):
    resp = client.get("/kpi/trend?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    # After a run, there should be at least one cycle score
    assert len(data) >= 1
    # Items should have the expected KPI fields
    first = data[0]
    assert "mrr" in first
    assert "weighted_score" in first
    assert "cycle_count" in first
