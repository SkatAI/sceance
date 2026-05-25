"""Pipeline observer that forwards transcripts, timing, and metrics to a
SessionRecorder (in-memory queue, drained to Supabase off the audio path).

What it captures:
- Final user transcriptions → `messages` (role='user') + `events`.
- Assistant responses (LLMTextFrame chunks between Start/End) → `messages`.
- Speech / LLM / TTS lifecycle frames → `events` (for per-turn latency).
- Pipecat MetricsFrame contents (TTFB, processing time, LLM token usage,
  TTS character usage) → `metrics`, attributed to the emitting service.
"""

from __future__ import annotations

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    MetricsFrame,
    TranscriptionFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.metrics.metrics import (
    LLMUsageMetricsData,
    ProcessingMetricsData,
    TTFBMetricsData,
    TTSUsageMetricsData,
)
from pipecat.observers.base_observer import BaseObserver, FramePushed

from recorder import SessionRecorder

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
    """Forward pipeline frames to a SessionRecorder."""

    def __init__(self, recorder: SessionRecorder):
        super().__init__()
        self._rec = recorder
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
                self._rec.record_message(
                    role="user",
                    text=text,
                    language=lang,
                    stt_timestamp=frame.timestamp,
                )
                self._rec.record_event(
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
                self._rec.record_message(role="assistant", text=text)

        # Per-service metrics: TTFB, processing time, token / char usage.
        if isinstance(frame, MetricsFrame):
            for m in frame.data:
                self._record_metric(m)
            return

        # Generic lifecycle events.
        kind = _EVENT_FRAMES.get(type(frame))
        if kind is not None:
            self._rec.record_event(kind, ts)

    def _record_metric(self, m) -> None:
        processor = getattr(m, "processor", "?")
        model = getattr(m, "model", None)
        if isinstance(m, TTFBMetricsData):
            self._rec.record_metric(processor, model, "ttfb", value_num=float(m.value))
        elif isinstance(m, ProcessingMetricsData):
            self._rec.record_metric(processor, model, "processing", value_num=float(m.value))
        elif isinstance(m, LLMUsageMetricsData):
            v = m.value
            self._rec.record_metric(
                processor,
                model,
                "llm_usage",
                prompt_tokens=getattr(v, "prompt_tokens", None),
                completion_tokens=getattr(v, "completion_tokens", None),
                cache_read_input_tokens=getattr(v, "cache_read_input_tokens", None),
                cache_creation_input_tokens=getattr(v, "cache_creation_input_tokens", None),
                reasoning_tokens=getattr(v, "reasoning_tokens", None),
            )
        elif isinstance(m, TTSUsageMetricsData):
            self._rec.record_metric(processor, model, "tts_usage", value_num=float(m.value))
        # Other MetricsData subclasses (text aggregation, turn) are ignored for now.
