from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4

from memory import NO_PROFILE, load_memory_brief, summarize_and_persist


class FakeConnection:
    def __init__(self, profile_row=None, recent_rows=None):
        self.profile_row = profile_row
        self.recent_rows = recent_rows or []

    async def fetchrow(self, *args):
        return self.profile_row

    async def fetch(self, *args):
        return self.recent_rows


class AcquireContext:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePool:
    def __init__(self, connection):
        self.connection = connection

    def acquire(self):
        return AcquireContext(self.connection)


def test_load_memory_brief_returns_none_for_anonymous_user():
    assert asyncio.run(load_memory_brief(FakePool(FakeConnection()), None)) is None


def test_load_memory_brief_includes_default_profile_and_no_recent_sessions():
    user_id = str(uuid4())
    brief = asyncio.run(load_memory_brief(FakePool(FakeConnection()), user_id))

    assert "[Memory brief" in brief
    assert NO_PROFILE in brief
    assert "Recent sessions: (none)" in brief


def test_load_memory_brief_includes_profile_and_recent_sessions():
    user_id = str(uuid4())
    connection = FakeConnection(
        profile_row={"profile_text": "Likes direct feedback. "},
        recent_rows=[
            {
                "started_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
                "persona_name": "Marie",
                "summary": "Practiced a concise intro.",
            }
        ],
    )

    brief = asyncio.run(load_memory_brief(FakePool(connection), user_id))

    assert "Likes direct feedback." in brief
    assert "Recent sessions (most recent first" in brief
    assert "2026-01-02" in brief
    assert "Marie" in brief
    assert "Practiced a concise intro." in brief


class Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class SummaryConnection:
    def __init__(self, messages=None, prior=None):
        self.messages = messages or []
        self.prior = prior
        self.executed = []

    async def fetch(self, query, *args):
        return self.messages

    async def fetchrow(self, query, *args):
        return self.prior

    def transaction(self):
        return Tx()

    async def execute(self, query, *args):
        self.executed.append((query, args))


def test_summarize_and_persist_skips_sessions_without_messages(monkeypatch):
    connection = SummaryConnection(messages=[])

    def fail_call(*args, **kwargs):
        raise AssertionError("summarizer should not be called")

    monkeypatch.setattr("memory.call_anthropic_text", fail_call)

    asyncio.run(
        summarize_and_persist(
            FakePool(connection),
            uuid4(),
            str(uuid4()),
        )
    )

    assert connection.executed == []


def test_summarize_and_persist_updates_session_and_user_profile(monkeypatch):
    connection = SummaryConnection(
        messages=[{"role": "user", "text": "I need a sharper intro."}],
        prior={"profile_text": "Prior profile"},
    )
    session_id = uuid4()
    user_id = uuid4()
    captured = {}

    async def fake_call(*, api_key, model, system, prompt, max_tokens=1500):
        captured["api_key"] = api_key
        captured["model"] = model
        captured["system"] = system
        captured["prompt"] = prompt
        return json.dumps(
            {
                "session_summary": "Practiced a sharper intro.",
                "updated_profile": "Wants concise feedback.",
            }
        )

    monkeypatch.setattr("memory.call_anthropic_text", fake_call)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")

    asyncio.run(
        summarize_and_persist(
            FakePool(connection),
            session_id,
            str(user_id),
            model="model-test",
        )
    )

    assert captured["api_key"] == "anthropic-key"
    assert captured["model"] == "model-test"
    assert "Prior user profile:\nPrior profile" in captured["prompt"]
    assert "user: I need a sharper intro." in captured["prompt"]
    assert len(connection.executed) == 2
    assert "UPDATE sessions" in connection.executed[0][0]
    assert connection.executed[0][1] == (
        "Practiced a sharper intro.",
        "model-test",
        session_id,
    )
    assert "INSERT INTO user_profile" in connection.executed[1][0]
    assert connection.executed[1][1] == (
        user_id,
        "Wants concise feedback.",
        session_id,
        "model-test",
    )


def test_summarize_and_persist_does_not_write_empty_summary_fields(monkeypatch):
    connection = SummaryConnection(messages=[{"role": "user", "text": "hello"}])

    async def fake_call(*, api_key, model, system, prompt, max_tokens=1500):
        return json.dumps({"session_summary": "", "updated_profile": "profile"})

    monkeypatch.setattr("memory.call_anthropic_text", fake_call)

    asyncio.run(summarize_and_persist(FakePool(connection), uuid4(), str(uuid4())))

    assert connection.executed == []
