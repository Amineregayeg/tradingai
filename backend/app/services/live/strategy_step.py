"""Live strategy evaluation — the backtest's entry logic for the LATEST bar.

`evaluate_latest_bar` is the exact, validated entry decision from
`backtest/engine.run_backtest`, applied to the most recent closed bar so the
live loop can act on it. No-lookahead: BOS confirmed at smc's BrokenIndex,
swings lagged by swing_length (identical to the backtest).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.db.enums import DirectionType, OrderType
from app.services.backtest.engine import (
    Params,
    _atr,
    causal_bias_now,
)
from app.services.execution.service import Signal
from app.services.live.decision_trace import DecisionTrace
from app.services.live.news_context import GATE_NAME as NEWS_GATE_NAME, NewsContext
# EXIT-001's RATIFIED constants, read from the registry doctrine — not `Params.rr_partial`,
# which is the BACKTEST's knob and whose numeric equality with PARTIAL_AT_R is the coincidence
# B162 is about. No new exit constant is introduced by this cutover.
from app.services.rules.exit_001_v1_model import PARTIAL_AT_R, PARTIAL_FRACTION
from app.services.ict.detector import _normalize_df, ict_detector


def evaluate_latest_bar(
    symbol: str,
    entry_df: pd.DataFrame,
    bias_df: pd.DataFrame,
    p: Params | None = None,
    risk_pct: float = 0.01,
    news: NewsContext | None = None,
) -> Signal | None:
    """Return a Signal if the latest closed bar triggers an entry, else None.

    Thin wrapper over :func:`evaluate_latest_bar_traced`. Kept so existing
    callers and tests are unaffected by the addition of decision tracing.
    """
    signal, _trace = evaluate_latest_bar_traced(symbol, entry_df, bias_df, p, risk_pct, news)
    return signal


def evaluate_latest_bar_traced(
    symbol: str,
    entry_df: pd.DataFrame,
    bias_df: pd.DataFrame,
    p: Params | None = None,
    risk_pct: float = 0.01,
    news: NewsContext | None = None,
) -> tuple[Signal | None, DecisionTrace]:
    """Evaluate the latest bar AND record why (task 2.3).

    The trace is built as the evaluation proceeds, so it reflects the code that
    actually ran rather than a reconstruction of it. Every gate is recorded
    whether it passed or failed: a record of only the failures cannot tell you
    whether the rest were even reached.

    ``news`` is `T-0036` Stage A and is RECORDED, NEVER ACTED ON. **`None` means the
    verdict was NOT TAKEN — it does not mean "no blackout", and the two must not share a
    representation.** The caller is async and this function is not, so the calendar is
    fetched there and the verdict arrives here as data; a caller that could not reach the
    calendar passes `None`, and the trace says `NOT-EVALUATED` rather than staying silent.
    **Silence would be indistinguishable from a clear week, which is the failure this
    parameter exists to make impossible.**
    """
    p = p or Params()
    trace = DecisionTrace(symbol=symbol, timeframe=str(p.entry_tf))

    # RECORDED FIRST, before any gate that can return early. A news verdict written only on
    # bars that survived `history` and `daily_bias` would be missing from exactly the traces
    # a later reader needs — the declines — and Stage B's count would be taken over a
    # population silently filtered by unrelated gates.
    if news is None:
        trace.observe(
            NEWS_GATE_NAME, None,
            "calendar verdict NOT TAKEN for this bar — this is not 'no blackout'",
        )
    else:
        news.record_on(trace)

    required = max(60, p.atr_period + 5)
    have = 0 if entry_df is None else len(entry_df)
    if not trace.gate("history", have >= required,
                      f"{have} bars available, {required} required",
                      have=have, required=required):
        return None, trace
    if entry_df.index.tz is None:
        entry_df = entry_df.copy()
        entry_df.index = pd.DatetimeIndex(entry_df.index, tz="UTC")

    ndf = _normalize_df(entry_df.reset_index().copy())
    swing = ict_detector._compute_swing(ndf, p.swing_length)
    fvgs = ict_detector.detect_fvg(ndf)
    ltf_bos = ict_detector.detect_bos_choch(ndf, swing)
    atr = _atr(entry_df, p.atr_period).to_numpy()

    n = len(entry_df)
    i = n - 1
    a = atr[i] if not np.isnan(atr[i]) else 0.0
    t = entry_df.index[i]
    hi = float(entry_df["high"].iloc[i])
    lo = float(entry_df["low"].iloc[i])
    cl = float(entry_df["close"].iloc[i])

    # SAME BIAS AS THE BACKTEST. This used to call _daily_bias_events over the
    # whole to-now frame, including today's still-forming daily bar. Measured
    # over 710 days, that disagreed with the backtest on ~2.8% of days and chose
    # the OPPOSITE direction on 32 of them — so the live engine and the
    # instrument meant to validate it were different programs, and Tier 1.7
    # ("the forward run must agree with the backtest") could not be evaluated.
    bias = causal_bias_now(bias_df, p.swing_length)
    trace.bar_time = str(t)
    if not trace.gate("daily_bias", bias is not None,
                      f"daily bias is {bias}" if bias else
                      "no daily bias yet — not enough completed daily structure",
                      bias=bias):
        return None, trace

    # LTF BOS confirmed (broken_index + 1 <= i)
    bos_dir = None
    for bi, dirn in sorted(
        (int(b["broken_index"]), "LONG" if str(b["direction"]).endswith("BULL") else "SHORT")
        for b in ltf_bos
        if b.get("broken_index") is not None
    ):
        if bi + 1 <= i:
            bos_dir = dirn
        else:
            break
    if not trace.gate(
        "ltf_bos",
        (not p.require_ltf_bos) or bos_dir == bias,
        (f"lower-timeframe break is {bos_dir or 'none'}, needs to match bias {bias}"
         if p.require_ltf_bos else "not required"),
        bos_direction=bos_dir, bias=bias, required=p.require_ltf_bos,
    ):
        return None, trace

    # PAST EVERY GATE THAT CAN STOP THIS BAR. `B217`'s landmark, and it is "past every
    # enforced gate", NOT "detection has run" — those are different lines and the difference
    # is the whole fix. Detection (`_compute_swing`, `detect_fvg`, `detect_bos_choch` above)
    # runs BEFORE two of the three gates, so a flag set there reads True on bars that
    # `daily_bias` or `ltf_bos` went on to block. Those bars would stop being
    # LIVE_NOT_REACHED and become COMPARABLE carrying `live_verdict = False` — "the live
    # heuristic DECLINED" for a bar blocked before the entry decision was reached.
    #
    # Not a corner case: `ltf_bos` blocks 849 of 1060 rows (80.1%), and 358 of 375 since
    # 08-19. `history` and `daily_bias` have never blocked a row in the corpus at all.
    trace.reached_entry_decision = True

    # last confirmed swing low/high as-of i (lagged by swing_length)
    last_low = last_high = np.nan
    if swing is not None and len(swing):
        hl = (swing["HighLow"] if "HighLow" in swing else swing.iloc[:, 0]).to_numpy()
        lvl = (swing["Level"] if "Level" in swing else swing.iloc[:, 1]).to_numpy()
        ll = hh = np.nan
        for k in range(min(n, len(hl))):
            if k + p.swing_length <= i:
                if hl[k] == -1:
                    ll = lvl[k]
                elif hl[k] == 1:
                    hh = lvl[k]
        last_low, last_high = ll, hh
    # GATE-037 removed the equilibrium midpoint from this function entirely.
    # "The bot should not use a premium/discount (equilibrium or OTE) entry filter…
    # it should not influence whether a trade is taken or rejected." The geometry
    # survives as READING VOCABULARY — it may be recorded under primitives.ranges —
    # but it may never be computed on an accept/reject path, which is where it was.
    # Deleted rather than defaulted off, so no config flip can bring it back.

    for idx, f in enumerate(fvgs):
        born = int(f["candle_index"])
        age = i - born
        fdir = "LONG" if str(f["direction"]).endswith("BULL") else "SHORT"
        ph, pl = f["price_high"], f["price_low"]

        # LOOKAHEAD GUARD (mirrors backtest engine): the FVG near-edge is the
        # bar after `born`, so entry is only admissible from born+2 onward —
        # at born+1 the edge IS this bar's own extreme and the retrace test is
        # vacuously true (fills at the bar's exact low/high).
        if age < 2:
            # Not recorded as a candidate: a gap that formed moments ago is not
            # a setup the strategy passed on, and listing every one of them
            # would bury the rejections that actually mean something.
            continue
        if age > p.fvg_lookback:
            continue

        if fdir != bias:
            trace.candidate(idx, fdir, False, "wrong direction for the daily bias",
                            bias=bias, age_bars=age)
            continue
        if a > 0 and (ph - pl) < p.min_fvg_atr * a:
            trace.candidate(idx, fdir, False, "gap too small relative to ATR",
                            gap=round(ph - pl, 2), min_required=round(p.min_fvg_atr * a, 2))
            continue

        if bias == "LONG":
            if not (lo <= ph and cl > pl):
                trace.candidate(idx, fdir, False, "price never retraced into the gap",
                                bar_low=round(lo, 2), gap_top=round(ph, 2),
                                bar_close=round(cl, 2), gap_bottom=round(pl, 2))
                continue
            entry = ph
            base = last_low if (p.sl_mode == "swing" and not np.isnan(last_low) and last_low < entry) else pl
            sl = base - p.sl_buffer_atr * a
            risk = entry - sl
            if risk <= 0:
                trace.candidate(idx, fdir, False, "stop would be at or above entry",
                                entry=round(entry, 2), stop=round(sl, 2))
                continue
            trace.candidate(idx, fdir, True, "all conditions met",
                            entry=round(entry, 2), stop=round(sl, 2), risk=round(risk, 2))
            trace.took_trade = True
            return Signal(
                symbol, DirectionType.LONG, entry, sl,
                # NO FINAL TARGET. See `Signal.tp` — this used to be
                # `entry + p.rr_partial * risk`, the partial's constant spent as the whole
                # position's take-profit (B162).
                tp=None,
                partial_price=entry + PARTIAL_AT_R * risk,
                partial_fraction=PARTIAL_FRACTION,
                risk_pct=risk_pct, order_type=OrderType.MARKET, approved=True), trace

        if bias == "SHORT":
            if not (hi >= pl and cl < ph):
                trace.candidate(idx, fdir, False, "price never retraced into the gap",
                                bar_high=round(hi, 2), gap_bottom=round(pl, 2),
                                bar_close=round(cl, 2), gap_top=round(ph, 2))
                continue
            entry = pl
            base = last_high if (p.sl_mode == "swing" and not np.isnan(last_high) and last_high > entry) else ph
            sl = base + p.sl_buffer_atr * a
            risk = sl - entry
            if risk <= 0:
                trace.candidate(idx, fdir, False, "stop would be at or below entry",
                                entry=round(entry, 2), stop=round(sl, 2))
                continue
            trace.candidate(idx, fdir, True, "all conditions met",
                            entry=round(entry, 2), stop=round(sl, 2), risk=round(risk, 2))
            trace.took_trade = True
            return Signal(
                symbol, DirectionType.SHORT, entry, sl,
                tp=None,
                partial_price=entry - PARTIAL_AT_R * risk,
                partial_fraction=PARTIAL_FRACTION,
                risk_pct=risk_pct, order_type=OrderType.MARKET, approved=True), trace

    return None, trace
