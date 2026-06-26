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
    _bias_at,
    _daily_bias_events,
)
from app.services.execution.service import Signal
from app.services.ict.detector import _normalize_df, ict_detector


def evaluate_latest_bar(
    symbol: str,
    entry_df: pd.DataFrame,
    bias_df: pd.DataFrame,
    p: Params | None = None,
    risk_pct: float = 0.01,
) -> Signal | None:
    """Return a Signal if the latest closed bar triggers an entry, else None."""
    p = p or Params()
    if entry_df is None or len(entry_df) < max(60, p.atr_period + 5):
        return None
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

    bias = _bias_at(_daily_bias_events(bias_df, p.swing_length), t)
    if bias is None:
        return None

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
    if p.require_ltf_bos and bos_dir != bias:
        return None

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
    eq = (last_low + last_high) / 2 if not (np.isnan(last_low) or np.isnan(last_high)) else None

    for f in fvgs:
        born = int(f["candle_index"])
        if not (1 <= i - born <= p.fvg_lookback):
            continue
        fdir = "LONG" if str(f["direction"]).endswith("BULL") else "SHORT"
        if fdir != bias:
            continue
        ph, pl = f["price_high"], f["price_low"]
        if a > 0 and (ph - pl) < p.min_fvg_atr * a:
            continue
        if bias == "LONG" and lo <= ph and cl > pl:
            entry = ph
            if p.use_premium_discount and eq is not None and entry > eq:
                continue
            base = last_low if (p.sl_mode == "swing" and not np.isnan(last_low) and last_low < entry) else pl
            sl = base - p.sl_buffer_atr * a
            risk = entry - sl
            if risk <= 0:
                continue
            return Signal(symbol, DirectionType.LONG, entry, sl, entry + p.rr_partial * risk,
                          risk_pct, OrderType.MARKET, approved=True)
        if bias == "SHORT" and hi >= pl and cl < ph:
            entry = pl
            if p.use_premium_discount and eq is not None and entry < eq:
                continue
            base = last_high if (p.sl_mode == "swing" and not np.isnan(last_high) and last_high > entry) else ph
            sl = base + p.sl_buffer_atr * a
            risk = sl - entry
            if risk <= 0:
                continue
            return Signal(symbol, DirectionType.SHORT, entry, sl, entry - p.rr_partial * risk,
                          risk_pct, OrderType.MARKET, approved=True)
    return None
