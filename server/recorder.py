"""Non-blocking session recorder.

The observer pushes records onto an in-memory `asyncio.Queue` (microsecond cost,
zero awaits) and a background task drains them in batches to Supabase. This
keeps the audio pipeline off the network round-trip path.

Trade-off: if the process crashes mid-session, up to one batch interval of
records is lost. Acceptable per the plan.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any

import asyncpg
from loguru import logger

from storage import bulk_insert

BATCH_MAX = 50
BATCH_INTERVAL_S = 1.0
QUEUE_MAX = 10_000


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SessionRecorder:
    """Owns a session row and a background drain loop for child rows."""

    def __init__(self, pool: asyncpg.Pool, persona: dict, user_id: str | None = None):
        self._pool = pool
        self._persona = persona
        self._user_id = uuid.UUID(user_id) if user_id else None
        self.session_id: uuid.UUID = uuid.uuid4()
        self._queue: asyncio.Queue[tuple[str, dict] | None] = asyncio.Queue(maxsize=QUEUE_MAX)
        self._drain_task: asyncio.Task | None = None
        self._closed = False
        # Token / character totals, updated as llm_usage / tts_usage flow by.
        self._totals = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
            "tts_chars": 0,
        }

    async def start(self) -> None:
        """Create the session row, then launch the drain loop."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO sessions (id, persona_name, persona_json, lang, started_at, user_id)
                VALUES ($1, $2, $3::jsonb, $4, $5, $6)
                """,
                self.session_id,
                self._persona.get("name"),
                json.dumps(self._persona),
                self._persona.get("lang"),
                _utcnow(),
                self._user_id,
            )
        self._drain_task = asyncio.create_task(self._drain_loop())
        logger.info(f"SessionRecorder started for session {self.session_id}")

    # ---- Hot path: non-blocking enqueue ---------------------------------

    def record_message(
        self,
        role: str,
        text: str,
        language: str | None = None,
        stt_timestamp: str | None = None,
    ) -> None:
        self._enqueue("messages", {
            "session_id": self.session_id,
            "role": role,
            "text": text,
            "language": language,
            "stt_timestamp": stt_timestamp,
            "recorded_at": _utcnow(),
        })

    def record_event(self, kind: str, timestamp_ns: int, payload: dict | None = None) -> None:
        self._enqueue("events", {
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
            self._totals["prompt_tokens"] += prompt_tokens or 0
            self._totals["completion_tokens"] += completion_tokens or 0
            self._totals["cache_read_tokens"] += cache_read_input_tokens or 0
            self._totals["cache_creation_tokens"] += cache_creation_input_tokens or 0
        elif kind == "tts_usage" and value_num is not None:
            self._totals["tts_chars"] += int(value_num)

        self._enqueue("metrics", {
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

    def _enqueue(self, table: str, row: dict[str, Any]) -> None:
        if self._closed:
            return
        try:
            self._queue.put_nowait((table, row))
        except asyncio.QueueFull:
            logger.warning(f"SessionRecorder queue full; dropping {table} row")

    # ---- Cold path: background drain ------------------------------------

    async def _drain_loop(self) -> None:
        """Pull from the queue, batch by table, flush to Supabase."""
        try:
            while True:
                batch: list[tuple[str, dict]] = []
                try:
                    item = await asyncio.wait_for(self._queue.get(), timeout=BATCH_INTERVAL_S)
                except asyncio.TimeoutError:
                    continue
                if item is None:  # sentinel: shutdown
                    break
                batch.append(item)
                # Drain whatever else is sitting in the queue, up to BATCH_MAX.
                while len(batch) < BATCH_MAX:
                    try:
                        nxt = self._queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    if nxt is None:
                        await self._flush(batch)
                        return
                    batch.append(nxt)
                await self._flush(batch)
        except asyncio.CancelledError:
            # Best-effort final flush.
            leftover: list[tuple[str, dict]] = []
            while True:
                try:
                    leftover.append(self._queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            await self._flush([x for x in leftover if x is not None])
            raise

    async def _flush(self, batch: list[tuple[str, dict]]) -> None:
        if not batch:
            return
        # Group by table; preserve column order per table.
        by_table: dict[str, list[dict]] = {}
        for table, row in batch:
            by_table.setdefault(table, []).append(row)
        for table, rows in by_table.items():
            columns = list(rows[0].keys())
            try:
                await bulk_insert(
                    self._pool,
                    table,
                    columns,
                    [[r[c] for c in columns] for r in rows],
                )
            except Exception as e:
                logger.exception(f"SessionRecorder flush to {table} failed: {e}")

    # ---- Shutdown -------------------------------------------------------

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        # Signal drain loop to exit after one final flush.
        try:
            self._queue.put_nowait(None)
        except asyncio.QueueFull:
            pass
        if self._drain_task is not None:
            try:
                await asyncio.wait_for(self._drain_task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("SessionRecorder drain loop did not finish in time; cancelling")
                self._drain_task.cancel()
                try:
                    await self._drain_task
                except (asyncio.CancelledError, Exception):
                    pass

        # Finalize session row.
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE sessions
                       SET ended_at                    = $1,
                           total_prompt_tokens         = $2,
                           total_completion_tokens     = $3,
                           total_cache_read_tokens     = $4,
                           total_cache_creation_tokens = $5,
                           total_tts_chars             = $6
                     WHERE id = $7
                    """,
                    _utcnow(),
                    self._totals["prompt_tokens"],
                    self._totals["completion_tokens"],
                    self._totals["cache_read_tokens"],
                    self._totals["cache_creation_tokens"],
                    self._totals["tts_chars"],
                    self.session_id,
                )
        except Exception as e:
            logger.exception(f"SessionRecorder finalize failed: {e}")
        logger.info(f"SessionRecorder closed for session {self.session_id}")
