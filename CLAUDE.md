# Sceance

A voice-agent demo: the user dials into a "séance" and converses with a medium and one or more AI-played spirits of famous people. The product hook is "guess who you're talking to" — each persona is a puzzle, and turns-to-correct-guess is the natural eval signal.

See `readme.md` for the product sketch and `notes.md` for the full stack rationale.

## Layout

- `server/` — Pipecat backend (Python, `uv`-managed). Currently a near-verbatim copy of the Pipecat quickstart, used as the bootstrap point.
- `server/bot.py` — single-file bot: STT → LLM → TTS cascade pipeline, supports both Daily and SmallWebRTC transports.
- `server/pyproject.toml` — deps pinned via `pipecat-ai[cartesia,daily,deepgram,openai,runner,silero,webrtc]`. Note the `onnxruntime==1.23.0` override — required for Intel Macs since later wheels dropped x86_64 support.
- `server/Dockerfile`, `server/pcc-deploy.toml` — Pipecat Cloud deployment config.
- No frontend yet — planned: React + Vite using `@pipecat-ai/client-react`.

## Current stack (as wired)

- **Transport:** Daily (cloud) or SmallWebRTC (local), selected by runner args.
- **STT:** Deepgram
- **LLM:** OpenAI Responses API (`gpt-4.1` by default)
- **TTS:** Cartesia (default voice: British Reading Lady, `71a7ad14-...`)
- **VAD:** Silero

## Intended stack (per `notes.md`)

The quickstart wiring is not the target stack. The plan:

- LLM: Claude Sonnet as the persona brain, with Groq-hosted Llama / Gemini Flash as swappable fast alternatives.
- TTS: ElevenLabs primary (its shared voice library is the casting pool for character personas), Cartesia as swappable low-latency alternative, Hume as a v2 wildcard for emotion-aware responses.
- STT: stay on Deepgram.
- Tracing: SQLite — per-turn STT/LLM/TTS latency split + transcript + persona version. Whisker + Tail for live debugging.
- Frontend: React + Vite, two surfaces — the séance (player) and the dashboard (operator CRUD over personas + session browser).

Build the LLM and TTS services as swappable from the start.

## Running the bot

From `server/`:

```
uv run bot.py
```

`uv` resolves `.venv` automatically — no need to activate it. Activating only helps if you want bare `python`/`pytest` in the shell.

Entry point is `pipecat.runner.run.main`, which picks Daily or SmallWebRTC based on CLI args.

## Secrets

`server/.env` holds API keys (Deepgram, Cartesia, OpenAI). It is gitignored. **The current `.env` contains live keys committed in plaintext from the bootstrap — rotate before sharing the repo publicly.**
