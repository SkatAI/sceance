"""Authentication routes: passwordless email login and current-user lookup.

`from auth import ...` is an absolute import — it resolves to the top-level
`auth.py` (JWT verification), not this module.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import config
from auth import CurrentUser, get_current_user
from deps import get_pool
from supabase_admin import (
    admin_configured,
    create_user,
    generate_magiclink_token,
    user_exists,
)

router = APIRouter()


class LoginBody(BaseModel):
    email: str


@router.post("/api/auth/login")
async def api_auth_login(body: LoginBody, pool=Depends(get_pool)):
    """Passwordless sign-in by email — no magic-link email is sent.

    Returns a one-time `token_hash` the browser redeems with verifyOtp. Unknown
    emails are auto-created when OPEN_SIGNUP is on, else rejected as invite-only.
    """
    email = (body.email or "").strip().lower()
    if "@" not in email or len(email) < 3:
        raise HTTPException(status_code=400, detail="invalid_email")
    if not admin_configured():
        raise HTTPException(status_code=500, detail="auth_admin_not_configured")

    exists = await user_exists(pool, email)
    async with httpx.AsyncClient(timeout=15.0) as client:
        if not exists:
            if not config.OPEN_SIGNUP:
                raise HTTPException(status_code=403, detail="invite_only")
            await create_user(client, email)
        token_hash = await generate_magiclink_token(client, email)

    return {"token_hash": token_hash, "type": "magiclink"}


@router.get("/api/me")
async def api_me(user: CurrentUser = Depends(get_current_user)):
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "is_admin": user.is_admin,
    }
