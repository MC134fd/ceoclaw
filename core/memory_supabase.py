"""Supabase-backed memory store."""

from __future__ import annotations

import logging
from typing import Optional

from core.memory_store import BaseMemoryStore

logger = logging.getLogger(__name__)


class SupabaseMemoryStore(BaseMemoryStore):
    """
    Stores agent memory in a Supabase table `agent_memory`.

    Required env vars: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
    Optional: SUPABASE_SCHEMA (default: public)

    Table DDL (run once, or apply supabase/migrations/001_ceoclaw.sql):
        CREATE TABLE IF NOT EXISTS agent_memory (
            namespace TEXT NOT NULL,
            key       TEXT NOT NULL,
            value     TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (namespace, key)
        );
    """

    def __init__(self) -> None:
        from config.settings import settings
        try:
            from supabase import create_client  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "supabase package not installed. Run: pip install supabase"
            ) from exc

        if not settings.has_supabase:
            raise ValueError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set for Supabase memory."
            )

        self._client = create_client(settings.supabase_url, settings.supabase_service_role_key)
        self._schema = settings.supabase_schema
        self._table = "agent_memory"

    def _tbl(self):
        return self._client.schema(self._schema).table(self._table)

    def set(self, key: str, value: str, namespace: str = "default") -> None:
        self._tbl().upsert(
            {"namespace": namespace, "key": key, "value": value},
            on_conflict="namespace,key",
        ).execute()

    def get(self, key: str, namespace: str = "default") -> Optional[str]:
        resp = (
            self._tbl()
            .select("value")
            .eq("namespace", namespace)
            .eq("key", key)
            .maybe_single()
            .execute()
        )
        if resp.data:
            return resp.data.get("value")
        return None

    def get_all(self, namespace: str = "default") -> dict[str, str]:
        resp = (
            self._tbl()
            .select("key,value")
            .eq("namespace", namespace)
            .execute()
        )
        return {row["key"]: row["value"] for row in (resp.data or [])}

    def delete(self, key: str, namespace: str = "default") -> None:
        self._tbl().delete().eq("namespace", namespace).eq("key", key).execute()
