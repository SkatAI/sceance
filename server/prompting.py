"""System-instruction assembly and output-language policy.

The shared prompt appendix and the language directive live here, separate from
provider construction, so `build_llm` only selects a provider while the prompt
policy is assembled — and unit-tested — independently of any LLM service.
"""

from __future__ import annotations

from personas import Persona

SHARED_SYSTEM_APPENDIX = """

— Memory & onboarding —
You will receive a memory brief at the start of each conversation, wrapped in a
"[Memory brief — internal context, do not read aloud or quote]" block.
- If the brief says no prior conversations exist, this is the first time you
  meet this user. Get their name when it feels natural — once, gently, and
  only the name. Do not ask for age, gender, family, or work; let those
  surface on their own as the user chooses to share.
- If the brief contains a profile and recent sessions, treat the user as
  someone you know. Don't recite their facts back at them; just speak like
  someone who remembers.
- Never read the memory brief aloud, paraphrase it verbatim, or quote it.
"""

# Map persona `lang` codes to language names for the output-language directive.
_LANG_NAMES = {"en": "English", "fr": "French"}


def _language_directive(lang: str, has_memory: bool) -> str:
    """Pin the persona's spoken language so a user speaking something else can't
    flip it. `lang` only steers STT/TTS; the LLM needs telling separately.

    The memory-brief clauses are conditional: a memory-off persona is never sent
    a brief, so warning it not to mirror the brief's language is instructions
    about a thing that does not exist.
    """
    name = _LANG_NAMES.get(lang.split("-")[0].lower(), "English")
    if has_memory:
        return (
            f"\n\n— Language —\n"
            f"Always speak {name}. Every response must be in {name}, regardless of the "
            f"language of the memory brief, earlier context, or anything the user says. "
            f"The memory brief is internal notes that may be in another language — never "
            f"mirror its language. If the user speaks another language, gently continue "
            f"in {name}."
        )
    return (
        f"\n\n— Language —\n"
        f"Always speak {name}. Every response must be in {name}, regardless of earlier "
        f"context or anything the user says. If the user speaks another language, "
        f"gently continue in {name}."
    )


def build_system_instruction(persona: Persona) -> str:
    """The complete LLM system instruction for a persona: its base system prompt,
    the memory/onboarding appendix, and the output-language directive.

    Everything memory-related is gated on `persona.memory`. It used to be
    unconditional, so a memory-off persona was told it "will receive a memory brief
    at the start of each conversation" — one `bot._load_memory_brief` never sends.
    That is a lie to the model, ~150 tokens of prompt it cannot act on, and (for
    the memory-off personas used in the gradbot comparison) a prompt the other
    build does not have.
    """
    lang = (persona.lang or "en").lower()
    appendix = SHARED_SYSTEM_APPENDIX if persona.memory else ""
    return persona.system_prompt + appendix + _language_directive(lang, persona.memory)
