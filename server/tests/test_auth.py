from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import auth
from auth import CurrentUser, get_current_user, require_admin
from tests.conftest import FakePool


class ProfileConnection:
    def __init__(self, row):
        self.row = row
        self.queries = []

    async def fetchrow(self, query, *args):
        self.queries.append((query, args))
        return self.row


def request_with_pool(pool):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)))


def test_verify_jwt_uses_legacy_secret_when_jwks_unavailable(monkeypatch):
    monkeypatch.setattr(auth, "_get_jwks_client", lambda: None)
    monkeypatch.setattr(auth, "SUPABASE_JWT_SECRET", "secret")
    monkeypatch.setattr(auth.jwt, "decode", lambda token, key, algorithms, audience: {"sub": "u1"})

    assert auth.verify_jwt("token") == {"sub": "u1"}


def test_verify_jwt_turns_decode_errors_into_401(monkeypatch):
    monkeypatch.setattr(auth, "_get_jwks_client", lambda: None)
    monkeypatch.setattr(auth, "SUPABASE_JWT_SECRET", "secret")

    def fail(*args, **kwargs):
        raise auth.jwt.InvalidTokenError("bad")

    monkeypatch.setattr(auth.jwt, "decode", fail)

    with pytest.raises(HTTPException) as exc:
        auth.verify_jwt("token")
    assert exc.value.status_code == 401
    assert "invalid_token" in exc.value.detail


def test_get_current_user_requires_bearer_header():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_current_user(request_with_pool(FakePool(ProfileConnection(None))), None))

    assert exc.value.status_code == 401
    assert exc.value.detail == "missing_bearer_token"


def test_get_current_user_requires_sub_claim(monkeypatch):
    monkeypatch.setattr(auth, "verify_jwt", lambda token: {})

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            get_current_user(
                request_with_pool(FakePool(ProfileConnection(None))),
                "Bearer token",
            )
        )

    assert exc.value.status_code == 401
    assert exc.value.detail == "token_missing_sub"


def test_get_current_user_requires_profile(monkeypatch):
    monkeypatch.setattr(auth, "verify_jwt", lambda token: {"sub": "u1"})

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            get_current_user(
                request_with_pool(FakePool(ProfileConnection(None))),
                "Bearer token",
            )
        )

    assert exc.value.status_code == 403
    assert exc.value.detail == "profile_missing"


def test_get_current_user_returns_profile(monkeypatch):
    monkeypatch.setattr(auth, "verify_jwt", lambda token: {"sub": "u1"})
    connection = ProfileConnection(
        {"id": "u1", "email": "a@example.com", "username": "alex", "is_admin": 1}
    )

    user = asyncio.run(
        get_current_user(
            request_with_pool(FakePool(connection)),
            "Bearer token",
        )
    )

    assert user == CurrentUser(
        id="u1",
        email="a@example.com",
        username="alex",
        is_admin=True,
    )
    assert connection.queries[0][1] == ("u1",)


def test_require_admin_allows_admin_and_rejects_non_admin():
    admin = CurrentUser(id="u1", email="a@example.com", username="alex", is_admin=True)
    non_admin = CurrentUser(id="u2", email="b@example.com", username="bea", is_admin=False)

    assert asyncio.run(require_admin(admin)) is admin
    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_admin(non_admin))
    assert exc.value.status_code == 403
    assert exc.value.detail == "admin_only"
