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
        self.flock_auth_strategy = os.getenv("FLOCK_AUTH_STRATEGY", "both").lower().strip()

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
        self.supabase_anon_key = os.getenv("SUPABASE_ANON_KEY", "").strip()
        self.supabase_jwt_secret = os.getenv("SUPABASE_JWT_SECRET", "").strip()
        self.supabase_schema = os.getenv("SUPABASE_SCHEMA", "public").strip()

        # ── Auth + Credits feature flags ──────────────────────────────
        # AUTH_REQUIRED=true → builder endpoints require a valid Supabase JWT
        self.auth_required = _bool_env("AUTH_REQUIRED", False)
        # CREDITS_ENFORCED=true → generation is blocked when balance < cost
        self.credits_enforced = _bool_env("CREDITS_ENFORCED", False)
        # Credits granted to new free-tier users on sign-up
        self.free_tier_credits = _int_env("FREE_TIER_CREDITS", 10)

        # ── Builder repair loop (Phase 4) ─────────────────────────────
        # Default False: conservative until integration tests confirm safety.
        # Set True + BUILDER_REPAIR_MAX_ROUNDS=1 for a single-pass trial.
        self.builder_repair_enabled = _bool_env("BUILDER_REPAIR_ENABLED", False)
        # Hard cap on repair iterations per pipeline run (1–2 recommended).
        self.builder_repair_max_rounds = _int_env("BUILDER_REPAIR_MAX_ROUNDS", 2)
        # Max FileChange entries patched per round (1–2 recommended).
        self.builder_repair_max_files_per_round = _int_env("BUILDER_REPAIR_MAX_FILES_PER_ROUND", 2)

        # ── Generation plan-aware ordering ────────────────────────────
        # When True, the legacy per-file LLM loop uses scaffold-derived
        # ordering from the BuildPlan instead of brand_spec.pages.
        # Set to false to restore pre-Phase-3 behavior exactly.
        self.plan_aware_generation = _bool_env("PLAN_AWARE_GENERATION", True)

        # ── OpenAI primary provider ────────────────────────────────────
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
        self.openai_endpoint = os.getenv(
            "OPENAI_ENDPOINT", "https://api.openai.com/v1/chat/completions"
        ).strip()
        raw_mode = os.getenv("OPENAI_API_MODE", "auto").lower().strip()
        self.openai_api_mode = raw_mode if raw_mode in ("auto", "responses", "chat") else "auto"

        if self.openai_api_key:
            logger.info(
                "[Settings] OpenAI API key detected (model=%s, mode=%s).",
                self.openai_model,
                self.openai_api_mode,
            )

        # ── Image generation (DALL-E) ─────────────────────────────────
        self.image_generation_enabled = _bool_env("IMAGE_GENERATION_ENABLED", True)
        self.dalle_model = os.getenv("DALLE_MODEL", "dall-e-2").strip()
        self.dalle_hero_size = os.getenv("DALLE_HERO_SIZE", "1024x1024").strip()
        self.dalle_icon_size = os.getenv("DALLE_ICON_SIZE", "256x256").strip()
        self.dalle_timeout = _int_env("DALLE_TIMEOUT", 25)

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
    def has_supabase_auth(self) -> bool:
        return bool(self.supabase_url and self.supabase_jwt_secret)

    @property
    def live_research_available(self) -> bool:
        return self.web_research_enabled and (self.has_brave or self.has_google_cse)


# Module-level singleton
settings = Settings()
