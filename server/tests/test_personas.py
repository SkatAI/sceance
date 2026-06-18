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


def test_visibility_defaults_to_public_and_parses_admin():
    assert Persona.from_dict(persona_payload(), id="marie").visibility == "public"

    admin = persona_payload()
    admin["agent"]["visibility"] = "ADMIN"  # normalized to lowercase
    assert Persona.from_dict(admin, id="marie").visibility == "admin"


def test_invalid_visibility_raises():
    bad = persona_payload()
    bad["agent"]["visibility"] = "secret"
    with pytest.raises(PersonaError, match="visibility"):
        Persona.from_dict(bad, id="marie")


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


def test_tts_speed_defaults_to_none_when_absent():
    persona = Persona.from_dict(persona_payload(), id="no-speed")

    assert persona.tts_speed is None


def test_tts_speed_is_parsed_as_float():
    raw = persona_payload()
    raw["tts"]["speed"] = 1.2

    persona = Persona.from_dict(raw, id="fast")

    assert persona.tts_speed == 1.2


def test_tts_speed_rejects_out_of_range():
    raw = persona_payload()
    raw["tts"]["speed"] = 2.0

    with pytest.raises(PersonaError, match="tts.speed.*between 0.7 and 1.5"):
        Persona.from_dict(raw, id="too-fast")


def test_tts_speed_rejects_non_numeric():
    raw = persona_payload()
    raw["tts"]["speed"] = "fast"

    with pytest.raises(PersonaError, match="tts.speed.*must be a number"):
        Persona.from_dict(raw, id="bad-speed")


def test_from_dict_rejects_invalid_text_aggregation_mode():
    raw = persona_payload(pipecat={"TextAggregationMode": "paragraph"})

    with pytest.raises(PersonaError, match="TextAggregationMode"):
        Persona.from_dict(raw, id="bad-agg")


def test_from_dict_rejects_missing_required_fields():
    raw = persona_payload()
    raw["persona"]["system_prompt"] = ""

    with pytest.raises(PersonaError, match="persona.system_prompt"):
        Persona.from_dict(raw, id="broken")


def test_system_prompt_path_resolves_and_bakes_into_raw(tmp_path):
    prompt_file = tmp_path / "spock.md"
    prompt_file.write_text("Be logical.\n", encoding="utf-8")

    raw = persona_payload()
    del raw["persona"]["system_prompt"]
    raw["persona"]["system_prompt_path"] = str(prompt_file)

    persona = Persona.from_dict(raw, id="spock")

    # resolved (and stripped of trailing newline)
    assert persona.system_prompt == "Be logical."
    # baked back into raw so the DB snapshot is self-contained
    assert raw["persona"]["system_prompt"] == "Be logical."


def test_system_prompt_path_resolves_relative_to_repo_root(tmp_path, monkeypatch):
    # PERSONAS_DIR.parent is treated as the repo root for relative paths.
    monkeypatch.setattr(personas, "PERSONAS_DIR", tmp_path / "personas")
    prompt_file = tmp_path / "prompts" / "spock.md"
    prompt_file.parent.mkdir(parents=True)
    prompt_file.write_text("Be logical.", encoding="utf-8")

    raw = persona_payload()
    del raw["persona"]["system_prompt"]
    raw["persona"]["system_prompt_path"] = "prompts/spock.md"

    persona = Persona.from_dict(raw, id="spock")

    assert persona.system_prompt == "Be logical."


def test_inline_system_prompt_wins_over_path(tmp_path):
    prompt_file = tmp_path / "spock.md"
    prompt_file.write_text("From file.", encoding="utf-8")

    raw = persona_payload()
    raw["persona"]["system_prompt"] = "Inline."
    raw["persona"]["system_prompt_path"] = str(prompt_file)

    persona = Persona.from_dict(raw, id="spock")

    assert persona.system_prompt == "Inline."


def test_system_prompt_path_missing_file_raises(tmp_path):
    raw = persona_payload()
    del raw["persona"]["system_prompt"]
    raw["persona"]["system_prompt_path"] = str(tmp_path / "does_not_exist.md")

    with pytest.raises(PersonaError, match="system_prompt_path not found"):
        Persona.from_dict(raw, id="missing")


def test_from_dict_rejects_when_neither_prompt_nor_path():
    raw = persona_payload()
    del raw["persona"]["system_prompt"]

    with pytest.raises(PersonaError, match="system_prompt"):
        Persona.from_dict(raw, id="broken")


def test_from_dict_rejects_missing_sections():
    raw = persona_payload()
    raw.pop("llm")

    with pytest.raises(PersonaError, match="missing or invalid 'llm' section"):
        Persona.from_dict(raw, id="broken")


def test_grouped_configs_expose_section_data():
    persona = Persona.from_dict(persona_payload(), id="grouped")

    # Provider factories can read grouped objects directly…
    assert persona.llm.model == "gpt-test"
    assert persona.llm.provider == "openai"
    assert persona.tts.voice_id == "voice-123"
    assert persona.stt.provider == "deepgram"
    assert persona.pipecat.text_aggregation_mode == "SENTENCE"
    # …and the flat compatibility properties mirror them.
    assert persona.llm_model == persona.llm.model
    assert persona.voice_id == persona.tts.voice_id


def test_temperature_accepts_none_and_in_range():
    raw = persona_payload()
    raw["llm"]["temperature"] = 1.0
    assert Persona.from_dict(raw, id="t").temperature == 1.0

    raw["llm"]["temperature"] = None
    assert Persona.from_dict(raw, id="t").temperature is None


def test_temperature_rejects_out_of_range():
    raw = persona_payload()
    raw["llm"]["temperature"] = 2.5

    with pytest.raises(PersonaError, match="temperature.*between 0.0 and 2.0"):
        Persona.from_dict(raw, id="hot")


def test_temperature_rejects_non_numeric():
    raw = persona_payload()
    raw["llm"]["temperature"] = "warm"

    with pytest.raises(PersonaError, match="temperature.*must be a number"):
        Persona.from_dict(raw, id="bad-temp")


def test_temperature_rejects_bool():
    raw = persona_payload()
    raw["llm"]["temperature"] = True

    with pytest.raises(PersonaError, match="temperature.*must be a number"):
        Persona.from_dict(raw, id="bool-temp")


def test_opening_messages_validated_as_role_content_objects():
    raw = persona_payload()
    raw["persona"]["opening_messages"] = [{"role": "system"}]  # missing content

    with pytest.raises(PersonaError, match="opening_messages"):
        Persona.from_dict(raw, id="bad-opening")


def test_opening_messages_rejects_non_list():
    raw = persona_payload()
    raw["persona"]["opening_messages"] = "Start."

    with pytest.raises(PersonaError, match="opening_messages.*must be a list"):
        Persona.from_dict(raw, id="bad-opening-type")


def test_load_persona_reads_from_configured_directory(tmp_path, monkeypatch):
    persona_file = tmp_path / "test_agent.json"
    persona_file.write_text(json.dumps(persona_payload()), encoding="utf-8")
    monkeypatch.setattr(personas, "PERSONAS_DIR", tmp_path)

    persona = load_persona(" test_agent ")

    assert persona.id == "test_agent"
    assert persona.name == "Marie"
