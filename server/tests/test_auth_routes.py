from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from auth import CurrentUser
from routes import auth as auth_routes


def test_api_me_projects_current_user():
    user = CurrentUser(id="u1", email="a@example.com", username="alex", is_admin=True)

    assert asyncio.run(auth_routes.api_me(user)) == {
        "id": "u1",
        "email": "a@example.com",
        "username": "alex",
        "is_admin": True,
    }


def _patch_login(monkeypatch, *, exists, redeem=True, waitlist_added=True):
    """Stub the supabase_admin helpers the login route calls, recording activity."""
    calls = {"created": [], "waitlisted": [], "redeemed": []}

    async def fake_user_exists(pool, email):
        return exists

    async def fake_redeem(pool, code):
        calls["redeemed"].append(code)
        return redeem

    async def fake_waitlist(pool, email):
        calls["waitlisted"].append(email)
        return waitlist_added

    async def fake_create_user(client, email):
        calls["created"].append(email)

    async def fake_token(client, email):
        return "tok"

    monkeypatch.setattr(auth_routes, "admin_configured", lambda: True)
    monkeypatch.setattr(auth_routes, "user_exists", fake_user_exists)
    monkeypatch.setattr(auth_routes, "redeem_invite_code", fake_redeem)
    monkeypatch.setattr(auth_routes, "add_to_waitlist", fake_waitlist)
    monkeypatch.setattr(auth_routes, "create_user", fake_create_user)
    monkeypatch.setattr(auth_routes, "generate_magiclink_token", fake_token)
    return calls


def test_login_existing_user_returns_token(monkeypatch):
    calls = _patch_login(monkeypatch, exists=True)

    result = asyncio.run(auth_routes.api_auth_login(auth_routes.LoginBody(email="A@Example.com"), pool=None))

    assert result == {"status": "ok", "token_hash": "tok", "type": "magiclink"}
    assert calls["created"] == []  # existing users are never (re)created


def test_login_new_user_with_valid_code_creates_and_logs_in(monkeypatch):
    calls = _patch_login(monkeypatch, exists=False, redeem=True)

    result = asyncio.run(
        auth_routes.api_auth_login(
            auth_routes.LoginBody(email="new@example.com", invite_code="inigo"), pool=None
        )
    )

    assert result == {"status": "ok", "token_hash": "tok", "type": "magiclink"}
    assert calls["created"] == ["new@example.com"]
    assert calls["redeemed"] == ["inigo"]
    assert calls["waitlisted"] == []


def test_login_new_user_without_code_is_waitlisted(monkeypatch):
    calls = _patch_login(monkeypatch, exists=False)

    result = asyncio.run(auth_routes.api_auth_login(auth_routes.LoginBody(email="new@example.com"), pool=None))

    assert result == {"status": "waitlisted", "already": False, "invalid_code": False}
    assert calls["waitlisted"] == ["new@example.com"]
    assert calls["created"] == []


def test_login_already_on_waitlist_reports_already(monkeypatch):
    _patch_login(monkeypatch, exists=False, waitlist_added=False)

    result = asyncio.run(auth_routes.api_auth_login(auth_routes.LoginBody(email="new@example.com"), pool=None))

    assert result == {"status": "waitlisted", "already": True, "invalid_code": False}


def test_login_new_user_with_bad_code_is_waitlisted_and_flagged(monkeypatch):
    calls = _patch_login(monkeypatch, exists=False, redeem=False)

    result = asyncio.run(
        auth_routes.api_auth_login(
            auth_routes.LoginBody(email="new@example.com", invite_code="nope"), pool=None
        )
    )

    assert result == {"status": "waitlisted", "already": False, "invalid_code": True}
    assert calls["created"] == []
    assert calls["waitlisted"] == ["new@example.com"]


def test_login_rejects_malformed_email(monkeypatch):
    _patch_login(monkeypatch, exists=False)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(auth_routes.api_auth_login(auth_routes.LoginBody(email="x"), pool=None))

    assert exc.value.status_code == 400
    assert exc.value.detail == "invalid_email"
