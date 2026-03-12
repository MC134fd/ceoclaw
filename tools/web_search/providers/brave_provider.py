"""Brave Search API provider."""

from __future__ import annotations

import logging

import requests

from config.settings import settings
from tools.web_search.providers.base import BaseSearchProvider, SearchResponse, SearchResult

logger = logging.getLogger(__name__)

_BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"


class BraveSearchProvider(BaseSearchProvider):
    name = "brave"

    def is_available(self) -> bool:
        return bool(settings.brave_api_key)

    def search(self, query: str, max_results: int = 8) -> SearchResponse:
        if not self.is_available():
            return SearchResponse(
                provider=self.name,
                query=query,
                error="BRAVE_SEARCH_API_KEY not set",
            )
        try:
            resp = requests.get(
                _BRAVE_URL,
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "X-Subscription-Token": settings.brave_api_key,
                },
                params={"q": query, "count": min(max_results, 20)},
                timeout=settings.web_research_timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            logger.warning("[BraveSearch] request failed: %s", exc)
            return SearchResponse(provider=self.name, query=query, error=str(exc))

        web_results = data.get("web", {}).get("results", [])
        results = [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("description", ""),
                source=self.name,
            )
            for r in web_results[:max_results]
        ]
        return SearchResponse(results=results, provider=self.name, query=query)
