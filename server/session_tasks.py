"""Registry of in-flight bot session tasks.

Shared by `/health` (reports the active count), `/start-session` (registers a
spawned bot task and enforces MAX_SESSIONS), and the app lifespan (cancels all
on shutdown).
"""

from __future__ import annotations

import asyncio

from loguru import logger

_active_sessions: set[asyncio.Task] = set()


def count() -> int:
    return len(_active_sessions)


def register(task: asyncio.Task) -> None:
    _active_sessions.add(task)
    task.add_done_callback(_cleanup)


def cancel_all() -> None:
    for t in list(_active_sessions):
        t.cancel()


def _cleanup(task: asyncio.Task) -> None:
    _active_sessions.discard(task)
    if task.cancelled():
        return
    try:
        task.result()
    except Exception:
        logger.exception("Bot task failed")
