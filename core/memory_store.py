"""
Abstract memory interface for cross-run persistence.

A "memory" is a keyed string value scoped to a product/run session.
Concrete backends: SQLite (default) and Supabase (cloud).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class BaseMemoryStore(ABC):

    @abstractmethod
    def set(self, key: str, value: str, namespace: str = "default") -> None:
        """Upsert a memory entry."""
        ...

    @abstractmethod
    def get(self, key: str, namespace: str = "default") -> Optional[str]:
        """Return the value for key, or None."""
        ...

    @abstractmethod
    def get_all(self, namespace: str = "default") -> dict[str, str]:
        """Return all key-value pairs in a namespace."""
        ...

    @abstractmethod
    def delete(self, key: str, namespace: str = "default") -> None:
        """Remove an entry."""
        ...


def build_memory_store() -> BaseMemoryStore:
    """Factory — returns the configured backend."""
    from config.settings import settings

    backend = settings.memory_backend
    if backend == "supabase":
        from core.memory_supabase import SupabaseMemoryStore
        return SupabaseMemoryStore()
    # Default: sqlite
    from core.memory_sqlite import SQLiteMemoryStore
    return SQLiteMemoryStore()
