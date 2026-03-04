# CEOClaw Demo Flow — Judge Guide

> **CEOClaw** is an autonomous founder agent that iterates toward **$100 MRR**
> using a strict LangGraph topology: Planner → Router → Executor → Evaluator → StopCheck.
> Every cycle is persisted to SQLite and exposed via a REST API.

---

## 3-Command Demo Script

```bash
# 1. One-command full demo run (mock mode — no API key needed)
python main.py demo --cycles 8 --mock-model

# 2. Explore results via the REST API
uvicorn api.server:app --port 8000 &
curl http://localhost:8000/summary/latest | python3 -m json.tool

# 3. Export a judge-readable Markdown report
python main.py export
```

That's it. No environment variables, no external services.

---

## What Each Command Does

### `python main.py demo --cycles 8 --mock-model`

Runs 8 autonomous founder-agent cycles, then prints:

1. **Cycle-by-cycle KPI table** — domain chosen, action taken, MRR, weighted score, trend, stagnation flags
2. **Final KPI summary** — run ID, MRR progress, weighted score, stop reason
3. **Auto-exported Markdown report** — written to `data/exports/<run_id[:8]>_summary.md`
4. **API quick-links** — endpoint URLs if the API server is already running

Expected output snippet:

```
================================================================
  CEOClaw  –  Autonomous Founder Agent  –  Demo Mode
================================================================
  goal=$100 MRR | cycles=8 | mock=True
----------------------------------------------------------------
  #  Domain       Action                         MRR    Score  Trend  Flags
  ────────────────────────────────────────────────────────────────────────
  1  product      build_landing_page           $  0.00   0.000   flat
  2  marketing    run_seo_analysis             $  0.00   0.000   flat
  3  sales        create_outreach_campaign     $  0.00   0.000   flat  ⏸ stagnant
  4  product      record_baseline_metrics      $  0.00   0.000   flat  ⏸ stagnant
  5  sales        build_landing_page           $  0.00   0.000   flat  ⏸ stagnant
  6  ops          run_seo_analysis             $ 20.00   0.156     up
  7  sales        create_outreach_campaign     $ 20.00   0.156   flat
  8  ops          record_baseline_metrics      $ 50.00   0.388     up
  ────────────────────────────────────────────────────────────────────────

  Run ID      : a3dbbf72-8887-4043-ba61-520931b87843
  Cycles      : 8
  MRR         : $50.00  (goal $100.00)
  Traffic     : 140
  Signups     : 12
  Weighted    : 0.388 / 1.000
  Progress    : 50.0%
  Stop reason : max_cycles_reached(8)
  Errors      : 0

  Exporting run summary…
  Report  : data/exports/a3dbbf72_summary.md
```

### `curl http://localhost:8000/summary/latest`

Returns a single JSON object with everything a judge needs to see:

```json
{
  "status": "ok",
  "run_id": "a3dbbf72-...",
  "goal_mrr": 100.0,
  "cycles_run": 8,
  "final_mrr": 50.0,
  "final_weighted_score": 0.388,
  "stop_reason": "max_cycles_reached(8)",
  "artifact_count": 9,
  "kpi_trend": [ ... 8 cycle rows ... ]
}
```

Other useful endpoints:

| Endpoint | What it shows |
|----------|--------------|
| `GET /health` | Liveness probe |
| `GET /status` | Config + most recent run |
| `GET /runs/recent` | All runs, newest first |
| `GET /runs/{run_id}/timeline` | Per-cycle KPI for a specific run |
| `GET /kpi/trend` | KPI trend (oldest→newest) for charting |
| `GET /artifacts/recent` | Artifacts created across all runs |
| `GET /summary/latest` | One-shot judge summary |

### `python main.py export`

Reads the most recent completed run from SQLite and writes a Markdown report.
Includes: run metadata, KPI timeline, artifacts, risk events, node stats, confidence note.

---

## 2-Minute Walkthrough for Judges

| Time | What to show |
|------|-------------|
| 0:00 | Run `python main.py demo --cycles 8 --mock-model` — explain the topology on the right panel |
| 0:30 | Watch cycle table print — point out stagnation flags (⏸) and trend arrows |
| 0:50 | Demo the domain rotation: stagnation forces the planner away from the stuck domain |
| 1:10 | Open `data/exports/*_summary.md` in a browser/editor — highlight KPI timeline and confidence note |
| 1:30 | Show `curl http://localhost:8000/summary/latest` in a second terminal |
| 1:50 | Mention: 62 passing tests, SQLite audit trail, circuit breaker, mock + live model modes |

---

## Fallback Behavior

### Mock mode (no FLock API)
`--mock-model` flag enables fully deterministic responses — no network calls.
The mock planner cycles through all four domains in order; the mock evaluator
computes real weighted KPI scores from actual metrics.

### Model failure during live mode
If the FLock HTTP endpoint is unreachable, `FlockChatModel` automatically
falls back to deterministic mock responses tagged `[FALLBACK]`.
The run continues without interruption — no exception is raised.

### Circuit breaker
If any executor fails 3 consecutive times, the RouterNode redirects that cycle
to `ops_executor` for a recovery run. All failure counters reset on success.

### Export failure
If `export_run_summary` fails for any reason during `demo` mode,
a warning is printed but the CLI exit code remains 0 and the run result
display is unaffected. The run data is still in SQLite.

---

## Architecture at a Glance

```
START
 └─> PlannerNode       (FLock model / mock)
      └─> RouterNode   (domain validation + circuit breaker)
           ├─> ProductExecutorNode   (website_builder, seo_tool)
           ├─> MarketingExecutorNode (seo_tool, analytics_tool)
           ├─> SalesExecutorNode     (outreach_tool)
           └─> OpsExecutorNode       (analytics_tool, recovery)
                └─> EvaluatorNode    (weighted KPI, stagnation tracking)
                     └─> StopCheckNode
                          ├─> END           (goal reached | max cycles | error threshold)
                          └─> PlannerNode   (loop continues)
```

All state is typed (`CEOClawState TypedDict`), all node I/O is logged to SQLite,
and all outputs are Pydantic-validated with safe fallback parsers.
