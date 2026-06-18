from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest
from fastapi import HTTPException

import session_tasks
from auth import CurrentUser
from routes import sessions
from settings import get_settings
from tests.fakes import FakeDailyClient
from tests.test_personas import persona_payload


def test_start_session_rejects_missing_and_unknown_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "personas_dir", tmp_path)
    user = CurrentUser(id=str(uuid4()), email="a@example.com", username="a", is_admin=False)

    with pytest.raises(HTTPException) as missing:
        asyncio.run(sessions.start_session(sessions.StartSessionBody(agent=""), None, user))
    with pytest.raises(HTTPException) as unknown:
        asyncio.run(sessions.start_session(sessions.StartSessionBody(agent="nope"), None, user))

    assert missing.value.status_code == 400
    assert missing.value.detail == "agent_required"
    assert unknown.value.status_code == 404
    assert unknown.value.detail == "agent_not_found"


def test_start_session_rejects_admin_agent_for_non_admin(tmp_path, monkeypatch):
    payload = persona_payload()
    payload["agent"]["visibility"] = "admin"
    (tmp_path / "secret.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(get_settings(), "personas_dir", tmp_path)
    monkeypatch.setattr(get_settings(), "max_sessions", 5)
    user = CurrentUser(id=str(uuid4()), email="a@example.com", username="a", is_admin=False)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(sessions.start_session(sessions.StartSessionBody(agent="secret"), None, user))

    assert exc.value.status_code == 403
    assert exc.value.detail == "admin_only"


def test_start_session_rejects_busy_and_missing_daily_key(tmp_path, monkeypatch):
    (tmp_path / "agent.json").write_text(json.dumps(persona_payload()), encoding="utf-8")
    monkeypatch.setattr(get_settings(), "personas_dir", tmp_path)
    user = CurrentUser(id=str(uuid4()), email="a@example.com", username="a", is_admin=False)

    monkeypatch.setattr(get_settings(), "max_sessions", 0)
    with pytest.raises(HTTPException) as busy:
        asyncio.run(sessions.start_session(sessions.StartSessionBody(agent="agent"), None, user))
    assert busy.value.status_code == 429

    monkeypatch.setattr(get_settings(), "max_sessions", 5)
    monkeypatch.setattr(get_settings(), "daily_api_key", "")
    with pytest.raises(HTTPException) as missing_key:
        asyncio.run(sessions.start_session(sessions.StartSessionBody(agent="agent"), None, user))
    assert missing_key.value.status_code == 500
    assert missing_key.value.detail == "daily_api_key_missing"


def test_start_session_creates_daily_room_tokens_and_spawns_bot(tmp_path, monkeypatch):
    (tmp_path / "agent.json").write_text(json.dumps(persona_payload()), encoding="utf-8")
    monkeypatch.setattr(get_settings(), "personas_dir", tmp_path)
    monkeypatch.setattr(get_settings(), "daily_api_key", "daily-key")
    monkeypatch.setattr(get_settings(), "max_sessions", 5)
    session_tasks._active_sessions.clear()
    spawned = []
    created_tasks = []

    class AsyncClient:
        def __init__(self, headers=None, timeout=None):
            self.client = FakeDailyClient()
            spawned.append({"headers": headers, "timeout": timeout, "client": self.client})

        async def __aenter__(self):
            return self.client

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def fake_run_daily_bot(room_url, token, agent_name, pool, user_id=None):
        spawned.append(
            {
                "room_url": room_url,
                "token": token,
                "agent_name": agent_name,
                "pool": pool,
                "user_id": user_id,
            }
        )

    class FakeTask:
        def add_done_callback(self, callback):
            self.callback = callback

    def fake_create_task(coro):
        created_tasks.append(coro.cr_frame.f_locals.copy())
        coro.close()
        return FakeTask()

    monkeypatch.setattr(sessions.daily_client.httpx, "AsyncClient", AsyncClient)
    monkeypatch.setattr(sessions, "run_daily_bot", fake_run_daily_bot)
    monkeypatch.setattr(sessions.asyncio, "create_task", fake_create_task)
    user = CurrentUser(id=str(uuid4()), email="a@example.com", username="a", is_admin=False)
    pool = object()

    result = asyncio.run(
        sessions.start_session(sessions.StartSessionBody(agent="agent"), pool, user)
    )

    assert result == {"room_url": "https://room.test/a", "token": "user-token"}
    assert spawned[0]["headers"] == {"Authorization": "Bearer daily-key"}
    assert created_tasks[0]["room_url"] == "https://room.test/a"
    assert created_tasks[0]["token"] == "bot-token"
    assert created_tasks[0]["agent_name"] == "agent"
    assert created_tasks[0]["user_id"] == user.id
    assert len(created_tasks) == 1
    assert session_tasks.count() == 1
    session_tasks._active_sessions.clear()
