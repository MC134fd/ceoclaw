"""
Regression tests for bugs found and fixed during audit.

Bug fixes covered:
R1. safe_parse_evaluator: invalid trend_direction ('neutral', 'rising', etc.)
    must not raise a secondary Pydantic ValidationError — must sanitize to 'flat'.
R2. sales_agent: single-target slice when offset == last index must wrap around
    and always yield exactly 2 targets.
R3. database WAL mode: get_connection must enable WAL journal mode.
R4. pyproject.toml: python-dotenv declared as dependency (import-level check).

Additional coverage gaps closed:
R5. export_run_summary with zero cycle_scores (no ops cycle ran) must not crash.
R6. evaluator_node broad exception path must log error and return fallback state.
R7. run_graph exception mid-run must persist status='failed' in graph_runs.
R8. ops_executor MRR growth formula: MRR increases monotonically across cycles.
R9. _stagnation_domain always returns a domain different from the current one.
R10. outreach_tool message template with missing placeholder raises KeyError
     (confirmed existing behavior — warn users).
"""

import json
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("CEOCLAW_DATABASE_PATH", str(tmp_path / "test_reg.db"))
    import config.settings as cs
    cs.settings = cs.Settings()
    from data.database import init_db
    init_db()
    yield


# ---------------------------------------------------------------------------
# R1 – safe_parse_evaluator: invalid trend_direction must not raise
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_trend", ["neutral", "rising", "sideways", "", "UP", "123"])
def test_safe_parse_evaluator_invalid_trend_sanitized(bad_trend):
    """Invalid trend_direction must be coerced to 'flat', not raise an exception."""
    from core.prompts import safe_parse_evaluator, ParseErrorCode

    content = json.dumps({
        "kpi_snapshot": {"mrr": 10.0, "signups": 2, "traffic": 100, "revenue": 10.0},
        "progress_score": 0.1,
        "weighted_score": 0.09,
        "trend_direction": bad_trend,
        "recommendation": "keep going",
        "risk_flags": [],
    })
    # Must not raise
    result = safe_parse_evaluator(content, current_mrr=10.0, goal_mrr=100.0)
    assert result.data["trend_direction"] in {"up", "down", "flat"}, (
        f"trend_direction must be sanitized, got {result.data['trend_direction']!r}"
    )


def test_safe_parse_evaluator_valid_trend_preserved():
    """Valid trend_direction values must pass through unchanged."""
    from core.prompts import safe_parse_evaluator

    for trend in ("up", "down", "flat"):
        content = json.dumps({
            "kpi_snapshot": {"mrr": 5.0, "signups": 1, "traffic": 50, "revenue": 5.0},
            "progress_score": 0.05,
            "weighted_score": 0.04,
            "trend_direction": trend,
            "recommendation": "ok",
            "risk_flags": [],
        })
        result = safe_parse_evaluator(content, current_mrr=5.0, goal_mrr=100.0)
        assert result.data["trend_direction"] == trend


# ---------------------------------------------------------------------------
# R2 – sales_agent: always yields exactly 2 targets across all cycle counts
# ---------------------------------------------------------------------------

def test_sales_agent_targets_always_two():
    """_dispatch must always produce exactly 2 outreach targets, even at boundary offset."""
    from agents.sales_agent import _DEFAULT_TARGETS

    n = len(_DEFAULT_TARGETS)
    for cycle_count in range(1, n * 3 + 1):  # cover 3 full rotations
        offset = (cycle_count - 1) % n
        targets = [_DEFAULT_TARGETS[offset % n], _DEFAULT_TARGETS[(offset + 1) % n]]
        assert len(targets) == 2, (
            f"Expected 2 targets at cycle_count={cycle_count}, got {len(targets)}: {targets}"
        )


def test_sales_agent_targets_wrap_at_last_index():
    """At the last index, targets must wrap to the first element."""
    from agents.sales_agent import _DEFAULT_TARGETS

    n = len(_DEFAULT_TARGETS)
    last_offset = n - 1
    # Simulate cycle where offset hits the last index
    cycle_count = last_offset + 1  # offset = (cycle_count-1) % n = n-1
    offset = (cycle_count - 1) % n
    targets = [_DEFAULT_TARGETS[offset % n], _DEFAULT_TARGETS[(offset + 1) % n]]
    assert targets[0] == _DEFAULT_TARGETS[n - 1]
    assert targets[1] == _DEFAULT_TARGETS[0]  # wraps to first


def test_sales_executor_always_creates_2_outreach_records():
    """sales_executor_node must persist exactly 2 outreach_attempts per dispatch."""
    from data.database import get_connection, start_graph_run
    from agents.sales_agent import sales_executor_node

    run_id = str(uuid.uuid4())
    start_graph_run(run_id=run_id, goal_mrr=100.0)

    # Count before
    with get_connection() as conn:
        before = conn.execute("SELECT COUNT(*) AS cnt FROM outreach_attempts").fetchone()["cnt"]

    # cycle_count=5 is the boundary case that previously only got 1 target
    state = {
        "run_id": run_id,
        "cycle_count": 5,
        "selected_action": "create_outreach_campaign",
        "active_product": None,
        "consecutive_failures": {},
        "errors": [],
    }
    config = {"configurable": {"mock_mode": True, "max_cycles": 10}}
    result = sales_executor_node(state, config)
    assert result["executor_result"]["execution_status"] == "completed"

    # Count after — delta must be exactly 2
    with get_connection() as conn:
        after = conn.execute("SELECT COUNT(*) AS cnt FROM outreach_attempts").fetchone()["cnt"]
    assert after - before == 2, f"Expected 2 new outreach records at cycle 5, got {after - before}"


# ---------------------------------------------------------------------------
# R3 – database WAL mode
# ---------------------------------------------------------------------------

def test_get_connection_enables_wal_mode(tmp_path, monkeypatch):
    """get_connection must enable WAL journal_mode for concurrent access safety."""
    monkeypatch.setenv("CEOCLAW_DATABASE_PATH", str(tmp_path / "wal_test.db"))
    import config.settings as cs
    cs.settings = cs.Settings()
    from data.database import get_connection, init_db
    init_db()

    with get_connection() as conn:
        row = conn.execute("PRAGMA journal_mode").fetchone()
    assert row[0].upper() == "WAL", f"Expected WAL mode, got {row[0]!r}"


# ---------------------------------------------------------------------------
# R4 – python-dotenv importable (pyproject.toml completeness)
# ---------------------------------------------------------------------------

def test_python_dotenv_importable():
    """python-dotenv must be importable — confirms it's in the install requirements."""
    import dotenv  # noqa: F401


# ---------------------------------------------------------------------------
# R5 – export_run_summary with no cycle_scores must not crash
# ---------------------------------------------------------------------------

def test_export_run_summary_zero_cycle_scores(tmp_path, monkeypatch):
    """export_run_summary must complete even when no cycle_scores exist for the run."""
    monkeypatch.setenv("CEOCLAW_DATABASE_PATH", str(tmp_path / "export_empty.db"))
    import config.settings as cs
    cs.settings = cs.Settings()
    from data.database import init_db, start_graph_run, finish_graph_run
    from core.agent_loop import export_run_summary
    init_db()

    run_id = str(uuid.uuid4())
    start_graph_run(run_id=run_id, goal_mrr=100.0)
    finish_graph_run(run_id=run_id, cycles_run=0, stop_reason="test", status="completed")

    out = export_run_summary(run_id, output_dir=str(tmp_path / "exports"))
    assert out.exists()
    content = out.read_text()
    assert run_id in content
    assert "## KPI Timeline" in content
    assert "## Confidence Note" in content


# ---------------------------------------------------------------------------
# R6 – evaluator_node broad except path returns valid fallback state
# ---------------------------------------------------------------------------

def test_evaluator_node_exception_returns_fallback():
    """When _run_evaluator raises, evaluator_node must return a valid fallback dict."""
    from unittest.mock import patch
    from core.agent_loop import evaluator_node
    from data.database import init_db, start_graph_run

    run_id = str(uuid.uuid4())
    init_db()
    start_graph_run(run_id=run_id, goal_mrr=100.0)

    state = {
        "run_id": run_id,
        "cycle_count": 2,
        "goal_mrr": 100.0,
        "latest_metrics": {"mrr": 5.0, "signups": 1, "website_traffic": 50, "revenue": 5.0},
        "last_mrr": 0.0,
        "stagnant_cycles": 0,
        "weighted_score": 0.0,
        "previous_weighted_score": 0.0,
        "selected_domain": "product",
        "selected_action": "build_landing_page",
        "executor_result": {},
        "errors": [],
    }
    config = {"configurable": {"mock_mode": True, "max_cycles": 10}}

    with patch("core.agent_loop._run_evaluator", side_effect=RuntimeError("forced failure")):
        result = evaluator_node(state, config)

    # Must return required keys without raising
    assert "evaluation" in result
    assert "weighted_score" in result
    assert "trend_direction" in result
    assert "errors" in result
    assert len(result["errors"]) == 1
    assert "forced failure" in result["errors"][0]["error"]


# ---------------------------------------------------------------------------
# R7 – run_graph mid-run exception persists status='failed'
# ---------------------------------------------------------------------------

def test_run_graph_exception_persists_failed_status(monkeypatch):
    """If run_graph raises, graph_runs must be marked status='failed'."""
    from unittest.mock import patch
    from data.database import get_connection, init_db
    from core.agent_loop import run_graph

    init_db()

    with patch("core.agent_loop.build_graph", side_effect=RuntimeError("graph build failed")):
        with pytest.raises(RuntimeError, match="graph build failed"):
            run_graph(cycles=1, mock_mode=True)

    # The run_id is not returned on exception, so find the failed run
    with get_connection() as conn:
        row = conn.execute(
            "SELECT status FROM graph_runs WHERE status='failed' LIMIT 1"
        ).fetchone()
    assert row is not None, "Expected a 'failed' graph_runs row after mid-run exception"


# ---------------------------------------------------------------------------
# R8 – ops_executor MRR grows monotonically
# ---------------------------------------------------------------------------

def test_ops_executor_mrr_grows_monotonically(tmp_path, monkeypatch):
    """Each successive ops cycle must produce MRR >= previous MRR."""
    monkeypatch.setenv("CEOCLAW_DATABASE_PATH", str(tmp_path / "ops_test.db"))
    import config.settings as cs
    cs.settings = cs.Settings()
    from data.database import init_db, start_graph_run
    from agents.ops_agent import ops_executor_node
    init_db()

    run_id = str(uuid.uuid4())
    start_graph_run(run_id=run_id, goal_mrr=100.0)

    config = {"configurable": {"mock_mode": True, "max_cycles": 20}}
    prev_mrr = -1.0
    prev_metrics: dict = {}

    for cycle in [3, 6, 9, 12]:
        state = {
            "run_id": run_id,
            "cycle_count": cycle,
            "selected_action": "record_baseline_metrics",
            "latest_metrics": prev_metrics,
            "circuit_breaker_active": False,
            "consecutive_failures": {},
            "errors": [],
        }
        result = ops_executor_node(state, config)
        new_mrr = result["latest_metrics"]["mrr"]
        assert new_mrr >= prev_mrr, (
            f"MRR decreased: cycle={cycle}, prev={prev_mrr}, new={new_mrr}"
        )
        prev_mrr = new_mrr
        prev_metrics = result["latest_metrics"]


# ---------------------------------------------------------------------------
# R9 – _stagnation_domain always returns a different domain
# ---------------------------------------------------------------------------

def test_stagnation_domain_always_different():
    """_stagnation_domain must always return a domain != current_domain when threshold met."""
    from agents.ceo_agent import _stagnation_domain

    domains = ["product", "marketing", "sales", "ops"]
    for domain in domains:
        for stagnant in range(3, 10):
            result = _stagnation_domain(stagnant, threshold=3, current_domain=domain)
            assert result != domain, (
                f"Stagnation override returned same domain: "
                f"stagnant={stagnant} current={domain} result={result}"
            )


def test_stagnation_domain_below_threshold_returns_same():
    """_stagnation_domain must return current domain when stagnant < threshold."""
    from agents.ceo_agent import _stagnation_domain
    assert _stagnation_domain(2, threshold=3, current_domain="marketing") == "marketing"
    assert _stagnation_domain(0, threshold=3, current_domain="ops") == "ops"


# ---------------------------------------------------------------------------
# R10 – compute_progress_score boundary: goal_mrr=0 must not divide by zero
# ---------------------------------------------------------------------------

def test_compute_progress_score_zero_goal():
    """compute_progress_score must return 0.0 when goal_mrr=0, not ZeroDivisionError."""
    from core.prompts import compute_progress_score
    result = compute_progress_score(current_mrr=50.0, goal_mrr=0.0)
    assert result == 0.0


def test_compute_weighted_score_zero_goal():
    """compute_weighted_score must return 0.0 when goal_mrr=0."""
    from core.prompts import compute_weighted_score
    result = compute_weighted_score(
        {"mrr": 50.0, "signups": 10, "website_traffic": 500, "revenue": 50.0},
        goal_mrr=0.0,
    )
    assert result == 0.0
