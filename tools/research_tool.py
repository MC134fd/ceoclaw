"""
research_tool – LangChain tool.

Produces a structured market research report for a product/topic.
Attempts live web research via the provider chain first; falls back to
deterministic templates when no provider is available.

Persists the report to research_reports table and creates an artifact entry.
Returns a JSON string suitable for the agent loop.
"""

import json
import logging
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from data.database import persist_artifact, persist_research_report
from tools.web_search import live_research

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Deterministic research templates (safe fallback — no external API needed)
# ---------------------------------------------------------------------------

_RESEARCH_TEMPLATES: dict[str, dict[str, Any]] = {
    "product": {
        "summary": "The B2B SaaS productivity market is growing at 13% CAGR with $150B+ TAM. Early-stage founders face intense competition from established players but win on niche vertical focus.",
        "competitors": [
            {"name": "Notion", "stage": "unicorn", "weakness": "Complexity for non-technical users"},
            {"name": "Linear", "stage": "growth", "weakness": "Dev-focused, narrow audience"},
            {"name": "Airtable", "stage": "unicorn", "weakness": "Price creep, complex for SMB"},
        ],
        "audience": {
            "primary": "Solo founders and small teams (1-10 people)",
            "pain_points": ["Too many tools", "Context switching overhead", "Manual reporting"],
            "willingness_to_pay": "$29-$99/mo",
            "acquisition_channel": "Product Hunt, Twitter/X, Indie Hackers",
        },
        "opportunities": [
            "Vertical SaaS for specific industries (e.g. legal, healthcare founders)",
            "AI-first workflow automation replacing spreadsheets",
            "Integrate with existing tools instead of replacing them",
        ],
        "risks": [
            "Market saturation in general productivity",
            "Large incumbents copying features quickly",
            "Long enterprise sales cycles if targeting mid-market",
        ],
        "experiments": [
            {"name": "Landing page A/B test", "metric": "signup_rate", "duration_days": 7},
            {"name": "Cold outreach to IH community", "metric": "response_rate", "duration_days": 14},
            {"name": "Content marketing via Twitter threads", "metric": "followers_gained", "duration_days": 30},
        ],
    },
    "marketing": {
        "summary": "Content marketing and community-led growth dominate early-stage acquisition. SEO has 6-12 month lag; paid ads burn cash pre-PMF. Focus on founder networks and word-of-mouth.",
        "competitors": [
            {"name": "HubSpot Blog", "stage": "enterprise", "weakness": "Generic, high competition keywords"},
            {"name": "Beehiiv newsletters", "stage": "growth", "weakness": "Requires large audience first"},
            {"name": "Substack", "stage": "growth", "weakness": "Discovery is limited"},
        ],
        "audience": {
            "primary": "Early adopters in founder and startup communities",
            "pain_points": ["Finding PMF quickly", "Limited budget for paid acquisition", "No brand recognition"],
            "willingness_to_pay": "Free trials → $49-$299/mo conversion",
            "acquisition_channel": "Twitter/X, LinkedIn, Indie Hackers, YC forums",
        },
        "opportunities": [
            "Build-in-public content generates authentic audience",
            "Short-form video on LinkedIn outperforms text posts 3x",
            "Community sponsorships often cheaper than Google Ads CPM",
        ],
        "risks": [
            "Algorithm changes can kill organic reach overnight",
            "Content production is time-intensive at small team size",
            "Mistarget audience = high CAC with low LTV",
        ],
        "experiments": [
            {"name": "Twitter/X thread series", "metric": "click_through_rate", "duration_days": 14},
            {"name": "LinkedIn thought leadership posts", "metric": "profile_views", "duration_days": 21},
            {"name": "Indie Hackers product showcase", "metric": "upvotes_and_referrals", "duration_days": 7},
        ],
    },
    "sales": {
        "summary": "Founder-led sales is most effective pre-$1M ARR. Direct outreach converts 5-15x better than inbound at early stage. Personalization and social proof are key conversion levers.",
        "competitors": [
            {"name": "Outreach.io", "stage": "enterprise", "weakness": "Complex, expensive ($100+/seat)"},
            {"name": "Apollo.io", "stage": "growth", "weakness": "High spam risk, data quality issues"},
            {"name": "Lemlist", "stage": "growth", "weakness": "Steep learning curve"},
        ],
        "audience": {
            "primary": "B2B buyers: CTOs, VPs of Product, operations leaders",
            "pain_points": ["Too many cold emails", "Irrelevant pitches", "Long evaluation cycles"],
            "willingness_to_pay": "$500-$2000/mo for proven ROI",
            "acquisition_channel": "LinkedIn, email, warm intros, conference networking",
        },
        "opportunities": [
            "Personalized video outreach (Loom) achieves 3x reply rate vs text email",
            "Focus on trigger events (funding rounds, job changes, product launches)",
            "Case studies from early customers dramatically reduce sales cycles",
        ],
        "risks": [
            "Spam filters increasingly block cold email at scale",
            "Founder time is the bottleneck — can't scale without SDR",
            "Churn risk if customers bought based on founder relationship alone",
        ],
        "experiments": [
            {"name": "Personalized video outreach to 20 leads", "metric": "meeting_rate", "duration_days": 7},
            {"name": "LinkedIn DM warm intro sequence", "metric": "reply_rate", "duration_days": 14},
            {"name": "Free audit offer to cold prospects", "metric": "conversion_to_paid", "duration_days": 21},
        ],
    },
    "ops": {
        "summary": "Operational efficiency compounds over time. The biggest leverage for early startups is automating data collection, standardizing customer feedback loops, and preventing metric blind spots.",
        "competitors": [
            {"name": "Mixpanel", "stage": "growth", "weakness": "Expensive at scale, complex setup"},
            {"name": "Amplitude", "stage": "enterprise", "weakness": "Overkill for early stage"},
            {"name": "PostHog", "stage": "growth", "weakness": "Self-hosted complexity"},
        ],
        "audience": {
            "primary": "Founder + first ops hire managing growth metrics",
            "pain_points": ["Data scattered across tools", "No single source of truth", "Reactive vs proactive"],
            "willingness_to_pay": "$49-$199/mo for ops clarity",
            "acquisition_channel": "Founder communities, YC network, ops job boards",
        },
        "opportunities": [
            "Automate weekly metrics report to save 3+ hours/week",
            "NPS + churn prediction from usage patterns",
            "Unit economics dashboard (CAC, LTV, payback period) visibility",
        ],
        "risks": [
            "Premature optimization before PMF wastes engineering cycles",
            "Over-instrumentation causes data overload and analysis paralysis",
            "GDPR/privacy compliance complexity for EU customers",
        ],
        "experiments": [
            {"name": "Automated weekly KPI digest", "metric": "time_saved_per_week", "duration_days": 14},
            {"name": "Churn alert system at 30-day inactivity", "metric": "churn_reduction_rate", "duration_days": 30},
            {"name": "CAC/LTV dashboard for investor updates", "metric": "fundraising_efficiency", "duration_days": 21},
        ],
    },
}


def _get_template(topic: str) -> dict[str, Any]:
    """Return the best matching research template for a topic."""
    topic_lower = topic.lower()
    for key in ("product", "marketing", "sales", "ops"):
        if key in topic_lower:
            return _RESEARCH_TEMPLATES[key]
    return _RESEARCH_TEMPLATES["product"]


def _enrich_summary_with_live(topic: str, product_name: str) -> tuple[str, list[dict]]:
    """
    Run a live web search for the topic and return (summary_prefix, citations).

    Falls back gracefully — callers always receive a string even on failure.
    """
    query = f"{product_name} {topic} market research 2024"
    response = live_research.search(query)
    citations: list[dict] = []
    if not response.ok:
        logger.debug("[research_tool] live search unavailable: %s", response.error)
        return "", citations

    snippet_lines = []
    for i, r in enumerate(response.results[:5], 1):
        if r.snippet:
            snippet_lines.append(f"{r.snippet.strip()}")
        citations.append({"index": i, "title": r.title, "url": r.url})

    live_summary = " ".join(snippet_lines)[:600] if snippet_lines else ""
    return live_summary, citations


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------

class ResearchToolInput(BaseModel):
    topic: str = Field(description="Research topic (market, domain, or product area to research).")
    product_name: str = Field(default="CEOClaw MVP", description="Product name for context.")
    run_id: str = Field(default="", description="Current run ID for artifact persistence.")
    cycle_count: int = Field(default=0, description="Current cycle number.")


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------

@tool("research_tool", args_schema=ResearchToolInput)
def research_tool(
    topic: str,
    product_name: str = "CEOClaw MVP",
    run_id: str = "",
    cycle_count: int = 0,
) -> str:
    """Conduct market research and produce a structured report.

    Uses deterministic templates as fallback when external research is unavailable.
    Persists the report to the research_reports table.

    Returns a JSON string with: summary, competitors, audience, opportunities, risks, experiments.
    """
    template = _get_template(topic)

    # Attempt live web research; enrich summary if available
    live_summary, citations = _enrich_summary_with_live(topic, product_name)
    summary = (live_summary + " " + template["summary"]).strip() if live_summary else template["summary"]
    source = "live+template" if citations else "template"

    report_id = None
    if run_id:
        try:
            report_id = persist_research_report(
                run_id=run_id,
                cycle_count=cycle_count,
                topic=topic,
                product_name=product_name,
                summary=summary,
                competitors=template["competitors"],
                audience=template["audience"],
                opportunities=template["opportunities"],
                risks=template["risks"],
                experiments=template["experiments"],
            )
            persist_artifact(
                run_id=run_id,
                cycle_count=cycle_count,
                node_name="marketing_executor",
                artifact_type="research_report",
                content_summary=f"topic={topic} source={source} competitors={len(template['competitors'])} opportunities={len(template['opportunities'])}",
            )
        except Exception:
            pass  # Don't fail the tool on persistence errors

    return json.dumps({
        "status": "success",
        "report_id": report_id,
        "topic": topic,
        "product_name": product_name,
        "source": source,
        "citations": citations,
        "summary": summary,
        "competitors": template["competitors"],
        "audience": template["audience"],
        "opportunities": template["opportunities"],
        "risks": template["risks"],
        "experiments": template["experiments"],
    })
