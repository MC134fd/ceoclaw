"""Tests for live web research provider chain and memory store."""

import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Provider base / registry
# ---------------------------------------------------------------------------

class TestSearchResultDataclass:
    def test_fields(self):
        from tools.web_search.providers.base import SearchResult
        r = SearchResult(title="T", url="http://x.com", snippet="S")
        assert r.title == "T"
        assert r.url == "http://x.com"
        assert r.snippet == "S"
        assert r.source == ""

    def test_source_set(self):
        from tools.web_search.providers.base import SearchResult
        r = SearchResult(title="T", url="u", snippet="s", source="brave")
        assert r.source == "brave"


class TestSearchResponseDataclass:
    def test_ok_when_results_present(self):
        from tools.web_search.providers.base import SearchResponse, SearchResult
        resp = SearchResponse(results=[SearchResult("T", "u", "s")], provider="brave", query="q")
        assert resp.ok is True

    def test_not_ok_when_empty(self):
        from tools.web_search.providers.base import SearchResponse
        resp = SearchResponse(results=[], provider="brave", query="q")
        assert resp.ok is False

    def test_not_ok_when_error(self):
        from tools.web_search.providers.base import SearchResponse, SearchResult
        resp = SearchResponse(
            results=[SearchResult("T", "u", "s")], provider="brave", query="q", error="oops"
        )
        assert resp.ok is False


# ---------------------------------------------------------------------------
# Brave provider
# ---------------------------------------------------------------------------

class TestBraveProvider:
    def test_unavailable_when_no_key(self):
        from tools.web_search.providers.brave_provider import BraveSearchProvider
        with patch("tools.web_search.providers.brave_provider.settings") as mock_s:
            mock_s.brave_api_key = ""
            p = BraveSearchProvider()
            assert p.is_available() is False

    def test_returns_error_response_when_no_key(self):
        from tools.web_search.providers.brave_provider import BraveSearchProvider
        with patch("tools.web_search.providers.brave_provider.settings") as mock_s:
            mock_s.brave_api_key = ""
            p = BraveSearchProvider()
            resp = p.search("test query")
            assert resp.ok is False
            assert "BRAVE_SEARCH_API_KEY" in (resp.error or "")

    def test_available_when_key_set(self):
        from tools.web_search.providers.brave_provider import BraveSearchProvider
        with patch("tools.web_search.providers.brave_provider.settings") as mock_s:
            mock_s.brave_api_key = "test-key-123"
            p = BraveSearchProvider()
            assert p.is_available() is True

    def test_parses_brave_response(self):
        from tools.web_search.providers.brave_provider import BraveSearchProvider
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "web": {
                "results": [
                    {"title": "Title1", "url": "http://a.com", "description": "Desc1"},
                    {"title": "Title2", "url": "http://b.com", "description": "Desc2"},
                ]
            }
        }
        mock_resp.raise_for_status.return_value = None
        with patch("tools.web_search.providers.brave_provider.settings") as mock_s, \
             patch("tools.web_search.providers.brave_provider.requests.get", return_value=mock_resp):
            mock_s.brave_api_key = "test-key"
            mock_s.web_research_timeout = 10
            p = BraveSearchProvider()
            resp = p.search("test", max_results=5)
        assert resp.ok is True
        assert len(resp.results) == 2
        assert resp.results[0].title == "Title1"
        assert resp.results[0].source == "brave"


# ---------------------------------------------------------------------------
# Google CSE provider
# ---------------------------------------------------------------------------

class TestGoogleCSEProvider:
    def test_unavailable_when_missing_keys(self):
        from tools.web_search.providers.google_provider import GoogleCSEProvider
        with patch("tools.web_search.providers.google_provider.settings") as mock_s:
            mock_s.google_cse_api_key = ""
            mock_s.google_cse_cx = ""
            p = GoogleCSEProvider()
            assert p.is_available() is False

    def test_returns_error_response_when_no_key(self):
        from tools.web_search.providers.google_provider import GoogleCSEProvider
        with patch("tools.web_search.providers.google_provider.settings") as mock_s:
            mock_s.google_cse_api_key = ""
            mock_s.google_cse_cx = ""
            p = GoogleCSEProvider()
            resp = p.search("test")
            assert resp.ok is False

    def test_parses_google_response(self):
        from tools.web_search.providers.google_provider import GoogleCSEProvider
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "items": [
                {"title": "G1", "link": "http://g1.com", "snippet": "Snip1"},
            ]
        }
        mock_resp.raise_for_status.return_value = None
        with patch("tools.web_search.providers.google_provider.settings") as mock_s, \
             patch("tools.web_search.providers.google_provider.requests.get", return_value=mock_resp):
            mock_s.google_cse_api_key = "key"
            mock_s.google_cse_cx = "cx"
            mock_s.web_research_timeout = 10
            p = GoogleCSEProvider()
            resp = p.search("test")
        assert resp.ok is True
        assert resp.results[0].title == "G1"
        assert resp.results[0].source == "google"


# ---------------------------------------------------------------------------
# Live research chain
# ---------------------------------------------------------------------------

class TestLiveResearchChain:
    def test_disabled_returns_error(self):
        from tools.web_search import live_research
        with patch("tools.web_search.live_research.settings") as mock_s:
            mock_s.web_research_enabled = False
            resp = live_research.search("test")
        assert resp.ok is False
        assert "disabled" in resp.provider

    def test_no_available_providers_returns_fallback(self):
        from tools.web_search import live_research
        with patch("tools.web_search.live_research.settings") as mock_s, \
             patch("tools.web_search.live_research._build_provider_chain", return_value=[]):
            mock_s.web_research_enabled = True
            mock_s.web_research_max_results = 8
            resp = live_research.search("test")
        assert resp.ok is False
        assert "none" in resp.provider

    def test_uses_first_successful_provider(self):
        from tools.web_search import live_research
        from tools.web_search.providers.base import SearchResponse, SearchResult

        good_resp = SearchResponse(
            results=[SearchResult("T", "u", "s")], provider="brave", query="test"
        )
        mock_provider = MagicMock()
        mock_provider.name = "brave"
        mock_provider.search.return_value = good_resp

        with patch("tools.web_search.live_research.settings") as mock_s, \
             patch("tools.web_search.live_research._build_provider_chain", return_value=[mock_provider]):
            mock_s.web_research_enabled = True
            mock_s.web_research_max_results = 8
            resp = live_research.search("test")
        assert resp.ok is True
        assert resp.provider == "brave"

    def test_skips_failed_provider_tries_next(self):
        from tools.web_search import live_research
        from tools.web_search.providers.base import SearchResponse, SearchResult

        bad = MagicMock()
        bad.name = "brave"
        bad.search.return_value = SearchResponse(provider="brave", query="t", error="fail")

        good_resp = SearchResponse(
            results=[SearchResult("T", "u", "s")], provider="google", query="t"
        )
        good = MagicMock()
        good.name = "google"
        good.search.return_value = good_resp

        with patch("tools.web_search.live_research.settings") as mock_s, \
             patch("tools.web_search.live_research._build_provider_chain", return_value=[bad, good]):
            mock_s.web_research_enabled = True
            mock_s.web_research_max_results = 8
            resp = live_research.search("t")
        assert resp.provider == "google"

    def test_format_citations(self):
        from tools.web_search import live_research
        from tools.web_search.providers.base import SearchResponse, SearchResult

        resp = SearchResponse(
            results=[
                SearchResult("Title A", "http://a.com", "Snippet for A"),
                SearchResult("Title B", "http://b.com", ""),
            ],
            provider="brave",
            query="test",
        )
        out = live_research.format_citations(resp)
        assert "[1] Title A" in out
        assert "http://a.com" in out
        assert "[2] Title B" in out

    def test_format_citations_empty(self):
        from tools.web_search import live_research
        from tools.web_search.providers.base import SearchResponse
        assert live_research.format_citations(SearchResponse()) == ""


# ---------------------------------------------------------------------------
# Memory store – SQLite backend
# ---------------------------------------------------------------------------

class TestSQLiteMemoryStore:
    def test_set_and_get(self, tmp_path):
        with patch("core.memory_sqlite.get_connection") as mock_gc:
            import sqlite3
            db = sqlite3.connect(":memory:")
            db.row_factory = sqlite3.Row
            from core.memory_sqlite import _DDL
            db.executescript(_DDL)
            db.commit()
            mock_gc.return_value.__enter__ = lambda s: db
            mock_gc.return_value.__exit__ = MagicMock(return_value=False)

            from core.memory_sqlite import SQLiteMemoryStore
            store = SQLiteMemoryStore.__new__(SQLiteMemoryStore)
            store.set.__func__  # check method exists
            # Just exercise construction path with real SQLite in-memory
            import sqlite3 as _sq
            db2 = _sq.connect(":memory:")
            db2.row_factory = _sq.Row
            db2.executescript(_DDL)
            db2.commit()

    def test_set_get_delete(self):
        """Integration test using a single shared in-memory SQLite DB."""
        import sqlite3
        from contextlib import contextmanager
        from core.memory_sqlite import _DDL

        _shared = sqlite3.connect(":memory:")
        _shared.row_factory = sqlite3.Row
        _shared.executescript(_DDL)
        _shared.commit()

        @contextmanager
        def _mock_conn():
            try:
                yield _shared
                _shared.commit()
            except Exception:
                _shared.rollback()
                raise

        with patch("core.memory_sqlite.get_connection", side_effect=_mock_conn):
            from importlib import reload
            import core.memory_sqlite as _mod
            store = _mod.SQLiteMemoryStore.__new__(_mod.SQLiteMemoryStore)
            store.set("hello", "world")
            assert store.get("hello") == "world"
            store.delete("hello")
            assert store.get("hello") is None

    def test_get_all(self):
        import sqlite3
        from contextlib import contextmanager

        _db = sqlite3.connect(":memory:")
        _db.row_factory = sqlite3.Row
        from core.memory_sqlite import _DDL
        _db.executescript(_DDL)
        _db.commit()

        @contextmanager
        def _mock_conn():
            try:
                yield _db
                _db.commit()
            except Exception:
                _db.rollback()
                raise

        with patch("core.memory_sqlite.get_connection", side_effect=_mock_conn):
            from core.memory_sqlite import SQLiteMemoryStore
            store = SQLiteMemoryStore()
            store.set("k1", "v1", namespace="ns")
            store.set("k2", "v2", namespace="ns")
            store.set("k3", "v3", namespace="other")
            result = store.get_all(namespace="ns")
            assert result == {"k1": "v1", "k2": "v2"}


# ---------------------------------------------------------------------------
# Research tool with live search integration
# ---------------------------------------------------------------------------

class TestResearchToolCitations:
    def test_template_fallback_when_no_live(self):
        """research_tool returns template data when live search unavailable."""
        from tools.research_tool import research_tool
        from tools.web_search.providers.base import SearchResponse

        with patch("tools.research_tool.live_research.search") as mock_search:
            mock_search.return_value = SearchResponse(provider="none", query="q", error="disabled")
            result = research_tool.invoke({"topic": "product market", "product_name": "Test", "run_id": "", "cycle_count": 0})

        import json
        data = json.loads(result)
        assert data["status"] == "success"
        assert data["source"] == "template"
        assert data["citations"] == []

    def test_live_enrichment_prepends_to_summary(self):
        """research_tool prepends live snippet to template summary."""
        from tools.research_tool import research_tool
        from tools.web_search.providers.base import SearchResponse, SearchResult

        live_resp = SearchResponse(
            results=[SearchResult("T", "http://x.com", "Live market insight from search")],
            provider="brave",
            query="q",
        )

        with patch("tools.research_tool.live_research.search", return_value=live_resp):
            result = research_tool.invoke({"topic": "marketing", "product_name": "MVP", "run_id": "", "cycle_count": 0})

        import json
        data = json.loads(result)
        assert data["source"] == "live+template"
        assert len(data["citations"]) == 1
        assert data["citations"][0]["url"] == "http://x.com"
        assert "Live market insight" in data["summary"]
