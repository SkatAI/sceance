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


def _language_directive(lang: str) -> str:
    """Pin the persona's spoken language so prior-session memory (which may be in
    another language) or a user speaking something else can't flip it. `lang`
    only steered STT/TTS before; the LLM had no language instruction at all."""
    name = _LANG_NAMES.get(lang.split("-")[0].lower(), "English")
    return (
        f"\n\n— Language —\n"
        f"Always speak {name}. Every response must be in {name}, regardless of the "
        f"language of the memory brief, earlier context, or anything the user says. "
        f"The memory brief is internal notes that may be in another language — never "
        f"mirror its language. If the user speaks another language, gently continue "
        f"in {name}."
    )


def build_system_instruction(persona: Persona) -> str:
    """The complete LLM system instruction for a persona: its base system prompt,
    the shared memory/onboarding appendix, and the output-language directive."""
    lang = (persona.lang or "en").lower()
    return persona.system_prompt + SHARED_SYSTEM_APPENDIX + _language_directive(lang)
