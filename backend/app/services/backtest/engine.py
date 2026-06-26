"""v1 event-driven backtester for the crypto ICT core edge.

Deterministic, no lookahead: at each entry-timeframe bar we use only structure
that had already formed. Reuses the (fixed) ICT detector for FVG + structure and
the cached Binance datasets.

Strategy v1 (per the documented method, core only):
  * HTF bias  = direction of the most recent DAILY break of structure (BOS/CHoCH).
  * Entry     = retrace into a fresh, unmitigated FVG ("imbalance") on the entry TF,
                in the bias direction, after a same-direction LTF structure break.
  * SL        = beyond the FVG (cushion), buffered by ATR.
  * Exit      = bank `partial_frac` at `rr_partial`-R, run the remainder to EOD
                (move stop to break-even after the partial).
  * Risk      = fixed `risk_pct` of equity per trade (compounding).

All thresholds are explicit parameters (the calibratable "20%"); see Params.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime

import numpy as np
import pandas as pd

from app.services.ict.detector import ict_detector, _normalize_df


@dataclass
class Params:
    entry_tf: str = "1H"
    bias_tf: str = "D"
    swing_length: int = 10          # smc swing lookback (per-TF calib knob)
    fvg_lookback: int = 12          # bars an FVG stays "fresh" for entry
    min_fvg_atr: float = 0.05       # min FVG size as fraction of ATR (noise filter)
    sl_buffer_atr: float = 0.25     # SL buffer beyond the FVG, in ATR
    rr_partial: float = 2.0         # bank partial at this R multiple
    partial_frac: float = 0.70      # fraction banked at rr_partial
    risk_pct: float = 0.01          # risk per trade (fraction of equity)
    require_ltf_bos: bool = True    # require a same-direction LTF break before entry
    max_hold_bars: int = 10         # pre-2R time-stop: close if the setup hasn't worked in N bars
    runner_trail_atr: float = 2.5   # after 2R partial, trail the 30% runner by this ATR (chandelier)
    runner_max_hold: int = 48       # hard cap on how long the runner can ride
    one_per_day: bool = True        # at most one new entry per UTC day
    atr_period: int = 14
    sl_mode: str = "swing"          # "swing" (cushion, beyond structure) | "fvg"
    use_premium_discount: bool = True  # longs only in discount, shorts in premium
    fee_pct_per_side: float = 0.0006  # taker fee per leg (entry/partial/exit)
    slip_r: float = 0.04            # avg slippage haircut per trade, in R
    # --- randomized-entry CONTROL (falsification test): keep bias + all exit/
    # sizing machinery, but enter at random times instead of at FVGs. If this
    # wins as much as the real strategy, the WR is an exit/market artifact.
    random_entries: bool = False
    random_seed: int = 0
    random_entry_prob: float = 0.04   # per eligible flat bar (one_per_day still caps)
    random_sl_atr: float = 1.5        # SL distance for the control, in ATR


@dataclass
class Trade:
    symbol: str
    direction: str          # "LONG" | "SHORT"
    entry_time: datetime
    entry: float
    sl: float
    risk_per_unit: float
    exit_time: datetime | None = None
    r_multiple: float = 0.0         # realized blended R (after partial + runner)
    pnl_pct: float = 0.0            # realized account % (r_multiple * risk_pct)
    outcome: str = "open"           # "win" | "loss" | "scratch"
    partialed: bool = False
    peak: float = 0.0               # best price since the 2R partial (for runner trail)
    month: str = ""


def _atr(df: pd.DataFrame, period: int) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def _daily_bias_events(bias_df: pd.DataFrame, swing_length: int) -> list[tuple[pd.Timestamp, str]]:
    """(event_time, 'LONG'|'SHORT') from daily BOS/CHoCH, chronological.

    NO-LOOKAHEAD: a swing/break detected at bar ``idx`` cannot be *confirmed*
    until ~``swing_length`` bars later, so we stamp the event at the bar where
    it would actually have been visible (``idx + swing_length``).
    """
    ndf = _normalize_df(bias_df.reset_index().copy())
    swing = ict_detector._compute_swing(ndf, swing_length)
    bos = ict_detector.detect_bos_choch(ndf, swing)
    n = len(bias_df)
    events: list[tuple[pd.Timestamp, str]] = []
    for d in bos:
        bi = d.get("broken_index")
        if bi is None:                      # never confirmed -> never visible
            continue
        idx = bi + 1                        # known at the bar AFTER the break completes
        if 0 <= idx < n:
            direction = "LONG" if str(d["direction"]).endswith("BULL") else "SHORT"
            events.append((bias_df.index[idx], direction))
    events.sort(key=lambda e: e[0])
    return events


def _bias_at(events: list[tuple[pd.Timestamp, str]], t: pd.Timestamp) -> str | None:
    bias = None
    for et, d in events:
        if et <= t:
            bias = d
        else:
            break
    return bias


def run_backtest(
    entry_df: pd.DataFrame,
    bias_df: pd.DataFrame,
    symbol: str,
    p: Params | None = None,
    market_bias_events: list[tuple[pd.Timestamp, str]] | None = None,
) -> tuple[list[Trade], pd.DataFrame]:
    """Run the v1 backtest. Returns (trades, equity_curve_df).

    ``market_bias_events`` (optional): the market-leader's (e.g. BTC's) daily bias
    events. When given, an entry only fires if the leader agrees with the trade
    direction — a first-order **Magic Alignment** filter (trade with the leader).
    """
    p = p or Params()
    entry_df = entry_df.copy()
    if entry_df.index.tz is None:
        entry_df.index = pd.DatetimeIndex(entry_df.index, tz="UTC")

    # Precompute structure on the FULL entry-tf series (formation index respected).
    ndf = _normalize_df(entry_df.reset_index().copy())
    swing = ict_detector._compute_swing(ndf, p.swing_length)
    fvgs = ict_detector.detect_fvg(ndf)
    ltf_bos = ict_detector.detect_bos_choch(ndf, swing)
    atr = _atr(entry_df, p.atr_period).to_numpy()

    # Forward-filled last swing low / high price as-of each bar (for cushion SL
    # and premium/discount equilibrium). NO-LOOKAHEAD: a swing at bar k is only
    # confirmable ~swing_length bars later, so it becomes "known" at k+lag.
    n = len(entry_df)
    lag = p.swing_length
    last_low = np.full(n, np.nan)
    last_high = np.full(n, np.nan)
    if swing is not None and len(swing):
        hl = (swing["HighLow"] if "HighLow" in swing else swing.iloc[:, 0]).to_numpy()
        lvl = (swing["Level"] if "Level" in swing else swing.iloc[:, 1]).to_numpy()
        pts = [(k, hl[k], lvl[k]) for k in range(min(n, len(hl))) if hl[k] in (-1, 1)]
        ll = hh = np.nan
        ptr = 0
        for i in range(n):
            while ptr < len(pts) and pts[ptr][0] + lag <= i:
                _, typ, lv = pts[ptr]
                if typ == -1:
                    ll = lv
                else:
                    hh = lv
                ptr += 1
            last_low[i] = ll
            last_high[i] = hh

    # index -> list of FVGs formed at that bar
    fvg_by_idx: dict[int, list[dict]] = {}
    for f in fvgs:
        fvg_by_idx.setdefault(int(f["candle_index"]), []).append(f)
    # last LTF BOS direction as-of each bar index. NO-LOOKAHEAD: a break is only
    # known at its smc BrokenIndex (15-35 bars after formation); discard breaks
    # that never confirmed (broken_index is None).
    bos_dir_upto: list[str | None] = [None] * len(entry_df)
    bos_events = sorted(
        (int(b["broken_index"]), "LONG" if str(b["direction"]).endswith("BULL") else "SHORT")
        for b in ltf_bos
        if b.get("broken_index") is not None
    )
    cur = None
    bptr = 0
    for i in range(len(entry_df)):
        while bptr < len(bos_events) and bos_events[bptr][0] + 1 <= i:
            cur = bos_events[bptr][1]
            bptr += 1
        bos_dir_upto[i] = cur

    bias_events = _daily_bias_events(bias_df, p.swing_length)

    times = entry_df.index
    highs = entry_df["high"].to_numpy()
    lows = entry_df["low"].to_numpy()
    closes = entry_df["close"].to_numpy()

    trades: list[Trade] = []
    equity = 1.0
    eq_curve: list[tuple[pd.Timestamp, float]] = []

    rng = np.random.default_rng(p.random_seed)
    open_t: Trade | None = None
    open_idx: int | None = None  # bar index when the position was opened (time-stop)
    sl_runner = None            # BE stop after partial
    last_entry_day = None
    # active FVG candidates: list of dicts with extra runtime keys
    active: list[dict] = []

    for i in range(len(entry_df)):
        t = times[i]
        hi, lo, cl = highs[i], lows[i], closes[i]
        a = atr[i] if not np.isnan(atr[i]) else 0.0

        # ---- manage an open position first ----
        if open_t is not None:
            ev, sl_runner = _manage_open(open_t, hi, lo, cl, sl_runner, i - open_idx, p, a)
            if ev and "close" in ev:
                _close(open_t, t, equity_r_before=open_t.r_multiple, r=ev["close"], p=p)
                equity *= (1 + open_t.pnl_pct)
                trades.append(open_t); open_t = None; open_idx = None; sl_runner = None

        eq_curve.append((t, equity))

        # register FVGs formed at this bar
        for f in fvg_by_idx.get(i, []):
            ph, pl = f["price_high"], f["price_low"]
            if a > 0 and (ph - pl) < p.min_fvg_atr * a:
                continue
            active.append({
                "dir": "LONG" if str(f["direction"]).endswith("BULL") else "SHORT",
                "ph": ph, "pl": pl, "born": i, "triggered": False,
            })

        # prune stale / invalidated candidates
        active = [c for c in active if (i - c["born"]) <= p.fvg_lookback]

        # ---- look for an entry ----
        if open_t is not None:
            continue
        if p.one_per_day and last_entry_day == t.date():
            continue
        bias = _bias_at(bias_events, t)
        if bias is None:
            continue

        # Magic Alignment (first-order): only trade WITH the market leader (BTC).
        if market_bias_events is not None and _bias_at(market_bias_events, t) != bias:
            continue

        # randomized-entry CONTROL: same bias + same exit/sizing, random timing
        if p.random_entries:
            if rng.random() < p.random_entry_prob:
                long = bias == "LONG"
                entry = cl
                a2 = a if a > 0 else entry * 0.005
                sl = entry - p.random_sl_atr * a2 if long else entry + p.random_sl_atr * a2
                risk = abs(entry - sl)
                if risk > 0:
                    open_t = Trade(symbol, "LONG" if long else "SHORT", t, entry, sl, risk, month=f"{t:%Y-%m}")
                    open_idx = i
                    last_entry_day = t.date()
        else:
            for c in active:
                if c["triggered"] or c["dir"] != bias:
                    continue
                if (i - c["born"]) < 1:   # FVG only usable after it has fully formed
                    continue
                if p.require_ltf_bos and bos_dir_upto[i] != bias:
                    continue
                lo_sw, hi_sw = last_low[i], last_high[i]
                eq = (lo_sw + hi_sw) / 2 if not (np.isnan(lo_sw) or np.isnan(hi_sw)) else None
                if bias == "LONG":
                    # retrace down into the bullish FVG
                    if lo <= c["ph"] and cl > c["pl"]:
                        entry = c["ph"]
                        # premium/discount: longs only in discount (below equilibrium)
                        if p.use_premium_discount and eq is not None and entry > eq:
                            continue
                        # cushion SL beyond the protected swing low (fallback to FVG)
                        base = lo_sw if (p.sl_mode == "swing" and not np.isnan(lo_sw) and lo_sw < entry) else c["pl"]
                        sl = base - p.sl_buffer_atr * a
                        risk = entry - sl
                        if risk <= 0:
                            continue
                        open_t = Trade(symbol, "LONG", t, entry, sl, risk, month=f"{t:%Y-%m}")
                        open_idx = i
                        c["triggered"] = True
                        last_entry_day = t.date()
                        break
                else:
                    if hi >= c["pl"] and cl < c["ph"]:
                        entry = c["pl"]
                        if p.use_premium_discount and eq is not None and entry < eq:
                            continue
                        base = hi_sw if (p.sl_mode == "swing" and not np.isnan(hi_sw) and hi_sw > entry) else c["ph"]
                        sl = base + p.sl_buffer_atr * a
                        risk = sl - entry
                        if risk <= 0:
                            continue
                        open_t = Trade(symbol, "SHORT", t, entry, sl, risk, month=f"{t:%Y-%m}")
                        open_idx = i
                        c["triggered"] = True
                        last_entry_day = t.date()
                        break

        # NO ENTRY-BAR FREE PASS: the opening bar itself can stop us out (the
        # smc fill is intrabar; SL-first ordering is the conservative assumption).
        if open_t is not None and open_idx == i:
            ev, sl_runner = _manage_open(open_t, hi, lo, cl, sl_runner, 0, p, a)
            if ev and "close" in ev:
                _close(open_t, t, equity_r_before=open_t.r_multiple, r=ev["close"], p=p)
                equity *= (1 + open_t.pnl_pct)
                trades.append(open_t); open_t = None; open_idx = None; sl_runner = None

    eq_df = pd.DataFrame(eq_curve, columns=["time", "equity"]).set_index("time")
    return trades, eq_df


def _manage_open(d: Trade, hi: float, lo: float, cl: float, sl_runner, held: int, p: Params, a: float = 0.0):
    """Evaluate one bar against an open trade. SL-first (conservative) ordering.

    Pre-2R: original SL or a `max_hold_bars` time-stop. After the 2R partial the
    30% runner trails by `runner_trail_atr` ATR (never below break-even) and is
    hard-capped at `runner_max_hold` — this is what lets winners ride.
    Returns (event, sl_runner) where event is {"close": r} | {"partial": True} | None.
    """
    risk = d.risk_per_unit
    if d.direction == "LONG":
        if not d.partialed:
            target = d.entry + p.rr_partial * risk
            if lo <= d.sl:
                return {"close": (d.sl - d.entry) / risk}, sl_runner
            if hi >= target:
                d.partialed = True
                d.r_multiple += p.partial_frac * p.rr_partial
                d.peak = hi
                trail = hi - p.runner_trail_atr * a
                return {"partial": True}, max(d.entry, trail)
            if held >= p.max_hold_bars:
                return {"close": (cl - d.entry) / risk}, sl_runner
        else:
            d.peak = max(d.peak, hi)
            new_stop = max(sl_runner, d.entry, d.peak - p.runner_trail_atr * a)
            if lo <= new_stop:
                return {"close": (new_stop - d.entry) / risk}, new_stop
            if held >= p.runner_max_hold:
                return {"close": (cl - d.entry) / risk}, new_stop
            return None, new_stop
    else:
        if not d.partialed:
            target = d.entry - p.rr_partial * risk
            if hi >= d.sl:
                return {"close": (d.entry - d.sl) / risk}, sl_runner
            if lo <= target:
                d.partialed = True
                d.r_multiple += p.partial_frac * p.rr_partial
                d.peak = lo
                trail = lo + p.runner_trail_atr * a
                return {"partial": True}, min(d.entry, trail)
            if held >= p.max_hold_bars:
                return {"close": (d.entry - cl) / risk}, sl_runner
        else:
            d.peak = min(d.peak, lo)
            new_stop = min(sl_runner, d.entry, d.peak + p.runner_trail_atr * a)
            if hi >= new_stop:
                return {"close": (d.entry - new_stop) / risk}, new_stop
            if held >= p.runner_max_hold:
                return {"close": (d.entry - cl) / risk}, new_stop
            return None, new_stop
    return None, sl_runner


def _close(d: Trade, t: pd.Timestamp, equity_r_before: float, r: float, p: Params) -> None:
    """Finalize a trade: blend any banked partial with the closing leg."""
    if d.partialed:
        # 70% already banked at rr_partial; remaining (1-frac) closes at r
        d.r_multiple = p.partial_frac * p.rr_partial + (1 - p.partial_frac) * r
    else:
        d.r_multiple = r
    # fees charged on EVERY leg (entry + exit, plus the partial leg if it fired),
    # expressed in R (cost / risk-per-unit); plus an average slippage haircut.
    legs = 3 if d.partialed else 2
    fee_r = legs * (p.fee_pct_per_side * d.entry) / d.risk_per_unit if d.risk_per_unit > 0 else 0.0
    d.r_multiple -= fee_r + p.slip_r
    d.pnl_pct = d.r_multiple * p.risk_pct
    d.exit_time = t
    d.outcome = "win" if d.r_multiple > 1e-9 else ("scratch" if abs(d.r_multiple) < 1e-9 else "loss")


def summarize(trades: list[Trade]) -> dict:
    """Aggregate stats overall and per month."""
    def block(ts: list[Trade]) -> dict:
        n = len(ts)
        wins = sum(1 for t in ts if t.outcome == "win")
        losses = sum(1 for t in ts if t.outcome == "loss")
        roi = float(np.prod([1 + t.pnl_pct for t in ts]) - 1) if ts else 0.0
        avg_r = float(np.mean([t.r_multiple for t in ts])) if ts else 0.0
        return {
            "trades": n, "wins": wins, "losses": losses,
            "win_rate": round(100 * wins / n, 1) if n else 0.0,
            "roi_pct": round(100 * roi, 2), "avg_R": round(avg_r, 3),
        }

    months = sorted({t.month for t in trades})
    return {
        "total": block(trades),
        "by_month": {m: block([t for t in trades if t.month == m]) for m in months},
    }
