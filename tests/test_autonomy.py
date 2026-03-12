"""
Tests for autonomy mode system (v0.5).

Coverage:
  - AutonomyMode constants accessible and correct
  - autonomy_mode flows through run_graph into state
  - social_publisher enforces dry-run, approval, autonomous policies
  - API request models accept autonomy_mode
  - approval queue create/resolve/retrieve lifecycle
"""

import json
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("CEOCLAW_DATABASE_PATH", str(tmp_path / "autonomy_test.db"))
    import config.settings as cs
    cs.settings = cs.Settings()
    from data.database import init_db
    init_db()
    yield


# ===========================================================================
# Autonomy mode constants
# ===========================================================================

def test_autonomy_mode_constants_defined():
    from tools.social_publisher import AUTONOMOUS, HUMAN_APPROVAL, ASSISTED, DRY_RUN
    assert AUTONOMOUS == "A_AUTONOMOUS"
    assert HUMAN_APPROVAL == "B_HUMAN_APPROVAL"
    assert ASSISTED == "C_ASSISTED"
    assert DRY_RUN == "D_DRY_RUN"


# ===========================================================================
# Social publisher — DRY_RUN mode
# ===========================================================================

def test_social_publisher_dry_run_never_publishes():
    from tools.social_publisher import social_publisher_tool, DRY_RUN
    rid = str(uuid.uuid4())
    raw = social_publisher_tool.invoke({
        "platform": "x",
        "content": "Test post content #buildinpublic",
        "autonomy_mode": DRY_RUN,
        "run_id": rid,
        "cycle_count": 1,
    })
    result = json.loads(raw)
    assert result["status"] == "drafted"
    assert result["autonomy_mode"] == DRY_RUN


def test_social_publisher_dry_run_instagram():
    from tools.social_publisher import social_publisher_tool, DRY_RUN
    rid = str(uuid.uuid4())
    raw = social_publisher_tool.invoke({
        "platform": "instagram",
        "content": "Instagram test post content",
        "autonomy_mode": DRY_RUN,
        "run_id": rid,
        "cycle_count": 1,
    })
    result = json.loads(raw)
    assert result["status"] == "drafted"
    assert result["platform"] == "instagram"


# ===========================================================================
# Social publisher — B_HUMAN_APPROVAL mode
# ===========================================================================

def test_social_publisher_human_approval_queues():
    from tools.social_publisher import social_publisher_tool, HUMAN_APPROVAL
    from data.database import get_pending_approvals
    rid = str(uuid.uuid4())
    raw = social_publisher_tool.invoke({
        "platform": "x",
        "content": "Needs approval before posting",
        "autonomy_mode": HUMAN_APPROVAL,
        "run_id": rid,
        "cycle_count": 2,
    })
    result = json.loads(raw)
    assert result["status"] == "pending_approval"
    assert result["approval_id"] is not None

    approvals = get_pending_approvals(rid)
    assert len(approvals) == 1
    assert approvals[0]["approval_type"] == "social_publish"
    assert approvals[0]["status"] == "pending"


def test_social_publisher_assisted_mode_queues():
    from tools.social_publisher import social_publisher_tool, ASSISTED
    from data.database import get_pending_approvals
    rid = str(uuid.uuid4())
    raw = social_publisher_tool.invoke({
        "platform": "x",
        "content": "Assisted mode test",
        "autonomy_mode": ASSISTED,
        "run_id": rid,
        "cycle_count": 1,
    })
    result = json.loads(raw)
    assert result["status"] == "pending_approval"
    approvals = get_pending_approvals(rid)
    assert len(approvals) >= 1


# ===========================================================================
# Social publisher — A_AUTONOMOUS mode (no credentials = draft)
# ===========================================================================

def test_social_publisher_autonomous_no_creds_drafts(monkeypatch):
    """Without API credentials, autonomous mode should create a draft."""
    monkeypatch.delenv("X_API_KEY", raising=False)
    monkeypatch.delenv("X_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("TWITTER_API_KEY", raising=False)
    monkeypatch.delenv("TWITTER_BEARER_TOKEN", raising=False)

    from tools.social_publisher import social_publisher_tool, AUTONOMOUS
    rid = str(uuid.uuid4())
    raw = social_publisher_tool.invoke({
        "platform": "x",
        "content": "Autonomous mode test",
        "autonomy_mode": AUTONOMOUS,
        "run_id": rid,
        "cycle_count": 1,
    })
    result = json.loads(raw)
    # Without credentials, should be drafted (not posted, not failed)
    assert result["status"] in ("drafted", "failed")
    assert result["content"] == "Autonomous mode test"


# ===========================================================================
# Approval lifecycle
# ===========================================================================

def test_approval_create_and_resolve():
    from data.database import create_pending_approval, resolve_approval, get_approval
    rid = str(uuid.uuid4())
    approval_id = create_pending_approval(
        run_id=rid,
        approval_type="social_publish",
        payload={"platform": "x", "content": "test"},
    )
    assert approval_id is not None

    row = get_approval(approval_id)
    assert row["status"] == "pending"
    assert row["run_id"] == rid

    resolve_approval(approval_id, "approved", resolved_by="user")
    row = get_approval(approval_id)
    assert row["status"] == "approved"
    assert row["resolved_by"] == "user"


def test_approval_rejected():
    from data.database import create_pending_approval, resolve_approval, get_approval
    rid = str(uuid.uuid4())
    approval_id = create_pending_approval(
        run_id=rid,
        approval_type="social_publish",
        payload={"platform": "instagram", "content": "reject me"},
    )
    resolve_approval(approval_id, "rejected")
    row = get_approval(approval_id)
    assert row["status"] == "rejected"


def test_get_pending_approvals_filters():
    from data.database import create_pending_approval, resolve_approval, get_pending_approvals
    rid = str(uuid.uuid4())
    a1 = create_pending_approval(rid, "social_publish", {"p": "x"})
    a2 = create_pending_approval(rid, "social_publish", {"p": "ig"})
    resolve_approval(a1, "approved")

    pending = get_pending_approvals(rid, status="pending")
    assert len(pending) == 1
    assert pending[0]["id"] == a2


# ===========================================================================
# API — autonomy_mode in request models
# ===========================================================================

@pytest.fixture
def client():
    from api.server import app
    from fastapi.testclient import TestClient
    return TestClient(app)


def test_chat_endpoint_accepts_autonomy_mode(client):
    resp = client.post("/chat", json={
        "goal_mrr": 50.0,
        "cycles": 1,
        "mock_mode": True,
        "autonomy_mode": "D_DRY_RUN",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["autonomy_mode"] == "D_DRY_RUN"


def test_runs_start_accepts_autonomy_mode(client):
    resp = client.post("/runs/start", json={
        "mock_mode": True,
        "autonomy_mode": "B_HUMAN_APPROVAL",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["autonomy_mode"] == "B_HUMAN_APPROVAL"


def test_chat_endpoint_defaults_to_autonomous(client):
    resp = client.post("/chat", json={"mock_mode": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["autonomy_mode"] == "A_AUTONOMOUS"


# ===========================================================================
# API — approvals endpoints
# ===========================================================================

def test_get_approvals_endpoint_returns_list(client):
    rid = str(uuid.uuid4())
    resp = client.get(f"/runs/{rid}/approvals")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_decide_approval_endpoint_approved(client):
    from data.database import create_pending_approval
    rid = str(uuid.uuid4())
    approval_id = create_pending_approval(rid, "social_publish", {"platform": "x", "content": "test"})

    resp = client.post(f"/approvals/{approval_id}/decide", json={"decision": "approved"})
    assert resp.status_code == 200
    assert resp.json()["decision"] == "approved"


def test_decide_approval_endpoint_rejected(client):
    from data.database import create_pending_approval
    rid = str(uuid.uuid4())
    approval_id = create_pending_approval(rid, "social_publish", {"platform": "x", "content": "test"})

    resp = client.post(f"/approvals/{approval_id}/decide", json={"decision": "rejected"})
    assert resp.status_code == 200
    assert resp.json()["decision"] == "rejected"


def test_decide_approval_invalid_decision(client):
    from data.database import create_pending_approval
    rid = str(uuid.uuid4())
    approval_id = create_pending_approval(rid, "social_publish", {"platform": "x", "content": "t"})
    resp = client.post(f"/approvals/{approval_id}/decide", json={"decision": "maybe"})
    assert resp.status_code == 400


def test_decide_approval_not_found(client):
    resp = client.post("/approvals/99999/decide", json={"decision": "approved"})
    assert resp.status_code == 404


def test_decide_approval_already_resolved(client):
    from data.database import create_pending_approval, resolve_approval
    rid = str(uuid.uuid4())
    approval_id = create_pending_approval(rid, "social_publish", {"platform": "x", "content": "t"})
    resolve_approval(approval_id, "approved")
    resp = client.post(f"/approvals/{approval_id}/decide", json={"decision": "approved"})
    assert resp.status_code == 409


# ===========================================================================
# autonomy_mode flows through run_graph
# ===========================================================================

def test_run_graph_autonomy_mode_in_state():
    from core.agent_loop import run_graph
    result = run_graph(
        cycles=1,
        mock_mode=True,
        goal_mrr=50.0,
        max_cycles=1,
        quiet=True,
        autonomy_mode="D_DRY_RUN",
    )
    assert result.get("autonomy_mode") == "D_DRY_RUN"
