"""Session route: create a Daily room + tokens and spawn the bot task."""

from __future__ import annotations

import asyncio

import httpx
from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel

import config
import daily_client
import session_tasks
from auth import CurrentUser, get_current_user
from bot import run_daily_bot
from deps import get_pool

router = APIRouter()


class StartSessionBody(BaseModel):
    agent: str


@router.post("/start-session")
async def start_session(
    body: StartSessionBody,
    pool=Depends(get_pool),
    user: CurrentUser = Depends(get_current_user),
):
    agent_name = (body.agent or "").strip()
    if not agent_name:
        raise HTTPException(status_code=400, detail="agent_required")
    persona_path = config.PERSONAS_DIR / f"{agent_name}.json"
    if not persona_path.exists():
        raise HTTPException(status_code=404, detail="agent_not_found")
    if session_tasks.count() >= config.MAX_SESSIONS:
        raise HTTPException(status_code=429, detail="agent_busy")
    if not config.DAILY_API_KEY:
        raise HTTPException(status_code=500, detail="daily_api_key_missing")

    async with daily_client.make_client(config.DAILY_API_KEY) as client:
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
        run_daily_bot(room_url, bot_token, agent_name, pool, user_id=user.id)
    )
    session_tasks.register(task)
    logger.info(f"Spawned bot for room {room_name} (active={session_tasks.count()})")

    return {"room_url": room_url, "token": user_token}
