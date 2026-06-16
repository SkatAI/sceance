from __future__ import annotations

import asyncio

from pipecat.runner.types import DailyRunnerArguments, SmallWebRTCRunnerArguments

import cli_bot


class FakeTransport:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


def _patch_runtime(monkeypatch):
    ran = {}

    async def fake_run_bot(transport, agent_name, pool, user_id=None):
        ran["transport"] = transport
        ran["agent_name"] = agent_name
        ran["pool"] = pool

    async def fake_create_pool():
        return "pool"

    async def fake_close_pool(pool):
        ran["closed"] = pool

    monkeypatch.setattr(cli_bot, "run_bot", fake_run_bot)
    monkeypatch.setattr(cli_bot, "create_pool", fake_create_pool)
    monkeypatch.setattr(cli_bot, "close_pool", fake_close_pool)
    monkeypatch.setenv("AGENT_NAME", "marie")
    return ran


def test_bot_dispatches_daily_runner_args(monkeypatch):
    ran = _patch_runtime(monkeypatch)
    monkeypatch.setattr(cli_bot, "DailyTransport", FakeTransport)

    asyncio.run(cli_bot.bot(DailyRunnerArguments(room_url="https://room", token="tok")))

    assert isinstance(ran["transport"], FakeTransport)
    assert ran["transport"].args[:2] == ("https://room", "tok")
    assert ran["agent_name"] == "marie"
    assert ran["pool"] == "pool"
    assert ran["closed"] == "pool"


def test_bot_dispatches_smallwebrtc_runner_args(monkeypatch):
    ran = _patch_runtime(monkeypatch)
    monkeypatch.setattr(cli_bot, "SmallWebRTCTransport", FakeTransport)

    asyncio.run(cli_bot.bot(SmallWebRTCRunnerArguments(webrtc_connection="conn")))

    assert isinstance(ran["transport"], FakeTransport)
    assert ran["transport"].kwargs["webrtc_connection"] == "conn"
    assert ran["closed"] == "pool"


def test_bot_returns_early_on_unsupported_runner_args(monkeypatch):
    ran = _patch_runtime(monkeypatch)

    asyncio.run(cli_bot.bot(object()))

    # No transport built, no pool created/closed.
    assert ran == {}
