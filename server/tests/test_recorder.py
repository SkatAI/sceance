from __future__ import annotations

import asyncio
import json
from uuid import uuid4

from personas import Persona
from recorder import RecordKind, SessionRecorder
from recording import UsageTotals
from tests.conftest import FakePool
from tests.test_personas import persona_payload


class RecorderConnection:
    def __init__(self):
        self.executed = []

    async def execute(self, query, *args):
        self.executed.append((query, args))


class FakeQueue:
    """Stand-in for RecordDrainQueue: captures enqueued rows, no real drain."""

    def __init__(self):
        self.items = []
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def enqueue(self, kind, row):
        self.items.append((kind, row))

    async def stop(self):
        self.stopped = True


def make_persona(memory=True):
    raw = persona_payload()
    raw["agent"]["memory"] = memory
    return Persona.from_dict(raw, id="agent")


def test_record_methods_enqueue_expected_rows_and_totals():
    queue = FakeQueue()
    recorder = SessionRecorder(FakePool(RecorderConnection()), make_persona(), queue=queue)

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

    assert queue.items[0][0] == RecordKind.MESSAGE
    assert queue.items[0][1]["role"] == "user"
    assert queue.items[1] == (
        RecordKind.EVENT,
        {
            "session_id": recorder.session_id,
            "kind": "joined",
            "timestamp_ns": 123,
            "payload": json.dumps({"id": "p1"}),
        },
    )
    assert recorder._totals == UsageTotals(
        prompt_tokens=10,
        completion_tokens=4,
        cache_read_tokens=3,
        cache_creation_tokens=2,
        tts_chars=11,
    )


def test_start_inserts_session_row_and_close_finalizes_without_user_summary():
    connection = RecorderConnection()
    queue = FakeQueue()
    recorder = SessionRecorder(FakePool(connection), make_persona(), user_id=None, queue=queue)

    async def run_session():
        await recorder.start()
        recorder.record_metric("LLM", "m", "llm_usage", prompt_tokens=2, completion_tokens=3)
        await recorder.close()

    asyncio.run(run_session())

    assert queue.started is True
    assert queue.stopped is True
    assert "INSERT INTO sessions" in connection.executed[0][0]
    insert_args = connection.executed[0][1]
    assert insert_args[1] == "Marie"
    assert json.loads(insert_args[2])["persona"]["name"] == "Marie"
    assert "UPDATE sessions" in connection.executed[-1][0]
    update_args = connection.executed[-1][1]
    assert update_args[1:6] == (2, 3, 0, 0, 0)


def test_close_schedules_summary_once_for_authenticated_user():
    scheduled = []

    def fake_scheduler(pool, session_id, user_id):
        scheduled.append((session_id, user_id))

    recorder = SessionRecorder(
        FakePool(RecorderConnection()),
        make_persona(),
        user_id=str(uuid4()),
        queue=FakeQueue(),
        schedule_summary=fake_scheduler,
    )

    asyncio.run(recorder.close())
    asyncio.run(recorder.close())  # idempotent: no second schedule

    assert len(scheduled) == 1


def test_close_skips_summary_when_update_memory_off():
    # Blank-slate personas still record, but must not write cross-session memory.
    scheduled = []

    def fake_scheduler(pool, session_id, user_id):
        scheduled.append((session_id, user_id))

    recorder = SessionRecorder(
        FakePool(RecorderConnection()),
        make_persona(),
        user_id=str(uuid4()),
        update_memory=False,
        queue=FakeQueue(),
        schedule_summary=fake_scheduler,
    )

    asyncio.run(recorder.close())

    assert scheduled == []
