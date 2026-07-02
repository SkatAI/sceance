"""Centralized application settings.

One `Settings` object holds the environment-derived configuration that used to
live as import-time module globals across `config`, `auth`, `supabase_admin`,
and `recorder`. Handlers and services read it via `get_settings()` at call time,
so values aren't frozen at import and tests can override the whole object in one
place (`set_settings`) or patch a single attribute on `get_settings()`.

Env var names and parsing are unchanged from the previous per-module globals.
Provider API keys (OpenAI/Anthropic/Groq/Cartesia/Deepgram/Gradium) are not here
yet — they're read inside the bot provider factories and move in with the
factory refactor (Tasks 4/11).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_SERVER_DIR = Path(__file__).parent
_DEFAULT_STATIC_DIR = _SERVER_DIR / "static"
_DEFAULT_PERSONAS_DIR = _SERVER_DIR.parent / "personas"


@dataclass
class Settings:
    # Daily / session limits
    daily_api_key: str = ""
    max_sessions: int = 5
    # When true, an unrecognized email is auto-created on sign-in (local/dev).
    # When false (deployed), unknown emails are rejected as invite-only.
    open_signup: bool = False
    # Where the server runs: 'local' (dev .env) or 'online' (deployed secret);
    # 'unknown' when unset. Recorded on each session row.
    deploy_env: str = "unknown"
    # Supabase
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_jwt_secret: str = ""
    supabase_service_role_key: str = ""
    supabase_db_url: str = ""
    supabase_pool_max: int = 8
    # Provider API keys (None when unset, matching the prior os.getenv behavior).
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    groq_api_key: str | None = None
    openrouter_api_key: str | None = None
    cartesia_api_key: str | None = None
    deepgram_api_key: str | None = None
    gradium_api_key: str | None = None
    # Paths
    static_dir: Path = _DEFAULT_STATIC_DIR
    personas_dir: Path = _DEFAULT_PERSONAS_DIR

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv(override=True)
        return cls(
            daily_api_key=os.getenv("DAILY_API_KEY", ""),
            max_sessions=int(os.getenv("MAX_SESSIONS", "5")),
            open_signup=os.getenv("OPEN_SIGNUP", "").strip().lower() in ("1", "true", "yes"),
            deploy_env=os.getenv("DEPLOY_ENV", "unknown").strip().lower() or "unknown",
            supabase_url=os.getenv("SUPABASE_URL", "").rstrip("/"),
            supabase_anon_key=os.getenv("SUPABASE_KEY", ""),
            supabase_jwt_secret=os.getenv("SUPABASE_JWT_SECRET", "").strip(),
            supabase_service_role_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip(),
            supabase_db_url=os.getenv("SUPABASE_DB_URL", "").strip(),
            supabase_pool_max=int(os.getenv("SUPABASE_POOL_MAX", "8")),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            groq_api_key=os.getenv("GROQ_API_KEY"),
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY"),
            cartesia_api_key=os.getenv("CARTESIA_API_KEY"),
            deepgram_api_key=os.getenv("DEEPGRAM_API_KEY"),
            gradium_api_key=os.getenv("GRADIUM_API_KEY"),
        )


_settings: Settings | None = None


def get_settings() -> Settings:
    """The process-wide settings, built lazily from the environment on first use."""
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings


def set_settings(settings: Settings | None) -> None:
    """Override the settings singleton, or reset it (None) to re-read env next call.

    Intended for tests: override the whole object, or patch one attribute on the
    instance returned by `get_settings()`.
    """
    global _settings
    _settings = settings
