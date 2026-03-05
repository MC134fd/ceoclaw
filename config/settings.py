"""
CEOClaw application settings.

Loads configuration from environment variables with sensible defaults.
Extended for LangGraph / FLock model layer.
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

# Project root: two levels up from this file (ceoclaw/config/settings.py -> ceoclaw/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load .env from project root (no-op if file doesn't exist)
load_dotenv(_PROJECT_ROOT / ".env")

logger = logging.getLogger(__name__)


def _int_env(key: str, default: int) -> int:
    """Read an integer env var, warn and use default on bad value."""
    raw = os.getenv(key, str(default))
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid value for %s=%r — using default %d", key, raw, default)
        return default


def _float_env(key: str, default: float) -> float:
    """Read a float env var, warn and use default on bad value."""
    raw = os.getenv(key, str(default))
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid value for %s=%r — using default %s", key, raw, default)
        return default


class Settings:
    """Application configuration resolved from environment variables."""

    def __init__(self) -> None:
        self.app_name: str = os.getenv("CEOCLAW_APP_NAME", "CEOClaw")
        self.environment: str = os.getenv("CEOCLAW_ENV", "development")
        self.database_path: str = os.getenv(
            "CEOCLAW_DATABASE_PATH", "data/ceoclaw.db"
        )
        self.log_level: str = os.getenv("CEOCLAW_LOG_LEVEL", "INFO")

        # FLock model adapter
        self.flock_endpoint: str = os.getenv("FLOCK_ENDPOINT", "")
        self.flock_api_key: str = os.getenv("FLOCK_API_KEY", "")
        self.flock_model: str = os.getenv("FLOCK_MODEL", "flock-default")
        self.flock_timeout: int = _int_env("FLOCK_TIMEOUT", 30)
        self.flock_max_retries: int = _int_env("FLOCK_MAX_RETRIES", 3)
        self.flock_mock_mode: bool = (
            os.getenv("FLOCK_MOCK_MODE", "false").lower() == "true"
        )
        # Auth header strategy: "bearer" | "litellm" | "both"
        # "both"   — sends Authorization: Bearer AND x-litellm-api-key (max compat)
        # "bearer" — OpenAI-style only
        # "litellm"— LiteLLM/OpenClaw VPS-style only
        self.flock_auth_strategy: str = os.getenv("FLOCK_AUTH_STRATEGY", "both").lower()

        # Warn at construction time if live mode is requested but endpoint is missing
        if not self.flock_mock_mode and not self.flock_endpoint:
            logger.warning(
                "[Settings] FLOCK_ENDPOINT is not set and FLOCK_MOCK_MODE=false. "
                "Live API calls will fail immediately. Set FLOCK_ENDPOINT or "
                "FLOCK_MOCK_MODE=true."
            )

        # Graph runtime defaults
        self.default_goal_mrr: float = _float_env("CEOCLAW_GOAL_MRR", 100.0)
        self.default_max_cycles: int = _int_env("CEOCLAW_MAX_CYCLES", 20)

    def resolve_db_path(self) -> Path:
        """Return an absolute Path to the SQLite database file.

        If ``database_path`` is already absolute it is returned as-is;
        otherwise it is resolved relative to the project root.
        """
        path = Path(self.database_path)
        if path.is_absolute():
            return path
        return (_PROJECT_ROOT / path).resolve()

    def resolve_websites_dir(self) -> Path:
        """Return the absolute path to the generated websites directory."""
        return (_PROJECT_ROOT / "data" / "websites").resolve()


# Module-level singleton – import and use directly.
settings = Settings()
