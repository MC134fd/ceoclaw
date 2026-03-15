"""
CEOClaw JWT authentication — Supabase Google OAuth support.

Verifies Supabase-issued JWTs (HS256, signed with SUPABASE_JWT_SECRET).
The dependency `get_current_user` is used in FastAPI endpoint signatures via
`Depends(get_current_user)`.

Feature flag: when AUTH_REQUIRED=false (default), all endpoints receive
ANONYMOUS_USER without performing any token validation — preserving current
anonymous builder behaviour during rollout.
"""

import logging
from typing import Any, Optional

import jwt as _jwt  # PyJWT
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


def _verify_supabase_jwt(token: str) -> dict[str, Any]:
    """Decode and verify a Supabase JWT.

    Supabase signs user JWTs with HS256 using the JWT secret found in
    Supabase Dashboard → Settings → API → JWT Settings.

    Raises HTTPException(401) on any validation failure.
    """
    jwt_secret = _settings_mod.settings.supabase_jwt_secret
    if not jwt_secret:
        raise HTTPException(
            status_code=401,
            detail="SUPABASE_JWT_SECRET not configured — cannot verify token",
        )

    try:
        payload = _jwt.decode(
            token,
            jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
            options={"require": ["sub", "exp"]},
        )
    except _jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except _jwt.InvalidAudienceError:
        raise HTTPException(status_code=401, detail="Token has invalid audience")
    except _jwt.InvalidTokenError as exc:
        logger.debug("JWT validation failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid token")

    return payload


def _extract_user_claims(payload: dict[str, Any]) -> dict[str, Any]:
    """Pull user info out of Supabase JWT claims."""
    user_metadata = payload.get("user_metadata") or {}
    app_metadata = payload.get("app_metadata") or {}

    # Google OAuth stores name / picture in user_metadata
    display_name = (
        user_metadata.get("full_name")
        or user_metadata.get("name")
        or (payload.get("email", "") or "").split("@")[0]
    )
    avatar_url = user_metadata.get("avatar_url") or user_metadata.get("picture")
    provider = app_metadata.get("provider", "google")

    return {
        "id": payload["sub"],
        "email": payload.get("email", ""),
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

    payload = _verify_supabase_jwt(credentials.credentials)
    claims = _extract_user_claims(payload)

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
