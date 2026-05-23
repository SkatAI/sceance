# Changelog

## 2026-05-23 — Bootstrap + persona system + tracing + multi-provider LLM

### Bootstrap
- Imported the Pipecat quickstart into `server/` as the starting point.
- Wired services per the quickstart defaults: Deepgram STT, OpenAI Responses
  LLM, Cartesia TTS, Silero VAD.
- Transports: Daily and SmallWebRTC both supported via runner args.
- Added `onnxruntime==1.23.0` override in `pyproject.toml` to keep Silero
  VAD working on Intel Mac (later wheels dropped x86_64).
- Pipecat Cloud deploy config in place (`server/pcc-deploy.toml`,
  `server/Dockerfile`) but not yet deployed.

### Persona config
- Pulled the hardcoded system prompt and opening messages out of `bot.py`
  into JSON persona files under `personas/`.
- Persona files own: `name`, `llm_model`, `tts_voice_id`, optional
  `temperature`, `system_instruction`, `opening_messages`.
- `AGENT_NAME` env var in `server/.env` picks which `personas/<name>.json`
  to load. Errors loudly if unset or missing.
- Moved `OPENAI_MODEL` and `CARTESIA_VOICE_ID` out of `.env` into the
  persona files.
- Disabled Deepgram's default `profanity_filter=True` (pipecat default
  overrides Deepgram's own False default).

### Personas authored
- `marie_egg` — a customer complaining about egg prices, OpenAI gpt-4.1.
- `inigo` — Ignatian-tradition life coach, gentle/reflective variant,
  OpenAI gpt-4.1.
- `inigo2` — same character, more directive prompt, Anthropic
  `claude-sonnet-4-5`.

### Session tracing
- New `server/db.py` with a `SessionDB` class — opens SQLite, creates
  schema if missing, inserts one `sessions` row with a full persona
  snapshot per pipeline run, stamps `ended_at` on close.
- Schema: `sessions`, `messages` (user/assistant transcripts),
  `events` (frame-level timing for latency analysis).
- New `server/observer.py` — `TranscriptObserver(BaseObserver)` watches
  the pipeline:
  - `TranscriptionFrame` → row in `messages`.
  - `LLMTextFrame` chunks accumulated between `LLMFullResponseStart`/
    `EndFrame` → one assistant message per turn.
  - Lifecycle frames (`UserStartedSpeaking`, `BotStartedSpeaking`,
    `TTSStarted`, etc.) → rows in `events` with the pipecat-supplied
    nanosecond timestamp.
- Wired into `PipelineTask(observers=[TranscriptObserver(db)])` and
  `db.close()` on disconnect.

### Multi-provider LLM routing
- Added `anthropic` to the pipecat extras in `pyproject.toml`.
- `llm_model` in persona files is now namespaced `<provider>:<model>`
  (e.g. `openai:gpt-4.1`, `anthropic:claude-sonnet-4-5`).
- New `build_llm(persona)` factory in `bot.py` routes to the right
  pipecat service from the prefix. Bare strings still default to OpenAI.
- Anthropic path uses `enable_prompt_caching=True` so the system prompt
  isn't re-billed every turn.
- Optional `temperature` field in persona files, passed through to
  whichever provider.

### Misc
- `.gitignore` extended to skip `*.db`, `*.db-journal`, and audio dumps.
- Updated `readme.md` to describe the persona system and tracing layout.

## Next

- Decide whether to wire a second agent (séance medium + spirit) — design
  pattern outlined in chat: Director + per-turn settings swap with a
  single shared `LLMContext`.
- Stand up the React + Vite frontend with `@pipecat-ai/client-react`
  (séance surface + dashboard surface).
- Build a tiny query layer on top of the SQLite tracing to surface
  per-turn STT/LLM/TTS latency.
