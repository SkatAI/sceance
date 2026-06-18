"""Authentication routes: passwordless email login and current-user lookup.

`from auth import ...` is an absolute import — it resolves to the top-level
`auth.py` (JWT verification), not this module.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import CurrentUser, get_current_user
from deps import get_pool
from supabase_admin import (
    add_to_waitlist,
    admin_configured,
    create_user,
    generate_magiclink_token,
    redeem_invite_code,
    user_exists,
)

router = APIRouter()


class LoginBody(BaseModel):
    email: str
    invite_code: str | None = None


@router.post("/api/auth/login")
async def api_auth_login(body: LoginBody, pool=Depends(get_pool)):
    """Passwordless sign-in by email — no magic-link email is sent.

    Returns a one-time `token_hash` the browser redeems with verifyOtp.

    New emails are gated by an invite code: a valid code creates the account and
    logs in immediately; no code adds the email to the beta waitlist (202); a
    bad/expired/exhausted code is rejected (400) so the user can retry.
    """
    email = (body.email or "").strip().lower()
    if "@" not in email or len(email) < 3:
        raise HTTPException(status_code=400, detail="invalid_email")
    if not admin_configured():
        raise HTTPException(status_code=500, detail="auth_admin_not_configured")

    if not await user_exists(pool, email):
        if not (body.invite_code or "").strip():
            await add_to_waitlist(pool, email)
            raise HTTPException(status_code=202, detail="waitlisted")
        if not await redeem_invite_code(pool, body.invite_code):
            raise HTTPException(status_code=400, detail="invalid_invite")
        async with httpx.AsyncClient(timeout=15.0) as client:
            await create_user(client, email)
            return {
                "token_hash": await generate_magiclink_token(client, email),
                "type": "magiclink",
            }

    async with httpx.AsyncClient(timeout=15.0) as client:
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
