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
    assert persona.memory is True
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
        "memory": True,
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
    assert persona.memory is True
    assert persona.description == ""
    assert persona.opening_messages == []
    assert persona.llm_description == ""
    assert persona.temperature is None
    assert persona.tts_provider == "cartesia"
    assert persona.tts_model is None
    assert persona.stt_provider == "deepgram"
    assert persona.stt_model is None


def test_from_dict_allows_memory_to_be_disabled():
    raw = persona_payload()
    raw["agent"]["memory"] = False

    persona = Persona.from_dict(raw, id="blank")

    assert persona.memory is False


def test_text_aggregation_mode_defaults_to_sentence_when_section_absent():
    raw = persona_payload()
    raw.pop("pipecat", None)

    persona = Persona.from_dict(raw, id="default-agg")

    assert persona.text_aggregation_mode == "SENTENCE"


def test_text_aggregation_mode_read_and_normalized_from_pipecat_section():
    raw = persona_payload(pipecat={"TextAggregationMode": "token"})

    persona = Persona.from_dict(raw, id="token-agg")

    assert persona.text_aggregation_mode == "TOKEN"


def test_text_aggregation_mode_defaults_when_key_missing_in_section():
    raw = persona_payload(pipecat={})

    persona = Persona.from_dict(raw, id="empty-pipecat")

    assert persona.text_aggregation_mode == "SENTENCE"


def test_from_dict_rejects_invalid_text_aggregation_mode():
    raw = persona_payload(pipecat={"TextAggregationMode": "paragraph"})

    with pytest.raises(PersonaError, match="TextAggregationMode"):
        Persona.from_dict(raw, id="bad-agg")


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
