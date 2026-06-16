"""Session recorder — orchestrates the session lifecycle.

The recorder owns the session row (create on `start`, finalize on `close`),
accumulates usage totals, and enqueues transcript/event/metric rows for the
background drain. The mechanical pieces live in `recording.py`:
`RecordDrainQueue` (the non-blocking queue + batched flush) and `UsageTotals`.
Cross-session memory summarization is scheduled through an injectable callable so
`close()` never spawns a background task directly.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone

import asyncpg
from loguru import logger

from memory import summarize_and_persist
from personas import Persona
from recording import RecordDrainQueue, RecordKind, UsageTotals
from settings import get_settings
from storage import finalize_session, insert_session

__all__ = ["RecordKind", "SessionRecorder", "NullSessionRecorder"]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _default_summary_scheduler(pool, session_id, user_id) -> None:
    """Fire-and-forget cross-session memory summarization. Isolated here (and
    injectable) so `SessionRecorder.close()` doesn't create background tasks
    directly."""
    asyncio.create_task(summarize_and_persist(pool, session_id, str(user_id)))


class SessionRecorder:
    """Owns a session row and a background drain queue for child rows."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        persona: Persona,
        user_id: str | None = None,
        update_memory: bool = True,
        *,
        schedule_summary=None,
        queue: RecordDrainQueue | None = None,
    ):
        self._pool = pool
        self._persona = persona
        self._user_id = uuid.UUID(user_id) if user_id else None
        # When False (blank-slate personas), the session is still recorded for
        # observability but no cross-session user memory is written at close.
        self._update_memory = update_memory
        self.session_id: uuid.UUID = uuid.uuid4()
        self._queue = queue if queue is not None else RecordDrainQueue(pool)
        self._schedule_summary = schedule_summary or _default_summary_scheduler
        self._totals = UsageTotals()
        self._closed = False

    async def start(self) -> None:
        """Create the session row, then launch the drain loop."""
        await insert_session(
            self._pool,
            session_id=self.session_id,
            persona_name=self._persona.name,
            persona_json=json.dumps(self._persona.raw),
            lang=self._persona.lang,
            started_at=_utcnow(),
            user_id=self._user_id,
            # 'local' (dev) / 'online' (deployed) / 'unknown'; lets dev/test
            # sessions be told apart from real ones on the session row.
            environment=get_settings().deploy_env,
        )
        self._queue.start()
        logger.info(f"SessionRecorder started for session {self.session_id}")

    # ---- Hot path: non-blocking enqueue ---------------------------------

    def record_message(
        self,
        role: str,
        text: str,
        language: str | None = None,
        stt_timestamp: str | None = None,
    ) -> None:
        self._queue.enqueue(RecordKind.MESSAGE, {
            "session_id": self.session_id,
            "role": role,
            "text": text,
            "language": language,
            "stt_timestamp": stt_timestamp,
            "recorded_at": _utcnow(),
        })

    def record_event(self, kind: str, timestamp_ns: int, payload: dict | None = None) -> None:
        self._queue.enqueue(RecordKind.EVENT, {
            "session_id": self.session_id,
            "kind": kind,
            "timestamp_ns": int(timestamp_ns),
            "payload": json.dumps(payload) if payload is not None else None,
        })

    def record_metric(
        self,
        processor: str,
        model: str | None,
        kind: str,
        value_num: float | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        cache_read_input_tokens: int | None = None,
        cache_creation_input_tokens: int | None = None,
        reasoning_tokens: int | None = None,
    ) -> None:
        # Update running totals (cheap, in-memory).
        if kind == "llm_usage":
            self._totals.add_llm(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cache_read_input_tokens=cache_read_input_tokens,
                cache_creation_input_tokens=cache_creation_input_tokens,
            )
        elif kind == "tts_usage" and value_num is not None:
            self._totals.add_tts(value_num)

        self._queue.enqueue(RecordKind.METRIC, {
            "session_id": self.session_id,
            "processor": processor,
            "model": model,
            "kind": kind,
            "ts": _utcnow(),
            "value_num": value_num,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cache_read_input_tokens": cache_read_input_tokens,
            "cache_creation_input_tokens": cache_creation_input_tokens,
            "reasoning_tokens": reasoning_tokens,
        })

    # ---- Shutdown -------------------------------------------------------

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True

        # Drain and stop the background queue (one final flush).
        await self._queue.stop()

        # Schedule cross-session memory summarization (isolated/injected — never a
        # raw create_task here). We do not await it: close() should return promptly.
        if self._update_memory and self._user_id is not None:
            self._schedule_summary(self._pool, self.session_id, self._user_id)

        # Finalize session row.
        try:
            await finalize_session(
                self._pool,
                session_id=self.session_id,
                ended_at=_utcnow(),
                prompt_tokens=self._totals.prompt_tokens,
                completion_tokens=self._totals.completion_tokens,
                cache_read_tokens=self._totals.cache_read_tokens,
                cache_creation_tokens=self._totals.cache_creation_tokens,
                tts_chars=self._totals.tts_chars,
            )
        except Exception as e:
            logger.exception(f"SessionRecorder finalize failed: {e}")
        logger.info(f"SessionRecorder closed for session {self.session_id}")


class NullSessionRecorder:
    """No-op recorder for memory-off (blank-slate) personas: nothing is read from
    or written to the database — no session row, transcript, metrics/events, or
    cross-session memory update. Mirrors SessionRecorder's interface so the
    pipeline, observer, and bot wiring work unchanged."""

    def __init__(self) -> None:
        self.session_id = uuid.uuid4()  # for logging only; never persisted

    async def start(self) -> None:
        pass

    def record_message(self, *args, **kwargs) -> None:
        pass

    def record_event(self, *args, **kwargs) -> None:
        pass

    def record_metric(self, *args, **kwargs) -> None:
        pass

    async def close(self) -> None:
        pass
