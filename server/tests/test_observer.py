from __future__ import annotations

import asyncio
from types import SimpleNamespace

import observer
from observer import TranscriptObserver


class Recorder:
    def __init__(self):
        self.messages = []
        self.events = []
        self.metrics = []

    def record_message(self, **kwargs):
        self.messages.append(kwargs)

    def record_event(self, *args):
        self.events.append(args)

    def record_metric(self, *args, **kwargs):
        self.metrics.append((args, kwargs))


class Transcription:
    def __init__(self, text, frame_id=1):
        self.id = frame_id
        self.text = text
        self.language = "en"
        self.timestamp = "stt-ts"
        self.user_id = "participant"


class ResponseStart:
    def __init__(self, frame_id=2):
        self.id = frame_id


class Text:
    def __init__(self, text, frame_id):
        self.id = frame_id
        self.text = text


class ResponseEnd:
    def __init__(self, frame_id=5):
        self.id = frame_id


class UserStarted:
    def __init__(self, frame_id=6):
        self.id = frame_id


class Metrics:
    def __init__(self, data, frame_id=7):
        self.id = frame_id
        self.data = data


class TTFB:
    processor = "LLM#0"
    model = "m"
    value = 0.25


class Processing:
    processor = "LLM#0"
    model = "m"
    value = 0.75


class UsageValue:
    prompt_tokens = 10
    completion_tokens = 5
    cache_read_input_tokens = 2
    cache_creation_input_tokens = 1
    reasoning_tokens = 3


class LLMUsage:
    processor = "LLM#0"
    model = "m"
    value = UsageValue()


class TTSUsage:
    processor = "TTS#0"
    model = "v"
    value = 42


def push(obs, frame, timestamp=123):
    return asyncio.run(obs.on_push_frame(SimpleNamespace(frame=frame, timestamp=timestamp)))


def test_transcription_records_non_empty_user_message_and_event(monkeypatch):
    monkeypatch.setattr(observer, "TranscriptionFrame", Transcription)
    rec = Recorder()
    obs = TranscriptObserver(rec)

    push(obs, Transcription(" hello "))
    push(obs, Transcription("ignored duplicate", frame_id=1))
    push(obs, Transcription("   ", frame_id=2))

    assert rec.messages == [
        {
            "role": "user",
            "text": "hello",
            "language": "en",
            "stt_timestamp": "stt-ts",
        }
    ]
    assert rec.events == [
        (
            "transcription",
            123,
            {"user_id": "participant", "text": "hello", "language": "en"},
        )
    ]


def test_assistant_chunks_are_buffered_between_response_frames(monkeypatch):
    monkeypatch.setattr(observer, "LLMFullResponseStartFrame", ResponseStart)
    monkeypatch.setattr(observer, "LLMTextFrame", Text)
    monkeypatch.setattr(observer, "LLMFullResponseEndFrame", ResponseEnd)
    rec = Recorder()
    obs = TranscriptObserver(rec)

    push(obs, ResponseStart())
    push(obs, Text("Hel", 3))
    push(obs, Text("lo", 4))
    push(obs, ResponseEnd())

    assert rec.messages == [{"role": "assistant", "text": "Hello"}]


def test_lifecycle_frames_record_configured_events(monkeypatch):
    monkeypatch.setattr(observer, "_EVENT_FRAMES", {UserStarted: "user_started_speaking"})
    rec = Recorder()
    obs = TranscriptObserver(rec)

    push(obs, UserStarted(), timestamp=999)

    assert rec.events == [("user_started_speaking", 999)]


def test_metrics_frame_records_supported_metric_types(monkeypatch):
    monkeypatch.setattr(observer, "MetricsFrame", Metrics)
    monkeypatch.setattr(observer, "TTFBMetricsData", TTFB)
    monkeypatch.setattr(observer, "ProcessingMetricsData", Processing)
    monkeypatch.setattr(observer, "LLMUsageMetricsData", LLMUsage)
    monkeypatch.setattr(observer, "TTSUsageMetricsData", TTSUsage)
    rec = Recorder()
    obs = TranscriptObserver(rec)

    push(obs, Metrics([TTFB(), Processing(), LLMUsage(), TTSUsage()]))

    assert rec.metrics[0] == (("LLM#0", "m", "ttfb"), {"value_num": 0.25})
    assert rec.metrics[1] == (("LLM#0", "m", "processing"), {"value_num": 0.75})
    assert rec.metrics[2] == (
        ("LLM#0", "m", "llm_usage"),
        {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "cache_read_input_tokens": 2,
            "cache_creation_input_tokens": 1,
            "reasoning_tokens": 3,
        },
    )
    assert rec.metrics[3] == (("TTS#0", "v", "tts_usage"), {"value_num": 42.0})
