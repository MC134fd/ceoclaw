"""SQLite-backed memory store."""

from __future__ import annotations

import logging
from typing import Optional

from data.database import get_connection
from core.memory_store import BaseMemoryStore

logger = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS agent_memory (
    namespace TEXT NOT NULL,
    key       TEXT NOT NULL,
    value     TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    PRIMARY KEY (namespace, key)
);
"""


class SQLiteMemoryStore(BaseMemoryStore):

    def __init__(self) -> None:
        with get_connection() as conn:
            conn.executescript(_DDL)

    def set(self, key: str, value: str, namespace: str = "default") -> None:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO agent_memory (namespace, key, value, updated_at)
                VALUES (?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
                ON CONFLICT(namespace, key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (namespace, key, value),
            )

    def get(self, key: str, namespace: str = "default") -> Optional[str]:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT value FROM agent_memory WHERE namespace=? AND key=?",
                (namespace, key),
            ).fetchone()
        return row["value"] if row else None

    def get_all(self, namespace: str = "default") -> dict[str, str]:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT key, value FROM agent_memory WHERE namespace=?",
                (namespace,),
            ).fetchall()
        return {r["key"]: r["value"] for r in rows}

    def delete(self, key: str, namespace: str = "default") -> None:
        with get_connection() as conn:
            conn.execute(
                "DELETE FROM agent_memory WHERE namespace=? AND key=?",
                (namespace, key),
            )
