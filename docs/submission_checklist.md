# CEOClaw Submission Checklist (v0.7)

## Requirement Verification

| Requirement | Status | File Evidence | Command to Verify |
|-------------|--------|--------------|-------------------|
| Build on OpenClaw | Met | `integrations/flock_client.py:122` — `class FlockChatModel(BaseChatModel)` | `pytest tests/test_chat_api.py::test_flockchatmodel_is_basechatmodel` |
| Founder-oriented use case | Met | README §2 — 14 extensions | `python main.py demo --cycles 4` |
| Multi-step business loop | Met | `core/agent_loop.py` — 7-node LangGraph | `pytest tests/test_agent_loop.py` |
| Product domain | Met | `agents/product_agent.py` + `tools/website_builder.py` | `pytest tests/test_tools.py::test_website_builder_creates_file` |
| Marketing domain | Met | `agents/marketing_agent.py` + research + social | `pytest tests/test_research.py` |
| Sales domain | Met | `agents/sales_agent.py` + `tools/outreach_tool.py` | `pytest tests/test_tools.py` |
| Ops domain | Met | `agents/ops_agent.py` + circuit breaker | `pytest tests/test_regression.py` |
| Autonomy modes | Met | `tools/social_publisher.py` A/B/C/D | `pytest tests/test_autonomy.py` |
| Research capability | Met | `tools/research_tool.py` | `pytest tests/test_research.py` |
| Social publishing | Met | `tools/social_publishers/` | `pytest tests/test_social_publishers.py` |
| Real-time UI | Met | `frontend/index.html` + SSE | `uvicorn api.server:app --port 8000` then `/app` |
| Intent-driven execution | Met | `core/intent_parser.py` — parse chat→ProductIntent | `pytest tests/test_workflow.py` |
| Chronological workflow | Met | `core/agent_loop.py` — 6-step sequence mode | `pytest tests/test_workflow.py::TestChronologicalRouter` |
| V1 scaffold + endpoints | Met | `tools/website_builder.py` — index+app+endpoints.json | `pytest tests/test_workflow.py::TestV1Generation` |
| Quality self-audit | Met | `tools/quality_audit_tool.py` + `agents/quality_agent.py` | `pytest tests/test_workflow.py::TestQualityAudit` |
| X-only social path | Met | `agents/marketing_agent.py` — Instagram gated by config | `pytest tests/test_workflow.py::TestXOnlySocial` |
| Tests | Met | 266 passing | `pytest tests/ -q` |
| REST API | Met | `api/server.py` — 14+ endpoints | `curl localhost:8000/health` |
| README | Met | `README.md` | — |

## Test Commands

```bash
# Full suite
python3 -m pytest tests/ -q

# By category
python3 -m pytest tests/test_autonomy.py -v          # 26 tests
python3 -m pytest tests/test_research.py -v          # 18 tests
python3 -m pytest tests/test_social_publishers.py -v # 18 tests
python3 -m pytest tests/test_chat_api.py -v          # 22 tests
```

## File Index

| File | Role |
|------|------|
| `integrations/flock_client.py` | OpenClaw boundary (canonical) |
| `integrations/openclaw_adapter.py` | OpenClaw reference (preserved, not runtime) |
| `core/agent_loop.py` | LangGraph graph + event emission |
| `core/event_bus.py` | Thread-safe SSE event bus |
| `agents/__init__.py` | CEOClawState (22+ fields) |
| `tools/research_tool.py` | Market research reports |
| `tools/social_publisher.py` | Unified social publish facade |
| `tools/social_publishers/x_publisher.py` | X/Twitter adapter |
| `tools/social_publishers/instagram_publisher.py` | Instagram adapter |
| `api/server.py` | 14+ FastAPI endpoints |
| `frontend/index.html` | Founder Cockpit UI (4 tabs) |
| `data/database.py` | 14 SQLite tables |

## Known Gaps (Honest Assessment)

- Research uses deterministic templates (no live web search) — Tavily integration is next milestone
- Social publishing requires real API credentials to post; without them, content is saved as drafts
- MRR is simulated by analytics_tool (no live Stripe integration)
- Token count is word-count heuristic, not exact API tokens
