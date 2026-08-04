# Two voice agents, one product: a field report on Pipecat and Gradbot

*Notes from porting a real-time voice agent from one framework to another, and
discovering that the two cannot be meaningfully raced against each other.*

---

## TL;DR

We built the same voice agent twice. Same personas, same users, same database —
once on **Pipecat** (a Python framework where you assemble a pipeline of swappable
parts) and once on **Gradbot** (Gradium's framework, where a Rust core owns the
whole speech loop). Both write their traces into one Postgres database, tagged by
which stack recorded them, precisely so we could compare.

Then we tried to compare them, and the comparison fell apart in an instructive way.

**1. The same metric name measures different things.** Both stacks record a number
called `ttfb` ("time to first byte") for the *same* text-to-speech vendor. Pipecat
says 0.211s. Gradbot says 0.361s. Nothing is wrong with either number, and neither
tells you anything about the vendor: Pipecat starts its stopwatch when a finished
sentence is handed to the speech synthesizer, and Gradbot starts its stopwatch at
the first word out of the language model. They are timing different spans.

**2. The architecture points the opposite way from the number.** Pipecat's speech
synthesis *looks* faster in that measurement precisely *because* Pipecat makes it
wait — it holds text back until a full sentence is ready, and that waiting happens
before the stopwatch starts. Gradbot streams words into the synthesizer as they
arrive, so its stopwatch is running during work that Pipecat simply doesn't count.
The stack that looks slower on the metric is the one doing less waiting.

**3. Some things aren't measured at all.** Gradbot's Rust core owns the call to the
language model and never reports how many tokens it used, so our cost columns are
permanently zero on that side, against a 4,384-token average on the Pipecat side.
It also runs speech recognition inside the core, so there is no speech-recognition
timing to compare — not a small number, an *absent* one.

The headline figure looks decisive and isn't. End-to-end, the pause a caller
actually experiences reads **1.38s on Gradbot and 2.37s on Pipecat** — but Gradbot's
clock starts *later in the turn* (after speech recognition has already produced
text), so a large part of that gap is the measurement, not the software.

The most honest thing in this whole story is the ending. The two codebases had a
test pinning their turn-taking settings together so the numbers would stay
comparable. Then we found that the setting on the Gradbot side was cutting people
off mid-sentence, and we changed it — knowingly destroying the comparability to get
an agent that could hear. **Correctness beat comparability, and that is the correct
outcome.**

---

## Part 1: What a voice agent actually does

If you have never built one: a real-time voice agent is a loop with three stages and
one hard problem.

The three stages:

- **STT — speech to text.** Audio from the caller's microphone goes to a
  transcription model, which streams back words.
- **LLM — the language model.** The transcribed text goes to a model like Llama or
  Claude, which streams back a reply, token by token.
- **TTS — text to speech.** The reply text goes to a synthesizer, which streams back
  audio to play into the caller's ear.

The hard problem is **turn-taking**: knowing when the human has finished speaking.
Humans do this with a mix of acoustics, grammar and intent as well as body language, and we do it so well we
never notice. A machine has to guess, and both kinds of mistake are bad. Wait too
long, and the agent feels slow and dead. Cut in too early, and you get the failure
described later in this report. An agent that answers the first half of your
sentence while you are still saying the second half.

Two terms that matter for everything below:

- **TTFB (time to first byte)** — for any one stage, how long from giving it work to
  getting the first output back. It's the standard latency metric because in a
  streaming system, *first* output is what matters; the rest arrives while the
  earlier part is already playing.
- **Perceived latency** — the pause the human actually feels: from the moment they
  stop talking to the moment they hear the agent start talking. This is the number
  that matters to users, and it's the sum of everything: finishing transcription,
  deciding the turn ended, the language model thinking, the synthesizer synthesizing.

**Everything is streaming, and that's the whole game.** A naive implementation waits
for the full transcript, then the full reply, then the full audio: three complete
round-trips, several seconds, unusable. Every real system overlaps these stages —
starts synthesizing speech while the language model is still writing, starts playing
audio while the synthesizer is still working. **Where exactly you overlap them is
the main design decision in a voice framework, and it is where Pipecat and Gradbot
diverge most sharply.**

---

## Part 2: The two frameworks

### Pipecat: a pipeline of parts

[Pipecat](https://github.com/pipecat-ai/pipecat) is an open-source Python framework.
You build a voice agent by assembling a **pipeline**, and data flows through it as
"frames" (an audio chunk is a frame, a transcribed word is a frame, a token from the
language model is a frame). Our pipeline is seven stages:

```python
return Pipeline([
    transport.input(),      # audio in from the browser (via Daily/WebRTC)
    stt,                    # speech-to-text
    user_aggregator,        # assembles the user's turn; owns VAD + turn-taking
    llm,                    # the language model
    tts,                    # text-to-speech
    transport.output(),     # audio out to the browser
    assistant_aggregator,   # records what the agent said, back into context
])
```

Every stage is a swappable Python object, and we have genuinely swapped them. The
traces show four different language-model providers (OpenAI, Anthropic, Groq,
OpenRouter), three synthesizers (Cartesia, Deepgram, Gradium) and two transcribers
(Deepgram, Gradium) all in real use.

Because each stage is just a Python class, you
can also subclass one to fix something the vendor didn't expose — we have a
`SpeedDeepgramTTSService` that adds a speech-rate parameter Pipecat didn't surface,
and a `StallGuardedDeepgramSTTService` that watchdogs the transcription socket and
reconnects if it goes quiet.

### Gradbot: a Rust core

[Gradbot](https://github.com/gradium-ai/gradbot) is Gradium's framework. The
structure is completely different: **a Rust engine owns the entire STT → LLM → TTS
loop as one process.** It talks to the transcriber, calls the language model, drives
the synthesizer, decides when your turn ended, and handles barge-in — all inside
compiled code. Your Python is a thin bridge that hands it a config and pipes audio
between it and the browser.

You configure it, essentially, by filling in a struct:

```python
gradbot.SessionConfig(
    voice_id=...,
    instructions=...,          # the system prompt
    language=...,
    assistant_speaks_first=True,
    silence_timeout_s=0.0,
    flush_duration_s=0.6,      # turn-taking
    ...
)
```

That's the trade in one image. Pipecat gives you a box of parts and full access to
the seams between them. Gradbot gives you an engine with a config surface. Both are
legitimate. Which one is right depends on whether the thing you need to change is
something the engine's authors thought to expose and, as we'll see, on whether the
thing you need to *see* is something they thought to show you.

---

## Part 3: The worked example — when does the agent start speaking?

This is the single clearest illustration of why these two systems can't be raced,
so it's worth going slowly.

The language model produces its reply one token at a time — roughly, one fragment
of a word every few tens of milliseconds. The synthesizer needs *text* to turn into
*audio*. **So: how much text do you wait for before you start synthesizing?**

Wait for more, and the speech sounds better — a synthesizer that can see a whole
sentence knows where the emphasis goes and how the intonation should fall. Wait for
less, and the agent starts talking sooner. This is a real trade-off with no
universally right answer, and the two frameworks answer it differently.

### Pipecat waits for a sentence

Pipecat's text-to-speech stage buffers incoming text and releases it on **sentence
boundaries**. It walks the text character by character looking for sentence-ending
punctuation, and — to avoid being fooled by "Dr." or "3.5" — only accepts it after a
lookahead check confirms a real sentence break.

Pipecat's own documentation is refreshingly blunt about the cost:

> **SENTENCE**: Buffer text until sentence boundaries are detected before synthesis.
> Produces more natural speech but adds latency (~200-300ms per sentence).
>
> **TOKEN**: Stream text tokens directly to TTS as they arrive. Reduces latency but
> may affect speech quality depending on the TTS provider.

All nine of our personas run in `SENTENCE` mode. So the agent does not begin
speaking when the first word arrives from the language model. **It begins speaking
when the first complete sentence has arrived.**

### Gradbot streams words

Gradbot does something quite different, and it does it in Rust. First, it opens the
connection to the synthesizer **before the language model has produced a single
token** — so the ~100ms of connection setup happens *during* the ~100ms the language
model takes to produce its first word. That overlap makes the setup effectively free.

Then it pushes text into the synthesizer at **word boundaries**:

```rust
buffer.push_str(&chunk);
// Send when we have a word boundary (ends with space or sentence punctuation).
// This ensures "don't" and "well-known" stay together.
let is_word_boundary = matches!(last_char, Some(' ' | '.' | '!' | '?' | ',' | '\n'));
if is_word_boundary {
    tts_tx.send_text(&buffer).await?;
    buffer.clear();
}
```

A space counts as a boundary, so in practice the synthesizer receives text roughly
**one word at a time**, milliseconds after the language model emits it. The only
buffering is sub-word: keeping `don't` intact, and a one-step lookahead so `$50,000`
and `6.1%` don't get split at the punctuation.

There is no sentence aggregation anywhere in Gradbot. **Pipecat speaks in sentences.
Gradbot speaks in words.**

### And now the measurement breaks

Both stacks record a metric called TTS `ttfb`. Here is where each starts its
stopwatch:

- **Pipecat** starts it when the finished sentence is handed to the synthesizer. All
  the sentence-waiting has *already happened* and is not in the number.
- **Gradbot** starts it at the **first word out of the language model** and stops it
  at the first audio. So its number includes accumulating words, the network hop, and
  the synthesis.

Now look at what the database says. This is the *same synthesis vendor*, Gradium,
measured under both frameworks, on overlapping dates:

| framework | processor | sessions overlap | n | median TTFB |
|---|---|---|---|---|
| Pipecat | `GradiumTTSService` | Jun 13 – Jul 13 | 247 | **0.211 s** |
| Gradbot | `GradiumTTS` | Jul 13 – Jul 14 | 88 | **0.361 s** |

Same vendor. Same voice. A 150ms gap. And it says **nothing whatsoever about
Gradium**, and nothing about which framework gets the agent talking sooner. It is
almost entirely an artifact of where each framework starts counting.

Worse — and this is the part that should make anyone nervous about vendor
benchmarks — **the number runs opposite to the architecture.** Pipecat posts the
faster TTS TTFB while being the framework that deliberately *delays* synthesis by up
to 300ms waiting for a sentence. That delay is real, the caller feels it, and it is
invisible in the metric because it happens upstream of the stopwatch. Gradbot posts
the slower TTS TTFB while being the framework that starts synthesizing after roughly
one word.

If you took these two numbers at face value you would conclude the exact opposite of
what the code does.

---

## Part 4: Why the latency comparison doesn't work

The TTS example is not an isolated quirk. It's the pattern.

### The headline number, and why it's not a race

Perceived latency — from "user stops talking" to "agent starts talking" — is *the*
number. Both stacks record it, from events with identical names:

| framework | n (turns) | median | 90th percentile |
|---|---|---|---|
| Gradbot | 79 | **1.38 s** | 2.45 s |
| Pipecat | 1,405 | **2.37 s** | 12.01 s |

Gradbot looks 40% faster. Resist that conclusion, because **the two stacks do not
agree on when the user stopped talking.**

- **Pipecat** fires `user_stopped_speaking` after a chain: Silero (a voice-activity
  detector) sees 0.2s of silence, *then* a local neural model called Smart Turn v3
  judges whether the sentence sounds semantically finished, *then* it waits for the
  transcriber to finalize the text. All of that is inside its stopwatch.
- **Gradbot** fires its equivalent from an event called `Flushing` — which, we
  discovered by reading the Rust, is only emitted **after transcribed text has
  already arrived.** Speech recognition has already run. Its cost sits *before* the
  stopwatch starts.

So Gradbot's number excludes speech recognition entirely and Pipecat's includes it,
along with two extra deliberation stages. These are not two measurements of one
thing. They are two different things wearing the same label.

(The 12-second 90th percentile on the Pipecat side is a *pairing artifact*, not
evidence of a slow system: we pair each "user stopped" with the next "agent started",
and when a caller pauses, thinks, and doesn't get a reply because they never finished
a turn, that gap can be enormous. It's a measurement bug in the query, not a user
experience. It is exactly the kind of thing that makes a bar chart lie.)

### Even one framework disagrees with itself

Gradbot prints its own language-model latency to the log:

```
LLM time-to-first-token ttft_ms=87
```

That number is honest but narrow. Reading the Rust, the stopwatch starts *after* the
HTTP request to the model has already been opened. The connection setup — which in
our recorded session ranged from **430ms to 1,483ms** — is not in it.

Our tracing code, by contrast, anchors the same measurement to the moment the text
was handed to the language model, and records **517ms** for the very same turn where
the log says 87ms.

Same event. Two truthful numbers. A 6× difference. Neither is wrong; they answer
different questions. If you quote one without saying which, you have misled someone.

### The near-tie that also means nothing

Language-model TTFB comes out almost identical: **0.607s median on Gradbot, 0.622s
on Pipecat's Anthropic path.** Fifteen milliseconds apart! Surely *that* is a fair
comparison?

No. Different models, different providers, different prompts — and the Pipecat side
carries an average prompt of **4,384 tokens** while running a memory feature the
Gradbot personas don't have. The two systems agree on a number while doing visibly
different work. Coincidence is not comparability.

### The holes that can't be filled

Some gaps aren't measurement disagreements — they're absences.

- **Token counts.** Gradbot's Rust core makes the language-model call itself and
  parses the response stream internally. It never re-emits usage. So our cost columns
  read `0` on every Gradbot session, forever, against 4,384 prompt / 297 completion
  tokens on average for Pipecat. We cannot compare cost. Not "we haven't yet" — we
  *cannot*, without changing Gradbot.
- **Speech recognition timing.** Same reason: it's inside the core. Pipecat records
  transcription TTFB for every transcriber it has run (0.56s to 0.64s on average,
  depending on vendor). Gradbot records **no STT metric at all**.

You cannot difference against a number that does not exist.

### And the samples aren't comparable either

To be completely straight about it: **138 Pipecat sessions across seven weeks
(May 25 – Jul 13) against 19 Gradbot sessions across two days.** The Pipecat corpus
spans months of prompt changes, four language models and three synthesizers. The
Gradbot corpus is two days of testing a brand-new port — including, as it happens,
the days when it had a turn-taking bug. Any statistic drawn across those two
populations is comparing eras as much as frameworks.

### The ending: comparability lost, on purpose

Here is what makes this story worth telling.

We *knew* the measurement-alignment problem, and we engineered against it. Pipecat's
silence threshold and Gradbot's turn-flush window both decide "when did the user stop
talking", so they must be equal or every cross-framework number is off by the
difference. We measured the gap once at 0.3s. There is a test in the Pipecat repo
holding the line:

```python
GRADBOT_FLUSH_DURATION_S = 0.2  # personas/*.json in ../../gradbot

def test_vad_stop_secs_matches_the_gradbot_flush_gate():
    assert Settings().vad_stop_secs == GRADBOT_FLUSH_DURATION_S, (
        "pipecat's VAD stop_secs and gradbot's flush_duration_s have drifted "
        "apart; cross-framework latency comparisons are now wrong by the gap"
    )
```

Then we discovered that on the Gradbot side, 0.2s was **cutting callers off
mid-sentence** (Part 5 tells that story). Fixing it meant raising the value to 0.6s.
Which we did — knowingly abandoning the alignment, and with it the ability to compare
the two stacks' latency at all.

And the test? It still passes. It hardcodes `0.2` as a *constant with a comment*
rather than reading the other repository, so it cannot see that the value it is
guarding against has moved to 0.6. The guard rail survives; the thing it guarded is
gone.

That's the real lesson, and it generalizes far beyond these two frameworks: **an
agent that can hear you is worth more than a benchmark that compares cleanly.** When
those two goals collided, the benchmark lost, and it deserved to.

---

## Part 5: What actually bit us

The port took two days. Most of that was not writing code.

**The agent spoke and the browser threw the sound away.** Gradbot's bundled browser
audio player decides "is this audio?" by checking `data instanceof Blob`. We had set
the WebSocket to `binaryType = "arraybuffer"` — a change that looks like a harmless
optimization. Every audio frame then failed the Blob check, fell through to the
"this must be JSON" branch, and was silently discarded. The agent was talking
perfectly; the browser was dropping every packet on the floor. This cost an
afternoon.

**The agent talked to itself.** Gradbot has a `silence_timeout_s` that defaults to 5
seconds. What happens after five seconds of silence is not documented in an obvious
place, and it is startling: the Rust core **injects the literal string `"..."` into
the conversation as a user turn** and runs a full language-model → speech cycle on
it. The model, handed a contentless user turn, does the only thing it can — it fills
the silence, re-asking its last question or elaborating on its last point. That's
what "it talks to itself" means: it is answering a prompt nobody spoke.

This is a perfectly sensible default for a chatty demo agent. It was badly wrong for
ours — one of our two personas is a discernment guide, where **silence is the point**;
you are supposed to sit and think. Both personas now pin it to `0.0`, which disables
the branch entirely.

**Every latency we recorded was `0.000s`, and everything looked fine.** Gradbot's
messages carry a field called `time_s`. It is always `0.0` — the type declares it,
the Rust sends it, the Python binding never fills it in. There are also `start_s` and
`stop_s` fields which *are* populated, but they're a position within the *synthesized
audio*, not a wall clock — two turns an hour apart both start at 0.0. Our first
tracing implementation trusted them, and every event in a turn collapsed onto one
timestamp.

What makes this the most dangerous bug in the report is that **the transcripts stayed
perfect.** Everything a human would spot-check looked right. Only the numbers were
dead, and numbers don't look wrong; they just look like numbers. Timestamps now come
from the local clock at the moment each message arrives, and there are tests that
fail if anyone reaches for those fields again.

**We had to fork the framework to see inside it.** This is the deepest structural
difference of the whole exercise. Gradbot's session handler reads messages from the
Rust core and forwards them to the browser — and offers **no hook to observe them**.
Worse, the conversion to the wire format *drops the timing field on the way*. Every
transcript and every timing this application records exists only inside that loop.
There is no middleware, no event bus, no callback.

So we copied the file and added one line — a callback invoked on each message before
conversion — and pinned Gradbot to an exact version, because our copy will drift from
theirs the moment they change it. **In Pipecat, observability is a first-class
concept: you insert an observer, or a processor, anywhere in the pipeline.** In
Gradbot, we had to fork to watch.

**And the one that started this whole investigation: the agent went hard of hearing.**
Callers reported it was like talking to someone hard of hearing — it caught the start
of your sentence and missed the end. It was *not* bad transcription; the words coming
back from the transcriber were correct. It was turn truncation:

```
on_text  text="I'm going"
PushToLlm { user_text: "I'm going" }     <- turn committed on a fragment
on_text  text="to"                        <- arrives late...
on_text  text="be"                        <- ...and lands in the NEXT turn
PushToLlm { user_text: "to be" }          <- answered as its own utterance
```

You said "I'm going to be…". The agent heard "I'm going", answered it, then heard
"to be" and answered *that*.

The cause was the setting from Part 4. Gradium's transcriber emits text with real
lookahead lag — it buffers about a second of audio before committing to words, which
is *why* it's accurate. Our turn-flush window was 0.2s. We were closing the turn
while words were still in flight. And we had chosen 0.2s **specifically to match
Pipecat's setting so the latency numbers would be comparable** — optimizing the
benchmark at the expense of the product, without realizing it.

---

## Part 6: What each framework is good at

Neither of these is better. They are shaped for different jobs.

**Pipecat's strengths** come from being made of parts. Every stage is swappable, and
we have the traces to prove it isn't just theoretical — four language-model
providers, three synthesizers, two transcribers, all in production use. It is
observable by construction: you can watch, or modify, any seam. It reports token
usage, so you can actually cost a conversation. It can speak a **canned opening
line** without invoking the language model at all, which drops the cold-start
greeting to about half a second. Its turn-taking is genuinely sophisticated — a
neural model that judges whether your sentence sounded *finished*, plus a rule that
you must say at least two words to interrupt the agent (a single cough shouldn't
cancel its turn). And when a vendor doesn't expose what you need, it's Python: you
subclass it.

**Pipecat's costs** are the mirror image. The sentence-buffering that makes speech
sound natural costs 200–300ms before the agent starts talking. There are a great many
moving parts, and configuration can be *emergent* — Smart Turn v3, a whole neural
turn-detection model, is running in our agent and is **nowhere mentioned in our
pipeline code**; it arrives as a default when you leave one field unset. That is a
lot of behavior to inherit silently. We also needed defensive subclasses to survive
vendor hiccups, which is power, but it's power you had to use because you needed it.

**Gradbot's strengths** come from being one engine. The whole loop lives in Rust, and
the tight coupling buys real things: it opens the synthesizer connection before the
first token exists, so that setup costs nothing; it streams word by word rather than
sentence by sentence; it paces audio against the audio clock with a 300ms jitter
buffer. There are far fewer knobs, which means far fewer ways to be wrong. It ships
its own browser audio. For a team that wants a voice agent rather than a voice
framework, this is a real proposition.

**Gradbot's costs** are the flip side of that integration, and they are not small.
The engine is a closed pipe: **we forked it to observe a session**, and we're pinned
to one version as a result. Its timing fields cannot be trusted, and we only know
that because we measured them. It reports no token usage, ever. It has no API to
speak a fixed line, so the greeting must be *generated* by the language model — which
costs 1.2–1.9 seconds of cold start on every call, and means the agent can, and
occasionally does, drift from the greeting you wrote. It speaks exactly one
language-model wire protocol and works with exactly one speech vendor. And it
publishes macOS wheels for ARM only, so on an Intel Mac, it's Docker or nothing.

---

## The takeaway

If you take one thing from this: **be extremely suspicious of latency comparisons
between voice frameworks, including your own.**

We did this comparison with every advantage. The same product, the same personas,
the same users, one shared database, a deliberately shared metrics vocabulary, and a
test pinning the turn-taking settings together. We still ended up with two numbers
called `ttfb`, for one vendor, that differ by 70% and mean different things — and a
headline latency figure where a large share of the gap is the *stopwatch*, not the
software.

The number you can trust is the one where you know precisely what starts the clock
and what stops it, on both sides. Everything else is a vibe with error bars.

And when the benchmark and the product disagree — when the setting that keeps your
numbers comparable is the same setting that makes your agent mishear people — ship
the agent that can hear. We did, and we lost the comparison, and that was the right
trade.

---

*All figures in this report are drawn from production traces of both applications
(138 Pipecat sessions, 19 Gradbot sessions) sharing one Postgres database, plus a
recorded debug session with per-turn timings. Where a number is an artifact of
measurement rather than a property of the software, we've said so — that was rather
the point.*
