For session c5cb0669-287e-4288-a425-333226eda2f6:

1. STT processing
      - Avg 0.994s
      - P90 2.655s
      - Max 4.892s
      - Largest cumulative total: 283.18s
  2. LLM processing
      - Avg 1.029s
      - P90 2.805s
      - Max 5.493s
  3. LLM TTFB
      - Avg 0.623s
      - P95 1.702s
      - Max 2.759s

In the session dashboard responce latency I see
median : 1.20s

what is the main cause of this rather high median latency for that session

---

What the 1.20s actually measures

The dashboard's "response latency" is bot_started_speaking − user_stopped_speaking
(server.py:_pair_response_latencies). That is the perceived latency: the user goes quiet,
and 1.20s later (median, over 30 turns) they hear the first word. One caveat —
user_stopped_speaking only fires after the VAD confirms silence (stop_secs = 0.2s, the
pipecat default, since you pass a bare SileroVADAnalyzer()). So the human-felt pause from
"I finished talking" is ≈ 1.20s + 0.2s ≈ 1.4s.

The real decomposition (this session, median turn)

This session ran Anthropic Haiku 4.5 + Deepgram STT + Deepgram TTS, with prompt caching
working near-perfectly (382K cache-read vs 680 uncached tokens — so caching is not a
problem).

┌────────────────────────────────────────┬────────┬─────────────┬────────────────────┐
│               Component                │ Median │  Share of   │ On critical path?  │
│                                        │        │    1.20s    │                    │
├────────────────────────────────────────┼────────┼─────────────┼────────────────────┤
│ LLM TTFB (Haiku first token)           │ 0.584s │        ~49% │ ✅ dominant        │
├────────────────────────────────────────┼────────┼─────────────┼────────────────────┤
│ STT finalize tail + first-sentence     │ ~0.42s │        ~35% │ ✅ (derived:       │
│ wait + overhead                        │        │             │ remainder)         │
├────────────────────────────────────────┼────────┼─────────────┼────────────────────┤
│ TTS TTFB (Deepgram first audio)        │ 0.196s │        ~16% │ ✅                 │
├────────────────────────────────────────┼────────┼─────────────┼────────────────────┤
│ LLM TTFB + TTS TTFB                    │  0.78s │         65% │ —                  │
└────────────────────────────────────────┴────────┴─────────────┴────────────────────┘

Main cause: LLM time-to-first-token — ~0.58s, roughly half the wait. Even with optimal
caching, that's Haiku's network round-trip + prefill + first-token time for your workload.

Why your STT/LLM "processing" numbers misled you

Those big totals are not what the user waits for:

- STT processing (0.99s avg, 286 samples) runs while the user is still talking — it
overlaps speech. Only the short finalization tail after speech-end is on the critical
path, not the full 0.99s.
- LLM processing (1.02s avg) is the whole response generation. But TTS starts speaking at
the first sentence (SENTENCE mode — confirmed earlier), so most of that 1.02s overlaps
with the bot already talking. It affects total turn duration, not first-word latency.
- The scary cumulative totals (283s of STT) are just sums across a 23-minute session —
irrelevant to per-turn feel.

Correction to what I said earlier

I was wrong that Deepgram-WS doesn't record TTS TTFB — the data shows it does (0.196s
median, via the base audio-context path that stops the TTFB timer when the first audio
frame arrives). My grep only checked the Deepgram file; the bracketing lives in the base
class. The tts_chars gap was real; the TTS-TTFB gap was not.

Levers, ranked by impact

1. LLM TTFB (~0.58s, the big one). Haiku is already fast and caching is maxed. The
highest-impact move is the swappable fast LLM in your notes.md plan — Groq-hosted Llama
typically has TTFB ~0.2–0.3s, which could roughly halve the dominant term. This is your
best lever.
2. The ~0.42s middle bucket. Switching TTS to TOKEN mode removes the
wait-for-first-sentence (start synthesizing on first tokens) — on Deepgram WS this is
smooth, not choppy, and could shave ~0.1–0.2s (tradeoff: number/abbreviation
normalization, as we discussed). Tightening Deepgram STT endpointing or VAD stop_secs also
helps but risks cutting users off.
3. TTS TTFB (0.196s). Deepgram Aura is already quick; little to gain.

Also worth noting the tail: mean 1.59s and p90 2.66s exceed the median because LLM TTFB
spikes (p90 1.0s, max 2.76s) drag slow turns. So a faster/steadier LLM helps both the
median and the tail.

Want me to (a) make text_aggregation_mode a per-persona field so you can A/B SENTENCE vs
TOKEN, and/or (b) add a Groq LLM provider to build_llm so you can measure TTFB against
Haiku on the same personas?

✻ Crunched for 4m 27s

❯ **what is the finalization tail ?**


⏺ The **finalization tail** is the gap between when the user stops making sound and when the STT
engine emits its final transcript.

While you talk, Deepgram streams interim (provisional) transcripts. When you stop, it
waits a moment — to confirm you're really done (endpointing) and to lock in the last words
— before emitting the final transcript that gets sent to the LLM. That waiting gap is the
finalization tail.

It's on the critical path because the LLM can't start until that final transcript lands.
In my decomposition it's part of the ~0.42s "middle bucket" (lumped with the
first-sentence wait), governed by Deepgram's endpointing setting and the VAD stop_secs.

**options to speed things up**

- switch to TOKENS mode vs SENTENCE mode
- change LLM to a faster one (e.g. Groq)

Latency-reduction options (session 1.20s median; LLM TTFB ~0.58s is ~half):

- Swap to a faster LLM (biggest lever) :
  - Groq-Llama / Gemini Flash have ~0.2–0.3s TTFB vs
  - Haiku's 0.58s; could roughly halve the dominant term.
- TTS → TOKEN mode:
  - start synthesizing on first tokens instead of waiting for a full sentence; smooth (not choppy) on Deepgram WS. Saves ~0.1–0.2s.
  - Tradeoff: weaker number/abbreviation normalization.
- Tighten endpointing:
  - lower Deepgram STT endpointing and/or VAD stop_secs (currently 0.2s) to shrink the finalization tail.
  - Tradeoff: too aggressive cuts users off mid-sentence.

also:
- Keep prompt caching maxed — already ~99.8% hit rate here, so no gain available, but don't regress it (cache misses spike TTFB).
- Shorter first sentence — prompt the persona for a brief opening clause so SENTENCE mode
  flushes to TTS sooner. Low effort, modest gain.
- Low/no further gain: TTS TTFB (0.196s, already fast) and STT/LLM processing times
  (overlap speech / bot playback — not on the critical path).
