#!/usr/bin/env python3
"""Re-measure the base-method baseline and compare it against the reference.

    python scripts/verify_baseline.py          # re-run and compare
    python scripts/verify_baseline.py --write  # adopt the new result as reference

WHY THIS EXISTS
The baseline — *143 trades, 39.9% WR, mean −0.118R, −16.1%* — is the yardstick
every future strategy claim is measured against. "Magic Alignment beats the
baseline" means nothing if the baseline itself has quietly moved.

Until this script, that number lived only as prose in a handoff document. This
turns it into something checkable: the reference trade-by-trade export is
committed next to this file, and a re-run either reproduces it exactly or says
what changed.

WHEN TO RUN IT
After anything that could alter the numeric path: a numpy/pandas bump, a
smartmoneyconcepts upgrade, or any edit to backtest/engine.py. A dependency bump
that silently shifts the yardstick is the failure this guards against — it would
not break a single test, and every later comparison would inherit the error.

NOT IN CI, deliberately: it fetches ~470 days of real Binance data, so it is
slow and depends on an external service. A CI job that fails when Binance is
having a bad morning teaches people to ignore CI.

VERIFIED 2026-08-03 under production's pins (numpy 2.2.6, pandas 3.0.2,
smartmoneyconcepts 0.0.27): bit-identical to the reference across all 143 trades
and every field, mean R matching to 12 decimal places. The concern that numpy 2's
changed reduction behaviour might shift the result was checked, not assumed.
"""
from __future__ import annotations

import argparse
import csv
import math
import statistics as st
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REFERENCE = Path(__file__).parent / "baseline" / "reference_trades.csv"

#: The pre-registered measurement window. Fixed dates, NOT "the last 470 days" —
#: a moving window would produce a different answer every run and could never
#: falsify anything.
WINDOW_END = datetime(2026, 7, 20, tzinfo=timezone.utc)
ENTRY_DAYS = 470
BIAS_EXTRA_DAYS = 300

FIELDS = [
    "symbol", "direction", "entry_time", "exit_time", "entry", "sl",
    "risk_per_unit", "r_multiple", "pnl_pct", "outcome",
]


def run_backtest_now() -> list[dict]:
    """Re-run the corrected backtest over the pre-registered window."""
    from app.services.backtest.engine import Params, run_backtest
    from app.services.market_data.sources.binance import BinanceSource

    src = BinanceSource()
    start_entry = WINDOW_END - timedelta(days=ENTRY_DAYS)
    start_bias = WINDOW_END - timedelta(days=ENTRY_DAYS + BIAS_EXTRA_DAYS)

    rows: list[dict] = []
    for pair, bsym in {"BTC/USD": "BTCUSDT", "ETH/USD": "ETHUSDT"}.items():
        entry = src.fetch_ohlcv(bsym, "1H", start_entry, WINDOW_END)
        biasd = src.fetch_ohlcv(bsym, "D", start_bias, WINDOW_END)
        trades, _ = run_backtest(entry, biasd, pair, Params())  # risk_pct fixed at 1%
        for t in trades:
            rows.append({
                "symbol": pair, "direction": t.direction,
                "entry_time": str(t.entry_time), "exit_time": str(t.exit_time),
                "entry": f"{t.entry:.2f}", "sl": f"{t.sl:.2f}",
                "risk_per_unit": f"{t.risk_per_unit:.4f}",
                "r_multiple": f"{t.r_multiple:.4f}",
                "pnl_pct": f"{t.pnl_pct:.6f}", "outcome": t.outcome,
            })
    rows.sort(key=lambda r: (r["exit_time"] or r["entry_time"]))
    return rows


def summarise(rows: list[dict]) -> dict:
    R = [float(r["r_multiple"]) for r in rows]
    n = len(R)
    if n < 2:
        return {"n": n}
    mean = st.mean(R)
    sd = st.stdev(R)
    equity = 1.0
    for r in rows:
        equity *= 1 + float(r["pnl_pct"])
    return {
        "n": n,
        "win_rate": 100 * sum(1 for x in R if x > 1e-9) / n,
        "mean_R": mean,
        "t_stat": mean / (sd / math.sqrt(n)) if sd else 0.0,
        "roi_pct": 100 * (equity - 1),
    }


def compare(reference: list[dict], fresh: list[dict]) -> bool:
    print(f"  trades   reference {len(reference)}   fresh {len(fresh)}")
    if len(reference) != len(fresh):
        print("  DIFFERS: trade count changed")
        return False

    key = lambda r: (r["symbol"], r["entry_time"])  # noqa: E731
    ref_by_key = {key(r): r for r in reference}
    new_by_key = {key(r): r for r in fresh}
    if set(ref_by_key) != set(new_by_key):
        only_ref = sorted(set(ref_by_key) - set(new_by_key))[:3]
        only_new = sorted(set(new_by_key) - set(ref_by_key))[:3]
        print(f"  DIFFERS: different trades. reference-only {only_ref}, fresh-only {only_new}")
        return False

    identical = True
    for field in FIELDS:
        bad = [k for k in ref_by_key if ref_by_key[k][field] != new_by_key[k][field]]
        if bad:
            identical = False
            k = bad[0]
            print(f"  DIFFERS: {field} on {len(bad)} trade(s) — e.g. {k}: "
                  f"{ref_by_key[k][field]!r} -> {new_by_key[k][field]!r}")
    if identical:
        print("  every field identical on every trade")
    return identical


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write", action="store_true",
                    help="adopt the fresh result as the new reference (state WHY in the commit)")
    args = ap.parse_args()

    print("Re-running the corrected backtest over the pre-registered window")
    print(f"  window: {WINDOW_END - timedelta(days=ENTRY_DAYS):%Y-%m-%d} -> {WINDOW_END:%Y-%m-%d}")
    fresh = run_backtest_now()
    s = summarise(fresh)
    print(f"\n  fresh: {s['n']} trades, WR {s['win_rate']:.1f}%, "
          f"mean R {s['mean_R']:+.4f}, t {s['t_stat']:+.2f}, ROI {s['roi_pct']:+.1f}%")

    if args.write:
        REFERENCE.parent.mkdir(parents=True, exist_ok=True)
        with open(REFERENCE, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(fresh)
        print(f"\n  wrote {REFERENCE}")
        return 0

    if not REFERENCE.is_file():
        print(f"\n  no reference at {REFERENCE} — run with --write to create one")
        return 1

    reference = list(csv.DictReader(open(REFERENCE)))
    print("\nComparing against the committed reference:")
    same = compare(reference, fresh)

    rs = summarise(reference)
    print(f"\n  reference: {rs['n']} trades, mean R {rs['mean_R']:+.12f}")
    print(f"  fresh:     {s['n']} trades, mean R {s['mean_R']:+.12f}")

    if same:
        print("\nBASELINE HOLDS — the yardstick is unchanged.")
        return 0
    print("\nBASELINE MOVED. Every past 'beats the baseline' comparison used the old")
    print("number. Find out what changed before trusting any strategy result.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
