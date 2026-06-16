"""FastAPI app for the Inigo voice agent web deployment.

Wires the app together: lifespan (asyncpg pool + session-task cleanup), CORS,
the route modules under `routes/`, and the static mount. Route handlers live in
`routes/{public,auth,sessions,admin}.py`.

Run locally:
    uv run uvicorn server:app --host 0.0.0.0 --port 8001 --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger

import config
import session_tasks
from routes import admin, auth, public, sessions
from storage import close_pool, create_pool


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not config.DAILY_API_KEY:
        logger.warning("DAILY_API_KEY is not set — /start-session will fail")
    logger.info(f"Static dir: {config.STATIC_DIR}, MAX_SESSIONS={config.MAX_SESSIONS}")
    app.state.db_pool = await create_pool()
    try:
        yield
    finally:
        session_tasks.cancel_all()
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

app.include_router(public.router)
app.include_router(auth.router)
app.include_router(sessions.router)
app.include_router(admin.router)

# Mount static last so the API routes above take precedence.
if config.STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(config.STATIC_DIR), html=True), name="static")
