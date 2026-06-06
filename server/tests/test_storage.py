from __future__ import annotations

import asyncio

from storage import bulk_insert, close_pool
from tests.conftest import FakePool


class CopyConnection:
    def __init__(self):
        self.copied = []

    async def copy_records_to_table(self, table, records, columns):
        self.copied.append((table, records, columns))


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
