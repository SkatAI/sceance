# Refactoring Plan - 2026-06-14

This plan updates the earlier audit in `docs/codex_refactoring_plan.md` after re-reading the current codebase. Some earlier recommendations have already been partly addressed: the frontend dashboard has been split into `auth.js`, `format.js`, `dashboard.js`, and `session.js`, and the server now has focused tests under `server/tests/`.

The remaining issues are mostly backend boundary problems: large modules still mix HTTP, orchestration, persistence, provider construction, and LLM side effects. The tasks below are intentionally granular so a coding agent can take one item, make the change, and verify it without needing to complete the whole plan.

## Current Design Pressure Points

- `server/server.py` is still a god module. It owns app construction, config endpoints, auth login, persona listing, Daily room creation, bot task lifecycle, dashboard SQL, session detail shaping, latency-analysis triggering, and static routing.
- `server/bot.py` still mixes provider factories, prompt construction, STT/TTS/LLM wiring, memory injection, recorder startup, transport event handlers, Pipecat pipeline assembly, and CLI runner support.
- `server/recorder.py` still combines session lifecycle, hot-path queueing, batching, generic table persistence, token totals, close semantics, and background memory summarization kickoff.
- Persistence is too implicit. `storage.bulk_insert(pool, table, columns, rows)` plus recorder-supplied table names is flexible, but brittle and harder to test than explicit repository methods.
- Provider selection uses `if provider == ...` chains in `build_llm` and `build_tts`, so adding a provider edits core orchestration code.
- `memory.py` and `latency.py` duplicate Anthropic call and JSON extraction patterns.
- `latency.py` has deterministic collector logic, LLM prompt synthesis, model calls, and DB upsert in one module, and currently appears to have no dedicated tests.
- `personas.py` is improved from the old audit, but one wide dataclass still carries agent metadata, prompt config, LLM config, TTS config, STT config, and Pipecat tuning fields.
- `server/static/app.js` still duplicates Supabase boot and token handling that operator pages already centralized in `server/static/auth.js`.
- Ruff is configured to check imports only, so many design-preserving cleanup rules are not enforced.

## Task 1 - Extract Daily Room Client

**Principle:** SRP, DIP, KISS  
**Files:** `server/server.py`, new `server/daily_client.py`, `server/tests/test_daily_client.py`

Move `_create_daily_room`, `_create_meeting_token`, `DAILY_API_BASE`, and `ROOM_EXPIRY_SECONDS` into a small `DailyClient` module or plain functions that accept an `httpx.AsyncClient`.

Keep behavior identical:

- room payload keeps expiry, room eject, chat/screenshare disabled, video off, audio on
- meeting tokens keep room name, owner flag, and expiry
- `start_session` delegates Daily-specific details instead of constructing payloads directly

Acceptance criteria:

- Existing `test_daily_room_and_token_payloads_include_expected_properties` is moved or rewritten against the new module.
- `server.start_session` no longer knows Daily endpoint paths or JSON payload details.
- No behavior changes to `/start-session` response shape.

## Task 2 - Split FastAPI Routers From `server.py`

**Principle:** SRP, ISP, KISS  
**Files:** `server/server.py`, new `server/routes/*.py`, tests in `server/tests/`

Extract routes into focused modules:

- `routes/public.py`: `/health`, `/api/config`, `/agents`, static page redirects if desired
- `routes/auth.py`: `/api/auth/login`, `/api/me`
- `routes/sessions.py`: `/start-session`
- `routes/admin.py`: `/api/aggregate`, `/api/sessions`, `/api/sessions/{id}`, latency-analysis endpoint

Keep `server.py` responsible for app construction, lifespan, CORS, router registration, and static mount only.

Acceptance criteria:

- `server/server.py` is reduced to app wiring and shared startup/shutdown.
- Route tests continue to import callable route functions or use `TestClient`; avoid losing direct unit-test coverage.
- Shared app dependencies are explicit: `request.app.state.db_pool`, settings object, or dependency provider. Avoid hidden globals where practical.

## Task 3 - Add a Small Settings Object

**Principle:** DIP, KISS  
**Files:** `server/settings.py`, `server/server.py`, `server/auth.py`, `server/recorder.py`, `server/bot.py`

Centralize environment reads that currently happen at import time:

- Daily API key and max sessions
- Supabase URL, anon key, JWT secret, service role key
- deployment environment
- provider API keys used by factories

Use a lightweight dataclass or Pydantic settings model. Keep it simple; this app does not need a full configuration framework unless it materially reduces import-time side effects.

Acceptance criteria:

- Tests can override settings without monkeypatching many module globals.
- `DEPLOY_ENV`, `DAILY_API_KEY`, `OPEN_SIGNUP`, and Supabase auth globals are no longer fixed only at import time.
- Existing behavior and env var names remain compatible.

## Task 4 - Replace Provider `if` Chains With Registries

**Principle:** OCP, DRY  
**Files:** `server/bot.py`, possibly new `server/providers.py`, `server/tests/test_bot_factories.py`

Introduce simple registries for LLM and TTS providers:

- `LLM_FACTORIES = {"openai": build_openai_llm, ...}`
- `TTS_FACTORIES = {"cartesia": build_cartesia_tts, ...}`

Each provider-specific function should validate only its own requirements and construct only its own service.

Acceptance criteria:

- `build_llm` and `build_tts` become thin lookup wrappers.
- Existing provider tests still pass and add one test proving registry lookup rejects unknown providers.
- Adding a provider only requires adding a factory and registry entry, not editing orchestration code.

## Task 5 - Extract Prompt and Language Policy Builder

**Principle:** SRP, DRY  
**Files:** `server/bot.py`, new `server/prompting.py`, tests

Move `SHARED_SYSTEM_APPENDIX`, `_LANG_NAMES`, `_language_directive`, and system-instruction assembly out of provider construction.

Acceptance criteria:

- Provider factories receive a complete system instruction or call a named `build_system_instruction(persona)`.
- Unit tests cover English, French, unknown language fallback, and memory appendix inclusion.
- `build_llm` no longer mixes provider selection with prompt policy details.

## Task 6 - Extract Bot Pipeline Assembly

**Principle:** SRP, KISS  
**Files:** `server/bot.py`, maybe `server/pipeline.py`, `server/tests/test_bot_factories.py`

Break `run_bot` into small functions:

- `build_stt(persona)`
- `build_context_aggregators()`
- `build_pipeline(transport, stt, llm, tts, aggregators)`
- `create_recorder(pool, persona, user_id)`
- `register_transport_handlers(...)`
- `kickoff_conversation(...)`

Do this after the provider registry task so tests can stay focused.

Acceptance criteria:

- `run_bot` reads as orchestration, not construction detail.
- Existing memory-on and memory-off tests still pass.
- There are direct tests for STT model selection: English defaults to `nova-3`, non-English defaults to `nova-2`, explicit persona model wins.

## Task 7 - Isolate CLI / SmallWebRTC Runner Code

**Principle:** YAGNI, SRP  
**Files:** `server/bot.py`, new `server/bot_runner.py` or `server/cli_bot.py`

The production web path uses `run_daily_bot`; the Pipecat CLI entrypoint and `SmallWebRTCRunnerArguments` support add forward-compatibility weight to the core bot module.

Move the `bot(runner_args)` entrypoint and SmallWebRTC transport handling into a separate runner module, or delete it if it is no longer used by deployment.

Acceptance criteria:

- `server/bot.py` keeps production Daily bot orchestration and reusable builders only.
- CLI behavior, if retained, has a minimal smoke test or documented command.
- Imports for SmallWebRTC are no longer loaded on the production `/start-session` import path unless needed.

## Task 8 - Create Explicit Recorder Repository Methods

**Principle:** SRP, KISS, DIP  
**Files:** `server/storage.py`, `server/recorder.py`, `server/tests/test_storage.py`, `server/tests/test_recorder.py`

Replace generic recorder persistence calls with explicit methods:

- `insert_messages(pool, rows)`
- `insert_events(pool, rows)`
- `insert_metrics(pool, rows)`
- `insert_session(pool, ...)`
- `finalize_session(pool, ...)`

This can still use `copy_records_to_table` internally, but table names and column order should live in the repository layer, not in `SessionRecorder._flush`.

Acceptance criteria:

- `SessionRecorder` no longer passes arbitrary table names to storage.
- Tests assert that each repository method uses a fixed, expected column order.
- Queue items can become typed event objects or `(RecordKind, payload)` rather than raw table strings.

## Task 9 - Separate Recorder Queue, Totals, and Memory Summary Kickoff

**Principle:** SRP, ISP  
**Files:** `server/recorder.py`, possible `server/recording.py`, tests

Split responsibilities currently held by `SessionRecorder`:

- queue drain and batch flush
- usage totals accumulation
- session row lifecycle
- memory summary job scheduling

Keep the public recorder interface stable for `TranscriptObserver`.

Acceptance criteria:

- A small `UsageTotals` object has direct unit tests for LLM and TTS accounting.
- Memory summary scheduling is injected or isolated so `SessionRecorder.close()` is not directly creating hidden background tasks.
- Close semantics remain idempotent.

## Task 10 - Remove or Justify `NullSessionRecorder`

**Principle:** YAGNI, KISS  
**Files:** `server/recorder.py`, tests

`NullSessionRecorder` is currently not used by `run_bot`; memory-off personas still use `SessionRecorder(update_memory=False)`. Either remove `NullSessionRecorder` and its tests, or wire it intentionally for a concrete mode such as no-observability local runs.

Acceptance criteria:

- No unused recorder implementation remains.
- If retained, the mode that selects it is documented and tested.

## Task 11 - Share Anthropic JSON Synthesis Utilities

**Principle:** DRY, SRP  
**Files:** `server/memory.py`, `server/latency.py`, new `server/llm_json.py`, tests

Both memory summarization and latency analysis create an Anthropic client, run a blocking call via `asyncio.to_thread`, concatenate text blocks, and extract JSON with fence/prose tolerance.

Create a small shared helper:

- `call_anthropic_text(api_key, model, system, prompt, max_tokens)`
- `extract_json_object(text)`

Acceptance criteria:

- Memory and latency modules use the helper.
- Existing memory JSON extraction tests move to the helper.
- Add equivalent latency/helper tests instead of duplicating parser coverage.

## Task 12 - Split Latency Collector, Synthesis, and Storage

**Principle:** SRP, KISS  
**Files:** `server/latency.py`, new `server/latency_collector.py`, `server/latency_report.py`, `server/latency_repository.py`, tests

Keep deterministic analysis separate from model-based synthesis and DB upsert.

Suggested boundaries:

- `latency_collector.py`: `_quantile`, `_pearson`, `_build_turns`, `collect_latency_bundle`
- `latency_report.py`: prompt, `synthesize_latency_report`
- `latency_repository.py`: `upsert_latency_analysis`, `load_latency_analysis`
- `latency.py`: thin orchestration facade if the route wants one import

Acceptance criteria:

- Add focused tests for `_build_turns`, stall flagging, outlier cause tagging, `_pearson`, and bundle stats.
- The admin route no longer parses stored latency JSON inline; it calls repository/load mapping code.
- The LLM prompt remains unchanged unless a test or product requirement forces a change.

## Task 13 - Extract Dashboard Query Repository

**Principle:** SRP, DRY  
**Files:** `server/server.py`, new `server/dashboard_repository.py`, tests

Move SQL and row-to-JSON mapping for aggregate, session list, and session detail out of route functions.

Acceptance criteria:

- Route functions validate query/path params and call repository functions.
- Repository functions return already-shaped dictionaries or typed dataclasses.
- Tests for filter SQL cover persona-only, environment-only, both filters, and no filters.
- Dynamic SQL remains parameterized; no raw user input is interpolated into SQL except controlled placeholder positions.

## Task 14 - Normalize Session Detail Persona Projection

**Principle:** SRP, KISS  
**Files:** `server/server.py` or new presenter module, tests

`api_session_detail` currently loads `persona_json`, conditionally parses JSON, tries `Persona.from_dict`, falls back to legacy dicts, and builds a persona view inline.

Extract this into `project_persona_snapshot(persona_json)`.

Acceptance criteria:

- Unit tests cover current nested persona dict, JSON string, malformed legacy dict, and `None`.
- `api_session_detail` no longer contains persona parsing branches.

## Task 15 - Consolidate Browser Auth Boot

**Principle:** DRY, SRP  
**Files:** `server/static/app.js`, `server/static/auth.js`

Operator pages use `auth.js`, but the landing page still hand-rolls Supabase config loading, client creation, session lookup, `/api/me`, and auth-state handling.

Extend `auth.js` with reusable primitives for:

- creating the Supabase client from `/api/config`
- fetching `/api/me`
- subscribing to session changes
- producing auth headers for API calls

Do not force the landing page into `bootAdmin`; it needs regular signed-in users, not admin-only access.

Acceptance criteria:

- Supabase `createClient` configuration appears in one file only.
- `app.js` keeps landing-page UI and Daily call behavior, not generic auth boot logic.
- Manual browser check: sign in, start session, sign out, admin dashboard link visibility.

## Task 16 - Convert Large Frontend Render Strings Into Smaller Renderers

**Principle:** KISS, SRP  
**Files:** `server/static/format.js`, `server/static/dashboard.js`

`format.js` is now a mixed formatter and session-detail renderer. Keep the split lightweight:

- `format.js`: pure formatters and escaping
- `session_render.js`: `renderDetail`, `renderLatencyAnalysis`, chart rendering
- optionally `dashboard_render.js`: aggregate/session list rendering

Acceptance criteria:

- Existing imports are updated without behavior changes.
- Rendering modules have no network calls.
- Network modules do not build large HTML blocks beyond page-specific orchestration.

## Task 17 - Tighten Persona Model Boundaries

**Principle:** ISP, SRP  
**Files:** `server/personas.py`, tests

The nested JSON schema is good, but `Persona` is still one wide dataclass with provider-specific and UI-specific fields. Introduce nested dataclasses only if it reduces call-site complexity:

- `AgentConfig`
- `PersonaTextConfig`
- `LLMConfig`
- `TTSConfig`
- `STTConfig`
- `PipecatConfig`

Keep compatibility properties if needed so this can be incremental.

Acceptance criteria:

- Current persona JSON files still parse.
- Provider factories receive `persona.llm` / `persona.tts` style objects or compatibility properties.
- Validation for `temperature` is explicit: `None` or numeric, with a reasonable provider-agnostic range if one is chosen.
- `opening_messages` is validated as a list of `{role, content}` objects.

## Task 18 - Raise Tooling Coverage Gradually

**Principle:** KISS, correctness feedback  
**Files:** `server/pyproject.toml`, source files, tests

Ruff currently selects only import sorting (`select = ["I"]`). Expand linting in a controlled way after structural refactors land.

Suggested first step:

- `E`, `F`, `I`, `UP`, `B`, `SIM`

Acceptance criteria:

- `uv run ruff check .` passes in `server/`.
- Avoid broad style churn in the same PR as architectural moves.
- Add a `make lint` target or update the existing one if it does not run Ruff and Pyright.

## Task 19 - Add Integration Smoke Tests for Route Wiring

**Principle:** regression safety  
**Files:** `server/tests/`, possibly `server/tests/test_routes.py`

Once routers and repositories are split, add a small set of FastAPI-level smoke tests with dependency overrides/fake pool:

- `/health`
- `/agents`
- `/api/me`
- `/start-session` validation errors
- one admin endpoint auth failure path

Acceptance criteria:

- Tests prove router registration and dependency wiring survived the split.
- Unit tests remain the primary coverage for SQL shaping and orchestration.

## Task 20 - Document Runtime Entry Points

**Principle:** KISS, YAGNI  
**Files:** `readme.md`, `server/bot.py`, optional runner module

After splitting production and CLI bot paths, document the supported entry points:

- web server command
- production Daily bot path through `/start-session`
- optional Pipecat CLI runner, if retained

Acceptance criteria:

- A new contributor can tell which modules are production-critical and which are local/experimental.
- Forward-compat code is either documented as supported or removed.

## Suggested Order

1. Extract Daily client and settings first. These reduce global coupling with low behavior risk.
2. Split provider factories and prompt building before touching `run_bot`; this makes the bot orchestration refactor smaller.
3. Refactor recorder persistence before splitting recorder internals; explicit storage methods make the later queue/totals split safer.
4. Split routers and dashboard repositories after the storage and bot seams are clearer.
5. Consolidate frontend auth and renderer files as a separate pass.
6. Tighten Ruff and Pyright only after the major file moves, to avoid combining architecture changes with mechanical lint churn.

## Explicit Non-Goals

- Do not introduce a large framework, dependency-injection container, or service layer for every function. The codebase is small enough that plain modules, dataclasses, and injected functions are sufficient.
- Do not rewrite the frontend in a framework unless there is a separate product requirement. The current static JS approach is serviceable after smaller auth/rendering splits.
- Do not change provider behavior, prompt content, Daily room behavior, or database schema as part of these refactors unless a task explicitly calls for it.
- Do not combine unrelated tasks into one large PR. The value of this plan is that each task should be reviewable and revertible on its own.
