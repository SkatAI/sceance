"""Daily REST client for room + meeting-token creation.

Thin wrappers over the Daily v1 REST API. Functions take an injected
``httpx.AsyncClient`` so callers control connection lifetime and so tests can
substitute a fake. ``make_client`` builds a client preconfigured with the Daily
bearer auth header and request timeout, keeping the auth scheme out of callers.
"""

from __future__ import annotations

import time

import httpx

DAILY_API_BASE = "https://api.daily.co/v1"
ROOM_EXPIRY_SECONDS = 30 * 60  # 30 min


def make_client(api_key: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=15.0,
    )


async def create_room(client: httpx.AsyncClient) -> dict:
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


async def create_meeting_token(
    client: httpx.AsyncClient, room_name: str, is_owner: bool
) -> str:
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
