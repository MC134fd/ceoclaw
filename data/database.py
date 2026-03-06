"""
CEOClaw database utilities.

Provides SQLite connection helpers, schema initialisation, and helpers for
persisting graph execution data.  All schema changes are idempotent
(CREATE TABLE IF NOT EXISTS).

Tables:
  Original  : ideas, products, marketing_experiments, outreach_attempts,
              metrics, loop_runs, memory_entries
  LangGraph : graph_runs, graph_checkpoints, node_executions
  v0.3      : artifacts, cycle_scores
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Optional

from config.settings import settings


# ---------------------------------------------------------------------------
# Timestamp helper
# ---------------------------------------------------------------------------

def utc_now() -> str:
    """Return the current UTC time as an ISO-8601 string (microseconds)."""
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Connection factory
# ---------------------------------------------------------------------------

def _db_path() -> Path:
    return settings.resolve_db_path()


@contextmanager
def get_connection() -> Generator[sqlite3.Connection, None, None]:
    """Yield a SQLite connection with row_factory and foreign keys enabled."""
    db_file = _db_path()
    db_file.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema – original tables
# ---------------------------------------------------------------------------

_SCHEMA_ORIGINAL = """
CREATE TABLE IF NOT EXISTS ideas (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT    NOT NULL,
    title       TEXT    NOT NULL,
    description TEXT    NOT NULL,
    status      TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at         TEXT    NOT NULL,
    idea_id            INTEGER,
    name               TEXT    NOT NULL,
    landing_page_path  TEXT,
    status             TEXT    NOT NULL,
    FOREIGN KEY (idea_id) REFERENCES ideas (id)
);

CREATE TABLE IF NOT EXISTS marketing_experiments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT    NOT NULL,
    product_id  INTEGER,
    channel     TEXT    NOT NULL,
    content     TEXT    NOT NULL,
    impressions INTEGER NOT NULL DEFAULT 0,
    clicks      INTEGER NOT NULL DEFAULT 0,
    signups     INTEGER NOT NULL DEFAULT 0,
    status      TEXT    NOT NULL,
    FOREIGN KEY (product_id) REFERENCES products (id)
);

CREATE TABLE IF NOT EXISTS outreach_attempts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT    NOT NULL,
    product_id  INTEGER,
    target      TEXT    NOT NULL,
    message     TEXT    NOT NULL,
    status      TEXT    NOT NULL,
    response    TEXT,
    FOREIGN KEY (product_id) REFERENCES products (id)
);

CREATE TABLE IF NOT EXISTS metrics (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at      TEXT    NOT NULL,
    website_traffic  INTEGER NOT NULL DEFAULT 0,
    signups          INTEGER NOT NULL DEFAULT 0,
    conversion_rate  REAL    NOT NULL DEFAULT 0,
    revenue          REAL    NOT NULL DEFAULT 0,
    mrr              REAL    NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS loop_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at   TEXT    NOT NULL,
    finished_at  TEXT,
    action_taken TEXT,
    outcome      TEXT,
    status       TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_entries (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at          TEXT    NOT NULL,
    agent_name          TEXT    NOT NULL,
    memory_type         TEXT    NOT NULL,
    content             TEXT    NOT NULL,
    related_entity_type TEXT,
    related_entity_id   INTEGER
);
"""

# ---------------------------------------------------------------------------
# Schema – LangGraph tables
# ---------------------------------------------------------------------------

_SCHEMA_GRAPH = """
CREATE TABLE IF NOT EXISTS graph_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT    NOT NULL UNIQUE,
    started_at   TEXT    NOT NULL,
    finished_at  TEXT,
    goal_mrr     REAL    NOT NULL DEFAULT 100.0,
    cycles_run   INTEGER NOT NULL DEFAULT 0,
    stop_reason  TEXT,
    status       TEXT    NOT NULL DEFAULT 'running'
);

CREATE TABLE IF NOT EXISTS graph_checkpoints (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT    NOT NULL,
    cycle_count  INTEGER NOT NULL,
    saved_at     TEXT    NOT NULL,
    state_json   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS node_executions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         TEXT    NOT NULL,
    cycle_count    INTEGER NOT NULL DEFAULT 0,
    node_name      TEXT    NOT NULL,
    started_at     TEXT    NOT NULL,
    finished_at    TEXT,
    duration_ms    INTEGER,
    input_summary  TEXT,
    output_summary TEXT,
    status         TEXT    NOT NULL DEFAULT 'running'
);
"""

# ---------------------------------------------------------------------------
# Schema – v0.3 hardening tables
# ---------------------------------------------------------------------------

_SCHEMA_V03 = """
CREATE TABLE IF NOT EXISTS artifacts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT    NOT NULL,
    cycle_count     INTEGER NOT NULL DEFAULT 0,
    node_name       TEXT    NOT NULL,
    artifact_type   TEXT    NOT NULL,
    path_or_hash    TEXT,
    content_summary TEXT,
    created_at      TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS cycle_scores (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT    NOT NULL,
    cycle_count     INTEGER NOT NULL,
    recorded_at     TEXT    NOT NULL,
    domain          TEXT    NOT NULL,
    action          TEXT    NOT NULL DEFAULT '',
    progress_score  REAL    NOT NULL DEFAULT 0.0,
    weighted_score  REAL    NOT NULL DEFAULT 0.0,
    trend_direction TEXT    NOT NULL DEFAULT 'flat',
    mrr             REAL    NOT NULL DEFAULT 0.0,
    traffic         INTEGER NOT NULL DEFAULT 0,
    signups         INTEGER NOT NULL DEFAULT 0,
    stagnant_cycles INTEGER NOT NULL DEFAULT 0
);
"""


def init_db() -> list[str]:
    """Create all tables idempotently.

    Returns a list of user-facing table names.
    """
    with get_connection() as conn:
        conn.executescript(_SCHEMA_ORIGINAL)
        conn.executescript(_SCHEMA_GRAPH)
        conn.executescript(_SCHEMA_V03)
        _migrate_graph_runs_budget_cols(conn)

        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()

    return [row["name"] for row in rows]


def _migrate_graph_runs_budget_cols(conn: sqlite3.Connection) -> None:
    """Add budget/mode columns to graph_runs if they don't exist (idempotent)."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(graph_runs)").fetchall()}
    for col, definition in [
        ("model_mode",     "TEXT    NOT NULL DEFAULT 'unknown'"),
        ("fallback_count", "INTEGER NOT NULL DEFAULT 0"),
        ("tokens_used",    "INTEGER NOT NULL DEFAULT 0"),
        ("external_calls", "INTEGER NOT NULL DEFAULT 0"),
    ]:
        if col not in existing:
            conn.execute(f"ALTER TABLE graph_runs ADD COLUMN {col} {definition}")


# ---------------------------------------------------------------------------
# Graph-run persistence
# ---------------------------------------------------------------------------

def start_graph_run(run_id: str, goal_mrr: float) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO graph_runs
                (run_id, started_at, goal_mrr, status)
            VALUES (?, ?, ?, 'running')
            """,
            (run_id, utc_now(), goal_mrr),
        )


def finish_graph_run(
    run_id: str,
    cycles_run: int,
    stop_reason: Optional[str],
    status: str = "completed",
    model_mode: str = "unknown",
    fallback_count: int = 0,
    tokens_used: int = 0,
    external_calls: int = 0,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE graph_runs
            SET    finished_at    = ?,
                   cycles_run     = ?,
                   stop_reason    = ?,
                   status         = ?,
                   model_mode     = ?,
                   fallback_count = ?,
                   tokens_used    = ?,
                   external_calls = ?
            WHERE  run_id = ?
            """,
            (utc_now(), cycles_run, stop_reason, status,
             model_mode, fallback_count, tokens_used, external_calls,
             run_id),
        )


def save_checkpoint(run_id: str, cycle_count: int, state: dict[str, Any]) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO graph_checkpoints
                (run_id, cycle_count, saved_at, state_json)
            VALUES (?, ?, ?, ?)
            """,
            (run_id, cycle_count, utc_now(), json.dumps(state, default=str)),
        )


# ---------------------------------------------------------------------------
# Node execution logging
# ---------------------------------------------------------------------------

def log_node_start(
    run_id: str,
    cycle_count: int,
    node_name: str,
    input_summary: str,
) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO node_executions
                (run_id, cycle_count, node_name, started_at, input_summary, status)
            VALUES (?, ?, ?, ?, ?, 'running')
            """,
            (run_id, cycle_count, node_name, utc_now(), input_summary),
        )
    return cursor.lastrowid  # type: ignore[return-value]


def log_node_finish(
    execution_id: int,
    output_summary: str,
    status: str = "completed",
) -> None:
    finished = utc_now()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT started_at FROM node_executions WHERE id = ?",
            (execution_id,),
        ).fetchone()

        duration_ms: Optional[int] = None
        if row:
            start = datetime.fromisoformat(row["started_at"])
            end = datetime.fromisoformat(finished)
            duration_ms = int((end - start).total_seconds() * 1000)

        conn.execute(
            """
            UPDATE node_executions
            SET    finished_at    = ?,
                   duration_ms    = ?,
                   output_summary = ?,
                   status         = ?
            WHERE  id = ?
            """,
            (finished, duration_ms, output_summary, status, execution_id),
        )


# ---------------------------------------------------------------------------
# Artifact persistence  (v0.3)
# ---------------------------------------------------------------------------

def persist_artifact(
    run_id: str,
    cycle_count: int,
    node_name: str,
    artifact_type: str,
    path_or_hash: Optional[str] = None,
    content_summary: Optional[str] = None,
) -> int:
    """Insert an artifact row and return its id."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO artifacts
                (run_id, cycle_count, node_name, artifact_type,
                 path_or_hash, content_summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                cycle_count,
                node_name,
                artifact_type,
                path_or_hash,
                content_summary,
                utc_now(),
            ),
        )
    return cursor.lastrowid  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Cycle score persistence  (v0.3)
# ---------------------------------------------------------------------------

def persist_cycle_score(
    run_id: str,
    cycle_count: int,
    domain: str,
    action: str,
    progress_score: float,
    weighted_score: float,
    trend_direction: str,
    mrr: float,
    traffic: int,
    signups: int,
    stagnant_cycles: int = 0,
) -> int:
    """Insert a cycle_scores row and return its id."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO cycle_scores
                (run_id, cycle_count, recorded_at, domain, action,
                 progress_score, weighted_score, trend_direction,
                 mrr, traffic, signups, stagnant_cycles)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                cycle_count,
                utc_now(),
                domain,
                action,
                progress_score,
                weighted_score,
                trend_direction,
                mrr,
                traffic,
                signups,
                stagnant_cycles,
            ),
        )
    return cursor.lastrowid  # type: ignore[return-value]
