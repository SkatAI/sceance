"""Tests for the stall-guarded Deepgram STT service.

The guard exists because pipecat's DeepgramSTTService recovers from hard
WebSocket errors and idle timeouts, but NOT from a silently half-open socket
(audio/keepalive/finalize all send fine, yet no final transcript ever comes
back). See `deepgram_stt.py` for the full rationale.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from pipecat.frames.frames import (
    InterimTranscriptionFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
    VADUserStoppedSpeakingFrame,
)

from deepgram_stt import (
    StallGuardedDeepgramSTTService,
    _is_auth_error,
    _redact_secrets,
    _StallWatchdog,
)

# --- _StallWatchdog ---------------------------------------------------------


def test_watchdog_fires_on_stall_after_timeout():
    async def run():
        fired = asyncio.Event()
        wd = _StallWatchdog(timeout=0.05, on_stall=lambda: _set(fired))
        wd.arm()
        await asyncio.wait_for(fired.wait(), timeout=1.0)
        return fired.is_set()

    assert asyncio.run(run()) is True


def test_watchdog_does_not_fire_when_disarmed_before_timeout():
    async def run():
        fired = asyncio.Event()
        wd = _StallWatchdog(timeout=0.2, on_stall=lambda: _set(fired))
        wd.arm()
        await asyncio.sleep(0.05)
        wd.disarm()
        await asyncio.sleep(0.3)
        return fired.is_set()

    assert asyncio.run(run()) is False


def test_watchdog_rearm_fires_only_once():
    async def run():
        calls = []
        wd = _StallWatchdog(timeout=0.05, on_stall=lambda: calls.append(1))
        wd.arm()
        await asyncio.sleep(0.01)
        wd.arm()  # re-arm cancels the first timer
        await asyncio.sleep(0.2)
        return len(calls)

    assert asyncio.run(run()) == 1


async def _set(event: asyncio.Event) -> None:
    event.set()


# --- StallGuardedDeepgramSTTService frame routing ---------------------------


def _make_service(**kwargs):
    svc = StallGuardedDeepgramSTTService(api_key="test-key", **kwargs)
    return svc


class _FakeWatchdog:
    def __init__(self):
        self.armed = 0
        self.disarmed = 0

    def arm(self):
        self.armed += 1

    def disarm(self):
        self.disarmed += 1


def test_arms_watchdog_on_user_stopped_speaking_with_speech():
    svc = _make_service()
    fake = _FakeWatchdog()
    svc._watchdog = fake
    svc._note_frame_in(VADUserStoppedSpeakingFrame(stop_secs=0.8))
    assert fake.armed == 1


def test_does_not_arm_on_user_stopped_speaking_with_zero_stop_secs():
    svc = _make_service()
    fake = _FakeWatchdog()
    svc._watchdog = fake
    svc._note_frame_in(VADUserStoppedSpeakingFrame(stop_secs=0.0))
    assert fake.armed == 0


def test_disarms_watchdog_on_final_transcription():
    svc = _make_service()
    fake = _FakeWatchdog()
    svc._watchdog = fake
    svc._note_frame_out(TranscriptionFrame("hello", "user", "2026-01-01T00:00:00Z"))
    assert fake.disarmed == 1


def test_does_not_disarm_on_interim_transcription():
    svc = _make_service()
    fake = _FakeWatchdog()
    svc._watchdog = fake
    svc._note_frame_out(
        InterimTranscriptionFrame("hel", "user", "2026-01-01T00:00:00Z")
    )
    assert fake.disarmed == 0


# --- _on_stall behavior -----------------------------------------------------


def test_on_stall_triggers_reconnect():
    async def run():
        svc = _make_service()
        reconnected = []
        svc._request_reconnect = lambda: _append(reconnected)
        svc.push_frame = lambda *a, **k: _noop()
        await svc._on_stall()
        return len(reconnected)

    assert asyncio.run(run()) == 1


def test_on_stall_speaks_recovery_message_when_configured():
    async def run():
        svc = _make_service(recovery_message="Sorry, I missed that.")
        svc._request_reconnect = lambda: _noop()
        spoken = []
        svc.push_frame = lambda frame, *a, **k: _record(spoken, frame)
        await svc._on_stall()
        return spoken

    spoken = asyncio.run(run())
    assert len(spoken) == 1
    assert isinstance(spoken[0], TTSSpeakFrame)
    assert spoken[0].text == "Sorry, I missed that."


def test_on_stall_stays_silent_when_no_recovery_message():
    async def run():
        svc = _make_service()  # recovery_message defaults to None
        svc._request_reconnect = lambda: _noop()
        spoken = []
        svc.push_frame = lambda frame, *a, **k: _record(spoken, frame)
        await svc._on_stall()
        return spoken

    assert asyncio.run(run()) == []


# --- _redact_secrets --------------------------------------------------------


def test_redact_secrets_strips_deepgram_token():
    fake_key = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"  # not a real credential
    raw = f"Connection lost: headers: {{'Authorization': 'Token {fake_key}'}}, status_code: 401"
    out = _redact_secrets(raw)
    assert fake_key not in out
    assert "Token" in out  # the label stays, only the secret is removed
    assert "status_code: 401" in out  # non-secret context preserved


def test_redact_secrets_leaves_plain_text_unchanged():
    msg = "Connection lost, will retry: connection reset by peer"
    assert _redact_secrets(msg) == msg


# --- _is_auth_error ---------------------------------------------------------


def test_is_auth_error_true_for_status_code_attribute():
    class E(Exception):
        status_code = 401

    assert _is_auth_error(E()) is True


def test_is_auth_error_true_for_403():
    class E(Exception):
        status_code = 403

    assert _is_auth_error(E()) is True


def test_is_auth_error_true_from_message_text():
    exc = Exception(
        "status_code: 401, body: Websocket initialized with invalid credentials."
    )
    assert _is_auth_error(exc) is True


def test_is_auth_error_false_for_transient_error():
    assert _is_auth_error(Exception("connection reset by peer")) is False


# --- _connection_handler fail-fast ------------------------------------------


def test_connection_handler_stops_retrying_on_auth_error():
    async def run():
        svc = _make_service()
        counter = {"n": 0}

        class _AuthExc(Exception):
            status_code = 401

        class _CM:
            async def __aenter__(self_):
                counter["n"] += 1
                raise _AuthExc("HTTP 401 invalid credentials")

            async def __aexit__(self_, *a):
                return False

        class _V1:
            def connect(self_, **kw):
                return _CM()

        svc._client = SimpleNamespace(listen=SimpleNamespace(v1=_V1()))
        # If the handler retried forever, wait_for would time out and fail.
        await asyncio.wait_for(svc._connection_handler(), timeout=1.0)
        return counter["n"]

    assert asyncio.run(run()) == 1


async def _noop() -> None:
    return None


async def _append(acc: list) -> None:
    acc.append(1)


async def _record(acc: list, frame) -> None:
    acc.append(frame)
