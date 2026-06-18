"""Typed persona loader.

Persona JSON is nested by concern (schema_version 2):

    {
      "agent":   { "active": bool, "lang": "en" },
      "persona": { "name", "description",
                   "system_prompt" | "system_prompt_path",  # inline OR a .md file
                   "opening_messages", "page_intro"?, "cta"? },
      "llm":     { "provider", "model", "description", "temperature"? },
      "tts":     { "provider", "model"?, "voice_id", "voice_name", "voice_description",
                   "speed"? },   # Deepgram speaking-rate multiplier, 0.7–1.5
      "stt":     { "provider", "model"? },
      "pipecat": { "TextAggregationMode"? }   # "SENTENCE" (default) | "TOKEN"
    }

This module is the single parse point: `load_persona` reads a file and returns a
`Persona`; everything else (bot, server, recorder) reads typed attributes off it.
The original dict is kept on `Persona.raw` for the DB snapshot.

The schema's sections each parse into a small frozen config (`AgentConfig`,
`PersonaTextConfig`, `LLMConfig`, `TTSConfig`, `STTConfig`, `PipecatConfig`), each
owning its own validation. `Persona` holds those six and also exposes flat
compatibility properties (`persona.llm_model`, `persona.voice_id`, …) so existing
call sites keep working while new code can read grouped objects (`persona.llm`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

PERSONAS_DIR = Path(__file__).parent.parent / "personas"


class PersonaError(ValueError):
    """Raised when a persona file is missing required fields or is malformed."""


def _read_prompt_file(rel_or_abs: str, persona_id: str) -> str:
    """Read a system-prompt markdown file. Relative paths resolve from the repo
    root (PERSONAS_DIR.parent), matching e.g. 'personas/systemprompts/x.md'."""
    p = Path(rel_or_abs)
    if not p.is_absolute():
        p = PERSONAS_DIR.parent / p
    if not p.exists():
        raise PersonaError(
            f"persona {persona_id!r}: system_prompt_path not found: {p}"
        )
    return p.read_text().strip()


def _required(sec: dict, sec_name: str, key: str, id: str):
    if key not in sec or sec[key] in (None, ""):
        raise PersonaError(f"persona {id!r}: '{sec_name}.{key}' is required")
    return sec[key]


def _validate_temperature(value, id: str) -> float | None:
    """`None` or a number in the provider-agnostic range [0.0, 2.0]."""
    if value is None:
        return None
    if isinstance(value, bool):  # bool is an int subclass; reject it explicitly
        raise PersonaError(f"persona {id!r}: 'llm.temperature' must be a number, got {value!r}")
    try:
        t = float(value)
    except (TypeError, ValueError):
        raise PersonaError(f"persona {id!r}: 'llm.temperature' must be a number, got {value!r}")
    if not 0.0 <= t <= 2.0:
        raise PersonaError(
            f"persona {id!r}: 'llm.temperature' must be between 0.0 and 2.0, got {t}"
        )
    return t


def _validate_speed(value, id: str) -> float | None:
    """Deepgram speaking-rate multiplier. `None` → provider default; else 0.7–1.5."""
    if value is None:
        return None
    try:
        speed = float(value)
    except (TypeError, ValueError):
        raise PersonaError(f"persona {id!r}: 'tts.speed' must be a number, got {value!r}")
    if not 0.7 <= speed <= 1.5:
        raise PersonaError(f"persona {id!r}: 'tts.speed' must be between 0.7 and 1.5, got {speed}")
    return speed


def _validate_opening_messages(value, id: str) -> list[dict]:
    """A list of `{role, content}` objects; absent/None → empty list."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise PersonaError(f"persona {id!r}: 'persona.opening_messages' must be a list")
    for i, msg in enumerate(value):
        if not isinstance(msg, dict) or "role" not in msg or "content" not in msg:
            raise PersonaError(
                f"persona {id!r}: 'persona.opening_messages[{i}]' must be an "
                f"object with 'role' and 'content'"
            )
    return value


@dataclass(frozen=True)
class AgentConfig:
    active: bool
    lang: str
    memory: bool

    @classmethod
    def from_section(cls, agent: dict) -> "AgentConfig":
        return cls(
            active=bool(agent.get("active", False)),
            lang=(agent.get("lang") or "en"),
            memory=bool(agent.get("memory", True)),  # absent → memory on
        )


@dataclass(frozen=True)
class PersonaTextConfig:
    name: str
    description: str
    system_prompt: str
    opening_messages: list[dict]
    page_intro: str | None
    cta: str | None

    @classmethod
    def from_section(cls, persona: dict, id: str) -> "PersonaTextConfig":
        name = _required(persona, "persona", "name", id)
        # System prompt: inline `system_prompt` wins; otherwise load from the
        # markdown file named by `system_prompt_path` and bake the resolved text
        # back into the dict so the DB snapshot (persona.raw) is self-contained.
        system_prompt = persona.get("system_prompt") or ""
        if not system_prompt and persona.get("system_prompt_path"):
            system_prompt = _read_prompt_file(persona["system_prompt_path"], id)
            persona["system_prompt"] = system_prompt
        if not system_prompt:
            raise PersonaError(
                f"persona {id!r}: one of 'persona.system_prompt' or "
                f"'persona.system_prompt_path' is required"
            )
        return cls(
            name=name,
            description=persona.get("description", ""),
            system_prompt=system_prompt,
            opening_messages=_validate_opening_messages(persona.get("opening_messages", []), id),
            page_intro=persona.get("page_intro"),
            cta=persona.get("cta"),
        )


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    description: str
    temperature: float | None

    @classmethod
    def from_section(cls, llm: dict, id: str) -> "LLMConfig":
        return cls(
            provider=str(_required(llm, "llm", "provider", id)).lower(),
            model=_required(llm, "llm", "model", id),
            description=llm.get("description", ""),
            temperature=_validate_temperature(llm.get("temperature"), id),
        )


@dataclass(frozen=True)
class TTSConfig:
    provider: str
    model: str | None
    voice_id: str | None
    voice_name: str
    voice_description: str
    speed: float | None  # Deepgram speaking-rate multiplier (0.7–1.5)

    @classmethod
    def from_section(cls, tts: dict, id: str) -> "TTSConfig":
        return cls(
            provider=str(tts.get("provider") or "cartesia").lower(),
            model=tts.get("model"),
            voice_id=tts.get("voice_id"),  # Cartesia-specific; per-provider check in build_tts
            voice_name=tts.get("voice_name", ""),
            voice_description=tts.get("voice_description", ""),
            speed=_validate_speed(tts.get("speed"), id),
        )


@dataclass(frozen=True)
class STTConfig:
    provider: str
    model: str | None

    @classmethod
    def from_section(cls, stt: dict) -> "STTConfig":
        return cls(
            provider=str(stt.get("provider") or "deepgram").lower(),
            model=stt.get("model"),
        )


@dataclass(frozen=True)
class PipecatConfig:
    text_aggregation_mode: str  # "SENTENCE" | "TOKEN"

    @classmethod
    def from_section(cls, pipecat: dict, id: str) -> "PipecatConfig":
        # SENTENCE (default, buffers to sentence boundaries) or TOKEN (streams
        # tokens for lower latency).
        agg_mode = str(pipecat.get("TextAggregationMode") or "SENTENCE").upper()
        if agg_mode not in ("SENTENCE", "TOKEN"):
            raise PersonaError(
                f"persona {id!r}: 'pipecat.TextAggregationMode' must be "
                f"'SENTENCE' or 'TOKEN', got {agg_mode!r}"
            )
        return cls(text_aggregation_mode=agg_mode)


@dataclass
class Persona:
    id: str
    raw: dict
    agent: AgentConfig
    text: PersonaTextConfig
    llm: LLMConfig
    tts: TTSConfig
    stt: STTConfig
    pipecat: PipecatConfig

    # ---- Flat compatibility properties (existing call sites) ----------------
    @property
    def active(self) -> bool:
        return self.agent.active

    @property
    def lang(self) -> str:
        return self.agent.lang

    @property
    def memory(self) -> bool:
        return self.agent.memory

    @property
    def name(self) -> str:
        return self.text.name

    @property
    def description(self) -> str:
        return self.text.description

    @property
    def system_prompt(self) -> str:
        return self.text.system_prompt

    @property
    def opening_messages(self) -> list[dict]:
        return self.text.opening_messages

    @property
    def page_intro(self) -> str | None:
        return self.text.page_intro

    @property
    def cta(self) -> str | None:
        return self.text.cta

    @property
    def llm_provider(self) -> str:
        return self.llm.provider

    @property
    def llm_model(self) -> str:
        return self.llm.model

    @property
    def llm_description(self) -> str:
        return self.llm.description

    @property
    def temperature(self) -> float | None:
        return self.llm.temperature

    @property
    def tts_provider(self) -> str:
        return self.tts.provider

    @property
    def tts_model(self) -> str | None:
        return self.tts.model

    @property
    def voice_id(self) -> str | None:
        return self.tts.voice_id

    @property
    def voice_name(self) -> str:
        return self.tts.voice_name

    @property
    def voice_description(self) -> str:
        return self.tts.voice_description

    @property
    def tts_speed(self) -> float | None:
        return self.tts.speed

    @property
    def stt_provider(self) -> str:
        return self.stt.provider

    @property
    def stt_model(self) -> str | None:
        return self.stt.model

    @property
    def text_aggregation_mode(self) -> str:
        return self.pipecat.text_aggregation_mode

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

        stt_raw = raw.get("stt") if isinstance(raw.get("stt"), dict) else {}
        pipecat_raw = raw.get("pipecat") if isinstance(raw.get("pipecat"), dict) else {}
        return cls(
            id=id,
            raw=raw,
            agent=AgentConfig.from_section(section("agent")),
            text=PersonaTextConfig.from_section(section("persona"), id),
            llm=LLMConfig.from_section(section("llm"), id),
            tts=TTSConfig.from_section(section("tts"), id),
            stt=STTConfig.from_section(stt_raw),
            pipecat=PipecatConfig.from_section(pipecat_raw, id),
        )

    def public(self) -> dict:
        """The safe subset rendered on the /agents card."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "lang": self.lang,
            "memory": self.memory,
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
