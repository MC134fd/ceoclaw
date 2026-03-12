"""
Tests for social publisher adapters and social post persistence (v0.5).

Coverage:
  - X publisher dry_run always returns 'drafted'
  - Instagram publisher dry_run always returns 'drafted'
  - X publisher no credentials returns 'drafted'
  - Instagram publisher no credentials returns 'drafted'
  - social_post DB persistence lifecycle
  - social_post status update
  - API endpoint returns social posts
"""

import json
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("CEOCLAW_DATABASE_PATH", str(tmp_path / "social_test.db"))
    import config.settings as cs
    cs.settings = cs.Settings()
    from data.database import init_db
    init_db()
    yield


# ===========================================================================
# X publisher
# ===========================================================================

def test_x_publisher_dry_run_always_drafts():
    from tools.social_publishers.x_publisher import publish
    result = publish("Test tweet content", dry_run=True)
    assert result.platform == "x"
    assert result.status == "drafted"
    assert result.content == "Test tweet content"


def test_x_publisher_dry_run_no_post_id():
    from tools.social_publishers.x_publisher import publish
    result = publish("Test content", dry_run=True)
    assert result.post_id is None


def test_x_publisher_no_credentials_drafts(monkeypatch):
    monkeypatch.delenv("X_API_KEY", raising=False)
    monkeypatch.delenv("X_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("TWITTER_API_KEY", raising=False)
    monkeypatch.delenv("TWITTER_BEARER_TOKEN", raising=False)
    from tools.social_publishers.x_publisher import publish
    result = publish("Test no creds")
    assert result.status == "drafted"
    assert "no_credentials" in str(result.metadata)


def test_x_publisher_enforces_280_char_limit():
    from tools.social_publishers.x_publisher import publish
    long_content = "A" * 400
    result = publish(long_content, dry_run=True)
    assert len(result.content) == 280


def test_x_publisher_result_has_required_fields():
    from tools.social_publishers.x_publisher import publish, PublishResult
    result = publish("Short content", dry_run=True)
    assert hasattr(result, "platform")
    assert hasattr(result, "status")
    assert hasattr(result, "content")
    assert hasattr(result, "post_id")
    assert hasattr(result, "error_detail")
    assert hasattr(result, "metadata")


# ===========================================================================
# Instagram publisher
# ===========================================================================

def test_instagram_publisher_dry_run_always_drafts():
    from tools.social_publishers.instagram_publisher import publish
    result = publish("Test Instagram caption", dry_run=True)
    assert result.platform == "instagram"
    assert result.status == "drafted"


def test_instagram_publisher_no_credentials_drafts(monkeypatch):
    monkeypatch.delenv("INSTAGRAM_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("INSTAGRAM_USER_ID", raising=False)
    from tools.social_publishers.instagram_publisher import publish
    result = publish("No creds caption")
    assert result.status == "drafted"
    assert "no_credentials" in str(result.metadata)


def test_instagram_publisher_enforces_2200_char_limit():
    from tools.social_publishers.instagram_publisher import publish
    long_content = "B" * 3000
    result = publish(long_content, dry_run=True)
    assert len(result.content) == 2200


# ===========================================================================
# social_publisher tool (facade)
# ===========================================================================

def test_social_publisher_tool_returns_json():
    from tools.social_publisher import social_publisher_tool, DRY_RUN
    raw = social_publisher_tool.invoke({
        "platform": "x",
        "content": "Test content",
        "autonomy_mode": DRY_RUN,
    })
    assert isinstance(raw, str)
    result = json.loads(raw)
    assert "status" in result
    assert "platform" in result


def test_social_publisher_empty_content_returns_failed():
    from tools.social_publisher import social_publisher_tool, AUTONOMOUS
    raw = social_publisher_tool.invoke({
        "platform": "x",
        "content": "",
        "autonomy_mode": AUTONOMOUS,
    })
    result = json.loads(raw)
    assert result["status"] == "failed"


def test_social_publisher_unknown_platform_drafts():
    from tools.social_publisher import social_publisher_tool, AUTONOMOUS
    raw = social_publisher_tool.invoke({
        "platform": "tiktok",
        "content": "Unknown platform test",
        "autonomy_mode": AUTONOMOUS,
    })
    result = json.loads(raw)
    assert result["status"] in ("drafted", "failed")


# ===========================================================================
# social_post DB persistence
# ===========================================================================

def test_persist_social_post_and_retrieve():
    from data.database import persist_social_post, get_social_posts
    rid = str(uuid.uuid4())
    db_id = persist_social_post(
        run_id=rid,
        cycle_count=1,
        platform="x",
        content="Test tweet for #buildinpublic",
        status="drafted",
    )
    assert db_id is not None
    posts = get_social_posts(rid)
    assert len(posts) == 1
    assert posts[0]["platform"] == "x"
    assert posts[0]["status"] == "drafted"
    assert posts[0]["content"] == "Test tweet for #buildinpublic"


def test_social_post_status_update():
    from data.database import persist_social_post, update_social_post_status, get_social_posts
    rid = str(uuid.uuid4())
    db_id = persist_social_post(
        run_id=rid, cycle_count=1, platform="x",
        content="Pending post", status="pending_approval",
    )
    update_social_post_status(db_id, "posted", post_id="tweet_12345")
    posts = get_social_posts(rid)
    assert posts[0]["status"] == "posted"
    assert posts[0]["post_id"] == "tweet_12345"


def test_social_post_failure_records_error():
    from data.database import persist_social_post, update_social_post_status, get_social_posts
    rid = str(uuid.uuid4())
    db_id = persist_social_post(
        run_id=rid, cycle_count=1, platform="instagram",
        content="Failed post", status="drafted",
    )
    update_social_post_status(db_id, "failed", error_detail="API rate limit exceeded")
    posts = get_social_posts(rid)
    assert posts[0]["status"] == "failed"
    assert posts[0]["error_detail"] == "API rate limit exceeded"


def test_social_publisher_persists_post_with_run_id():
    from tools.social_publisher import social_publisher_tool, DRY_RUN
    from data.database import get_social_posts
    rid = str(uuid.uuid4())
    social_publisher_tool.invoke({
        "platform": "x",
        "content": "Persisted draft content",
        "autonomy_mode": DRY_RUN,
        "run_id": rid,
        "cycle_count": 3,
    })
    posts = get_social_posts(rid)
    assert len(posts) == 1
    assert posts[0]["cycle_count"] == 3


# ===========================================================================
# API endpoint
# ===========================================================================

@pytest.fixture
def client():
    from api.server import app
    from fastapi.testclient import TestClient
    return TestClient(app)


def test_social_posts_endpoint_returns_list(client):
    rid = str(uuid.uuid4())
    resp = client.get(f"/runs/{rid}/social-posts")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_social_posts_endpoint_returns_persisted(client):
    from data.database import persist_social_post
    rid = str(uuid.uuid4())
    persist_social_post(rid, 1, "x", "Test tweet", "drafted")
    persist_social_post(rid, 2, "instagram", "Test caption", "posted", post_id="ig_123")

    resp = client.get(f"/runs/{rid}/social-posts")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    platforms = {p["platform"] for p in data}
    assert platforms == {"x", "instagram"}
