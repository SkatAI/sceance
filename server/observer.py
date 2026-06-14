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
        # Fallback TTS char accounting. Some TTS services (e.g. Pipecat's
        # WebSocket DeepgramTTSService) never emit TTSUsageMetricsData, so
        # tts_chars would stay 0. We tally the assistant transcript length and,
        # at finalize, synthesize a tts_usage metric *only if* the provider
        # never reported its own usage — avoiding double-counting for services
        # that do (Cartesia). See finalize_tts_chars().
        self._assistant_chars = 0
        self._provider_tts_usage_seen = False
        self._tts_chars_finalized = False

    async def on_push_frame(self, data: FramePushed):
        frame = data.frame
        ts = data.timestamp

        # Each frame is pushed at multiple points in the pipeline; dedupe by
        # the frame's own monotonic id. (Earlier we used Python's id(), but
        # CPython recycles addresses on GC, so short-lived LLMTextFrame chunks
        # collided and got silently dropped — truncating assistant turns.)
        fid = getattr(frame, "id", None)
        if fid is None:
            fid = id(frame)
        if fid in self._seen_frame_ids:
            return
        # Speaking events are *broadcast*: Pipecat pushes two distinct frame
        # instances (downstream + upstream) with different ids, linked via
        # broadcast_sibling_id. Deduping on id alone lets both through and the
        # events table double-records every speaking event. Skip a frame whose
        # sibling we've already recorded. No-op for non-broadcast frames
        # (broadcast_sibling_id is None).
        sibling_id = getattr(frame, "broadcast_sibling_id", None)
        if sibling_id is not None and sibling_id in self._seen_frame_ids:
            self._seen_frame_ids.add(fid)  # so this instance's later edges skip too
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
                self._assistant_chars += len(text)

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
            self._provider_tts_usage_seen = True
            self._rec.record_metric(processor, model, "tts_usage", value_num=float(m.value))
        # Other MetricsData subclasses (text aggregation, turn) are ignored for now.

    def finalize_tts_chars(self) -> None:
        """Emit an estimated tts_usage metric from the assistant transcript
        length when the TTS provider never reported its own usage.

        Idempotent and a no-op when the provider self-reported (Cartesia) or no
        assistant text was spoken. Call once at session end, before closing the
        recorder, so the synthesized count lands in the session totals.
        """
        if self._tts_chars_finalized:
            return
        self._tts_chars_finalized = True
        if self._provider_tts_usage_seen or self._assistant_chars <= 0:
            return
        self._rec.record_metric(
            "TranscriptObserver (estimated)",
            None,
            "tts_usage",
            value_num=float(self._assistant_chars),
        )
