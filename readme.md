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
    ├── db.py          ← SQLite session storage
    ├── observer.py    ← TranscriptObserver, persists transcripts + timing
    ├── pyproject.toml
    ├── Dockerfile
    ├── pcc-deploy.toml
    └── .env           ← gitignored; holds API keys + AGENT_NAME
```

## Run

From `server/`:

```
uv run bot.py
```

`uv` resolves `.venv` automatically — no `source` step needed. The bot
listens on a SmallWebRTC transport by default; open the URL it logs to
talk to it.

## Picking a persona

`server/.env` selects which persona is loaded:

```
AGENT_NAME=inigo2
```

`bot.py` loads `../personas/<AGENT_NAME>.json`. Edit the env line and
restart the bot to swap personas. The persona file owns:

- `llm_model` — namespaced `<provider>:<model>` (e.g. `openai:gpt-4.1`,
  `anthropic:claude-sonnet-4-5`). The bot routes to the right pipecat
  service from the prefix.
- `tts_voice_id` — Cartesia voice ID.
- `temperature` — optional; omit for provider default.
- `system_instruction` — the persona's character prompt.
- `opening_messages` — user-role messages that prime the first turn.

## What gets recorded

Every session writes to `server/sceance.db` (SQLite). Three tables:

- `sessions` — one row per pipeline run, with a full persona snapshot.
- `messages` — user/assistant transcript turns.
- `events` — frame-level timing (`user_started_speaking`, `llm_start`,
  `tts_start`, etc.) for latency analysis.

Inspect with:

```
sqlite3 server/sceance.db "SELECT role, text FROM messages WHERE session_id = (SELECT MAX(id) FROM sessions);"
```

## Stack (as wired today)

- **Transport:** Daily (cloud) or SmallWebRTC (local), selected by runner args.
- **STT:** Deepgram (nova-3, profanity filter off).
- **LLM:** OpenAI Responses API or Anthropic Messages API, picked per persona.
- **TTS:** Cartesia.
- **VAD:** Silero.
- **Tracing:** SQLite via a `BaseObserver` subclass.

## Notes

- Intel Mac quirk: `pyproject.toml` pins `onnxruntime==1.23.0` because later
  wheels dropped x86_64 support. Silero VAD still works against the older
  API.
- API keys live in `server/.env` and are gitignored. Rotate them before
  sharing the repo or making it public.
- For the eventual séance frontend, the target is React + Vite using
  `@pipecat-ai/client-react`. Not built yet.

See `notes.md` for the longer-form rationale on stack choices.
