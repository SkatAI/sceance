from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

import server
from auth import CurrentUser
from tests.test_personas import persona_payload


class FakeResponse:
    def __init__(self, data, status_code=200):
        self.data = data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise server.httpx.HTTPStatusError(
                "bad response",
                request=server.httpx.Request("POST", "https://example.test"),
                response=server.httpx.Response(self.status_code),
            )

    def json(self):
        return self.data


class FakeDailyClient:
    def __init__(self):
        self.posts = []

    async def post(self, url, json):
        self.posts.append((url, json))
        if url.endswith("/rooms"):
            return FakeResponse({"name": "room-a", "url": "https://room.test/a"})
        if url.endswith("/meeting-tokens"):
            owner = json["properties"]["is_owner"]
            return FakeResponse({"token": "bot-token" if owner else "user-token"})
        raise AssertionError(url)


def test_quantile_handles_empty_single_and_interpolated_values():
    assert server._quantile([], 0.5) is None
    assert server._quantile([4.0], 0.9) == 4.0
    assert server._quantile([1.0, 3.0, 5.0], 0.5) == 3.0
    assert server._quantile([10.0, 20.0, 30.0, 40.0], 0.25) == 17.5


def test_pair_response_latencies_pairs_recent_unanswered_user_stop():
    events = [
        {"kind": "bot_started_speaking", "timestamp_ns": 1_000_000_000},
        {"kind": "user_stopped_speaking", "timestamp_ns": 2_000_000_000},
        {"kind": "user_stopped_speaking", "timestamp_ns": 3_500_000_000},
        {"kind": "bot_started_speaking", "timestamp_ns": 5_000_000_000},
        {"kind": "bot_started_speaking", "timestamp_ns": 7_000_000_000},
    ]

    assert server._pair_response_latencies(events) == [1.5]


def test_daily_room_and_token_payloads_include_expected_properties(monkeypatch):
    monkeypatch.setattr(server.time, "time", lambda: 1000)
    client = FakeDailyClient()

    room = asyncio.run(server._create_daily_room(client))
    token = asyncio.run(server._create_meeting_token(client, "room-a", is_owner=True))

    assert room == {"name": "room-a", "url": "https://room.test/a"}
    assert token == "bot-token"
    room_payload = client.posts[0][1]["properties"]
    token_payload = client.posts[1][1]["properties"]
    assert room_payload["exp"] == 1000 + server.ROOM_EXPIRY_SECONDS
    assert room_payload["eject_at_room_exp"] is True
    assert room_payload["enable_chat"] is False
    assert token_payload == {
        "room_name": "room-a",
        "is_owner": True,
        "exp": 1000 + server.ROOM_EXPIRY_SECONDS,
    }


def test_list_agents_returns_only_active_valid_personas(tmp_path, monkeypatch):
    active = persona_payload()
    inactive = persona_payload()
    inactive["agent"]["active"] = False
    (tmp_path / "active.json").write_text(json.dumps(active), encoding="utf-8")
    (tmp_path / "inactive.json").write_text(json.dumps(inactive), encoding="utf-8")
    (tmp_path / "broken.json").write_text("{bad json", encoding="utf-8")
    monkeypatch.setattr(server, "PERSONAS_DIR", tmp_path)

    result = asyncio.run(server.list_agents())

    assert [agent["id"] for agent in result["agents"]] == ["active"]


def test_start_session_rejects_missing_and_unknown_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "PERSONAS_DIR", tmp_path)
    user = CurrentUser(id=str(uuid4()), email="a@example.com", username="a", is_admin=False)

    with pytest.raises(HTTPException) as missing:
        asyncio.run(server.start_session(server.StartSessionBody(agent=""), user))
    with pytest.raises(HTTPException) as unknown:
        asyncio.run(server.start_session(server.StartSessionBody(agent="nope"), user))

    assert missing.value.status_code == 400
    assert missing.value.detail == "agent_required"
    assert unknown.value.status_code == 404
    assert unknown.value.detail == "agent_not_found"


def test_start_session_rejects_busy_and_missing_daily_key(tmp_path, monkeypatch):
    (tmp_path / "agent.json").write_text(json.dumps(persona_payload()), encoding="utf-8")
    monkeypatch.setattr(server, "PERSONAS_DIR", tmp_path)
    user = CurrentUser(id=str(uuid4()), email="a@example.com", username="a", is_admin=False)

    monkeypatch.setattr(server, "MAX_SESSIONS", 0)
    with pytest.raises(HTTPException) as busy:
        asyncio.run(server.start_session(server.StartSessionBody(agent="agent"), user))
    assert busy.value.status_code == 429

    monkeypatch.setattr(server, "MAX_SESSIONS", 5)
    monkeypatch.setattr(server, "DAILY_API_KEY", "")
    with pytest.raises(HTTPException) as missing_key:
        asyncio.run(server.start_session(server.StartSessionBody(agent="agent"), user))
    assert missing_key.value.status_code == 500
    assert missing_key.value.detail == "daily_api_key_missing"


def test_start_session_creates_daily_room_tokens_and_spawns_bot(tmp_path, monkeypatch):
    (tmp_path / "agent.json").write_text(json.dumps(persona_payload()), encoding="utf-8")
    monkeypatch.setattr(server, "PERSONAS_DIR", tmp_path)
    monkeypatch.setattr(server, "DAILY_API_KEY", "daily-key")
    monkeypatch.setattr(server, "MAX_SESSIONS", 5)
    monkeypatch.setattr(server.app.state, "db_pool", object(), raising=False)
    server._active_sessions.clear()
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

    monkeypatch.setattr(server.httpx, "AsyncClient", AsyncClient)
    monkeypatch.setattr(server, "run_daily_bot", fake_run_daily_bot)
    monkeypatch.setattr(server.asyncio, "create_task", fake_create_task)
    user = CurrentUser(id=str(uuid4()), email="a@example.com", username="a", is_admin=False)

    result = asyncio.run(server.start_session(server.StartSessionBody(agent="agent"), user))

    assert result == {"room_url": "https://room.test/a", "token": "user-token"}
    assert spawned[0]["headers"] == {"Authorization": "Bearer daily-key"}
    assert created_tasks[0]["room_url"] == "https://room.test/a"
    assert created_tasks[0]["token"] == "bot-token"
    assert created_tasks[0]["agent_name"] == "agent"
    assert created_tasks[0]["user_id"] == user.id
    assert len(created_tasks) == 1
    assert len(server._active_sessions) == 1
    server._active_sessions.clear()


def test_api_me_projects_current_user():
    user = CurrentUser(id="u1", email="a@example.com", username="alex", is_admin=True)

    assert asyncio.run(server.api_me(user)) == {
        "id": "u1",
        "email": "a@example.com",
        "username": "alex",
        "is_admin": True,
    }


def test_api_session_detail_formats_session_rows(monkeypatch):
    sid = uuid4()
    started = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    ended = datetime(2026, 1, 1, 10, 5, tzinfo=timezone.utc)

    class Connection:
        async def fetchrow(self, query, *args):
            # api_session_detail also looks up stored latency analysis; mimic
            # the "none generated yet" path so it doesn't get the session row.
            if "session_latency_analysis" in query:
                return None
            return {
                "id": sid,
                "persona_name": "Marie",
                "persona_json": persona_payload(),
                "lang": "fr",
                "started_at": started,
                "ended_at": ended,
                "duration_s": 300,
                "total_prompt_tokens": 10,
                "total_completion_tokens": 20,
                "total_cache_read_tokens": 2,
                "total_cache_creation_tokens": 1,
                "total_tts_chars": 123,
            }

        async def fetch(self, query, *args):
            if "FROM messages" in query:
                return [
                    {
                        "role": "user",
                        "text": "Bonjour",
                        "language": "fr",
                        "recorded_at": started,
                    }
                ]
            if "FROM metrics" in query:
                return [
                    {
                        "processor": "LLM#0",
                        "kind": "ttfb",
                        "n": 2,
                        "avg_value": 0.5,
                        "sum_value": 1.0,
                    }
                ]
            if "FROM events" in query:
                return [
                    {"kind": "user_stopped_speaking", "timestamp_ns": 1_000_000_000},
                    {"kind": "bot_started_speaking", "timestamp_ns": 2_250_000_000},
                ]
            raise AssertionError(query)

    monkeypatch.setattr(
        server.app.state,
        "db_pool",
        SimpleNamespace(acquire=lambda: Acquire(Connection())),
        raising=False,
    )

    detail = asyncio.run(server.api_session_detail(str(sid), CurrentUser("u", "e", "n", True)))

    assert detail["id"] == str(sid)
    assert detail["persona"]["name"] == "Marie"
    assert detail["duration_s"] == 300.0
    assert detail["messages"][0]["text"] == "Bonjour"
    assert detail["metrics"][0]["avg"] == 0.5
    assert detail["response_latency"]["per_turn"] == [{"turn": 1, "latency_s": 1.25}]


def test_api_aggregate_maps_database_rows(monkeypatch):
    class Connection:
        async def fetchrow(self, query, *args):
            return {
                "total_sessions": 3,
                "finished_sessions": 2,
                "total_duration_s": 120,
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "cache_read_tokens": 4,
                "cache_creation_tokens": 1,
                "tts_chars": 300,
            }

        async def fetch(self, query, *args):
            return [{"processor": "LLM#0", "avg_ttfb": 0.25, "n": 4}]

    monkeypatch.setattr(
        server.app.state,
        "db_pool",
        SimpleNamespace(acquire=lambda: Acquire(Connection())),
        raising=False,
    )

    result = asyncio.run(server.api_aggregate(7, CurrentUser("u", "e", "n", True)))

    assert result["days"] == 7
    assert result["sessions"]["total_sessions"] == 3
    assert result["ttfb"] == [{"processor": "LLM#0", "avg_ttfb": 0.25, "n": 4}]


def test_api_sessions_maps_list_rows(monkeypatch):
    sid = uuid4()
    started = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)

    class Connection:
        async def fetch(self, query, *args):
            return [
                {
                    "id": sid,
                    "persona_name": "Marie",
                    "environment": "local",
                    "lang": "fr",
                    "started_at": started,
                    "ended_at": None,
                    "duration_s": None,
                    "total_prompt_tokens": 10,
                    "total_completion_tokens": 20,
                    "total_cache_read_tokens": 2,
                    "total_cache_creation_tokens": 1,
                    "total_tts_chars": 300,
                    "msg_count": 5,
                }
            ]

        async def fetchval(self, query, *args):
            return 1

    monkeypatch.setattr(
        server.app.state,
        "db_pool",
        SimpleNamespace(acquire=lambda: Acquire(Connection())),
        raising=False,
    )

    result = asyncio.run(server.api_sessions(20, 0, None, None, CurrentUser("u", "e", "n", True)))

    assert result["total"] == 1
    assert result["sessions"] == [
        {
            "id": str(sid),
            "persona_name": "Marie",
            "environment": "local",
            "lang": "fr",
            "started_at": started.isoformat(),
            "ended_at": None,
            "duration_s": None,
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "cache_read_tokens": 2,
            "cache_creation_tokens": 1,
            "tts_chars": 300,
            "msg_count": 5,
        }
    ]


class Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False
