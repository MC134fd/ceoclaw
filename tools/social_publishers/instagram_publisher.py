"""
Instagram publisher adapter.

Handles publishing content to Instagram via the Graph API.
Falls back to draft status when credentials are absent.

Never silently fails — always returns a structured PublishResult.
"""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PublishResult:
    """Structured result from a publish attempt."""
    platform: str = "instagram"
    status: str = "drafted"          # drafted | pending_approval | posted | failed
    content: str = ""
    post_id: Optional[str] = None
    error_detail: Optional[str] = None
    metadata: dict = field(default_factory=dict)


# Instagram caption limit
_MAX_CAPTION_LEN = 2200


def publish(content: str, dry_run: bool = False) -> PublishResult:
    """Attempt to publish a caption to Instagram.

    Args:
        content:  Caption text (≤2200 characters enforced).
        dry_run:  If True, always returns 'drafted' — never makes API call.

    Returns:
        PublishResult with status and metadata.
    """
    content = content[:_MAX_CAPTION_LEN]

    if dry_run:
        return PublishResult(
            platform="instagram",
            status="drafted",
            content=content,
            metadata={"reason": "dry_run_mode", "char_count": len(content)},
        )

    access_token = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
    ig_user_id = os.environ.get("INSTAGRAM_USER_ID")

    if not access_token or not ig_user_id:
        return PublishResult(
            platform="instagram",
            status="drafted",
            content=content,
            metadata={
                "reason": "no_credentials",
                "required_env": ["INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_USER_ID"],
                "char_count": len(content),
            },
        )

    # Live path — Instagram Graph API requires a two-step publish
    try:
        import httpx  # type: ignore

        # Step 1: Create media container
        create_resp = httpx.post(
            f"https://graph.instagram.com/{ig_user_id}/media",
            params={
                "caption": content,
                "image_url": "",  # In production, a hosted image URL would be required
                "access_token": access_token,
            },
            timeout=15,
        )
        create_resp.raise_for_status()
        container_id = create_resp.json().get("id")

        if not container_id:
            raise ValueError("No container ID returned from Instagram API")

        # Step 2: Publish container
        pub_resp = httpx.post(
            f"https://graph.instagram.com/{ig_user_id}/media_publish",
            params={
                "creation_id": container_id,
                "access_token": access_token,
            },
            timeout=15,
        )
        pub_resp.raise_for_status()
        return PublishResult(
            platform="instagram",
            status="posted",
            content=content,
            post_id=pub_resp.json().get("id"),
            metadata={"char_count": len(content)},
        )
    except Exception as exc:
        return PublishResult(
            platform="instagram",
            status="failed",
            content=content,
            error_detail=f"{type(exc).__name__}: {exc}",
            metadata={"char_count": len(content)},
        )
