I'll search for current TTS pricing and the latest options, since this landscape shifts fast.Now let me check the self-hosted open-source options, since those are the real answer for a free-tier cost structure, and what Pipecat supports.A few things worth untangling here, because the provider swap you're considering won't actually fix the structural problem.

First, correct a wrong assumption: ElevenLabs is *more* expensive than Cartesia, not less. Across self-serve plans Cartesia is roughly one fifth the cost of ElevenLabs. ElevenLabs Flash/Turbo lands around $50 per million characters, and v3 around $100/M, versus Cartesia Sonic at roughly $35/M effective. So switching there makes your problem worse.

The deeper issue is the billing *model*, not the vendor. Every premium real-time API bills per character (or per second of audio), so cost scales linearly with free-tier usage that brings no revenue. You can lower the constant, but you can't escape the linear curve unless you change the cost structure entirely. That gives you two paths.

**Path 1 — lower the hosted floor.** If you stay API-based, the cheapest credible options for a conversational latency budget:
- **Deepgram Aura-2** (~$30/M, sub-200ms tunable to ~90ms). This is your most pragmatic swap: you're *already* on Deepgram for STT, so you'd unify STT+TTS under one vendor and one bill. Deepgram Aura-2 runs at $30 per million with all voices included.
- **Hyperscaler standard tiers** (Google Standard / Polly Standard at ~$4/M) are far cheaper but old-generation quality and 150–300ms latency — fine for a free tier where you're explicitly degrading quality, bad for the experience you'd want paying users to feel.
- **OpenAI gpt-4o-mini-tts** is token/minute-based at roughly $0.015 per minute, worth benchmarking but not a step-change.

**Path 2 — self-host an open model (the actual free-tier answer).** This converts variable per-character cost into fixed GPU cost. At a known concurrency ceiling, marginal cost per free user drops to ~zero, which is exactly what you need for non-revenue usage.

For your Pipecat stack the obvious candidate is **Kokoro** (82M params, Apache 2.0). Pipecat has a native service — install with pipecat-ai[kokoro], it runs entirely local via ONNX Runtime, no API key or network access after the initial model download. It runs comfortably on CPU and hits RTF 0.03 on GPU (a 10-second clip in 0.3s), and supports 9 languages including French. Quality-wise it's the top open-weight model, roughly just behind ElevenLabs on TTS Arena. The catch: no arbitrary voice cloning (style presets only), and French output is likely weaker than English — test it against Inigo/Ignace before committing. Heavier alternatives if Kokoro's expressiveness falls short: **Orpheus** (Canopy, Llama-based, 1B–3B) or **Chatterbox-Turbo** (350M, MIT, emotion + cloning).

The pattern that actually ships: **tier the TTS by user, not by app.** Free tier → local Kokoro (fixed cost). Paid tier → Cartesia/ElevenLabs premium voice. In Pipecat this is a one-line service swap in the pipeline, so you don't fork your codebase. The hybrid routing pattern (cheap/local for utility responses, premium for branded ones) is already standard in production teams.

One more lever specific to a discernment agent: cache the TTS for your fixed/recurring lines (greeting, framing prompts, the recurring Ignatian scaffolding). Those get synthesized once and replayed, which strips a meaningful chunk of characters out of the billed total regardless of which path you pick.

If it'd help, I can sketch the Pipecat config for the tiered Kokoro/Cartesia swap so you can drop it into the existing pipeline.