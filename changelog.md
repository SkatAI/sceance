# Changelog

## 2026-07-13 — Make the turn-taking knobs configurable (for framework comparison)

Two constants became settings, because a like-for-like comparison against the
gradbot build needs to be able to match them.

- **`VAD_STOP_SECS`** (default `0.2`, Silero's default — previously implicit in a
  bare `SileroVADAnalyzer()`). This is now explicit because it is load-bearing:
  it decides when `user_stopped_speaking` fires, which starts the response-latency
  stopwatch. The gradbot build's `flush_duration_s` **must equal it**, or the two
  frameworks time "the user stopped talking" from different moments and every
  cross-framework latency figure is wrong by the gap. It was 0.3s out; gradbot
  looked 0.5s faster at the median when the real gap was 0.2s.
- **`BARGE_IN_MIN_WORDS`** (default `2` — unchanged shipping behaviour). Set it to
  `1` to make barge-in purely VAD-driven, which is what gradbot does, for a fair
  interruption comparison. **This re-exposes the contentless-blip dead-air bug it
  was added to fix** — it logs a warning and must never run in production.

`tests/test_user_turn_strategy.py` now pins both, so the two builds cannot
silently drift apart again.

## 2026-07-13 — Show which framework recorded each session

The gradbot app writes its sessions into this same database and has no dashboard
of its own, so its calls surface in this ledger. Unlabelled, they were
indistinguishable from Pipecat's — and an unfiltered latency figure was an
average across two different frameworks.

- `sessions.framework` (`'pipecat'` | `'gradbot'`, added in gradbot's migration
  007, defaulting to `'pipecat'`) is now surfaced on each ledger row and offered
  as an "All stacks" filter, alongside the persona and environment ones.
- `admin.api_sessions` gained a `framework` query param. Its test now calls the
  handler with **keyword** args: the signature keeps growing, and calling it
  positionally means the next inserted parameter silently shifts `pool` into
  something else. That is exactly how this broke.

## 2026-07-13 — Recover from a stale session instead of wedging on it

- **Auth self-heals on a 401.** A rejected token from `/api/me` was left in
  `localStorage`, so supabase-js kept handing the same dead token back on every
  page load: you sat on the sign-in form holding a credential the server would
  never accept, and only a fresh login cleared it. The dashboard was worse — it
  bounced to `/`, which reloaded the same dead session and bounced again. Both
  `static/app.js` and `static/auth.js` now `signOut()` on a 401.
- **A rejected JWT now says why.** The reason (`invalid_token: Signature has
  expired`, …) only reached the browser's network tab, so the server log showed a
  bare `401 Unauthorized` with no way to tell an expired token from a bad
  signature. `auth.verify_jwt` logs the failure plus the token's *unverified*
  `alg`/`aud`/`iss`/`exp` — for the log line only, never for an auth decision.

## 2026-07-02 — Add OpenRouter as an LLM provider

- **New provider:** personas can now set `llm.provider = "openrouter"` to reach
  any model on OpenRouter's OpenAI-compatible gateway (Google, Mistral,
  DeepSeek, Llama, …) using the full model slug (e.g.
  `"google/gemini-2.5-flash"`) as `llm.model`. Wired via pipecat's
  `OpenRouterLLMService` in `build_openrouter_llm` + a `LLM_FACTORIES` entry
  (`server/providers.py`) — no bot-orchestration change. Requests set
  `provider.sort=latency` so OpenRouter routes each turn to the lowest-latency
  upstream, the right default for a real-time voice agent.
- **Config:** reads `OPENROUTER_API_KEY` from the environment
  (`server/settings.py`); add it to `server/.env`.

## 2026-07-01 — Fix LLM cold-start on turn zero (static greeting + cache-priming warm-up)

- **New feature:** personas can define an optional `persona.static_greeting`
  string. When set, turn zero is that fixed line spoken straight to TTS
  (`TTSSpeakFrame` in `make_kickoff`, `server/bot.py`) instead of an
  `LLMRunFrame` — the caller hears the agent immediately rather than waiting on
  the cold first inference (~3–4s). The slow first real inference is deferred to
  after the user's first reply, when the connection and cache are warm. The
  greeting is recorded to the transcript as an `assistant` message; the
  `opening_messages` are still seeded so message ordering stays user-first (an
  Anthropic requirement) and the LLM has coherent context for turn two. Opt-in:
  personas without the field keep the dynamic LLM greeting.
- **Warm-up upgrade:** `prewarm_llm` now fires a throwaway
  `run_inference(max_tokens=1)` instead of `models.list()`. Besides opening the
  pooled HTTP connection, it uses the configured system instruction, so for
  Anthropic (`enable_prompt_caching`) it also *writes* the system-prompt cache —
  the first real turn reads it (cache hit).
- Static greetings authored for the active personas: `inigo_v3` (Inigo),
  `inigo_v4_fr` (Ignace), `inigo_v5_fr_nomem` (Leo), `yarden_mini` (Sophie).

## 2026-06-20 — Gate interruptions on a real transcript (fix dead-air after a turn)

- **Behavior change:** the user-turn start / barge-in trigger is now
  `MinWordsUserTurnStartStrategy` instead of pipecat's default raw-VAD strategy
  (`build_context_aggregators` in `server/bot.py`). A contentless VAD blip
  (breath/noise) can no longer start a turn, so it can no longer interrupt and
  cancel an in-flight LLM response.
- **Bug fixed:** online session `e6ec5595` went silent ~13s after "How are you
  today?" — the sentence was transcribed and the LLM started replying, but a
  ~0.2s VAD blip 0.16s into generation cancelled the run (`llm_start`→`llm_end`
  in 219ms, no TTS), and since that blip produced no transcript nothing
  re-queued a response. This is a **distinct failure mode from the Deepgram
  stalled-socket bug** (the StallGuard can't catch it — a transcript does
  arrive). VAD still runs (turn-stop timing + STT); it just no longer triggers
  interruptions on its own. Pre-TTS the threshold is effectively 1 word so
  normal turn-taking is unchanged; `min_words=2` applies only while the bot is
  speaking. New tests: `server/tests/test_user_turn_strategy.py`.

## 2026-06-20 — Per-turn timestamps in the session transcript

- The session-detail Transcript now shows a precise wall-clock time
  (`HH:MM:SS.mmm`) on each turn, from `messages.recorded_at`. For assistant
  turns this `recorded_at` is captured at `LLMFullResponseEndFrame`, so it is
  the moment **LLM text generation finished** (hover title clarifies user vs
  assistant). Frontend-only — `recorded_at` was already served by
  `GET /api/sessions/{id}`; rendered in `static/format.js` with `fmtClock()`
  and styled in `dashboard.css`.

## 2026-06-18 — Per-agent visibility (public vs admin-only)

- Persona `agent` section gains a `visibility` key (`"public"` | `"admin"`,
  default `"public"`; validated in `AgentConfig`). Admin-only agents are listed
  on the séance page only for admin users; public agents show for everyone.
  Active-only listing still applies.
- Enforced server-side, not just hidden in the UI: `/agents` now takes an
  optional auth (new `get_current_user_optional` in `auth.py`) and omits
  admin-only personas for anonymous/non-admin callers; `/start-session` rejects
  starting an admin-only agent for non-admins (`403 admin_only`). The landing
  page sends its access token with the `/agents` request so admins get the full
  list.

## 2026-06-18 — Invite-code gated signup + beta waitlist

- Logged-out landing page now shows an optional **invite code** field alongside
  email, with private-beta copy. New behaviour in `POST /api/auth/login`:
  existing emails log in as before; a new email with a **valid invite code**
  creates a pre-confirmed account and logs in immediately (still no email sent);
  any other new email joins the beta waitlist. The response reports
  `{status: "waitlisted", already, invalid_code}` so the page can show the right
  message — newly added, already on the list, or "that code wasn't valid, but
  you've joined the waitlist" (an invalid/expired/exhausted code now waitlists
  instead of erroring). On waitlisting, the page replaces the whole sign-in form
  with a large confirmation message. The old `OPEN_SIGNUP` auto-create branch is
  removed — an invite code is now the only way for a new user to get in.
- Migration `006_invites.sql` adds `public.invite_codes` (code PK, `max_uses`
  default 5, `used_count`, `expires_at` default now()+3 days) and
  `public.waitlist` (email PK). Codes are managed manually in Supabase; seeds the
  first code `inigo`. Apply with
  `psql "$SUPABASE_DB_URL" -f server/migrations/006_invites.sql`.
- `supabase_admin.py` gains `normalize_invite_code` (lowercase/trim/strip to
  `[a-z0-9]`), `redeem_invite_code` (atomic increment guarded by `used_count <
  max_uses` and expiry, so concurrent signups can't over-redeem), and
  `add_to_waitlist` (idempotent). Tests cover the helpers and all login branches.

## 2026-06-18 — Route smoke tests for wiring (refactor Task 19)

- Added `test_route_smoke.py`: FastAPI-level tests via `TestClient` that prove
  router registration + dependency wiring survived the router/repository split.
  The client is built without a `with` block so the app lifespan never opens a
  real asyncpg pool; handlers that need a pool/user get their dependencies
  overridden. Covers `/health`, `/agents`, `/api/me` (401 without a token + the
  authenticated shape), `/start-session` validation errors (422 missing field,
  400 blank agent, 404 unknown agent), and the admin auth-failure path (401
  anonymous, 403 non-admin). Unit tests stay the primary coverage for SQL
  shaping and orchestration.

## 2026-06-18 — Tighten persona model boundaries (refactor Task 17)

- `Persona` was one wide dataclass carrying agent/text/llm/tts/stt/pipecat fields
  with all parsing + validation inline in `from_dict`. Split each section into a
  small frozen config that owns its own validation — `AgentConfig`,
  `PersonaTextConfig`, `LLMConfig`, `TTSConfig`, `STTConfig`, `PipecatConfig` —
  each with a `from_section` classmethod. `Persona` now holds those six and
  exposes the grouped objects (`persona.llm`, `persona.tts`, …) for new code,
  while keeping every flat attribute (`persona.llm_model`, `persona.voice_id`, …)
  as a compatibility property, so all existing call sites and the DB snapshot
  (`persona.raw` / `public()`) are unchanged. This adds lines but isolates each
  section's validation; call sites were already clean, so they stay flat.
- New explicit validation: `llm.temperature` must be `None` or a number in
  `[0.0, 2.0]` (bool rejected); `persona.opening_messages` must be a list of
  `{role, content}` objects. All shipped persona JSON files still parse. Added
  tests for the grouped configs and both validations.

## 2026-06-18 — Normalize session-detail persona projection (refactor Task 14)

- `api_session_detail` parsed the stored `persona_json` snapshot inline (decode if
  string, try `Persona.from_dict`, fall back to legacy dicts). Extracted it into
  `persona_snapshot.project_persona_snapshot(persona_json)`, handling nested dict,
  JSON string, malformed legacy dict, malformed JSON string, and None/non-dict
  uniformly. The route now has no persona-parsing branches. Minor hardening: a
  malformed JSON *string* now returns None instead of raising (the route would
  previously have 500'd). Added `test_persona_snapshot.py` for all five input
  shapes.

## 2026-06-18 — Extract dashboard query repository (refactor Task 13)

- The admin routes (`/api/aggregate`, `/api/sessions`, `/api/sessions/{id}`) held
  their SQL and row→JSON shaping inline. Moved it into a new
  `dashboard_repository.py`: `aggregate(pool, days)`, `list_sessions(...)` (with a
  testable `_session_filter` that builds the shared WHERE clause), and
  `fetch_session_detail(...)`. The route handlers now validate params and call the
  repository; `api_session_detail` still assembles the detail page's derived bits
  (persona projection — left for Task 14 — and per-turn response latency) from the
  raw `persona_json` / `turn_events` the repository returns alongside the shaped
  fields. Dynamic SQL stays parameterized — only fixed column names are
  interpolated; user values go through `$n` placeholders.
- Added `test_dashboard_repository.py`: `_session_filter` for persona-only,
  environment-only, both, and no filters; `list_sessions` arg ordering proving no
  raw interpolation; and aggregate / session-detail shaping. Existing
  through-the-route admin tests still pass unchanged.

## 2026-06-18 — Split latency collector / report / repository (refactor Task 12)

- `latency.py` held three concerns in one module: deterministic SQL + arithmetic,
  the LLM synthesis call, and the DB upsert. Split into `latency_collector.py`
  (`_quantile` / `_pearson` / `_build_turns` / `collect_latency_bundle` + the
  heuristic thresholds), `latency_report.py` (`_SYNTH_SYSTEM` prompt + `SYNTH_MODEL`
  + `synthesize_latency_report`), and `latency_repository.py` (`upsert_latency_analysis`
  / `load_latency_analysis`, owning the jsonb decode + timestamp shaping). `latency.py`
  is now a thin facade: `generate_and_store` chains the three, and it re-exports the
  pieces. The LLM prompt is byte-for-byte unchanged.
- The admin session-detail route no longer parses stored latency JSON inline — it
  calls `load_latency_analysis(pool, sid)` — and imports `_quantile` from the
  collector. Added first dedicated latency tests: `_pearson`, `_build_turns` (intro
  detection, duplicate-bot-start skip, full + tail stall flagging), `collect_latency_bundle`
  stats + cause tagging + correlation verdict + missing-session error, and the
  repository load-mapping (jsonb-as-string decode, None passthrough).

## 2026-06-18 — Share Anthropic JSON synthesis helpers (refactor Task 11)

- `memory.py` and `latency.py` each carried their own copy of the same two
  helpers: a blocking Anthropic `messages.create` run off the event loop via
  `asyncio.to_thread` (concatenating text blocks), and a fence/prose-tolerant
  JSON-object extractor. Extracted both into a new `llm_json.py`:
  `call_anthropic_text(api_key, model, system, prompt, max_tokens=1500)` and
  `extract_json_object(text)`. Both modules now import the shared helpers and
  drop their private `_call_anthropic` / `_extract_json`. Behavior is unchanged
  (same model call shape, same parser). The JSON-extraction tests moved out of
  `test_memory.py` into a new `test_llm_json.py`, which also adds direct coverage
  for `call_anthropic_text` (arg passing + text-block concatenation).

## 2026-06-16 — Remove unused NullSessionRecorder (refactor Task 10)

- `NullSessionRecorder` (a no-op "record nothing to the DB" recorder) was never
  used by `run_bot` — memory-off personas use `SessionRecorder(update_memory=False)`,
  which still records the session for observability and only skips cross-session
  memory. The no-op mode contradicted the product reality that every session is
  recorded, so removed the class and its test rather than wiring it in.

## 2026-06-16 — Split recorder queue / totals / memory kickoff (refactor Task 9)

- `SessionRecorder` mixed four concerns. Moved the mechanical ones into a new
  `recording.py`: `UsageTotals` (a dataclass accumulating token/char totals, with
  `add_llm` / `add_tts`) and `RecordDrainQueue` (the in-memory queue, background
  drain loop, and batched flush dispatch). `SessionRecorder` now orchestrates the
  session-row lifecycle and holds an injectable queue + summary scheduler. The
  fire-and-forget memory summarization is isolated in `_default_summary_scheduler`
  and injectable, so `close()` no longer spawns a background task directly. Public
  interface (`record_*` / `start` / `close` / `session_id`) and `close()`
  idempotency are unchanged; `UsageTotals` and the queue have direct unit tests,
  and recorder tests now drive behavior through an injected fake queue/scheduler.

## 2026-06-16 — Explicit recorder repository methods (refactor Task 8)

- `SessionRecorder` passed arbitrary table names and dict-derived column orders
  into `storage.bulk_insert`, and inlined the session INSERT/UPDATE SQL. Added a
  session repository to `storage.py`: `insert_messages` / `insert_events` /
  `insert_metrics` (each owns its table name + a fixed `*_COLUMNS` order),
  `insert_session`, and `finalize_session`. The recorder's queue now carries a
  `RecordKind` enum instead of raw table strings, and `_flush` dispatches by kind
  to the matching repository method — the recorder no longer names a table or
  builds a column list anywhere. `bulk_insert` stays as the low-level primitive
  the inserters wrap. Each repository method has a fixed-column-order test.

## 2026-06-16 — Isolate the CLI / SmallWebRTC runner (refactor Task 7)

- The Pipecat dev-runner entry point `bot(runner_args)` + the `__main__` block
  and the SmallWebRTC transport imports lived in `bot.py`, loading the SmallWebRTC
  stack on the production `/start-session` import path. Moved them into a new
  `cli_bot.py`; `bot.py` now keeps only production Daily orchestration
  (`run_daily_bot`) and the reusable builders (293 lines, down from 345). Verified
  no `smallwebrtc` module loads when importing `bot`. Local dev command is now
  `uv run cli_bot.py` (readme + CLAUDE.md updated); a smoke test covers the
  Daily / SmallWebRTC / unsupported dispatch branches.

## 2026-06-16 — Break up run_bot into named builders (refactor Task 6)

- `run_bot` inlined every construction and wiring step (~135 lines). Split it into
  module-level builders — `build_stt`, `build_context_aggregators`, `build_pipeline`,
  `create_recorder`, `_load_memory_brief`, `make_kickoff`,
  `register_transport_handlers` — so `run_bot` (now ~45 lines) reads as
  orchestration. STT model selection (nova-3 for English, nova-2 otherwise,
  explicit `stt.model` wins) is now `build_stt` and directly unit-tested. The STT
  stall-recovery messages now live with `build_stt`. No runtime behavior change;
  the existing memory-on / memory-off `run_bot` tests pass unchanged.

## 2026-06-16 — Extract prompt/language policy (refactor Task 5)

- The shared system-prompt appendix and the output-language directive lived in
  `bot.py` and were stitched together inside `build_llm`, mixing prompt policy
  with provider selection. Moved `SHARED_SYSTEM_APPENDIX`, `_LANG_NAMES`,
  `_language_directive`, and the assembly into a new `prompting.py` behind
  `build_system_instruction(persona)`; `build_llm` now just calls it and selects
  the provider. Prompt policy is unit-tested independently (English, French,
  unknown-language fallback, memory-appendix inclusion) in `test_prompting.py`.
  The STT stall recovery messages stay in `bot.py` for now (they belong with the
  Task 6 STT extraction). `bot.py` 357 → 319 lines.

## 2026-06-16 — Provider factory registries (refactor Task 4)

- `bot.build_llm` / `bot.build_tts` were `if provider == …` chains that read each
  provider's API key and built its service inline, so adding a provider meant
  editing core orchestration. Extracted the per-provider factories into a new
  `providers.py` with `LLM_FACTORIES` / `TTS_FACTORIES` registries; `build_llm`
  and `build_tts` are now thin wrappers that assemble the shared inputs and
  dispatch by `persona.llm_provider` / `persona.tts_provider`. Adding a provider
  is now a factory + a registry entry, no orchestration edit. Folded the six
  provider API keys (OpenAI/Anthropic/Groq/Cartesia/Deepgram/Gradium) into the
  Settings object (the keys deferred from Task 3), so factories read
  `get_settings().<provider>_api_key`; both Deepgram key reads (TTS + STT) now
  share that one home. `bot.py` 443 → 357 lines.

## 2026-06-16 — Centralize env reads in a Settings object (refactor Task 3)

- Environment configuration was scattered as import-time module globals across
  `config.py` (Daily/session/signup), `auth.py` (SUPABASE_URL, JWT secret, derived
  JWKS url), `supabase_admin.py` (SUPABASE_URL, service-role key, derived auth
  base), and `recorder.py` (DEPLOY_ENV), each monkeypatched individually in tests.
  Replaced with a single `settings.py` `Settings` dataclass read via
  `get_settings()` at call time (`config.py` removed). Env var names and parsing
  are unchanged. The Supabase/DB reads in `storage.create_pool` and the public
  `/api/config` endpoint now come from settings too. Tests override one object —
  `monkeypatch.setattr(get_settings(), "<field>", …)` — instead of patching many
  module globals, with an autouse conftest fixture resetting the singleton between
  tests. Provider API keys (bot/memory/latency factories) are intentionally left
  for the Task 4/11 factory refactor.

## 2026-06-16 — Split FastAPI routers out of server.py (refactor Task 2)

- `server.py` (541 lines) was a god module owning every route handler, dashboard
  SQL, and shared state. Split the handlers into focused `routes/` modules —
  `public` (config/health/agents/landing redirects), `auth` (login + `/api/me`),
  `sessions` (`/start-session`), `admin` (aggregate/sessions/detail/latency) —
  leaving `server.py` (now 62 lines) responsible only for lifespan, CORS, router
  registration, and the static mount. No route behavior, SQL, or response shapes
  changed. Three supporting modules were introduced: `config.py` (shared env/path
  constants, a minimal precursor to the Task 3 settings object), `deps.py`
  (`get_pool` request dependency so handlers stay directly unit-testable), and
  `session_tasks.py` (the active-bot-task registry shared by `/health`,
  `/start-session`, and lifespan). Route tests were re-homed per module
  (`test_{public,auth,session,admin}_routes.py`), replacing `test_server_helpers.py`.

## 2026-06-16 — Extract Daily room client from server.py (refactor)

- First step of the `docs/refactoring_plan_2026-06-14.md` decomposition (Task 1).
  Moved the Daily REST calls (`_create_daily_room`, `_create_meeting_token`) and
  their constants out of the `server.py` god module into a new `daily_client.py`:
  `create_room`, `create_meeting_token`, plus a `make_client(api_key)` factory
  that owns the `Bearer` auth header and timeout. `start_session` now delegates
  and no longer knows Daily endpoint paths, payload shapes, or the auth scheme.
  Behavior and the `/start-session` response are unchanged. Test fakes moved to
  `tests/fakes.py` (shared by the unit + integration tests); new
  `tests/test_daily_client.py` covers payloads and the client factory.

## 2026-06-14 — Pre-warm LLM connection to cut intro latency

- The agent's self-introduction paid full LLM cold-start cost (~3.4s TTFB, ~4s
  to first word) because the kickoff was the session's first OpenAI/Anthropic/
  Groq request. `bot.py` now fires a cheap `models.list()` on the LLM service's
  own `_client` (the pool the pipeline reuses) the moment the bot boots —
  fire-and-forget, during the idle gap before the caller connects — so the intro
  turn hits a warm connection. Intro is otherwise unchanged (still LLM-generated
  and memory-personalized). Best-effort: prewarm failures are swallowed, never
  breaking a session. Payoff scales with join delay (full on Daily, partial on
  instant local joins).

## 2026-06-14 — Fix double-recorded speaking events

- The `events` table was double-recording every speaking event
  (`user/bot_started/stopped_speaking`). Pipecat broadcasts these as two frame
  instances (downstream + upstream) with different `frame.id`s, so the
  observer's id-based dedup let both through. `observer.py` now also skips a
  frame whose `broadcast_sibling_id` was already recorded — one row per event.
  Note: existing historical rows remain doubled; `latency.py` already tolerates
  this when building turns.

## 2026-06-14 — Per-session latency analysis (dashboard)

- New one-click **Latency analysis** on the session detail page (button left of
  "← all séances"). Runs a deterministic SQL collector (per-stage TTFB stats,
  per-turn perceived latency with intro/stall flags + rule-based cause tags,
  context-bloat-vs-jitter correlation) then one Claude Sonnet 4.6 synthesis call
  that writes the report and flags anything outside the known cause buckets.
- Results stored one-per-session in new `session_latency_analysis` table
  (migration `005_session_latency.sql`) and reloaded with the page if already
  generated; regenerating overwrites.
- New `server/latency.py` (collector + synthesis + upsert);
  `POST /api/sessions/{id}/latency-analysis`; `GET /api/sessions/{id}` now
  includes any stored `latency_analysis`.
- SQL-only for now — log cross-check deferred, so the stall tail is flagged
  heuristically.

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
> Superseded 2026-05-25: SQLite/`server/db.py` was replaced by the Supabase
> Postgres pipeline (`recorder.py` + `storage.py`); the nested persona schema
> on 2026-06-06 dropped the last of the SQLite path. See entries below.

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

## 2026-05-24 — Web deploy + per-agent picker

- FastAPI server (`server/server.py`) fronting the bot: serves the landing
  page, the `/agents` list, and `/start-session`. DigitalOcean App Platform
  deploy via `Dockerfile` + `Makefile` + spec.
- Landing page that lists active personas and lets the caller pick one.
- French language wiring (per-persona `lang`) and a persona reorg.
- Persona v3 of `inigo`.

## 2026-05-25 — Supabase migration: recording, dashboard, auth, memory

### Recording off the audio path → Supabase Postgres
- Replaced the synchronous SQLite `SessionDB` with `server/recorder.py`: a
  `SessionRecorder` that enqueues records on an in-memory `asyncio.Queue`
  (microsecond cost, zero awaits) and a background task batch-drains them to
  Supabase via `server/storage.py` — keeping the audio pipeline off the
  network round-trip.
- Schema lives in `server/migrations/001_init.sql`: `sessions` (with persona
  snapshot + token/char totals), `messages`, `events`, `metrics`.
- `observer.py` now records pipecat `MetricsFrame` contents (TTFB, processing
  time, LLM token usage, TTS char usage) into `metrics`, attributed per
  service.

### Operator dashboard
- `server/static/dashboard.html` + `dashboard.js` + `dashboard.css`: recent
  séances, aggregate KPIs (`/api/aggregate`), and per-session detail
  (`/api/sessions`, `/api/sessions/{id}`) with a per-turn response-latency
  chart (user→bot first word) built from `events`.

### Auth
- Supabase magic-link auth + user accounts; `auth.py` verifies the Supabase
  JWT (JWKS-first, HS256 fallback). `migrations/002_auth.sql` adds a
  `profiles` table, signup trigger, and `sessions.user_id`. Landing page gates
  session creation; `/dashboard` + `/api/*` are admin-only.

### Cross-session memory
- `server/memory.py`: `load_memory_brief` injects a brief of past sessions at
  call start; `summarize_and_persist` runs fire-and-forget at hangup to
  summarize the session into per-user memory (`migrations/003_user_memory.sql`).

## 2026-05-30 — Passwordless email sign-in

- Replaced magic-link emails with email-only, passwordless sign-in to stay
  under the free Supabase email quota: `POST /api/auth/login` mints a one-time
  `token_hash` server-side (service-role key) and the browser redeems it with
  `verifyOtp`. `OPEN_SIGNUP` gates local self-signup vs deployed invite-only.
  Admin REST helpers in `server/supabase_admin.py`.

## 2026-06-06 — Nested persona schema, Deepgram TTS, blank-slate flag

- Restructured persona JSON into a nested, provider-aware schema
  (`agent` / `persona` / `llm` / `tts` / `stt`); dropped the last SQLite code.
  Single parse point in `server/personas.py` → typed `Persona`.
- Added **Deepgram** as a TTS provider alongside Cartesia; `build_tts` routes
  on `tts.provider`. Switched `yarden_mini` to `aura-2-pandora-en`.
- `agent.memory` flag (default true): `false` = blank slate (no past-session
  retrieval). Shown on the agent card.
- Comprehensive offline test suite (`server/tests/`).

## 2026-06-07 — Latency work, session detail page, observability fixes

- **Latency analysis** (`docs/latency_analysis.md`): decomposed perceived
  latency (user→bot first word) — dominated by LLM TTFB; STT/LLM *processing*
  totals overlap speech/playback and aren't on the critical path.
- **Per-persona `TextAggregationMode`**: new `pipecat` section in persona JSON
  (`SENTENCE` default | `TOKEN`), passed through `build_tts` to both TTS
  services, so a persona can opt into token streaming for lower first-word
  latency without code changes.
- **Decoupled recording from memory**: blank-slate personas
  (`memory: false`) are now still recorded for the dashboard;
  `SessionRecorder` gained `update_memory` to skip only the cross-session
  memory write. (Previously they used a no-op recorder and never appeared.)
- **`tts_chars` fix**: the WebSocket `DeepgramTTSService` never emits TTS usage
  metrics, so `total_tts_chars` read 0. The observer now estimates it from the
  assistant transcript length when the provider reports nothing — avoiding
  double-counting for Cartesia.
- **`/sessions/{id}` detail page**: clicking a séance opens a standalone page
  instead of an inline expand; shared formatters/auth extracted into
  `format.js` / `auth.js`.

## 2026-06-13 — Markdown system prompts, Monty Spock, more TTS/LLM providers

- **System prompts moved to markdown**: persona prompts pulled out of the JSON
  files into `personas/systemprompts/<name>.md`, loaded by `server/personas.py`.
  Came with a persona reorg/rename — `inigo2/3*` → `inigo_v2_en` / `inigo_v3` /
  `inigo_v4_fr`, and `marie_egg` → `marie_weather`.
- **`monty_spock` persona** added (JSON + markdown prompt).
- **Groq LLM provider**: `build_llm` now routes a `groq:` prefix to Groq-hosted
  models (the swappable fast-LLM path from `notes.md`).
- **Deepgram TTS speed control**: new `server/deepgram_tts.py` wrapper exposing a
  per-persona speed setting, routed through `build_tts`.
- **Gradium (Kyutai) TTS provider**: added as another `tts.provider` option,
  plus `monty_spock` voice tuning. Test coverage in `test_bot_factories.py` /
  `test_personas.py`.
- Planning notes, research docs, and Claude Code permissions checked in.

## 2026-06-14 — Deepgram STT stall recovery

- **STT stall watchdog**: new `server/deepgram_stt.py` with
  `StallGuardedDeepgramSTTService`, a `DeepgramSTTService` subclass that guards
  against a silently half-open Deepgram socket — the one failure pipecat does
  *not* auto-recover (audio/keepalive/finalize keep sending fine but no final
  transcript ever returns, so the LLM is never triggered and the bot goes deaf
  until hangup; observed in session e5b1d767-…, 24s STT TTFB, no transcript).
  If a turn ends with no final transcript within `stall_timeout` (6s), it forces
  a reconnect via the base `_request_reconnect` so the next turn lands on a
  healthy socket, and speaks a `recovery_message` so the dead air is audible.
- Wired into `bot.py` in place of the bare `DeepgramSTTService`.
- **Fail-fast on bad Deepgram credentials**: `StallGuardedDeepgramSTTService`
  overrides `_connection_handler` so a 401/403 (invalid `DEEPGRAM_API_KEY`)
  stops reconnecting instead of retrying ~1.5×/s forever; transient errors still
  retry, now with a 1s backoff.
- **No API key in logs**: the Deepgram handshake exception embeds
  `Authorization: Token <key>`, which pipecat logged verbatim; reconnect logging
  now scrubs `Token <secret>` via `_redact_secrets` so the key never reaches the
  DigitalOcean log store.

## 2026-06-14 — Dashboard agent filter, per-session environment tag

- **Dashboard sessions table**: column headers plus agent and environment
  filter dropdowns (the `envt` column sits right of the agent name); the
  `/api/sessions` query gained composable `persona` + `environment` filter
  params and returns the distinct values to populate the dropdowns (`server.py`,
  `static/dashboard.{html,js,css}`).
- **Per-session environment tag**: `migrations/004_environment.sql` adds an
  `environment` column to `sessions`; `recorder.py` stamps each row from the
  `DEPLOY_ENV` env var — `local` (dev, set in `.env`) or `online` (deployed
  Pipecat Cloud secret set). Falls back to `unknown` when unset, and existing
  rows backfilled to `unknown` since their location can't be known in hindsight.
- Minor: `monty_spock` tts key reorder; test fix for the new persona filter param.
