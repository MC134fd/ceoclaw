# CEOClaw — FAQ for Judges

### Q: Does this actually use the FLock/OpenClaw API?

Yes. `integrations/flock_client.py` wraps the FLock HTTP endpoint as a LangChain `BaseChatModel`. When `FLOCK_ENDPOINT` and `FLOCK_API_KEY` are set, every `PlannerNode` and `EvaluatorNode` call sends a real HTTP request to the FLock endpoint. Run with `--mock-model` (or `FLOCK_MOCK_MODE=true`) for a fully deterministic demo that requires no credentials.

### Q: What is `integrations/openclaw_adapter.py` and why is it marked DEPRECATED?

That file captures the original OpenClaw prompt interface we started with — same JSON schema, same domain heuristics, same `compute_progress()` formula. We preserved it for reference and transparency. CEOClaw's production runtime uses `core/prompts.py` (Pydantic-validated, stagnation-aware) and `integrations/flock_client.py` (retry, fallback, metadata) instead. You can import `OpenClawAdapter` and see exactly what the starting point was; the diff versus `core/prompts.py` shows every extension we made.

### Q: Is the MRR real?

No — MRR is simulated. The `analytics_tool` reads from a SQLite `metrics` table seeded by `ops_executor_node`. In production, you would wire Stripe webhooks to write real MRR into that table; the rest of the agent loop is production-ready. The simulation is intentional and documented — this is a hackathon demo.

### Q: Does outreach actually send messages?

No — `outreach_tool` generates and persists outreach records to the `outreach_attempts` table with `status='pending'`. In production, you would wire SendGrid / LinkedIn / Twitter API to send them. The records are fully formed messages with personalized content.

### Q: How is mock mode different from fallback mode?

| | Mock mode | Fallback mode |
|-|-----------|---------------|
| Activation | `--mock-model` flag / `FLOCK_MOCK_MODE=true` | Live mode + all retries fail |
| Indication | `Mode: mock (deterministic)` in CLI | `[FALLBACK]` prefix in response content + WARNING log |
| `model_mode` field | `"mock"` | `"fallback"` |
| `fallback_count` | 0 | +1 per call that fell back |
| Intended use | Demo, testing | Production self-healing |

### Q: Can I run this with my own FLock key right now?

Yes:
```bash
cp .env.example .env
# Edit .env: set FLOCK_ENDPOINT and FLOCK_API_KEY
python main.py demo --cycles 4
```

The agent will make real FLock API calls, track token usage, and fall back automatically if the endpoint is unreachable.

### Q: What happens if the FLock endpoint is down mid-run?

`FlockChatModel._generate()` retries up to `max_retries` times with exponential backoff. If all retries fail, it automatically switches to a deterministic fallback response tagged `[FALLBACK]`. The run continues uninterrupted, `fallback_count` increments, and the `model_mode` is recorded as `"fallback"` in the DB.

### Q: What is the weighted KPI score?

```
weighted_score = (
  min(traffic / 1000, 1.0) × 0.10   +   # 10% weight
  min(signups / 100,  1.0) × 0.20   +   # 20% weight
  min(revenue / goal, 1.0) × 0.25   +   # 25% weight
  min(mrr     / goal, 1.0) × 0.45       # 45% weight — MRR is dominant
)
```

Score 0.0 = no progress, 1.0 = all KPI goals fully met. This score drives trend detection, stagnation flags, and the confidence note in the export.

### Q: What does the circuit breaker do?

If any executor node (product/marketing/sales/ops) fails 3 consecutive times, `RouterNode` redirects that cycle to `OpsExecutorNode` for a recovery run — regardless of what the planner chose. On the next successful execution, failure counters reset. This prevents the agent from getting stuck in a crash loop.

### Q: Are there any external dependencies beyond Python packages?

No. SQLite is bundled with Python. All Python packages are in `requirements.txt` / `pyproject.toml`. The only optional external dependency is the FLock API endpoint (which you can skip with `--mock-model`).

### Q: How does stagnation detection work?

`EvaluatorNode` compares `current_mrr` to `last_mrr` each cycle. If `current_mrr <= last_mrr`, `stagnant_cycles` increments; otherwise it resets to 0. After 3 stagnant cycles:
1. Planner prompt includes a `⚠ STAGNATION ALERT` instructing domain rotation
2. `PlannerNode._stagnation_domain()` applies a deterministic override as safety net
3. CLI displays `⏸ stagnant` flag in the cycle table

### Q: What is the test strategy?

132 tests across 7 files:
- **Unit**: individual node functions, prompt builders, KPI computation
- **Integration**: full `run_graph()` with isolated tmp_path DB, API endpoint responses
- **Regression**: 20 edge-case scenarios (zero MRR, wrap-around targets, WAL mode, stale imports)
- **Fix verification**: 26 tests for 5 specific reliability improvements

All tests use `tmp_path` for DB isolation; no test touches the production DB.
