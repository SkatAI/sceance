"""Shared FastAPI dependencies for route modules."""

from __future__ import annotations

from fastapi import Request


def get_pool(request: Request):
    """The asyncpg pool, created in the app lifespan and stored on app state.

    Injected into handlers so they stay directly unit-testable: a test calls the
    handler with a fake pool instead of standing up the app.
    """
    return request.app.state.db_pool
