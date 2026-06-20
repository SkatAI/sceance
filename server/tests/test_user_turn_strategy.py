"""Tests for the user-turn start strategy that gates interruptions.

Regression coverage for the silence bug in online session e6ec5595: a
contentless VAD blip ~0.2s after the user finished speaking was treated as the
user starting to speak again, which cancelled the in-flight LLM turn and left
nothing queued (~13s of dead air). The fix replaces the default raw-VAD turn
start with `MinWordsUserTurnStartStrategy`, so only a real transcript can start a
turn / trigger an interruption. See `bot.build_context_aggregators`.

`process_frame` returns ProcessFrameResult.STOP when the strategy starts a user
turn and CONTINUE otherwise — that return value is the assertion signal here.
"""

from __future__ import annotations

import asyncio

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
    VADUserStartedSpeakingFrame,
)
from pipecat.turns.types import ProcessFrameResult
from pipecat.turns.user_start import MinWordsUserTurnStartStrategy

_TS = "2026-01-01T00:00:00Z"


def _process(strategy, *frames) -> ProcessFrameResult:
    """Feed frames in order; return the result of the LAST frame."""

    async def run():
        result = ProcessFrameResult.CONTINUE
        for f in frames:
            result = await strategy.process_frame(f)
        return result

    return asyncio.run(run())


# --- the regression guard ---------------------------------------------------


def test_vad_start_alone_does_not_start_a_turn():
    # The exact bug: a bare VAD event (no transcript) must NOT start a user turn,
    # so it can never interrupt/cancel an in-flight LLM response.
    strategy = MinWordsUserTurnStartStrategy(min_words=2)
    assert _process(strategy, VADUserStartedSpeakingFrame()) is ProcessFrameResult.CONTINUE


# --- normal turn-taking preserved (bot idle → 1 word is enough) -------------


def test_single_word_transcript_starts_turn_when_bot_idle():
    strategy = MinWordsUserTurnStartStrategy(min_words=2)
    assert (
        _process(strategy, TranscriptionFrame("hello", "user", _TS))
        is ProcessFrameResult.STOP
    )


# --- barge-in threshold applies only while the bot is speaking --------------


def test_single_word_does_not_interrupt_while_bot_speaking():
    strategy = MinWordsUserTurnStartStrategy(min_words=2)
    result = _process(
        strategy,
        BotStartedSpeakingFrame(),
        TranscriptionFrame("hello", "user", _TS),
    )
    assert result is ProcessFrameResult.CONTINUE


def test_min_words_transcript_interrupts_while_bot_speaking():
    strategy = MinWordsUserTurnStartStrategy(min_words=2)
    result = _process(
        strategy,
        BotStartedSpeakingFrame(),
        TranscriptionFrame("hello there", "user", _TS),
    )
    assert result is ProcessFrameResult.STOP


# --- wiring guard: bot.py keeps the MinWords strategy on the user aggregator -


def test_build_context_aggregators_uses_min_words_start_strategy():
    # Guards against the config silently reverting to the raw-VAD default, which
    # would reintroduce the silence bug. Imported lazily so the model-loading
    # cost is paid only when this test runs.
    import bot

    _, user_aggregator, _ = bot.build_context_aggregators()
    start = user_aggregator._params.user_turn_strategies.start
    assert any(isinstance(s, MinWordsUserTurnStartStrategy) for s in start)
