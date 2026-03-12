"""
CEOClaw application settings.

Loads configuration from environment variables with sensible defaults.
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

logger = logging.getLogger(__name__)


def _int_env(key: str, default: int) -> int:
    raw = os.getenv(key, str(default))
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid value for %s=%r — using default %d", key, raw, default)
        return default


def _float_env(key: str, default: float) -> float:
    raw = os.getenv(key, str(default))
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid value for %s=%r — using default %s", key, raw, default)
        return default


def _bool_env(key: str, default: bool) -> bool:
    raw = os.getenv(key, str(default)).lower()
    return raw in ("true", "1", "yes")


class Settings:
    """Application configuration resolved from environment variables."""

    def __init__(self) -> None:
        self.reload()

    def reload(self) -> None:
        """Reload environment-backed settings from .env and process env."""
        load_dotenv(_PROJECT_ROOT / ".env", override=True)

        # ── App ────────────────────────────────────────────────────────
        self.app_name = os.getenv("CEOCLAW_APP_NAME", "CEOClaw").strip()
        self.environment = os.getenv("CEOCLAW_ENV", "development").strip()
        self.database_path = os.getenv("CEOCLAW_DATABASE_PATH", "data/ceoclaw.db").strip()
        self.log_level = os.getenv("CEOCLAW_LOG_LEVEL", "INFO").strip()
        self.default_goal_mrr = _float_env("CEOCLAW_GOAL_MRR", 100.0)
        self.default_max_cycles = _int_env("CEOCLAW_MAX_CYCLES", 20)

        # ── FLock / OpenClaw model ─────────────────────────────────────
        self.flock_endpoint = os.getenv("FLOCK_ENDPOINT", "").strip()
        self.flock_api_key = os.getenv("FLOCK_API_KEY", "").strip()
        self.flock_model = os.getenv("FLOCK_MODEL", "flock-default").strip()
        self.flock_timeout = _int_env("FLOCK_TIMEOUT", 30)
        self.flock_max_retries = _int_env("FLOCK_MAX_RETRIES", 3)
        self.flock_mock_mode = _bool_env("FLOCK_MOCK_MODE", False)
        self.flock_auth_strategy = os.getenv("FLOCK_AUTH_STRATEGY", "both").lower().strip()

        if not self.flock_mock_mode and not self.flock_endpoint:
            logger.warning(
                "[Settings] FLOCK_ENDPOINT is not set and FLOCK_MOCK_MODE=false. "
                "Live API calls will fail. Set FLOCK_ENDPOINT or FLOCK_MOCK_MODE=true."
            )

        # ── Web Research ───────────────────────────────────────────────
        self.web_research_enabled = _bool_env("WEB_RESEARCH_ENABLED", True)
        self.web_research_provider_order = [
            p.strip()
            for p in os.getenv("WEB_RESEARCH_PROVIDER_ORDER", "brave,google").split(",")
            if p.strip()
        ]
        self.web_research_max_results = _int_env("WEB_RESEARCH_MAX_RESULTS", 8)
        self.web_research_timeout = _int_env("WEB_RESEARCH_TIMEOUT", 12)

        # Brave Search
        self.brave_api_key = os.getenv("BRAVE_SEARCH_API_KEY", "").strip()

        # Google Custom Search
        self.google_cse_api_key = os.getenv("GOOGLE_CSE_API_KEY", "").strip()
        self.google_cse_cx = os.getenv("GOOGLE_CSE_CX", "").strip()

        # ── Memory backend ─────────────────────────────────────────────
        self.memory_backend = os.getenv("MEMORY_BACKEND", "sqlite").lower().strip()

        # Supabase
        self.supabase_url = os.getenv("SUPABASE_URL", "").strip()
        self.supabase_service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        self.supabase_schema = os.getenv("SUPABASE_SCHEMA", "public").strip()

        # ── OpenAI fallback provider ───────────────────────────────────
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
        self.openai_endpoint = os.getenv(
            "OPENAI_ENDPOINT", "https://api.openai.com/v1/chat/completions"
        ).strip()
        raw_mode = os.getenv("OPENAI_API_MODE", "auto").lower().strip()
        self.openai_api_mode = raw_mode if raw_mode in ("auto", "responses", "chat") else "auto"

        # ── Social publishing ──────────────────────────────────────────
        self.x_api_key = os.getenv("X_API_KEY", "").strip()
        self.x_bearer_token = os.getenv("X_BEARER_TOKEN", "").strip()
        self.instagram_access_token = os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip()
        self.instagram_user_id = os.getenv("INSTAGRAM_USER_ID", "").strip()

        # ── Email outreach ─────────────────────────────────────────────
        self.outreach_email_provider = os.getenv("OUTREACH_EMAIL_PROVIDER", "none").lower().strip()
        self.sendgrid_api_key = os.getenv("SENDGRID_API_KEY", "").strip()
        self.resend_api_key = os.getenv("RESEND_API_KEY", "").strip()

    def resolve_db_path(self) -> Path:
        path = Path(self.database_path)
        if path.is_absolute():
            return path
        return (_PROJECT_ROOT / path).resolve()

    def resolve_websites_dir(self) -> Path:
        return (_PROJECT_ROOT / "data" / "websites").resolve()

    @property
    def has_brave(self) -> bool:
        return bool(self.brave_api_key)

    @property
    def has_google_cse(self) -> bool:
        return bool(self.google_cse_api_key and self.google_cse_cx)

    @property
    def has_supabase(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)

    @property
    def live_research_available(self) -> bool:
        return self.web_research_enabled and (self.has_brave or self.has_google_cse)


# Module-level singleton
settings = Settings()
