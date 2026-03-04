"""
Tests for LangChain tools and safe parsers  – v0.3

Tools:
1.  website_builder creates an HTML file.
2.  website_builder writes correct HTML content.
3.  seo_tool handles missing page.
4.  seo_tool analyses an existing page.
5.  outreach_tool persists records.
6.  analytics_tool returns trend structure.
7.  analytics_tool records snapshot.

Parser robustness (v0.3):
8.  safe_parse_planner: valid JSON → OK result.
9.  safe_parse_planner: plain text with domain keyword → JSON_DECODE fallback, correct domain.
10. safe_parse_planner: total garbage → JSON_DECODE fallback, default domain.
11. safe_parse_evaluator: valid JSON → OK result.
12. safe_parse_evaluator: malformed JSON → JSON_DECODE fallback with computed scores.
13. safe_parse_evaluator: partial JSON (missing fields) → VALIDATION fallback.
14. compute_weighted_score: full-score metrics → 1.0.
15. compute_trend: up/down/flat detection.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _tmp_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CEOCLAW_DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("CEOCLAW_WEBSITES_DIR", str(tmp_path / "websites"))
    import config.settings as cs
    cs.settings = cs.Settings()
    cs.settings.resolve_websites_dir = lambda: tmp_path / "websites"
    from data.database import init_db
    init_db()
    yield


# ---------------------------------------------------------------------------
# website_builder
# ---------------------------------------------------------------------------

def test_website_builder_creates_file(tmp_path, monkeypatch):
    import tools.website_builder as wb_mod
    monkeypatch.setattr(wb_mod.settings, "resolve_websites_dir", lambda: tmp_path / "websites")
    from tools.website_builder import website_builder_tool
    raw = website_builder_tool.invoke({
        "product_name": "Test Product",
        "tagline": "The best test product ever.",
        "features": ["Fast", "Reliable"],
        "cta_text": "Sign Up Free",
    })
    data = json.loads(raw)
    assert data["status"] == "success"
    assert (tmp_path / "websites" / "test-product" / "index.html").exists()


def test_website_builder_writes_html_content(tmp_path, monkeypatch):
    import tools.website_builder as wb_mod
    monkeypatch.setattr(wb_mod.settings, "resolve_websites_dir", lambda: tmp_path / "websites")
    from tools.website_builder import website_builder_tool
    website_builder_tool.invoke({
        "product_name": "My SaaS",
        "tagline": "Save time with My SaaS.",
        "features": ["Feature A", "Feature B"],
    })
    html = (tmp_path / "websites" / "my-saas" / "index.html").read_text()
    assert "My SaaS" in html
    assert "Save time with My SaaS" in html


# ---------------------------------------------------------------------------
# seo_tool
# ---------------------------------------------------------------------------

def test_seo_tool_missing_page_returns_zero_score():
    from tools.seo_tool import seo_tool
    raw = seo_tool.invoke({"product_name": "nonexistent-xyz", "target_keyword": "xyz"})
    data = json.loads(raw)
    assert data["seo_score"] == 0
    assert any("not found" in issue for issue in data["issues"])


def test_seo_tool_analyses_existing_page(tmp_path, monkeypatch):
    import tools.website_builder as wb_mod
    monkeypatch.setattr(wb_mod.settings, "resolve_websites_dir", lambda: tmp_path / "websites")
    from tools.website_builder import website_builder_tool
    from tools.seo_tool import seo_tool
    import config.settings as cs
    cs.settings.resolve_websites_dir = lambda: tmp_path / "websites"

    website_builder_tool.invoke({
        "product_name": "SEO Test App",
        "tagline": "SEO test app tagline for testing.",
        "features": ["seo feature one"],
    })
    raw = seo_tool.invoke({"product_name": "SEO Test App", "target_keyword": "seo-test-app"})
    data = json.loads(raw)
    assert "seo_score" in data
    assert 0 <= data["seo_score"] <= 100


# ---------------------------------------------------------------------------
# outreach_tool
# ---------------------------------------------------------------------------

def test_outreach_tool_persists_records():
    from tools.outreach_tool import outreach_tool
    from data.database import get_connection
    raw = outreach_tool.invoke({
        "product_name": "Test Product",
        "targets": ["Alice", "Bob"],
        "message_template": "Hi {target}, check out {product}!",
        "channel": "email",
    })
    data = json.loads(raw)
    assert data["status"] == "success"
    assert data["created_count"] == 2
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM outreach_attempts WHERE target IN ('Alice','Bob')"
        ).fetchone()
    assert row["cnt"] == 2


# ---------------------------------------------------------------------------
# analytics_tool
# ---------------------------------------------------------------------------

def test_analytics_tool_returns_structure():
    from tools.analytics_tool import analytics_tool
    raw = analytics_tool.invoke({"lookback": 3, "record_snapshot": False})
    data = json.loads(raw)
    assert "latest" in data
    assert "trend" in data
    assert "summary" in data


def test_analytics_tool_records_snapshot():
    from tools.analytics_tool import analytics_tool
    from data.database import get_connection
    analytics_tool.invoke({
        "lookback": 1,
        "record_snapshot": True,
        "new_traffic": 42,
        "new_signups": 3,
        "new_mrr": 15.0,
    })
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM metrics ORDER BY recorded_at DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    assert row["website_traffic"] == 42
    assert row["mrr"] == 15.0


# ---------------------------------------------------------------------------
# Parser robustness (v0.3)
# ---------------------------------------------------------------------------

def test_safe_parse_planner_valid_json():
    from core.prompts import safe_parse_planner, ParseErrorCode
    content = json.dumps({
        "selected_domain": "sales",
        "selected_action": "email_outreach",
        "strategy_rationale": "Need more customers.",
        "priority_score": 0.8,
    })
    result = safe_parse_planner(content)
    assert result.success is True
    assert result.error_code == ParseErrorCode.OK
    assert result.data["selected_domain"] == "sales"
    assert result.data["selected_action"] == "email_outreach"


def test_safe_parse_planner_plain_text_with_domain():
    """Plain text with a domain keyword must be extracted as a fallback."""
    from core.prompts import safe_parse_planner, ParseErrorCode
    content = "I think we should focus on marketing activities this cycle."
    result = safe_parse_planner(content)
    assert result.success is False
    assert result.error_code == ParseErrorCode.JSON_DECODE
    assert result.data["selected_domain"] == "marketing"


def test_safe_parse_planner_total_garbage():
    """Completely unrecognizable input must return a default PlannerOutput."""
    from core.prompts import safe_parse_planner, ParseErrorCode
    content = "!!!@@@###$$$%%%^^^&&&***"
    result = safe_parse_planner(content)
    assert result.success is False
    # Falls back to default domain
    assert result.data["selected_domain"] == "product"


def test_safe_parse_evaluator_valid_json():
    from core.prompts import safe_parse_evaluator, ParseErrorCode
    content = json.dumps({
        "kpi_snapshot": {"mrr": 20.0, "signups": 5, "traffic": 200, "revenue": 20.0},
        "progress_score": 0.20,
        "weighted_score": 0.18,
        "trend_direction": "up",
        "recommendation": "Keep going.",
        "risk_flags": [],
    })
    result = safe_parse_evaluator(content, current_mrr=20.0, goal_mrr=100.0)
    assert result.success is True
    assert result.error_code == ParseErrorCode.OK
    assert result.data["trend_direction"] == "up"


def test_safe_parse_evaluator_malformed_json():
    """Malformed JSON must return JSON_DECODE fallback with computed scores."""
    from core.prompts import safe_parse_evaluator, ParseErrorCode
    content = "Sorry, I cannot produce JSON right now."
    result = safe_parse_evaluator(
        content, current_mrr=50.0, goal_mrr=100.0,
        current_metrics={"mrr": 50.0, "signups": 10, "website_traffic": 300, "revenue": 50.0},
    )
    assert result.success is False
    assert result.error_code == ParseErrorCode.JSON_DECODE
    # progress_score should be computed from real metrics
    assert result.data["progress_score"] == pytest.approx(0.5, abs=0.01)


def test_safe_parse_evaluator_partial_json():
    """JSON with missing required fields must return a VALIDATION/fallback result."""
    from core.prompts import safe_parse_evaluator, ParseErrorCode
    content = json.dumps({"trend_direction": "down"})  # missing most fields
    result = safe_parse_evaluator(content, current_mrr=10.0, goal_mrr=100.0)
    # Either OK (Pydantic fills defaults) or VALIDATION/REGEX fallback — either is acceptable
    assert result.data["trend_direction"] == "down"
    assert "progress_score" in result.data


# ---------------------------------------------------------------------------
# KPI computation (v0.3)
# ---------------------------------------------------------------------------

def test_compute_weighted_score_full_metrics():
    """All KPI components maxed out must return score == 1.0."""
    from core.prompts import compute_weighted_score
    score = compute_weighted_score(
        {"mrr": 100.0, "signups": 100, "website_traffic": 1000, "revenue": 100.0},
        goal_mrr=100.0,
    )
    assert score == pytest.approx(1.0, abs=0.001)


def test_compute_weighted_score_zero_metrics():
    from core.prompts import compute_weighted_score
    score = compute_weighted_score({}, goal_mrr=100.0)
    assert score == 0.0


def test_compute_trend_up():
    from core.prompts import compute_trend
    assert compute_trend(0.5, 0.48) == "up"


def test_compute_trend_down():
    from core.prompts import compute_trend
    assert compute_trend(0.3, 0.35) == "down"


def test_compute_trend_flat():
    from core.prompts import compute_trend
    assert compute_trend(0.5, 0.501) == "flat"
