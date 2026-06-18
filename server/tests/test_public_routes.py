from __future__ import annotations

import asyncio
import json

from auth import CurrentUser
from routes import public
from settings import get_settings
from tests.test_personas import persona_payload


def _admin(is_admin):
    return CurrentUser(id="u1", email="a@example.com", username="a", is_admin=is_admin)


def test_list_agents_returns_only_active_valid_personas(tmp_path, monkeypatch):
    active = persona_payload()
    inactive = persona_payload()
    inactive["agent"]["active"] = False
    (tmp_path / "active.json").write_text(json.dumps(active), encoding="utf-8")
    (tmp_path / "inactive.json").write_text(json.dumps(inactive), encoding="utf-8")
    (tmp_path / "broken.json").write_text("{bad json", encoding="utf-8")
    monkeypatch.setattr(get_settings(), "personas_dir", tmp_path)

    result = asyncio.run(public.list_agents(user=None))

    assert [agent["id"] for agent in result["agents"]] == ["active"]


def _write_visibility_personas(tmp_path, monkeypatch):
    pub = persona_payload()
    pub["agent"]["visibility"] = "public"
    adm = persona_payload()
    adm["agent"]["visibility"] = "admin"
    (tmp_path / "pub.json").write_text(json.dumps(pub), encoding="utf-8")
    (tmp_path / "adm.json").write_text(json.dumps(adm), encoding="utf-8")
    monkeypatch.setattr(get_settings(), "personas_dir", tmp_path)


def test_list_agents_hides_admin_only_personas_from_non_admins(tmp_path, monkeypatch):
    _write_visibility_personas(tmp_path, monkeypatch)

    anon = asyncio.run(public.list_agents(user=None))
    member = asyncio.run(public.list_agents(user=_admin(False)))

    assert [a["id"] for a in anon["agents"]] == ["pub"]
    assert [a["id"] for a in member["agents"]] == ["pub"]


def test_list_agents_shows_admin_only_personas_to_admins(tmp_path, monkeypatch):
    _write_visibility_personas(tmp_path, monkeypatch)

    result = asyncio.run(public.list_agents(user=_admin(True)))

    assert sorted(a["id"] for a in result["agents"]) == ["adm", "pub"]


def test_health_reports_active_session_count():
    result = asyncio.run(public.health())

    assert result["ok"] is True
    assert isinstance(result["active_sessions"], int)
