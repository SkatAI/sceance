from __future__ import annotations

from pathlib import Path


MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def migration_text(name: str) -> str:
    return (MIGRATIONS / name).read_text(encoding="utf-8").lower()


def test_observability_schema_contains_recorder_tables_and_columns():
    sql = migration_text("001_init.sql")

    for table in ("sessions", "messages", "events", "metrics"):
        assert f"create table if not exists {table}" in sql

    for column in (
        "persona_name",
        "persona_json",
        "total_prompt_tokens",
        "total_completion_tokens",
        "total_cache_read_tokens",
        "total_cache_creation_tokens",
        "total_tts_chars",
    ):
        assert column in sql

    for column in ("role", "text", "language", "stt_timestamp", "recorded_at"):
        assert column in sql

    for column in ("processor", "model", "kind", "value_num", "reasoning_tokens"):
        assert column in sql


def test_auth_migration_contains_profiles_and_session_user_link():
    sql = migration_text("002_auth.sql")

    assert "create table if not exists public.profiles" in sql
    assert "references auth.users(id)" in sql
    assert "is_admin" in sql
    assert "create trigger on_auth_user_created" in sql
    assert "add column if not exists user_id" in sql
    assert "idx_sessions_user_id" in sql


def test_memory_migration_contains_profile_and_session_summary_columns():
    sql = migration_text("003_user_memory.sql")

    assert "create table if not exists public.user_profile" in sql
    assert "profile_text" in sql
    assert "last_session_id" in sql
    assert "summary_model" in sql
    assert "add column if not exists summary" in sql
    assert "add column if not exists summarized_at" in sql
