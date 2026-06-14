# Cold-start latency (the intro takes ~4s)

Status: **mitigated 2026-06-14** via LLM connection pre-warm (option 2 below).
The intro still routes through the LLM but no longer pays connection cold-start;
`bot.py` fires a throwaway `models.list()` on the LLM service's `_client` at
boot, before the caller joins, so the kickoff call reuses a warm pool. Payoff
scales with join delay (full on Daily, partial on instant local joins). The
canned-TTS opening (option 1) was *not* taken: `opening_messages` turned out to
be a generation instruction (it greets from memory and asks the caller's name),
so a static line would drop personalization the coach/friend product wants.

## Symptom

The very first thing the caller hears — the agent's self-introduction — lands
~4 seconds after the participant joins. Every subsequent turn is fast
(median ~1.45s user→bot first word), so the slow open is the most-felt latency
in a session: it's the caller's first impression and there's nothing happening
to mask it.

Observed in online session `bf779b37-0166-479c-a768-555d78741f5f`
(Yarden Mini, OpenAI gpt-4.1, Deepgram TTS):

- `08:04:25.7` participant joins → kickoff fires.
- `08:04:29.1` LLM finishes first token. **LLM TTFB = 3.438s.**
- `08:04:29.8` bot starts speaking. ≈ **4.1s** from join to first word.

## Root cause

The intro is generated **through the LLM**, on a cold connection:

1. `bot.py` kickoff sends a synthetic prompt ("Introduce yourself. State your
   name …") to the LLM the moment the participant joins.
2. That first OpenAI Responses API call pays cold-start cost (no warm
   connection, full system prompt uploaded for the first time) → 3.4s TTFB,
   vs 0.06–0.7s for warm mid-call turns.
3. Nothing is spoken until the LLM returns, so the whole 3.4s is dead air.

Confirmed it is **not** context size: across the same call, prompt context grew
329→846 tokens but TTFB did **not** track it (the 846-token turn returned in
1.2s, a 574-token turn took 2.28s). It's connection/cold-start + API jitter, so
trimming history will not help the intro.

## Fix options (in rough order of value)

1. **Canned opening line via TTS (recommended).** Personas already carry
   `opening_messages` in the JSON schema. Speak the opening line directly as a
   `TTSSpeakFrame` instead of routing the first turn through the LLM. Removes
   the LLM from the critical path for the intro entirely: ~4s → ~0.5s (just TTS
   TTFB). The LLM only engages once the user actually speaks.
   - Caveat: a static opening can't react to the memory brief. For
     memory-enabled personas that personalize the greeting, this trades a bit
     of warmth for latency — make it per-persona if needed.
2. **Pre-warm the LLM connection** at pipeline start (a throwaway tiny request
   during `join`, before the participant arrives) so the first real call is
   warm. Cheaper to implement, smaller win, still routes the intro through the
   LLM.
3. **Faster model for the first turn** (e.g. Groq/Llama or `gpt-4.1-mini`).
   `monty_spock`'s Groq path showed tighter TTFB in other logs. Helps spikes
   generally, not just the intro.

Options 1 and 2 are independent and can be combined.

## How to measure it

Per-turn perceived latency lives in the `events` table; the intro turn shows up
as a `bot_started_speaking` with no preceding `user_stopped_speaking`. See
[`session_latency_analysis.md`](./session_latency_analysis.md) for the queries —
the intro is the first row (NULL "previous user stop"); time it from the
`bot.py` kickoff log line to the first `Bot started speaking`.
