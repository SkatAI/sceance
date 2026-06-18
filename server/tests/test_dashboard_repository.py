from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from dashboard_repository import _session_filter, aggregate, fetch_session_detail, list_sessions
from tests.conftest import FakePool
from tests.test_personas import persona_payload

# ─── _session_filter: persona-only / env-only / both / none ──────────

def test_session_filter_no_filters():
    assert _session_filter(None, None) == ("", [])


def test_session_filter_persona_only():
    assert _session_filter("Marie", None) == ("WHERE s.persona_name = $1", ["Marie"])


def test_session_filter_environment_only():
    assert _session_filter(None, "local") == ("WHERE s.environment = $1", ["local"])


def test_session_filter_both_filters_number_placeholders_in_order():
    where, args = _session_filter("Marie", "local")
    assert where == "WHERE s.persona_name = $1 AND s.environment = $2"
    assert args == ["Marie", "local"]


# ─── list_sessions: parameterization (no raw interpolation) ──────────

class RecordingConnection:
    """Records every query + args; returns empty result sets."""

    def __init__(self):
        self.calls = []

    async def fetch(self, query, *args):
        self.calls.append((query, args))
        return []

    async def fetchval(self, query, *args):
        self.calls.append((query, args))
        return 0


def test_list_sessions_passes_filter_args_then_limit_offset():
    conn = RecordingConnection()
    asyncio.run(list_sessions(FakePool(conn), limit=20, offset=40, persona="Marie", environment="local"))

    main = next(q for q in conn.calls if "msg_count" in q[0])
    count = next(q for q in conn.calls if q[0].strip().startswith("SELECT count(*)"))

    # WHERE uses placeholders only; user values arrive as positional args.
    assert "WHERE s.persona_name = $1 AND s.environment = $2" in main[0]
    assert main[1] == ("Marie", "local", 20, 40)
    assert count[1] == ("Marie", "local")
    assert "Marie" not in main[0] and "local" not in main[0]


def test_list_sessions_unfiltered_has_no_where_and_only_limit_offset_args():
    conn = RecordingConnection()
    asyncio.run(list_sessions(FakePool(conn), limit=10, offset=0, persona=None, environment=None))

    main = next(q for q in conn.calls if "msg_count" in q[0])
    count = next(q for q in conn.calls if q[0].strip().startswith("SELECT count(*)"))
    # No filter WHERE on the sessions table; only limit/offset reach the args.
    assert "s.persona_name = $" not in main[0]
    assert "s.environment = $" not in main[0]
    assert main[1] == (10, 0)
    assert count[1] == ()


# ─── aggregate / fetch_session_detail shaping ───────────────────────

def test_aggregate_shapes_rollup_and_ttfb():
    class Connection:
        async def fetchrow(self, query, *args):
            return {"total_sessions": 3, "finished_sessions": 2}

        async def fetch(self, query, *args):
            return [{"processor": "LLM#0", "avg_ttfb": 0.25, "n": 4}]

    result = asyncio.run(aggregate(FakePool(Connection()), 7))

    assert result["days"] == 7
    assert result["since"] is not None
    assert result["sessions"] == {"total_sessions": 3, "finished_sessions": 2}
    assert result["ttfb"] == [{"processor": "LLM#0", "avg_ttfb": 0.25, "n": 4}]


def test_fetch_session_detail_returns_none_when_missing():
    class Connection:
        async def fetchrow(self, query, *args):
            return None

    assert asyncio.run(fetch_session_detail(FakePool(Connection()), uuid4())) is None


def test_fetch_session_detail_keeps_persona_json_and_turn_events_raw():
    sid = uuid4()
    started = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)

    class Connection:
        async def fetchrow(self, query, *args):
            return {
                "id": sid,
                "persona_name": "Marie",
                "persona_json": persona_payload(),
                "lang": "fr",
                "started_at": started,
                "ended_at": None,
                "duration_s": None,
                "total_prompt_tokens": 1,
                "total_completion_tokens": 2,
                "total_cache_read_tokens": 0,
                "total_cache_creation_tokens": 0,
                "total_tts_chars": 5,
            }

        async def fetch(self, query, *args):
            if "FROM events" in query:
                return [{"kind": "user_stopped_speaking", "timestamp_ns": 1}]
            return []

    detail = asyncio.run(fetch_session_detail(FakePool(Connection()), sid))

    assert detail["id"] == str(sid)
    assert detail["persona_json"]["persona"]["name"] == "Marie"
    assert detail["turn_events"] == [{"kind": "user_stopped_speaking", "timestamp_ns": 1}]
    assert detail["started_at"] == started.isoformat()
