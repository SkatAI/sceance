"""Deepgram STT with a stall watchdog that forces a reconnect on a dead socket.

Pipecat's `DeepgramSTTService` (1.2.x) already recovers from the failure modes
that *raise* or *close*:

- idle timeout    → `_keepalive_handler` sends KeepAlive every 5s
- hard WS error   → `_connection_handler` retry loop reconnects
- `send_media` failure → connection dropped + reconnected
- VAD stop        → `Finalize` is sent to flush a final transcript

It does **not** recover from a *silently half-open* socket: audio, keepalive,
and finalize all send fine (TCP accepts them, no exception is raised), yet
Deepgram returns no `ListenV1Results`. The built-in `stt_ttfb_timeout` only
reports a metric in that case — it never re-establishes the connection. The
result is a session that goes deaf after one turn until the caller hangs up
(observed in session e5b1d767-…: 24s STT TTFB, no final transcript, no LLM
turn). See the project memory `stt-resilience-defenses` for the incident.

`StallGuardedDeepgramSTTService` adds the missing layer: when the user stops
speaking but no final transcript arrives within `stall_timeout` seconds, it
forces a reconnect (via the base class's `_request_reconnect`, which defers
safely if the user is mid-utterance) so the *next* turn lands on a healthy
socket. Optionally it speaks a `recovery_message` so the dead air is audible
and the caller knows to repeat themselves.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from loguru import logger
from pipecat.frames.frames import (
    Frame,
    TranscriptionFrame,
    TTSSpeakFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.deepgram.stt import DeepgramSTTService

# Longer than any legitimate VAD-stop → final-transcript gap (finals normally
# land in well under 2s once Finalize is sent), so the watchdog only trips on a
# genuine stall, not on a slow-but-working response.
DEFAULT_STALL_TIMEOUT_S = 6.0


class _StallWatchdog:
    """A re-armable one-shot timer that calls `on_stall` if not disarmed in time.

    `on_stall` is an async, zero-argument callable. `arm()` (re)starts the
    countdown; `disarm()` cancels it. Both are cheap and synchronous so they can
    be called from the frame hot path.
    """

    def __init__(self, timeout: float, on_stall: Callable[[], Coroutine[Any, Any, None]]):
        self._timeout = timeout
        self._on_stall = on_stall
        self._task: asyncio.Task | None = None

    def arm(self) -> None:
        self.disarm()
        self._task = asyncio.create_task(self._run())

    def disarm(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None

    async def _run(self) -> None:
        try:
            await asyncio.sleep(self._timeout)
        except asyncio.CancelledError:
            return
        await self._on_stall()


class StallGuardedDeepgramSTTService(DeepgramSTTService):
    """DeepgramSTTService that reconnects when a turn produces no final transcript."""

    def __init__(
        self,
        *args,
        stall_timeout: float = DEFAULT_STALL_TIMEOUT_S,
        recovery_message: str | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._stall_timeout = stall_timeout
        self._recovery_message = recovery_message
        self._watchdog = _StallWatchdog(stall_timeout, self._on_stall)

    # ---- Frame routing --------------------------------------------------

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        self._note_frame_in(frame)

    async def push_frame(
        self, frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM
    ) -> None:
        await super().push_frame(frame, direction)
        self._note_frame_out(frame)

    def _note_frame_in(self, frame: Frame) -> None:
        # The user finished a real utterance — a final transcript should follow
        # shortly. Arm the watchdog. stop_secs == 0 marks a non-speech VAD
        # artifact (mirrors the base TTFB logic), which produces no transcript,
        # so arming on it would cause a spurious reconnect.
        if isinstance(frame, VADUserStoppedSpeakingFrame) and frame.stop_secs:
            self._watchdog.arm()

    def _note_frame_out(self, frame: Frame) -> None:
        # A final transcript arrived (InterimTranscriptionFrame is a distinct
        # type, not a subclass), so the socket is alive — stand down.
        if isinstance(frame, TranscriptionFrame):
            self._watchdog.disarm()

    # ---- Recovery -------------------------------------------------------

    async def _on_stall(self) -> None:
        logger.warning(
            f"{self}: no final transcript {self._stall_timeout}s after user stopped "
            f"speaking — forcing STT reconnect"
        )
        await self._request_reconnect()
        if self._recovery_message:
            await self.push_frame(TTSSpeakFrame(self._recovery_message))

    # ---- Lifecycle ------------------------------------------------------

    async def stop(self, frame) -> None:
        self._watchdog.disarm()
        await super().stop(frame)

    async def cancel(self, frame) -> None:
        self._watchdog.disarm()
        await super().cancel(frame)
