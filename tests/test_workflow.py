"""
Tests for v0.7 instruction-driven workflow:
  - Intent parsing
  - Chronological sequence enforcement
  - V1 artifact + endpoint manifest generation
  - Quality audit output shape + feedback loop
  - SSE events include new step types
  - X-only social path
  - Memory write from quality audit
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# A. Intent parser
# ---------------------------------------------------------------------------

class TestIntentParser:
    def test_calorie_tracker_intent(self):
        from core.intent_parser import parse_intent
        result = parse_intent("build me a calorie tracker saas for fitness enthusiasts")
        assert result["product_name"] != "My Startup App"
        assert "tracker" in result["product_type"] or "saas" in result["product_type"]
        assert "fitness" in result["target_user"] or "consumer" in result["target_user"]
        assert any("calori" in f or "tracking" in f for f in result["core_features"])
        assert result["confidence"] > 0.3

    def test_crm_saas_intent(self):
        from core.intent_parser import parse_intent
        r = parse_intent("create a CRM SaaS for small businesses")
        assert "saas" in r["product_type"]
        assert "small" in r["target_user"]
        assert r["desired_endpoints"]

    def test_endpoints_present(self):
        from core.intent_parser import parse_intent
        r = parse_intent("build a calorie tracking app")
        assert len(r["desired_endpoints"]) > 0
        assert "/api/health" in r["desired_endpoints"]

    def test_nonfunctional_reqs_extracted(self):
        from core.intent_parser import parse_intent
        r = parse_intent("build a fast, secure, mobile-friendly calorie tracker")
        reqs_str = " ".join(r["nonfunctional_reqs"]).lower()
        assert "performance" in reqs_str or "fast" in reqs_str
        assert "security" in reqs_str or "secure" in reqs_str
        assert "mobile" in reqs_str

    def test_fallback_name_when_ambiguous(self):
        from core.intent_parser import parse_intent
        r = parse_intent("build something cool")
        assert r["product_name"]  # must always have a name
        assert len(r["product_name"]) > 0

    def test_confidence_higher_with_explicit_signals(self):
        from core.intent_parser import parse_intent
        vague = parse_intent("build something")
        specific = parse_intent("build me a calorie tracker saas for fitness enthusiasts with tracking and analytics")
        assert specific["confidence"] > vague["confidence"]

    def test_parse_intent_returns_all_keys(self):
        from core.intent_parser import parse_intent
        r = parse_intent("build me a todo app")
        required = [
            "product_type", "product_name", "target_user", "core_features",
            "nonfunctional_reqs", "desired_endpoints", "tech_stack", "raw_message", "confidence",
        ]
        for k in required:
            assert k in r, f"Missing key: {k}"


# ---------------------------------------------------------------------------
# B. Chronological sequence mode
# ---------------------------------------------------------------------------

class TestChronologicalRouter:
    def _make_state(self, step="", mode="chronological", failures=None):
        return {
            "run_id": "test-run",
            "cycle_count": 1,
            "selected_domain": "product",
            "consecutive_failures": failures or {},
            "workflow_mode": mode,
            "workflow_step": step,
        }

    def _make_config(self):
        from langchain_core.runnables import RunnableConfig
        return RunnableConfig(configurable={})

    def test_first_step_is_product_build(self):
        from core.agent_loop import router_node
        state = self._make_state(step="", mode="chronological")
        result = router_node(state, self._make_config())
        assert result["workflow_step"] == "product_build"

    def test_sequence_product_to_marketing(self):
        from core.agent_loop import router_node
        state = self._make_state(step="product_build", mode="chronological")
        result = router_node(state, self._make_config())
        assert result["workflow_step"] == "marketing_launch"

    def test_sequence_marketing_to_sales(self):
        from core.agent_loop import router_node
        state = self._make_state(step="marketing_launch", mode="chronological")
        result = router_node(state, self._make_config())
        assert result["workflow_step"] == "sales_outreach"

    def test_sequence_sales_to_ops(self):
        from core.agent_loop import router_node
        state = self._make_state(step="sales_outreach", mode="chronological")
        result = router_node(state, self._make_config())
        assert result["workflow_step"] == "ops_metrics"

    def test_sequence_ops_to_audit(self):
        from core.agent_loop import router_node
        state = self._make_state(step="ops_metrics", mode="chronological")
        result = router_node(state, self._make_config())
        assert result["workflow_step"] == "quality_audit"

    def test_sequence_audit_to_iterate(self):
        from core.agent_loop import router_node
        state = self._make_state(step="quality_audit", mode="chronological")
        result = router_node(state, self._make_config())
        assert result["workflow_step"] == "iterate"

    def test_iterate_wraps_to_product_build(self):
        from core.agent_loop import router_node
        state = self._make_state(step="iterate", mode="chronological")
        result = router_node(state, self._make_config())
        assert result["workflow_step"] == "product_build"

    def test_adaptive_mode_uses_domain(self):
        from core.agent_loop import router_node, _route_from_router
        state = self._make_state(step="", mode="adaptive")
        state["selected_domain"] = "marketing"
        result = router_node(state, self._make_config())
        assert result.get("workflow_step") != "product_build"

    def test_circuit_breaker_overrides_chrono_to_ops(self):
        from core.agent_loop import router_node
        state = self._make_state(mode="adaptive")
        state["consecutive_failures"] = {"product_executor": 3}
        state["selected_domain"] = "product"
        result = router_node(state, self._make_config())
        assert result["circuit_breaker_active"] is True
        assert result["selected_domain"] == "ops"

    def test_route_from_router_chrono_returns_executor(self):
        from core.agent_loop import _route_from_router
        state = {
            "workflow_mode": "chronological",
            "workflow_step": "quality_audit",
        }
        assert _route_from_router(state) == "quality_auditor"

    def test_route_from_router_chrono_product_build(self):
        from core.agent_loop import _route_from_router
        state = {"workflow_mode": "chronological", "workflow_step": "product_build"}
        assert _route_from_router(state) == "product_executor"


# ---------------------------------------------------------------------------
# C. V1 artifact + endpoint manifest
# ---------------------------------------------------------------------------

class TestV1Generation:
    def test_website_builder_creates_app_page(self, tmp_path):
        """website_builder_tool creates both index.html and app.html."""
        with patch("tools.website_builder.settings") as mock_s:
            mock_s.resolve_websites_dir.return_value = tmp_path
            from tools.website_builder import website_builder_tool, _slugify

            # Pre-create the product in a mock DB
            with patch("tools.website_builder._upsert_product"):
                result = website_builder_tool.invoke({
                    "product_name": "Calorie Tracker",
                    "tagline": "Track your calories effortlessly.",
                    "features": ["Calorie tracking", "Macro insights"],
                    "cta_text": "Start free",
                    "target_user": "fitness enthusiasts",
                    "endpoint_manifest": ["/api/health", "/api/entries"],
                })

        data = json.loads(result)
        assert data["status"] == "success"
        assert "app_path" in data
        assert data["endpoint_manifest"] == ["/api/health", "/api/entries"]

    def test_landing_page_has_target_user(self, tmp_path):
        with patch("tools.website_builder.settings") as mock_s:
            mock_s.resolve_websites_dir.return_value = tmp_path
            with patch("tools.website_builder._upsert_product"):
                from tools.website_builder import website_builder_tool
                result = website_builder_tool.invoke({
                    "product_name": "FitTrack",
                    "tagline": "Your fitness companion.",
                    "features": ["Calorie tracking"],
                    "target_user": "gym goers",
                    "endpoint_manifest": [],
                })
        data = json.loads(result)
        slug = data["slug"]
        page = (tmp_path / slug / "index.html").read_text()
        assert "gym goers" in page

    def test_landing_page_high_quality_defaults(self, tmp_path):
        """Generated HTML should pass basic quality checks."""
        with patch("tools.website_builder.settings") as mock_s:
            mock_s.resolve_websites_dir.return_value = tmp_path
            with patch("tools.website_builder._upsert_product"):
                from tools.website_builder import website_builder_tool
                result = website_builder_tool.invoke({
                    "product_name": "HealthPal",
                    "tagline": "Be healthier.",
                    "features": ["Tracking"],
                    "target_user": "",
                    "endpoint_manifest": [],
                })
        data = json.loads(result)
        slug = data["slug"]
        html = (tmp_path / slug / "index.html").read_text()
        assert 'lang="en"' in html
        assert 'name="viewport"' in html
        assert "Inter" in html or "font-family" in html
        assert "line-height" in html
        assert '<h1' in html  # may have attributes like id="hero-heading"

    def test_endpoint_manifest_json_written(self, tmp_path):
        with patch("tools.website_builder.settings") as mock_s:
            mock_s.resolve_websites_dir.return_value = tmp_path
            with patch("tools.website_builder._upsert_product"):
                from tools.website_builder import website_builder_tool
                result = website_builder_tool.invoke({
                    "product_name": "CalApp",
                    "tagline": "T",
                    "features": [],
                    "endpoint_manifest": ["/api/health", "/api/entries"],
                })
        data = json.loads(result)
        slug = data["slug"]
        manifest = json.loads((tmp_path / slug / "endpoints.json").read_text())
        assert "/api/health" in manifest["endpoints"]
        assert "/api/entries" in manifest["endpoints"]


# ---------------------------------------------------------------------------
# D. Quality audit tool
# ---------------------------------------------------------------------------

class TestQualityAudit:
    def _write_page(self, tmp_path, slug: str, html: str) -> None:
        page_dir = tmp_path / slug
        page_dir.mkdir(parents=True, exist_ok=True)
        (page_dir / "index.html").write_text(html, encoding="utf-8")

    def test_missing_page_returns_zero(self, tmp_path):
        with patch("tools.quality_audit_tool.settings") as mock_s:
            mock_s.resolve_websites_dir.return_value = tmp_path
            with patch("tools.quality_audit_tool.persist_artifact"):
                from tools.quality_audit_tool import quality_audit_tool
                result = quality_audit_tool.invoke({
                    "product_name": "MissingProd",
                    "run_id": "",
                    "cycle_count": 0,
                })
        data = json.loads(result)
        assert data["score"] == 0
        assert data["grade"] == "F"

    def test_basic_html_scores_nonzero(self, tmp_path):
        self._write_page(
            tmp_path,
            "my-product",
            """<!DOCTYPE html><html lang="en"><head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <meta name="description" content="A product">
            <title>My Product</title>
            <style>body{font-family:'Inter',sans-serif;line-height:1.6;font-size:1rem;}
            h1{font-size:2rem;font-weight:800;margin-bottom:1rem;color:#111;}
            .cta{background:#2563eb;color:#fff;padding:.8rem 2rem;border-radius:8px;}
            </style>
            </head><body role="main">
            <h1>My Product</h1><p>Tagline here. Free trial.</p>
            <a class="cta" href="#s">Start free</a>
            <h2>Features</h2>
            <footer>&copy; 2025 My Product. <a href="/privacy">Privacy</a></footer>
            </body></html>""",
        )
        with patch("tools.quality_audit_tool.settings") as mock_s:
            mock_s.resolve_websites_dir.return_value = tmp_path
            with patch("tools.quality_audit_tool.persist_artifact"):
                from tools.quality_audit_tool import quality_audit_tool
                result = quality_audit_tool.invoke({
                    "product_name": "My Product",
                    "run_id": "",
                    "cycle_count": 0,
                })
        data = json.loads(result)
        assert data["score"] > 40
        assert "scorecard" in data
        assert "improvement_plan" in data
        assert "critical_defects" in data
        assert "grade" in data

    def test_scorecard_has_all_dimensions(self, tmp_path):
        self._write_page(tmp_path, "foo-app", "<html><body><h1>T</h1></body></html>")
        with patch("tools.quality_audit_tool.settings") as mock_s:
            mock_s.resolve_websites_dir.return_value = tmp_path
            with patch("tools.quality_audit_tool.persist_artifact"):
                from tools.quality_audit_tool import quality_audit_tool
                result = quality_audit_tool.invoke({"product_name": "Foo App"})
        data = json.loads(result)
        sc = data["scorecard"]
        assert "visual_hierarchy" in sc
        assert "typography" in sc
        assert "cta_clarity" in sc
        assert "mobile_responsiveness" in sc
        assert "trust_signals" in sc
        assert "performance" in sc
        assert "accessibility" in sc

    def test_premium_score_present(self, tmp_path):
        self._write_page(tmp_path, "bar-app", "<html><body><h1>T</h1></body></html>")
        with patch("tools.quality_audit_tool.settings") as mock_s:
            mock_s.resolve_websites_dir.return_value = tmp_path
            with patch("tools.quality_audit_tool.persist_artifact"):
                from tools.quality_audit_tool import quality_audit_tool
                result = quality_audit_tool.invoke({"product_name": "Bar App"})
        data = json.loads(result)
        assert "premium_score" in data
        assert isinstance(data["premium_score"], int)

    def test_improvement_plan_is_list(self, tmp_path):
        self._write_page(tmp_path, "baz", "<html><body></body></html>")
        with patch("tools.quality_audit_tool.settings") as mock_s:
            mock_s.resolve_websites_dir.return_value = tmp_path
            with patch("tools.quality_audit_tool.persist_artifact"):
                from tools.quality_audit_tool import quality_audit_tool
                result = quality_audit_tool.invoke({"product_name": "Baz"})
        data = json.loads(result)
        assert isinstance(data["improvement_plan"], list)
        assert len(data["improvement_plan"]) > 0

    def test_audit_writes_to_memory(self, tmp_path):
        self._write_page(tmp_path, "mem-app", "<html lang='en'><body><h1>T</h1></body></html>")
        mock_store = MagicMock()
        with patch("core.memory_store.build_memory_store", return_value=mock_store):
            from agents.quality_agent import _write_audit_memory
            _write_audit_memory("run-1", 72, "B", ["no_trust_signals"], ["Add trust signals"])
        mock_store.set.assert_called()
        calls = [c[0] for c in mock_store.set.call_args_list]
        keys_set = [c[0] for c in calls]
        assert "last_quality_score" in keys_set


# ---------------------------------------------------------------------------
# E. SSE events include new step types
# ---------------------------------------------------------------------------

class TestSSEStepEvents:
    def test_step_to_event_mapping_complete(self):
        from core.agent_loop import _STEP_TO_EVENT, _CHRONO_STEPS
        for step in _CHRONO_STEPS:
            assert step in _STEP_TO_EVENT, f"Missing event for step {step}"

    def test_event_types_are_strings(self):
        from core.agent_loop import _STEP_TO_EVENT
        expected_events = {
            "product_build": "product_spec_ready",
            "marketing_launch": "marketing_executed",
            "sales_outreach": "sales_executed",
            "ops_metrics": "ops_evaluated",
            "quality_audit": "quality_audited",
            "iterate": "iteration_planned",
        }
        for step, expected in expected_events.items():
            assert _STEP_TO_EVENT[step] == expected

    def test_initial_state_includes_workflow_fields(self):
        from core.agent_loop import _initial_state
        state = _initial_state("r1", 100.0, workflow_mode="chronological")
        assert state["workflow_mode"] == "chronological"
        assert state["workflow_step"] == ""
        assert state["product_intent"] == {}
        assert state["quality_audit"] == {}
        assert state["iteration_tasks"] == []

    def test_intent_parsed_event_emitted_when_intent_present(self):
        from core.agent_loop import _initial_state, run_graph
        from unittest.mock import patch, MagicMock

        intent = {"product_name": "FitTrack", "product_type": "saas",
                  "target_user": "athletes", "core_features": ["tracking"],
                  "confidence": 0.8, "desired_endpoints": [], "nonfunctional_reqs": [],
                  "tech_stack": "html", "raw_message": "build FitTrack"}

        emitted = []

        with patch("core.agent_loop.build_graph") as mock_build, \
             patch("core.agent_loop._bus") as mock_bus, \
             patch("core.agent_loop.init_db"), \
             patch("core.agent_loop.start_graph_run"), \
             patch("core.agent_loop.finish_graph_run"):
            mock_bus.emit.side_effect = lambda run_id, ev: emitted.append(ev)
            mock_bus.mark_done = MagicMock()

            mock_graph = MagicMock()
            mock_graph.stream.return_value = []
            mock_build.return_value = mock_graph

            run_graph(cycles=1, mock_mode=True, run_id="test-r", product_intent=intent)

        intent_events = [e for e in emitted if e.get("type") == "intent_parsed"]
        assert len(intent_events) == 1
        assert intent_events[0]["product_name"] == "FitTrack"


# ---------------------------------------------------------------------------
# F. X-only social path
# ---------------------------------------------------------------------------

class TestXOnlySocial:
    def test_x_platform_always_used(self):
        """X should always be in the platforms list regardless of Instagram config."""
        from unittest.mock import patch, MagicMock
        import json

        state = {
            "run_id": "r1",
            "cycle_count": 1,
            "selected_domain": "marketing",
            "selected_action": "social_publish_campaign",
            "consecutive_failures": {},
            "autonomy_mode": "D_DRY_RUN",
            "active_product": {"name": "TestApp"},
            "product_intent": {},
            "latest_metrics": {},
        }

        calls = []

        def mock_social_invoke(params):
            calls.append(params["platform"])
            return json.dumps({"status": "drafted", "platform": params["platform"]})

        import agents.marketing_agent as _mkt
        with patch.object(_mkt, "social_publisher_tool") as mock_sp, \
             patch.object(_mkt, "seo_tool") as mock_seo, \
             patch.object(_mkt, "analytics_tool") as mock_analytics, \
             patch.object(_mkt, "research_tool") as mock_research, \
             patch.object(_mkt, "settings") as mock_settings, \
             patch.object(_mkt, "persist_artifact"):

            mock_sp.invoke.side_effect = mock_social_invoke
            mock_seo.invoke.return_value = json.dumps({"seo_score": 80, "issues": [], "recommendations": []})
            mock_analytics.invoke.return_value = json.dumps({"latest": {"website_traffic": 100, "signups": 5, "mrr": 0.0, "conversion_rate": 0.05, "revenue": 0.0}, "summary": "ok", "trend": {}})
            mock_research.invoke.return_value = json.dumps({"status": "success", "summary": "ok", "opportunities": [], "competitors": [], "audience": {}, "risks": [], "experiments": []})

            # No Instagram configured
            mock_settings.instagram_access_token = ""
            mock_settings.instagram_user_id = ""

            from langchain_core.runnables import RunnableConfig
            _mkt.marketing_executor_node(state, RunnableConfig(configurable={}))

        assert "x" in calls
        assert "instagram" not in calls

    def test_instagram_added_when_configured(self):
        """Instagram should be added when both credentials are set."""
        import json
        from unittest.mock import patch, MagicMock

        state = {
            "run_id": "r1",
            "cycle_count": 1,
            "selected_domain": "marketing",
            "selected_action": "social_publish_campaign",
            "consecutive_failures": {},
            "autonomy_mode": "D_DRY_RUN",
            "active_product": {"name": "TestApp"},
            "product_intent": {},
            "latest_metrics": {},
        }
        calls = []

        import agents.marketing_agent as _mkt2
        with patch.object(_mkt2, "social_publisher_tool") as mock_sp, \
             patch.object(_mkt2, "seo_tool") as mock_seo, \
             patch.object(_mkt2, "analytics_tool") as mock_analytics, \
             patch.object(_mkt2, "research_tool") as mock_research, \
             patch.object(_mkt2, "settings") as mock_settings, \
             patch.object(_mkt2, "persist_artifact"):

            mock_sp.invoke.side_effect = lambda p: (
                calls.append(p["platform"]) or
                json.dumps({"status": "drafted", "platform": p["platform"]})
            )
            mock_seo.invoke.return_value = json.dumps({"seo_score": 80, "issues": [], "recommendations": []})
            mock_analytics.invoke.return_value = json.dumps({"latest": {"website_traffic": 0, "signups": 0, "mrr": 0.0, "conversion_rate": 0.0, "revenue": 0.0}, "summary": "", "trend": {}})
            mock_research.invoke.return_value = json.dumps({"status": "success", "summary": "", "opportunities": [], "competitors": [], "audience": {}, "risks": [], "experiments": []})

            mock_settings.instagram_access_token = "tok"
            mock_settings.instagram_user_id = "123"

            from langchain_core.runnables import RunnableConfig
            _mkt2.marketing_executor_node(state, RunnableConfig(configurable={}))

        assert "x" in calls
        assert "instagram" in calls


# ---------------------------------------------------------------------------
# G. Chat endpoint drives product_intent
# ---------------------------------------------------------------------------

class TestChatIntentIntegration:
    def test_chat_endpoint_parses_message(self):
        from fastapi.testclient import TestClient
        with patch("core.agent_loop.init_db"), \
             patch("threading.Thread") as mock_thread:
            mock_thread.return_value.start = MagicMock()
            from api.server import app
            client = TestClient(app)
            resp = client.post("/chat", json={
                "message": "build me a calorie tracker for fitness enthusiasts",
                "mock_mode": True,
                "cycles": 1,
            })
        assert resp.status_code == 200
        data = resp.json()
        assert "run_id" in data
        assert "product_intent" in data
        pi = data["product_intent"]
        assert pi is not None
        assert pi["product_name"] != "My Startup App"
        assert pi["confidence"] > 0.2

    def test_chat_empty_message_still_starts(self):
        from fastapi.testclient import TestClient
        with patch("threading.Thread") as mock_thread:
            mock_thread.return_value.start = MagicMock()
            from api.server import app
            client = TestClient(app)
            resp = client.post("/chat", json={"message": "", "mock_mode": True, "cycles": 1})
        assert resp.status_code == 200

    def test_workflow_mode_defaults_to_chronological(self):
        from fastapi.testclient import TestClient
        with patch("threading.Thread") as mock_thread:
            mock_thread.return_value.start = MagicMock()
            from api.server import app
            client = TestClient(app)
            resp = client.post("/chat", json={"message": "build a crm", "mock_mode": True})
        assert resp.status_code == 200
        assert resp.json()["workflow_mode"] == "chronological"
