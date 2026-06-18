"""Admin dashboard routes: aggregate stats, session list/detail, latency analysis.

SQL and row→JSON shaping live here for now; Tasks 13/14 extract them into a
dashboard repository and persona-projection helper.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import CurrentUser, require_admin
from deps import get_pool
from latency import generate_and_store
from latency_collector import _quantile
from latency_repository import load_latency_analysis
from personas import Persona, PersonaError

router = APIRouter()


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _pair_response_latencies(events: list[dict]) -> list[float]:
    """Pair each user_stopped_speaking with the next bot_started_speaking.

    Events are assumed time-ordered. If the user speaks twice without the
    bot answering, the older pending stop is overwritten (we always pair
    against the most recent unanswered user stop).
    """
    out: list[float] = []
    pending: int | None = None
    for ev in events:
        kind = ev["kind"]
        ts = ev["timestamp_ns"]
        if kind == "user_stopped_speaking":
            pending = ts
        elif kind == "bot_started_speaking" and pending is not None:
            out.append((ts - pending) / 1e9)
            pending = None
    return out


@router.get("/api/aggregate")
async def api_aggregate(
    days: int = Query(7, ge=1, le=365),
    pool=Depends(get_pool),
    _admin: CurrentUser = Depends(require_admin),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
              count(*)                                                       AS total_sessions,
              count(*) FILTER (WHERE ended_at IS NOT NULL)                   AS finished_sessions,
              coalesce(sum(extract(epoch FROM (ended_at - started_at))), 0)  AS total_duration_s,
              coalesce(sum(total_prompt_tokens), 0)                          AS prompt_tokens,
              coalesce(sum(total_completion_tokens), 0)                      AS completion_tokens,
              coalesce(sum(total_cache_read_tokens), 0)                      AS cache_read_tokens,
              coalesce(sum(total_cache_creation_tokens), 0)                  AS cache_creation_tokens,
              coalesce(sum(total_tts_chars), 0)                              AS tts_chars
            FROM sessions
            WHERE started_at >= $1
            """,
            since,
        )
        ttfb = await conn.fetch(
            """
            SELECT processor, avg(value_num) AS avg_ttfb, count(*) AS n
            FROM metrics m
            JOIN sessions s ON s.id = m.session_id
            WHERE m.kind = 'ttfb' AND s.started_at >= $1
            GROUP BY processor
            ORDER BY processor
            """,
            since,
        )
    return {
        "since": _iso(since),
        "days": days,
        "sessions": dict(row),
        "ttfb": [
            {"processor": r["processor"], "avg_ttfb": float(r["avg_ttfb"]), "n": r["n"]}
            for r in ttfb
        ],
    }


@router.get("/api/sessions")
async def api_sessions(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    persona: str | None = Query(None),
    environment: str | None = Query(None),
    pool=Depends(get_pool),
    _admin: CurrentUser = Depends(require_admin),
):
    # Optional filters by persona/agent name and environment. Built as a shared
    # WHERE clause so the page query and its total count stay in sync.
    conditions: list[str] = []
    filter_args: list = []
    if persona:
        filter_args.append(persona)
        conditions.append(f"s.persona_name = ${len(filter_args)}")
    if environment:
        filter_args.append(environment)
        conditions.append(f"s.environment = ${len(filter_args)}")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT s.id, s.persona_name, s.environment, s.lang, s.started_at, s.ended_at,
                   extract(epoch FROM (s.ended_at - s.started_at)) AS duration_s,
                   s.total_prompt_tokens, s.total_completion_tokens,
                   s.total_cache_read_tokens, s.total_cache_creation_tokens,
                   s.total_tts_chars,
                   (SELECT count(*) FROM messages WHERE session_id = s.id) AS msg_count
            FROM sessions s
            {where}
            ORDER BY s.started_at DESC
            LIMIT ${len(filter_args) + 1} OFFSET ${len(filter_args) + 2}
            """,
            *filter_args, limit, offset,
        )
        total = await conn.fetchval(
            f"SELECT count(*) FROM sessions s {where}", *filter_args
        )
        # Distinct persona names across ALL sessions, for the filter dropdown.
        persona_rows = await conn.fetch(
            """
            SELECT DISTINCT persona_name FROM sessions
            WHERE persona_name IS NOT NULL
            ORDER BY persona_name
            """
        )
        # Distinct environments across ALL sessions, for the filter dropdown.
        env_rows = await conn.fetch(
            """
            SELECT DISTINCT environment FROM sessions
            WHERE environment IS NOT NULL
            ORDER BY environment
            """
        )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "personas": [r["persona_name"] for r in persona_rows],
        "environments": [r["environment"] for r in env_rows],
        "sessions": [
            {
                "id": str(r["id"]),
                "persona_name": r["persona_name"],
                "environment": r["environment"],
                "lang": r["lang"],
                "started_at": _iso(r["started_at"]),
                "ended_at": _iso(r["ended_at"]),
                "duration_s": float(r["duration_s"]) if r["duration_s"] is not None else None,
                "prompt_tokens": r["total_prompt_tokens"],
                "completion_tokens": r["total_completion_tokens"],
                "cache_read_tokens": r["total_cache_read_tokens"],
                "cache_creation_tokens": r["total_cache_creation_tokens"],
                "tts_chars": r["total_tts_chars"],
                "msg_count": r["msg_count"],
            }
            for r in rows
        ],
    }


@router.get("/api/sessions/{session_id}")
async def api_session_detail(
    session_id: str,
    pool=Depends(get_pool),
    _admin: CurrentUser = Depends(require_admin),
):
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="bad_uuid")
    async with pool.acquire() as conn:
        s = await conn.fetchrow(
            """
            SELECT id, persona_name, persona_json, lang, started_at, ended_at,
                   extract(epoch FROM (ended_at - started_at)) AS duration_s,
                   total_prompt_tokens, total_completion_tokens,
                   total_cache_read_tokens, total_cache_creation_tokens,
                   total_tts_chars
            FROM sessions WHERE id = $1
            """,
            sid,
        )
        if s is None:
            raise HTTPException(status_code=404, detail="session_not_found")
        messages = await conn.fetch(
            "SELECT role, text, language, recorded_at FROM messages "
            "WHERE session_id = $1 ORDER BY id",
            sid,
        )
        metrics = await conn.fetch(
            """
            SELECT processor, kind,
                   count(*)              AS n,
                   avg(value_num)        AS avg_value,
                   sum(value_num)        AS sum_value
            FROM metrics
            WHERE session_id = $1
            GROUP BY processor, kind
            ORDER BY processor, kind
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

    # Stored latency analysis (if generated before), loaded with the page.
    latency_analysis = await load_latency_analysis(pool, sid)

    # Per-turn user→bot response latency.
    latencies = _pair_response_latencies([dict(r) for r in turn_events])
    sorted_l = sorted(latencies)
    response = {
        "count": len(latencies),
        "mean": (sum(latencies) / len(latencies)) if latencies else None,
        "median": _quantile(sorted_l, 0.5),
        "p90": _quantile(sorted_l, 0.9),
        "max": max(latencies) if latencies else None,
        "per_turn": [
            {"turn": i + 1, "latency_s": v} for i, v in enumerate(latencies)
        ],
    }
    persona = s["persona_json"]
    if isinstance(persona, str):
        persona = json.loads(persona)
    persona_view = None
    if isinstance(persona, dict):
        try:
            p = Persona.from_dict(persona)
            persona_view = {
                "name": p.name,
                "lang": p.lang,
                "llm_model": p.llm_model,
                "llm": p.llm_description,
                "tts_provider": p.tts_provider,
                "tts_voice_id": p.voice_id,
                "voice_name": p.voice_name,
                "voice_description": p.voice_description,
                "description": p.description,
            }
        except PersonaError:
            # Legacy/flat snapshot from before the nested schema — return as-is.
            persona_view = persona
    return {
        "id": str(s["id"]),
        "persona_name": s["persona_name"],
        "persona": persona_view,
        "lang": s["lang"],
        "started_at": _iso(s["started_at"]),
        "ended_at": _iso(s["ended_at"]),
        "duration_s": float(s["duration_s"]) if s["duration_s"] is not None else None,
        "prompt_tokens": s["total_prompt_tokens"],
        "completion_tokens": s["total_completion_tokens"],
        "cache_read_tokens": s["total_cache_read_tokens"],
        "cache_creation_tokens": s["total_cache_creation_tokens"],
        "tts_chars": s["total_tts_chars"],
        "messages": [
            {
                "role": m["role"],
                "text": m["text"],
                "language": m["language"],
                "recorded_at": _iso(m["recorded_at"]),
            }
            for m in messages
        ],
        "metrics": [
            {
                "processor": m["processor"],
                "kind": m["kind"],
                "n": m["n"],
                "avg": float(m["avg_value"]) if m["avg_value"] is not None else None,
                "sum": float(m["sum_value"]) if m["sum_value"] is not None else None,
            }
            for m in metrics
        ],
        "response_latency": response,
        "latency_analysis": latency_analysis,
    }


@router.post("/api/sessions/{session_id}/latency-analysis")
async def api_session_latency_analysis(
    session_id: str,
    pool=Depends(get_pool),
    _admin: CurrentUser = Depends(require_admin),
):
    """Run the deterministic collector + one LLM synthesis call, store, return it.

    Single row per session — regenerating overwrites. Synchronous (one LLM call).
    """
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="bad_uuid")
    try:
        return await generate_and_store(pool, sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="session_not_found")
