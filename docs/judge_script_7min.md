# CEOClaw — 7-Minute Judge Demo Script

## Setup (before judges arrive)

```bash
cd ceoclaw/
pip install -r requirements.txt   # already done if env is prepared
```

Open two terminal windows:
- **Terminal A**: for CLI commands
- **Terminal B**: for API + curl

---

## Minute 0:00–0:45 — The Pitch + Graph Overview

**Say:** "CEOClaw is an autonomous founder agent that uses the FLock API to run a self-directed startup loop — plan, execute, evaluate, repeat — targeting $100 MRR with no human input."

Point to the ASCII graph in the README or architecture.md:

```
START → PlannerNode → RouterNode → [Product | Marketing | Sales | Ops] Executor
     → EvaluatorNode → StopCheckNode → (END or loop)
```

**Say:** "The planner uses the FLock model to decide which domain to focus on each cycle. The router enforces a circuit breaker — if any executor fails 3 times in a row, we force an ops recovery cycle. The evaluator scores KPIs with a weighted formula, detects stagnation, and writes a checkpoint to SQLite."

---

## Minute 0:45–2:00 — Live Demo Run

**Terminal A:**
```bash
python main.py demo --cycles 8 --mock-model
```

While it runs, narrate:
- "8 autonomous cycles running — no API key needed in mock mode"
- Point at the cycle table as it prints: domain, action, MRR, weighted score, trend
- When ⏸ stagnant flag appears: "Here — the agent detected MRR stagnation. Watch it rotate domains."
- When trend shows `up`: "And here — MRR grew. The weighted score jumped."

After completion, point at:
- **Run ID** — unique per run, links everything
- **Mode: mock** — transparent, never confused for live
- **Errors: 0** — clean run
- **Report path** — auto-exported

---

## Minute 2:00–3:00 — Exported Markdown Report

```bash
# Either use the auto-exported path or run:
python main.py export
cat data/exports/*_summary.md
```

Point at sections:
1. **KPI Timeline table** — every cycle: domain, action, MRR, traffic, signups, weighted score, trend
2. **Artifacts table** — landing_page, seo_report, analytics_snapshot, outreach_batch, metrics_snapshot — concrete outputs per cycle
3. **Risk Events** — stagnation detected and flagged automatically
4. **Node Execution Stats** — timing per node; planner and evaluator are slowest (FLock calls)
5. **Confidence Note** — automated assessment of run quality

**Say:** "Every run produces this report automatically. It's designed for judges, investors, and post-mortems."

---

## Minute 3:00–4:30 — REST API

**Terminal B:**
```bash
uvicorn api.server:app --port 8000 &
sleep 1

# Health check
curl http://localhost:8000/health

# One-shot judge summary
curl http://localhost:8000/summary/latest | python3 -m json.tool
```

Point out in the JSON:
- `"status": "ok"` — API never returns 500
- `"model_mode": "mock"` — transparent about run mode
- `"final_mrr"`, `"final_weighted_score"` — quick scorecard
- `"kpi_trend"` array — full per-cycle history
- `"recent_artifacts"` — what the agent built

```bash
# Per-cycle timeline for the run
RUN_ID=$(curl -s http://localhost:8000/runs/recent | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['run_id'])")
curl "http://localhost:8000/runs/$RUN_ID/timeline" | python3 -m json.tool

# Artifact history
curl http://localhost:8000/artifacts/recent | python3 -m json.tool
```

---

## Minute 4:30–5:30 — Architecture Walk

**Say:** "Let me show you the actual code path."

Open `integrations/flock_client.py`:
- "This is our FLock adapter — a LangChain BaseChatModel that wraps the FLock HTTP endpoint with retry, timeout, and automatic fallback."
- "Every response carries metadata: model_mode, tokens estimated, whether we fell back."

Open `core/prompts.py`:
- "Prompt templates include current MRR progress %, weighted score, and a stagnation alert when growth has stalled."
- "All model output is Pydantic-validated with safe fallback parsers — bad JSON from the model never crashes the graph."

Open `core/agent_loop.py` lines 63–98:
- "RouterNode — this is the circuit breaker. Three consecutive failures on any executor and we redirect to ops recovery."

---

## Minute 5:30–6:15 — Test Suite

**Terminal A:**
```bash
python3 -m pytest tests/ -q
```

While running:
- "132 tests across 7 files — unit, integration, and regression."
- "We test the graph compilation, all 4 executor nodes, all 8 API endpoints, all 4 tools, and 5 specific reliability scenarios."

Expected output:
```
132 passed, 1 warning in ~5s
```

---

## Minute 6:15–7:00 — Live Mode + Closing

**Say:** "In live mode, you set `FLOCK_ENDPOINT` and `FLOCK_API_KEY` in .env and drop the `--mock-model` flag. The FlockChatModel hits the real FLock endpoint, tracks actual token usage, and automatically falls back with a `[FALLBACK]` tag if the endpoint is unreachable."

```bash
# Show .env.example
cat .env.example
```

**Closing:** "CEOClaw turns the FLock model API into a complete autonomous founder stack — typed state machine, 4 domain agents, 4 production tools, SQLite audit trail, REST API, and 132 tests. One command to run, one endpoint to inspect results."

---

## Contingency

**If API server fails to start:**
```bash
# Check if port 8000 is in use
lsof -i :8000
# Kill conflicting process if needed, then restart
uvicorn api.server:app --port 8001 &
curl http://localhost:8001/health
```

**If demo crashes:**
```bash
# Reset DB and rerun
rm data/ceoclaw.db
python main.py demo --cycles 8 --mock-model
```

**If tests fail:**
```bash
# Run just the core tests
python3 -m pytest tests/test_agent_loop.py tests/test_api.py -v
```
