from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

import supabase_admin
from settings import get_settings
from tests.conftest import FakePool


class UserConnection:
    def __init__(self, row):
        self.row = row
        self.calls = []

    async def fetchrow(self, query, *args):
        self.calls.append((query, args))
        return self.row


class ExecConnection:
    def __init__(self):
        self.calls = []

    async def execute(self, query, *args):
        self.calls.append((query, args))


class FakeResponse:
    def __init__(self, data=None, status_code=200, text=""):
        self._data = data or {}
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._data


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.posts = []

    async def post(self, url, headers=None, json=None):
        self.posts.append({"url": url, "headers": headers, "json": json})
        return self.response


def test_admin_configured_reflects_auth_base_and_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "supabase_url", "https://example.test")
    monkeypatch.setattr(get_settings(), "supabase_service_role_key", "service")
    assert supabase_admin.admin_configured() is True

    monkeypatch.setattr(get_settings(), "supabase_service_role_key", "")
    assert supabase_admin.admin_configured() is False


def test_user_exists_queries_auth_users_case_insensitively():
    connection = UserConnection({"?column?": 1})

    assert asyncio.run(supabase_admin.user_exists(FakePool(connection), "A@EXAMPLE.COM")) is True
    assert "lower(email)" in connection.calls[0][0]
    assert connection.calls[0][1] == ("A@EXAMPLE.COM",)


def test_user_exists_returns_false_when_no_row():
    assert asyncio.run(supabase_admin.user_exists(FakePool(UserConnection(None)), "a@example.com")) is False


def test_normalize_invite_code_lowercases_trims_and_strips_unsafe():
    assert supabase_admin.normalize_invite_code("  INIGO ") == "inigo"
    assert supabase_admin.normalize_invite_code("in-i go!") == "inigo"
    assert supabase_admin.normalize_invite_code("") == ""


def test_redeem_invite_code_consumes_when_row_returned():
    connection = UserConnection({"code": "inigo"})

    assert asyncio.run(supabase_admin.redeem_invite_code(FakePool(connection), "  INIGO ")) is True
    query, args = connection.calls[0]
    assert "used_count < max_uses" in query and "expires_at > now()" in query
    assert args == ("inigo",)  # normalized before the query


def test_redeem_invite_code_returns_false_when_no_row():
    assert asyncio.run(supabase_admin.redeem_invite_code(FakePool(UserConnection(None)), "inigo")) is False


def test_redeem_invite_code_short_circuits_blank_code():
    connection = UserConnection({"code": "x"})

    assert asyncio.run(supabase_admin.redeem_invite_code(FakePool(connection), "  !! ")) is False
    assert connection.calls == []  # never touched the DB


def test_add_to_waitlist_inserts_idempotently():
    connection = ExecConnection()

    asyncio.run(supabase_admin.add_to_waitlist(FakePool(connection), "a@example.com"))

    query, args = connection.calls[0]
    assert "INSERT INTO public.waitlist" in query and "ON CONFLICT" in query
    assert args == ("a@example.com",)


def test_create_user_posts_preconfirmed_user(monkeypatch):
    monkeypatch.setattr(get_settings(), "supabase_url", "https://example.test")
    monkeypatch.setattr(get_settings(), "supabase_service_role_key", "service")
    client = FakeClient(FakeResponse())

    asyncio.run(supabase_admin.create_user(client, "a@example.com"))

    assert client.posts[0]["url"].endswith("/admin/users")
    assert client.posts[0]["json"] == {"email": "a@example.com", "email_confirm": True}
    assert client.posts[0]["headers"]["Authorization"] == "Bearer service"


def test_create_user_raises_on_admin_failure():
    client = FakeClient(FakeResponse(status_code=500, text="nope"))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(supabase_admin.create_user(client, "a@example.com"))
    assert exc.value.status_code == 502
    assert exc.value.detail == "signup_failed"


def test_generate_magiclink_token_accepts_top_level_and_nested_tokens(monkeypatch):
    monkeypatch.setattr(get_settings(), "supabase_url", "https://example.test")

    top = asyncio.run(
        supabase_admin.generate_magiclink_token(
            FakeClient(FakeResponse({"hashed_token": "top"})),
            "a@example.com",
        )
    )
    nested = asyncio.run(
        supabase_admin.generate_magiclink_token(
            FakeClient(FakeResponse({"properties": {"hashed_token": "nested"}})),
            "a@example.com",
        )
    )

    assert top == "top"
    assert nested == "nested"


def test_generate_magiclink_token_raises_when_token_missing_or_request_fails():
    with pytest.raises(HTTPException) as failed:
        asyncio.run(
            supabase_admin.generate_magiclink_token(
                FakeClient(FakeResponse(status_code=400, text="bad")),
                "a@example.com",
            )
        )
    with pytest.raises(HTTPException) as missing:
        asyncio.run(
            supabase_admin.generate_magiclink_token(
                FakeClient(FakeResponse({"properties": {}})),
                "a@example.com",
            )
        )

    assert failed.value.detail == "login_link_failed"
    assert missing.value.detail == "login_link_failed"
