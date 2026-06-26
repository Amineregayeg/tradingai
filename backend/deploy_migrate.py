"""Idempotent DB schema bootstrap, run at container start.

Online ``alembic upgrade head`` double-creates Postgres ENUM types under asyncpg
(DuplicateObjectError, e.g. on ``direction_t``). This instead emits alembic's
offline SQL, drops duplicate ``CREATE TYPE`` statements, and applies it once --
but only when the schema isn't already present, so it is safe to run on every
(re)start.
"""
import asyncio
import os
import re
import subprocess

import asyncpg


async def main() -> None:
    dsn = os.environ["DATABASE_URL"].replace("+asyncpg", "")
    conn = await asyncpg.connect(dsn)
    try:
        if await conn.fetchval("SELECT to_regclass('public.alembic_version')") is not None:
            print("[migrate] schema already present - skipping", flush=True)
            return
        sql = subprocess.check_output(
            ["alembic", "upgrade", "head", "--sql"], cwd="/app"
        ).decode()
        seen: set[str] = set()
        kept: list[str] = []
        for stmt in sql.split(";"):
            m = re.search(r"CREATE TYPE\s+(\w+)\s+AS ENUM", stmt, re.IGNORECASE)
            if m:
                name = m.group(1).lower()
                if name in seen:
                    continue
                seen.add(name)
            kept.append(stmt)
        await conn.execute(";".join(kept))
        print("[migrate] schema created", flush=True)
    finally:
        await conn.close()


asyncio.run(main())
