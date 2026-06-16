"""FastAPI server for the Inigo voice agent web deployment.

Serves the landing page and exposes POST /start-session, which creates
a Daily room, mints a user token + a bot token, spawns the bot into the
room as a background asyncio task, and returns {room_url, token} to the
browser. The browser joins the same room via daily-js.

Run locally:
    uv run uvicorn server:app --host 0.0.0.0 --port 8001 --reload
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger

import daily_client
from auth import CurrentUser, get_current_user, require_admin
from bot import run_daily_bot
from latency import _quantile, generate_and_store
from personas import Persona, PersonaError
from storage import close_pool, create_pool
from supabase_admin import (
    admin_configured,
    create_user,
    generate_magiclink_token,
    user_exists,
)

load_dotenv(override=True)

DAILY_API_KEY = os.getenv("DAILY_API_KEY", "")
MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", "5"))
# When true, an unrecognized email is auto-created on sign-in (local/dev). When
# false (deployed), unknown emails are rejected as invite-only.
OPEN_SIGNUP = os.getenv("OPEN_SIGNUP", "").strip().lower() in ("1", "true", "yes")

STATIC_DIR = Path(__file__).parent / "static"
PERSONAS_DIR = Path(__file__).parent.parent / "personas"

_active_sessions: set[asyncio.Task] = set()


def _cleanup_task(task: asyncio.Task) -> None:
    _active_sessions.discard(task)
    if task.cancelled():
        return
    try:
        task.result()
    except Exception:
        logger.exception("Bot task failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not DAILY_API_KEY:
        logger.warning("DAILY_API_KEY is not set — /start-session will fail")
    logger.info(f"Static dir: {STATIC_DIR}, MAX_SESSIONS={MAX_SESSIONS}")
    app.state.db_pool = await create_pool()
    try:
        yield
    finally:
        for t in list(_active_sessions):
            t.cancel()
        await close_pool(app.state.db_pool)


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8001",
        "http://127.0.0.1:8001",
        "https://voice.alexisperrier.com",
        "https://alexisperrier.com",
        "https://www.alexisperrier.com",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*", "Authorization"],
)


@app.get("/api/config")
async def api_config():
    """Public Supabase config consumed by the browser to initialize supabase-js."""
    return {
        "supabase_url": os.getenv("SUPABASE_URL", ""),
        "supabase_anon_key": os.getenv("SUPABASE_KEY", ""),
        "open_signup": OPEN_SIGNUP,
    }


class LoginBody(BaseModel):
    email: str


@app.post("/api/auth/login")
async def api_auth_login(body: LoginBody):
    """Passwordless sign-in by email — no magic-link email is sent.

    Returns a one-time `token_hash` the browser redeems with verifyOtp. Unknown
    emails are auto-created when OPEN_SIGNUP is on, else rejected as invite-only.
    """
    email = (body.email or "").strip().lower()
    if "@" not in email or len(email) < 3:
        raise HTTPException(status_code=400, detail="invalid_email")
    if not admin_configured():
        raise HTTPException(status_code=500, detail="auth_admin_not_configured")

    pool = app.state.db_pool
    exists = await user_exists(pool, email)
    async with httpx.AsyncClient(timeout=15.0) as client:
        if not exists:
            if not OPEN_SIGNUP:
                raise HTTPException(status_code=403, detail="invite_only")
            await create_user(client, email)
        token_hash = await generate_magiclink_token(client, email)

    return {"token_hash": token_hash, "type": "magiclink"}


@app.get("/api/me")
async def api_me(user: CurrentUser = Depends(get_current_user)):
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "is_admin": user.is_admin,
    }


@app.get("/health")
async def health():
    return {"ok": True, "active_sessions": len(_active_sessions)}


@app.get("/dashboard")
async def dashboard():
    return RedirectResponse(url="/dashboard.html")


@app.get("/sessions/{session_id}")
async def session_page(session_id: str):
    # Operator detail view for a single séance. The page itself is admin-gated
    # client-side (same as the dashboard); the JWT-protected data is fetched
    # from /api/sessions/{id}.
    return FileResponse(STATIC_DIR / "session.html")


@app.get("/agents")
async def list_agents():
    agents = []
    for path in sorted(PERSONAS_DIR.glob("*.json")):
        try:
            with path.open() as f:
                data = json.load(f)
            persona = Persona.from_dict(data, id=path.stem)
        except (OSError, json.JSONDecodeError, PersonaError) as e:
            logger.warning(f"Skipping persona {path.name}: {e}")
            continue
        if not persona.active:
            continue
        agents.append(persona.public())
    return {"agents": agents}


class StartSessionBody(BaseModel):
    agent: str


@app.post("/start-session")
async def start_session(
    body: StartSessionBody,
    user: CurrentUser = Depends(get_current_user),
):
    agent_name = (body.agent or "").strip()
    if not agent_name:
        raise HTTPException(status_code=400, detail="agent_required")
    persona_path = PERSONAS_DIR / f"{agent_name}.json"
    if not persona_path.exists():
        raise HTTPException(status_code=404, detail="agent_not_found")
    if len(_active_sessions) >= MAX_SESSIONS:
        raise HTTPException(status_code=429, detail="agent_busy")
    if not DAILY_API_KEY:
        raise HTTPException(status_code=500, detail="daily_api_key_missing")

    async with daily_client.make_client(DAILY_API_KEY) as client:
        try:
            room = await daily_client.create_room(client)
            room_name = room["name"]
            room_url = room["url"]
            user_token = await daily_client.create_meeting_token(client, room_name, is_owner=False)
            bot_token = await daily_client.create_meeting_token(client, room_name, is_owner=True)
        except httpx.HTTPError as e:
            logger.exception("Daily REST call failed")
            raise HTTPException(status_code=502, detail=f"daily_error: {e}")

    task = asyncio.create_task(
        run_daily_bot(room_url, bot_token, agent_name, app.state.db_pool, user_id=user.id)
    )
    _active_sessions.add(task)
    task.add_done_callback(_cleanup_task)
    logger.info(f"Spawned bot for room {room_name} (active={len(_active_sessions)})")

    return {"room_url": room_url, "token": user_token}


# ----- Dashboard API -------------------------------------------------------

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


@app.get("/api/aggregate")
async def api_aggregate(
    days: int = Query(7, ge=1, le=365),
    _admin: CurrentUser = Depends(require_admin),
):
    pool = app.state.db_pool
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


@app.get("/api/sessions")
async def api_sessions(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    persona: str | None = Query(None),
    environment: str | None = Query(None),
    _admin: CurrentUser = Depends(require_admin),
):
    pool = app.state.db_pool
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


@app.get("/api/sessions/{session_id}")
async def api_session_detail(
    session_id: str,
    _admin: CurrentUser = Depends(require_admin),
):
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="bad_uuid")
    pool = app.state.db_pool
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
        la = await conn.fetchrow(
            """
            SELECT bundle, report, has_unexplained, model, generated_at
            FROM session_latency_analysis WHERE session_id = $1
            """,
            sid,
        )

    latency_analysis = None
    if la is not None:
        latency_analysis = {
            "bundle": json.loads(la["bundle"]) if isinstance(la["bundle"], str) else la["bundle"],
            "report": json.loads(la["report"]) if isinstance(la["report"], str) else la["report"],
            "has_unexplained": la["has_unexplained"],
            "model": la["model"],
            "generated_at": _iso(la["generated_at"]),
        }

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


@app.post("/api/sessions/{session_id}/latency-analysis")
async def api_session_latency_analysis(
    session_id: str,
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
        return await generate_and_store(app.state.db_pool, sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="session_not_found")


# Mount static last so /health and /start-session take precedence.
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
