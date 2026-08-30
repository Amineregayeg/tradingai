import asyncio, os, re, collections
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
RX = re.compile(r"disagree=(\d+) \(rule_stricter=(\d+) rule_looser=(\d+)[^)]*\) agree=(\d+) not_comparable=(\d+)")
async def main():
    e = create_async_engine(os.environ["DATABASE_URL"])
    async with e.connect() as c:
        for label, rid in (("RUN-23 f8b40671 (the one the commit names)", "f8b40671"),
                           ("RUN-21 a32c3b98 (not pre-selected by anyone)", "a32c3b98")):
            r = (await c.execute(text(
              "select id, started_at, ended_at from engine_runs where id::text like :p"),
              {"p": rid + "%"})).one()
            rows = (await c.execute(text(
              "select outcome, reasons from decision_records where run_id = :r order by created_at"),
              {"r": r.id})).all()
            t = collections.Counter(); n = 0
            for x in rows:
                for line in (x.reasons or []):
                    m = RX.search(line)
                    if m:
                        n += 1
                        t["disagree"] += int(m.group(1)); t["stricter"] += int(m.group(2))
                        t["looser"] += int(m.group(3)); t["agree"] += int(m.group(4))
                        t["nc"] += int(m.group(5))
            oc = collections.Counter(x.outcome for x in rows)
            print(f"\n{label}")
            print(f"  run id       {r.id}")
            print(f"  window       {str(r.started_at)[:19]} .. {str(r.ended_at)[:19] if r.ended_at else 'OPEN'}")
            print(f"  decision rows {len(rows)}   outcomes {dict(oc)}")
            print(f"  parsed comparison lines {n} of {len(rows)}")
            print(f"  agree {t['agree']}  disagree {t['disagree']}  rule_stricter {t['stricter']}"
                  f"  rule_looser {t['looser']}  not_comparable {t['nc']}"
                  f"  comparable {t['agree']+t['disagree']}")
    await e.dispose()
asyncio.run(main())
