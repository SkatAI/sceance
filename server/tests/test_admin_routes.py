from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from auth import CurrentUser
from routes import admin
from tests.conftest import FakePool
from tests.test_personas import persona_payload


def test_quantile_handles_empty_single_and_interpolated_values():
    assert admin._quantile([], 0.5) is None
    assert admin._quantile([4.0], 0.9) == 4.0
    assert admin._quantile([1.0, 3.0, 5.0], 0.5) == 3.0
    assert admin._quantile([10.0, 20.0, 30.0, 40.0], 0.25) == 17.5


def test_pair_response_latencies_pairs_recent_unanswered_user_stop():
    events = [
        {"kind": "bot_started_speaking", "timestamp_ns": 1_000_000_000},
        {"kind": "user_stopped_speaking", "timestamp_ns": 2_000_000_000},
        {"kind": "user_stopped_speaking", "timestamp_ns": 3_500_000_000},
        {"kind": "bot_started_speaking", "timestamp_ns": 5_000_000_000},
        {"kind": "bot_started_speaking", "timestamp_ns": 7_000_000_000},
    ]

    assert admin._pair_response_latencies(events) == [1.5]


def test_api_session_detail_formats_session_rows():
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

    pool = FakePool(Connection())
    detail = asyncio.run(
        admin.api_session_detail(str(sid), pool, CurrentUser("u", "e", "n", True))
    )

    assert detail["id"] == str(sid)
    assert detail["persona"]["name"] == "Marie"
    assert detail["duration_s"] == 300.0
    assert detail["messages"][0]["text"] == "Bonjour"
    assert detail["metrics"][0]["avg"] == 0.5
    assert detail["response_latency"]["per_turn"] == [{"turn": 1, "latency_s": 1.25}]


def test_api_aggregate_maps_database_rows():
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

    pool = FakePool(Connection())
    result = asyncio.run(admin.api_aggregate(7, pool, CurrentUser("u", "e", "n", True)))

    assert result["days"] == 7
    assert result["sessions"]["total_sessions"] == 3
    assert result["ttfb"] == [{"processor": "LLM#0", "avg_ttfb": 0.25, "n": 4}]


def test_api_sessions_maps_list_rows():
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

    pool = FakePool(Connection())
    result = asyncio.run(
        admin.api_sessions(20, 0, None, None, pool, CurrentUser("u", "e", "n", True))
    )

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
