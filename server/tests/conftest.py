from __future__ import annotations

import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import pytest  # noqa: E402

from settings import set_settings  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_settings():
    """Rebuild the settings singleton from env after each test, so a test that
    patches `get_settings()` attributes can't leak into the next one."""
    yield
    set_settings(None)


class FakeAcquire:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePool:
    def __init__(self, connection):
        self.connection = connection

    def acquire(self):
        return FakeAcquire(self.connection)
