# CEOClaw Demo Assets Guide

## What to Record for a Video Demo

### Terminal Setup
- Font size: 16pt or larger (readable in 1080p)
- Terminal width: 120 columns
- Dark theme recommended (contrast for recording)
- Two panes or two windows: CLI on left, API/curl on right

---

## Shot 1 — The Demo Run (60 seconds)

**Command:**
```bash
python main.py demo --cycles 8
```

**What to capture:**
- The header: `CEOClaw — Autonomous Founder Agent — Demo Mode`
- The cycle table printing line by line (let it scroll naturally)
- The ⏸ stagnant flag appearing (highlight with cursor)
- The trend arrow changing from `flat` → `up` when MRR grows
- Final summary: Run ID, MRR, Weighted score, Errors: 0
- Export path line: `Report: data/exports/...`

**Narration cue:** "Watch the agent autonomously rotate domains — product, marketing, sales, ops — and detect when growth stalls."

---

## Shot 2 — Exported Markdown Report (30 seconds)

**Command:**
```bash
cat data/exports/*_summary.md
```

Or open in a Markdown previewer (VS Code / Typora) for prettier display.

**What to capture:**
- KPI Timeline table (all 8 rows visible)
- Artifacts table — show the concrete deliverables: landing_page, seo_report, outreach_batch, metrics_snapshot
- Risk Events section (stagnation flagged)
- Confidence Note at the bottom

**Narration cue:** "Every run auto-exports this report. Artifacts show exactly what the agent produced each cycle."

---

## Shot 3 — REST API (45 seconds)

**Commands:**
```bash
# Terminal 2 (run this first, before starting recording)
uvicorn api.server:app --port 8000 &

# During recording:
curl http://localhost:8000/health
curl http://localhost:8000/summary/latest | python3 -m json.tool
```

**What to capture:**
- `/health` response: `{"status": "ok", "app": "CEOClaw"}`
- `/summary/latest` JSON — scroll slowly so judges can read:
  - `"status": "ok"` (never 500)
  - `"model_mode"` (transparent)
  - `"final_mrr"`, `"final_weighted_score"`
  - `"kpi_trend"` array (scroll through)
  - `"recent_artifacts"` list

**Narration cue:** "The `/summary/latest` endpoint is designed for judge inspection — always returns structured JSON, never 500."

---

## Shot 4 — Test Suite (20 seconds)

**Command:**
```bash
python3 -m pytest tests/ -q
```

**What to capture:**
- The progress bar or dots filling up
- Final line: `132 passed, 1 warning in X.XXs`

**Narration cue:** "132 tests across all layers — graph, agents, API, tools, and 5 reliability fix scenarios."

---

## Shot 5 — Code Architecture (60 seconds)

Show in IDE (VS Code preferred):

1. **`integrations/flock_client.py`** — `class FlockChatModel(BaseChatModel)` and the `_generate` method showing live/fallback branches
2. **`core/prompts.py`** — `PLANNER_SYSTEM_PROMPT` with the stagnation alert section
3. **`core/agent_loop.py`** — `build_graph()` function showing the 7-node topology, then `router_node` showing the circuit breaker logic
4. **`agents/__init__.py`** — `CEOClawState` TypedDict with the `errors: Annotated[list, add]` reducer

---

## Key Numbers to Memorize

| Metric | Value |
|--------|-------|
| Graph nodes | 7 |
| Domain executors | 4 |
| LangChain tools | 4 |
| SQLite tables | 11 |
| REST API endpoints | 8 |
| Tests | 132 |
| Test files | 7 |
| KPI weights | MRR 45%, Revenue 25%, Signups 20%, Traffic 10% |
| Circuit breaker threshold | 3 consecutive failures |
| Stagnation threshold | 3 cycles with no MRR growth |

---

## Ideal Video Flow (3 minutes max)

```
0:00–0:15  Title card: "CEOClaw — Autonomous Founder Agent"
0:15–1:00  Shot 1: Demo run (let it play, narrate live)
1:00–1:30  Shot 2: Exported report (scroll KPI Timeline + Artifacts)
1:30–2:00  Shot 3: REST API (health + summary/latest)
2:00–2:20  Shot 4: Tests (132 passed)
2:20–3:00  Shot 5: Code walk (flock_client → prompts → agent_loop)
```

---

## Screenshots to Include in Submission

1. **Full 8-cycle demo output** — terminal screenshot, full scroll
2. **`GET /summary/latest` JSON** — formatted with `| python3 -m json.tool`
3. **Exported Markdown report** — rendered in Markdown viewer (show KPI Timeline table)
4. **`pytest -v` output** — showing all 132 test names and PASSED
5. **Graph topology diagram** — from README or architecture.md
