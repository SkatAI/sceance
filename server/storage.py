"""Thin asyncpg wrapper for Supabase Postgres.

One process-wide connection pool, created in the FastAPI lifespan and passed
into each bot session. Provides a minimal `bulk_insert` helper used by the
background drain loop in `recorder.py`.
"""

from __future__ import annotations

import os
from typing import Any, Iterable, Sequence

import asyncpg
from loguru import logger


async def create_pool() -> asyncpg.Pool:
    url = os.getenv("SUPABASE_DB_URL", "").strip()
    if not url:
        raise RuntimeError("SUPABASE_DB_URL is not set")
    # statement_cache_size=0 is required when connecting through Supabase's
    # Supavisor / pgbouncer pooler (transaction mode). Without it, asyncpg's
    # per-connection prepared-statement names collide across recycled sessions:
    #   DuplicatePreparedStatementError: prepared statement "__asyncpg_stmt_1__"
    #   already exists
    pool = await asyncpg.create_pool(
        dsn=url,
        min_size=1,
        max_size=int(os.getenv("SUPABASE_POOL_MAX", "8")),
        command_timeout=10,
        statement_cache_size=0,
    )
    logger.info("Supabase pool created")
    return pool


async def close_pool(pool: asyncpg.Pool | None) -> None:
    if pool is None:
        return
    await pool.close()
    logger.info("Supabase pool closed")


async def bulk_insert(
    pool: asyncpg.Pool,
    table: str,
    columns: Sequence[str],
    rows: Iterable[Sequence[Any]],
) -> None:
    rows = list(rows)
    if not rows:
        return
    async with pool.acquire() as conn:
        await conn.copy_records_to_table(table, records=rows, columns=list(columns))
