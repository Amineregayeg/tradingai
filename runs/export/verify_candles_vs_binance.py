import asyncio, os, json, urllib.request, datetime
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

def binance(sym, start_ms, end_ms, interval="1h"):
    url = (f"https://api.binance.com/api/v3/klines?symbol={sym}&interval={interval}"
           f"&startTime={start_ms}&endTime={end_ms}&limit=10")
    return json.load(urllib.request.urlopen(url, timeout=25))

async def main():
    e = create_async_engine(os.environ["DATABASE_URL"])
    async with e.connect() as c:
        rows = (await c.execute(text(
          "select time, pair, timeframe, open, high, low, close from candles "
          "where pair='BTC/USD' and timeframe='1H' order by time desc limit 5"))).all()
    await e.dispose()
    print(f"{'candle time':<20} {'src':<7} {'open':>12} {'high':>12} {'low':>12} {'close':>12}")
    worst = 0.0
    for r in rows:
        t = r.time
        ms = int(t.timestamp()*1000)
        try:
            k = binance("BTCUSDT", ms, ms+60_000)
        except Exception as ex:
            print("  binance fetch failed:", str(ex)[:80]); return
        if not k:
            print(f"{str(t)[:19]:<20} NO BINANCE KLINE"); continue
        bo, bh, bl, bc = float(k[0][1]), float(k[0][2]), float(k[0][3]), float(k[0][4])
        do, dh, dl, dc = float(r.open), float(r.high), float(r.low), float(r.close)
        print(f"{str(t)[:19]:<20} {'db':<7} {do:>12.2f} {dh:>12.2f} {dl:>12.2f} {dc:>12.2f}")
        print(f"{'':<20} {'binance':<7} {bo:>12.2f} {bh:>12.2f} {bl:>12.2f} {bc:>12.2f}")
        d = max(abs(do-bo), abs(dh-bh), abs(dl-bl), abs(dc-bc))
        rel = d / bc * 100 if bc else 0
        worst = max(worst, rel)
        print(f"{'':<20} max abs diff {d:.2f}  ({rel:.4f}% of close)\n")
    print(f"WORST RELATIVE DIFFERENCE ACROSS SAMPLES: {worst:.4f}%")
asyncio.run(main())
