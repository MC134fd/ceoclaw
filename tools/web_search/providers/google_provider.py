"""Google Custom Search Engine provider."""

from __future__ import annotations

import logging

import requests

from config.settings import settings
from tools.web_search.providers.base import BaseSearchProvider, SearchResponse, SearchResult

logger = logging.getLogger(__name__)

_GOOGLE_URL = "https://www.googleapis.com/customsearch/v1"


class GoogleCSEProvider(BaseSearchProvider):
    name = "google"

    def is_available(self) -> bool:
        return bool(settings.google_cse_api_key and settings.google_cse_cx)

    def search(self, query: str, max_results: int = 8) -> SearchResponse:
        if not self.is_available():
            return SearchResponse(
                provider=self.name,
                query=query,
                error="GOOGLE_CSE_API_KEY or GOOGLE_CSE_CX not set",
            )
        try:
            resp = requests.get(
                _GOOGLE_URL,
                params={
                    "key": settings.google_cse_api_key,
                    "cx": settings.google_cse_cx,
                    "q": query,
                    "num": min(max_results, 10),
                },
                timeout=settings.web_research_timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            logger.warning("[GoogleCSE] request failed: %s", exc)
            return SearchResponse(provider=self.name, query=query, error=str(exc))

        items = data.get("items", [])
        results = [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("link", ""),
                snippet=item.get("snippet", ""),
                source=self.name,
            )
            for item in items[:max_results]
        ]
        return SearchResponse(results=results, provider=self.name, query=query)
