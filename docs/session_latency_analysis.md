# Per-session latency analysis (runbook)

Reproducible steps to analyze the latency of one séance session, cross-checking
the live pipeline logs against what the recorder wrote to Supabase. This is the
manual procedure; the intent is to **automate it to run after every session**
(see "Toward automation" at the end).

Worked end-to-end against session `bf779b37-0166-479c-a768-555d78741f5f`
(Yarden Mini, gpt-4.1, Deepgram TTS) on 2026-06-14.

## What "latency" means here

Two different things — don't conflate them:

- **Per-stage TTFB** — time-to-first-token for STT, LLM, TTS individually
  (`metrics` table, `kind='ttfb'`). Diagnostic: tells you *which stage* is slow.
- **Perceived latency** — wall-clock from the user finishing their turn to the
  bot's first spoken word (`events` table: `user_stopped_speaking` →
  `bot_started_speaking`). This is what the caller actually feels. **Report this
  as the headline number.**

Prior finding (`docs/latency_analysis.md`): perceived latency is dominated by
LLM TTFB; STT/LLM *processing* totals overlap speech/playback and are not on the
critical path.

## Inputs

- `SID` — the session UUID (from the dashboard, or `bot.py` "Recording session
  <id>" log line).
- `SUPABASE_DB_URL` — in `server/.env` (local and prod share one DB).
- Optional: a captured `logs/production.log` for the same session, to cross-check
  the DB against the live pipeline.

## Schema cheat-sheet (`server/migrations/001_init.sql`)

- `sessions` — one row/session: persona, environment (`local`/`online`),
  started/ended, token + tts-char totals.
- `metrics` — `processor`, `kind` (`ttfb` | `processing` | `llm_usage` |
  `tts_usage`), `value_num` (seconds for ttfb/processing), `ts`, token columns.
- `events` — `kind` (snake_case: `user_started_speaking`,
  `user_stopped_speaking`, `bot_started_speaking`, `bot_stopped_speaking`,
  `transcription`, `llm_start`/`llm_end`, `tts_start`/`tts_stop`),
  `timestamp_ns` (pipecat monotonic clock — **nanoseconds since pipeline start,
  not epoch**, so it reads as "seconds into the call", which is fine for deltas).
- `messages` — user/assistant transcripts.

## Steps

Run all queries with:

```bash
cd server
set -a && . ./.env && set +a      # loads SUPABASE_DB_URL (note: file has live keys)
SID="<session-uuid>"
psql "$SUPABASE_DB_URL" -P pager=off -c "<query>"
```

### 1. Session overview

```sql
select persona_name, environment, started_at, ended_at,
       ended_at - started_at as duration,
       total_prompt_tokens, total_completion_tokens, total_tts_chars
from sessions where id='SID';
```

### 2. Per-stage TTFB summary (which stage is slow?)

```sql
select processor, count(*) n,
       round(min(value_num)::numeric,3) min,
       round(avg(value_num)::numeric,3) avg,
       round(max(value_num)::numeric,3) max
from metrics where session_id='SID' and kind='ttfb'
group by processor order by avg desc;
```

Expectation: STT/TTS steady (~0.4s avg); LLM is the dominant + most variable.

### 3. TTFB timeline (spot the spikes)

```sql
select to_char(ts,'HH24:MI:SS') t, processor, round(value_num::numeric,3) ttfb
from metrics where session_id='SID' and kind='ttfb' order by ts;
```

### 4. Perceived latency per turn (the headline) — user stop → bot first word

```sql
with bs as (select timestamp_ns from events where session_id='SID' and kind='bot_started_speaking'),
     us as (select timestamp_ns from events where session_id='SID' and kind='user_stopped_speaking')
select to_char(to_timestamp(bs.timestamp_ns/1e9),'HH24:MI:SS') as bot_first_word,
       round(((bs.timestamp_ns
              - (select max(us.timestamp_ns) from us where us.timestamp_ns < bs.timestamp_ns)
             )/1e9)::numeric,3) as perceived_s
from bs order by bs.timestamp_ns;
```

Reading it:
- First row has NULL previous-stop = **the intro** (no user turn before it).
  Time the intro separately: kickoff log line → first `bot_started_speaking`.
  See [`cold_start_latency.md`](./cold_start_latency.md).
- A row with a very large value (e.g. ~7.9s) right before hangup is usually the
  **stall watchdog** firing (6s timeout + reconnect + recovery line), not a real
  turn — exclude it. Confirm with the
  `deepgram_stt:_on_stall ... forcing STT reconnect` WARNING in the log.

### 5. Perceived-latency stats (exclude intro NULL + stall tail)

```sql
with bs as (select timestamp_ns from events where session_id='SID' and kind='bot_started_speaking'),
     us as (select timestamp_ns from events where session_id='SID' and kind='user_stopped_speaking'),
     lat as (select (bs.timestamp_ns
                     - (select max(us.timestamp_ns) from us where us.timestamp_ns < bs.timestamp_ns)
                    )/1e9 v from bs)
select count(*) turns,
       round(min(v)::numeric,2) min,
       round(avg(v)::numeric,2) avg,
       round((percentile_cont(0.5) within group (order by v))::numeric,2) median,
       round(max(v)::numeric,2) max
from lat where v is not null and v < 30;     -- <30 drops the stall-tail outlier
```

### 6. Is it context bloat or API jitter? (LLM usage growth)

```sql
select to_char(ts,'HH24:MI:SS') t, prompt_tokens, completion_tokens
from metrics where session_id='SID' and kind='llm_usage' order by ts;
```

Compare against the step-3 LLM TTFB timeline: if TTFB spikes do **not** track
prompt-token growth, the slow turns are **OpenAI-side jitter**, not your context
getting long → trimming history won't help; change model/path instead.

### 7. (Optional) Cross-check DB vs live log

The captured `logs/production.log` should match the DB row-for-row. Gotchas:
- DigitalOcean captures sometimes prefix the file with **null bytes**, which
  makes plain `grep` treat it as binary → use `grep -a`.
- Pull TTFB from the log:
  `grep -aoE "[0-9:.]+ .*#0 TTFB: [0-9.]+s" logs/production.log`
- Pull stall/error markers:
  `grep -anE "forcing STT reconnect|will retry|authentication|Client disconnected" logs/production.log`

## How to report it

1. Headline: turns, perceived **median** + **max** (excluding intro & stall).
2. Outliers, each with its cause (intro cold-start / LLM jitter spike / stall).
3. Main cause: per-stage avg table; call out LLM as dominant; state whether
   spikes are context-driven or jitter (step 6).
4. Confirm DB == log if a log was captured.

## Reference: a healthy result (session `bf779b37`, 2026-06-14)

- 2m28s, 7 real turns. Perceived: **min 1.13s · median 1.45s · max 2.63s**.
- Per-stage avg TTFB: LLM 0.84s (max 3.44s), TTS 0.43s, STT 0.43s.
- Outliers: intro ~4.0s (cold start), one 2.63s turn (LLM jitter), one 7.9s
  "turn" = stall watchdog firing at hangup (not latency).
- Spikes did not track token growth → API jitter, not context bloat.

## Toward automation (the goal)

Run this automatically at session end so every séance gets a latency record:

- **Hook point:** `recorder.close()` / the `bot.py` disconnect `finally` block
  already fire at hangup with the `SID` in scope — that's where to trigger it.
- **Shape:** a `server/analyze_session.py` that takes a `SID`, runs steps 1–6
  against the pool, and writes a compact summary (the "healthy result" block
  above) to a `session_latency` table and/or logs it.
- **Surface:** show the perceived median/max + outlier breakdown on the
  dashboard session-detail page (it already computes per-turn response latency
  from `events`; this adds the stage decomposition + cause tagging).
- Keep the stall-tail and intro exclusions (steps 4–5) so the headline number
  reflects real conversational turns.
