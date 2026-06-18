"""Project a stored persona snapshot into the session-detail view.

A session row keeps `persona_json` as a point-in-time snapshot of the persona it
ran. It may be a nested dict (current schema), a JSON string, a legacy/flat dict
from before the nested schema, or absent. `project_persona_snapshot` normalizes
all of those into the small view the detail page renders (or None).
"""

from __future__ import annotations

import json

from personas import Persona, PersonaError


def project_persona_snapshot(persona_json) -> dict | None:
    """Return the detail-page persona view, or None when there's nothing usable.

    - dict  → projected through `Persona.from_dict` (nested schema)
    - str   → JSON-decoded first, then as above
    - legacy/flat dict that won't parse → returned as-is
    - None / non-dict → None
    """
    persona = persona_json
    if isinstance(persona, str):
        try:
            persona = json.loads(persona)
        except json.JSONDecodeError:
            return None
    if not isinstance(persona, dict):
        return None
    try:
        p = Persona.from_dict(persona)
    except PersonaError:
        # Legacy/flat snapshot from before the nested schema — return as-is.
        return persona
    return {
        "name": p.name,
        "lang": p.lang,
        "llm_model": p.llm_model,
        "llm": p.llm_description,
        "tts_provider": p.tts_provider,
        "tts_voice_id": p.voice_id,
        "voice_name": p.voice_name,
        "voice_description": p.voice_description,
        "description": p.description,
    }
