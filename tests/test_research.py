"""
Tests for research_tool and research report persistence (v0.5).

Coverage:
  - research_tool returns required keys
  - All four domain topics produce topic-specific content
  - Persistence to DB works correctly
  - API endpoint returns research reports
"""

import json
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("CEOCLAW_DATABASE_PATH", str(tmp_path / "research_test.db"))
    import config.settings as cs
    cs.settings = cs.Settings()
    from data.database import init_db
    init_db()
    yield


# ===========================================================================
# research_tool output structure
# ===========================================================================

def test_research_tool_returns_required_keys():
    from tools.research_tool import research_tool
    raw = research_tool.invoke({
        "topic": "product market research",
        "product_name": "TestProduct",
    })
    result = json.loads(raw)
    required = {"status", "topic", "product_name", "summary", "competitors", "audience",
                "opportunities", "risks", "experiments"}
    assert required.issubset(result.keys())


def test_research_tool_status_success():
    from tools.research_tool import research_tool
    raw = research_tool.invoke({"topic": "marketing analysis"})
    result = json.loads(raw)
    assert result["status"] == "success"


def test_research_tool_competitors_is_list():
    from tools.research_tool import research_tool
    raw = research_tool.invoke({"topic": "sales strategy"})
    result = json.loads(raw)
    assert isinstance(result["competitors"], list)
    assert len(result["competitors"]) > 0


def test_research_tool_opportunities_is_list():
    from tools.research_tool import research_tool
    raw = research_tool.invoke({"topic": "ops efficiency"})
    result = json.loads(raw)
    assert isinstance(result["opportunities"], list)
    assert len(result["opportunities"]) > 0


def test_research_tool_experiments_have_metric():
    from tools.research_tool import research_tool
    raw = research_tool.invoke({"topic": "product market research"})
    result = json.loads(raw)
    for exp in result["experiments"]:
        assert "metric" in exp
        assert "duration_days" in exp


def test_research_tool_audience_has_pain_points():
    from tools.research_tool import research_tool
    raw = research_tool.invoke({"topic": "marketing analysis"})
    result = json.loads(raw)
    audience = result["audience"]
    assert "primary" in audience
    assert "pain_points" in audience


# ===========================================================================
# Domain-specific templates
# ===========================================================================

def test_research_product_topic_matches_product_template():
    from tools.research_tool import research_tool
    raw = research_tool.invoke({"topic": "product development"})
    result = json.loads(raw)
    # Product template has specific competitors
    competitor_names = [c["name"] for c in result["competitors"]]
    assert any(n in competitor_names for n in ("Notion", "Linear", "Airtable"))


def test_research_sales_topic_matches_sales_template():
    from tools.research_tool import research_tool
    raw = research_tool.invoke({"topic": "sales outreach strategy"})
    result = json.loads(raw)
    competitor_names = [c["name"] for c in result["competitors"]]
    assert any("Apollo" in n or "Outreach" in n or "Lemlist" in n for n in competitor_names)


def test_research_marketing_topic_matches_marketing_template():
    from tools.research_tool import research_tool
    raw = research_tool.invoke({"topic": "marketing growth"})
    result = json.loads(raw)
    # Marketing template focuses on content channels
    assert any("content" in opp.lower() or "community" in opp.lower()
               for opp in result["opportunities"])


def test_research_ops_topic_matches_ops_template():
    from tools.research_tool import research_tool
    raw = research_tool.invoke({"topic": "ops efficiency"})
    result = json.loads(raw)
    competitor_names = [c["name"] for c in result["competitors"]]
    assert any(n in competitor_names for n in ("Mixpanel", "Amplitude", "PostHog"))


def test_research_unknown_topic_defaults_gracefully():
    from tools.research_tool import research_tool
    raw = research_tool.invoke({"topic": "completely unrelated random topic xyz"})
    result = json.loads(raw)
    assert result["status"] == "success"
    assert len(result["competitors"]) > 0


# ===========================================================================
# Persistence
# ===========================================================================

def test_research_tool_persists_with_run_id():
    from tools.research_tool import research_tool
    from data.database import get_research_reports
    rid = str(uuid.uuid4())
    raw = research_tool.invoke({
        "topic": "product market",
        "product_name": "MyStartup",
        "run_id": rid,
        "cycle_count": 2,
    })
    result = json.loads(raw)
    assert result["report_id"] is not None

    reports = get_research_reports(rid)
    assert len(reports) == 1
    assert reports[0]["topic"] == "product market"
    assert reports[0]["cycle_count"] == 2


def test_research_tool_no_run_id_no_crash():
    from tools.research_tool import research_tool
    raw = research_tool.invoke({"topic": "marketing", "run_id": ""})
    result = json.loads(raw)
    assert result["status"] == "success"
    assert result["report_id"] is None


def test_persist_research_report_directly():
    from data.database import persist_research_report, get_research_reports
    rid = str(uuid.uuid4())
    report_id = persist_research_report(
        run_id=rid,
        cycle_count=1,
        topic="product",
        product_name="TestCo",
        summary="Test summary",
        competitors=[{"name": "Competitor A"}],
        audience={"primary": "Founders"},
        opportunities=["Opportunity 1"],
        risks=["Risk 1"],
        experiments=[{"name": "Experiment 1", "metric": "signup_rate", "duration_days": 7}],
    )
    assert report_id is not None
    reports = get_research_reports(rid)
    assert len(reports) == 1
    assert reports[0]["product_name"] == "TestCo"


# ===========================================================================
# API endpoint
# ===========================================================================

@pytest.fixture
def client():
    from api.server import app
    from fastapi.testclient import TestClient
    return TestClient(app)


def test_research_endpoint_returns_list(client):
    rid = str(uuid.uuid4())
    resp = client.get(f"/runs/{rid}/research")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_research_endpoint_returns_persisted_reports(client):
    from data.database import persist_research_report
    rid = str(uuid.uuid4())
    persist_research_report(
        run_id=rid,
        cycle_count=1,
        topic="marketing",
        product_name="TestCo",
        summary="Good market",
        competitors=[],
        audience={},
        opportunities=["grow"],
        risks=["compete"],
        experiments=[],
    )
    resp = client.get(f"/runs/{rid}/research")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["topic"] == "marketing"
    assert isinstance(data[0]["opportunities"], list)
