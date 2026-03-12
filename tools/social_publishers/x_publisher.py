"""
X (Twitter) publisher adapter.

Handles publishing content to X/Twitter.  When live credentials are absent,
falls back to a draft status with full structured detail.

Never silently fails — always returns a structured PublishResult.
"""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PublishResult:
    """Structured result from a publish attempt."""
    platform: str = "x"
    status: str = "drafted"          # drafted | pending_approval | posted | failed
    content: str = ""
    post_id: Optional[str] = None
    error_detail: Optional[str] = None
    metadata: dict = field(default_factory=dict)


def publish(content: str, dry_run: bool = False) -> PublishResult:
    """Attempt to publish content to X/Twitter.

    Args:
        content:  The text to post (≤280 characters enforced).
        dry_run:  If True, always returns 'drafted' — never makes API call.

    Returns:
        PublishResult with status and metadata.
    """
    content = content[:280]  # Enforce X character limit

    if dry_run:
        return PublishResult(
            platform="x",
            status="drafted",
            content=content,
            metadata={"reason": "dry_run_mode", "char_count": len(content)},
        )

    api_key = os.environ.get("X_API_KEY") or os.environ.get("TWITTER_API_KEY")
    bearer_token = os.environ.get("X_BEARER_TOKEN") or os.environ.get("TWITTER_BEARER_TOKEN")

    if not api_key and not bearer_token:
        return PublishResult(
            platform="x",
            status="drafted",
            content=content,
            metadata={
                "reason": "no_credentials",
                "required_env": ["X_API_KEY", "X_BEARER_TOKEN"],
                "char_count": len(content),
            },
        )

    # Live path — attempt actual post
    try:
        import httpx  # type: ignore

        response = httpx.post(
            "https://api.twitter.com/2/tweets",
            headers={
                "Authorization": f"Bearer {bearer_token}",
                "Content-Type": "application/json",
            },
            json={"text": content},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        return PublishResult(
            platform="x",
            status="posted",
            content=content,
            post_id=data.get("data", {}).get("id"),
            metadata={"response": data, "char_count": len(content)},
        )
    except Exception as exc:
        return PublishResult(
            platform="x",
            status="failed",
            content=content,
            error_detail=f"{type(exc).__name__}: {exc}",
            metadata={"char_count": len(content)},
        )
