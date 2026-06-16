"""Public, unauthenticated routes: config, health, landing redirects, agents."""

from __future__ import annotations

import json
import os

from fastapi import APIRouter
from fastapi.responses import FileResponse, RedirectResponse
from loguru import logger

import config
import session_tasks
from personas import Persona, PersonaError

router = APIRouter()


@router.get("/api/config")
async def api_config():
    """Public Supabase config consumed by the browser to initialize supabase-js."""
    return {
        "supabase_url": os.getenv("SUPABASE_URL", ""),
        "supabase_anon_key": os.getenv("SUPABASE_KEY", ""),
        "open_signup": config.OPEN_SIGNUP,
    }


@router.get("/health")
async def health():
    return {"ok": True, "active_sessions": session_tasks.count()}


@router.get("/dashboard")
async def dashboard():
    return RedirectResponse(url="/dashboard.html")


@router.get("/sessions/{session_id}")
async def session_page(session_id: str):
    # Operator detail view for a single séance. The page itself is admin-gated
    # client-side (same as the dashboard); the JWT-protected data is fetched
    # from /api/sessions/{id}.
    return FileResponse(config.STATIC_DIR / "session.html")


@router.get("/agents")
async def list_agents():
    agents = []
    for path in sorted(config.PERSONAS_DIR.glob("*.json")):
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
