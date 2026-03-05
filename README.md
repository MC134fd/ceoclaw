# CEOClaw

Autonomous founder agent that iterates toward **$100 MRR** using a strict
LangGraph graph topology backed by SQLite persistence and a FLock model adapter.

---

## Graph topology

```
START
 └─> PlannerNode       (CEO agent – FLock model, no tools)
      └─> RouterNode   (validates domain, conditional edge)
           ├─> ProductExecutorNode   (website_builder, seo_tool)
           ├─> MarketingExecutorNode (seo_tool, analytics_tool)
           ├─> SalesExecutorNode     (outreach_tool)
           └─> OpsExecutorNode       (analytics_tool)
                └─> EvaluatorNode    (FLock model, scorecard update)
                     └─> StopCheckNode
                          ├─> END           (goal reached or max cycles hit)
                          └─> PlannerNode   (loop continues)
```

### Node contracts

| Node | Inputs consumed | Outputs produced |
|------|-----------------|-----------------|
| **PlannerNode** | `latest_metrics`, `active_product`, `goal_mrr`, `cycle_count` | `selected_domain`, `selected_action`, `strategy`, `cycle_count+1` |
| **RouterNode** | `selected_domain` | `selected_domain` (validated) |
| **\*ExecutorNode** | `selected_action`, `active_product` | `executor_result`, `active_product?`, `latest_metrics?` |
| **EvaluatorNode** | `latest_metrics`, `executor_result`, `goal_mrr` | `evaluation` (kpi_snapshot, progress_score, recommendation, risk_flags) |
| **StopCheckNode** | `evaluation.progress_score`, `cycle_count`, `errors` | `should_stop`, `stop_reason` |

---

## How CEOClaw extends OpenClaw

OpenClaw (see `integrations/openclaw_adapter.py`) is CEOClaw's internal
base framework.  It provides:

- **Canonical prompt templates** – structured system prompts for planner and
  evaluator that enforce JSON-only responses.
- **Response parsers** – JSON extraction with regex fallback and domain
  validation.
- **Domain priority heuristics** – rule-based fallback when the model is
  unavailable.
- **Progress computation** – `compute_progress(mrr, goal_mrr)` used by both
  the EvaluatorNode and StopCheckNode.

CEOClaw extends these foundations with:

- **LangGraph graph** (`core/agent_loop.py`) – the compiled StateGraph with
  retry-safe node functions and conditional routing.
- **FLock model adapter** (`integrations/flock_client.py`) – a
  `BaseChatModel` subclass that wraps the FLock HTTP API with timeout,
  retry, and deterministic mock/fallback mode.
- **SQLite persistence** – all node executions, graph runs, and checkpoints
  are persisted alongside existing business tables.

---

## Setup

```bash
# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. (Optional) copy and edit environment config
cp .env.example .env
```

Environment variables (all optional):

| Variable | Default | Description |
|----------|---------|-------------|
| `FLOCK_ENDPOINT` | _(empty — use mock mode if unset)_ | Hosted FLock / OpenClaw VPS URL |
| `FLOCK_API_KEY` | _(empty)_ | API key (never logged) |
| `FLOCK_MODEL` | `flock-default` | Model name sent in request payload |
| `FLOCK_AUTH_STRATEGY` | `both` | Header strategy: `both` \| `bearer` \| `litellm` |
| `FLOCK_MOCK_MODE` | `false` | Use deterministic mock responses (no HTTP) |
| `FLOCK_TIMEOUT` | `30` | HTTP timeout in seconds |
| `FLOCK_MAX_RETRIES` | `3` | Retries before fallback to mock |
| `CEOCLAW_DATABASE_PATH` | `data/ceoclaw.db` | SQLite file path |
| `CEOCLAW_GOAL_MRR` | `100.0` | Default MRR target |
| `CEOCLAW_LOG_LEVEL` | `INFO` | Log level |

### Auth strategy guide

`FLOCK_AUTH_STRATEGY=both` (default) sends **both** headers simultaneously, which works with
all OpenAI-compatible wrappers:

```
Authorization: Bearer <key>        ← OpenAI-style
x-litellm-api-key: <key>           ← LiteLLM / OpenClaw VPS style
```

Set `bearer` or `litellm` only if your VPS rejects unknown headers.

### How to tell real responses vs fallback

Real responses contain your model's text. Fallback responses (when all retries fail) are prefixed with `[FALLBACK]` in the content, and the log shows:
```
WARNING [FLock] FALLBACK activated after N retries — last error: ...
```

### Verify your endpoint before running

```bash
# Test with both auth headers (matches FLOCK_AUTH_STRATEGY=both)
curl -sf \
  -H "Authorization: Bearer $FLOCK_API_KEY" \
  -H "x-litellm-api-key: $FLOCK_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"$FLOCK_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"ping\"}]}" \
  "$FLOCK_ENDPOINT" | python3 -m json.tool

# Expected: JSON with a "choices" array.
# 401 → check FLOCK_API_KEY and FLOCK_AUTH_STRATEGY
# 404 / model_not_found → check FLOCK_MODEL
# connection refused / timeout → check FLOCK_ENDPOINT
```

---

## Quick demo (3 commands)

```bash
# 1. Full demo run — mock mode, no API key needed
python main.py demo --cycles 8 --mock-model

# 2. Explore results via REST API
uvicorn api.server:app --port 8000 &
curl http://localhost:8000/summary/latest | python3 -m json.tool

# 3. Export judge-readable Markdown report
python main.py export
```

See [`docs/demo_flow.md`](docs/demo_flow.md) for the full walkthrough and expected output.

---

## Docker / compose

```bash
# Build and start the REST API (mock mode by default)
docker compose up --build

# With a live FLock endpoint
FLOCK_ENDPOINT=http://your-flock-host/v1/chat/completions \
FLOCK_API_KEY=your-key \
FLOCK_MOCK_MODE=false \
docker compose up --build

# Check health
curl http://localhost:8000/health

# One-shot judge summary
curl http://localhost:8000/summary/latest | python3 -m json.tool
```

SQLite data persists in the `ceoclaw_sqlite` named volume across restarts.

---

## Run commands

```bash
# Run subcommand (verbose, per-cycle streaming output)
python main.py run --cycles 5 --mock-model --goal-mrr 100

# Demo subcommand (quiet run + clean cycle table + auto-export + API links)
python main.py demo --cycles 8 --mock-model

# Export subcommand (generate Markdown for most recent run)
python main.py export

# Export specific run by ID
python main.py export --run-id <uuid>

# Continuous until goal or 20 cycles
python main.py run --continuous --goal-mrr 100 --mock-model

# With a live FLock endpoint
python main.py run --cycles 3 --goal-mrr 100

# Start the REST API
uvicorn api.server:app --reload --port 8000

# Run tests
pytest tests/ -v

# Smoke-check the API (seeds DB, starts server, hits all endpoints)
./scripts/run_local.sh smoke
```

---

## Example output – `demo` subcommand (8 cycles, mock)

```
==================================================================
  CEOClaw  –  Autonomous Founder Agent  –  Demo Mode
==================================================================
  goal=$100 MRR | cycles=8 | mock=True
------------------------------------------------------------------
  #  Domain       Action                         MRR    Score  Trend  Flags
  ────────────────────────────────────────────────────────────────────────
  1  product      build_landing_page           $  0.00   0.000   flat
  2  marketing    run_seo_analysis             $  0.00   0.000   flat
  3  sales        create_outreach_campaign     $  0.00   0.000   flat  ⏸ stagnant
  6  ops          run_seo_analysis             $ 20.00   0.156     up
  8  ops          record_baseline_metrics      $ 50.00   0.388     up
  ────────────────────────────────────────────────────────────────────────

  Run ID      : a3dbbf72-8887-4043-ba61-520931b87843
  Cycles      : 8
  MRR         : $50.00  (goal $100.00)
  Weighted    : 0.388 / 1.000
  Progress    : 50.0%
  Stop reason : max_cycles_reached(8)
  Errors      : 0

  Exporting run summary…
  Report  : data/exports/a3dbbf72_summary.md
```

---

## Persistence tables overview

| Table | Purpose |
|-------|---------|
| `ideas` | Raw startup ideas evaluated by the agent |
| `products` | Products built (landing page path, status) |
| `marketing_experiments` | SEO and channel experiments with impression/click data |
| `outreach_attempts` | Outreach messages per target with status |
| `metrics` | Business metric snapshots (MRR, traffic, signups) |
| `loop_runs` | Legacy loop-run records (backward compat) |
| `memory_entries` | Agent memory store (observations, decisions) |
| `graph_runs` | One row per LangGraph run (run_id, goal, status, stop_reason) |
| `graph_checkpoints` | State snapshots saved after each EvaluatorNode execution |
| `node_executions` | Per-node timing and I/O summaries for every cycle |
| `cycle_scores` | Weighted KPI score, trend, stagnation count — one row per cycle |
| `artifacts` | Every file/report produced by executor nodes with content summary |

---

## Architecture decision record

- **MemorySaver** is used for LangGraph in-process checkpointing; state
  snapshots are also written to `graph_checkpoints` for external inspection.
- **FLock fallback** – if the HTTP endpoint is unreachable, `FlockChatModel`
  automatically switches to deterministic mock responses tagged `[FALLBACK]`.
- **No external packages** beyond `langgraph`, `langchain-core`, `fastapi`,
  `uvicorn`, `httpx`, and `pydantic`.  All persistence uses stdlib `sqlite3`.
