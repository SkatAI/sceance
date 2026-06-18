"""FastAPI-level smoke tests: prove router registration + dependency wiring
survived the router/repository split. Unit tests remain the primary coverage for
SQL shaping and orchestration; these only exercise the wiring.

The TestClient is built without a `with` block, so the app lifespan (which would
open a real asyncpg pool) never runs. Handlers that need a pool or a user get
their dependencies overridden.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server
from auth import CurrentUser, get_current_user
from deps import get_pool


@pytest.fixture
def client():
    c = TestClient(server.app)
    yield c
    server.app.dependency_overrides.clear()


def _as_user(**over):
    base = {"id": "u1", "email": "u@example.com", "username": "u", "is_admin": False}
    base.update(over)
    return lambda: CurrentUser(**base)


# ─── Unauthenticated routes ─────────────────────────────────────────

def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "active_sessions" in body


def test_agents_lists_active_personas(client):
    r = client.get("/agents")
    assert r.status_code == 200
    assert isinstance(r.json()["agents"], list)


# ─── /api/me: dependency wiring ─────────────────────────────────────

def test_me_requires_bearer_token(client):
    r = client.get("/api/me")
    assert r.status_code == 401
    assert r.json()["detail"] == "missing_bearer_token"


def test_me_returns_current_user_when_authenticated(client):
    server.app.dependency_overrides[get_current_user] = _as_user(is_admin=True)
    r = client.get("/api/me")
    assert r.status_code == 200
    assert r.json() == {
        "id": "u1",
        "email": "u@example.com",
        "username": "u",
        "is_admin": True,
    }


# ─── /start-session: validation errors ──────────────────────────────

def test_start_session_missing_agent_field_is_422(client):
    server.app.dependency_overrides[get_current_user] = _as_user()
    server.app.dependency_overrides[get_pool] = lambda: object()
    r = client.post("/start-session", json={})
    assert r.status_code == 422  # pydantic: 'agent' required


def test_start_session_blank_agent_is_400(client):
    server.app.dependency_overrides[get_current_user] = _as_user()
    server.app.dependency_overrides[get_pool] = lambda: object()
    r = client.post("/start-session", json={"agent": "   "})
    assert r.status_code == 400
    assert r.json()["detail"] == "agent_required"


def test_start_session_unknown_agent_is_404(client):
    server.app.dependency_overrides[get_current_user] = _as_user()
    server.app.dependency_overrides[get_pool] = lambda: object()
    r = client.post("/start-session", json={"agent": "no_such_agent_xyz"})
    assert r.status_code == 404
    assert r.json()["detail"] == "agent_not_found"


# ─── Admin auth-failure path ────────────────────────────────────────

def test_admin_endpoint_rejects_anonymous(client):
    server.app.dependency_overrides[get_pool] = lambda: object()
    r = client.get("/api/aggregate")
    assert r.status_code == 401  # require_admin -> get_current_user, no token


def test_admin_endpoint_rejects_non_admin(client):
    server.app.dependency_overrides[get_current_user] = _as_user(is_admin=False)
    server.app.dependency_overrides[get_pool] = lambda: object()
    r = client.get("/api/aggregate")
    assert r.status_code == 403
    assert r.json()["detail"] == "admin_only"
