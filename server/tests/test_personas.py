from __future__ import annotations

import json

import pytest

import personas
from personas import Persona, PersonaError, load_persona


def persona_payload(**overrides):
    payload = {
        "agent": {"active": True, "lang": "fr"},
        "persona": {
            "name": "Marie",
            "description": "A careful coach",
            "system_prompt": "Be concise.",
            "opening_messages": [{"role": "system", "content": "Start."}],
            "page_intro": "Bonjour",
            "cta": "Talk",
        },
        "llm": {
            "provider": "OpenAI",
            "model": "gpt-test",
            "description": "test model",
            "temperature": 0.4,
        },
        "tts": {
            "provider": "Cartesia",
            "model": "sonic-test",
            "voice_id": "voice-123",
            "voice_name": "Calm",
            "voice_description": "Soft voice",
        },
        "stt": {"provider": "Deepgram", "model": "nova-test"},
    }
    payload.update(overrides)
    return payload


def test_from_dict_normalizes_provider_names_and_keeps_public_subset():
    persona = Persona.from_dict(persona_payload(), id="marie")

    assert persona.id == "marie"
    assert persona.active is True
    assert persona.lang == "fr"
    assert persona.llm_provider == "openai"
    assert persona.tts_provider == "cartesia"
    assert persona.stt_provider == "deepgram"
    assert persona.temperature == 0.4
    assert persona.public() == {
        "id": "marie",
        "name": "Marie",
        "description": "A careful coach",
        "lang": "fr",
        "voice_name": "Calm",
        "voice_description": "Soft voice",
        "llm": "test model",
        "tts_provider": "cartesia",
    }


def test_from_dict_uses_optional_defaults():
    raw = persona_payload()
    raw.pop("stt")
    raw["agent"].pop("lang")
    raw["persona"].pop("description")
    raw["persona"].pop("opening_messages")
    raw["llm"].pop("description")
    raw["llm"].pop("temperature")
    raw["tts"].pop("provider")
    raw["tts"].pop("model")

    persona = Persona.from_dict(raw, id="defaults")

    assert persona.lang == "en"
    assert persona.description == ""
    assert persona.opening_messages == []
    assert persona.llm_description == ""
    assert persona.temperature is None
    assert persona.tts_provider == "cartesia"
    assert persona.tts_model is None
    assert persona.stt_provider == "deepgram"
    assert persona.stt_model is None


def test_from_dict_rejects_missing_required_fields():
    raw = persona_payload()
    raw["persona"]["system_prompt"] = ""

    with pytest.raises(PersonaError, match="persona.system_prompt"):
        Persona.from_dict(raw, id="broken")


def test_from_dict_rejects_missing_sections():
    raw = persona_payload()
    raw.pop("llm")

    with pytest.raises(PersonaError, match="missing or invalid 'llm' section"):
        Persona.from_dict(raw, id="broken")


def test_load_persona_reads_from_configured_directory(tmp_path, monkeypatch):
    persona_file = tmp_path / "test_agent.json"
    persona_file.write_text(json.dumps(persona_payload()), encoding="utf-8")
    monkeypatch.setattr(personas, "PERSONAS_DIR", tmp_path)

    persona = load_persona(" test_agent ")

    assert persona.id == "test_agent"
    assert persona.name == "Marie"
