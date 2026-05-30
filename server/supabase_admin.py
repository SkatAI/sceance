"""Passwordless login via Supabase's GoTrue admin API.

The landing page lets a user sign in with just an email — no password, and
(critically, on the free plan's tight email quota) no magic-link email sent.

To pull that off without emailing, the server holds the Supabase *service-role*
secret and talks to the GoTrue admin REST endpoints directly:

  1. `admin/generate_link` mints a one-time `hashed_token` for an existing user
     WITHOUT delivering an email. The browser redeems it via
     `supabase.auth.verifyOtp({ token_hash, type: 'magiclink' })` to get a real
     session — same JWTs the rest of the app already verifies.
  2. `admin/users` creates a pre-confirmed user when open signup is allowed.

Existence is checked straight against `auth.users` through the existing asyncpg
pool (the SUPABASE_DB_URL role owns the auth schema), so it's deterministic and
independent of GoTrue's autoconfirm/signup settings.

Requires SUPABASE_SERVICE_ROLE_KEY in the environment. This key bypasses RLS and
must never be exposed to the browser — it lives only here, server-side.
"""

from __future__ import annotations

import os

import asyncpg
import httpx
from fastapi import HTTPException
from loguru import logger

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
_AUTH_BASE = f"{SUPABASE_URL}/auth/v1" if SUPABASE_URL else ""


def admin_configured() -> bool:
    return bool(_AUTH_BASE and _SERVICE_ROLE_KEY)


def _admin_headers() -> dict[str, str]:
    return {
        "apikey": _SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }


async def user_exists(pool: asyncpg.Pool, email: str) -> bool:
    """True if an auth.users row matches this email (case-insensitive)."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM auth.users WHERE lower(email) = lower($1) LIMIT 1",
            email,
        )
    return row is not None


async def create_user(client: httpx.AsyncClient, email: str) -> None:
    """Create a pre-confirmed, passwordless auth.users row.

    `email_confirm: true` skips the confirmation email; the profiles trigger
    fills in a username from the email local-part automatically.
    """
    r = await client.post(
        f"{_AUTH_BASE}/admin/users",
        headers=_admin_headers(),
        json={"email": email, "email_confirm": True},
    )
    if r.status_code >= 400:
        logger.error(f"admin/users create failed ({r.status_code}): {r.text}")
        raise HTTPException(status_code=502, detail="signup_failed")


async def generate_magiclink_token(client: httpx.AsyncClient, email: str) -> str:
    """Mint a one-time login token for an existing user (no email sent).

    Returns the `hashed_token` the browser feeds to verifyOtp. GoTrue versions
    differ on where they put it (top-level vs. nested under `properties`), so we
    check both.
    """
    r = await client.post(
        f"{_AUTH_BASE}/admin/generate_link",
        headers=_admin_headers(),
        json={"type": "magiclink", "email": email},
    )
    if r.status_code >= 400:
        logger.error(f"admin/generate_link failed ({r.status_code}): {r.text}")
        raise HTTPException(status_code=502, detail="login_link_failed")
    data = r.json()
    token = data.get("hashed_token") or data.get("properties", {}).get("hashed_token")
    if not token:
        logger.error(f"generate_link returned no hashed_token: {data}")
        raise HTTPException(status_code=502, detail="login_link_failed")
    return token
