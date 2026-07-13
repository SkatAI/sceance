"""Per-provider LLM and TTS service factories, with registries.

`bot.build_llm` / `bot.build_tts` are thin wrappers that look up the right
factory here by `persona.llm_provider` / `persona.tts_provider`. Adding a
provider means adding a factory + a registry entry — no edit to bot
orchestration.

Each factory validates only its own requirements, reads its own API key from
`get_settings()`, and constructs only its own service. The shared system
instruction (prompt policy) is assembled by the caller and passed in; Task 5
extracts that assembly into a prompting module.
"""

from __future__ import annotations

from pipecat.services.anthropic.llm import AnthropicLLMService
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.deepgram.tts import DeepgramTTSService
from pipecat.services.gradium.stt import GradiumSTTService
from pipecat.services.gradium.tts import GradiumTTSService
from pipecat.services.groq.llm import GroqLLMService
from pipecat.services.openai.responses.llm import OpenAIResponsesHttpLLMService
from pipecat.services.openrouter.llm import OpenRouterLLMService
from pipecat.transcriptions.language import Language

from deepgram_stt import StallGuardedDeepgramSTTService
from deepgram_tts import SpeedDeepgramTTSService
from personas import Persona
from settings import get_settings

# ---- LLM factories --------------------------------------------------------


def build_openai_llm(persona: Persona, system_instruction: str):
    openai_settings = {"model": persona.llm_model, "system_instruction": system_instruction}
    if persona.temperature is not None:
        openai_settings["temperature"] = persona.temperature
    return OpenAIResponsesHttpLLMService(
        api_key=get_settings().openai_api_key,
        settings=OpenAIResponsesHttpLLMService.Settings(**openai_settings),
    )


def build_anthropic_llm(persona: Persona, system_instruction: str):
    anthropic_settings = {
        "model": persona.llm_model,
        "system_instruction": system_instruction,
        "enable_prompt_caching": True,
    }
    if persona.temperature is not None:
        anthropic_settings["temperature"] = persona.temperature
    return AnthropicLLMService(
        api_key=get_settings().anthropic_api_key,
        settings=AnthropicLLMService.Settings(**anthropic_settings),
    )


def build_groq_llm(persona: Persona, system_instruction: str):
    # Groq is an OpenAI-compatible chat-completions endpoint (LPU-hosted, very
    # low latency). Same Settings shape as OpenAI; hosts e.g. mistral-saba-24b.
    groq_settings = {"model": persona.llm_model, "system_instruction": system_instruction}
    if persona.temperature is not None:
        groq_settings["temperature"] = persona.temperature
    return GroqLLMService(
        api_key=get_settings().groq_api_key,
        settings=GroqLLMService.Settings(**groq_settings),
    )


def build_openrouter_llm(persona: Persona, system_instruction: str):
    # OpenRouter is an OpenAI-compatible gateway in front of many providers,
    # letting us reach models we have no direct integration for (Google, Mistral,
    # DeepSeek, …). The pipecat service bakes in
    # base_url=https://openrouter.ai/api/v1; the model id is the full OpenRouter
    # slug (e.g. "google/gemini-2.5-flash"). `provider.sort=latency` disables
    # OpenRouter's load-balancing and routes each request to the lowest-latency
    # upstream — the right default for a real-time voice agent. It rides through
    # pipecat via Settings.extra -> the OpenAI client's extra_body.
    openrouter_settings = {"model": persona.llm_model, "system_instruction": system_instruction}
    if persona.temperature is not None:
        openrouter_settings["temperature"] = persona.temperature
    openrouter_settings["extra"] = {"extra_body": {"provider": {"sort": "latency"}}}
    return OpenRouterLLMService(
        api_key=get_settings().openrouter_api_key,
        settings=OpenRouterLLMService.Settings(**openrouter_settings),
    )


LLM_FACTORIES = {
    "openai": build_openai_llm,
    "anthropic": build_anthropic_llm,
    "groq": build_groq_llm,
    "openrouter": build_openrouter_llm,
}


# ---- TTS factories --------------------------------------------------------


def build_cartesia_tts(persona: Persona, lang: str, agg_mode):
    if not persona.voice_id:
        raise ValueError("cartesia TTS requires tts.voice_id")
    cartesia_settings = {"voice": persona.voice_id, "language": lang}
    if persona.tts_model:
        cartesia_settings["model"] = persona.tts_model
    return CartesiaTTSService(
        api_key=get_settings().cartesia_api_key,
        settings=CartesiaTTSService.Settings(**cartesia_settings),
        text_aggregation_mode=agg_mode,
    )


def build_deepgram_tts(persona: Persona, lang: str, agg_mode):
    # Deepgram folds voice into the model name (e.g. "aura-2-pandora-en"), which
    # is English-only — no separate voice_id or language to pass.
    if not persona.tts_model:
        raise ValueError("deepgram TTS requires tts.model (e.g. 'aura-2-pandora-en')")
    # speed: Deepgram speaking-rate multiplier (0.7–1.5); None → provider default.
    return SpeedDeepgramTTSService(
        api_key=get_settings().deepgram_api_key,
        settings=DeepgramTTSService.Settings(voice=persona.tts_model),
        text_aggregation_mode=agg_mode,
        speed=persona.tts_speed,
    )


def build_gradium_tts(persona: Persona, lang: str, agg_mode):
    # Gradium hosts Kyutai's streaming TTS (e.g. "kyutai/tts-1.6b-en_fr", en+fr,
    # 48kHz WebSocket). voice_id + model come from the Gradium dashboard/voice
    # library; tts.model is optional (defaults to Gradium's).
    if not persona.voice_id:
        raise ValueError("gradium TTS requires tts.voice_id")
    gradium_settings = {"voice": persona.voice_id, "language": lang}
    if persona.tts_model:
        gradium_settings["model"] = persona.tts_model
    return GradiumTTSService(
        api_key=get_settings().gradium_api_key,
        settings=GradiumTTSService.Settings(**gradium_settings),
        text_aggregation_mode=agg_mode,
    )


TTS_FACTORIES = {
    "cartesia": build_cartesia_tts,
    "deepgram": build_deepgram_tts,
    "gradium": build_gradium_tts,
}


# ---- STT --------------------------------------------------------------------
#
# STT was hardcoded to Deepgram until the gradbot comparison needed it swappable:
# that build runs Gradium STT, and a latency comparison whose STT vendors differ
# is measuring the vendors as much as the frameworks.


def build_deepgram_stt(persona: Persona, lang: str, recovery_message: str):
    """Deepgram STT with a stall watchdog.

    Model defaults to nova-3 for English (nova-3 is English-only) and nova-2
    otherwise; an explicit `persona.stt_model` wins.

    StallGuardedDeepgramSTTService adds a watchdog on top of the base service: if
    a turn ends with no final transcript (a silently half-open Deepgram socket —
    the failure pipecat does NOT auto-recover; see deepgram_stt.py), it forces a
    reconnect so the next turn lands on a healthy connection, and speaks
    `recovery_message` so the dead air is audible.
    """
    stt_model = persona.stt_model or ("nova-3" if lang.startswith("en") else "nova-2")
    return StallGuardedDeepgramSTTService(
        api_key=get_settings().deepgram_api_key,
        settings=DeepgramSTTService.Settings(
            model=stt_model,
            language=lang,
            profanity_filter=False,
        ),
        recovery_message=recovery_message,
    )


def build_gradium_stt(persona: Persona, lang: str, recovery_message: str):
    """Gradium streaming STT (WebSocket ASR).

    No stall watchdog: `StallGuardedDeepgramSTTService` exists for a Deepgram
    failure mode (a silently half-open socket that pipecat never recovers). We
    have not seen Gradium do that, and wrapping a service in a watchdog written
    for someone else's bug would be cargo-culting. `recovery_message` is accepted
    to keep the factory signature uniform, and ignored.

    `delay_in_frames` is Gradium's latency/accuracy knob — frames of 80ms it
    buffers before emitting text, default 10 (= 800ms). `stt.model` is unused by
    this service; `stt.delay_in_frames` on the persona sets the knob.
    """
    del recovery_message
    settings = {"language": Language(lang) if lang else None}
    delay = persona.raw.get("stt", {}).get("delay_in_frames")
    if delay is not None:
        settings["delay_in_frames"] = int(delay)
    return GradiumSTTService(
        api_key=get_settings().gradium_api_key,
        settings=GradiumSTTService.Settings(**settings),
    )


STT_FACTORIES = {
    "deepgram": build_deepgram_stt,
    "gradium": build_gradium_stt,
}
