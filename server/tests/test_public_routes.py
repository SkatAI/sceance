from __future__ import annotations

import asyncio
import json

import config
from routes import public
from tests.test_personas import persona_payload


def test_list_agents_returns_only_active_valid_personas(tmp_path, monkeypatch):
    active = persona_payload()
    inactive = persona_payload()
    inactive["agent"]["active"] = False
    (tmp_path / "active.json").write_text(json.dumps(active), encoding="utf-8")
    (tmp_path / "inactive.json").write_text(json.dumps(inactive), encoding="utf-8")
    (tmp_path / "broken.json").write_text("{bad json", encoding="utf-8")
    monkeypatch.setattr(config, "PERSONAS_DIR", tmp_path)

    result = asyncio.run(public.list_agents())

    assert [agent["id"] for agent in result["agents"]] == ["active"]


def test_health_reports_active_session_count():
    result = asyncio.run(public.health())

    assert result["ok"] is True
    assert isinstance(result["active_sessions"], int)
