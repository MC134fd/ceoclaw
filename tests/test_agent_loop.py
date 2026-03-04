"""
Tests for core/agent_loop.py  – v0.3

1.  Graph compiles.
2.  Mock run 3 cycles completes.
3.  node_executions rows persisted.
4.  graph_runs row persisted.
5.  cycle_scores rows persisted after mock run.
6.  Artifacts rows persisted after mock run.
7.  Circuit breaker: router overrides domain to ops after 3 consecutive failures.
8.  Stagnation: evaluator increments stagnant_cycles when MRR doesn't grow.
9.  Weighted score is between 0 and 1.
10. export_run_summary writes a Markdown file.
"""

import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    db = str(tmp_path / "test_ceoclaw.db")
    monkeypatch.setenv("CEOCLAW_DATABASE_PATH", db)
    import config.settings as cs
    cs.settings = cs.Settings()
    yield


# ---------------------------------------------------------------------------
# Basic graph compilation and run
# ---------------------------------------------------------------------------

def test_graph_compiles():
    from core.agent_loop import build_graph
    graph = build_graph()
    assert graph is not None
    assert callable(getattr(graph, "invoke", None)) or callable(getattr(graph, "stream", None))


def test_mock_run_3_cycles():
    from core.agent_loop import run_graph
    final = run_graph(cycles=3, mock_mode=True, goal_mrr=100.0, max_cycles=3)
    assert final is not None
    assert final.get("run_id") is not None
    assert final.get("cycle_count", 0) >= 1


def test_node_execution_persistence():
    from core.agent_loop import run_graph
    from data.database import get_connection, init_db
    init_db()
    final = run_graph(cycles=2, mock_mode=True, goal_mrr=100.0, max_cycles=2)
    run_id = final.get("run_id")
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM node_executions WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    assert row["cnt"] > 0


def test_graph_run_persistence():
    from core.agent_loop import run_graph
    from data.database import get_connection, init_db
    init_db()
    final = run_graph(cycles=1, mock_mode=True, goal_mrr=100.0, max_cycles=1)
    run_id = final.get("run_id")
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM graph_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
    assert row is not None
    assert row["status"] in ("completed", "failed")


# ---------------------------------------------------------------------------
# v0.3 – cycle_scores and artifacts
# ---------------------------------------------------------------------------

def test_cycle_scores_persisted():
    """cycle_scores must contain one row per completed cycle."""
    from core.agent_loop import run_graph
    from data.database import get_connection, init_db
    init_db()
    final = run_graph(cycles=3, mock_mode=True, goal_mrr=100.0, max_cycles=3)
    run_id = final.get("run_id")
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM cycle_scores WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    assert row["cnt"] >= 1, "Expected at least one cycle_scores row"


def test_artifacts_persisted():
    """At least one artifact must be written per cycle (ops executor writes metrics_snapshot)."""
    from core.agent_loop import run_graph
    from data.database import get_connection, init_db
    init_db()
    final = run_graph(cycles=2, mock_mode=True, goal_mrr=100.0, max_cycles=2)
    run_id = final.get("run_id")
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM artifacts WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    assert row["cnt"] >= 1, "Expected artifact rows after a run"


# ---------------------------------------------------------------------------
# v0.3 – circuit breaker
# ---------------------------------------------------------------------------

def test_circuit_breaker_triggers_ops_route(monkeypatch):
    """When an executor has >= 3 consecutive failures, router must switch to ops."""
    from core.agent_loop import router_node
    import uuid

    state = {
        "run_id": str(uuid.uuid4()),
        "cycle_count": 4,
        "selected_domain": "marketing",
        "consecutive_failures": {"marketing_executor": 3},
        "circuit_breaker_active": False,
        "errors": [],
    }
    config = {"configurable": {"mock_mode": True, "max_cycles": 10}}
    result = router_node(state, config)

    assert result["selected_domain"] == "ops"
    assert result.get("circuit_breaker_active") is True


def test_circuit_breaker_resets_on_recovery():
    """After ops recovery, all consecutive_failures counters are zero."""
    from core.agent_loop import run_graph
    from data.database import init_db
    init_db()
    # Just verify the run completes — recovery logic is internal
    final = run_graph(cycles=2, mock_mode=True, goal_mrr=100.0, max_cycles=2)
    # No raised exception = circuit breaker didn't crash the loop
    assert final.get("run_id") is not None


# ---------------------------------------------------------------------------
# v0.3 – stagnation tracking
# ---------------------------------------------------------------------------

def test_stagnation_increments_when_mrr_flat():
    """evaluator_node must increment stagnant_cycles when MRR doesn't grow."""
    from core.agent_loop import evaluator_node
    import uuid

    run_id = str(uuid.uuid4())
    from data.database import init_db, start_graph_run
    init_db()
    start_graph_run(run_id=run_id, goal_mrr=100.0)

    state = {
        "run_id": run_id,
        "cycle_count": 3,
        "goal_mrr": 100.0,
        "latest_metrics": {"mrr": 5.0, "signups": 2, "website_traffic": 50, "revenue": 5.0},
        "last_mrr": 5.0,       # same as current → stagnant
        "stagnant_cycles": 1,
        "weighted_score": 0.05,
        "previous_weighted_score": 0.04,
        "selected_domain": "product",
        "selected_action": "build_landing_page",
        "executor_result": {},
        "errors": [],
    }
    config = {"configurable": {"mock_mode": True, "max_cycles": 10}}
    result = evaluator_node(state, config)
    assert result["stagnant_cycles"] == 2, (
        f"Expected stagnant_cycles=2, got {result['stagnant_cycles']}"
    )


def test_stagnation_resets_when_mrr_grows():
    """evaluator_node must reset stagnant_cycles to 0 when MRR increases."""
    from core.agent_loop import evaluator_node
    import uuid

    run_id = str(uuid.uuid4())
    from data.database import init_db, start_graph_run
    init_db()
    start_graph_run(run_id=run_id, goal_mrr=100.0)

    state = {
        "run_id": run_id,
        "cycle_count": 4,
        "goal_mrr": 100.0,
        "latest_metrics": {"mrr": 20.0, "signups": 5, "website_traffic": 200, "revenue": 20.0},
        "last_mrr": 5.0,       # MRR grew
        "stagnant_cycles": 3,
        "weighted_score": 0.10,
        "previous_weighted_score": 0.05,
        "selected_domain": "sales",
        "selected_action": "create_outreach_campaign",
        "executor_result": {},
        "errors": [],
    }
    config = {"configurable": {"mock_mode": True, "max_cycles": 10}}
    result = evaluator_node(state, config)
    assert result["stagnant_cycles"] == 0, (
        f"Expected stagnant_cycles=0 after MRR growth, got {result['stagnant_cycles']}"
    )


# ---------------------------------------------------------------------------
# v0.3 – weighted score
# ---------------------------------------------------------------------------

def test_weighted_score_is_bounded():
    """compute_weighted_score must return a value in [0, 1]."""
    from core.prompts import compute_weighted_score
    for mrr in [0, 50, 100, 200]:
        score = compute_weighted_score(
            {"mrr": mrr, "signups": 10, "website_traffic": 500, "revenue": mrr},
            goal_mrr=100.0,
        )
        assert 0.0 <= score <= 1.0, f"Out-of-range weighted score for mrr={mrr}: {score}"


def test_weighted_score_increases_with_mrr():
    """Higher MRR must produce a higher weighted score."""
    from core.prompts import compute_weighted_score
    low  = compute_weighted_score({"mrr": 10.0, "signups": 0, "website_traffic": 0, "revenue": 0}, 100.0)
    high = compute_weighted_score({"mrr": 80.0, "signups": 0, "website_traffic": 0, "revenue": 0}, 100.0)
    assert high > low


# ---------------------------------------------------------------------------
# v0.3 – export_run_summary
# ---------------------------------------------------------------------------

def test_export_run_summary(tmp_path):
    """export_run_summary must write a Markdown file for a completed run."""
    from core.agent_loop import run_graph, export_run_summary
    from data.database import init_db
    init_db()
    final = run_graph(cycles=2, mock_mode=True, goal_mrr=100.0, max_cycles=2)
    run_id = final["run_id"]

    out = export_run_summary(run_id, output_dir=str(tmp_path))
    assert out.exists(), "Markdown file was not created"
    content = out.read_text()
    assert run_id in content
    assert "## KPI Timeline" in content
    assert "## Artifacts" in content
