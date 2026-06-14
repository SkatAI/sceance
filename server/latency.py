"""Per-session latency analysis.

Two layers, mirroring `docs/session_latency_analysis.md`:

1. `collect_latency_bundle` — deterministic. Runs the runbook's SQL against the
   pool and returns a JSON-serializable bundle: per-stage TTFB stats, per-turn
   perceived latency (with intro/stall flags + rule-based cause tags), and the
   LLM-usage timeline used to tell context-bloat from API jitter. No model call;
   an LLM must never do arithmetic on these rows.
2. `synthesize_latency_report` — one Claude call (Sonnet 4.6, same pattern as
   `memory.py`). Turns the bundle into a readable report and, crucially, flags
   anything that does not fall into the known cause buckets.

`generate_and_store` chains the two and upserts the single per-session row.

This iteration is SQL-only — log cross-check (runbook step 7) is deferred, so
the stall tail is flagged heuristically (threshold, no log confirmation).
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid

import anthropic
import asyncpg
from loguru import logger

SYNTH_MODEL = "claude-sonnet-4-6"

# Heuristics (SQL-only; see module docstring).
STALL_S = 30.0       # a "turn" this long is the stall watchdog, never a real turn
STALL_TAIL_S = 6.0   # 6s+ on the LAST turn = stall watchdog firing at hangup
OUTLIER_MULT = 2.0   # a real turn >= this * median perceived latency is an outlier
BLOAT_CORR = 0.5     # LLM ttfb vs prompt-token correlation above this => context bloat


# ─── Deterministic collector ────────────────────────────────────────

def _quantile(sorted_vals: list[float], q: float) -> float | None:
    """Linear-interp quantile. q in [0, 1]. Returns None for empty input."""
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation, or None if undefined (too few points / no variance)."""
    n = min(len(xs), len(ys))
    if n < 3:
        return None
    xs, ys = xs[:n], ys[:n]
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / (sxx ** 0.5 * syy ** 0.5)


def _build_turns(turn_events: list[dict]) -> list[dict]:
    """One entry per real conversational turn, ordered.

    perceived_s = time from the most recent unanswered user_stopped_speaking to
    the bot's FIRST word after it. Only the very first bot word(s), before any
    user has stopped speaking, are the intro (cold start). Later bot-starts with
    no pending user-stop are continuation utterances or duplicate events (the
    events table double-records) and are skipped, not counted. The stall
    watchdog firing shows up as a real turn with a huge gap.
    """
    turns: list[dict] = []
    pending: int | None = None
    seen_user_stop = False
    intro_emitted = False
    n = 0
    for ev in turn_events:
        if ev["kind"] == "user_stopped_speaking":
            pending = ev["timestamp_ns"]
            seen_user_stop = True
        elif ev["kind"] == "bot_started_speaking":
            if pending is not None:
                n += 1
                perceived_s = (ev["timestamp_ns"] - pending) / 1e9
                turns.append({
                    "turn": n,
                    "perceived_s": round(perceived_s, 3),
                    "is_intro": False,
                    "is_stall": False,
                })
                pending = None
            elif not seen_user_stop and not intro_emitted:
                n += 1
                intro_emitted = True
                turns.append({
                    "turn": n, "perceived_s": None, "is_intro": True, "is_stall": False,
                })
            # else: duplicate / continuation bot-start — ignore.

    # Stall flagging: a real turn over STALL_S, or over STALL_TAIL_S on the last
    # turn (near-hangup watchdog). SQL-only, so heuristic (no log confirmation).
    last_real = max(
        (i for i, t in enumerate(turns) if t["perceived_s"] is not None),
        default=None,
    )
    for i, t in enumerate(turns):
        ps = t["perceived_s"]
        if ps is not None and (ps >= STALL_S or (ps >= STALL_TAIL_S and i == last_real)):
            t["is_stall"] = True
    return turns


async def collect_latency_bundle(pool: asyncpg.Pool, sid: uuid.UUID) -> dict:
    """Run the runbook's SQL (steps 1-6) and return the deterministic bundle."""
    async with pool.acquire() as conn:
        s = await conn.fetchrow(
            """
            SELECT persona_name, environment,
                   extract(epoch FROM (ended_at - started_at)) AS duration_s,
                   total_prompt_tokens, total_completion_tokens,
                   total_cache_read_tokens, total_cache_creation_tokens,
                   total_tts_chars
            FROM sessions WHERE id = $1
            """,
            sid,
        )
        if s is None:
            raise KeyError("session_not_found")
        stage = await conn.fetch(
            """
            SELECT processor, count(*) AS n,
                   min(value_num) AS min_v, avg(value_num) AS avg_v, max(value_num) AS max_v
            FROM metrics WHERE session_id = $1 AND kind = 'ttfb'
            GROUP BY processor ORDER BY avg(value_num) DESC
            """,
            sid,
        )
        ttfb_rows = await conn.fetch(
            """
            SELECT ts, processor, value_num FROM metrics
            WHERE session_id = $1 AND kind = 'ttfb' ORDER BY ts
            """,
            sid,
        )
        turn_events = await conn.fetch(
            """
            SELECT kind, timestamp_ns FROM events
            WHERE session_id = $1
              AND kind IN ('user_stopped_speaking', 'bot_started_speaking')
            ORDER BY timestamp_ns
            """,
            sid,
        )
        usage_rows = await conn.fetch(
            """
            SELECT ts, processor, prompt_tokens, completion_tokens FROM metrics
            WHERE session_id = $1 AND kind = 'llm_usage' ORDER BY ts
            """,
            sid,
        )

    session = {
        "persona_name": s["persona_name"],
        "environment": s["environment"],
        "duration_s": float(s["duration_s"]) if s["duration_s"] is not None else None,
        "prompt_tokens": s["total_prompt_tokens"],
        "completion_tokens": s["total_completion_tokens"],
        "cache_read_tokens": s["total_cache_read_tokens"],
        "cache_creation_tokens": s["total_cache_creation_tokens"],
        "tts_chars": s["total_tts_chars"],
    }
    stage_ttfb = [
        {
            "processor": r["processor"],
            "n": r["n"],
            "min": round(float(r["min_v"]), 3) if r["min_v"] is not None else None,
            "avg": round(float(r["avg_v"]), 3) if r["avg_v"] is not None else None,
            "max": round(float(r["max_v"]), 3) if r["max_v"] is not None else None,
        }
        for r in stage
    ]
    ttfb_timeline = [
        {"t": r["ts"].strftime("%H:%M:%S"), "processor": r["processor"],
         "ttfb": round(float(r["value_num"]), 3) if r["value_num"] is not None else None}
        for r in ttfb_rows
    ]
    llm_usage_timeline = [
        {"t": r["ts"].strftime("%H:%M:%S"),
         "prompt_tokens": r["prompt_tokens"], "completion_tokens": r["completion_tokens"]}
        for r in usage_rows
    ]

    turns = _build_turns([dict(r) for r in turn_events])

    # Perceived-latency stats over real turns only (exclude intro + stall).
    real = [t["perceived_s"] for t in turns
            if not t["is_intro"] and not t["is_stall"] and t["perceived_s"] is not None]
    sorted_real = sorted(real)
    median = _quantile(sorted_real, 0.5)
    perceived_stats = {
        "count": len(real),
        "min": round(min(real), 3) if real else None,
        "avg": round(sum(real) / len(real), 3) if real else None,
        "median": round(median, 3) if median is not None else None,
        "p90": round(_quantile(sorted_real, 0.9), 3) if real else None,
        "max": round(max(real), 3) if real else None,
    }

    # Context-bloat vs API-jitter: do LLM TTFB spikes track prompt-token growth?
    # The LLM stage is whichever processor emits llm_usage rows.
    llm_proc = usage_rows[0]["processor"] if usage_rows else None
    llm_ttfb = [float(r["value_num"]) for r in ttfb_rows
                if r["processor"] == llm_proc and r["value_num"] is not None]
    prompt_series = [r["prompt_tokens"] for r in usage_rows if r["prompt_tokens"] is not None]
    corr = _pearson(llm_ttfb, prompt_series)
    spike_cause = (
        "context_bloat" if corr is not None and corr >= BLOAT_CORR else "llm_jitter"
    )

    # Rule-based cause tags per turn.
    for t in turns:
        if t["is_intro"]:
            t["cause"] = "intro_cold_start"
        elif t["is_stall"]:
            t["cause"] = "stall_watchdog"
        elif median and t["perceived_s"] is not None and t["perceived_s"] >= OUTLIER_MULT * median:
            t["cause"] = spike_cause
        else:
            t["cause"] = None

    return {
        "session": session,
        "stage_ttfb": stage_ttfb,
        "ttfb_timeline": ttfb_timeline,
        "llm_usage_timeline": llm_usage_timeline,
        "turns": turns,
        "perceived_stats": perceived_stats,
        "correlation": {
            "llm_ttfb_vs_prompt_tokens": round(corr, 3) if corr is not None else None,
            "verdict": spike_cause,
            "n": min(len(llm_ttfb), len(prompt_series)),
        },
        "thresholds": {
            "stall_s": STALL_S, "stall_tail_s": STALL_TAIL_S,
            "outlier_mult": OUTLIER_MULT, "bloat_corr": BLOAT_CORR,
        },
    }


# ─── LLM synthesis (one call) ───────────────────────────────────────

_SYNTH_SYSTEM = """You are a latency analyst for a real-time voice-agent service
(STT -> LLM -> TTS cascade). You receive a pre-computed JSON bundle of one
session's latency — all numbers are already calculated; DO NOT recompute or
second-guess them. Your job is to write a short operator-facing report and, most
importantly, flag anything you cannot explain.

Definitions:
- "Perceived latency" = wall-clock from the user finishing their turn to the
  bot's first spoken word. This is the headline number. Report median + max over
  real turns (intro and stall are already excluded from perceived_stats).
- Per-stage TTFB = time-to-first-token for each stage (STT/LLM/TTS). Diagnostic:
  tells you which stage is slow. The LLM is normally dominant and most variable.

Known cause buckets (each outlier turn in the bundle is pre-tagged with one):
- intro_cold_start: the first bot word, generated through a cold LLM connection.
  Expected ~4s; off the critical path of real turns.
- stall_watchdog: a huge gap (>= stall thresholds), usually the STT stall
  watchdog firing at hangup. NOT a real conversational turn — exclude it.
- llm_jitter: a slow real turn whose LLM TTFB spike does NOT track prompt-token
  growth (correlation low) => OpenAI/provider-side jitter, not your context.
- context_bloat: LLM TTFB tracks prompt-token growth (correlation high) =>
  trimming history would help.

Write STRICT JSON with exactly these keys, no prose outside the object:
- "headline": one sentence — real turns, perceived median and max.
- "main_cause": one or two sentences naming the dominant latency driver, citing
  the per-stage averages and whether spikes are jitter or context bloat.
- "outliers": array of {"turn": int, "perceived_s": number, "cause": string,
  "note": string}. One per intro/stall/outlier turn, each with a plain-English
  reason. Use the pre-assigned cause tag.
- "unexplained": array of strings. List anything that does NOT fit a known
  bucket or that the data cannot account for — a stage slow for no clear reason,
  a tag that contradicts the numbers, missing/zero data where you'd expect some,
  a correlation that's null when it matters. EMPTY array if everything is
  explained. Be honest; this is the signal for a human to look closer."""


async def synthesize_latency_report(bundle: dict, model: str = SYNTH_MODEL) -> dict:
    """One Claude call: bundle -> structured report. Raises on hard failure."""
    prompt = (
        "Here is the latency bundle for one session. Produce the JSON now.\n\n"
        + json.dumps(bundle, indent=2)
    )
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    raw = await _call_anthropic(client, model, prompt)
    report = _extract_json(raw)
    # Normalise the keys we depend on downstream.
    report.setdefault("headline", "")
    report.setdefault("main_cause", "")
    report.setdefault("outliers", [])
    report.setdefault("unexplained", [])
    if not isinstance(report["unexplained"], list):
        report["unexplained"] = [str(report["unexplained"])]
    return report


async def _call_anthropic(client: anthropic.Anthropic, model: str, prompt: str) -> str:
    """Run a blocking Anthropic call off the event loop."""
    def _run() -> str:
        msg = client.messages.create(
            model=model,
            max_tokens=1500,
            system=_SYNTH_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(getattr(b, "text", "") for b in msg.content)

    return await asyncio.to_thread(_run)


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of the model's response (fences/prose tolerant)."""
    s = text.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        start = s.find("{")
        end = s.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(s[start : end + 1])


# ─── Orchestration + storage ────────────────────────────────────────

async def generate_and_store(pool: asyncpg.Pool, sid: uuid.UUID) -> dict:
    """Collect -> synthesize -> upsert the single per-session row. Returns the analysis."""
    bundle = await collect_latency_bundle(pool, sid)
    report = await synthesize_latency_report(bundle)
    has_unexplained = bool(report.get("unexplained"))

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO session_latency_analysis
                (session_id, bundle, report, has_unexplained, model, generated_at)
            VALUES ($1, $2::jsonb, $3::jsonb, $4, $5, now())
            ON CONFLICT (session_id) DO UPDATE
              SET bundle = EXCLUDED.bundle,
                  report = EXCLUDED.report,
                  has_unexplained = EXCLUDED.has_unexplained,
                  model = EXCLUDED.model,
                  generated_at = now()
            RETURNING generated_at
            """,
            sid, json.dumps(bundle), json.dumps(report), has_unexplained, SYNTH_MODEL,
        )
    logger.info(
        f"latency analysis stored for session {sid} "
        f"(unexplained={has_unexplained}, turns={len(bundle['turns'])})"
    )
    return {
        "bundle": bundle,
        "report": report,
        "has_unexplained": has_unexplained,
        "model": SYNTH_MODEL,
        "generated_at": row["generated_at"].isoformat(),
    }
