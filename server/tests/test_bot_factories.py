from __future__ import annotations

import asyncio

import pytest

import bot
import providers
from personas import Persona
from settings import get_settings
from tests.test_personas import persona_payload


class FakeOpenAIService:
    class Settings:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    def __init__(self, api_key, settings, **extra):
        self.api_key = api_key
        self.settings = settings
        self.extra = extra


class FakeAnthropicService(FakeOpenAIService):
    pass


class FakeGroqService(FakeOpenAIService):
    pass


class FakeCartesiaService(FakeOpenAIService):
    pass


class FakeDeepgramTTSService(FakeOpenAIService):
    pass


class FakeGradiumTTSService(FakeOpenAIService):
    pass


def make_persona(**changes):
    raw = persona_payload()
    for section, values in changes.items():
        raw[section].update(values)
    return Persona.from_dict(raw, id="agent")


def test_stt_recovery_message_localizes_by_language():
    # The STT stall watchdog speaks this; it must match the persona language so a
    # French session doesn't break into English on a recovery prompt.
    assert bot._stt_recovery_message("fr").startswith("Pardon")
    assert bot._stt_recovery_message("fr-FR").startswith("Pardon")
    assert "Sorry" in bot._stt_recovery_message("en-US")
    # Unknown language falls back to English.
    assert "Sorry" in bot._stt_recovery_message("es")


def test_build_llm_creates_openai_service(monkeypatch):
    monkeypatch.setattr(providers, "OpenAIResponsesHttpLLMService", FakeOpenAIService)
    monkeypatch.setattr(get_settings(), "openai_api_key", "openai-key")
    persona = make_persona(llm={"provider": "openai", "temperature": 0.7})

    service = bot.build_llm(persona)

    assert isinstance(service, FakeOpenAIService)
    assert service.api_key == "openai-key"
    assert service.settings.kwargs["model"] == "gpt-test"
    assert service.settings.kwargs["temperature"] == 0.7
    assert "Be concise." in service.settings.kwargs["system_instruction"]
    assert "Memory & onboarding" in service.settings.kwargs["system_instruction"]


def test_build_llm_creates_anthropic_service_with_prompt_cache(monkeypatch):
    monkeypatch.setattr(providers, "AnthropicLLMService", FakeAnthropicService)
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "anthropic-key")
    persona = make_persona(llm={"provider": "anthropic"})

    service = bot.build_llm(persona)

    assert isinstance(service, FakeAnthropicService)
    assert service.api_key == "anthropic-key"
    assert service.settings.kwargs["enable_prompt_caching"] is True


def test_build_llm_creates_groq_service(monkeypatch):
    monkeypatch.setattr(providers, "GroqLLMService", FakeGroqService)
    monkeypatch.setattr(get_settings(), "groq_api_key", "groq-key")
    persona = make_persona(
        llm={"provider": "groq", "model": "mistral-saba-24b", "temperature": 0.5}
    )

    service = bot.build_llm(persona)

    assert isinstance(service, FakeGroqService)
    assert service.api_key == "groq-key"
    assert service.settings.kwargs["model"] == "mistral-saba-24b"
    assert service.settings.kwargs["temperature"] == 0.5
    assert "Be concise." in service.settings.kwargs["system_instruction"]


def test_build_llm_rejects_unknown_provider():
    persona = make_persona(llm={"provider": "other"})

    with pytest.raises(ValueError, match="Unknown LLM provider"):
        bot.build_llm(persona)


def test_llm_and_tts_registries_list_supported_providers():
    # Adding a provider should be a registry entry, not an orchestration edit —
    # so the registries are the single source of truth for what's supported.
    assert set(providers.LLM_FACTORIES) == {"openai", "anthropic", "groq"}
    assert set(providers.TTS_FACTORIES) == {"cartesia", "deepgram", "gradium"}


def test_prewarm_llm_warms_the_shared_client_pool():
    # prewarm should hit the service's own _client (the pool the pipeline reuses)
    # with a cheap models.list() call.
    called = {}

    class FakeModels:
        async def list(self):
            called["list"] = True

    class FakeClient:
        models = FakeModels()

    class FakeLLM:
        _client = FakeClient()

    asyncio.run(bot.prewarm_llm(FakeLLM()))

    assert called.get("list") is True


def test_prewarm_llm_swallows_errors():
    # A prewarm failure must never break a session.
    class FakeModels:
        async def list(self):
            raise RuntimeError("offline")

    class FakeClient:
        models = FakeModels()

    class FakeLLM:
        _client = FakeClient()

    asyncio.run(bot.prewarm_llm(FakeLLM()))  # must not raise


def test_prewarm_llm_noop_without_client():
    class FakeLLM:
        pass

    asyncio.run(bot.prewarm_llm(FakeLLM()))  # no _client → no-op, no raise


def test_build_tts_creates_cartesia_service(monkeypatch):
    monkeypatch.setattr(providers, "CartesiaTTSService", FakeCartesiaService)
    monkeypatch.setattr(get_settings(), "cartesia_api_key", "cartesia-key")
    persona = make_persona(tts={"provider": "cartesia"})

    service = bot.build_tts(persona)

    assert isinstance(service, FakeCartesiaService)
    assert service.api_key == "cartesia-key"
    assert service.settings.kwargs == {
        "voice": "voice-123",
        "language": "fr",
        "model": "sonic-test",
    }
    assert service.extra["text_aggregation_mode"] == bot.TextAggregationMode.SENTENCE


def test_build_tts_requires_cartesia_voice_id():
    persona = make_persona(tts={"provider": "cartesia", "voice_id": ""})

    with pytest.raises(ValueError, match="voice_id"):
        bot.build_tts(persona)


def test_build_tts_creates_deepgram_service(monkeypatch):
    # build_tts constructs SpeedDeepgramTTSService (the speed-aware subclass) and
    # reads DeepgramTTSService.Settings; fake both.
    monkeypatch.setattr(providers, "SpeedDeepgramTTSService", FakeDeepgramTTSService)
    monkeypatch.setattr(providers, "DeepgramTTSService", FakeDeepgramTTSService)
    monkeypatch.setattr(get_settings(), "deepgram_api_key", "deepgram-key")
    persona = make_persona(tts={"provider": "deepgram", "model": "aura-2"})

    service = bot.build_tts(persona)

    assert isinstance(service, FakeDeepgramTTSService)
    assert service.api_key == "deepgram-key"
    assert service.settings.kwargs == {"voice": "aura-2"}
    assert service.extra["text_aggregation_mode"] == bot.TextAggregationMode.SENTENCE
    # speed absent in persona → None forwarded (Deepgram then uses its default)
    assert service.extra["speed"] is None


def test_build_tts_forwards_deepgram_speed(monkeypatch):
    monkeypatch.setattr(providers, "SpeedDeepgramTTSService", FakeDeepgramTTSService)
    monkeypatch.setattr(providers, "DeepgramTTSService", FakeDeepgramTTSService)
    monkeypatch.setattr(get_settings(), "deepgram_api_key", "deepgram-key")
    persona = make_persona(tts={"provider": "deepgram", "model": "aura-2", "speed": 1.3})

    service = bot.build_tts(persona)

    assert service.extra["speed"] == 1.3


def test_build_tts_creates_gradium_service(monkeypatch):
    monkeypatch.setattr(providers, "GradiumTTSService", FakeGradiumTTSService)
    monkeypatch.setattr(get_settings(), "gradium_api_key", "gradium-key")
    persona = make_persona(
        tts={
            "provider": "gradium",
            "model": "kyutai/tts-1.6b-en_fr",
            "voice_id": "_6Aslh2DxfmnRLmP",
        }
    )

    service = bot.build_tts(persona)

    assert isinstance(service, FakeGradiumTTSService)
    assert service.api_key == "gradium-key"
    assert service.settings.kwargs == {
        "voice": "_6Aslh2DxfmnRLmP",
        "language": "fr",
        "model": "kyutai/tts-1.6b-en_fr",
    }
    assert service.extra["text_aggregation_mode"] == bot.TextAggregationMode.SENTENCE


def test_build_tts_requires_gradium_voice_id():
    persona = make_persona(tts={"provider": "gradium", "voice_id": ""})

    with pytest.raises(ValueError, match="gradium TTS requires tts.voice_id"):
        bot.build_tts(persona)


def test_build_tts_passes_token_aggregation_mode_from_persona(monkeypatch):
    monkeypatch.setattr(providers, "CartesiaTTSService", FakeCartesiaService)
    monkeypatch.setattr(get_settings(), "cartesia_api_key", "cartesia-key")
    raw = persona_payload(pipecat={"TextAggregationMode": "TOKEN"})
    persona = Persona.from_dict(raw, id="token-agent")

    service = bot.build_tts(persona)

    assert service.extra["text_aggregation_mode"] == bot.TextAggregationMode.TOKEN


def test_build_tts_requires_deepgram_model():
    persona = make_persona(tts={"provider": "deepgram", "model": ""})

    with pytest.raises(ValueError, match="tts.model"):
        bot.build_tts(persona)


def test_build_tts_rejects_unknown_provider():
    persona = make_persona(tts={"provider": "other"})

    with pytest.raises(ValueError, match="Unknown TTS provider"):
        bot.build_tts(persona)


def test_run_bot_wires_pipeline_and_kickoff_with_memory(monkeypatch):
    persona = make_persona()
    persona.opening_messages = [{"role": "system", "content": "Opening."}]
    context_messages = []
    recorded_messages = []
    handlers = {}
    queued_frames = []
    recorder_events = []

    class FakeSTTService:
        class Settings:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        def __init__(self, api_key, settings, recovery_message=None, **kwargs):
            self.api_key = api_key
            self.settings = settings
            self.recovery_message = recovery_message

    class FakeContext:
        def add_message(self, message):
            context_messages.append(message)

    class FakeAggregatorPair:
        def __init__(self, context, user_params=None):
            self.user = "user-aggregator"
            self.assistant = "assistant-aggregator"

        def __iter__(self):
            return iter((self.user, self.assistant))

    class FakePipeline:
        def __init__(self, parts):
            self.parts = parts

    class FakeRtvi:
        def event_handler(self, name):
            def decorator(fn):
                handlers[f"rtvi:{name}"] = fn
                return fn

            return decorator

    class FakeTask:
        def __init__(self, pipeline, params=None, observers=None):
            self.pipeline = pipeline
            self.params = params
            self.observers = observers
            self.rtvi = FakeRtvi()

        async def queue_frames(self, frames):
            queued_frames.extend(frames)

        async def cancel(self):
            recorder_events.append("cancel")

    class FakeRunner:
        def __init__(self, handle_sigint):
            self.handle_sigint = handle_sigint

        async def run(self, task):
            await handlers["daily:on_first_participant_joined"](transport, {"id": "p1"})
            await handlers["daily:on_first_participant_joined"](transport, {"id": "p1"})
            await handlers["daily:on_client_disconnected"](transport, {"id": "p1"})

    class FakeRecorder:
        def __init__(self, pool, persona, user_id=None, update_memory=True):
            self.session_id = "session-id"
            self.pool = pool
            self.persona = persona
            self.user_id = user_id
            self.update_memory = update_memory

        async def start(self):
            recorder_events.append("start")

        def record_message(self, role, text):
            recorded_messages.append({"role": role, "text": text})

        async def close(self):
            recorder_events.append("close")

    class FakeObserver:
        def __init__(self, recorder):
            self.recorder = recorder
            self.finalized = False

        def finalize_tts_chars(self):
            self.finalized = True

    class FakeTransport:
        def input(self):
            return "transport-input"

        def output(self):
            return "transport-output"

        def event_handler(self, name):
            def decorator(fn):
                handlers[f"daily:{name}"] = fn
                return fn

            return decorator

    transport = FakeTransport()
    monkeypatch.setattr(bot, "load_persona", lambda agent_name: persona)
    monkeypatch.setattr(bot, "StallGuardedDeepgramSTTService", FakeSTTService)
    monkeypatch.setattr(bot, "build_tts", lambda persona: "tts")
    monkeypatch.setattr(bot, "build_llm", lambda persona: "llm")

    prewarmed = []

    async def fake_prewarm(llm):
        prewarmed.append(llm)

    monkeypatch.setattr(bot, "prewarm_llm", fake_prewarm)
    monkeypatch.setattr(bot, "LLMContext", FakeContext)
    monkeypatch.setattr(bot, "LLMContextAggregatorPair", FakeAggregatorPair)
    monkeypatch.setattr(bot, "LLMUserAggregatorParams", lambda **kwargs: kwargs)
    monkeypatch.setattr(bot, "SileroVADAnalyzer", lambda: "vad")
    monkeypatch.setattr(bot, "Pipeline", FakePipeline)
    monkeypatch.setattr(bot, "PipelineParams", lambda **kwargs: kwargs)
    monkeypatch.setattr(bot, "PipelineTask", FakeTask)
    monkeypatch.setattr(bot, "PipelineRunner", FakeRunner)
    monkeypatch.setattr(bot, "SessionRecorder", FakeRecorder)
    monkeypatch.setattr(bot, "TranscriptObserver", FakeObserver)
    async def fake_load_memory_brief(pool, user_id):
        return "memory brief"

    monkeypatch.setattr(bot, "LLMRunFrame", lambda: "run-frame")
    monkeypatch.setattr(bot, "load_memory_brief", fake_load_memory_brief)

    asyncio.run(bot.run_bot(transport, "agent", "pool", user_id="user-1"))

    assert recorder_events == ["start", "close", "cancel"]
    assert context_messages == [
        {"role": "user", "content": "memory brief"},
        {"role": "system", "content": "Opening."},
    ]
    assert recorded_messages == [{"role": "system", "text": "Opening."}]
    assert queued_frames == ["run-frame"]
    assert prewarmed == ["llm"]  # connection pre-warm fired for the built LLM


def test_run_bot_records_but_skips_memory_when_persona_memory_off(monkeypatch):
    # Blank-slate personas (memory off) must still be recorded for the dashboard,
    # but with cross-session memory decoupled: no brief retrieval, and the
    # recorder is told not to write user memory (update_memory=False).
    persona = make_persona(agent={"memory": False})
    captured = {}

    class FakeSTTService:
        class Settings:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        def __init__(self, api_key, settings, recovery_message=None, **kwargs):
            self.settings = settings

    class FakeAggregatorPair:
        def __init__(self, context, user_params=None):
            pass

        def __iter__(self):
            return iter(("user-aggregator", "assistant-aggregator"))

    class FakeRtvi:
        def event_handler(self, name):
            return lambda fn: fn

    class FakeTask:
        def __init__(self, *args, **kwargs):
            self.rtvi = FakeRtvi()

    class FakeRunner:
        def __init__(self, handle_sigint):
            pass

        async def run(self, task):
            captured["ran"] = True

    class FakeRecorder:
        def __init__(self, pool, persona, user_id=None, update_memory=True):
            captured["update_memory"] = update_memory
            self.session_id = "sid"

        async def start(self):
            captured["started"] = True

        def record_message(self, *args, **kwargs):
            pass

        async def close(self):
            pass

    class FakeObserver:
        def __init__(self, recorder):
            pass

        def finalize_tts_chars(self):
            pass

    class FakeTransport:
        def input(self):
            return "in"

        def output(self):
            return "out"

        def event_handler(self, name):
            return lambda fn: fn

    def fail_load_memory(pool, user_id):
        raise AssertionError("memory brief must not load when memory is off")

    monkeypatch.setattr(bot, "load_persona", lambda agent_name: persona)
    monkeypatch.setattr(bot, "StallGuardedDeepgramSTTService", FakeSTTService)
    monkeypatch.setattr(bot, "build_tts", lambda persona: "tts")
    monkeypatch.setattr(bot, "build_llm", lambda persona: "llm")
    monkeypatch.setattr(bot, "LLMContext", lambda: object())
    monkeypatch.setattr(bot, "LLMContextAggregatorPair", FakeAggregatorPair)
    monkeypatch.setattr(bot, "LLMUserAggregatorParams", lambda **kwargs: kwargs)
    monkeypatch.setattr(bot, "SileroVADAnalyzer", lambda: "vad")
    monkeypatch.setattr(bot, "Pipeline", lambda parts: parts)
    monkeypatch.setattr(bot, "PipelineParams", lambda **kwargs: kwargs)
    monkeypatch.setattr(bot, "PipelineTask", FakeTask)
    monkeypatch.setattr(bot, "PipelineRunner", FakeRunner)
    monkeypatch.setattr(bot, "SessionRecorder", FakeRecorder)
    monkeypatch.setattr(bot, "TranscriptObserver", FakeObserver)
    monkeypatch.setattr(bot, "load_memory_brief", fail_load_memory)

    asyncio.run(bot.run_bot(FakeTransport(), "agent", "pool", user_id="user-1"))

    assert captured["started"] is True
    assert captured["update_memory"] is False
    assert captured.get("ran") is True
