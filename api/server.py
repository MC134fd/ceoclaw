"""
CEOClaw FastAPI server  – v0.4 (demo-ready).

Endpoints (v0.2 – backward compatible):
    GET /health
    GET /status
    GET /metrics/latest
    GET /runs/recent

v0.3 endpoints:
    GET /runs/{run_id}
    GET /runs/{run_id}/timeline
    GET /artifacts/recent
    GET /kpi/trend

v0.4 endpoints:
    GET /summary/latest   — one-shot judge-friendly run summary
"""

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.settings import settings
from core.state_manager import StateManager
from data.database import init_db


@asynccontextmanager
async def _lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title=settings.app_name,
    description="Autonomous founder agent REST API.",
    version="0.4.0",
    lifespan=_lifespan,
)

_sm = StateManager()


# ---------------------------------------------------------------------------
# v0.2 endpoints (backward compatible)
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok", "app": settings.app_name}


@app.get("/status")
def status() -> dict[str, Any]:
    """App configuration and the most recent graph run."""
    try:
        recent = _sm.get_recent_graph_runs(limit=1)
        latest_run = recent[0] if recent else None
    except Exception:
        latest_run = None
    return {
        "app_name": settings.app_name,
        "environment": settings.environment,
        "goal_mrr": settings.default_goal_mrr,
        "mock_mode": settings.flock_mock_mode,
        "latest_run": latest_run,
    }


@app.get("/metrics/latest")
def metrics_latest() -> dict[str, Any]:
    """Most recently recorded business metrics snapshot."""
    row = _sm.get_latest_metrics()
    if row is None:
        raise HTTPException(status_code=404, detail="No metrics recorded yet.")
    return row


@app.get("/runs/recent")
def runs_recent(limit: int = 10) -> list[dict[str, Any]]:
    """The *limit* most recent graph runs."""
    try:
        return _sm.get_recent_graph_runs(limit=min(limit, 100))
    except Exception:
        return []


# ---------------------------------------------------------------------------
# v0.3 endpoints
# ---------------------------------------------------------------------------

@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    """Full details for a specific graph run."""
    row = _sm.get_graph_run(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found.")
    return row


@app.get("/runs/{run_id}/timeline")
def run_timeline(run_id: str) -> list[dict[str, Any]]:
    """Cycle-by-cycle KPI and decision timeline for a specific run."""
    if _sm.get_graph_run(run_id) is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found.")
    try:
        return _sm.get_run_timeline(run_id)
    except Exception:
        return []


@app.get("/artifacts/recent")
def artifacts_recent(limit: int = 20) -> list[dict[str, Any]]:
    """The *limit* most recently created artifacts across all runs."""
    try:
        return _sm.get_recent_artifacts(limit=min(limit, 200))
    except Exception:
        return []


@app.get("/kpi/trend")
def kpi_trend(limit: int = 20) -> list[dict[str, Any]]:
    """KPI trend across the *limit* most recent cycles (oldest→newest)."""
    try:
        return _sm.get_kpi_trend(limit=min(limit, 100))
    except Exception:
        return []


# ---------------------------------------------------------------------------
# v0.4 endpoint – judge-friendly one-shot summary
# ---------------------------------------------------------------------------

@app.get("/summary/latest")
def summary_latest() -> dict[str, Any]:
    """One-shot summary of the most recent run for demo and judging.

    Never returns 500 — returns a ``status`` field indicating data availability.
    """
    try:
        runs = _sm.get_recent_graph_runs(limit=1)
        if not runs:
            return {"status": "no_runs", "message": "No runs recorded yet."}

        run = runs[0]
        run_id: str = run["run_id"]

        # Scope KPI trend to this run only (not cross-run global trend)
        trend = _sm.get_run_timeline(run_id)
        run_artifacts = _sm.get_run_artifacts(run_id)

        final_weighted = trend[-1]["weighted_score"] if trend else 0.0
        final_mrr = trend[-1]["mrr"] if trend else 0.0

        return {
            "status": "ok",
            "run_id": run_id,
            "run_status": run["status"],
            "goal_mrr": run["goal_mrr"],
            "cycles_run": run["cycles_run"],
            "stop_reason": run["stop_reason"],
            "final_mrr": final_mrr,
            "final_weighted_score": final_weighted,
            "kpi_trend": trend,
            "artifact_count": len(run_artifacts),
            "recent_artifacts": run_artifacts[:5],
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}
