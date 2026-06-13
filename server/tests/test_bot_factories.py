from __future__ import annotations

import asyncio

import pytest

import bot
from personas import Persona
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


def make_persona(**changes):
    raw = persona_payload()
    for section, values in changes.items():
        raw[section].update(values)
    return Persona.from_dict(raw, id="agent")


def test_language_directive_maps_known_and_unknown_languages():
    assert "Always speak English" in bot._language_directive("en-US")
    assert "Always speak French" in bot._language_directive("fr")
    assert "Always speak English" in bot._language_directive("es")


def test_build_llm_creates_openai_service(monkeypatch):
    monkeypatch.setattr(bot, "OpenAIResponsesHttpLLMService", FakeOpenAIService)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    persona = make_persona(llm={"provider": "openai", "temperature": 0.7})

    service = bot.build_llm(persona)

    assert isinstance(service, FakeOpenAIService)
    assert service.api_key == "openai-key"
    assert service.settings.kwargs["model"] == "gpt-test"
    assert service.settings.kwargs["temperature"] == 0.7
    assert "Be concise." in service.settings.kwargs["system_instruction"]
    assert "Memory & onboarding" in service.settings.kwargs["system_instruction"]


def test_build_llm_creates_anthropic_service_with_prompt_cache(monkeypatch):
    monkeypatch.setattr(bot, "AnthropicLLMService", FakeAnthropicService)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")
    persona = make_persona(llm={"provider": "anthropic"})

    service = bot.build_llm(persona)

    assert isinstance(service, FakeAnthropicService)
    assert service.api_key == "anthropic-key"
    assert service.settings.kwargs["enable_prompt_caching"] is True


def test_build_llm_creates_groq_service(monkeypatch):
    monkeypatch.setattr(bot, "GroqLLMService", FakeGroqService)
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")
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


def test_build_tts_creates_cartesia_service(monkeypatch):
    monkeypatch.setattr(bot, "CartesiaTTSService", FakeCartesiaService)
    monkeypatch.setenv("CARTESIA_API_KEY", "cartesia-key")
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
    monkeypatch.setattr(bot, "SpeedDeepgramTTSService", FakeDeepgramTTSService)
    monkeypatch.setattr(bot, "DeepgramTTSService", FakeDeepgramTTSService)
    monkeypatch.setenv("DEEPGRAM_API_KEY", "deepgram-key")
    persona = make_persona(tts={"provider": "deepgram", "model": "aura-2"})

    service = bot.build_tts(persona)

    assert isinstance(service, FakeDeepgramTTSService)
    assert service.api_key == "deepgram-key"
    assert service.settings.kwargs == {"voice": "aura-2"}
    assert service.extra["text_aggregation_mode"] == bot.TextAggregationMode.SENTENCE
    # speed absent in persona → None forwarded (Deepgram then uses its default)
    assert service.extra["speed"] is None


def test_build_tts_forwards_deepgram_speed(monkeypatch):
    monkeypatch.setattr(bot, "SpeedDeepgramTTSService", FakeDeepgramTTSService)
    monkeypatch.setattr(bot, "DeepgramTTSService", FakeDeepgramTTSService)
    monkeypatch.setenv("DEEPGRAM_API_KEY", "deepgram-key")
    persona = make_persona(tts={"provider": "deepgram", "model": "aura-2", "speed": 1.3})

    service = bot.build_tts(persona)

    assert service.extra["speed"] == 1.3


def test_build_tts_passes_token_aggregation_mode_from_persona(monkeypatch):
    monkeypatch.setattr(bot, "CartesiaTTSService", FakeCartesiaService)
    monkeypatch.setenv("CARTESIA_API_KEY", "cartesia-key")
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

        def __init__(self, api_key, settings):
            self.api_key = api_key
            self.settings = settings

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
    monkeypatch.setattr(bot, "DeepgramSTTService", FakeSTTService)
    monkeypatch.setattr(bot, "build_tts", lambda persona: "tts")
    monkeypatch.setattr(bot, "build_llm", lambda persona: "llm")
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

        def __init__(self, api_key, settings):
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
    monkeypatch.setattr(bot, "DeepgramSTTService", FakeSTTService)
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
