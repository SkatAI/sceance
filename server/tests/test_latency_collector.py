from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from latency_collector import (
    _build_turns,
    _pearson,
    _quantile,
    collect_latency_bundle,
)
from tests.conftest import FakePool

# ─── _pearson ───────────────────────────────────────────────────────

def test_pearson_returns_none_for_too_few_points():
    assert _pearson([1.0, 2.0], [1.0, 2.0]) is None


def test_pearson_returns_none_when_a_series_has_no_variance():
    assert _pearson([1.0, 1.0, 1.0], [2.0, 3.0, 4.0]) is None


def test_pearson_detects_perfect_positive_and_negative_correlation():
    assert _pearson([1.0, 2.0, 3.0], [2.0, 4.0, 6.0]) == pytest.approx(1.0)
    assert _pearson([1.0, 2.0, 3.0], [6.0, 4.0, 2.0]) == pytest.approx(-1.0)


# ─── _build_turns ───────────────────────────────────────────────────

def test_build_turns_marks_intro_and_skips_duplicate_bot_start():
    events = [
        {"kind": "bot_started_speaking", "timestamp_ns": 0},            # intro
        {"kind": "user_stopped_speaking", "timestamp_ns": 1_000_000_000},
        {"kind": "bot_started_speaking", "timestamp_ns": 2_500_000_000},  # real: 1.5s
        {"kind": "bot_started_speaking", "timestamp_ns": 3_000_000_000},  # continuation: ignored
    ]

    turns = _build_turns(events)

    assert len(turns) == 2
    assert turns[0] == {"turn": 1, "perceived_s": None, "is_intro": True, "is_stall": False}
    assert turns[1]["perceived_s"] == 1.5
    assert turns[1]["is_intro"] is False


def test_build_turns_flags_full_stall_over_threshold():
    events = [
        {"kind": "user_stopped_speaking", "timestamp_ns": 0},
        {"kind": "bot_started_speaking", "timestamp_ns": 35_000_000_000},  # 35s >= STALL_S
    ]

    turns = _build_turns(events)

    assert turns[0]["perceived_s"] == 35.0
    assert turns[0]["is_stall"] is True


def test_build_turns_flags_tail_stall_only_on_last_turn():
    events = [
        {"kind": "user_stopped_speaking", "timestamp_ns": 0},
        {"kind": "bot_started_speaking", "timestamp_ns": 1_000_000_000},   # 1.0s, normal
        {"kind": "user_stopped_speaking", "timestamp_ns": 10_000_000_000},
        {"kind": "bot_started_speaking", "timestamp_ns": 17_000_000_000},  # 7.0s, last turn
    ]

    turns = _build_turns(events)

    assert turns[0]["is_stall"] is False
    assert turns[1]["perceived_s"] == 7.0
    assert turns[1]["is_stall"] is True  # >= STALL_TAIL_S on the last real turn


# ─── collect_latency_bundle ─────────────────────────────────────────

def _ts(second: int) -> datetime:
    return datetime(2026, 1, 1, 10, 0, second, tzinfo=timezone.utc)


class BundleConnection:
    """Dispatches collect_latency_bundle's queries by content."""

    def __init__(self, session_row):
        self._session = session_row

    async def fetchrow(self, query, *args):
        if "FROM sessions" in query:
            return self._session
        raise AssertionError(query)

    async def fetch(self, query, *args):
        if "GROUP BY processor" in query:  # per-stage TTFB summary
            return [{"processor": "LLM#0", "n": 4, "min_v": 0.4, "avg_v": 0.6, "max_v": 0.9}]
        if "value_num FROM metrics" in query:  # ttfb timeline
            return [
                {"ts": _ts(i), "processor": "LLM#0", "value_num": v}
                for i, v in enumerate([0.4, 0.5, 0.6, 0.9])
            ]
        if "FROM events" in query:
            return [
                {"kind": "bot_started_speaking", "timestamp_ns": 0},                # intro
                {"kind": "user_stopped_speaking", "timestamp_ns": 10_000_000_000},
                {"kind": "bot_started_speaking", "timestamp_ns": 11_000_000_000},   # 1.0
                {"kind": "user_stopped_speaking", "timestamp_ns": 20_000_000_000},
                {"kind": "bot_started_speaking", "timestamp_ns": 21_000_000_000},   # 1.0
                {"kind": "user_stopped_speaking", "timestamp_ns": 30_000_000_000},
                {"kind": "bot_started_speaking", "timestamp_ns": 31_000_000_000},   # 1.0
                {"kind": "user_stopped_speaking", "timestamp_ns": 40_000_000_000},
                {"kind": "bot_started_speaking", "timestamp_ns": 45_000_000_000},   # 5.0 outlier
            ]
        if "llm_usage" in query:
            return [
                {"ts": _ts(0), "processor": "LLM#0", "prompt_tokens": 100, "completion_tokens": 10},
                {"ts": _ts(1), "processor": "LLM#0", "prompt_tokens": 120, "completion_tokens": 12},
            ]
        raise AssertionError(query)


def test_collect_latency_bundle_computes_stats_and_cause_tags():
    session_row = {
        "persona_name": "Marie",
        "environment": "local",
        "duration_s": 60,
        "total_prompt_tokens": 220,
        "total_completion_tokens": 22,
        "total_cache_read_tokens": 0,
        "total_cache_creation_tokens": 0,
        "total_tts_chars": 400,
    }
    pool = FakePool(BundleConnection(session_row))

    bundle = asyncio.run(collect_latency_bundle(pool, uuid4()))

    # Real turns = the four answered ones; intro excluded.
    stats = bundle["perceived_stats"]
    assert stats["count"] == 4
    assert stats["min"] == 1.0
    assert stats["avg"] == 2.0
    assert stats["median"] == 1.0
    assert stats["max"] == 5.0

    turns = bundle["turns"]
    assert turns[0]["cause"] == "intro_cold_start"
    assert turns[-1]["perceived_s"] == 5.0
    assert turns[-1]["cause"] == "llm_jitter"  # outlier, correlation undefined (n<3)

    # Correlation undefined with only two usage points => llm_jitter verdict.
    assert bundle["correlation"]["llm_ttfb_vs_prompt_tokens"] is None
    assert bundle["correlation"]["verdict"] == "llm_jitter"


def test_collect_latency_bundle_raises_for_missing_session():
    pool = FakePool(BundleConnection(None))

    with pytest.raises(KeyError):
        asyncio.run(collect_latency_bundle(pool, uuid4()))


# Smoke: _quantile lives here now; keep one assertion local to the module.
def test_quantile_interpolates():
    assert _quantile([10.0, 20.0, 30.0, 40.0], 0.25) == 17.5
