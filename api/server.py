"""
CEOClaw FastAPI server  – v0.4 (demo-ready).

Endpoints (v0.2 – backward compatible):
    GET /health
    GET /status
    GET /metrics/latest
    GET /runs/recent

v0.3 endpoints:
    GET /runs/{run_id}
    GET /runs/{run_id}/timeline
    GET /artifacts/recent
    GET /kpi/trend

v0.4 endpoints:
    GET /summary/latest   — one-shot judge-friendly run summary
"""

import asyncio
import json
import logging
import re
import sys
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

logger = logging.getLogger(__name__)
_DEBUG_LOG_PATH = Path("/Users/marcuschien/code/MC134fd/ceoclaw/.cursor/debug-9d4649.log")


def _debug_log(run_id: str, hypothesis_id: str, location: str, message: str, data: dict[str, Any]) -> None:
    # #region agent log
    try:
        payload = {
            "sessionId": "9d4649",
            "runId": run_id,
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(__import__("time").time() * 1000),
        }
        _DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _DEBUG_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload) + "\n")
    except Exception:
        pass
    # #endregion

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from api.auth import ANONYMOUS_USER, get_current_user
import config.settings as _settings_mod  # runtime lookup avoids stale binding in tests
from config.settings import settings
from core import event_bus as _bus
from core.intent_parser import parse_intent
from core.state_manager import StateManager
from data.database import (
    append_chat_message,
    deduct_credits,
    delete_chat_session,
    get_chat_history,
    get_chat_session,
    get_chat_session_owned_by,
    get_credit_ledger,
    get_design_system,
    get_session_version,
    get_user_by_id,
    get_user_credits,
    get_user_subscription,
    init_db,
    list_chat_sessions,
    list_chat_sessions_for_user,
    list_session_versions,
    save_session_version,
    upsert_chat_session,
    upsert_design_system,
)
from integrations.flock_client import get_model
from tools.website_builder import website_builder_tool

# ---------------------------------------------------------------------------
# Credits constants
# ---------------------------------------------------------------------------

GENERATION_COST = 1  # credits per generation request


@asynccontextmanager
async def _lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title=settings.app_name,
    description="Autonomous founder agent REST API.",
    version="0.7.0",
    lifespan=_lifespan,
)

_sm = StateManager()


# ---------------------------------------------------------------------------
# v0.2 endpoints (backward compatible)
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok", "app": settings.app_name}


@app.get("/status")
def status() -> dict[str, Any]:
    """App configuration and the most recent graph run."""
    try:
        recent = _sm.get_recent_graph_runs(limit=1)
        latest_run = recent[0] if recent else None
    except Exception:
        latest_run = None
    return {
        "app_name": settings.app_name,
        "environment": settings.environment,
        "goal_mrr": settings.default_goal_mrr,
        "mock_mode": settings.flock_mock_mode,
        "flock_endpoint_configured": bool(settings.flock_endpoint),
        "flock_model": settings.flock_model,
        "flock_auth_strategy": settings.flock_auth_strategy,
        "latest_run": latest_run,
    }


@app.get("/metrics/latest")
def metrics_latest() -> dict[str, Any]:
    """Most recently recorded business metrics snapshot."""
    row = _sm.get_latest_metrics()
    if row is None:
        raise HTTPException(status_code=404, detail="No metrics recorded yet.")
    return row


@app.get("/runs/recent")
def runs_recent(limit: int = 10) -> list[dict[str, Any]]:
    """The *limit* most recent graph runs."""
    try:
        return _sm.get_recent_graph_runs(limit=min(limit, 100))
    except Exception as exc:
        logger.warning("GET /runs/recent failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# v0.3 endpoints
# ---------------------------------------------------------------------------

@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    """Full details for a specific graph run."""
    row = _sm.get_graph_run(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found.")
    return row


@app.get("/runs/{run_id}/timeline")
def run_timeline(run_id: str) -> list[dict[str, Any]]:
    """Cycle-by-cycle KPI and decision timeline for a specific run."""
    if _sm.get_graph_run(run_id) is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found.")
    try:
        return _sm.get_run_timeline(run_id)
    except Exception as exc:
        logger.warning("GET /runs/%s/timeline failed: %s", run_id, exc)
        return []


@app.get("/artifacts/recent")
def artifacts_recent(limit: int = 20) -> list[dict[str, Any]]:
    """The *limit* most recently created artifacts across all runs."""
    try:
        return _sm.get_recent_artifacts(limit=min(limit, 200))
    except Exception as exc:
        logger.warning("GET /artifacts/recent failed: %s", exc)
        return []


@app.get("/kpi/trend")
def kpi_trend(limit: int = 20) -> list[dict[str, Any]]:
    """KPI trend across the *limit* most recent cycles (oldest→newest)."""
    try:
        return _sm.get_kpi_trend(limit=min(limit, 100))
    except Exception as exc:
        logger.warning("GET /kpi/trend failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# v0.4 endpoint – judge-friendly one-shot summary
# ---------------------------------------------------------------------------

@app.get("/summary/latest")
def summary_latest() -> dict[str, Any]:
    """One-shot summary of the most recent run for demo and judging.

    Never returns 500 — returns a ``status`` field indicating data availability.
    """
    try:
        runs = _sm.get_recent_graph_runs(limit=1)
        if not runs:
            return {"status": "no_runs", "message": "No runs recorded yet."}

        run = runs[0]
        run_id: str = run["run_id"]

        # Scope KPI trend to this run only (not cross-run global trend)
        trend = _sm.get_run_timeline(run_id)
        run_artifacts = _sm.get_run_artifacts(run_id)

        final_weighted = trend[-1]["weighted_score"] if trend else 0.0
        final_mrr = trend[-1]["mrr"] if trend else 0.0

        return {
            "status": "ok",
            "run_id": run_id,
            "run_status": run["status"],
            "goal_mrr": run["goal_mrr"],
            "cycles_run": run["cycles_run"],
            "stop_reason": run["stop_reason"],
            "final_mrr": final_mrr,
            "final_weighted_score": final_weighted,
            "kpi_trend": trend,
            "artifact_count": len(run_artifacts),
            "recent_artifacts": run_artifacts[:5],
            # Budget / transparency fields (Fix 2 + Fix 4)
            "model_mode": run.get("model_mode", "unknown"),
            "fallback_count": run.get("fallback_count", 0),
            "tokens_used": run.get("tokens_used", 0),
            "external_calls": run.get("external_calls", 0),
        }
    except Exception as exc:
        logger.warning("GET /summary/latest failed: %s", exc)
        return {"status": "error", "message": str(exc), "diagnostics": type(exc).__name__}


# ---------------------------------------------------------------------------
# Chat / interactive run endpoints (v0.5)
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str = ""
    goal_mrr: float = 100.0
    cycles: int = 8
    mock_mode: bool = True
    autonomy_mode: str = "A_AUTONOMOUS"
    workflow_mode: str = "chronological"   # new default: chronological
    selected_idea: dict[str, Any] | None = None


class RunStartRequest(BaseModel):
    goal_mrr: float = 100.0
    cycles: int = 8
    mock_mode: bool = True
    autonomy_mode: str = "A_AUTONOMOUS"
    workflow_mode: str = "adaptive"


class IdeaGenerateRequest(BaseModel):
    message: str
    count: int = 4


class WebsiteChatRequest(BaseModel):
    session_id: str = "default"
    message: str
    mock_mode: bool = False   # False = use real LLM when keys are configured


class StyleSeed(BaseModel):
    archetype: str = ""
    palette: str = ""
    density: str = ""
    motion: str = ""


class BuilderChatRequest(BaseModel):
    session_id: str = "default"
    message: str
    mock_mode: bool = False
    style_seed: StyleSeed | None = None
    operation: dict[str, Any] | None = None


class ModelCheckRequest(BaseModel):
    mock_mode: bool = False


def _bg_run(
    run_id: str,
    goal_mrr: float,
    cycles: int,
    mock_mode: bool,
    autonomy_mode: str = "A_AUTONOMOUS",
    product_intent: dict[str, Any] | None = None,
    workflow_mode: str = "adaptive",
) -> None:
    """Run the graph in a background thread, emitting events to the bus."""
    try:
        from core.agent_loop import run_graph
        run_graph(
            cycles=cycles,
            goal_mrr=goal_mrr,
            mock_mode=mock_mode,
            max_cycles=cycles,
            quiet=True,
            run_id=run_id,
            autonomy_mode=autonomy_mode,
            product_intent=product_intent,
            workflow_mode=workflow_mode,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Background run %s failed: %s", run_id[:8], exc)
        # event_bus already receives run_error from run_graph's except block


@app.post("/chat")
def chat_start(request: ChatRequest) -> dict[str, Any]:
    """Start an autonomous founder run from a chat message.

    The message is parsed into a structured product intent that drives
    all downstream agents (product name, features, target user, endpoints).

    Returns immediately with run_id; stream events via GET /runs/{run_id}/events.
    """
    from core.intent_parser import parse_intent

    product_intent: dict[str, Any] | None = None
    if request.selected_idea:
        product_intent = dict(request.selected_idea)
        logger.info(
            "Using selected idea: product=%r type=%s",
            product_intent.get("product_name"),
            product_intent.get("product_type"),
        )
    elif request.message.strip():
        product_intent = parse_intent(request.message)
        logger.info(
            "Intent parsed: product=%r type=%s confidence=%.2f",
            product_intent.get("product_name"),
            product_intent.get("product_type"),
            product_intent.get("confidence", 0),
        )

    run_id = str(uuid.uuid4())
    t = threading.Thread(
        target=_bg_run,
        args=(
            run_id,
            request.goal_mrr,
            request.cycles,
            request.mock_mode,
            request.autonomy_mode,
            product_intent,
            request.workflow_mode,
        ),
        daemon=True,
    )
    t.start()

    product_name = (product_intent or {}).get("product_name", "your product")
    return {
        "run_id": run_id,
        "message": (
            f"Building {product_name} — run {run_id[:8]}. "
            f"Goal: ${request.goal_mrr:.0f} MRR in {request.cycles} cycles "
            f"({'mock' if request.mock_mode else 'live'} model, {request.workflow_mode} workflow)."
        ),
        "stream_url": f"/runs/{run_id}/events",
        "autonomy_mode": request.autonomy_mode,
        "workflow_mode": request.workflow_mode,
        "product_intent": product_intent,
    }


@app.post("/ideas/generate")
def generate_ideas_endpoint(request: IdeaGenerateRequest) -> dict[str, Any]:
    """Generate 4 startup ideas and return them for user selection."""
    from core.idea_generator import generate_ideas

    if not request.message.strip():
        raise HTTPException(status_code=400, detail="message is required to generate ideas")

    ideas = generate_ideas(request.message, count=request.count)
    return {
        "message": request.message,
        "count": len(ideas),
        "ideas": ideas,
    }


@app.post("/model/check")
def model_check(request: ModelCheckRequest) -> dict[str, Any]:
    """Check model connectivity for UI diagnostics."""
    try:
        model = get_model(mock_mode=request.mock_mode)
        result = model.invoke("Reply with exactly: CEOClaw model check ok")
        content = (getattr(result, "content", "") or "").strip()
        metadata = getattr(result, "response_metadata", {}) or {}
        return {
            "status": "ok",
            "mock_mode": request.mock_mode,
            "content_preview": content[:120],
            "model_mode": metadata.get("model_mode", "unknown"),
            "fallback_used": bool(metadata.get("fallback_used", False)),
            "fallback_reason": metadata.get("fallback_reason"),
        }
    except Exception as exc:
        return {
            "status": "error",
            "mock_mode": request.mock_mode,
            "error": str(exc),
        }


@app.post("/website/chat")
def website_chat(request: WebsiteChatRequest) -> dict[str, Any]:
    """Chat-first website creation and iterative editing (Lovable/Base44 style).

    History is persisted in DB scoped by session_id.
    Each turn passes the full history + current file contents to the LLM,
    which generates structured file changes applied to disk with a backup.
    """
    from services.code_generation_service import generate
    from services.file_persistence import read_current_html
    from services.workspace_editor import apply_changes

    msg = request.message.strip()
    if not msg:
        raise HTTPException(status_code=400, detail="message is required")

    # Load DB-persisted state
    session_row = get_chat_session(request.session_id)
    existing_slug: str = (session_row or {}).get("slug", "")

    # History from DB (last 40 messages)
    db_history = get_chat_history(request.session_id, limit=40)
    history = [{"role": m["role"], "content": m["content"]} for m in db_history]

    # Load existing files from disk for iterative editing
    existing_files: dict[str, str] = {}
    if existing_slug:
        for fname in ("index.html", "app.html"):
            content = read_current_html(existing_slug, fname)
            if content:
                existing_files[fname] = content

    # Determine slug before generation (needed in prompt)
    slug = existing_slug
    if not slug:
        intent = parse_intent(msg)
        product_name = intent.get("product_name") or "my-app"
        slug = re.sub(r"[^a-z0-9]+", "-", product_name.lower()).strip("-") or "my-app"

    # Generate with LLM (or template fallback)
    gen = generate(
        slug=slug,
        user_message=msg,
        history=history,
        existing_files=existing_files or None,
        mock_mode=request.mock_mode,
    )

    # Apply file changes to disk (with validation + backup)
    apply_result = apply_changes(slug=slug, changes=gen.changes)

    # Determine final product name for display
    product_name = slug.replace("-", " ").title()

    # Persist to DB: upsert session + append both messages
    upsert_chat_session(
        request.session_id,
        slug=slug,
        product_name=product_name,
        version_id=apply_result.version_id,
    )
    append_chat_message(request.session_id, "user", msg)
    append_chat_message(request.session_id, "assistant", gen.assistant_message)

    # Build changes summary for frontend
    changes_summary = [
        {
            "path": r.path,
            "action": r.action,
            "status": r.status,
            "summary": r.summary,
            "error": r.error,
        }
        for r in apply_result.results
    ]

    return {
        "session_id": request.session_id,
        "assistant_message": gen.assistant_message,
        "product_name": product_name,
        "slug": slug,
        "landing_url": f"/websites/{slug}/index",
        "app_url": f"/websites/{slug}/app",
        "model": {
            "provider": gen.provider,
            "model_mode": gen.model_mode,
            "fallback_used": getattr(gen, "fallback_used", False),
            "fallback_reason": getattr(gen, "fallback_reason", ""),
        },
        "version_id": apply_result.version_id,
        "changes": changes_summary,
        "files_applied": apply_result.applied,
        "files_skipped": apply_result.skipped,
        "warnings": apply_result.warnings + gen.warnings,
    }


# ---------------------------------------------------------------------------
# Chat history endpoints (DB-backed)
# ---------------------------------------------------------------------------


@app.get("/website/sessions")
def list_sessions(limit: int = 20) -> list[dict[str, Any]]:
    """List recent website chat sessions (newest first)."""
    return list_chat_sessions(limit=min(limit, 100))


@app.get("/website/session/{session_id}")
def website_session_state(session_id: str) -> dict[str, Any]:
    """Get session metadata (no messages)."""
    session = get_chat_session(session_id)
    if not session:
        return {"status": "empty", "session_id": session_id}
    slug = session.get("slug", "")
    return {
        "status": "ok",
        "session_id": session_id,
        "slug": slug,
        "product_name": session.get("product_name", ""),
        "landing_url": f"/websites/{slug}/index" if slug else "",
        "app_url": f"/websites/{slug}/app" if slug else "",
        "version_id": session.get("version_id"),
        "created_at": session.get("created_at"),
        "updated_at": session.get("updated_at"),
    }


@app.get("/website/session/{session_id}/history")
def get_session_history(session_id: str, limit: int = 100) -> dict[str, Any]:
    """Return full chat history + session metadata for session restore."""
    session = get_chat_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
    messages = get_chat_history(session_id, limit=limit)
    slug = session.get("slug", "")
    return {
        "session_id": session_id,
        "slug": slug,
        "product_name": session.get("product_name", ""),
        "version_id": session.get("version_id"),
        "created_at": session.get("created_at"),
        "updated_at": session.get("updated_at"),
        "messages": messages,
        "landing_url": f"/websites/{slug}/index" if slug else "",
        "app_url": f"/websites/{slug}/app" if slug else "",
    }


_EXTENSION_MEDIA_TYPES: dict[str, str] = {
    ".html": "text/html",
    ".css": "text/css",
    ".js": "application/javascript",
    ".json": "application/json",
    ".md": "text/plain",
    ".txt": "text/plain",
    ".svg": "image/svg+xml",
}
_ALLOWED_SERVING_EXTENSIONS = set(_EXTENSION_MEDIA_TYPES.keys())


@app.get("/websites/{slug}/{file_path:path}")
def serve_generated_asset(slug: str, file_path: str) -> FileResponse:
    """Serve any file under data/websites/<slug>/ with strict path safety.

    Backward-compatible: bare names 'index' and 'app' map to .html files.
    """
    from pathlib import Path as _Path

    # 1. Sanitize slug
    safe_slug = re.sub(r"[^a-z0-9-]+", "-", slug.lower()).strip("-")
    if not safe_slug:
        raise HTTPException(status_code=400, detail="invalid slug")

    # 2. Backward compat: bare page names → .html
    if file_path in ("index", "app"):
        file_path = file_path + ".html"

    # 3. Basic path safety checks
    if ".." in file_path:
        raise HTTPException(status_code=400, detail="path traversal not allowed")

    from pathlib import PurePosixPath
    ext = PurePosixPath(file_path).suffix.lower()
    if ext not in _ALLOWED_SERVING_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"file extension {ext!r} not allowed")

    # 4. Build and verify absolute path
    websites_dir = settings.resolve_websites_dir()
    slug_dir = websites_dir / safe_slug
    resolved = (slug_dir / file_path).resolve()

    # 5. Realpath check: must remain under slug_dir
    try:
        resolved.relative_to(slug_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="path escapes slug directory")

    if not resolved.exists():
        raise HTTPException(
            status_code=404,
            detail=f"File {file_path!r} not found for slug={safe_slug!r}",
        )

    media_type = _EXTENSION_MEDIA_TYPES.get(ext, "application/octet-stream")
    return FileResponse(resolved, media_type=media_type)




@app.post("/runs/start")
def runs_start(request: RunStartRequest) -> dict[str, Any]:
    """Start a run without a chat message. Alias for /chat."""
    run_id = str(uuid.uuid4())
    t = threading.Thread(
        target=_bg_run,
        args=(run_id, request.goal_mrr, request.cycles, request.mock_mode,
              request.autonomy_mode, None, request.workflow_mode),
        daemon=True,
    )
    t.start()
    return {
        "run_id": run_id,
        "stream_url": f"/runs/{run_id}/events",
        "autonomy_mode": request.autonomy_mode,
    }


@app.get("/runs/{run_id}/events")
async def stream_run_events(run_id: str) -> StreamingResponse:
    """Server-Sent Events stream for a running or completed graph run.

    Each event is a JSON object with a ``type`` field.
    The stream ends with a ``run_complete`` or ``run_error`` event.
    """
    async def generate():
        idx = 0
        max_wait = 120  # seconds before giving up on a silent run
        waited = 0.0
        try:
            while True:
                batch = _bus.get_events(run_id, idx)
                for ev in batch:
                    yield f"data: {json.dumps(ev)}\n\n"
                    idx += 1
                    waited = 0.0
                    # Close stream after final event
                    if ev.get("type") in ("run_complete", "run_error"):
                        return
                # Check if done and no more events
                if _bus.is_done(run_id) and not _bus.get_events(run_id, idx):
                    yield f"data: {json.dumps({'type': 'stream_end'})}\n\n"
                    return
                await asyncio.sleep(0.15)
                waited += 0.15
                if waited > max_wait:
                    yield f"data: {json.dumps({'type': 'stream_timeout'})}\n\n"
                    return
        finally:
            # Delay cleanup so late-arriving consumers can still read history
            await asyncio.sleep(30)
            _bus.cleanup(run_id)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ---------------------------------------------------------------------------
# v0.5 endpoints – autonomy / approvals / research / social
# ---------------------------------------------------------------------------

@app.get("/runs/{run_id}/approvals")
def get_approvals(run_id: str, status: str = "pending") -> list[dict[str, Any]]:
    """List pending (or all) approvals for a run."""
    from data.database import get_pending_approvals
    try:
        rows = get_pending_approvals(run_id, status=status)
        for r in rows:
            if isinstance(r.get("payload"), str):
                import json as _json
                try:
                    r["payload"] = _json.loads(r["payload"])
                except Exception:
                    pass
        return rows
    except Exception as exc:
        logger.warning("GET /runs/%s/approvals failed: %s", run_id, exc)
        return []


class ApprovalDecision(BaseModel):
    decision: str  # "approved" | "rejected"
    resolved_by: str = "user"


@app.post("/approvals/{approval_id}/decide")
def decide_approval(approval_id: int, body: ApprovalDecision) -> dict[str, Any]:
    """Approve or reject a pending action."""
    from data.database import get_approval, resolve_approval, update_social_post_status
    import json as _json

    if body.decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="decision must be 'approved' or 'rejected'")

    approval = get_approval(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail=f"Approval {approval_id} not found")
    if approval["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"Approval {approval_id} already resolved")

    resolve_approval(approval_id, body.decision, body.resolved_by)

    # If approved social_publish, execute it now
    payload = approval.get("payload", {})
    if isinstance(payload, str):
        try:
            payload = _json.loads(payload)
        except Exception:
            payload = {}

    if approval["approval_type"] == "social_publish" and body.decision == "approved":
        from tools.social_publishers.x_publisher import publish as x_publish
        from tools.social_publishers.instagram_publisher import publish as ig_publish
        from data.database import update_social_post_status as _upd
        platform = payload.get("platform", "x")
        content = payload.get("content", "")
        db_id = payload.get("social_post_db_id")
        if content:
            pub = x_publish(content) if platform == "x" else ig_publish(content)
            if db_id:
                _upd(db_id, pub.status, pub.post_id, pub.error_detail)
        _bus.emit(approval["run_id"], {
            "type": "approval_resolved",
            "approval_id": approval_id,
            "decision": body.decision,
            "platform": platform,
            "publish_status": getattr(pub, "status", "unknown") if content else "skipped",
        })
    else:
        _bus.emit(approval["run_id"], {
            "type": "approval_resolved",
            "approval_id": approval_id,
            "decision": body.decision,
        })

    return {"approval_id": approval_id, "decision": body.decision, "status": "resolved"}


@app.get("/runs/{run_id}/research")
def get_research(run_id: str) -> list[dict[str, Any]]:
    """List research reports for a run."""
    from data.database import get_research_reports
    import json as _json
    try:
        rows = get_research_reports(run_id)
        # Parse JSON string fields
        for r in rows:
            for field in ("competitors", "audience", "opportunities", "risks", "experiments"):
                if isinstance(r.get(field), str):
                    try:
                        r[field] = _json.loads(r[field])
                    except Exception:
                        pass
        return rows
    except Exception as exc:
        logger.warning("GET /runs/%s/research failed: %s", run_id, exc)
        return []


@app.get("/runs/{run_id}/social-posts")
def get_social_posts(run_id: str) -> list[dict[str, Any]]:
    """List social posts (all statuses) for a run."""
    from data.database import get_social_posts
    try:
        return get_social_posts(run_id)
    except Exception as exc:
        logger.warning("GET /runs/%s/social-posts failed: %s", run_id, exc)
        return []


# ---------------------------------------------------------------------------
# v0.6 endpoints – prospects + memory
# ---------------------------------------------------------------------------

@app.get("/runs/{run_id}/quality-audit")
def get_quality_audit(run_id: str) -> dict[str, Any]:
    """Return the latest quality audit scorecard for a run."""
    from data.database import get_connection
    try:
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT content_summary, created_at FROM artifacts
                WHERE run_id=? AND artifact_type='quality_audit'
                ORDER BY created_at DESC LIMIT 1
                """,
                (run_id,),
            ).fetchone()
        if row:
            return {"run_id": run_id, "summary": row["content_summary"], "created_at": row["created_at"]}
        return {"run_id": run_id, "summary": None, "message": "No audit yet for this run."}
    except Exception as exc:
        return {"run_id": run_id, "error": str(exc)}


@app.get("/runs/{run_id}/prospects")
def get_run_prospects(run_id: str, status: str = "") -> list[dict[str, Any]]:
    """List prospects discovered during a run."""
    from data.database import get_prospects
    try:
        return get_prospects(run_id, status=status or None)
    except Exception as exc:
        logger.warning("GET /runs/%s/prospects failed: %s", run_id, exc)
        return []


class ProspectStatusUpdate(BaseModel):
    status: str
    notes: str = ""


@app.patch("/prospects/{prospect_id}/status")
def update_prospect(prospect_id: int, body: ProspectStatusUpdate) -> dict[str, Any]:
    """Update a prospect's status (e.g. contacted, qualified, rejected)."""
    from data.database import update_prospect_status
    valid = {"discovered", "contacted", "qualified", "rejected", "converted"}
    if body.status not in valid:
        raise HTTPException(status_code=400, detail=f"status must be one of: {', '.join(valid)}")
    update_prospect_status(prospect_id, body.status, body.notes or None)
    return {"prospect_id": prospect_id, "status": body.status}


@app.get("/memory")
def get_memory(namespace: str = "default") -> dict[str, str]:
    """Read all cross-run memory entries in a namespace."""
    from core.memory_store import build_memory_store
    try:
        return build_memory_store().get_all(namespace=namespace)
    except Exception as exc:
        logger.warning("GET /memory failed: %s", exc)
        return {}


class MemoryEntry(BaseModel):
    key: str
    value: str
    namespace: str = "default"


@app.post("/memory")
def set_memory(entry: MemoryEntry) -> dict[str, str]:
    """Upsert a memory entry."""
    from core.memory_store import build_memory_store
    build_memory_store().set(entry.key, entry.value, namespace=entry.namespace)
    return {"key": entry.key, "namespace": entry.namespace, "status": "ok"}


@app.delete("/memory/{key}")
def delete_memory(key: str, namespace: str = "default") -> dict[str, str]:
    """Delete a memory entry."""
    from core.memory_store import build_memory_store
    build_memory_store().delete(key, namespace=namespace)
    return {"key": key, "namespace": namespace, "status": "deleted"}


# ---------------------------------------------------------------------------
# Builder endpoints (v0.8) — Lovable/Base44 style, richer responses
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Auth + credits helpers (used by builder endpoints)
# ---------------------------------------------------------------------------


def _require_session_access(session_id: str, user: dict) -> dict:
    """Return the session dict, enforcing ownership when AUTH_REQUIRED=true.

    Policy: 404 if session doesn't exist; 403 if session is owned by someone else.
    When auth is disabled (or user is anonymous), ownership is not checked.
    """
    user_id = user.get("id", "anonymous")
    if _settings_mod.settings.auth_required and user_id != "anonymous":
        session = get_chat_session_owned_by(session_id, user_id)
        if session is None:
            # Distinguish "not found" from "owned by someone else"
            full = get_chat_session(session_id)
            if full is None:
                raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
            raise HTTPException(status_code=403, detail="Access denied: session not owned by you")
        return session
    # Auth disabled or anonymous — plain lookup
    session = get_chat_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
    return session


def _gate_credits(user: dict, session_id: str) -> dict:
    """Check and (conditionally) deduct credits before a generation request.

    Returns a metadata dict:
      {"credits_before": N, "credits_after": N-cost, "cost": N, "tier": str}

    Behaviour:
    - Anonymous / AUTH_REQUIRED=false → returns null values, never blocks.
    - CREDITS_ENFORCED=false          → deducts if possible, returns preview, never blocks.
    - CREDITS_ENFORCED=true           → raises HTTP 402 if balance < cost.
    """
    user_id = user.get("id", "anonymous")

    # Anonymous mode — no credit tracking
    if not _settings_mod.settings.auth_required or user_id == "anonymous":
        return {"credits_before": None, "credits_after": None,
                "cost": GENERATION_COST, "tier": "anonymous"}

    credits_row = get_user_credits(user_id)
    balance = credits_row.get("balance", 0)
    sub_row = get_user_subscription(user_id)
    tier = (sub_row or {}).get("tier", "free")

    if _settings_mod.settings.credits_enforced and balance < GENERATION_COST:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "insufficient_credits",
                "message": (
                    f"You need {GENERATION_COST} credit(s) to generate. "
                    f"Current balance: {balance}."
                ),
                "balance": balance,
                "required": GENERATION_COST,
                "tier": tier,
            },
        )

    # Deduct when credits are available (even when enforcement is off — tracks usage)
    if balance >= GENERATION_COST:
        result = deduct_credits(user_id, GENERATION_COST, "generate_request", session_id)
        credits_after = result.get("balance_after", balance - GENERATION_COST)
    else:
        # Not enforced + zero balance: preview-only, no deduction
        credits_after = balance

    return {
        "credits_before": balance,
        "credits_after": credits_after,
        "cost": GENERATION_COST,
        "tier": tier,
    }


def _maybe_add_endpoint_scaffold(gen: Any, slug: str, intent: dict) -> None:
    """Append data.json FileChange if intent has api_endpoints. Idempotent.

    Called after generate() returns in both builder_chat and _run_pipeline_bg
    so the endpoint scaffold is always produced regardless of which code path
    handled the generation.
    """
    from services.code_generation_service import FileChange
    import json as _json

    operation = intent  # intent here is the operation dict
    if operation.get("type") != "add_endpoint":
        return

    # Avoid double-appending if already present
    for change in gen.changes:
        if change.path.endswith("/data.json") or change.path.endswith("data.json"):
            return

    methods = operation.get("metadata", {}).get("http_methods", ["GET", "POST"])
    endpoint_scaffold = {
        "endpoints": [
            {"method": m, "path": f"/api/{slug}", "description": f"{m} endpoint"}
            for m in methods
        ]
    }
    gen.changes.append(FileChange(
        path=f"data/websites/{slug}/data.json",
        action="create",
        content=_json.dumps(endpoint_scaffold, indent=2),
        summary="Scaffolded endpoint spec",
    ))


@app.post("/builder/chat")
def builder_chat(
    request: BuilderChatRequest,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Chat-first website creation with richer response (Builder v0.9).

    - Accepts optional style_seed and operation for design diversification
    - Auto-detects operation type from message if not provided
    - Persists design system per session
    - Saves version record after successful apply
    - Returns fallback_used / fallback_reason in model info
    - Requires auth when AUTH_REQUIRED=true; enforces credits when CREDITS_ENFORCED=true
    """
    from services.code_generation_service import generate
    from services.file_persistence import list_project_files, read_current_file
    from services.operation_parser import parse_operation
    from services.workspace_editor import apply_changes

    msg = request.message.strip()
    if not msg:
        raise HTTPException(status_code=400, detail="message is required")

    # ── Ownership check: existing session must belong to this user ──────────
    session_row = get_chat_session(request.session_id)
    if session_row and _settings_mod.settings.auth_required and current_user["id"] != "anonymous":
        existing_owner = session_row.get("owner_user_id")
        if existing_owner and existing_owner != current_user["id"]:
            raise HTTPException(status_code=403, detail="Access denied: session not owned by you")

    # ── Credits gate ────────────────────────────────────────────────────────
    credit_meta = _gate_credits(current_user, request.session_id)

    existing_slug: str = (session_row or {}).get("slug", "")

    db_history = get_chat_history(request.session_id, limit=40)
    history = [{"role": m["role"], "content": m["content"]} for m in db_history]

    # Load ALL existing project files (not just index.html and app.html)
    existing_files: dict[str, str] = {}
    if existing_slug:
        for rel_path in list_project_files(existing_slug):
            content = read_current_file(existing_slug, rel_path)
            if content:
                existing_files[rel_path] = content

    slug = existing_slug
    if not slug:
        intent = parse_intent(msg)
        product_name_raw = intent.get("product_name") or "my-app"
        slug = re.sub(r"[^a-z0-9]+", "-", product_name_raw.lower()).strip("-") or "my-app"

    style_seed_dict: dict | None = None
    if request.style_seed:
        style_seed_dict = {
            k: v for k, v in {
                "archetype": request.style_seed.archetype,
                "palette": request.style_seed.palette,
                "density": request.style_seed.density,
                "motion": request.style_seed.motion,
            }.items() if v
        } or None

    # Detect or use provided operation
    operation = request.operation or parse_operation(msg)

    # Load persisted design system; generate one if first request
    design_system_dict = get_design_system(request.session_id)
    if design_system_dict is None:
        from services.design_system_service import DesignSystem
        ds = DesignSystem.generate_unique(
            archetype=(style_seed_dict or {}).get("archetype", "saas"),
            style_seed=style_seed_dict,
        )
        design_system_dict = ds.to_dict()
        upsert_design_system(request.session_id, design_system_dict)
    elif not design_system_dict.get("design_family"):
        # Backfill missing design_family on legacy sessions
        design_system_dict["design_family"] = "framer_aura"
        upsert_design_system(request.session_id, design_system_dict)

    gen = generate(
        slug=slug,
        user_message=msg,
        history=history,
        existing_files=existing_files or None,
        mock_mode=request.mock_mode,
        style_seed=style_seed_dict,
        design_system=design_system_dict,
        operation=operation,
    )

    # Append data.json scaffold if this is an add_endpoint operation
    _maybe_add_endpoint_scaffold(gen, slug, operation)

    apply_result = apply_changes(slug=slug, changes=gen.changes)
    product_name = slug.replace("-", " ").title()

    upsert_chat_session(
        request.session_id,
        slug=slug,
        product_name=product_name,
        version_id=apply_result.version_id,
        owner_user_id=current_user.get("id") if _settings_mod.settings.auth_required else None,
    )
    append_chat_message(request.session_id, "user", msg)
    msg_id = append_chat_message(request.session_id, "assistant", gen.assistant_message)

    # Save version record if files were applied
    if apply_result.version_id and apply_result.applied:
        # Build files snapshot from applied files
        files_snapshot: dict[str, str] = {}
        for rel_path in apply_result.applied:
            content = read_current_file(slug, rel_path)
            if content is not None:
                files_snapshot[rel_path] = content
        if files_snapshot:
            save_session_version(
                session_id=request.session_id,
                version_id=apply_result.version_id,
                files=files_snapshot,
                message_id=msg_id,
            )

    changes_summary = [
        {
            "path": r.path,
            "action": r.action,
            "status": r.status,
            "summary": r.summary,
            "error": r.error,
        }
        for r in apply_result.results
    ]

    return {
        "session_id": request.session_id,
        "assistant_message": gen.assistant_message,
        "product_name": product_name,
        "slug": slug,
        "landing_url": f"/websites/{slug}/index",
        "app_url": f"/websites/{slug}/app",
        "model": {
            "provider": gen.provider,
            "model_mode": gen.model_mode,
            "fallback_used": gen.fallback_used,
            "fallback_reason": gen.fallback_reason,
        },
        "version_id": apply_result.version_id,
        "changes": changes_summary,
        "files_applied": apply_result.applied,
        "files_skipped": apply_result.skipped,
        "warnings": apply_result.warnings + gen.warnings,
        "operation": operation,
        "design_system": design_system_dict,
        "blueprint": getattr(gen, "blueprint", {}),
        "layout_plan": gen.layout_plan,
        "consistency_profile_id": gen.consistency_profile_id or design_system_dict.get("consistency_profile_id", ""),
        "credits": credit_meta,
    }


@app.get("/builder/sessions")
def builder_list_sessions(
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """List builder chat sessions (newest first).

    When AUTH_REQUIRED=true, returns only sessions owned by the requesting user.
    """
    capped = min(limit, 100)
    user_id = current_user.get("id", "anonymous")
    if _settings_mod.settings.auth_required and user_id != "anonymous":
        return list_chat_sessions_for_user(user_id, limit=capped)
    return list_chat_sessions(limit=capped)


@app.get("/builder/sessions/{session_id}")
def builder_get_session(
    session_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Get session metadata (ownership-checked when AUTH_REQUIRED=true)."""
    session = get_chat_session(session_id)
    if not session:
        return {"status": "empty", "session_id": session_id}
    # Ownership check
    user_id = current_user.get("id", "anonymous")
    if _settings_mod.settings.auth_required and user_id != "anonymous":
        owner = session.get("owner_user_id")
        if owner and owner != user_id:
            raise HTTPException(status_code=403, detail="Access denied: session not owned by you")
    slug = session.get("slug", "")
    return {
        "status": "ok",
        "session_id": session_id,
        "slug": slug,
        "product_name": session.get("product_name", ""),
        "landing_url": f"/websites/{slug}/index" if slug else "",
        "app_url": f"/websites/{slug}/app" if slug else "",
        "version_id": session.get("version_id"),
        "created_at": session.get("created_at"),
        "updated_at": session.get("updated_at"),
    }


@app.delete("/builder/sessions/{session_id}")
def builder_delete_session(
    session_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Delete a session and all its messages (ownership-checked when AUTH_REQUIRED=true)."""
    _require_session_access(session_id, current_user)
    deleted = delete_chat_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "deleted", "session_id": session_id}


@app.get("/builder/sessions/{session_id}/messages")
def builder_get_session_messages(
    session_id: str,
    limit: int = 100,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Return full chat history + session metadata for session restore."""
    session = _require_session_access(session_id, current_user)
    messages = get_chat_history(session_id, limit=limit)
    slug = session.get("slug", "")
    return {
        "session_id": session_id,
        "slug": slug,
        "product_name": session.get("product_name", ""),
        "version_id": session.get("version_id"),
        "created_at": session.get("created_at"),
        "updated_at": session.get("updated_at"),
        "messages": messages,
        "landing_url": f"/websites/{slug}/index" if slug else "",
        "app_url": f"/websites/{slug}/app" if slug else "",
    }


@app.get("/builder/provider/status")
def builder_provider_status() -> dict[str, Any]:
    """Check health of configured LLM providers."""
    from services.llm_router_service import check_provider_health
    return check_provider_health()


# ---------------------------------------------------------------------------
# Version graph endpoints (v0.9)
# ---------------------------------------------------------------------------


@app.get("/builder/sessions/{session_id}/versions")
def list_versions(
    session_id: str,
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """List version records for a session, newest first."""
    if _settings_mod.settings.auth_required:
        _require_session_access(session_id, current_user)
    return list_session_versions(session_id, limit=min(limit, 100))


@app.get("/builder/sessions/{session_id}/versions/{version_id}")
def get_version(
    session_id: str,
    version_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Return version metadata + file list (not full content by default)."""
    if _settings_mod.settings.auth_required:
        _require_session_access(session_id, current_user)
    record = get_session_version(session_id, version_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Version {version_id!r} not found")
    return {
        "id": record.get("id"),
        "session_id": record.get("session_id"),
        "version_id": record.get("version_id"),
        "message_id": record.get("message_id"),
        "file_list": record.get("file_list", []),
        "created_at": record.get("created_at"),
    }


@app.post("/builder/sessions/{session_id}/versions/{version_id}/restore")
def restore_version(
    session_id: str,
    version_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Restore a previous version: re-apply its files to disk, upsert session."""
    from services.file_persistence import save_website_files

    run_id = f"restore:{session_id}:{version_id}"
    # #region agent log
    _debug_log(
        run_id,
        "H1_H2_H3",
        "api/server.py:restore_version:entry",
        "restore_version called",
        {
            "session_id": session_id,
            "version_id": version_id,
            "auth_required": _settings_mod.settings.auth_required,
            "current_user_id": current_user.get("id", "anonymous"),
        },
    )
    # #endregion

    # Ownership check (only when auth is required and user is not anonymous)
    if _settings_mod.settings.auth_required:
        try:
            session = _require_session_access(session_id, current_user)
            # #region agent log
            _debug_log(
                run_id,
                "H1_H2",
                "api/server.py:restore_version:after_require_session_access",
                "session access granted",
                {
                    "session_found": True,
                    "session_slug": session.get("slug"),
                    "owner_user_id": session.get("owner_user_id"),
                },
            )
            # #endregion
        except HTTPException as exc:
            # #region agent log
            _debug_log(
                run_id,
                "H1_H2",
                "api/server.py:restore_version:require_session_access_error",
                "session access rejected",
                {
                    "status_code": exc.status_code,
                    "detail": exc.detail,
                },
            )
            # #endregion
            raise
    else:
        session = get_chat_session(session_id) or {}
        # #region agent log
        _debug_log(
            run_id,
            "H1",
            "api/server.py:restore_version:auth_disabled_lookup",
            "auth disabled session lookup result",
            {
                "session_found": bool(session),
                "session_slug": session.get("slug"),
            },
        )
        # #endregion

    record = get_session_version(session_id, version_id)
    # #region agent log
    _debug_log(
        run_id,
        "H4",
        "api/server.py:restore_version:after_get_session_version",
        "version lookup completed",
        {
            "version_found": bool(record),
            "record_has_files": bool(record and record.get("files")),
        },
    )
    # #endregion
    if not record:
        raise HTTPException(status_code=404, detail=f"Version {version_id!r} not found")

    files = record.get("files", {})
    if not files:
        raise HTTPException(status_code=400, detail="Version has no file content to restore")

    slug = session.get("slug", "")
    # #region agent log
    _debug_log(
        run_id,
        "H5",
        "api/server.py:restore_version:before_slug_check",
        "checking session slug",
        {
            "slug": slug,
            "slug_present": bool(slug),
        },
    )
    # #endregion
    if not slug:
        raise HTTPException(status_code=400, detail="Session has no slug — cannot restore")

    save_result = save_website_files(slug, files)
    new_version_id = save_result.get("version_id", "")

    upsert_chat_session(session_id, slug=slug, version_id=new_version_id)

    return {
        "session_id": session_id,
        "restored_from": version_id,
        "version_id": new_version_id,
        "files_applied": list(files.keys()),
        "slug": slug,
    }


@app.get("/builder/sessions/{session_id}/versions/{version_id}/files/{file_path:path}")
def get_version_file(
    session_id: str,
    version_id: str,
    file_path: str,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Return content of a specific file at a given version."""
    if ".." in file_path:
        raise HTTPException(status_code=400, detail="path traversal not allowed")

    if _settings_mod.settings.auth_required:
        _require_session_access(session_id, current_user)
    record = get_session_version(session_id, version_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Version {version_id!r} not found")

    files = record.get("files", {})
    if file_path not in files:
        raise HTTPException(status_code=404, detail=f"File {file_path!r} not in this version")

    return {
        "session_id": session_id,
        "version_id": version_id,
        "file_path": file_path,
        "content": files[file_path],
    }


# ---------------------------------------------------------------------------
# Builder pipeline endpoints (v1.0) — async 8-stage orchestrated generation
# ---------------------------------------------------------------------------

def _run_pipeline_bg(
    job_id: str,
    session_id: str,
    message: str,
    slug: str,
    history: list[dict],
    existing_files: dict,
    mock_mode: bool,
    style_seed: dict | None,
    design_system: dict | None,
    operation: dict | None,
    owner_user_id: str | None = None,
) -> None:
    """Background thread: run the generation pipeline and emit events to bus."""
    run_id = f"pipeline_bg_{job_id[:8]}"

    def emit(event: dict) -> None:
        _bus.emit(job_id, event)

    try:
        from services.generation_pipeline import run_pipeline
        ctx = run_pipeline(
            session_id=session_id,
            slug=slug,
            message=message,
            history=history,
            existing_files=existing_files or None,
            mock_mode=mock_mode,
            style_seed=style_seed,
            design_system=design_system,
            operation=operation,
            emit=emit,
        )

        gen = ctx.get("gen")
        apply_result = ctx.get("apply")
        if not gen or not apply_result:
            raise RuntimeError("Pipeline produced no output")

        # Append data.json scaffold if this is an add_endpoint operation
        # (pipeline runs generate_code before apply_files; we patch gen.changes
        #  here so the result is reflected in files_applied / changes_summary)
        _maybe_add_endpoint_scaffold(gen, slug, operation or {})

        product_name = slug.replace("-", " ").title()

        # Persist to DB (same as builder_chat)
        upsert_chat_session(
            session_id,
            slug=slug,
            product_name=product_name,
            version_id=apply_result.version_id,
            owner_user_id=owner_user_id,
        )
        append_chat_message(session_id, "user", message)
        msg_id = append_chat_message(session_id, "assistant", gen.assistant_message)

        # Save version record if files were applied
        if apply_result.version_id and apply_result.applied:
            from services.file_persistence import read_current_file
            files_snapshot: dict[str, str] = {}
            for rel_path in apply_result.applied:
                content = read_current_file(slug, rel_path)
                if content is not None:
                    files_snapshot[rel_path] = content
            if files_snapshot:
                save_session_version(
                    session_id=session_id,
                    version_id=apply_result.version_id,
                    files=files_snapshot,
                    message_id=msg_id,
                )

        changes_summary = [
            {"path": r.path, "action": r.action, "status": r.status,
             "summary": r.summary, "error": r.error}
            for r in apply_result.results
        ]

        blueprint = ctx.get("blueprint", {}) or getattr(gen, "blueprint", {})
        response: dict[str, Any] = {
            "session_id": session_id,
            "assistant_message": gen.assistant_message,
            "product_name": product_name,
            "slug": slug,
            "landing_url": f"/websites/{slug}/index",
            "app_url": f"/websites/{slug}/app",
            "model": {
                "provider": gen.provider,
                "model_mode": gen.model_mode,
                "fallback_used": gen.fallback_used,
                "fallback_reason": gen.fallback_reason,
            },
            "version_id": apply_result.version_id,
            "changes": changes_summary,
            "files_applied": apply_result.applied,
            "files_skipped": apply_result.skipped,
            "warnings": apply_result.warnings + gen.warnings,
            "operation": operation or {},
            "design_system": design_system,
            "blueprint": blueprint,
            "layout_plan": getattr(gen, "layout_plan", {}),
            "consistency_profile_id": getattr(gen, "consistency_profile_id", "") or (design_system or {}).get("consistency_profile_id", ""),
        }

        _bus.emit(job_id, {"type": "pipeline_complete", "result": response})
        _debug_log(
            run_id,
            "H5",
            "api/server.py:_run_pipeline_bg",
            "pipeline_complete emitted",
            {"jobId": job_id, "versionId": response.get("version_id", ""), "changes": len(changes_summary)},
        )

    except Exception as exc:
        logger.exception("Pipeline job %s failed: %s", job_id[:8], exc)
        _bus.emit(job_id, {"type": "pipeline_error", "error": str(exc)})
        _debug_log(
            run_id,
            "H5",
            "api/server.py:_run_pipeline_bg",
            "pipeline_error emitted",
            {"jobId": job_id, "error": str(exc)[:180]},
        )

    finally:
        _bus.mark_done(job_id)


@app.post("/builder/generate")
def builder_generate_start(
    request: BuilderChatRequest,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Start an async pipeline generation job.  Returns job_id for SSE streaming.

    The client opens GET /builder/generate/{job_id}/events to receive live
    stage_update events, then a pipeline_complete or pipeline_error final event.

    Requires auth when AUTH_REQUIRED=true; enforces credits when CREDITS_ENFORCED=true.
    """
    from services.file_persistence import list_project_files, read_current_file
    from services.operation_parser import parse_operation

    msg = request.message.strip()
    if not msg:
        raise HTTPException(status_code=400, detail="message is required")

    # ── Ownership check for existing session ────────────────────────────────
    session_row = get_chat_session(request.session_id)
    if session_row and _settings_mod.settings.auth_required and current_user["id"] != "anonymous":
        existing_owner = session_row.get("owner_user_id")
        if existing_owner and existing_owner != current_user["id"]:
            raise HTTPException(status_code=403, detail="Access denied: session not owned by you")

    # ── Credits gate (must deduct before kicking off background work) ────────
    credit_meta = _gate_credits(current_user, request.session_id)

    existing_slug: str = (session_row or {}).get("slug", "")

    db_history = get_chat_history(request.session_id, limit=40)
    history = [{"role": m["role"], "content": m["content"]} for m in db_history]

    existing_files: dict[str, str] = {}
    if existing_slug:
        for rel_path in list_project_files(existing_slug):
            content = read_current_file(existing_slug, rel_path)
            if content:
                existing_files[rel_path] = content

    slug = existing_slug
    if not slug:
        intent = parse_intent(msg)
        product_name_raw = intent.get("product_name") or "my-app"
        slug = re.sub(r"[^a-z0-9]+", "-", product_name_raw.lower()).strip("-") or "my-app"

    style_seed_dict: dict | None = None
    if request.style_seed:
        style_seed_dict = {
            k: v for k, v in {
                "archetype": request.style_seed.archetype,
                "palette": request.style_seed.palette,
                "density": request.style_seed.density,
                "motion": request.style_seed.motion,
            }.items() if v
        } or None

    operation = request.operation or parse_operation(msg)

    design_system_dict = get_design_system(request.session_id)
    if design_system_dict is None:
        from services.design_system_service import DesignSystem
        ds = DesignSystem.generate_unique(
            archetype=(style_seed_dict or {}).get("archetype", "saas"),
            style_seed=style_seed_dict,
        )
        design_system_dict = ds.to_dict()
        upsert_design_system(request.session_id, design_system_dict)

    # Clarification check — return early if intent is too vague
    from services.generation_pipeline import check_clarification_needed
    clarification = check_clarification_needed(msg, history, style_seed_dict)
    if clarification:
        return {
            "needs_clarification": True,
            "questions": clarification["questions"],
            "reason": clarification["reason"],
            "job_id": None,
        }

    job_id = str(uuid.uuid4())
    _debug_log(
        f"pipeline_http_{job_id[:8]}",
        "H3",
        "api/server.py:builder_generate_start",
        "builder generate start accepted",
        {"jobId": job_id, "sessionId": request.session_id, "messageLen": len(msg), "mockMode": request.mock_mode},
    )
    owner_user_id = current_user.get("id") if _settings_mod.settings.auth_required else None
    t = threading.Thread(
        target=_run_pipeline_bg,
        args=(
            job_id, request.session_id, msg, slug,
            history, existing_files, request.mock_mode,
            style_seed_dict, design_system_dict, operation,
            owner_user_id,
        ),
        daemon=True,
    )
    t.start()

    return {
        "job_id": job_id,
        "slug": slug,
        "session_id": request.session_id,
        "credits": credit_meta,
    }


@app.get("/builder/generate/{job_id}/events")
async def builder_generate_events(job_id: str) -> StreamingResponse:
    """SSE stream for a pipeline generation job.

    Emits stage_update events as each stage completes, followed by a single
    pipeline_complete or pipeline_error terminal event.
    """
    async def generate():
        idx = 0
        max_wait = 660  # seconds — must exceed LLM timeout (600s) + buffer
        waited = 0.0
        heartbeat_interval = 15.0  # emit keepalive every 15s during long LLM calls
        since_heartbeat = 0.0
        try:
            while True:
                batch = _bus.get_events(job_id, idx)
                for ev in batch:
                    _debug_log(
                        f"pipeline_sse_{job_id[:8]}",
                        "H1",
                        "api/server.py:builder_generate_events",
                        "sse event emitted",
                        {"jobId": job_id, "eventType": ev.get("type", ""), "idx": idx},
                    )
                    yield f"data: {json.dumps(ev)}\n\n"
                    idx += 1
                    waited = 0.0
                    since_heartbeat = 0.0
                    if ev.get("type") in ("pipeline_complete", "pipeline_error"):
                        return
                if _bus.is_done(job_id) and not _bus.get_events(job_id, idx):
                    yield f"data: {json.dumps({'type': 'pipeline_error', 'error': 'stream_ended_without_completion'})}\n\n"
                    return
                await asyncio.sleep(0.1)
                waited += 0.1
                since_heartbeat += 0.1
                # Emit SSE comment heartbeat so client connection stays alive
                if since_heartbeat >= heartbeat_interval:
                    yield ": heartbeat\n\n"
                    since_heartbeat = 0.0
                if waited > max_wait:
                    yield f"data: {json.dumps({'type': 'pipeline_error', 'error': 'timeout'})}\n\n"
                    return
        finally:
            await asyncio.sleep(30)
            _bus.cleanup(job_id)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ---------------------------------------------------------------------------
# Account endpoints (v1.0 — requires auth)
# ---------------------------------------------------------------------------


@app.get("/account/me")
def account_me(current_user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Return the authenticated user's profile.

    When AUTH_REQUIRED=false, returns the anonymous user placeholder.
    """
    if current_user.get("id") == "anonymous":
        return {**ANONYMOUS_USER, "tier": "anonymous", "auth_required": False}

    user = get_user_by_id(current_user["id"])
    if not user:
        # Freshly minted token before the DB row was committed — return claims
        return {**current_user, "tier": "free", "auth_required": True}

    sub = get_user_subscription(current_user["id"])
    return {
        "id": user["id"],
        "email": user["email"],
        "display_name": user.get("display_name"),
        "avatar_url": user.get("avatar_url"),
        "provider": user.get("provider"),
        "created_at": user.get("created_at"),
        "tier": (sub or {}).get("tier", "free"),
        "auth_required": _settings_mod.settings.auth_required,
    }


@app.get("/account/credits")
def account_credits(current_user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Return the authenticated user's credit balance and recent ledger."""
    if current_user.get("id") == "anonymous":
        return {
            "user_id": "anonymous",
            "balance": None,
            "monthly_allocation": None,
            "credits_enforced": False,
            "ledger": [],
        }

    credits = get_user_credits(current_user["id"])
    ledger = get_credit_ledger(current_user["id"], limit=20)
    return {
        "user_id": current_user["id"],
        "balance": credits.get("balance", 0),
        "monthly_allocation": credits.get("monthly_allocation", 0),
        "updated_at": credits.get("updated_at"),
        "credits_enforced": _settings_mod.settings.credits_enforced,
        "cost_per_generation": GENERATION_COST,
        "ledger": ledger,
    }


@app.get("/account/subscription")
def account_subscription(current_user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Return the authenticated user's active subscription."""
    if current_user.get("id") == "anonymous":
        return {"tier": "anonymous", "status": "n/a", "user_id": "anonymous"}

    sub = get_user_subscription(current_user["id"])
    if not sub:
        return {"tier": "free", "status": "none", "user_id": current_user["id"]}
    return sub


# ---------------------------------------------------------------------------
# Frontend serving (v0.5 → v0.9: React build support)
# ---------------------------------------------------------------------------

_FRONTEND_DIST = _PROJECT_ROOT / "frontend" / "dist" / "index.html"
_FRONTEND_LEGACY = _PROJECT_ROOT / "frontend" / "legacy.html"
_FRONTEND_OLD = _PROJECT_ROOT / "frontend" / "index.html"

# Mount static assets from React build if available
_ASSETS_DIR = _PROJECT_ROOT / "frontend" / "dist" / "assets"
if _ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(_ASSETS_DIR)), name="assets")


@app.get("/app")
@app.get("/")
def serve_frontend() -> FileResponse:
    """Serve the React build or fall back to legacy HTML UI."""
    if _FRONTEND_DIST.exists():
        return FileResponse(_FRONTEND_DIST, media_type="text/html")
    if _FRONTEND_LEGACY.exists():
        return FileResponse(_FRONTEND_LEGACY, media_type="text/html")
    if _FRONTEND_OLD.exists():
        return FileResponse(_FRONTEND_OLD, media_type="text/html")
    raise HTTPException(status_code=404, detail="Frontend not built. Run: cd frontend && npm run build")
