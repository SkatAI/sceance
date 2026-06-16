from __future__ import annotations

import prompting
from personas import Persona
from tests.test_personas import persona_payload


def make_persona(**changes):
    raw = persona_payload()
    for section, values in changes.items():
        raw[section].update(values)
    return Persona.from_dict(raw, id="agent")


def test_language_directive_maps_known_and_unknown_languages():
    assert "Always speak English" in prompting._language_directive("en-US")
    assert "Always speak French" in prompting._language_directive("fr")
    # Unknown language falls back to English.
    assert "Always speak English" in prompting._language_directive("es")


def test_build_system_instruction_includes_prompt_and_memory_appendix():
    persona = make_persona()

    instruction = prompting.build_system_instruction(persona)

    assert persona.system_prompt in instruction
    assert "Memory & onboarding" in instruction
    assert "Always speak" in instruction


def test_build_system_instruction_pins_persona_language():
    english = prompting.build_system_instruction(make_persona(agent={"lang": "en"}))
    french = prompting.build_system_instruction(make_persona(agent={"lang": "fr"}))

    assert "Always speak English" in english
    assert "Always speak French" in french


def test_build_system_instruction_defaults_unknown_language_to_english():
    persona = make_persona(agent={"lang": "es"})

    assert "Always speak English" in prompting.build_system_instruction(persona)
