# CEOClaw Extensions vs OpenClaw Base

## What OpenClaw Provides

OpenClaw is the hackathon framework. It provides:
1. **FLock model API** — an OpenAI-compatible hosted LLM endpoint accessible via HTTP
2. **Base integration pattern** — the concept of wrapping the FLock API to build autonomous agents

The original OpenClaw interface (prompt format, domain heuristics, JSON parsers) is preserved in `integrations/openclaw_adapter.py` for reference. CEOClaw started from that pattern and superseded every component with production-grade versions.

## What CEOClaw Adds

### 1. FlockChatModel — LangChain BaseChatModel Adapter
**File:** `integrations/flock_client.py`

OpenClaw provides an HTTP endpoint. CEOClaw wraps it as a LangChain `BaseChatModel` subclass so it is interchangeable with any LangChain-compatible LLM. Adds:
- Configurable retry with exponential backoff (`max_retries`, sleep between attempts)
- Three auth header strategies: `bearer`, `litellm`, `both` (max compatibility)
- Automatic fallback to deterministic template responses on retry exhaustion — **run never crashes**
- Structured `response_metadata` on every `AIMessage`: `model_mode`, `fallback_used`, `fallback_reason`, `tokens_estimated`, `external_calls_delta`
- `cycle_index` parameter so fallback templates cycle through all four domains deterministically

**vs OpenClaw base:** The OpenClaw base used a direct `httpx.post()` call with no retry, no fallback, and no metadata. Our adapter adds 5 production-grade capabilities on top.

### 2. LangGraph StateGraph — Typed 7-Node Graph
**File:** `core/agent_loop.py`

OpenClaw provides no graph framework. CEOClaw uses LangGraph to compile a `StateGraph` with:
- 7 typed nodes: Planner, Router, 4 executors, Evaluator, StopCheck
- `MemorySaver` in-process checkpointing
- Conditional routing (`_route_from_router`, `_route_from_stop_check`)
- Stream mode execution so intermediate state is observable
- Exception-safe: if `build_graph()` fails, `graph_runs` status is persisted as `failed`

### 3. CEOClawState — 20-Field Typed State
**File:** `agents/__init__.py`

All inter-node data flows through a single `TypedDict` with `total=False`. Key additions:
- `errors` field uses `Annotated[list, add]` reducer — errors accumulate, never overwrite
- Budget fields: `tokens_used`, `external_calls`, `model_mode`, `fallback_count`
- Resilience fields: `consecutive_failures`, `circuit_breaker_active`, `stagnant_cycles`, `last_mrr`
- KPI fields: `weighted_score`, `trend_direction`, `previous_weighted_score`

### 4. Pydantic Prompt Layer — Validated I/O
**File:** `core/prompts.py`

OpenClaw's base used raw string templates and `json.loads()`. CEOClaw adds:
- Pydantic `PlannerOutput`, `EvaluatorOutput`, `ExecutorOutput` models with type constraints (`Literal["product","marketing","sales","ops"]`, `ge=0.0 le=1.0`)
- `safe_parse_planner()` and `safe_parse_evaluator()` with 4-level fallback cascade and structured error codes
- Rich prompt templates with stagnation context (current MRR %, weighted score, stagnation cycles, alert message)
- Weighted KPI computation (`compute_weighted_score`) with domain-specific normalization ceilings
- Trend detection (`compute_trend`) from consecutive cycle scores

### 5. Four Domain Executor Agents
**Files:** `agents/product_agent.py`, `agents/marketing_agent.py`, `agents/sales_agent.py`, `agents/ops_agent.py`

Each executor follows the same contract:
- Accepts `CEOClawState` + `RunnableConfig`
- Invokes domain-specific LangChain tools
- Persists artifacts via `persist_artifact()`
- Tracks `consecutive_failures` for circuit breaker
- Returns `ExecutorOutput` (Pydantic-validated)
- Never raises — all exceptions produce structured `error_entry`

OpenClaw base: no executor agents.

### 6. Four LangChain Tools
**Files:** `tools/website_builder.py`, `tools/seo_tool.py`, `tools/analytics_tool.py`, `tools/outreach_tool.py`

All tools use `@tool` decorator with `args_schema=PydanticModel`:
- **website_builder**: Generates SEO-valid HTML landing pages (title, meta description, h1, CTA, signup form); upserts `products` table row
- **seo_tool**: Audits HTML for title length, meta description, h1 count, keyword density; stores in `marketing_experiments`; returns score 0–100
- **analytics_tool**: Reads `metrics` table with trend delta computation; optionally records new snapshot
- **outreach_tool**: Generates personalized outreach messages for target list; writes `outreach_attempts` rows

OpenClaw base: no tools.

### 7. Weighted KPI Scoring Engine
**File:** `core/prompts.py` — `compute_weighted_score()`

```
score = traffic(10%) + signups(20%) + revenue(25%) + mrr(45%)
```

Beats the OpenClaw base's `compute_progress()` (MRR-only) with a four-dimensional composite that weights revenue contribution, signup momentum, and traffic traction independently.

### 8. Stagnation Detection & Domain Rotation
**Files:** `core/agent_loop.py` (EvaluatorNode), `agents/ceo_agent.py` (PlannerNode)

- EvaluatorNode tracks `stagnant_cycles` (MRR flat) and appends `stagnant_N_cycles` risk flags
- PlannerNode detects threshold breach, adds `⚠ STAGNATION ALERT` to model prompt, and applies deterministic domain rotation override as safety net
- CLI display shows ⏸ stagnant flag in cycle table

OpenClaw base: no stagnation detection.

### 9. Circuit Breaker
**File:** `core/agent_loop.py` — RouterNode

- Counts consecutive failures per executor key
- After 3 failures: overrides domain to `ops` for recovery cycle
- Success resets counter

OpenClaw base: no circuit breaker.

### 10. Budget Transparency
**Files:** `integrations/flock_client.py`, `agents/ceo_agent.py`, `core/agent_loop.py`, `data/database.py`

Full budget accounting per run:
- `model_mode`: `live` / `fallback` / `unknown` — never ambiguous
- `tokens_used`: heuristic word-count estimate
- `external_calls`: count of live HTTP calls to FLock
- `fallback_count`: how many model calls fell back

All fields persisted to `graph_runs` and surfaced in `/summary/latest`.

### 11. SQLite Persistence — 11 Tables
**File:** `data/database.py`

WAL mode, idempotent schema (`CREATE TABLE IF NOT EXISTS`), idempotent column migration (`PRAGMA table_info()` + `ALTER TABLE`). All node I/O logged with millisecond timing.

OpenClaw base: no persistence.

### 12. REST API — 8 Endpoints
**File:** `api/server.py`

FastAPI application exposing run data over HTTP. `/summary/latest` never returns 500 — always returns structured `status` field with `diagnostics` on error.

OpenClaw base: no API.

### 13. CLI — run / demo / export
**File:** `main.py`

Three subcommands with argparse:
- `run` — verbose streaming output
- `demo` — quiet run + cycle KPI table + auto-export + API quick-links
- `export` — Markdown report generation

OpenClaw base: no CLI.

### 14. 132-Test Suite
**Files:** `tests/` (7 files)

Full pytest suite covering graph compilation, node contracts, API endpoints, tool behavior, regression scenarios, and 5 specific reliability fixes. Isolated per-test databases using `tmp_path` fixtures.

OpenClaw base: no tests.

## Summary Table

| Capability | OpenClaw Base | CEOClaw Extension |
|-----------|--------------|-------------------|
| Model API | FLock HTTP endpoint | FlockChatModel (BaseChatModel, retry, fallback, metadata) |
| Orchestration | — | LangGraph 7-node StateGraph |
| State typing | — | CEOClawState TypedDict (20+ fields, error reducer) |
| Prompt engineering | String templates | Pydantic models, stagnation alerts, safe fallback parsers |
| Business domains | — | 4 executor agents (product, marketing, sales, ops) |
| Tools | — | 4 LangChain tools (website_builder, seo_tool, analytics_tool, outreach_tool) |
| KPI scoring | MRR progress only | Weighted 4-dim composite (MRR 45%, revenue 25%, signups 20%, traffic 10%) |
| Stagnation handling | — | Detection + domain rotation override |
| Fault tolerance | — | Circuit breaker (3 failures → ops recovery) |
| Budget tracking | — | model_mode, tokens, external_calls, fallback_count |
| Persistence | — | 11 SQLite tables, WAL mode, migration |
| API | — | 8 FastAPI endpoints |
| CLI | — | run / demo / export subcommands |
| Tests | — | 132 tests, 7 files |
