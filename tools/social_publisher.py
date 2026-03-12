"""
social_publisher – LangChain tool.

Unified facade for publishing social content.  Routes to platform-specific
adapters (X, Instagram) and enforces autonomy mode policies:

  A_AUTONOMOUS   — publish if credentials exist, else create draft artifact
  B_HUMAN_APPROVAL — create pending_approval before publishing; draft artifact
  C_ASSISTED     — same as B_HUMAN_APPROVAL (wait for user selection)
  D_DRY_RUN      — never publish; always create draft artifact

Always returns a structured JSON result.  Never silently fails.
"""

import json
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from data.database import (
    create_pending_approval,
    persist_artifact,
    persist_social_post,
    utc_now,
)

# Autonomy mode constants
AUTONOMOUS = "A_AUTONOMOUS"
HUMAN_APPROVAL = "B_HUMAN_APPROVAL"
ASSISTED = "C_ASSISTED"
DRY_RUN = "D_DRY_RUN"

_MODES_REQUIRING_APPROVAL = {HUMAN_APPROVAL, ASSISTED}
_MODES_NO_PUBLISH = {DRY_RUN}


class SocialPublisherInput(BaseModel):
    platform: str = Field(
        description="Target platform: 'x' or 'instagram'.",
        default="x",
    )
    content: str = Field(description="Content/caption to publish.")
    autonomy_mode: str = Field(
        default=AUTONOMOUS,
        description="Run autonomy mode (A_AUTONOMOUS | B_HUMAN_APPROVAL | C_ASSISTED | D_DRY_RUN).",
    )
    run_id: str = Field(default="", description="Current run ID for persistence.")
    cycle_count: int = Field(default=0, description="Current cycle number.")


@tool("social_publisher", args_schema=SocialPublisherInput)
def social_publisher_tool(
    platform: str = "x",
    content: str = "",
    autonomy_mode: str = AUTONOMOUS,
    run_id: str = "",
    cycle_count: int = 0,
) -> str:
    """Publish or draft social content with autonomy mode policy enforcement.

    Returns a JSON string with: platform, status, content, post_id, approval_id, detail.
    """
    if not content:
        return json.dumps({
            "platform": platform,
            "status": "failed",
            "error_detail": "content is empty",
        })

    platform = platform.lower()
    result: dict[str, Any] = {
        "platform": platform,
        "content": content,
        "autonomy_mode": autonomy_mode,
    }

    # --- D_DRY_RUN: always draft, no side effects ---
    if autonomy_mode in _MODES_NO_PUBLISH:
        db_id = _save_post(run_id, cycle_count, platform, content, "drafted")
        result.update({
            "status": "drafted",
            "db_id": db_id,
            "detail": f"Dry-run mode: content saved as draft, not published",
        })
        _save_artifact(run_id, cycle_count, platform, "drafted")
        return json.dumps(result)

    # --- B_HUMAN_APPROVAL / C_ASSISTED: queue for approval ---
    if autonomy_mode in _MODES_REQUIRING_APPROVAL:
        db_id = _save_post(run_id, cycle_count, platform, content, "pending_approval")
        approval_id = None
        if run_id:
            approval_id = create_pending_approval(
                run_id=run_id,
                approval_type="social_publish",
                payload={
                    "platform": platform,
                    "content": content,
                    "social_post_db_id": db_id,
                    "cycle_count": cycle_count,
                },
            )
        result.update({
            "status": "pending_approval",
            "db_id": db_id,
            "approval_id": approval_id,
            "detail": f"Waiting for human approval before publishing to {platform}",
        })
        _save_artifact(run_id, cycle_count, platform, "pending_approval")
        return json.dumps(result)

    # --- A_AUTONOMOUS: attempt publish ---
    publish_result = _route_publish(platform, content)
    db_id = _save_post(
        run_id, cycle_count, platform, content,
        publish_result.status, publish_result.post_id, publish_result.error_detail,
    )
    result.update({
        "status": publish_result.status,
        "db_id": db_id,
        "post_id": publish_result.post_id,
        "error_detail": publish_result.error_detail,
        "metadata": publish_result.metadata,
    })
    _save_artifact(run_id, cycle_count, platform, publish_result.status)
    return json.dumps(result)


def _route_publish(platform: str, content: str):
    """Route to the correct platform publisher."""
    if platform == "x":
        from tools.social_publishers.x_publisher import publish
        return publish(content)
    elif platform == "instagram":
        from tools.social_publishers.instagram_publisher import publish
        return publish(content)
    else:
        # Unknown platform — create a draft without calling any API
        from tools.social_publishers.x_publisher import PublishResult
        return PublishResult(
            platform=platform,
            status="drafted",
            content=content,
            error_detail=f"Unknown platform '{platform}'; saved as draft",
            metadata={"reason": "unknown_platform"},
        )


def _save_post(
    run_id: str,
    cycle_count: int,
    platform: str,
    content: str,
    status: str,
    post_id: str | None = None,
    error_detail: str | None = None,
) -> int | None:
    if not run_id:
        return None
    try:
        return persist_social_post(
            run_id=run_id,
            cycle_count=cycle_count,
            platform=platform,
            content=content,
            status=status,
            post_id=post_id,
            error_detail=error_detail,
        )
    except Exception:
        return None


def _save_artifact(
    run_id: str,
    cycle_count: int,
    platform: str,
    status: str,
) -> None:
    if not run_id:
        return
    try:
        persist_artifact(
            run_id=run_id,
            cycle_count=cycle_count,
            node_name="marketing_executor",
            artifact_type=f"social_{status}",
            content_summary=f"platform={platform} status={status}",
        )
    except Exception:
        pass
