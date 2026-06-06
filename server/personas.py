"""Typed persona loader.

Persona JSON is nested by concern (schema_version 2):

    {
      "agent":   { "active": bool, "lang": "en" },
      "persona": { "name", "description", "system_prompt", "opening_messages",
                   "page_intro"?, "cta"? },
      "llm":     { "provider", "model", "description", "temperature"? },
      "tts":     { "provider", "model"?, "voice_id", "voice_name", "voice_description" },
      "stt":     { "provider", "model"? }
    }

This module is the single parse point: `load_persona` reads a file and returns a
`Persona`; everything else (bot, server, recorder) reads typed attributes off it.
The original dict is kept on `Persona.raw` for the DB snapshot.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

PERSONAS_DIR = Path(__file__).parent.parent / "personas"


class PersonaError(ValueError):
    """Raised when a persona file is missing required fields or is malformed."""


@dataclass
class Persona:
    id: str
    raw: dict

    # agent
    active: bool
    lang: str
    memory: bool

    # persona
    name: str
    description: str
    system_prompt: str
    opening_messages: list[dict]
    page_intro: str | None
    cta: str | None

    # llm
    llm_provider: str
    llm_model: str
    llm_description: str
    temperature: float | None

    # tts
    tts_provider: str
    tts_model: str | None
    voice_id: str | None
    voice_name: str
    voice_description: str

    # stt
    stt_provider: str
    stt_model: str | None

    @classmethod
    def from_dict(cls, raw: dict, id: str = "") -> "Persona":
        """Parse the nested schema. Raises PersonaError on a missing section or
        required field (hard cutover — no flat-shape fallback)."""
        if not isinstance(raw, dict):
            raise PersonaError(f"persona {id!r}: expected a JSON object")

        def section(key: str) -> dict:
            val = raw.get(key)
            if not isinstance(val, dict):
                raise PersonaError(
                    f"persona {id!r}: missing or invalid '{key}' section"
                )
            return val

        def required(sec: dict, sec_name: str, key: str):
            if key not in sec or sec[key] in (None, ""):
                raise PersonaError(f"persona {id!r}: '{sec_name}.{key}' is required")
            return sec[key]

        agent = section("agent")
        persona = section("persona")
        llm = section("llm")
        tts = section("tts")
        stt = raw.get("stt") if isinstance(raw.get("stt"), dict) else {}

        return cls(
            id=id,
            raw=raw,
            active=bool(agent.get("active", False)),
            lang=(agent.get("lang") or "en"),
            memory=bool(agent.get("memory", True)),  # absent → memory on
            name=required(persona, "persona", "name"),
            description=persona.get("description", ""),
            system_prompt=required(persona, "persona", "system_prompt"),
            opening_messages=persona.get("opening_messages", []),
            page_intro=persona.get("page_intro"),
            cta=persona.get("cta"),
            llm_provider=str(required(llm, "llm", "provider")).lower(),
            llm_model=required(llm, "llm", "model"),
            llm_description=llm.get("description", ""),
            temperature=llm.get("temperature"),
            tts_provider=str(tts.get("provider") or "cartesia").lower(),
            tts_model=tts.get("model"),
            voice_id=tts.get("voice_id"),  # Cartesia-specific; per-provider check in build_tts
            voice_name=tts.get("voice_name", ""),
            voice_description=tts.get("voice_description", ""),
            stt_provider=str(stt.get("provider") or "deepgram").lower(),
            stt_model=stt.get("model"),
        )

    def public(self) -> dict:
        """The safe subset rendered on the /agents card."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "lang": self.lang,
            "voice_name": self.voice_name,
            "voice_description": self.voice_description,
            "llm": self.llm_description,
            "tts_provider": self.tts_provider,
        }


def load_persona(agent_name: str) -> Persona:
    agent_name = (agent_name or "").strip()
    if not agent_name:
        raise PersonaError("agent_name is required")
    persona_path = PERSONAS_DIR / f"{agent_name}.json"
    if not persona_path.exists():
        raise FileNotFoundError(f"Persona file not found: {persona_path}")
    with persona_path.open() as f:
        raw = json.load(f)
    return Persona.from_dict(raw, id=agent_name)
