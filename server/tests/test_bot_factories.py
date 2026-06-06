from __future__ import annotations

import pytest

import bot
from personas import Persona
from tests.test_personas import persona_payload


class FakeOpenAIService:
    class Settings:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    def __init__(self, api_key, settings):
        self.api_key = api_key
        self.settings = settings


class FakeAnthropicService(FakeOpenAIService):
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


def test_build_tts_requires_cartesia_voice_id():
    persona = make_persona(tts={"provider": "cartesia", "voice_id": ""})

    with pytest.raises(ValueError, match="voice_id"):
        bot.build_tts(persona)


def test_build_tts_creates_deepgram_service(monkeypatch):
    monkeypatch.setattr(bot, "DeepgramTTSService", FakeDeepgramTTSService)
    monkeypatch.setenv("DEEPGRAM_API_KEY", "deepgram-key")
    persona = make_persona(tts={"provider": "deepgram", "model": "aura-2"})

    service = bot.build_tts(persona)

    assert isinstance(service, FakeDeepgramTTSService)
    assert service.api_key == "deepgram-key"
    assert service.settings.kwargs == {"voice": "aura-2"}


def test_build_tts_requires_deepgram_model():
    persona = make_persona(tts={"provider": "deepgram", "model": ""})

    with pytest.raises(ValueError, match="tts.model"):
        bot.build_tts(persona)


def test_build_tts_rejects_unknown_provider():
    persona = make_persona(tts={"provider": "other"})

    with pytest.raises(ValueError, match="Unknown TTS provider"):
        bot.build_tts(persona)
