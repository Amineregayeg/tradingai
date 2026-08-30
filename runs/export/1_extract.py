import asyncio, os, json, datetime, decimal
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

def enc(o):
    if isinstance(o, (datetime.datetime, datetime.date)): return o.isoformat()
    if isinstance(o, decimal.Decimal): return str(o)
    if isinstance(o, (bytes, bytearray)): return o.decode("utf-8", "replace")
    return str(o)

async def rows(c, q, **kw):
    r = await c.execute(text(q), kw)
    keys = list(r.keys())
    return [dict(zip(keys, row)) for row in r.all()]

async def main():
    e = create_async_engine(os.environ["DATABASE_URL"])
    out = {}
    async with e.connect() as c:
        out["runs"] = await rows(c, "select * from engine_runs order by started_at")
        out["decisions"] = await rows(c, "select * from decision_records order by created_at")
        out["trades"] = await rows(c, "select * from trades order by entry_time")
        out["telemetry_by_run"] = await rows(c,
            "select run_id, record_type, count(*) n, min(created_at) first_at, max(created_at) last_at "
            "from telemetry_records group by run_id, record_type order by run_id, record_type")
        out["db_totals"] = (await rows(c,
            "select (select count(*) from engine_runs) runs, "
            "(select count(*) from decision_records) decisions, "
            "(select count(*) from trades) trades, "
            "(select count(*) from telemetry_records) telemetry, "
            "(select count(*) from candles) candles"))[0]
    await e.dispose()
    print("===JSON_BEGIN===")
    print(json.dumps(out, default=enc))
    print("===JSON_END===")
asyncio.run(main())
