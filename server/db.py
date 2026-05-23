"""SQLite storage for session transcripts and pipeline timing events.

Schema:
- sessions: one row per pipeline run, with a snapshot of the persona used.
- messages: user/assistant transcript turns.
- events:   fine-grained timing events (frame-level), for latency analysis.

All writes are synchronous sqlite3 calls. At the volume of a voice
conversation (a few hundred events per minute) this is fine; if it ever
becomes a bottleneck, switch to aiosqlite or batch inserts.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    persona_name  TEXT,
    persona_json  TEXT,
    started_at    TEXT NOT NULL,
    ended_at      TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     INTEGER NOT NULL REFERENCES sessions(id),
    role           TEXT NOT NULL,
    text           TEXT NOT NULL,
    language       TEXT,
    stt_timestamp  TEXT,
    recorded_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);

CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    INTEGER NOT NULL REFERENCES sessions(id),
    kind          TEXT NOT NULL,
    timestamp_ns  INTEGER NOT NULL,
    payload       TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionDB:
    """Thin wrapper around a sqlite3 connection scoped to one session."""

    def __init__(self, db_path: Path, persona: dict):
        self.path = db_path
        self._conn = sqlite3.connect(str(db_path), isolation_level=None)  # autocommit
        self._conn.executescript(SCHEMA)
        cur = self._conn.execute(
            "INSERT INTO sessions (persona_name, persona_json, started_at) VALUES (?, ?, ?)",
            (persona.get("name"), json.dumps(persona), _now_iso()),
        )
        self.session_id: int = cur.lastrowid

    def add_message(
        self,
        role: str,
        text: str,
        language: str | None = None,
        stt_timestamp: str | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO messages (session_id, role, text, language, stt_timestamp, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (self.session_id, role, text, language, stt_timestamp, _now_iso()),
        )

    def add_event(self, kind: str, timestamp_ns: int, payload: dict | None = None) -> None:
        self._conn.execute(
            "INSERT INTO events (session_id, kind, timestamp_ns, payload) VALUES (?, ?, ?, ?)",
            (
                self.session_id,
                kind,
                timestamp_ns,
                json.dumps(payload) if payload is not None else None,
            ),
        )

    def close(self) -> None:
        try:
            self._conn.execute(
                "UPDATE sessions SET ended_at = ? WHERE id = ?",
                (_now_iso(), self.session_id),
            )
        finally:
            self._conn.close()
