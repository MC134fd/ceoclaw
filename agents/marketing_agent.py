"""
MarketingExecutorNode  – v0.3 hardened.

Permitted tools: seo_tool, analytics_tool.
Persists artifacts.  Updates consecutive_failures circuit-breaker state.

Node contract output keys:
    executor_result, consecutive_failures
"""

import json
from typing import Any

from langchain_core.runnables import RunnableConfig

from agents import CEOClawState
from config.settings import settings
from core.prompts import ExecutorOutput
from data.database import log_node_finish, log_node_start, persist_artifact, utc_now
from tools.analytics_tool import analytics_tool
from tools.research_tool import research_tool
from tools.seo_tool import seo_tool
from tools.social_publisher import social_publisher_tool

_EXECUTOR_KEY = "marketing_executor"


def marketing_executor_node(state: CEOClawState, config: RunnableConfig) -> dict[str, Any]:
    """MarketingExecutorNode: run SEO and analytics experiments."""
    action = state.get("selected_action", "run_seo_analysis")
    cycle_count = state.get("cycle_count", 0)
    run_id = state["run_id"]

    exec_id = log_node_start(
        run_id=run_id, cycle_count=cycle_count,
        node_name="marketing_executor", input_summary=f"action={action}",
    )

    failures: dict[str, int] = dict(state.get("consecutive_failures") or {})

    try:
        result = _dispatch(state, action, run_id, cycle_count)
        failures[_EXECUTOR_KEY] = 0
        log_node_finish(exec_id, output_summary=result["executor_result"]["execution_status"])
        return {**result, "consecutive_failures": failures}
    except Exception as exc:  # noqa: BLE001
        failures[_EXECUTOR_KEY] = failures.get(_EXECUTOR_KEY, 0) + 1
        error_entry = {"node": "marketing_executor", "error": str(exc), "timestamp": utc_now()}
        log_node_finish(exec_id, output_summary=f"error:{exc}", status="failed")
        return {
            "errors": [error_entry],
            "executor_result": _error_result(action, str(exc)),
            "consecutive_failures": failures,
        }


def _dispatch(
    state: CEOClawState, action: str, run_id: str, cycle_count: int
) -> dict[str, Any]:
    product_name = _resolve_product_name(state)
    intent = state.get("product_intent") or {}
    autonomy_mode = state.get("autonomy_mode", "A_AUTONOMOUS")
    artifacts: list[str] = []
    metrics_delta: dict[str, Any] = {}
    seo_data: dict[str, Any] = {}
    research_data: dict[str, Any] = {}
    social_data: dict[str, Any] = {}

    # --- Research action (uses intent-aware topic) ---
    if "research" in action.lower() or "market" in action.lower() or "analys" in action.lower():
        # Build a more specific research topic from intent
        product_type = intent.get("product_type", "")
        target_user = intent.get("target_user", "")
        domain_topic = state.get("selected_domain", "marketing")
        topic = f"{domain_topic} for {product_type} targeting {target_user}" if product_type else f"{domain_topic} market research"
        raw_research = research_tool.invoke({
            "topic": topic,
            "product_name": product_name,
            "run_id": run_id,
            "cycle_count": cycle_count,
        })
        research_data = json.loads(raw_research)
        artifacts.append("research_report")
        metrics_delta["research_completed"] = 1

    # --- SEO audit ---
    if state.get("active_product") and "research" not in action.lower():
        raw_seo = seo_tool.invoke({
            "product_name": product_name,
            "target_keyword": product_name.lower().replace(" ", "-"),
        })
        seo_data = json.loads(raw_seo)
        metrics_delta["seo_score"] = seo_data.get("seo_score", 0)
        artifacts.append("seo_report")
        persist_artifact(
            run_id=run_id, cycle_count=cycle_count,
            node_name="marketing_executor", artifact_type="seo_report",
            content_summary=f"score={seo_data.get('seo_score')} issues={len(seo_data.get('issues', []))}",
        )

    # --- Social content publishing (X-only; Instagram only if configured) ---
    if "social" in action.lower() or "content" in action.lower() or "publish" in action.lower():
        post_content = _generate_social_content(product_name, state, research_data)
        platforms_to_post = ["x"]
        # Only add Instagram if explicitly configured (not required)
        if settings.instagram_access_token and settings.instagram_user_id:
            platforms_to_post.append("instagram")

        for platform in platforms_to_post:
            raw_social = social_publisher_tool.invoke({
                "platform": platform,
                "content": post_content,
                "autonomy_mode": autonomy_mode,
                "run_id": run_id,
                "cycle_count": cycle_count,
            })
            social_result = json.loads(raw_social)
            social_data[platform] = social_result
            artifacts.append(f"social_{platform}_{social_result.get('status', 'drafted')}")
        metrics_delta["social_posts_created"] = len(platforms_to_post)

    raw_analytics = analytics_tool.invoke({"lookback": 3, "record_snapshot": False})
    analytics_data = json.loads(raw_analytics)
    analytics_latest = analytics_data.get("latest") or {}
    metrics_delta["traffic"] = analytics_latest.get("website_traffic", 0)

    persist_artifact(
        run_id=run_id, cycle_count=cycle_count,
        node_name="marketing_executor", artifact_type="analytics_snapshot",
        content_summary=analytics_data.get("summary", "no summary"),
    )
    artifacts.append("analytics_snapshot")

    detail: dict[str, Any] = {
        "analytics_summary": analytics_data.get("summary", ""),
    }
    if seo_data:
        detail["seo"] = seo_data
    if research_data:
        detail["research_summary"] = research_data.get("summary", "")
        detail["research_opportunities"] = research_data.get("opportunities", [])
    if social_data:
        detail["social_posts"] = social_data

    er = ExecutorOutput(
        action_taken=action,
        artifacts_created=artifacts,
        metrics_delta=metrics_delta,
        execution_status="completed",
        detail=detail,
    )
    result: dict[str, Any] = {"executor_result": er.model_dump()}

    # Refresh latest_metrics from the analytics snapshot so evaluator sees
    # current DB state without requiring a full ops cycle.
    if analytics_latest:
        prev = state.get("latest_metrics") or {}
        result["latest_metrics"] = {
            "website_traffic": analytics_latest.get("website_traffic",
                                                     prev.get("website_traffic", 0)),
            "signups": analytics_latest.get("signups", prev.get("signups", 0)),
            "mrr": analytics_latest.get("mrr", prev.get("mrr", 0.0)),
            "conversion_rate": analytics_latest.get("conversion_rate",
                                                     prev.get("conversion_rate", 0.0)),
            "revenue": analytics_latest.get("revenue", prev.get("revenue", 0.0)),
        }

    return result


def _generate_social_content(product_name: str, state: dict, research_data: dict) -> str:
    """Generate a research-informed social media post for the product."""
    mrr = (state.get("latest_metrics") or {}).get("mrr", 0.0)
    cycle = state.get("cycle_count", 0)
    intent = state.get("product_intent") or {}
    target_user = intent.get("target_user", "founders")

    # Use research findings to make content specific
    opportunities = research_data.get("opportunities", [])
    opportunity_hook = opportunities[0] if opportunities else None
    summary_snippet = (research_data.get("summary", "") or "")[:120]

    if opportunity_hook:
        return (
            f"Spotted a big opportunity for {target_user}: {opportunity_hook}. "
            f"That's exactly why we're building {product_name}. "
            f"MRR: ${mrr:.0f} | Cycle {cycle} #buildinpublic #saas"
        )[:280]

    if summary_snippet:
        return (
            f"{summary_snippet} {product_name} is solving this for {target_user}. "
            f"MRR: ${mrr:.0f} #buildinpublic #founder"
        )[:280]

    templates = [
        f"Building {product_name} in public. Cycle {cycle}: MRR ${mrr:.0f}. "
        f"Every decision is data-driven. #buildinpublic #saas #founder",
        f"Shipped a major update to {product_name}. "
        f"Autonomous iteration running 24/7. MRR: ${mrr:.0f}. #indiedev #buildinpublic",
        f"{product_name} cycle {cycle} complete. "
        f"Built for {target_user}. Tracking metrics daily. #startuplife #saas",
    ]
    return templates[cycle % len(templates)][:280]


def _resolve_product_name(state: CEOClawState) -> str:
    intent = state.get("product_intent") or {}
    if intent.get("product_name"):
        return intent["product_name"]
    if state.get("active_product"):
        return state["active_product"].get("name", "CEOClaw MVP")
    return "CEOClaw MVP"


def _error_result(action: str, error: str) -> dict[str, Any]:
    return ExecutorOutput(
        action_taken=action, execution_status="failed", error_code=error
    ).model_dump()
