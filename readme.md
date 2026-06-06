# sceance

A voice-agent playground. The original product framing (in `notes.md`) is a
séance: user dials in, the medium and one or more "spirits" answer, and the
game is to guess who the spirits are. The codebase right now is the
single-agent foundation for that.

## Layout

```
sceance/
├── readme.md          ← this file
├── changelog.md       ← what was done, in order
├── notes.md           ← product framing + target-stack rationale
├── CLAUDE.md          ← orientation for Claude Code
├── personas/          ← one JSON file per agent persona
│   ├── inigo.json
│   ├── inigo2.json
│   ├── inigo.md
│   ├── inigo2.md
│   └── marie_egg.json
└── server/            ← Pipecat backend, uv-managed
    ├── bot.py
    ├── personas.py    ← typed persona loader (nested schema)
    ├── storage.py     ← Supabase (asyncpg) pool + batched writes
    ├── recorder.py    ← session row + background drain to Supabase
    ├── observer.py    ← TranscriptObserver, persists transcripts + timing
    ├── pyproject.toml
    ├── Dockerfile
    ├── pcc-deploy.toml
    └── .env           ← gitignored; holds API keys
```

## Run

From `server/`:

```
uv run bot.py
```

`uv` resolves `.venv` automatically — no `source` step needed. The bot
listens on a SmallWebRTC transport by default; open the URL it logs to
talk to it.

## Personas

Each persona is one JSON file under `personas/`, picked by `id` (the filename
stem) when a session starts. `server/personas.py` parses it into a typed
`Persona`. The schema is **nested by concern** (`schema_version` 2):

- `agent` — `active` (listed on the landing page), `lang` (steers STT/TTS and
  the LLM language directive).
- `persona` — `name`, `description`, `system_prompt`, `opening_messages`
  (user-role messages that prime the first turn), optional `page_intro` / `cta`.
- `llm` — `provider` (`openai` / `anthropic`), `model`, `description` (friendly
  label shown in the UI), optional `temperature`.
- `tts` — `provider` (`cartesia`), optional `model`, `voice_id`, plus
  `voice_name` / `voice_description` for display.
- `stt` — `provider` (`deepgram`), optional `model` (defaults: `nova-3` for
  English, `nova-2` otherwise).

`build_llm` / `build_tts` in `bot.py` route on the provider fields, so swapping
a model, voice, or provider is a JSON edit.

## What gets recorded

Every session is written to **Supabase Postgres** (asyncpg pool in
`storage.py`; non-blocking drain in `recorder.py`):

- `sessions` — one row per pipeline run, with a full persona snapshot (`persona_json`).
- `messages` — user/assistant transcript turns.
- `metrics` / `events` — per-processor metrics and frame-level timing
  (`user_stopped_speaking`, `bot_started_speaking`, etc.) for latency analysis.

Browse sessions in the operator dashboard (`/dashboard.html`) or via
`GET /api/sessions/{id}`.

## Stack (as wired today)

- **Transport:** Daily (cloud) or SmallWebRTC (local), selected by runner args.
- **STT:** Deepgram (nova-3, profanity filter off).
- **LLM:** OpenAI Responses API or Anthropic Messages API, picked per persona.
- **TTS:** Cartesia.
- **VAD:** Silero.
- **Tracing:** Supabase Postgres via a `BaseObserver` subclass.

## Notes

- Intel Mac quirk: `pyproject.toml` pins `onnxruntime==1.23.0` because later
  wheels dropped x86_64 support. Silero VAD still works against the older
  API.
- API keys live in `server/.env` and are gitignored. Rotate them before
  sharing the repo or making it public.
- For the eventual séance frontend, the target is React + Vite using
  `@pipecat-ai/client-react`. Not built yet.

See `notes.md` for the longer-form rationale on stack choices.
