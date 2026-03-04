"""
CEOClaw application settings.

Loads configuration from environment variables with sensible defaults.
Extended for LangGraph / FLock model layer.
"""

import os
from pathlib import Path


# Project root: two levels up from this file (ceoclaw/config/settings.py -> ceoclaw/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


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
        self.flock_endpoint: str = os.getenv(
            "FLOCK_ENDPOINT", "http://localhost:8080/v1/chat/completions"
        )
        self.flock_api_key: str = os.getenv("FLOCK_API_KEY", "")
        self.flock_timeout: int = int(os.getenv("FLOCK_TIMEOUT", "30"))
        self.flock_max_retries: int = int(os.getenv("FLOCK_MAX_RETRIES", "3"))
        self.flock_mock_mode: bool = (
            os.getenv("FLOCK_MOCK_MODE", "false").lower() == "true"
        )

        # Graph runtime defaults
        self.default_goal_mrr: float = float(
            os.getenv("CEOCLAW_GOAL_MRR", "100.0")
        )
        self.default_max_cycles: int = int(
            os.getenv("CEOCLAW_MAX_CYCLES", "20")
        )

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
