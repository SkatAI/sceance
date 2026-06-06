from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from memory import NO_PROFILE, _extract_json, load_memory_brief


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


def test_extract_json_accepts_plain_json():
    assert _extract_json('{"session_summary": "ok", "updated_profile": "new"}') == {
        "session_summary": "ok",
        "updated_profile": "new",
    }


def test_extract_json_accepts_fenced_json():
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_falls_back_to_first_object_in_prose():
    assert _extract_json('Here it is: {"a": 1, "b": 2}. Done.') == {"a": 1, "b": 2}


def test_extract_json_raises_when_no_json_object_exists():
    with pytest.raises(json.JSONDecodeError):
        _extract_json("no json here")


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
