"""Local CLI runner for the bot (Pipecat dev runner: Daily or SmallWebRTC).

Production joins a Daily room via `bot.run_daily_bot` from `/start-session`.
This module is the local development entry point — run with::

    uv run cli_bot.py

`pipecat.runner.run.main` picks Daily or SmallWebRTC from the CLI args and calls
`bot(runner_args)` below. Keeping it (and the SmallWebRTC transport imports) out
of `bot.py` means the production `/start-session` import path never loads the
SmallWebRTC stack.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from loguru import logger
from pipecat.runner.types import (
    DailyRunnerArguments,
    RunnerArguments,
    SmallWebRTCRunnerArguments,
)
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.daily.transport import DailyParams, DailyTransport
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

from bot import run_bot
from storage import close_pool, create_pool

load_dotenv(override=True)


async def bot(runner_args: RunnerArguments):
    """Main bot entry point for the Pipecat dev runner."""
    transport = None

    match runner_args:
        case DailyRunnerArguments():
            transport = DailyTransport(
                runner_args.room_url,
                runner_args.token,
                "Pipecat Bot",
                params=DailyParams(
                    audio_in_enabled=True,
                    audio_out_enabled=True,
                ),
            )
        case SmallWebRTCRunnerArguments():
            webrtc_connection: SmallWebRTCConnection = runner_args.webrtc_connection

            transport = SmallWebRTCTransport(
                webrtc_connection=webrtc_connection,
                params=TransportParams(
                    audio_in_enabled=True,
                    audio_out_enabled=True,
                ),
            )
        case _:
            logger.error(f"Unsupported runner arguments type: {type(runner_args)}")
            return

    pool = await create_pool()
    try:
        await run_bot(transport, os.getenv("AGENT_NAME", ""), pool)
    finally:
        await close_pool(pool)


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
