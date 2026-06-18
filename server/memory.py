"""Cross-session user memory.

Two coroutines:
- `load_memory_brief` builds the brief injected at the start of every call.
- `summarize_and_persist` runs fire-and-forget at hangup: it asks Claude to
  produce a session summary + updated user profile in one call, then writes
  both back to Supabase.

The brief is plain text wrapped in a clearly-marked block so the agent
treats it as internal context, not something to read aloud.
"""

from __future__ import annotations

import os
import uuid

import asyncpg
from loguru import logger

from llm_json import call_anthropic_text, extract_json_object

SUMMARIZER_MODEL = "claude-sonnet-4-6"
RECENT_SESSIONS_LIMIT = 3
NO_PROFILE = "(none yet — this is the first conversation with this user)"


async def load_memory_brief(pool: asyncpg.Pool, user_id: str | None) -> str | None:
    """Return the memory-brief text for a user, or None for anonymous calls.

    Always returns a string when user_id is given — even for first-timers — so
    the agent knows whether prior context exists.
    """
    if not user_id:
        return None
    uid = uuid.UUID(user_id)
    async with pool.acquire() as conn:
        profile_row = await conn.fetchrow(
            "SELECT profile_text FROM user_profile WHERE user_id = $1",
            uid,
        )
        recent = await conn.fetch(
            """
            SELECT started_at, persona_name, summary
            FROM sessions
            WHERE user_id = $1 AND summary IS NOT NULL AND summary <> ''
            ORDER BY started_at DESC
            LIMIT $2
            """,
            uid,
            RECENT_SESSIONS_LIMIT,
        )

    profile_text = (profile_row["profile_text"].strip() if profile_row else "") or NO_PROFILE
    lines = [
        "[Memory brief — internal context, do not read aloud or quote]",
        "User profile:",
        profile_text,
    ]
    if recent:
        lines.append("")
        lines.append(f"Recent sessions (most recent first, up to {RECENT_SESSIONS_LIMIT}):")
        for r in recent:
            date = r["started_at"].strftime("%Y-%m-%d")
            persona = r["persona_name"] or "unknown"
            lines.append(f"- {date} · {persona} — {r['summary'].strip()}")
    else:
        lines.append("")
        lines.append("Recent sessions: (none)")
    return "\n".join(lines)


_SUMMARIZER_SYSTEM = """You are the memory-keeper for a voice coach service. After each
call you read the transcript and produce two things:

1. A short session summary (≤200 words). Focus on what mattered to the user,
   themes, open threads worth picking up next time. Neutral, factual tone.
2. An updated user profile (≤500 words). Merge the prior profile (if any) with
   new facts surfaced this session. Put stable identity facts first — name,
   age, gender, family, work — then evolving themes (recurring concerns,
   relationships, goals). Drop nothing important; rewrite for clarity.

Return STRICT JSON with exactly two keys: "session_summary" and "updated_profile".
No prose outside the JSON object."""


async def summarize_and_persist(
    pool: asyncpg.Pool,
    session_id: uuid.UUID,
    user_id: str,
    model: str = SUMMARIZER_MODEL,
) -> None:
    """Fire-and-forget. Never raises — errors are logged."""
    try:
        async with pool.acquire() as conn:
            messages = await conn.fetch(
                "SELECT role, text FROM messages WHERE session_id = $1 ORDER BY id",
                session_id,
            )
            prior = await conn.fetchrow(
                "SELECT profile_text FROM user_profile WHERE user_id = $1",
                uuid.UUID(user_id),
            )
        if not messages:
            logger.info(f"summarize_and_persist: session {session_id} has no messages, skipping")
            return

        transcript = "\n".join(f"{m['role']}: {m['text']}" for m in messages)
        prior_profile = (prior["profile_text"] if prior else "") or "(no prior profile)"

        prompt = (
            f"Prior user profile:\n{prior_profile}\n\n"
            f"Conversation transcript:\n{transcript}\n\n"
            "Produce the JSON now."
        )

        resp = await call_anthropic_text(
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            model=model,
            system=_SUMMARIZER_SYSTEM,
            prompt=prompt,
        )
        parsed = extract_json_object(resp)
        session_summary = (parsed.get("session_summary") or "").strip()
        updated_profile = (parsed.get("updated_profile") or "").strip()
        if not session_summary or not updated_profile:
            logger.warning(
                f"summarize_and_persist: empty fields for session {session_id} — "
                f"summary={len(session_summary)}, profile={len(updated_profile)}"
            )
            return

        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    UPDATE sessions
                       SET summary = $1, summary_model = $2, summarized_at = now()
                     WHERE id = $3
                    """,
                    session_summary,
                    model,
                    session_id,
                )
                await conn.execute(
                    """
                    INSERT INTO user_profile (user_id, profile_text, updated_at, last_session_id, summary_model)
                    VALUES ($1, $2, now(), $3, $4)
                    ON CONFLICT (user_id) DO UPDATE
                      SET profile_text    = EXCLUDED.profile_text,
                          updated_at      = now(),
                          last_session_id = EXCLUDED.last_session_id,
                          summary_model   = EXCLUDED.summary_model
                    """,
                    uuid.UUID(user_id),
                    updated_profile,
                    session_id,
                    model,
                )
        logger.info(
            f"summarize_and_persist: session {session_id} summarized "
            f"(summary={len(session_summary)} chars, profile={len(updated_profile)} chars)"
        )
    except Exception as e:
        logger.exception(f"summarize_and_persist failed for session {session_id}: {e}")
