from __future__ import annotations

import asyncio

from auth import CurrentUser
from routes import auth as auth_routes


def test_api_me_projects_current_user():
    user = CurrentUser(id="u1", email="a@example.com", username="alex", is_admin=True)

    assert asyncio.run(auth_routes.api_me(user)) == {
        "id": "u1",
        "email": "a@example.com",
        "username": "alex",
        "is_admin": True,
    }
