from __future__ import annotations

import asyncio
import json
from uuid import uuid4

from personas import Persona
from recorder import NullSessionRecorder, RecordKind, SessionRecorder
from tests.conftest import FakePool
from tests.test_personas import persona_payload


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

    assert queued[0][0] == RecordKind.MESSAGE
    assert queued[0][1]["role"] == "user"
    assert queued[1] == (
        RecordKind.EVENT,
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


def test_flush_dispatches_rows_to_repository_by_kind(monkeypatch):
    calls = []

    async def fake_insert_messages(pool, rows):
        calls.append(("messages", list(rows)))

    async def fake_insert_events(pool, rows):
        calls.append(("events", list(rows)))

    monkeypatch.setattr("recorder.insert_messages", fake_insert_messages)
    monkeypatch.setattr("recorder.insert_events", fake_insert_events)
    recorder = SessionRecorder(FakePool(RecorderConnection()), make_persona())

    asyncio.run(
        recorder._flush(
            [
                (RecordKind.MESSAGE, {"a": 1, "b": 2}),
                (RecordKind.EVENT, {"kind": "x", "timestamp_ns": 3}),
                (RecordKind.MESSAGE, {"a": 4, "b": 5}),
            ]
        )
    )

    # Rows are grouped by kind and routed to the matching repository method;
    # the recorder never names a table or builds a column list itself.
    assert calls == [
        ("messages", [{"a": 1, "b": 2}, {"a": 4, "b": 5}]),
        ("events", [{"kind": "x", "timestamp_ns": 3}]),
    ]


def test_start_inserts_session_row_and_close_finalizes_without_user_summary(monkeypatch):
    connection = RecorderConnection()
    recorder = SessionRecorder(FakePool(connection), make_persona(), user_id=None)

    async def run_session():
        await recorder.start()
        recorder.record_metric("LLM", "m", "llm_usage", prompt_tokens=2, completion_tokens=3)
        await recorder.close()

    async def fake_insert_metrics(*args, **kwargs):
        return None

    monkeypatch.setattr("recorder.insert_metrics", fake_insert_metrics)

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
