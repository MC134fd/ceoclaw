"""
Provider chain for live web research.

Tries providers in the order specified by WEB_RESEARCH_PROVIDER_ORDER,
falls back to deterministic templates when none succeed.
"""

from __future__ import annotations

import logging
from typing import Optional

from config.settings import settings
from tools.web_search.providers.base import BaseSearchProvider, SearchResponse, SearchResult
from tools.web_search.providers.brave_provider import BraveSearchProvider
from tools.web_search.providers.google_provider import GoogleCSEProvider

logger = logging.getLogger(__name__)

_PROVIDER_REGISTRY: dict[str, type[BaseSearchProvider]] = {
    "brave": BraveSearchProvider,
    "google": GoogleCSEProvider,
}


def _build_provider_chain() -> list[BaseSearchProvider]:
    chain: list[BaseSearchProvider] = []
    for name in settings.web_research_provider_order:
        cls = _PROVIDER_REGISTRY.get(name)
        if cls is None:
            logger.warning("[LiveResearch] unknown provider %r — skipping", name)
            continue
        instance = cls()
        if instance.is_available():
            chain.append(instance)
        else:
            logger.debug("[LiveResearch] provider %r unavailable (missing keys)", name)
    return chain


def search(query: str, max_results: Optional[int] = None) -> SearchResponse:
    """
    Run query through the provider chain.

    Returns the first successful response, or a fallback response with
    empty results and an informational error message.
    """
    if not settings.web_research_enabled:
        return SearchResponse(
            query=query,
            provider="disabled",
            error="WEB_RESEARCH_ENABLED=false",
        )

    n = max_results or settings.web_research_max_results
    chain = _build_provider_chain()

    for provider in chain:
        try:
            resp = provider.search(query, max_results=n)
            if resp.ok:
                logger.info(
                    "[LiveResearch] %s returned %d results for %r",
                    provider.name,
                    len(resp.results),
                    query,
                )
                return resp
            logger.debug("[LiveResearch] %s: %s", provider.name, resp.error)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[LiveResearch] %s raised: %s", provider.name, exc)

    # No provider succeeded
    return SearchResponse(
        query=query,
        provider="none",
        error="no live provider available — using deterministic fallback",
    )


def format_citations(response: SearchResponse) -> str:
    """Format search results as a numbered citation block."""
    if not response.results:
        return ""
    lines = []
    for i, r in enumerate(response.results, 1):
        lines.append(f"[{i}] {r.title}")
        lines.append(f"    {r.url}")
        if r.snippet:
            lines.append(f"    {r.snippet[:200]}")
    return "\n".join(lines)
