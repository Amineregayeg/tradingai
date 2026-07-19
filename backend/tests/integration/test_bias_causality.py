"""The backtest daily bias must be CAUSAL (no future data).

A Level-2 stress test found that `_daily_bias_events` runs smc BOS/CHoCH over
the whole series, whose `broken_index` is non-causal, so the backtest's daily
HTF bias could reflect bars after the decision day (real direction flips). The
fix is `_causal_daily_bias_events`, which recomputes from a trailing window
ending at each day. These tests pin the property: the causal bias as-of a day is
truncation-invariant (identical whether computed from the full series or from
data ending that day), while the old method is not.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.backtest import engine as E


def _series(seed: int, n: int = 150) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 40000 + rng.normal(0, 1, n).cumsum() * 300
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "open": close + rng.normal(0, 60, n),
            "high": close + np.abs(rng.normal(0, 120, n)),
            "low": close - np.abs(rng.normal(0, 120, n)),
            "close": close,
        },
        index=idx,
    )


def test_old_full_series_bias_has_lookahead():
    """Guard-rail sanity: the OLD full-series method DOES leak future data, so
    the causal test below is meaningful (not vacuously satisfied)."""
    df = _series(seed=4)
    full = E._daily_bias_events(df, 10)
    violations = 0
    for j in range(25, len(df)):
        day = df.index[j]
        trunc = E._daily_bias_events(df.iloc[: j + 1], 10)
        if E._bias_at(full, day) != E._bias_at(trunc, day):
            violations += 1
    assert violations > 0, "expected the non-causal method to exhibit lookahead"


def test_causal_bias_is_truncation_invariant():
    """The FIX: the causal bias as-of day j must be identical whether computed
    from the full series or from data truncated at day j (i.e. no future data)."""
    df = _series(seed=4)
    full = E._causal_daily_bias_events(df, 10)
    for j in range(30, len(df), 8):  # sparse (each truncation recompute is O(window))
        day = df.index[j]
        trunc = E._causal_daily_bias_events(df.iloc[: j + 1], 10)
        assert E._bias_at(full, day) == E._bias_at(trunc, day), (
            f"causal bias differs full vs truncated at {day} — lookahead leak"
        )


def test_run_backtest_uses_causal_bias(monkeypatch):
    """run_backtest must feed CAUSAL bias into the entry loop — a regression here
    (reverting to the full-series events) is caught by spying on which function
    the backtest calls to build bias_events."""
    called = {"causal": 0, "full_direct": 0}
    real_causal = E._causal_daily_bias_events

    def spy_causal(*a, **k):
        called["causal"] += 1
        return real_causal(*a, **k)

    monkeypatch.setattr(E, "_causal_daily_bias_events", spy_causal)

    entry = _series(seed=4)  # reuse as a small 1H-like frame
    bias = _series(seed=4, n=120)
    E.run_backtest(entry, bias, "BTCUSDT", E.Params(require_ltf_bos=False))
    assert called["causal"] >= 1, "run_backtest must build bias from the causal timeline"


def test_intraday_flip_is_not_applied_before_its_day_closes():
    """INTRADAY causality (third-lookahead regression): the bias applied to
    intraday times ON day j must not depend on day j's own (not-yet-closed)
    candle. We blank each day's OHLC to a doji-at-open and confirm the bias
    as-of that day's 00:00 is unchanged — i.e. the flip that day j's full candle
    would trigger is stamped at the NEXT open, not consumed intraday."""
    df = _series(seed=4, n=140)
    full = E._causal_daily_bias_events(df, 10)
    changed = 0
    for j in range(30, len(df), 5):
        day_open = df.index[j]
        blanked = df.copy()
        o = float(blanked["open"].iloc[j])
        blanked.iloc[j, blanked.columns.get_loc("high")] = o
        blanked.iloc[j, blanked.columns.get_loc("low")] = o
        blanked.iloc[j, blanked.columns.get_loc("close")] = o
        tl_blank = E._causal_daily_bias_events(blanked, 10)
        # bias as-of the START of day j must be identical with/without day j's candle
        if E._bias_at(full, day_open) != E._bias_at(tl_blank, day_open):
            changed += 1
    assert changed == 0, f"day-j candle leaked into day-j intraday bias on {changed} days"
