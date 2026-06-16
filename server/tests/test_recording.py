from __future__ import annotations

import asyncio

from recording import RecordDrainQueue, RecordKind, UsageTotals


def test_usage_totals_accumulates_llm_token_fields():
    totals = UsageTotals()

    totals.add_llm(
        prompt_tokens=10,
        completion_tokens=4,
        cache_read_input_tokens=3,
        cache_creation_input_tokens=2,
    )
    totals.add_llm(prompt_tokens=5, completion_tokens=1)

    assert totals == UsageTotals(
        prompt_tokens=15,
        completion_tokens=5,
        cache_read_tokens=3,
        cache_creation_tokens=2,
        tts_chars=0,
    )


def test_usage_totals_add_llm_treats_none_as_zero():
    totals = UsageTotals()

    totals.add_llm()

    assert totals == UsageTotals()


def test_usage_totals_add_tts_truncates_to_int_per_call():
    totals = UsageTotals()

    totals.add_tts(11.9)
    totals.add_tts(0.4)

    assert totals.tts_chars == 11  # int(11.9) + int(0.4) = 11 + 0


def test_drain_queue_drops_enqueues_after_close():
    queue = RecordDrainQueue(pool=None)

    queue.enqueue(RecordKind.MESSAGE, {"a": 1})
    queue._closed = True
    queue.enqueue(RecordKind.MESSAGE, {"a": 2})

    assert queue._queue.qsize() == 1


def test_drain_queue_flush_dispatches_rows_by_kind(monkeypatch):
    calls = []

    async def fake_insert_messages(pool, rows):
        calls.append(("messages", list(rows)))

    async def fake_insert_events(pool, rows):
        calls.append(("events", list(rows)))

    monkeypatch.setattr("recording.insert_messages", fake_insert_messages)
    monkeypatch.setattr("recording.insert_events", fake_insert_events)
    queue = RecordDrainQueue(pool=None)

    asyncio.run(
        queue._flush(
            [
                (RecordKind.MESSAGE, {"a": 1, "b": 2}),
                (RecordKind.EVENT, {"kind": "x", "timestamp_ns": 3}),
                (RecordKind.MESSAGE, {"a": 4, "b": 5}),
            ]
        )
    )

    assert calls == [
        ("messages", [{"a": 1, "b": 2}, {"a": 4, "b": 5}]),
        ("events", [{"kind": "x", "timestamp_ns": 3}]),
    ]
