from __future__ import annotations

import asyncio

from storage import (
    EVENT_COLUMNS,
    MESSAGE_COLUMNS,
    METRIC_COLUMNS,
    bulk_insert,
    close_pool,
    finalize_session,
    insert_events,
    insert_messages,
    insert_metrics,
    insert_session,
)
from tests.conftest import FakePool


class CopyConnection:
    def __init__(self):
        self.copied = []

    async def copy_records_to_table(self, table, records, columns):
        self.copied.append((table, records, columns))


class ExecConnection:
    def __init__(self):
        self.executed = []

    async def execute(self, query, *args):
        self.executed.append((query, args))


class ClosablePool:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


def test_bulk_insert_noops_for_empty_rows():
    connection = CopyConnection()

    asyncio.run(bulk_insert(FakePool(connection), "messages", ["id"], []))

    assert connection.copied == []


def test_bulk_insert_copies_records_to_table():
    connection = CopyConnection()

    asyncio.run(
        bulk_insert(
            FakePool(connection),
            "messages",
            ["role", "text"],
            [("user", "hello"), ("assistant", "hi")],
        )
    )

    assert connection.copied == [
        (
            "messages",
            [("user", "hello"), ("assistant", "hi")],
            ["role", "text"],
        )
    ]


def test_close_pool_handles_none_and_closes_pool():
    pool = ClosablePool()

    asyncio.run(close_pool(None))
    asyncio.run(close_pool(pool))

    assert pool.closed is True


def test_insert_messages_uses_fixed_column_order():
    connection = CopyConnection()
    row = {
        "session_id": "s1",
        "role": "user",
        "text": "hi",
        "language": "en",
        "stt_timestamp": "t1",
        "recorded_at": "now",
    }

    asyncio.run(insert_messages(FakePool(connection), [row]))

    table, records, columns = connection.copied[0]
    assert table == "messages"
    assert columns == list(MESSAGE_COLUMNS)
    assert records == [["s1", "user", "hi", "en", "t1", "now"]]


def test_insert_events_uses_fixed_column_order():
    connection = CopyConnection()
    row = {"session_id": "s1", "kind": "joined", "timestamp_ns": 5, "payload": None}

    asyncio.run(insert_events(FakePool(connection), [row]))

    table, records, columns = connection.copied[0]
    assert table == "events"
    assert columns == list(EVENT_COLUMNS)
    assert records == [["s1", "joined", 5, None]]


def test_insert_metrics_uses_fixed_column_order():
    connection = CopyConnection()
    row = {c: c for c in METRIC_COLUMNS}

    asyncio.run(insert_metrics(FakePool(connection), [row]))

    table, records, columns = connection.copied[0]
    assert table == "metrics"
    assert columns == list(METRIC_COLUMNS)
    assert records == [list(METRIC_COLUMNS)]


def test_insert_messages_noops_for_empty_rows():
    connection = CopyConnection()

    asyncio.run(insert_messages(FakePool(connection), []))

    assert connection.copied == []


def test_insert_session_inserts_row_in_expected_arg_order():
    connection = ExecConnection()

    asyncio.run(
        insert_session(
            FakePool(connection),
            session_id="s1",
            persona_name="Marie",
            persona_json='{"x": 1}',
            lang="fr",
            started_at="t0",
            user_id=None,
            environment="local",
        )
    )

    query, args = connection.executed[0]
    assert "INSERT INTO sessions" in query
    assert args == ("s1", "Marie", '{"x": 1}', "fr", "t0", None, "local")


def test_finalize_session_updates_totals_then_id():
    connection = ExecConnection()

    asyncio.run(
        finalize_session(
            FakePool(connection),
            session_id="s1",
            ended_at="t1",
            prompt_tokens=2,
            completion_tokens=3,
            cache_read_tokens=4,
            cache_creation_tokens=5,
            tts_chars=6,
        )
    )

    query, args = connection.executed[0]
    assert "UPDATE sessions" in query
    assert args == ("t1", 2, 3, 4, 5, 6, "s1")
