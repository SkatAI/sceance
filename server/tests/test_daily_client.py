from __future__ import annotations

import asyncio

import daily_client
from tests.fakes import FakeDailyClient


def test_daily_room_and_token_payloads_include_expected_properties(monkeypatch):
    monkeypatch.setattr(daily_client.time, "time", lambda: 1000)
    client = FakeDailyClient()

    room = asyncio.run(daily_client.create_room(client))
    token = asyncio.run(daily_client.create_meeting_token(client, "room-a", is_owner=True))

    assert room == {"name": "room-a", "url": "https://room.test/a"}
    assert token == "bot-token"
    room_payload = client.posts[0][1]["properties"]
    token_payload = client.posts[1][1]["properties"]
    assert room_payload["exp"] == 1000 + daily_client.ROOM_EXPIRY_SECONDS
    assert room_payload["eject_at_room_exp"] is True
    assert room_payload["enable_chat"] is False
    assert token_payload == {
        "room_name": "room-a",
        "is_owner": True,
        "exp": 1000 + daily_client.ROOM_EXPIRY_SECONDS,
    }


def test_make_client_sets_auth_header_and_timeout():
    client = daily_client.make_client("daily-key")
    try:
        assert client.headers["authorization"] == "Bearer daily-key"
        assert client.timeout.connect == 15.0
        assert client.timeout.read == 15.0
    finally:
        asyncio.run(client.aclose())
