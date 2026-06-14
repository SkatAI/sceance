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
import re
from collections.abc import Callable, Coroutine
from typing import Any

from deepgram.core.events import EventType
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

# Pause between transient reconnect attempts, so a flapping connection doesn't
# hammer Deepgram (and flood the logs) several times a second.
RECONNECT_BACKOFF_S = 1.0

# Deepgram dumps the request headers — including `Authorization: Token <key>` —
# into the exception it raises on a failed WebSocket handshake, and pipecat logs
# that exception verbatim. Strip any `Token <secret>` before logging so the API
# key never lands in DigitalOcean's log store.
_TOKEN_RE = re.compile(r"(?i)(token\s+)([A-Za-z0-9._-]{12,})")


def _redact_secrets(text: str) -> str:
    """Replace `Token <secret>` occurrences with a redaction marker."""
    return _TOKEN_RE.sub(r"\1«redacted»", text)


def _is_auth_error(exc: Exception) -> bool:
    """True if `exc` is a non-retryable Deepgram auth failure (401/403).

    Checks structured status-code attributes first, then falls back to the
    error text, since the exact exception type varies across the deepgram-sdk /
    websockets stack.
    """
    for path in (("status_code",), ("response", "status_code"), ("code",)):
        obj: Any = exc
        for attr in path:
            obj = getattr(obj, attr, None)
        if obj in (401, 403):
            return True
    text = str(exc).lower()
    if re.search(r"status_code:\s*40[13]\b", text):
        return True
    return any(
        marker in text
        for marker in ("http 401", "http 403", "invalid credentials", "unauthorized")
    )


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

    # ---- Connection loop ------------------------------------------------

    async def _connection_handler(self) -> None:
        """Manage the WebSocket lifecycle, failing fast on auth errors.

        Mirrors pipecat 1.2.x ``DeepgramSTTService._connection_handler`` (the
        connect → listen → cleanup loop) with two changes, both addressing
        prod incidents:

        - **Redacted logging**: the Deepgram handshake exception embeds the API
          key (``Authorization: Token <key>``); we scrub it before logging.
        - **Fail-fast on 401/403**: an invalid credential never recovers, so we
          stop instead of reconnecting ~1.5×/s forever (log flood + wasted CPU).
          Transient errors still retry, now with a short backoff.

        Revisit if the pinned pipecat version changes this method.
        """
        while True:
            connect_kwargs = self._build_connect_kwargs()
            keepalive_task = None
            try:
                async with self._client.listen.v1.connect(**connect_kwargs) as connection:
                    self._connection = connection
                    self._connection_ready.set()
                    connection.on(EventType.MESSAGE, self._on_message)
                    connection.on(EventType.ERROR, self._on_error)
                    logger.debug(f"{self}: Websocket connection initialized")
                    keepalive_task = self.create_task(
                        self._keepalive_handler(), f"{self}::keepalive"
                    )
                    await connection.start_listening()
            except Exception as e:
                if _is_auth_error(e):
                    logger.error(
                        f"{self}: Deepgram rejected the credentials (401/403) — "
                        f"check DEEPGRAM_API_KEY. Not retrying."
                    )
                    await self.push_error(f"{self}: Deepgram authentication failed")
                    return
                logger.warning(
                    f"{self}: Connection lost, will retry: {_redact_secrets(str(e))}"
                )
                await asyncio.sleep(RECONNECT_BACKOFF_S)
            finally:
                self._connection_ready.clear()
                self._connection = None
                if keepalive_task:
                    await self.cancel_task(keepalive_task)

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
