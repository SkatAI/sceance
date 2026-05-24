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
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger

from bot import run_daily_bot

load_dotenv(override=True)

DAILY_API_KEY = os.getenv("DAILY_API_KEY", "")
DAILY_API_BASE = "https://api.daily.co/v1"
MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", "5"))
ROOM_EXPIRY_SECONDS = 30 * 60  # 30 min

STATIC_DIR = Path(__file__).parent / "static"

_active_sessions: set[asyncio.Task] = set()


def _cleanup_task(task: asyncio.Task) -> None:
    _active_sessions.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.exception("Bot task failed", exc_info=exc)


async def _create_daily_room(client: httpx.AsyncClient) -> dict:
    expiry = int(time.time()) + ROOM_EXPIRY_SECONDS
    payload = {
        "properties": {
            "exp": expiry,
            "eject_at_room_exp": True,
            "enable_chat": False,
            "enable_screenshare": False,
            "start_video_off": True,
            "start_audio_off": False,
        },
    }
    r = await client.post(f"{DAILY_API_BASE}/rooms", json=payload)
    r.raise_for_status()
    return r.json()


async def _create_meeting_token(client: httpx.AsyncClient, room_name: str, is_owner: bool) -> str:
    payload = {
        "properties": {
            "room_name": room_name,
            "is_owner": is_owner,
            "exp": int(time.time()) + ROOM_EXPIRY_SECONDS,
        },
    }
    r = await client.post(f"{DAILY_API_BASE}/meeting-tokens", json=payload)
    r.raise_for_status()
    return r.json()["token"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not DAILY_API_KEY:
        logger.warning("DAILY_API_KEY is not set — /start-session will fail")
    logger.info(f"Static dir: {STATIC_DIR}, MAX_SESSIONS={MAX_SESSIONS}")
    yield
    # Cancel any active bot tasks on shutdown.
    for t in list(_active_sessions):
        t.cancel()


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
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"ok": True, "active_sessions": len(_active_sessions)}


@app.post("/start-session")
async def start_session():
    if len(_active_sessions) >= MAX_SESSIONS:
        raise HTTPException(status_code=429, detail="agent_busy")
    if not DAILY_API_KEY:
        raise HTTPException(status_code=500, detail="daily_api_key_missing")

    headers = {"Authorization": f"Bearer {DAILY_API_KEY}"}
    async with httpx.AsyncClient(headers=headers, timeout=15.0) as client:
        try:
            room = await _create_daily_room(client)
            room_name = room["name"]
            room_url = room["url"]
            user_token = await _create_meeting_token(client, room_name, is_owner=False)
            bot_token = await _create_meeting_token(client, room_name, is_owner=True)
        except httpx.HTTPError as e:
            logger.exception("Daily REST call failed")
            raise HTTPException(status_code=502, detail=f"daily_error: {e}")

    task = asyncio.create_task(run_daily_bot(room_url, bot_token))
    _active_sessions.add(task)
    task.add_done_callback(_cleanup_task)
    logger.info(f"Spawned bot for room {room_name} (active={len(_active_sessions)})")

    return {"room_url": room_url, "token": user_token}


# Mount static last so /health and /start-session take precedence.
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
