"""
analytics_tool – LangChain tool.

Reads the latest metrics from SQLite, computes trend deltas against the
previous snapshot, and returns a structured analytics summary.
"""

import json

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from data.database import get_connection, utc_now


class AnalyticsToolInput(BaseModel):
    lookback: int = Field(
        default=5,
        description="Number of recent metric snapshots to analyse.",
    )
    record_snapshot: bool = Field(
        default=False,
        description="When True, write a new metrics row with current totals.",
    )
    new_traffic: int = Field(default=0, description="New website traffic to add (if recording).")
    new_signups: int = Field(default=0, description="New signups to add (if recording).")
    new_mrr: float = Field(default=0.0, description="New MRR value to record (if recording).")


@tool("analytics_tool", args_schema=AnalyticsToolInput)
def analytics_tool(
    lookback: int = 5,
    record_snapshot: bool = False,
    new_traffic: int = 0,
    new_signups: int = 0,
    new_mrr: float = 0.0,
) -> str:
    """Read recent metrics and optionally record a new snapshot.

    Returns a JSON string with: latest, trend, summary.
    """
    if record_snapshot:
        _record_metrics(new_traffic, new_signups, new_mrr)

    snapshots = _fetch_recent(lookback)
    latest = snapshots[0] if snapshots else {}
    prev = snapshots[1] if len(snapshots) > 1 else {}

    trend = {
        "traffic_delta": latest.get("website_traffic", 0) - prev.get("website_traffic", 0),
        "signup_delta": latest.get("signups", 0) - prev.get("signups", 0),
        "mrr_delta": round(
            latest.get("mrr", 0.0) - prev.get("mrr", 0.0), 2
        ),
    }

    summary = _summarise(latest, trend)

    return json.dumps({
        "latest": latest,
        "trend": trend,
        "summary": summary,
        "snapshots_analysed": len(snapshots),
    })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch_recent(limit: int) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM   metrics
            ORDER  BY recorded_at DESC
            LIMIT  ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def _record_metrics(traffic: int, signups: int, mrr: float) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO metrics
                (recorded_at, website_traffic, signups, conversion_rate, revenue, mrr)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                utc_now(),
                traffic,
                signups,
                round(signups / traffic, 4) if traffic > 0 else 0.0,
                mrr,
                mrr,
            ),
        )


def _summarise(latest: dict, trend: dict) -> str:
    mrr = latest.get("mrr", 0.0)
    mrr_delta = trend.get("mrr_delta", 0.0)
    if mrr == 0:
        return "No revenue recorded yet. Focus on product and outreach."
    if mrr_delta > 0:
        return f"MRR growing: ${mrr:.2f} (+${mrr_delta:.2f} vs previous snapshot)."
    if mrr_delta < 0:
        return f"MRR declining: ${mrr:.2f} (${mrr_delta:.2f} vs previous snapshot). Investigate churn."
    return f"MRR stable at ${mrr:.2f}."
