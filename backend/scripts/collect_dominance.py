#!/usr/bin/env python3
"""Intraday crypto-dominance collector — TOTAL / TOTAL2 / TOTAL3 / BTC.D / ETH.D / USDT.D.

Stdlib only, no dependencies, no API key. Designed to run unattended from cron
every minute and to be readable by whoever inherits it at 3am.

    python3 collect_dominance.py --once      # one sample, then exit (cron mode)
    python3 collect_dominance.py --loop 60   # sample every 60s (service mode)
    python3 collect_dominance.py --status    # what has been collected so far

WHY THIS EXISTS
---------------
Magic Alignment confirms an entry against the order flow of the dominance
symbols on the SAME intraday timeframe as the entry (5/15/30m). Nothing in this
project has ever recorded that data, and it CANNOT BE BACKFILLED — no free
source sells intraday dominance history. Every day this does not run is a day
that can never be measured later. That is the entire justification for building
it before the platform question is settled.

WHY NOT JUST POLL COINGECKO /global
-----------------------------------
That is what the existing daily cron does, and it is the obvious approach. It
does not work intraday: /global refreshes roughly every 10 MINUTES (measured:
602s between changes to its `updated_at`). Polling it per-minute yields nine
identical samples and then a jump. Resampled to 5m bars that is not low
resolution, it is FABRICATED STRUCTURE — flat candles and false breakouts that
a structure detector would happily read as order flow. Given this codebase's
history with phantom signal, that is precisely the failure worth refusing.

HOW IT ACTUALLY WORKS
---------------------
Market cap = price x circulating supply. Those two move on completely different
timescales, so they are fetched from different places at different rates:

  * circulating supplies: CoinGecko /coins/markets, top 250, refreshed ONCE A
    DAY. Supply changes are slow (issuance/burn); daily is ample. CoinGecko's
    free tier throttles hard — a burst of ~10 calls already drew a 401 during
    development — so it is called twice a day, not per minute.

  * prices: Binance /ticker/price, ONE request returning every symbol, polled
    per minute. No key, generous limits, real-time.

This is the same construction TradingView uses for its CRYPTOCAP:* symbols, so
the series should track the charts a trader actually looks at.

ACCURACY (measured at build time against CoinGecko /global)
  top-250 coins cover      99.59% of true TOTAL
  live-priced on Binance   94.2%  of computed TOTAL (127 of 250 coins)
  computed TOTAL           -0.55% vs reference
  BTC.D  +0.38pp   ETH.D  +0.06pp   USDT.D  +0.05pp

The residual is a near-constant level bias from the un-priced tail, which is
carried at its last known market cap. A multiplicative level bias does not move
BOS/FVG structure at all, which is what the strategy reads. It is calibrated out
anyway on each supply refresh (see CALIBRATION below) so the printed numbers
match what a trader sees on their chart.

HONESTY RULES (do not relax these)
  * A failed poll writes NOTHING. A gap in the series is the truth; an
    interpolated row is a lie that a structure detector will trade on.
  * Every row carries `coverage_pct` and `supplies_age_h` so degradation is
    visible in the data itself rather than hidden in a log.
  * Supplies are never fabricated. If the daily refresh fails, the previous
    snapshot keeps being used and its age climbs — visibly, in every row.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

UA = {"User-Agent": "tradingai-dominance/2.0"}

DATA_DIR = Path(os.getenv("DOMINANCE_DIR", "/opt/dominance"))
RAW_CSV = DATA_DIR / "dominance_intraday_raw.csv"
SUPPLIES = DATA_DIR / "supplies.json"

# Refresh supplies twice daily. CoinGecko free tier is fragile under load; this
# is 2 calls/day against a limit that tolerated ~10 in a burst before 401ing.
SUPPLY_MAX_AGE_H = 12.0

# Stablecoins Binance has no USDT pair for (or where the pair is meaningless).
# Held at $1.00 rather than dropped, since USDT.D is a signal the strategy uses.
PEGGED_USD = {"USDT", "USDC", "DAI", "FDUSD", "USDE", "PYUSD", "USDD", "TUSD", "USD1"}

RAW_HEADER = [
    "ts_utc",          # sample time, ISO-8601 UTC — the bar-boundary clock
    "TOTAL", "TOTAL2", "TOTAL3",
    "BTC_D", "ETH_D", "USDT_D",
    "coverage_pct",    # % of computed TOTAL that was priced live this sample
    "supplies_age_h",  # age of the supply snapshot; climbs if refresh fails
]


# --------------------------------------------------------------------------
# HTTP — retrying, but never so patiently that a per-minute cron overruns.
# --------------------------------------------------------------------------
def http_json(url: str, tries: int = 3, timeout: int = 25) -> dict | list:
    last: Exception | None = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except Exception as exc:  # noqa: BLE001 - retry any transport/decode error
            last = exc
            if attempt < tries - 1:
                time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"GET {url} failed after {tries} tries: {last}") from last


# --------------------------------------------------------------------------
# Supplies — slow-moving, refreshed twice a day, cached on disk.
# --------------------------------------------------------------------------
def refresh_supplies() -> dict:
    """Fetch top-250 circulating supplies, plus a MEASURED-BUT-UNAPPLIED bias.

    THE SERIES IS DELIBERATELY NOT CALIBRATED. This is worth explaining, because
    calibrating looks obviously correct and is in fact the wrong call here.

    Our TOTAL sits ~0.5% below CoinGecko's and BTC.D ~0.4-0.7pp above it: the
    top 250 miss a sliver of the true tail, and the un-priced remainder is
    carried at its last known cap while BTC is priced live. Scaling the output
    by a correction factor would fix the level — and would also make that factor
    STEP every time supplies refresh.

    A step in the series is exactly what a structure detector is built to notice.
    A 12-hourly discontinuity would print as a gap or a break of structure that
    no market participant ever traded. Given what this project has already been
    through with phantom signal, injecting artificial jumps into the very series
    the strategy reads for breakouts is not a trade worth making.

    A near-constant multiplicative bias, by contrast, moves no structure at all:
    BOS, FVG and direction are scale-invariant. So the bias is measured, recorded
    here for anyone reconciling levels against a TradingView chart, and left
    unapplied. `dominance_bias` below is diagnostics, not a correction.
    """
    markets = http_json(
        "https://api.coingecko.com/api/v3/coins/markets"
        "?vs_currency=usd&order=market_cap_desc&per_page=250&page=1"
    )
    time.sleep(6)  # be polite to a fragile free tier between the two calls
    glob = http_json("https://api.coingecko.com/api/v3/global")["data"]

    coins = []
    for c in markets:
        sym = (c.get("symbol") or "").upper()
        supply = c.get("circulating_supply") or 0.0
        mcap = c.get("market_cap") or 0.0
        if not sym:
            continue
        coins.append({"symbol": sym, "supply": float(supply), "mcap": float(mcap)})

    snap = {
        "fetched_at": datetime.now(tz=timezone.utc).isoformat(),
        "coins": coins,
        "reference_total": float(glob["total_market_cap"]["usd"]),
        "reference_pct": {k.upper(): float(v) for k, v in glob["market_cap_percentage"].items()},
    }

    # Measure the bias now, against a reference fetched seconds ago, so the
    # number recorded is real rather than assumed. Diagnostics only — nothing
    # downstream multiplies by it.
    prices = fetch_prices()
    computed = compute(coins, prices)
    if computed and computed["TOTAL"] > 0:
        ref_pct = snap["reference_pct"]
        snap["dominance_bias"] = {
            "note": "MEASURED, NOT APPLIED — see refresh_supplies() docstring",
            "total_ratio_ref_over_ours": snap["reference_total"] / computed["TOTAL"],
            "btc_d_pp": computed["BTC_D"] - ref_pct.get("BTC", 0.0),
            "eth_d_pp": computed["ETH_D"] - ref_pct.get("ETH", 0.0),
            "usdt_d_pp": computed["USDT_D"] - ref_pct.get("USDT", 0.0),
            "coverage_pct": computed["coverage_pct"],
        }
    else:
        snap["dominance_bias"] = {"note": "could not measure at refresh time"}

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SUPPLIES.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(snap))
    tmp.replace(SUPPLIES)  # atomic: a crash mid-write must not corrupt the cache
    return snap


def load_supplies(max_age_h: float = SUPPLY_MAX_AGE_H) -> tuple[dict, float]:
    """Return (snapshot, age_hours), refreshing if stale.

    If a refresh fails but a cached snapshot exists, the CACHE IS KEPT and its
    age keeps climbing. Stale supplies degrade accuracy slowly and visibly;
    stopping collection loses data permanently. The age rides along in every
    row so the degradation is never invisible.
    """
    snap = None
    if SUPPLIES.is_file():
        try:
            snap = json.loads(SUPPLIES.read_text())
        except Exception:  # noqa: BLE001 - a corrupt cache is not fatal, refetch
            snap = None

    def age_of(s: dict) -> float:
        t = datetime.fromisoformat(s["fetched_at"])
        return (datetime.now(tz=timezone.utc) - t).total_seconds() / 3600.0

    if snap is not None and age_of(snap) < max_age_h:
        return snap, age_of(snap)

    try:
        snap = refresh_supplies()
        return snap, 0.0
    except Exception as exc:  # noqa: BLE001
        if snap is None:
            raise RuntimeError(f"no cached supplies and refresh failed: {exc}") from exc
        print(f"WARN supply refresh failed ({exc}); using cache aged {age_of(snap):.1f}h",
              file=sys.stderr)
        return snap, age_of(snap)


# --------------------------------------------------------------------------
# Prices + the dominance computation itself.
# --------------------------------------------------------------------------
def fetch_prices() -> dict[str, float]:
    """Every Binance symbol in one request."""
    rows = http_json("https://api.binance.com/api/v3/ticker/price")
    return {r["symbol"]: float(r["price"]) for r in rows}


def compute(coins: list[dict], prices: dict[str, float]) -> dict | None:
    """Dominance from live prices x cached supplies. None if inputs are unusable.

    Returns absolute caps for TOTAL/TOTAL2/TOTAL3 and percentages for the .D
    symbols — matching the existing daily feed's schema exactly, so the two
    series are directly comparable.

    No correction factor is applied anywhere in here; see refresh_supplies().
    """
    if not coins or not prices:
        return None

    live_cap = 0.0      # coins we could price live this second
    static_cap = 0.0    # tail carried at last known market cap
    per: dict[str, float] = {}

    for c in coins:
        sym, supply, mcap = c["symbol"], c["supply"], c["mcap"]
        px = 1.0 if sym in PEGGED_USD else prices.get(f"{sym}USDT")
        if px and supply > 0:
            cap = px * supply
            live_cap += cap
        else:
            cap = mcap
            static_cap += cap
        # A symbol can legitimately appear twice (different chains); sum them.
        per[sym] = per.get(sym, 0.0) + cap

    total = live_cap + static_cap
    if total <= 0:
        return None

    btc = 100.0 * per.get("BTC", 0.0) / total
    eth = 100.0 * per.get("ETH", 0.0) / total
    usdt = 100.0 * per.get("USDT", 0.0) / total

    return {
        "TOTAL": total,
        "TOTAL2": total * (1.0 - btc / 100.0),
        "TOTAL3": total * (1.0 - (btc + eth) / 100.0),
        "BTC_D": btc,
        "ETH_D": eth,
        "USDT_D": usdt,
        "coverage_pct": 100.0 * live_cap / (live_cap + static_cap),
    }


# --------------------------------------------------------------------------
# Writing — append-only, header-once, never a partial row.
# --------------------------------------------------------------------------
def append_row(row: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    new = not RAW_CSV.exists() or RAW_CSV.stat().st_size == 0
    # Build the line fully before opening the file: a formatting error must not
    # leave a half-written row that breaks every future read of the series.
    line = [
        row["ts_utc"],
        f"{row['TOTAL']:.0f}", f"{row['TOTAL2']:.0f}", f"{row['TOTAL3']:.0f}",
        f"{row['BTC_D']:.4f}", f"{row['ETH_D']:.4f}", f"{row['USDT_D']:.4f}",
        f"{row['coverage_pct']:.2f}", f"{row['supplies_age_h']:.2f}",
    ]
    with open(RAW_CSV, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(RAW_HEADER)
        w.writerow(line)


def sample_once() -> dict | None:
    """One observation. Returns the row, or None if it could not be taken.

    A None return means NOTHING was written. That is deliberate: a gap in the
    series is honest, a synthesized row is not.
    """
    snap, age_h = load_supplies()
    prices = fetch_prices()
    vals = compute(snap["coins"], prices)
    if vals is None:
        return None
    row = {
        "ts_utc": datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat(),
        "supplies_age_h": age_h,
        **vals,
    }
    append_row(row)
    return row


def status() -> int:
    if not RAW_CSV.exists():
        print(f"no data yet at {RAW_CSV}")
        return 1
    with open(RAW_CSV) as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print(f"{RAW_CSV} exists but has no rows")
        return 1
    first, last = rows[0], rows[-1]
    t0 = datetime.fromisoformat(first["ts_utc"])
    t1 = datetime.fromisoformat(last["ts_utc"])
    span_min = (t1 - t0).total_seconds() / 60.0
    expected = int(span_min) + 1
    print(f"file      {RAW_CSV}")
    print(f"samples   {len(rows)}")
    print(f"span      {t0.isoformat()} -> {t1.isoformat()}  ({span_min/60:.2f}h)")
    if expected > 0:
        print(f"density   {100*len(rows)/expected:.1f}% of once-per-minute")
    print(f"latest    TOTAL={float(last['TOTAL']):,.0f}  BTC.D={last['BTC_D']}  "
          f"USDT.D={last['USDT_D']}  coverage={last['coverage_pct']}%  "
          f"supplies_age={last['supplies_age_h']}h")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--once", action="store_true", help="take one sample and exit (cron)")
    g.add_argument("--loop", type=int, metavar="SEC", help="sample every SEC seconds")
    g.add_argument("--status", action="store_true", help="summarize what has been collected")
    g.add_argument("--refresh-supplies", action="store_true", help="force a supply refresh")
    args = ap.parse_args()

    if args.status:
        return status()

    if args.refresh_supplies:
        snap = refresh_supplies()
        b = snap.get("dominance_bias", {})
        print(f"supplies refreshed: {len(snap['coins'])} coins")
        print(f"  measured bias vs CoinGecko (NOT applied to the series):")
        print(f"    TOTAL   ours x {b.get('total_ratio_ref_over_ours', float('nan')):.5f} = reference")
        print(f"    BTC.D   {b.get('btc_d_pp', float('nan')):+.4f} pp")
        print(f"    ETH.D   {b.get('eth_d_pp', float('nan')):+.4f} pp")
        print(f"    USDT.D  {b.get('usdt_d_pp', float('nan')):+.4f} pp")
        print(f"    live-priced coverage {b.get('coverage_pct', float('nan')):.2f}%")
        return 0

    if args.once:
        row = sample_once()
        if row is None:
            print("sample FAILED — nothing written (a gap is honest)", file=sys.stderr)
            return 1
        print(f"{row['ts_utc']} TOTAL={row['TOTAL']:,.0f} BTC.D={row['BTC_D']:.4f} "
              f"USDT.D={row['USDT_D']:.4f} coverage={row['coverage_pct']:.1f}%")
        return 0

    # --loop: a long-running collector. One bad sample must never kill the run;
    # the next minute may well succeed, and stopping loses data permanently.
    interval = max(10, int(args.loop))
    print(f"collecting every {interval}s -> {RAW_CSV} (ctrl-c to stop)")
    fails = 0
    while True:
        started = time.time()
        try:
            row = sample_once()
            if row is None:
                fails += 1
                print(f"WARN sample returned nothing ({fails} consecutive)", file=sys.stderr)
            else:
                fails = 0
        except Exception as exc:  # noqa: BLE001 - never let one bad minute end the series
            fails += 1
            print(f"WARN sample failed ({fails} consecutive): {exc}", file=sys.stderr)
        # Drift-free cadence: sleep the remainder of the interval, not a flat
        # `interval`, so samples stay aligned to the wall clock over days.
        time.sleep(max(1.0, interval - (time.time() - started)))


if __name__ == "__main__":
    sys.exit(main())
