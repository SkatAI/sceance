from __future__ import annotations

import asyncio
import json
from uuid import uuid4

from recorder import NullSessionRecorder, SessionRecorder
from tests.conftest import FakePool
from tests.test_personas import persona_payload
from personas import Persona


class RecorderConnection:
    def __init__(self):
        self.executed = []

    async def execute(self, query, *args):
        self.executed.append((query, args))


def make_persona(memory=True):
    raw = persona_payload()
    raw["agent"]["memory"] = memory
    return Persona.from_dict(raw, id="agent")


def test_record_methods_enqueue_expected_rows_and_totals():
    recorder = SessionRecorder(FakePool(RecorderConnection()), make_persona())

    recorder.record_message("user", "hello", language="en", stt_timestamp="t1")
    recorder.record_event("joined", 123, {"id": "p1"})
    recorder.record_metric(
        "LLM",
        "model",
        "llm_usage",
        prompt_tokens=10,
        completion_tokens=4,
        cache_read_input_tokens=3,
        cache_creation_input_tokens=2,
        reasoning_tokens=1,
    )
    recorder.record_metric("TTS", "voice", "tts_usage", value_num=11.9)

    queued = [recorder._queue.get_nowait() for _ in range(4)]

    assert queued[0][0] == "messages"
    assert queued[0][1]["role"] == "user"
    assert queued[1] == (
        "events",
        {
            "session_id": recorder.session_id,
            "kind": "joined",
            "timestamp_ns": 123,
            "payload": json.dumps({"id": "p1"}),
        },
    )
    assert recorder._totals == {
        "prompt_tokens": 10,
        "completion_tokens": 4,
        "cache_read_tokens": 3,
        "cache_creation_tokens": 2,
        "tts_chars": 11,
    }


def test_flush_groups_rows_by_table_and_preserves_columns(monkeypatch):
    calls = []

    async def fake_bulk_insert(pool, table, columns, rows):
        calls.append((table, columns, rows))

    monkeypatch.setattr("recorder.bulk_insert", fake_bulk_insert)
    recorder = SessionRecorder(FakePool(RecorderConnection()), make_persona())

    asyncio.run(
        recorder._flush(
            [
                ("messages", {"a": 1, "b": 2}),
                ("events", {"kind": "x", "timestamp_ns": 3}),
                ("messages", {"a": 4, "b": 5}),
            ]
        )
    )

    assert calls == [
        ("messages", ["a", "b"], [[1, 2], [4, 5]]),
        ("events", ["kind", "timestamp_ns"], [["x", 3]]),
    ]


def test_start_inserts_session_row_and_close_finalizes_without_user_summary(monkeypatch):
    connection = RecorderConnection()
    recorder = SessionRecorder(FakePool(connection), make_persona(), user_id=None)

    async def run_session():
        await recorder.start()
        recorder.record_metric("LLM", "m", "llm_usage", prompt_tokens=2, completion_tokens=3)
        await recorder.close()

    async def fake_bulk_insert(*args, **kwargs):
        return None

    monkeypatch.setattr("recorder.bulk_insert", fake_bulk_insert)

    asyncio.run(run_session())

    assert "INSERT INTO sessions" in connection.executed[0][0]
    insert_args = connection.executed[0][1]
    assert insert_args[1] == "Marie"
    assert json.loads(insert_args[2])["persona"]["name"] == "Marie"
    assert "UPDATE sessions" in connection.executed[-1][0]
    update_args = connection.executed[-1][1]
    assert update_args[1:6] == (2, 3, 0, 0, 0)


def test_close_starts_summary_task_for_authenticated_user(monkeypatch):
    created = []

    def fake_create_task(coro):
        created.append(coro)
        coro.close()
        return object()

    monkeypatch.setattr("recorder.asyncio.create_task", fake_create_task)
    recorder = SessionRecorder(FakePool(RecorderConnection()), make_persona(), user_id=str(uuid4()))

    asyncio.run(recorder.close())
    asyncio.run(recorder.close())

    assert len(created) == 1


def test_close_skips_summary_when_update_memory_off(monkeypatch):
    # Blank-slate personas still record, but must not write cross-session memory.
    created = []

    def fake_create_task(coro):
        created.append(coro)
        coro.close()
        return object()

    monkeypatch.setattr("recorder.asyncio.create_task", fake_create_task)
    recorder = SessionRecorder(
        FakePool(RecorderConnection()), make_persona(),
        user_id=str(uuid4()), update_memory=False,
    )

    asyncio.run(recorder.close())

    assert created == []


def test_null_session_recorder_is_noop():
    recorder = NullSessionRecorder()

    asyncio.run(recorder.start())
    recorder.record_message("user", "hello")
    recorder.record_event("x", 1)
    recorder.record_metric("p", None, "ttfb", value_num=1.0)
    asyncio.run(recorder.close())

    assert recorder.session_id is not None
