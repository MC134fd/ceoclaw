# CEOClaw — Autonomous Founder Agent

CEOClaw is a **production-grade autonomous founder agent** built on the **FLock model API (OpenClaw)**. It runs a self-directed startup loop — plan → execute → evaluate → repeat — iterating every business cycle toward a configurable MRR goal. It extends the OpenClaw base with a typed LangGraph state machine, market research capability, social publishing connectors, four autonomy modes, and a real-time chat UI.

---

## 1. Elevator Pitch

> Give CEOClaw a revenue goal. It autonomously plans domain strategy, conducts market research, builds landing pages, runs SEO analysis, drafts and publishes social content, and evaluates KPIs every cycle — all while showing you every decision in a live streaming UI.

**In 3 commands:**
```bash
pip install -r requirements.txt
python main.py demo --cycles 8 --mock-model
uvicorn api.server:app --port 8000  # then open http://localhost:8000/app
```

---

## 2. What OpenClaw Provides vs What CEOClaw Adds

**OpenClaw provides:**
- The FLock HTTP API endpoint (OpenAI-compatible hosted model)
- LiteLLM / x-litellm-api-key auth strategy
- The `BaseChatModel` interface contract

**CEOClaw adds (14 extensions):**

| Extension | File(s) | What it does |
|-----------|---------|-------------|
| **FLock BaseChatModel adapter** | `integrations/flock_client.py` | Wraps FLock HTTP API as LangChain `BaseChatModel` with retry, timeout, mock mode, structured metadata |
| **LangGraph StateGraph** | `core/agent_loop.py` | 7-node compiled graph: Planner → Router → [4 executors] → Evaluator → StopCheck |
| **Typed state + reducers** | `agents/__init__.py` | `CEOClawState` TypedDict with 22+ typed fields including `autonomy_mode` |
| **Pydantic prompt layer** | `core/prompts.py` | Rich prompt templates, Pydantic-validated output models, safe fallback parsers |
| **4 domain executor agents** | `agents/` | Product, Marketing, Sales, Ops with tool access |
| **Market research tool** | `tools/research_tool.py` | Structured reports: competitors, audience, opportunities, risks, experiments |
| **Social publishing connectors** | `tools/social_publishers/` | X and Instagram adapters with draft/approval/post lifecycle |
| **Autonomy modes A/B/C/D** | `tools/social_publisher.py` | Policy enforcement: autonomous, human approval, assisted, dry-run |
| **Weighted KPI scoring** | `core/prompts.py` | Composite 0–1 score: MRR 45% + Revenue 25% + Signups 20% + Traffic 10% |
| **Stagnation detector** | `core/agent_loop.py` | Tracks MRR-flat cycles; forces domain rotation after threshold |
| **Circuit breaker** | `core/agent_loop.py` | After 3 consecutive failures, RouterNode overrides to ops recovery |
| **Budget transparency** | `integrations/flock_client.py` | Tracks model_mode, tokens_used, external_calls, fallback_count per run |
| **SQLite persistence** | `data/database.py` | 14 tables including research_reports, social_posts, pending_approvals |
| **REST API + SSE streaming** | `api/server.py` | 14 FastAPI endpoints; real-time event stream; approval management |
| **Chat UI / Founder Cockpit** | `frontend/index.html` | Single-file dark-theme UI with timeline, research, social, approval panels |

**The canonical OpenClaw boundary** is `integrations/flock_client.py` — every model call in CEOClaw goes through `FlockChatModel(BaseChatModel)`. The `openclaw_adapter.py` file is preserved as the original OpenClaw interface reference but is not used at runtime.

---

## 3. Architecture

```
                         ┌─────────────────────────────────────────┐
                         │         FLock API (OpenClaw)            │
                         │   FlockChatModel (BaseChatModel)        │
                         │   mock | live | fallback modes          │
                         └───────────────┬─────────────────────────┘
                                         │ invoke()
START ──► PlannerNode ──► RouterNode ────┼──► ProductExecutorNode  (website_builder, seo_tool)
          (FLock model)   (circuit        │──► MarketingExecutorNode (research_tool, seo_tool,
          prompts.py      breaker +       │                           social_publisher)
          stagnation      domain          │──► SalesExecutorNode    (outreach_tool)
          override)       routing)        └──► OpsExecutorNode      (analytics_tool)
                                                      │
                                             EvaluatorNode ──► event_bus ──► SSE ──► Browser UI
                                             (FLock model · weighted KPI)
                                                      │
                                             StopCheckNode
                                          ┌───────────┴───────────┐
                                         END              PlannerNode
```

### Social publishing flow (autonomy-aware)

```
MarketingExecutor
  └── social_publisher_tool(autonomy_mode)
        ├── A_AUTONOMOUS   → publish() if creds exist, else draft
        ├── B_HUMAN_APPROVAL → pending_approvals table + SSE event → UI approval queue
        ├── C_ASSISTED     → pending_approvals table + wait for user selection
        └── D_DRY_RUN      → always draft, never publish
```

---

## 4. Autonomy Modes A/B/C/D

| Mode | ID | Behavior | Use case |
|------|----|----------|----------|
| **Autonomous** | `A_AUTONOMOUS` | Agent acts fully independently; publishes if credentials exist, drafts otherwise | Unattended production runs |
| **Human Approval** | `B_HUMAN_APPROVAL` | Queues all social publishes for human review before executing | Demo / controlled deployment |
| **Assisted** | `C_ASSISTED` | Presents options and waits for user selection at publishing steps | Interactive co-pilot mode |
| **Dry Run** | `D_DRY_RUN` | Never produces external side-effects; all content saved as drafts | Safe testing, CI, evaluation |

**How to select:**
- **UI**: Autonomy Mode dropdown in the left panel
- **API**: `"autonomy_mode": "D_DRY_RUN"` in `/chat` or `/runs/start` request body
- **CLI**: default is `A_AUTONOMOUS`

---

## 5. Quickstart (3 Commands)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run a full 8-cycle demo (no API key needed — mock mode)
python main.py demo --cycles 8 --mock-model

# 3. Start the chat UI
uvicorn api.server:app --reload --port 8000
# Open: http://localhost:8000/app
```

**To use the live FLock endpoint:**
```bash
cp .env.example .env
# Edit .env: set FLOCK_ENDPOINT and FLOCK_API_KEY
python main.py demo --cycles 8
```

---

## 6. Live / Mock / Fallback Behavior

| Mode | How to activate | What happens | Indicator |
|------|----------------|--------------|-----------|
| **Mock** | `--mock-model` or `FLOCK_MOCK_MODE=true` | Deterministic responses, zero HTTP calls | `Mode: mock` in CLI; cyan badge in UI |
| **Live** | Valid `FLOCK_ENDPOINT` + `FLOCK_API_KEY` | Real FLock API calls, token estimation | `[FLock] mode=LIVE` in logs; green badge |
| **Fallback** | Live + all retries fail | Automatic switch to mock tagged `[FALLBACK]` | `[FLock] FALLBACK activated` warning; amber badge |

---

## 7. Requirement Checklist

| Requirement | Status | Evidence |
|-------------|--------|----------|
| **Build on OpenClaw** | Met | `integrations/flock_client.py` wraps FLock HTTP API as `BaseChatModel`; all model calls go through this boundary |
| **Founder-oriented extensions** | Met | 14 extensions listed in §2; research, social, autonomy modes all novel |
| **Working multi-step business loop** | Met | 7-node LangGraph; `python main.py demo --cycles 8 --mock-model` |
| **Product domain** | Met | `agents/product_agent.py` + website_builder + seo_tool |
| **Marketing domain** | Met | `agents/marketing_agent.py` + research_tool + social_publisher |
| **Sales domain** | Met | `agents/sales_agent.py` + outreach_tool |
| **Ops domain** | Met | `agents/ops_agent.py` + analytics_tool + circuit breaker recovery |
| **Autonomy modes** | Met | A/B/C/D with policy enforcement, DB persistence, API + UI |
| **Research capability** | Met | `tools/research_tool.py` → structured report with competitors, audience, opportunities, risks |
| **Social publishing** | Met | X + Instagram adapters; draft/pending_approval/posted/failed states |
| **Tangible artifacts** | Met | landing_page, seo_report, research_report, social_drafted, outreach_batch, metrics_snapshot |
| **Real-time UI** | Met | SSE streaming to Founder Cockpit; timeline, research, social, approvals tabs |
| **API / programmatic access** | Met | 14 FastAPI endpoints including `/approvals`, `/research`, `/social-posts` |
| **Tests** | Met | 206 passing tests across 10 test files |
| **Persistence / audit trail** | Met | 14 SQLite tables; all artifacts, approvals, research reports persisted |

---

## 8. Example Run Outputs

### CLI Demo (8 cycles, mock mode)
```
  #  Domain       Action                            MRR   Score  Trend  Flags
  ────────────────────────────────────────────────────────────────────────
  1  product      build_landing_page            $  0.00   0.000   flat
  2  marketing    run_seo_analysis              $ 60.00   0.468     up
  3  sales        create_outreach_campaign      $ 60.00   0.468   flat
  4  ops          record_baseline_metrics       $ 70.00   0.548     up
  5  product      build_landing_page            $ 70.00   0.548   flat
  6  marketing    run_seo_analysis              $ 70.00   0.548   flat
  7  sales        create_outreach_campaign      $ 70.00   0.548   flat  ⏸ stagnant
  8  product      record_baseline_metrics       $ 70.00   0.548   flat  ⏸ stagnant
  ────────────────────────────────────────────────────────────────────────
  MRR: $70.00 · Score: 0.548 · Stop: max_cycles_reached(8)
```

### Research report (from `GET /runs/{id}/research`)
```json
{
  "topic": "marketing market research for CEOClaw MVP",
  "summary": "Content marketing and community-led growth dominate early-stage acquisition...",
  "competitors": [
    {"name": "HubSpot Blog", "stage": "enterprise", "weakness": "Generic, high competition keywords"},
    {"name": "Beehiiv newsletters", "stage": "growth", "weakness": "Requires large audience first"}
  ],
  "opportunities": [
    "Build-in-public content generates authentic audience",
    "Short-form video on LinkedIn outperforms text posts 3x"
  ],
  "risks": ["Algorithm changes can kill organic reach overnight"],
  "experiments": [
    {"name": "Twitter/X thread series", "metric": "click_through_rate", "duration_days": 14}
  ]
}
```

### Social post (from `GET /runs/{id}/social-posts`)
```json
{
  "platform": "x",
  "content": "Building CEOClaw MVP in public. Cycle 6: current MRR $70. Every decision is data-driven. #buildinpublic #saas",
  "status": "drafted",
  "cycle_count": 6
}
```

### API: `GET /summary/latest`
```json
{
  "status": "ok",
  "run_id": "...",
  "model_mode": "mock",
  "final_mrr": 70.0,
  "final_weighted_score": 0.548,
  "artifact_count": 12,
  "fallback_count": 0
}
```

---

## 9. Known Limitations & Next Milestones

**Current limitations:**
- MRR growth is simulated by `analytics_tool`; live payment integration (Stripe) would replace this
- Social publishing requires real API credentials (`X_API_KEY`, `INSTAGRAM_ACCESS_TOKEN`); without them, content is drafted
- Website builder generates HTML locally; production would deploy to CDN
- Research reports use deterministic templates; live web search would use Tavily/Perplexity API
- Token estimation is word-count heuristic, not exact API count

**Next milestones:**
1. Wire Stripe webhooks into `analytics_tool` for real MRR data
2. Integrate Tavily/Perplexity API into `research_tool` for live web research
3. Deploy landing pages to Vercel/Netlify via `website_builder`
4. Add memory layer for cross-run learning (`core/memory.py` scaffold exists)
5. Integrate SendGrid into `outreach_tool` for real email delivery

---

## Validation & Testing

```bash
# 206 tests across 10 files
python3 -m pytest tests/ -v

# Quick smoke check
python3 -m pytest tests/ -q          # expect: 206 passed

# API smoke test
uvicorn api.server:app --port 8000 &
curl http://localhost:8000/health
curl http://localhost:8000/summary/latest | python3 -m json.tool
```

**Test files:**
| File | Coverage |
|------|----------|
| `tests/test_agent_loop.py` | Graph compilation, run_graph, evaluator, stop conditions |
| `tests/test_agents.py` | All 4 executor nodes, planner node contracts |
| `tests/test_api.py` | All REST endpoints, error handling |
| `tests/test_chat_api.py` | SSE streaming, OpenClaw boundary, event bus |
| `tests/test_tools.py` | website_builder, seo_tool, analytics_tool, outreach_tool |
| `tests/test_demo.py` | CLI subcommand integration |
| `tests/test_regression.py` | 20 regression scenarios |
| `tests/test_fixes.py` | 26 reliability fix tests |
| `tests/test_autonomy.py` | Autonomy modes A/B/C/D policy enforcement |
| `tests/test_research.py` | Research tool output, persistence, API |
| `tests/test_social_publishers.py` | X/Instagram adapters, social post lifecycle |

---

## Repo Structure

```
ceoclaw/
├── main.py                         # CLI entry point
├── agents/
│   ├── __init__.py                 # CEOClawState TypedDict (22+ fields incl. autonomy_mode)
│   ├── ceo_agent.py                # PlannerNode
│   ├── product_agent.py            # ProductExecutorNode
│   ├── marketing_agent.py          # MarketingExecutorNode (+ research + social)
│   ├── sales_agent.py              # SalesExecutorNode
│   └── ops_agent.py                # OpsExecutorNode
├── core/
│   ├── agent_loop.py               # LangGraph build_graph(), run_graph()
│   ├── event_bus.py                # Thread-safe SSE event bus
│   ├── prompts.py                  # Pydantic models, prompt templates, KPI computation
│   └── state_manager.py            # API read layer over SQLite
├── integrations/
│   ├── flock_client.py             # FlockChatModel — canonical OpenClaw boundary
│   └── openclaw_adapter.py         # Original OpenClaw interface (preserved, not runtime)
├── tools/
│   ├── website_builder.py          # HTML landing page generation
│   ├── seo_tool.py                 # HTML SEO audit
│   ├── analytics_tool.py           # SQLite metrics reader/writer
│   ├── outreach_tool.py            # Outreach record generation
│   ├── research_tool.py            # Market research reports (NEW)
│   ├── social_publisher.py         # Unified social publish facade (NEW)
│   └── social_publishers/
│       ├── x_publisher.py          # X/Twitter adapter (NEW)
│       └── instagram_publisher.py  # Instagram adapter (NEW)
├── api/server.py                   # FastAPI (14 endpoints)
├── frontend/index.html             # Founder Cockpit UI (tabs: timeline/research/social/approvals)
├── data/database.py                # SQLite helpers, 14 tables
├── config/settings.py              # Settings (env vars)
├── tests/                          # 206 tests across 10 files
├── docs/
│   ├── architecture.md
│   ├── extensions_vs_openclaw.md
│   ├── submission_checklist.md
│   ├── judge_script_7min.md
│   └── demo_assets.md
├── .env.example
├── requirements.txt
└── docker-compose.yml
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `FLOCK_ENDPOINT` | _(empty)_ | FLock / OpenClaw VPS URL |
| `FLOCK_API_KEY` | _(empty)_ | API key |
| `FLOCK_MOCK_MODE` | `false` | `true` = deterministic mock |
| `X_API_KEY` | _(empty)_ | X/Twitter API key (optional) |
| `X_BEARER_TOKEN` | _(empty)_ | X/Twitter bearer token (optional) |
| `INSTAGRAM_ACCESS_TOKEN` | _(empty)_ | Instagram Graph API token (optional) |
| `INSTAGRAM_USER_ID` | _(empty)_ | Instagram user ID (optional) |
| `CEOCLAW_DATABASE_PATH` | `data/ceoclaw.db` | SQLite file path |

---

## REST API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Liveness probe |
| `GET /status` | Config + most recent run |
| `GET /metrics/latest` | Latest business metrics |
| `GET /runs/recent` | Recent graph runs |
| `GET /runs/{id}` | Full run details |
| `GET /runs/{id}/timeline` | Per-cycle KPI timeline |
| `GET /runs/{id}/events` | SSE stream (real-time events) |
| `GET /runs/{id}/approvals` | Pending approvals for a run |
| `GET /runs/{id}/research` | Research reports for a run |
| `GET /runs/{id}/social-posts` | Social posts for a run |
| `POST /chat` | Start a run (with autonomy_mode) |
| `POST /runs/start` | Start a run (alias) |
| `POST /approvals/{id}/decide` | Approve or reject a pending action |
| `GET /artifacts/recent` | Recent artifacts across all runs |
| `GET /kpi/trend` | KPI trend for charting |
| `GET /summary/latest` | One-shot judge summary |
| `GET /app`, `GET /` | Serve Founder Cockpit UI |
