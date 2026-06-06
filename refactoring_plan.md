1. server/server.py:99 is a god module. It owns app lifespan, CORS, auth login, persona
     listing, Daily room creation, bot spawning, dashboard aggregate queries, session detail
     shaping, and static mounting. That contradicts SRP/KISS and makes every feature change
     touch the same file. Split into small routers/services: auth, agents, sessions,
     dashboard, plus a DailyClient.
  2. server/bot.py:164 concentrates provider construction, prompt assembly, STT/TTS/LLM
     wiring, memory injection, recorder startup, Pipecat pipeline creation, event handlers,
     and runner execution in one function. This hurts readability and testability. Extract
     build_pipeline, build_stt, register_transport_handlers, and a small orchestration
     layer.
  3. Provider selection is not open for extension. server/bot.py:91 and server/bot.py:130
     use growing if provider == ... chains. Every new provider requires editing core bot
     code. A simple registry like {provider: factory} would keep the current simplicity
     while respecting OCP.
  4. There is visible YAGNI / future-code weight in server/bot.py:251 and server/bot.py:300:
     RTVI, SmallWebRTC, CLI runner paths, and comments about future TTS providers are
     maintained inside the production bot module. If those paths are not actively used,
     isolate them into adapters or remove them until needed.
  5. server/recorder.py:35 has too many jobs: session row lifecycle, queueing, batching, SQL
     write shape, token totals, shutdown, and summarization kickoff. The hidden side effect
     in server/recorder.py:199 also makes behavior harder to reason about. Consider
     separating SessionStore, RecorderQueue, UsageTotals, and MemorySummaryJob.
  6. server/storage.py:38 plus dynamic table strings from server/recorder.py:178 is flexible
     but brittle. It bypasses explicit repository methods and relies on dict key order
     matching database columns. KISS would favor explicit insert_messages, insert_events,
     and insert_metrics functions.
  7. server/personas.py:32 is a broad config object with provider-specific fields mixed into
     one dataclass. The parser also accepts weakly typed values such as opening_messages and
     temperature without validation. A Pydantic model or smaller nested dataclasses would
     improve contracts and reduce defensive code elsewhere.
  8. server/static/dashboard.js:272 mixes fetching, state, rendering, formatting, manual
     escaping, and inline SVG generation in one 517-line file. The template-string HTML
     approach also makes escaping easy to miss. Splitting API access, formatters, and
     renderers would materially improve maintainability.
  9. Auth bootstrapping is duplicated between server/static/app.js:333 and server/static/
     dashboard.js:466. Both fetch config, create the Supabase client, read the session, and
     handle auth changes. A shared browser module would reduce drift.
  10. Tooling is underused. server/pyproject.toml:27 configures Ruff to check imports only,
     despite pyright and Ruff being dependencies. That misses many readability and
     correctness checks. I also found no test files in the repo, so refactors around
     recorder/session logic would be risky without adding focused tests.

  Priority

  Start with server.py and bot.py: they are the biggest SOLID/KISS pressure points. Then
  separate recorder persistence from summarization, and finally clean up frontend
  duplication. I did not modify any files.