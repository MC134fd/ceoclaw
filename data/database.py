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
  v0.5      : research_reports, social_posts, pending_approvals
  v0.6      : prospects, agent_memory
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Optional

import config.settings as _settings_mod


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
    return _settings_mod.settings.resolve_db_path()


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


# ---------------------------------------------------------------------------
# Schema – v0.5 autonomy / research / social tables
# ---------------------------------------------------------------------------

_SCHEMA_V05 = """
CREATE TABLE IF NOT EXISTS research_reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT    NOT NULL,
    cycle_count   INTEGER NOT NULL DEFAULT 0,
    topic         TEXT    NOT NULL,
    product_name  TEXT    NOT NULL,
    summary       TEXT,
    competitors   TEXT,
    audience      TEXT,
    opportunities TEXT,
    risks         TEXT,
    experiments   TEXT,
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS social_posts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT    NOT NULL,
    cycle_count  INTEGER NOT NULL DEFAULT 0,
    platform     TEXT    NOT NULL,
    content      TEXT    NOT NULL,
    status       TEXT    NOT NULL DEFAULT 'drafted',
    post_id      TEXT,
    error_detail TEXT,
    created_at   TEXT    NOT NULL,
    updated_at   TEXT
);

CREATE TABLE IF NOT EXISTS pending_approvals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT    NOT NULL,
    approval_type TEXT    NOT NULL,
    payload       TEXT    NOT NULL,
    status        TEXT    NOT NULL DEFAULT 'pending',
    created_at    TEXT    NOT NULL,
    resolved_at   TEXT,
    resolved_by   TEXT
);
"""


_SCHEMA_V07 = """
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id   TEXT PRIMARY KEY,
    slug         TEXT NOT NULL DEFAULT '',
    product_name TEXT NOT NULL DEFAULT '',
    version_id   TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id)
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session
    ON chat_messages (session_id, id ASC);
"""


# ---------------------------------------------------------------------------
# Schema – accounts / credits (v1.0)
# ---------------------------------------------------------------------------

_SCHEMA_ACCOUNTS = """
CREATE TABLE IF NOT EXISTS users (
    id           TEXT PRIMARY KEY,          -- Supabase user id (sub)
    email        TEXT UNIQUE NOT NULL,
    display_name TEXT,
    avatar_url   TEXT,
    provider     TEXT NOT NULL DEFAULT 'google',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_subscriptions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      TEXT NOT NULL,
    tier         TEXT NOT NULL DEFAULT 'free',   -- free / pro / business
    status       TEXT NOT NULL DEFAULT 'active', -- active / inactive
    period_start TEXT,
    period_end   TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS user_credits (
    user_id              TEXT PRIMARY KEY,
    balance              INTEGER NOT NULL DEFAULT 0,
    monthly_allocation   INTEGER NOT NULL DEFAULT 0,
    updated_at           TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS credit_ledger (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL,
    delta           INTEGER NOT NULL,      -- negative for usage, positive for grants
    reason          TEXT NOT NULL,         -- generate_request / initial_grant / monthly_reset
    ref_session_id  TEXT,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_user_subscriptions_user ON user_subscriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_credit_ledger_user      ON credit_ledger(user_id, created_at DESC);
"""


_SCHEMA_V08 = """
CREATE TABLE IF NOT EXISTS session_versions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT    NOT NULL,
    version_id      TEXT    NOT NULL,
    message_id      INTEGER,
    files_json      TEXT    NOT NULL,
    file_list_json  TEXT    NOT NULL,
    created_at      TEXT    NOT NULL,
    UNIQUE(session_id, version_id)
);
CREATE INDEX IF NOT EXISTS idx_session_versions_session ON session_versions(session_id);
"""

_SCHEMA_V09 = """
CREATE TABLE IF NOT EXISTS project_files (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL,
    file_path   TEXT    NOT NULL,
    content     TEXT,
    file_type   TEXT    NOT NULL DEFAULT 'text',
    size_bytes  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL,
    UNIQUE(session_id, file_path),
    FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_project_files_session ON project_files(session_id);
"""

_SCHEMA_V06 = """
CREATE TABLE IF NOT EXISTS prospects (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT    NOT NULL,
    cycle_count  INTEGER NOT NULL DEFAULT 0,
    name         TEXT    NOT NULL,
    company      TEXT,
    title        TEXT,
    email        TEXT,
    linkedin_url TEXT,
    score        REAL    NOT NULL DEFAULT 0.0,
    status       TEXT    NOT NULL DEFAULT 'discovered',
    notes        TEXT,
    source       TEXT,
    created_at   TEXT    NOT NULL,
    updated_at   TEXT
);

CREATE TABLE IF NOT EXISTS agent_memory (
    namespace  TEXT NOT NULL,
    key        TEXT NOT NULL,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    PRIMARY KEY (namespace, key)
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
        conn.executescript(_SCHEMA_V05)
        conn.executescript(_SCHEMA_V06)
        conn.executescript(_SCHEMA_V07)
        conn.executescript(_SCHEMA_V08)
        conn.executescript(_SCHEMA_ACCOUNTS)
        conn.executescript(_SCHEMA_V09)
        _migrate_graph_runs_budget_cols(conn)
        _migrate_graph_runs_autonomy_col(conn)
        _migrate_chat_sessions_design_system(conn)
        _migrate_chat_sessions_owner_user_id(conn)

        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()

    return [row["name"] for row in rows]


def _migrate_graph_runs_autonomy_col(conn: sqlite3.Connection) -> None:
    """Add autonomy_mode column to graph_runs if it doesn't exist (idempotent)."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(graph_runs)").fetchall()}
    if "autonomy_mode" not in existing:
        conn.execute(
            "ALTER TABLE graph_runs ADD COLUMN autonomy_mode TEXT NOT NULL DEFAULT 'A_AUTONOMOUS'"
        )


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

# ---------------------------------------------------------------------------
# Research report persistence  (v0.5)
# ---------------------------------------------------------------------------

def persist_research_report(
    run_id: str,
    cycle_count: int,
    topic: str,
    product_name: str,
    summary: str,
    competitors: list,
    audience: dict,
    opportunities: list,
    risks: list,
    experiments: list,
) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO research_reports
                (run_id, cycle_count, topic, product_name, summary,
                 competitors, audience, opportunities, risks, experiments, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id, cycle_count, topic, product_name, summary,
                json.dumps(competitors), json.dumps(audience),
                json.dumps(opportunities), json.dumps(risks),
                json.dumps(experiments), utc_now(),
            ),
        )
    return cursor.lastrowid  # type: ignore[return-value]


def get_research_reports(run_id: str) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM research_reports WHERE run_id=? ORDER BY created_at ASC",
            (run_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Social post persistence  (v0.5)
# ---------------------------------------------------------------------------

def persist_social_post(
    run_id: str,
    cycle_count: int,
    platform: str,
    content: str,
    status: str = "drafted",
    post_id: Optional[str] = None,
    error_detail: Optional[str] = None,
) -> int:
    now = utc_now()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO social_posts
                (run_id, cycle_count, platform, content, status, post_id, error_detail,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, cycle_count, platform, content, status, post_id, error_detail, now, now),
        )
    return cursor.lastrowid  # type: ignore[return-value]


def update_social_post_status(
    post_id_db: int,
    status: str,
    post_id: Optional[str] = None,
    error_detail: Optional[str] = None,
) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE social_posts SET status=?, post_id=?, error_detail=?, updated_at=? WHERE id=?",
            (status, post_id, error_detail, utc_now(), post_id_db),
        )


def get_social_posts(run_id: str) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM social_posts WHERE run_id=? ORDER BY created_at ASC",
            (run_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Pending approval persistence  (v0.5)
# ---------------------------------------------------------------------------

def create_pending_approval(
    run_id: str,
    approval_type: str,
    payload: dict[str, Any],
) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO pending_approvals
                (run_id, approval_type, payload, status, created_at)
            VALUES (?, ?, ?, 'pending', ?)
            """,
            (run_id, approval_type, json.dumps(payload), utc_now()),
        )
    return cursor.lastrowid  # type: ignore[return-value]


def resolve_approval(approval_id: int, decision: str, resolved_by: str = "user") -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE pending_approvals SET status=?, resolved_at=?, resolved_by=? WHERE id=?",
            (decision, utc_now(), resolved_by, approval_id),
        )


def get_pending_approvals(run_id: str, status: str = "pending") -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM pending_approvals WHERE run_id=? AND status=? ORDER BY created_at ASC",
            (run_id, status),
        ).fetchall()
    return [dict(r) for r in rows]


def get_approval(approval_id: int) -> Optional[dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM pending_approvals WHERE id=?", (approval_id,)
        ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Prospect persistence  (v0.6)
# ---------------------------------------------------------------------------

def persist_prospect(
    run_id: str,
    cycle_count: int,
    name: str,
    company: Optional[str] = None,
    title: Optional[str] = None,
    email: Optional[str] = None,
    linkedin_url: Optional[str] = None,
    score: float = 0.0,
    status: str = "discovered",
    notes: Optional[str] = None,
    source: Optional[str] = None,
) -> int:
    now = utc_now()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO prospects
                (run_id, cycle_count, name, company, title, email,
                 linkedin_url, score, status, notes, source, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, cycle_count, name, company, title, email,
             linkedin_url, score, status, notes, source, now, now),
        )
    return cursor.lastrowid  # type: ignore[return-value]


def update_prospect_status(prospect_id: int, status: str, notes: Optional[str] = None) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE prospects SET status=?, notes=?, updated_at=? WHERE id=?",
            (status, notes, utc_now(), prospect_id),
        )


def get_prospects(run_id: str, status: Optional[str] = None) -> list[dict[str, Any]]:
    query = "SELECT * FROM prospects WHERE run_id=?"
    params: list[Any] = [run_id]
    if status:
        query += " AND status=?"
        params.append(status)
    query += " ORDER BY score DESC, created_at ASC"
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


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


# ---------------------------------------------------------------------------
# Chat history helpers (v0.7)
# ---------------------------------------------------------------------------

def upsert_chat_session(
    session_id: str,
    slug: str = "",
    product_name: str = "",
    version_id: str = "",
    owner_user_id: Optional[str] = None,
) -> None:
    """Create or update a chat session row (idempotent).

    owner_user_id is set once on creation via COALESCE — ownership is never
    transferred after the row exists.
    """
    now = utc_now()
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO chat_sessions "
            "(session_id, slug, product_name, version_id, owner_user_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, slug, product_name, version_id, owner_user_id, now, now),
        )
        # COALESCE preserves the original owner if one was already set
        conn.execute(
            "UPDATE chat_sessions "
            "SET slug=?, product_name=?, version_id=?, updated_at=?, "
            "    owner_user_id=COALESCE(owner_user_id, ?) "
            "WHERE session_id=?",
            (slug or "", product_name or "", version_id or "", now, owner_user_id, session_id),
        )


def append_chat_message(session_id: str, role: str, content: str) -> int:
    """Append a message to a session; auto-creates session row if missing."""
    now = utc_now()
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO chat_sessions "
            "(session_id, created_at, updated_at) VALUES (?, ?, ?)",
            (session_id, now, now),
        )
        conn.execute(
            "UPDATE chat_sessions SET updated_at=? WHERE session_id=?",
            (now, session_id),
        )
        cursor = conn.execute(
            "INSERT INTO chat_messages (session_id, role, content, created_at) "
            "VALUES (?, ?, ?, ?)",
            (session_id, role, content, now),
        )
        return cursor.lastrowid  # type: ignore[return-value]


def get_chat_history(session_id: str, limit: int = 40) -> list[dict]:
    """Return messages for a session ordered oldest-first."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, session_id, role, content, created_at "
            "FROM chat_messages WHERE session_id=? "
            "ORDER BY id ASC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_chat_session(session_id: str) -> Optional[dict]:
    """Return the chat_sessions row for a session_id, or None."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM chat_sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
    return dict(row) if row else None


def list_chat_sessions(limit: int = 50) -> list[dict]:
    """Return recent sessions ordered by updated_at DESC (all users — admin/anon mode)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT s.session_id, s.slug, s.product_name, s.version_id, "
            "       s.created_at, s.updated_at, COUNT(m.id) as message_count "
            "FROM chat_sessions s "
            "LEFT JOIN chat_messages m ON m.session_id = s.session_id "
            "GROUP BY s.session_id "
            "ORDER BY s.updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def list_chat_sessions_for_user(user_id: str, limit: int = 50) -> list[dict]:
    """Return sessions owned by user_id, ordered by updated_at DESC."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT s.session_id, s.slug, s.product_name, s.version_id, "
            "       s.created_at, s.updated_at, COUNT(m.id) as message_count "
            "FROM chat_sessions s "
            "LEFT JOIN chat_messages m ON m.session_id = s.session_id "
            "WHERE s.owner_user_id = ? "
            "GROUP BY s.session_id "
            "ORDER BY s.updated_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_chat_session_owned_by(session_id: str, user_id: str) -> Optional[dict]:
    """Return session only if it belongs to user_id, else None."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM chat_sessions WHERE session_id=? AND owner_user_id=?",
            (session_id, user_id),
        ).fetchone()
    return dict(row) if row else None


def delete_chat_session(session_id: str) -> bool:
    """Delete a session and all its messages. Returns True if a row was deleted."""
    with get_connection() as conn:
        conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
        cur = conn.execute("DELETE FROM chat_sessions WHERE session_id = ?", (session_id,))
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Design system persistence  (v0.8)
# ---------------------------------------------------------------------------


def _migrate_chat_sessions_design_system(conn: sqlite3.Connection) -> None:
    """Add design_system_json column to chat_sessions if it doesn't exist (idempotent)."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(chat_sessions)").fetchall()}
    if "design_system_json" not in existing:
        conn.execute(
            "ALTER TABLE chat_sessions ADD COLUMN design_system_json TEXT DEFAULT NULL"
        )


def _migrate_chat_sessions_owner_user_id(conn: sqlite3.Connection) -> None:
    """Add owner_user_id column + index to chat_sessions (idempotent)."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(chat_sessions)").fetchall()}
    if "owner_user_id" not in existing:
        conn.execute("ALTER TABLE chat_sessions ADD COLUMN owner_user_id TEXT DEFAULT NULL")
    # Index creation is idempotent via IF NOT EXISTS
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_sessions_owner "
        "ON chat_sessions(owner_user_id, updated_at DESC)"
    )


def upsert_design_system(session_id: str, design_system: dict) -> None:
    """Persist design system JSON for a session."""
    now = utc_now()
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO chat_sessions (session_id, created_at, updated_at) "
            "VALUES (?, ?, ?)",
            (session_id, now, now),
        )
        conn.execute(
            "UPDATE chat_sessions SET design_system_json=?, updated_at=? WHERE session_id=?",
            (json.dumps(design_system), now, session_id),
        )


def get_design_system(session_id: str) -> Optional[dict[str, Any]]:
    """Return design system for session or None."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT design_system_json FROM chat_sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
    if row and row["design_system_json"]:
        try:
            return json.loads(row["design_system_json"])
        except (json.JSONDecodeError, TypeError):
            return None
    return None


# ---------------------------------------------------------------------------
# Session version persistence  (v0.8)
# ---------------------------------------------------------------------------


def save_session_version(
    session_id: str,
    version_id: str,
    files: dict[str, str],
    message_id: Optional[int] = None,
) -> int:
    """Insert a version record. files = {rel_path: content}.

    Returns the new row id.
    """
    file_list = sorted(files.keys())
    now = utc_now()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO session_versions
                (session_id, version_id, message_id, files_json, file_list_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                version_id,
                message_id,
                json.dumps(files),
                json.dumps(file_list),
                now,
            ),
        )
    return cursor.lastrowid or 0  # type: ignore[return-value]


def list_session_versions(session_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """Return [{id, session_id, version_id, file_list, created_at}] newest-first."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, session_id, version_id, file_list_json, created_at
            FROM session_versions
            WHERE session_id=?
            ORDER BY id DESC LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["file_list"] = json.loads(d.pop("file_list_json", "[]"))
        except (json.JSONDecodeError, TypeError):
            d["file_list"] = []
        result.append(d)
    return result


def get_session_version(session_id: str, version_id: str) -> Optional[dict[str, Any]]:
    """Return version record with files_json parsed as dict."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, session_id, version_id, message_id, files_json, file_list_json, created_at
            FROM session_versions
            WHERE session_id=? AND version_id=?
            """,
            (session_id, version_id),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["files"] = json.loads(d.pop("files_json", "{}"))
    except (json.JSONDecodeError, TypeError):
        d["files"] = {}
    try:
        d["file_list"] = json.loads(d.pop("file_list_json", "[]"))
    except (json.JSONDecodeError, TypeError):
        d["file_list"] = []
    return d


# ---------------------------------------------------------------------------
# User / account helpers (v1.0 accounts)
# ---------------------------------------------------------------------------

# Credits granted to new free-tier users — overridden by FREE_TIER_CREDITS env var via server
_DEFAULT_FREE_CREDITS = 10


def upsert_user(
    user_id: str,
    email: str,
    display_name: Optional[str] = None,
    avatar_url: Optional[str] = None,
    provider: str = "google",
) -> dict[str, Any]:
    """Create or update a user row from Supabase JWT claims."""
    now = utc_now()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO users (id, email, display_name, avatar_url, provider, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                email        = excluded.email,
                display_name = excluded.display_name,
                avatar_url   = excluded.avatar_url,
                provider     = excluded.provider,
                updated_at   = excluded.updated_at
            """,
            (user_id, email, display_name, avatar_url, provider, now, now),
        )
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return dict(row) if row else {}


def get_user_by_id(user_id: str) -> Optional[dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_user_by_email(email: str) -> Optional[dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    return dict(row) if row else None


def ensure_default_subscription_and_credits(
    user_id: str,
    free_credits: int = _DEFAULT_FREE_CREDITS,
) -> None:
    """Create a free subscription and initial credit grant if they don't already exist."""
    now = utc_now()
    with get_connection() as conn:
        # Subscription: INSERT OR IGNORE keeps existing rows untouched
        conn.execute(
            "INSERT OR IGNORE INTO user_subscriptions "
            "(user_id, tier, status, created_at, updated_at) "
            "VALUES (?, 'free', 'active', ?, ?)",
            (user_id, now, now),
        )
        # Credits: only seed once
        existing = conn.execute(
            "SELECT user_id FROM user_credits WHERE user_id=?", (user_id,)
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO user_credits (user_id, balance, monthly_allocation, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (user_id, free_credits, free_credits, now),
            )
            conn.execute(
                "INSERT INTO credit_ledger (user_id, delta, reason, created_at) "
                "VALUES (?, ?, 'initial_grant', ?)",
                (user_id, free_credits, now),
            )


def get_user_credits(user_id: str) -> dict[str, Any]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM user_credits WHERE user_id=?", (user_id,)
        ).fetchone()
    if not row:
        return {"user_id": user_id, "balance": 0, "monthly_allocation": 0, "updated_at": ""}
    return dict(row)


def get_user_subscription(user_id: str) -> Optional[dict[str, Any]]:
    """Return the active subscription row, or None."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM user_subscriptions WHERE user_id=? AND status='active' "
            "ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def deduct_credits(
    user_id: str,
    cost: int,
    reason: str,
    ref_session_id: Optional[str] = None,
) -> dict[str, Any]:
    """Atomically deduct credits and write a ledger entry.

    Uses a conditional UPDATE (WHERE balance >= cost) to prevent overdraft even
    under concurrent requests. Returns:
      {"ok": True,  "balance_before": N, "balance_after": N-cost}
      {"ok": False, "balance": N, "required": cost}   — insufficient
    """
    now = utc_now()
    with get_connection() as conn:
        # Read current balance for reporting
        row = conn.execute(
            "SELECT balance FROM user_credits WHERE user_id=?", (user_id,)
        ).fetchone()
        if not row:
            return {"ok": False, "balance": 0, "required": cost}

        balance_before = row["balance"]
        if balance_before < cost:
            return {"ok": False, "balance": balance_before, "required": cost}

        # Atomic conditional UPDATE — WHERE balance >= cost prevents overdraft
        result = conn.execute(
            "UPDATE user_credits SET balance = balance - ?, updated_at = ? "
            "WHERE user_id = ? AND balance >= ?",
            (cost, now, user_id, cost),
        )
        if result.rowcount == 0:
            # Concurrent request raced us to the last credits
            return {"ok": False, "balance": balance_before, "required": cost}

        conn.execute(
            "INSERT INTO credit_ledger (user_id, delta, reason, ref_session_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, -cost, reason, ref_session_id, now),
        )

    return {"ok": True, "balance_before": balance_before, "balance_after": balance_before - cost}


def get_credit_ledger(user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """Return recent credit ledger entries for a user, newest first."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM credit_ledger WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Project file persistence  (v0.9)
# ---------------------------------------------------------------------------


def upsert_project_file(
    session_id: str,
    file_path: str,
    content: str,
    file_type: str = "text",
) -> None:
    """Create or update a project file. Computes size_bytes from content length."""
    now = utc_now()
    size_bytes = len(content.encode("utf-8")) if content else 0
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO project_files
                (session_id, file_path, content, file_type, size_bytes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id, file_path) DO UPDATE SET
                content    = excluded.content,
                file_type  = excluded.file_type,
                size_bytes = excluded.size_bytes,
                updated_at = excluded.updated_at
            """,
            (session_id, file_path, content, file_type, size_bytes, now, now),
        )


def get_project_file(session_id: str, file_path: str) -> Optional[dict[str, Any]]:
    """Return the full row as dict (including content), or None."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM project_files WHERE session_id=? AND file_path=?",
            (session_id, file_path),
        ).fetchone()
    return dict(row) if row else None


def list_project_files_for_session(session_id: str) -> list[dict[str, Any]]:
    """Return all files for a session WITHOUT content — just metadata.

    Ordered by file_path ASC. Used for the file tree endpoint.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT file_path, file_type, size_bytes, updated_at
            FROM project_files
            WHERE session_id=?
            ORDER BY file_path ASC
            """,
            (session_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_project_file(session_id: str, file_path: str) -> bool:
    """Delete one file. Returns True if a row was actually deleted."""
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM project_files WHERE session_id=? AND file_path=?",
            (session_id, file_path),
        )
    return cur.rowcount > 0


def delete_all_project_files(session_id: str) -> int:
    """Delete every file for a session. Returns count deleted."""
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM project_files WHERE session_id=?",
            (session_id,),
        )
    return cur.rowcount


def get_project_files_content(session_id: str, file_paths: list[str]) -> dict[str, str]:
    """Batch-read content for specific files. Returns {file_path: content}.

    Uses a single query with WHERE file_path IN (...). Paths not found are omitted.
    """
    if not file_paths:
        return {}
    placeholders = ",".join("?" * len(file_paths))
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT file_path, content FROM project_files "
            f"WHERE session_id=? AND file_path IN ({placeholders})",
            [session_id, *file_paths],
        ).fetchall()
    return {row["file_path"]: row["content"] for row in rows if row["content"] is not None}
