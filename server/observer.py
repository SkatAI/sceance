"""Pipeline observer that persists transcripts and timing to SQLite.

Watches frames flowing through the pipeline and writes:
- Final user transcriptions as `messages` rows (role='user').
- Assistant responses, accumulated from LLMTextFrame chunks between
  LLMFullResponseStartFrame and LLMFullResponseEndFrame, as `messages`
  rows (role='assistant').
- Speech / LLM / TTS lifecycle frames as `events` rows, so per-turn
  latency can be reconstructed from the event timestamps.
"""

from __future__ import annotations

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TranscriptionFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.observers.base_observer import BaseObserver, FramePushed

from db import SessionDB


_EVENT_FRAMES: dict[type, str] = {
    UserStartedSpeakingFrame: "user_started_speaking",
    UserStoppedSpeakingFrame: "user_stopped_speaking",
    BotStartedSpeakingFrame: "bot_started_speaking",
    BotStoppedSpeakingFrame: "bot_stopped_speaking",
    LLMFullResponseStartFrame: "llm_start",
    LLMFullResponseEndFrame: "llm_end",
    TTSStartedFrame: "tts_start",
    TTSStoppedFrame: "tts_stop",
}


class TranscriptObserver(BaseObserver):
    """Persist transcripts and timing events to SQLite for a single session."""

    def __init__(self, db: SessionDB):
        super().__init__()
        self._db = db
        self._assistant_buf: list[str] = []
        self._seen_frame_ids: set[int] = set()

    async def on_push_frame(self, data: FramePushed):
        frame = data.frame
        ts = data.timestamp

        # Each frame is pushed at multiple points in the pipeline; dedupe by id.
        fid = id(frame)
        if fid in self._seen_frame_ids:
            return
        self._seen_frame_ids.add(fid)

        # User transcript (final only — interim frames are noisy).
        if isinstance(frame, TranscriptionFrame):
            text = (frame.text or "").strip()
            if text:
                lang = str(frame.language) if frame.language else None
                self._db.add_message(
                    role="user",
                    text=text,
                    language=lang,
                    stt_timestamp=frame.timestamp,
                )
                self._db.add_event(
                    "transcription",
                    ts,
                    {"user_id": frame.user_id, "text": text, "language": lang},
                )
            return

        # Assistant response: collect chunks between Start/End.
        if isinstance(frame, LLMFullResponseStartFrame):
            self._assistant_buf = []
        elif isinstance(frame, LLMTextFrame):
            if frame.text:
                self._assistant_buf.append(frame.text)
        elif isinstance(frame, LLMFullResponseEndFrame):
            text = "".join(self._assistant_buf).strip()
            self._assistant_buf = []
            if text:
                self._db.add_message(role="assistant", text=text)

        # Generic lifecycle events.
        kind = _EVENT_FRAMES.get(type(frame))
        if kind is not None:
            self._db.add_event(kind, ts)
