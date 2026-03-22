"""
CEOClaw JWT authentication — Supabase auth verification via REST API.

Verifies tokens by calling Supabase's /auth/v1/user endpoint directly,
so it works regardless of whether the project uses legacy HS256 or the
new RS256 JWT Signing Keys.

Feature flag: when AUTH_REQUIRED=false (default), all endpoints receive
ANONYMOUS_USER without performing any token validation.
"""

import logging
from typing import Any, Optional

import httpx
import config.settings as _settings_mod  # runtime lookup — avoids stale binding in tests
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from data.database import ensure_default_subscription_and_credits, upsert_user

logger = logging.getLogger(__name__)

# Returned by get_current_user when AUTH_REQUIRED=false
ANONYMOUS_USER: dict[str, Any] = {
    "id": "anonymous",
    "email": "anon@local",
    "display_name": "Anonymous",
    "avatar_url": None,
    "provider": "anonymous",
}

# HTTPBearer with auto_error=False returns None credentials instead of raising
# when no Authorization header is present.
_bearer_scheme = HTTPBearer(auto_error=False)


def _verify_supabase_token(token: str) -> dict[str, Any]:
    """Verify a Supabase access token by calling /auth/v1/user.

    This works with both legacy HS256 and new RS256 JWT Signing Keys.
    Raises HTTPException(401) on any validation failure.
    """
    supabase_url = _settings_mod.settings.supabase_url
    anon_key = _settings_mod.settings.supabase_anon_key

    if not supabase_url or not anon_key:
        raise HTTPException(
            status_code=401,
            detail="SUPABASE_URL / SUPABASE_ANON_KEY not configured on server",
        )

    try:
        resp = httpx.get(
            f"{supabase_url}/auth/v1/user",
            headers={
                "Authorization": f"Bearer {token}",
                "apikey": anon_key,
            },
            timeout=10,
        )
    except httpx.RequestError as exc:
        logger.warning("Supabase auth request failed: %s", exc)
        raise HTTPException(status_code=401, detail="Could not reach auth server")

    if resp.status_code == 401:
        raise HTTPException(status_code=401, detail="Token expired or invalid")
    if not resp.is_success:
        raise HTTPException(status_code=401, detail="Token verification failed")

    return resp.json()


def _extract_user_claims(user: dict[str, Any]) -> dict[str, Any]:
    """Pull user info out of Supabase /auth/v1/user response."""
    user_metadata = user.get("user_metadata") or {}
    app_metadata = user.get("app_metadata") or {}

    display_name = (
        user_metadata.get("full_name")
        or user_metadata.get("name")
        or (user.get("email", "") or "").split("@")[0]
    )
    avatar_url = user_metadata.get("avatar_url") or user_metadata.get("picture")
    provider = app_metadata.get("provider", "email")

    return {
        "id": user["id"],
        "email": user.get("email", ""),
        "display_name": display_name,
        "avatar_url": avatar_url,
        "provider": provider,
    }


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """FastAPI dependency: verify JWT, upsert local user, return user dict.

    Behaviour:
    - AUTH_REQUIRED=false → always returns ANONYMOUS_USER (no token needed).
    - AUTH_REQUIRED=true  → requires a valid Supabase Bearer token; raises 401
      if missing or invalid.
    """
    if not _settings_mod.settings.auth_required:
        return ANONYMOUS_USER

    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=401,
            detail="Authorization header required (Bearer <token>)",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_data = _verify_supabase_token(credentials.credentials)
    claims = _extract_user_claims(user_data)

    # Upsert the local user record and seed default credits on first login.
    try:
        upsert_user(
            user_id=claims["id"],
            email=claims["email"],
            display_name=claims.get("display_name"),
            avatar_url=claims.get("avatar_url"),
            provider=claims.get("provider", "google"),
        )
        ensure_default_subscription_and_credits(
            claims["id"],
            free_credits=_settings_mod.settings.free_tier_credits,
        )
    except Exception as exc:  # noqa: BLE001
        # Log but don't fail the request — DB upsert is best-effort on each call
        logger.warning("Failed to upsert user %s: %s", claims["id"][:8], exc)

    return claims


def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> Optional[dict[str, Any]]:
    """Like get_current_user but returns None instead of raising 401.

    Useful for endpoints that work both authenticated and anonymously.
    """
    if not _settings_mod.settings.auth_required:
        return None
    if credentials is None or not credentials.credentials:
        return None
    try:
        return get_current_user(credentials)
    except HTTPException:
        return None
