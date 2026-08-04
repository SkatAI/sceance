# Two frameworks, one bench: a field report on porting a voice agent from Pipecat to Gradbot

*Notes from running the same voice agent on two frameworks — and why the latency
numbers they produce cannot be compared, including by us.*

---

## TL;DR

We ported a voice agent from **Pipecat** (an opensource Python framework where you assemble a
pipeline of swappable parts) to **Gradbot** (Gradium's framework, where a Rust core
owns the whole speech loop). Two of the bench's nine personas were ported. Both
stacks write traces into one shared Postgres database, tagged by framework, so that
their metrics could sit side by side.

They sit side by side. They still don't compare, for three structural reasons:

**1. The same metric name times different spans.** Both stacks record a TTS `ttfb`
for the same synthesis vendor. Pipecat reports a median of 0.211s, Gradbot 0.361s.
Pipecat's stopwatch starts when a finished sentence is handed to the synthesizer;
Gradbot's starts at the first word out of the language model. Same label, different
clock.



**2. The architecture runs opposite to the number.** Pipecat posts the faster TTS
figure while being the framework that deliberately buffers text until a sentence
boundary (~200–300ms, by its own documentation) — a delay that sits *upstream* of
its stopwatch. Gradbot posts the slower figure while feeding the synthesizer
roughly one word at a time. Read naively, the numbers suggest the opposite of what
the code does.

**3. Some numbers exist on only one side.** Gradbot's core makes the LLM call
internally and does not re-emit token usage; it runs speech recognition internally
and reports no STT timing. Those columns are empty in its telemetry — comparable
figures would have to come from outside the framework (the LLM provider's usage
logs, for instance), which we have not yet done.

The headline pair — **1.38s (Gradbot) vs 2.37s (Pipecat)** under identically named
"perceived latency" events — is the clearest case. Gradbot's event fires *after*
transcription has produced text, so its number excludes speech recognition;
Pipecat's includes it. These are what each stack *reports*, not what a caller
experiences, and a rough decomposition below accounts for most of the gap as
stopwatch placement.

We also ended the experiment by deliberately breaking it: the turn-taking setting
that kept the two stacks' numbers aligned was cutting callers off mid-sentence on
the Gradbot side, so we changed it. Correctness beat comparability. That was the
right trade, and it is also why this report draws no conclusion about which
framework is faster.

---

## Background: the three stages and the one hard problem

A real-time voice agent is a loop: **STT** (the caller's audio streams into a
transcriber), **LLM** (the text streams into a language model), **TTS** (the reply
streams into a synthesizer and back to the caller's ear).

The hard problem is **turn-taking** — deciding when the human has finished
speaking. Wait too long and the agent feels dead; commit too early and it answers
the first half of your sentence while you're saying the second half.



Two measurements recur below:

- **TTFB** — for one stage, time from receiving work to first output. The standard
  streaming metric: the rest of the output arrives while the first part plays.
- **Perceived latency** — the pause the human feels, from end of their speech to
  start of the agent's. It is the sum of everything, and no single stage's TTFB
  predicts it.

Everything real is streaming: stages overlap, synthesis begins while the model is
still writing. *Where* each framework overlaps them is its main design decision,
and it is exactly where the two diverge.

---

## The two frameworks

**Pipecat** ([repo](https://github.com/pipecat-ai/pipecat)) is an open-source
Python framework. You assemble a pipeline of stages — transport in, STT, turn
aggregation, LLM, TTS, transport out — and data flows through as frames. Every
stage is a swappable Python object; on this bench, four LLM providers, three
synthesizers and two transcribers have run through the same pipeline. When a
vendor doesn't expose something, you subclass: we added a speech-rate parameter
to one TTS service and a reconnecting watchdog to one STT service that way.

**Gradbot** ([repo](https://github.com/gradium-ai/gradbot)) is Gradium's
framework. A Rust engine owns the entire STT → LLM → TTS loop as one process: it
talks to the transcriber, calls the model, drives the synthesizer, decides when
the turn ended, handles barge-in. Your Python hands it a config struct
(`voice_id`, `instructions`, `flush_duration_s`, …) and pipes audio to the
browser.

That is the trade in one image: a box of parts with open seams, versus an engine
with a config surface. Which is right depends on whether what you need to change —
or *see* — is something the engine's authors exposed.

---

## The worked example: when does the agent start speaking?

The LLM emits its reply token by token; the synthesizer needs text. **How much
text do you accumulate before synthesizing?** More text, better prosody; less
text, earlier speech. A genuine trade-off, answered differently:

- **Pipecat buffers to sentence boundaries.** Its documentation states the cost
  plainly: sentence mode "produces more natural speech but adds latency
  (~200–300ms per sentence)." All personas on this bench run in sentence mode.
- **Gradbot pushes at word boundaries.** It also opens the synthesizer connection
  before the first token exists, overlapping connection setup with the model's
  first-token time. The only buffering is sub-word (keeping `don't` and `$50,000`
  intact).

So Pipecat *feeds its synthesizer* sentences; Gradbot feeds it words. (What the
vendor does server-side with a one-word input — synthesize immediately or
accumulate internally before committing to prosody — is not visible from either
framework, a point we return to.)

Both stacks record a TTS `ttfb` for the same vendor:

| framework | processor | window | n (measurements) | median TTFB |
|---|---|---|---|---|
| Pipecat | `GradiumTTSService` | Jun 13 – Jul 13 | 247 | **0.211 s** |
| Gradbot | `GradiumTTS` | Jul 13 – Jul 14 | 88 | **0.361 s** |

(The windows share a single day; conditions are not matched.)

Pipecat's span: sentence handed to synthesizer → first audio. Gradbot's span:
first word out of the LLM → first audio, so it additionally contains word
accumulation and, possibly, vendor-side buffering triggered by receiving text
one word at a time. The 150ms gap is therefore dominated by stopwatch placement —
though not *purely* an artifact: input granularity is itself a variable, since
first-chunk synthesis time is unlikely to be independent of how much text the
vendor receives. What the gap does **not** support is any ranking of the two
frameworks, or of the vendor.

---

## Why the latency comparison doesn't work

### The headline number

Both stacks emit events named "user stopped speaking" / "bot started speaking",
and pairing them gives:

| framework | n (turns) | median | 90th percentile |
|---|---|---|---|
| Gradbot | 79 | 1.38 s | 2.45 s |
| Pipecat | 1,405 | 2.37 s | 12.01 s |

Three reasons to resist reading this as a race:

**The anchors differ.** Pipecat fires `user_stopped_speaking` after a chain —
0.2s of VAD silence (Silero), a neural end-of-turn judgment (Smart Turn v3), then
transcription finalization — all inside its stopwatch. Gradbot fires its
equivalent from a `Flushing` event that (per the Rust source) is emitted only
*after* transcribed text has arrived: speech recognition sits before its
stopwatch.

A rough decomposition using this bench's own figures: Pipecat's measured STT TTFB
runs 0.56–0.64s, plus the 0.2s VAD window, plus Smart Turn inference (not
separately measured here). Subtracting the measurable pieces from 2.37s leaves
roughly 1.5–1.6s — close to Gradbot's 1.38s. Most of the gap is accounted for by
where the clocks start. *(Per-turn verification against the shared database is
the outstanding work here; this arithmetic uses medians from different
distributions.)*

**The Gradbot figure is stale in its own favor, twice.** Most of the 79 turns
were recorded while a turn-flush window of 0.2s was truncating turns mid-sentence
(see below). Committing turns early shortens measured latency, so the bug biases
the 1.38s *downward*. And the fix raised the flush window to 0.6s, adding ~0.4s
of deliberate waiting to every subsequent turn. The number in the table describes
a configuration that no longer exists.

**The pairing query is suspect at both tails.** The 12s p90 on the Pipecat side
comes from pairing each "user stopped" with the *next* "bot started" — abandoned
or unfinished turns produce enormous phantom gaps. But a query that contaminates
the p90 contaminates the median too, just less visibly. Both statistics need
recomputing on filtered pairs before either is quoted. *(Also outstanding
database work.)*

### One framework, two truthful clocks

Gradbot logs its own LLM latency: `ttft_ms=87`. Per the Rust source, that
stopwatch starts after the HTTP request is already open. Our tracing, anchored to
the moment text was handed to the model, records 517ms for the same turn — 430ms
apart, which matches the low end of the connection setup times observed in a
recorded debug session (430–1,483ms). Both numbers are honest; they answer
different questions. Quote either without naming its anchor and you have misled
someone.

*(One caveat we could not resolve from outside: whether that setup cost recurs
per turn or reflects the absence of connection reuse in our configuration. Worth
confirming against the pinned source before citing.)*

### The near-tie that means nothing

LLM TTFB: 0.607s median on Gradbot, 0.622s on Pipecat's Anthropic path — 15ms
apart. Not comparable either: different models, different providers, and the
Pipecat side carries a ~4,400-token average prompt with a memory feature the
Gradbot personas don't run. Two systems agreeing on a number while doing
different work is coincidence, not comparability.

### The one-sided columns

Gradbot's telemetry reports no token usage and no STT timing — both live inside
the core. On the Pipecat side: ~4,400 prompt / ~300 completion tokens on average,
and per-vendor STT TTFB of 0.56–0.64s. Cost and STT timing for Gradbot are
recoverable *outside* the framework (provider usage logs; audio-level timing),
but not from its own telemetry, and not retroactively for the sessions already
recorded.

### The samples

138 Pipecat sessions over seven weeks — spanning prompt changes, four models,
three synthesizers — against 19 Gradbot sessions over two days of testing a
brand-new port, largely by one user, partly during a known turn-taking bug. Any
statistic across these two corpora compares eras and populations as much as
frameworks.

---

## What actually bit us

The port took two days; most of it was not writing code.

**The browser silently discarded all audio.** Gradbot's bundled player detects
audio via `data instanceof Blob`. We had set the WebSocket to
`binaryType = "arraybuffer"`; every audio frame failed the check, fell into the
JSON branch, and vanished. Cost: an afternoon.

**The agent answered silence.** `silence_timeout_s` defaults to 5s, after which
the core injects the literal string `"..."` as a user turn and runs a full
LLM → TTS cycle on it — the agent elaborates or re-asks, unprompted. A reasonable
default for a demo agent; wrong for a persona where silence is the point. Both
personas now pin it to `0.0`.

**Every recorded latency was 0.000s and everything looked fine.** Gradbot
messages carry a `time_s` field that is always 0.0 (declared, sent, never
populated in the binding we pinned), and `start_s`/`stop_s` fields that are
positions within the synthesized audio, not wall-clock times. Our first tracing
trusted them; every event in a turn collapsed onto one timestamp — while the
transcripts stayed perfect, which is what made it dangerous. Timestamps now come
from the local clock on message arrival, with tests forbidding those fields.

**Observability required a fork.** The session handler forwards core messages to
the browser with no hook to observe them, and drops the timing field during wire
conversion. No middleware, no event bus, no callback. We copied the file, added a
one-line callback, and pinned Gradbot to an exact version, accepting the
maintenance cost of a divergent copy.

**And the one that started the investigation: turn truncation.** Callers said the
agent caught the start of a sentence and missed the end. Transcription was
correct; turns were being committed on fragments:

```
on_text  "I'm going"
PushToLlm { user_text: "I'm going" }   ← turn committed on a fragment
on_text  "to" / "be"                    ← lands in the next turn
PushToLlm { user_text: "to be" }        ← answered as its own utterance
```

The transcriber buffers roughly a second of audio before committing to words —
lookahead is where its accuracy comes from — and our flush window was 0.2s: we
were closing turns while words were in flight. We had chosen 0.2s specifically to
match Pipecat's VAD setting so the cross-framework numbers would align. A test
pinned the two values together; when we raised the Gradbot side to 0.6s to fix
the truncation, the alignment — and with it the latency comparison — was
knowingly abandoned. (The pinning test initially kept passing because it
hardcoded the old value as a constant; it has since been corrected to read the
actual configuration.)

---

## What each framework is shaped for

Neither is better; they are shaped for different jobs, and each one's costs are
its strengths seen from the other side.

**Pipecat** is made of parts. Every stage is swappable (demonstrated on this
bench across four LLM providers, three synthesizers, two transcribers), every
seam is observable, token usage is reported, and a canned opening line can play
without an LLM call (~0.5s cold start on this bench). The costs: the
sentence-buffering that improves prosody adds 200–300ms before speech; there are
many moving parts; and significant behavior arrives as silent defaults — Smart
Turn v3, a full neural turn-detection model, runs in this bench's agent without
appearing anywhere in its pipeline code.

**Gradbot** is one engine. The tight Rust loop pre-opens the synthesizer
connection, streams word by word, and paces audio against a jitter buffer; there
are few knobs and correspondingly few ways to hold them wrong; it ships its own
browser audio. The costs: the loop is closed — observing a session required a
fork and a version pin; its timing fields are unusable; usage and STT timing are
not re-emitted; the opening line is LLM-generated (1.2–1.9s cold start on this
bench, and occasional drift from the written greeting) unless you play
pre-rendered audio around the session yourself; it targets one speech vendor; and
macOS wheels are ARM-only.

For a team that wants a voice *agent*, the engine is a real proposition. For a
bench whose purpose is to swap providers and watch the seams, the parts are.
Those are different jobs.

---

## The takeaway

Be suspicious of latency comparisons between voice frameworks — including this
one, which was built to be comparable and wasn't.

Same product, shared database, shared metric vocabulary, a test pinning the
turn-taking settings together — and still: two numbers with one name differing by
70% while timing different spans, a headline gap mostly explained by stopwatch
placement, and columns that exist on only one side. The number you can trust is
the one where you know exactly what starts the clock and what stops it, on both
sides. Everything else is a vibe with error bars.

And when the setting that keeps your numbers comparable is the setting that makes
your agent mishear people, change the setting. We did, we lost the comparison,
and that was the right trade — which is also why this report ranks nothing.

---

*Figures come from traces of both applications sharing one Postgres database (138
Pipecat sessions, May 25 – Jul 13; 19 Gradbot sessions, Jul 13 – 14; `n` in
tables counts measurements, not sessions), plus one recorded debug session with
per-turn timings. All claims about framework internals refer to pinned versions:
Pipecat `<commit>`, Gradbot `<commit>` (fill in before publishing). Two analyses
are flagged as outstanding: per-turn latency decomposition, and recomputing
perceived-latency statistics on filtered turn pairs.*
