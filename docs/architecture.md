# CEOClaw Architecture Deep-Dive

## Overview

CEOClaw is a typed LangGraph `StateGraph` that runs an autonomous founder loop. Every node is a pure Python function with a typed input/output contract; state flows through the graph as a single `CEOClawState` TypedDict. All I/O is persisted to SQLite; the graph is externally observable via REST API.

## Graph Topology

```
START
  │
  ▼
PlannerNode ────────────────────────────────────────────────────────┐
  │  FLock model (or mock)                                          │
  │  core/prompts.build_planner_prompt()                            │
  │  safe_parse_planner() → PlannerOutput (Pydantic)               │
  │  Stagnation override: forces domain rotation if MRR is flat    │
  ▼                                                                 │
RouterNode                                                           │
  │  Validates domain; circuit breaker check                        │
  │  If executor_key failures ≥ 3 → override domain to "ops"       │
  ▼                                                                 │
  ┌─────────────────────────────────────────────────────────┐       │
  │   Conditional dispatch on selected_domain               │       │
  ├─► ProductExecutorNode (website_builder, seo_tool)       │       │
  ├─► MarketingExecutorNode (seo_tool, analytics_tool)      │       │
  ├─► SalesExecutorNode (outreach_tool)                     │       │
  └─► OpsExecutorNode (analytics_tool)                      │       │
  └──────────────────────────┬──────────────────────────────┘       │
                             ▼                                       │
                     EvaluatorNode                                   │
                       │  FLock model (or mock)                      │
                       │  Weighted KPI: MRR(45%) + Rev(25%)         │
                       │  + Signups(20%) + Traffic(10%)             │
                       │  Trend detection, stagnation tracking       │
                       │  persist_cycle_score(), save_checkpoint()   │
                       ▼                                             │
                   StopCheckNode                                     │
                     │                                               │
              ┌──────┴──────┐                                        │
             END         continue ───────────────────────────────────┘
        (goal | max      (loop)
         cycles | errors)
```

## State: CEOClawState

`agents/__init__.py` defines the single TypedDict that flows through every node:

```python
class CEOClawState(TypedDict, total=False):
    # Identity
    run_id: str                         # UUID for this graph run
    cycle_count: int                    # Incremented by PlannerNode each cycle
    goal_mrr: float                     # MRR target (default $100)

    # Business context
    latest_metrics: dict[str, Any]      # {mrr, signups, website_traffic, revenue}
    active_product: Optional[dict]      # Product built so far

    # Planner outputs
    selected_domain: Literal["product","marketing","sales","ops"]
    selected_action: str
    strategy: dict[str, Any]

    # Executor outputs
    executor_result: dict[str, Any]     # ExecutorOutput.model_dump()

    # KPI scoring
    evaluation: dict[str, Any]         # EvaluatorOutput.model_dump()
    weighted_score: float               # 0.0–1.0 composite KPI
    trend_direction: str                # "up" | "down" | "flat"
    stagnant_cycles: int                # consecutive cycles with no MRR growth
    last_mrr: float                     # MRR from previous cycle

    # Circuit breaker
    consecutive_failures: dict[str, int]  # {executor_key: count}
    circuit_breaker_active: bool

    # Budget transparency
    tokens_used: int                    # heuristic token estimate (mock=0)
    external_calls: int                 # live HTTP calls to FLock
    model_mode: str                     # "live" | "mock" | "fallback" | "unknown"
    fallback_count: int                 # fallbacks this run

    # Error accumulation (append reducer)
    errors: Annotated[list[dict], add]

    # Stop signal
    should_stop: bool
    stop_reason: Optional[str]
```

## FLock Model Adapter

`integrations/flock_client.py` — `FlockChatModel(BaseChatModel)`:

```
invoke(messages)
  ├── mock_mode=True → _mock_generate()
  │     classify prompt (planner|evaluator)
  │     return deterministic JSON + metadata(model_mode="mock", tokens=0)
  │
  └── mock_mode=False → _generate() with retry loop
        for attempt in range(max_retries):
            try → _http_generate()
                  httpx.post(endpoint, json=payload)
                  return AIMessage(response_metadata={
                      model_mode: "live", tokens_estimated: N, external_calls_delta: 1
                  })
            except → sleep(0.5 * attempt)
        # All retries exhausted:
        → _mock_generate(prefix="[FALLBACK]", model_mode="fallback",
                         external_calls_delta=max_retries)
```

Budget metadata flows via `AIMessage.response_metadata` → extracted in PlannerNode / EvaluatorNode → accumulated into state as `tokens_used`, `external_calls`, `fallback_count`.

## KPI Scoring (core/prompts.py)

```
weighted_score = (
    min(traffic / 1000, 1.0) * 0.10    # Traffic score
  + min(signups / 100, 1.0)  * 0.20    # Signup score
  + min(revenue / goal, 1.0) * 0.25    # Revenue score
  + min(mrr / goal, 1.0)     * 0.45    # MRR score (dominant)
)
```

Trend: `delta = weighted_score - prev_score` → `up` (>0.005) / `down` (<-0.005) / `flat`.

## Stagnation Detection & Override

Tracked in `EvaluatorNode`:
- `stagnant_cycles` increments when `current_mrr <= last_mrr`
- Resets to 0 on any MRR growth

When `stagnant_cycles >= 3`:
1. Planner prompt includes `⚠ STAGNATION ALERT` with instruction to switch domain
2. `PlannerNode._stagnation_domain()` overrides the model's choice to a different domain
3. `cycle_scores.stagnant_cycles` records the count for display (⏸ flag in CLI table)

## Circuit Breaker

In `RouterNode`:
- Each executor tracks failures in `consecutive_failures[executor_key]`
- After 3 consecutive failures: domain overridden to `ops`, `circuit_breaker_active=True`
- `OpsExecutorNode` resets the failure counter for the tripped executor
- All failure counters reset to 0 on any success

## Persistence Layer

All nodes call `log_node_start()` / `log_node_finish()` for timing and I/O audit.

Key write paths:
- `EvaluatorNode` → `persist_cycle_score()` + `save_checkpoint()`
- All executors → `persist_artifact()` for each output
- `run_graph()` → `start_graph_run()` + `finish_graph_run()` (with budget fields)

## Safe Parsing

`core/prompts.safe_parse_planner()` and `safe_parse_evaluator()`:
1. Try `json.loads(content)` directly
2. Regex fallback: search for `{...}` block
3. Pydantic `model_validate()` with error codes (`OK`, `ERR_JSON_DECODE`, `ERR_VALIDATION`, `ERR_REGEX_FALLBACK`, `ERR_TOTAL_FAILURE`)
4. Construct safe default output if all else fails — **graph never crashes on bad model output**

## REST API (api/server.py)

FastAPI app with `StateManager` (read-only SQLite layer):

```
GET /health                → {"status": "ok", "app": "CEOClaw"}
GET /status                → config + latest run summary
GET /metrics/latest        → most recent metrics row
GET /runs/recent           → list of recent graph_runs rows
GET /runs/{run_id}         → single graph_runs row
GET /runs/{run_id}/timeline → cycle_scores for that run
GET /artifacts/recent      → artifacts rows (newest first)
GET /kpi/trend             → cycle_scores oldest→newest (charting)
GET /summary/latest        → one-shot: run + trend + artifacts + budget (never 500)
```

`/summary/latest` is designed for judge inspection — always returns `status: "ok" | "no_runs" | "error"` with structured `diagnostics` on failure.

---

## Website Builder & Chat Generation

### Provider routing

`services/provider_router.py` — `call_llm(messages) -> LLMResult`:

```
Flock (live endpoint)  →  OpenAI (chat completions | responses API)  →  deterministic mock
```

OpenAI routing:
- `OPENAI_API_MODE=auto` (default): chat completions for all models except `gpt-5*`; responses API for `gpt-5*`
- `OPENAI_API_MODE=responses`: always use `/v1/responses`
- `OPENAI_API_MODE=chat`: always use `/v1/chat/completions`

### Code generation service

`services/code_generation_service.py`:

```
generate(slug, user_message, history, existing_files, ...)
  │
  ├─ build_messages()      ← injects system prompt + operation hint + file context
  │    system prompt:       product-specific quality mandate, integration placeholders,
  │                         iteration preservation rules, responsive contract
  │    user turn:           [EDIT MODE] or [NEW BUILD] prefix + existing file content
  │
  ├─ call_llm(messages)    ← provider router
  │
  ├─ parse_response()      ← robust JSON extraction (direct → markdown → brace → raw HTML)
  ├─ extract_changes()     ← FileChange list with path normalisation
  │
  └─ _template_generate()  ← deterministic fallback when LLM unavailable
        uses _render_html() with category-aware palette + emoji feature icons
        uses _render_app_page() with integration placeholders (auth, data, actions)
```

### Workspace file safety

`services/workspace_scope.py` — `WorkspaceScope(slug)`:

- All file I/O for a project must go through `WorkspaceScope`
- Extension allowlist: `.html`, `.css`, `.js`, `.json`, `.md`, `.txt`, `.svg`
- Subdirectory allowlist: root, `pages/`, `assets/`
- Realpath traversal check on every operation
- Atomic writes: `.tmp` → `rename`
- Full audit log via `WorkspaceScope.operations` list

```
scope = WorkspaceScope("my-app")
safe_path = scope.resolve("pages/about.html")   # None if blocked
scope.write("index.html", html_content)         # atomic, audited
scope.list_files(".html")                       # → ["index.html", "app.html"]
```

---

## Autonomous Agent Framework (Scaffolding)

The following modules define the contracts for future autonomous agents.
No destructive automation is active; these are typed extension points.

### Agent lifecycle

```
OBSERVE → PLAN → VALIDATE → APPLY → VERIFY
   │         │        │         │       │
   │         │        │         │       └─ check result matches intent
   │         │        │         └─ execute capability within WorkspaceScope
   │         │        └─ pre-flight safety check (path, size, extension)
   │         └─ build AgentOperationPlan with ordered OperationSteps
   └─ read current workspace files, session state, user intent
```

### Capability registry

`services/agent_capabilities.py` — `CapabilityRegistry`:

```python
registry = get_registry()
registry.list_enabled()                   # all active capabilities
registry.list_by_scope("workspace")       # file-system capabilities
registry.list_requiring_confirmation()    # must prompt user before exec
registry.to_prompt_block()               # injects into agent planning prompt
```

Defined capabilities (enabled):
- **workspace**: `read_file`, `write_file`, `list_files`, `delete_file`, `diff_files`,
  `generate_page`, `edit_section`, `apply_design_system`, `validate_html`, `run_lighthouse_audit`
- **session**: `save_version`, `restore_version`, `list_versions`

Planned (disabled until implemented):
- `push_to_github`, `connect_stripe`, `send_marketing_email`

### Operation plan

`services/agent_operation_plan.py` — `AgentOperationPlan`:

Each plan is an ordered list of `OperationStep` objects:

```python
plan = AgentOperationPlan.build(session_id, slug, objective="Add pricing section")
plan.add_step(OperationStep(capability="save_version", ...))   # pre-edit snapshot
plan.add_step(OperationStep(capability="edit_section", ...))   # apply change
plan.add_step(OperationStep(capability="validate_html", continue_on_failure=True))

plan.to_dict()    # JSON for DB persistence
plan.progress()   # (done, total)
plan.summary()    # one-line log string
```

Plan states: `DRAFT → RUNNING → DONE | FAILED | ABORTED`
Step states: `PENDING → VALIDATING → APPLYING → DONE | FAILED | SKIPPED`

Factory helpers: `plan_add_page()`, `plan_edit_section()`, `plan_restore()`

### Workspace scope safety

All agent file operations are routed through `WorkspaceScope`:
- Every path validated before read/write (extension + subdir allowlist + realpath check)
- Operations logged in `scope.operations` (kind, path, permitted, bytes_written)
- Agents cannot access files outside `data/websites/<slug>/`
- Agents cannot write files over 2 MB

### Capability boundaries

| Scope         | Can read?  | Can write?  | User confirmation? |
|---------------|-----------|-------------|-------------------|
| `workspace`   | Yes       | Yes (audited) | Only for destructive |
| `session`     | Yes       | Yes         | Only for restore   |
| `global_read` | Yes       | No          | Never              |
| External APIs | No (future) | No (future) | Always             |

---

## Integrations Roadmap

| Integration | Status | Notes |
|---|---|---|
| OpenAI Chat Completions | ✅ Live | `/v1/chat/completions` |
| OpenAI Responses API | ✅ Live | `/v1/responses`, auto-routed for `gpt-5*` |
| Flock / OpenClaw | ✅ Live | LiteLLM proxy, bearer or x-litellm-api-key auth |
| Brave Search | ✅ Live | `tools/research_tool.py` |
| Google CSE | ✅ Live | `tools/research_tool.py` |
| Supabase memory | ✅ Live | `core/memory_supabase.py` |
| SQLite memory | ✅ Live | `core/memory_sqlite.py` |
| X (Twitter) | 🔧 Scaffolded | `tools/social_publishers/x_publisher.py` |
| Instagram | 🔧 Scaffolded | `tools/social_publishers/instagram_publisher.py` |
| SendGrid | 🔧 Scaffolded | `config/settings.py` |
| Resend | 🔧 Scaffolded | `config/settings.py` |
| Stripe payments | 📋 Planned | `connect_stripe` capability (disabled) |
| GitHub push | 📋 Planned | `push_to_github` capability (disabled) |
| Supabase realtime | 📋 Planned | Live preview sync |
