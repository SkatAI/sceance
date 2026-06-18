from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from latency_repository import load_latency_analysis
from tests.conftest import FakePool


class LoadConnection:
    def __init__(self, row):
        self._row = row

    async def fetchrow(self, query, *args):
        return self._row


def test_load_latency_analysis_returns_none_when_absent():
    pool = FakePool(LoadConnection(None))
    assert asyncio.run(load_latency_analysis(pool, uuid4())) is None


def test_load_latency_analysis_decodes_json_strings_and_iso_timestamp():
    generated = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    row = {
        "bundle": '{"turns": []}',          # jsonb handed back as a string
        "report": {"headline": "ok"},        # jsonb handed back already decoded
        "has_unexplained": False,
        "model": "claude-sonnet-4-6",
        "generated_at": generated,
    }
    pool = FakePool(LoadConnection(row))

    result = asyncio.run(load_latency_analysis(pool, uuid4()))

    assert result["bundle"] == {"turns": []}
    assert result["report"] == {"headline": "ok"}
    assert result["has_unexplained"] is False
    assert result["model"] == "claude-sonnet-4-6"
    assert result["generated_at"] == generated.isoformat()
