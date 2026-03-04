"""
Tests for agent routing and stop condition  – v0.3

1.  RouterNode routes correctly for each domain.
2.  RouterNode fallback on invalid domain.
3.  _route_from_router key mapping.
4.  StopCheckNode stops at goal MRR.
5.  StopCheckNode stops at max_cycles.
6.  StopCheckNode continues below goal.
7.  PlannerNode returns required keys.
8.  RouterNode circuit-breaker: 3 consecutive failures → ops.
9.  Stagnation domain rotation: planner switches domain after N stagnant cycles.
10. StopCheckNode stops when weighted_score >= 1.0.
"""

import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("CEOCLAW_DATABASE_PATH", str(tmp_path / "test.db"))
    import config.settings as cs
    cs.settings = cs.Settings()
    from data.database import init_db
    init_db()
    yield


def _base_state(domain="product", cycle=1, mrr=0.0, goal_mrr=100.0,
                consecutive_failures=None, stagnant_cycles=0):
    from agents import CEOClawState
    return CEOClawState(
        run_id=str(uuid.uuid4()),
        cycle_count=cycle,
        goal_mrr=goal_mrr,
        latest_metrics={"mrr": mrr, "signups": 0, "website_traffic": 0, "revenue": 0.0},
        active_product=None,
        strategy={},
        selected_action="build_landing_page",
        selected_domain=domain,
        executor_result={},
        evaluation={"progress_score": mrr / goal_mrr if goal_mrr else 0},
        weighted_score=0.0,
        previous_weighted_score=0.0,
        trend_direction="flat",
        stagnant_cycles=stagnant_cycles,
        last_mrr=0.0,
        consecutive_failures=consecutive_failures or {},
        circuit_breaker_active=False,
        tokens_used=0,
        external_calls=0,
        errors=[],
        stop_reason=None,
        should_stop=False,
    )


def _config(mock_mode=True, max_cycles=10):
    return {"configurable": {"mock_mode": mock_mode, "max_cycles": max_cycles}}


# ---------------------------------------------------------------------------
# Router tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("domain", ["product", "marketing", "sales", "ops"])
def test_router_routes_correct_domain(domain):
    """RouterNode must preserve the selected_domain for valid values."""
    from core.agent_loop import router_node
    state = _base_state(domain=domain)
    result = router_node(state, _config())
    assert result["selected_domain"] == domain


def test_router_fallback_on_invalid_domain():
    """RouterNode must fall back to 'product' when domain is invalid."""
    from core.agent_loop import router_node
    state = dict(_base_state(domain="product"))
    state["selected_domain"] = "finance"
    result = router_node(state, _config())
    assert result["selected_domain"] == "product"


@pytest.mark.parametrize("domain,expected_key", [
    ("product",   "product_executor"),
    ("marketing", "marketing_executor"),
    ("sales",     "sales_executor"),
    ("ops",       "ops_executor"),
])
def test_route_from_router_returns_correct_key(domain, expected_key):
    """_route_from_router must map each domain to the correct node name."""
    from core.agent_loop import _route_from_router
    state = _base_state(domain=domain)
    assert _route_from_router(state) == expected_key


# ---------------------------------------------------------------------------
# Circuit breaker route tests (v0.3)
# ---------------------------------------------------------------------------

def test_router_circuit_breaker_activates_on_three_failures():
    """RouterNode must route to ops when executor has 3+ consecutive failures."""
    from core.agent_loop import router_node
    state = _base_state(
        domain="marketing",
        consecutive_failures={"marketing_executor": 3},
    )
    result = router_node(state, _config())
    assert result["selected_domain"] == "ops"
    assert result.get("circuit_breaker_active") is True


def test_router_circuit_breaker_not_triggered_below_threshold():
    """RouterNode must NOT activate circuit breaker with < 3 failures."""
    from core.agent_loop import router_node
    state = _base_state(
        domain="sales",
        consecutive_failures={"sales_executor": 2},
    )
    result = router_node(state, _config())
    assert result["selected_domain"] == "sales"
    assert result.get("circuit_breaker_active") is False


# ---------------------------------------------------------------------------
# StopCheck tests
# ---------------------------------------------------------------------------

def test_stop_check_stops_at_goal_mrr():
    from core.agent_loop import stop_check_node
    state = _base_state(mrr=100.0, goal_mrr=100.0, cycle=3)
    state["evaluation"] = {"progress_score": 1.0}
    result = stop_check_node(state, _config(max_cycles=20))
    assert result["should_stop"] is True
    assert result["stop_reason"] == "goal_mrr_reached"


def test_stop_check_stops_at_max_cycles():
    from core.agent_loop import stop_check_node
    state = _base_state(mrr=0.0, goal_mrr=100.0, cycle=5)
    state["evaluation"] = {"progress_score": 0.0}
    result = stop_check_node(state, _config(max_cycles=5))
    assert result["should_stop"] is True
    assert "max_cycles" in result["stop_reason"]


def test_stop_check_continues_below_goal():
    from core.agent_loop import stop_check_node
    state = _base_state(mrr=10.0, goal_mrr=100.0, cycle=2)
    state["evaluation"] = {"progress_score": 0.1}
    result = stop_check_node(state, _config(max_cycles=20))
    assert result["should_stop"] is False
    assert result["stop_reason"] is None


def test_stop_check_stops_on_full_weighted_score():
    """StopCheckNode must stop when weighted_score >= 1.0 even if MRR < goal."""
    from core.agent_loop import stop_check_node
    state = dict(_base_state(mrr=50.0, goal_mrr=100.0, cycle=5))
    state["weighted_score"] = 1.0
    state["evaluation"] = {"progress_score": 0.5}
    result = stop_check_node(state, _config(max_cycles=20))
    assert result["should_stop"] is True
    assert result["stop_reason"] == "full_kpi_score_reached"


# ---------------------------------------------------------------------------
# Planner tests
# ---------------------------------------------------------------------------

def test_planner_node_returns_required_keys():
    """planner_node must return selected_domain, selected_action, strategy, cycle_count."""
    from agents.ceo_agent import planner_node
    state = _base_state(cycle=0)
    result = planner_node(state, _config(mock_mode=True))
    assert "selected_domain" in result
    assert "selected_action" in result
    assert "strategy" in result
    assert "cycle_count" in result
    assert result["selected_domain"] in {"product", "marketing", "sales", "ops"}


def test_planner_stagnation_forces_domain_rotation():
    """When stagnant_cycles >= threshold, planner must NOT pick the same domain."""
    from agents.ceo_agent import planner_node
    # Cycle repeatedly until stagnation threshold is reached.
    # We simulate stagnant_cycles=3 and check the domain rotates.
    state = dict(_base_state(domain="marketing", stagnant_cycles=3))
    state["selected_domain"] = "marketing"

    results: set[str] = set()
    for _ in range(5):
        r = planner_node(state, _config(mock_mode=True))
        results.add(r["selected_domain"])

    # At least one call should have switched away from marketing
    # (stagnation override cycles through alternatives)
    assert "marketing" not in results or len(results) > 1, (
        "Stagnation override should have switched domain away from marketing"
    )
