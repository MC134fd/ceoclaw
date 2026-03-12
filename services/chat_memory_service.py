"""
Clean service layer for chat memory.

Wraps data.database chat functions with a clean API for the builder endpoints.
"""

from __future__ import annotations

import logging
from typing import Optional

from data.database import (
    append_chat_message,
    get_chat_history,
    get_chat_session,
    list_chat_sessions,
    upsert_chat_session,
)

logger = logging.getLogger(__name__)


def create_session(session_id: str, slug: str, product_name: str) -> None:
    """Create or update a chat session."""
    upsert_chat_session(session_id, slug=slug, product_name=product_name, version_id=None)


def add_message(session_id: str, role: str, content: str, metadata: Optional[dict] = None) -> int:
    """Append a message to a session. Returns the message id."""
    # metadata ignored for now — database schema does not have a metadata column
    return append_chat_message(session_id, role, content)


def get_messages(session_id: str, limit: int = 100) -> list[dict]:
    """Return messages for a session, newest-last."""
    return get_chat_history(session_id, limit=limit)


def get_session(session_id: str) -> dict | None:
    """Return session metadata or None if not found."""
    return get_chat_session(session_id)


def list_sessions(limit: int = 20) -> list[dict]:
    """Return most recently updated sessions."""
    return list_chat_sessions(limit=limit)


def export_history_for_llm(session_id: str, limit: int = 10) -> list[dict]:
    """Return recent messages as [{"role": ..., "content": ...}] for LLM context."""
    rows = get_chat_history(session_id, limit=limit)
    return [{"role": m["role"], "content": m["content"]} for m in rows]
