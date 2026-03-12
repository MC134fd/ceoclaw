"""Abstract base class for web search providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    source: str = ""  # provider name


@dataclass
class SearchResponse:
    results: list[SearchResult] = field(default_factory=list)
    provider: str = ""
    query: str = ""
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and len(self.results) > 0


class BaseSearchProvider(ABC):
    """Interface all search providers must implement."""

    name: str = "base"

    @abstractmethod
    def search(self, query: str, max_results: int = 8) -> SearchResponse:
        """Execute a search query and return structured results."""
        ...

    def is_available(self) -> bool:
        """Return True if this provider has the required credentials."""
        return True
