"""
CEOClaw StateManager  – v0.3 extended.

New in v0.3:
  - get_graph_run(run_id)
  - get_run_timeline(run_id)
  - get_recent_artifacts(limit)
  - get_kpi_trend(limit)
"""

from typing import Any, Optional

from data.database import get_connection, utc_now


class StateManager:
    """Centralised store for runtime business metrics and loop-run tracking."""

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def get_latest_metrics(self) -> Optional[dict[str, Any]]:
        """Return the most recently recorded metrics row, or None if empty."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM metrics ORDER BY recorded_at DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def record_metrics(
        self,
        website_traffic: int = 0,
        signups: int = 0,
        conversion_rate: float = 0.0,
        revenue: float = 0.0,
        mrr: float = 0.0,
    ) -> int:
        """Insert a new metrics snapshot and return its row id."""
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO metrics
                    (recorded_at, website_traffic, signups,
                     conversion_rate, revenue, mrr)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (utc_now(), website_traffic, signups, conversion_rate, revenue, mrr),
            )
        return cursor.lastrowid  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Loop runs (backward-compatible)
    # ------------------------------------------------------------------

    def start_loop_run(self, action_taken: Optional[str] = None) -> int:
        with get_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO loop_runs (started_at, action_taken, status) VALUES (?, ?, ?)",
                (utc_now(), action_taken, "running"),
            )
        return cursor.lastrowid  # type: ignore[return-value]

    def finish_loop_run(self, run_id: int, outcome: str, status: str = "completed") -> None:
        with get_connection() as conn:
            conn.execute(
                "UPDATE loop_runs SET finished_at=?, outcome=?, status=? WHERE id=?",
                (utc_now(), outcome, status, run_id),
            )

    def get_recent_loop_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM loop_runs ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Graph runs
    # ------------------------------------------------------------------

    def get_recent_graph_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return the *limit* most recent graph_runs, newest first."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM graph_runs ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_graph_run(self, run_id: str) -> Optional[dict[str, Any]]:
        """Return a single graph_run row by run_id, or None."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM graph_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Node executions
    # ------------------------------------------------------------------

    def get_node_executions(
        self, run_id: Optional[str] = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        with get_connection() as conn:
            if run_id:
                rows = conn.execute(
                    "SELECT * FROM node_executions WHERE run_id=? ORDER BY started_at ASC LIMIT ?",
                    (run_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM node_executions ORDER BY started_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Timeline (v0.3)
    # ------------------------------------------------------------------

    def get_run_timeline(self, run_id: str) -> list[dict[str, Any]]:
        """Return cycle-by-cycle KPI and decision data for *run_id*.

        Joins cycle_scores with the first planner node_execution of each
        cycle to capture rationale.
        """
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT cs.*
                FROM   cycle_scores cs
                WHERE  cs.run_id = ?
                ORDER  BY cs.cycle_count ASC
                """,
                (run_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Artifacts (v0.3)
    # ------------------------------------------------------------------

    def get_recent_artifacts(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return the *limit* most recently created artifacts, newest first."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM artifacts ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_run_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        """Return all artifacts for a specific run."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM artifacts WHERE run_id=? ORDER BY created_at ASC",
                (run_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # KPI trend (v0.3)
    # ------------------------------------------------------------------

    def get_kpi_trend(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return the *limit* most recent cycle_scores rows, oldest first.

        Suitable for plotting a KPI trend chart over time.
        """
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM   cycle_scores
                ORDER  BY recorded_at DESC
                LIMIT  ?
                """,
                (limit,),
            ).fetchall()
        # Return oldest→newest for chart ordering
        return [dict(r) for r in reversed(rows)]

    # ------------------------------------------------------------------
    # Dashboard (backward-compatible)
    # ------------------------------------------------------------------

    def get_dashboard_state(self) -> dict[str, Any]:
        return {
            "latest_metrics": self.get_latest_metrics(),
            "recent_runs": self.get_recent_loop_runs(limit=20),
            "recent_graph_runs": self.get_recent_graph_runs(limit=5),
        }
