"""Shared configuration constants read from the environment.

Centralizes the env/path constants used across more than one route module (and
the app lifespan), so the router split doesn't force circular imports or
duplicated `os.getenv` reads. Handlers reference `config.X` at call time, which
keeps a single patch target for tests.

This is a deliberately minimal home — Task 3 of the refactoring plan replaces
these module-level constants with an override-able settings object and folds in
the auth/recorder/bot env reads. Until then, values are fixed at import time.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

DAILY_API_KEY = os.getenv("DAILY_API_KEY", "")
MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", "5"))
# When true, an unrecognized email is auto-created on sign-in (local/dev). When
# false (deployed), unknown emails are rejected as invite-only.
OPEN_SIGNUP = os.getenv("OPEN_SIGNUP", "").strip().lower() in ("1", "true", "yes")

STATIC_DIR = Path(__file__).parent / "static"
PERSONAS_DIR = Path(__file__).parent.parent / "personas"
