"""
CEOClaw MemoryStore.

Persists agent memories to the ``memory_entries`` SQLite table and
exposes simple retrieval and search helpers.  All methods return plain
Python dicts so agents can consume them without any ORM dependency.
"""

from typing import Any, Optional

from data.database import get_connection, utc_now


class MemoryStore:
    """SQLite-backed memory store for agent observations and decisions."""

    def add_memory(
        self,
        agent_name: str,
        memory_type: str,
        content: str,
        related_entity_type: Optional[str] = None,
        related_entity_id: Optional[int] = None,
    ) -> int:
        """Persist a new memory entry and return its row id.

        Args:
            agent_name:          Name of the agent storing the memory.
            memory_type:         Category label (e.g. ``"observation"``,
                                 ``"decision"``, ``"error"``).
            content:             Free-text memory content.
            related_entity_type: Optional table name the memory relates to
                                 (e.g. ``"products"``, ``"ideas"``).
            related_entity_id:   Optional primary key of the related row.

        Returns:
            The ``id`` of the newly inserted memory_entries row.
        """
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO memory_entries
                    (created_at, agent_name, memory_type, content,
                     related_entity_type, related_entity_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now(),
                    agent_name,
                    memory_type,
                    content,
                    related_entity_type,
                    related_entity_id,
                ),
            )
        return cursor.lastrowid  # type: ignore[return-value]

    def list_memories(
        self,
        agent_name: Optional[str] = None,
        memory_type: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return memories filtered by agent and/or type, newest first.

        Args:
            agent_name:  If given, restrict results to this agent.
            memory_type: If given, restrict results to this memory type.
            limit:       Maximum number of rows to return.

        Returns:
            List of dicts representing memory_entries rows.
        """
        conditions: list[str] = []
        params: list[Any] = []

        if agent_name is not None:
            conditions.append("agent_name = ?")
            params.append(agent_name)
        if memory_type is not None:
            conditions.append("memory_type = ?")
            params.append(memory_type)

        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.append(limit)

        with get_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM   memory_entries
                {where_clause}
                ORDER  BY created_at DESC
                LIMIT  ?
                """,
                params,
            ).fetchall()

        return [dict(r) for r in rows]

    def search_memories(
        self,
        query: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Return memories whose ``content`` contains *query* (case-insensitive).

        Uses a SQL ``LIKE`` expression – sufficient for the current scale.

        Args:
            query: Substring to search for within the content column.
            limit: Maximum number of rows to return.

        Returns:
            List of matching memory_entries rows as dicts, newest first.
        """
        pattern = f"%{query}%"
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM   memory_entries
                WHERE  content LIKE ?
                ORDER  BY created_at DESC
                LIMIT  ?
                """,
                (pattern, limit),
            ).fetchall()
        return [dict(r) for r in rows]
