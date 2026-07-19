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
        has_schema = (
            await conn.fetchval("SELECT to_regclass('public.alembic_version')") is not None
        )
    finally:
        await conn.close()

    if has_schema:
        # Existing DB: apply any PENDING migrations (e.g. 0002 decision_records).
        # We must NOT skip — skipping is how a new table silently never gets
        # created on the live DB. Online `alembic upgrade head` only re-runs
        # revisions AFTER the current one, so 0001's enums are never re-created;
        # 0002+ are hand-written enum-free (sa.String + CHECK), so no
        # DuplicateObject risk. If a future revision adds an enum, revisit this.
        subprocess.check_call(["alembic", "upgrade", "head"], cwd="/app")
        print("[migrate] upgraded to head (pending migrations applied)", flush=True)
        return

    # Fresh DB: bootstrap the FULL schema at head via alembic's OFFLINE SQL, with
    # duplicate CREATE TYPE statements dropped (asyncpg double-creates enums on an
    # online upgrade). This also stamps alembic_version at head.
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
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(";".join(kept))
        print("[migrate] schema created", flush=True)
    finally:
        await conn.close()


asyncio.run(main())
