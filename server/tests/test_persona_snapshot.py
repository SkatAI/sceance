from __future__ import annotations

import json

from persona_snapshot import project_persona_snapshot
from tests.test_personas import persona_payload


def test_project_nested_persona_dict():
    view = project_persona_snapshot(persona_payload())

    assert view["name"] == "Marie"
    assert view["lang"] == "fr"
    assert view["llm_model"] == "gpt-test"
    assert view["tts_provider"] == "cartesia"
    assert set(view) == {
        "name", "lang", "llm_model", "llm", "tts_provider",
        "tts_voice_id", "voice_name", "voice_description", "description",
    }


def test_project_persona_json_string_is_decoded_then_projected():
    view = project_persona_snapshot(json.dumps(persona_payload()))

    assert view["name"] == "Marie"
    assert view["llm_model"] == "gpt-test"


def test_project_malformed_legacy_dict_returned_as_is():
    legacy = {"name": "Old Marie", "voice": "british"}  # not the nested schema

    assert project_persona_snapshot(legacy) == legacy


def test_project_malformed_json_string_returns_none():
    assert project_persona_snapshot("{not valid json") is None


def test_project_none_returns_none():
    assert project_persona_snapshot(None) is None


def test_project_non_dict_non_str_returns_none():
    assert project_persona_snapshot(42) is None
