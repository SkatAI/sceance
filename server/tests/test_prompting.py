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
    assert "Always speak English" in prompting._language_directive("en-US", has_memory=True)
    assert "Always speak French" in prompting._language_directive("fr", has_memory=True)
    # Unknown language falls back to English.
    assert "Always speak English" in prompting._language_directive("es", has_memory=False)


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


def test_memory_appendix_only_for_memory_on_personas():
    # A memory-off persona used to be told it "will receive a memory brief at the
    # start of each conversation" — one it is never sent. Leo (inigo_v5_fr_nomem)
    # is memory-off, and this is also what keeps his prompt comparable with the
    # gradbot build's, which has no memory concept at all.
    off = make_persona(agent={"memory": False})
    assert "memory brief" not in prompting.build_system_instruction(off).lower()

    on = make_persona(agent={"memory": True})
    assert "memory brief" in prompting.build_system_instruction(on).lower()
