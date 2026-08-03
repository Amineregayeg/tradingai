"""The live engine and the backtest must decide direction the same way (A2 / 2.4).

THE DEFECT THIS PINS
`strategy_step` called `_daily_bias_events` over the whole to-now frame —
including today's still-forming daily bar — while `backtest/engine` used the
causal trailing-window timeline. Measured over 710 days of real BTC and ETH
data, those disagreed on ~2.8% of days and chose the OPPOSITE direction on 32
of them.

That is not drift, it is two different strategies wearing one name. It also made
Tier 1.7 — "the same edge must appear in forward live-paper, agreeing with the
backtest" — impossible to evaluate: a disagreement between them could always be
blamed on the bias mismatch rather than on the strategy.

A simulation cannot prove a live bot correct if they are not the same program.
These tests are the mechanism that keeps them one program.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services.backtest.engine import (
    Params,
    _bias_at,
    _causal_daily_bias_events,
    causal_bias_now,
)

P = Params()


def daily_frame(n: int = 400, seed: int = 7, end_today: bool = False) -> pd.DataFrame:
    """A synthetic daily series with enough structure to produce BOS/CHoCH."""
    rng = np.random.default_rng(seed)
    # Trending segments so swings and breaks actually form; pure noise often
    # yields no events at all, which would make these tests vacuous.
    steps = np.concatenate([
        rng.normal(0.6, 1.0, n // 4), rng.normal(-0.6, 1.0, n // 4),
        rng.normal(0.4, 1.2, n // 4), rng.normal(-0.3, 1.0, n - 3 * (n // 4)),
    ])
    close = 100 + np.cumsum(steps)
    high = close + rng.uniform(0.2, 1.2, n)
    low = close - rng.uniform(0.2, 1.2, n)
    open_ = np.concatenate([[close[0]], close[:-1]])
    end = pd.Timestamp.now(tz="UTC").normalize()
    if not end_today:
        end = end - pd.Timedelta(days=1)
    idx = pd.date_range(end=end, periods=n, freq="D", tz="UTC")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close,
         "volume": np.full(n, 1000.0)},
        index=idx,
    )


# ---------------------------------------------------------------------------
# The parity property
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("seed", [1, 7, 13, 42, 99])
def test_live_bias_matches_the_backtest_timeline(seed):
    """The single value live computes must equal what the backtest timeline
    reports for the same moment. This is the whole point of the shared helper."""
    df = daily_frame(seed=seed)

    live = causal_bias_now(df, P.swing_length)
    timeline = _causal_daily_bias_events(df, P.swing_length)
    backtest = _bias_at(timeline, df.index[-1] + pd.Timedelta(days=1))

    assert live == backtest, (
        f"seed {seed}: live says {live}, the backtest timeline says {backtest} — "
        "the two engines have diverged again"
    )


def test_parity_holds_as_history_grows():
    """Walk forward: at every step the live answer must match the timeline.

    A single matching point could be luck. Divergence in the original bug was
    day-dependent — it appeared on flip days — so this checks many.
    """
    full = daily_frame(n=400, seed=5)
    mismatches = []
    for cutoff in range(200, len(full), 7):
        window = full.iloc[:cutoff]
        live = causal_bias_now(window, P.swing_length)
        backtest = _bias_at(
            _causal_daily_bias_events(window, P.swing_length),
            window.index[-1] + pd.Timedelta(days=1),
        )
        if live != backtest:
            mismatches.append((str(window.index[-1].date()), live, backtest))

    assert not mismatches, f"diverged at {len(mismatches)} point(s): {mismatches[:5]}"


# ---------------------------------------------------------------------------
# The two specific causes of the original divergence
# ---------------------------------------------------------------------------
def test_the_still_forming_daily_bar_is_ignored():
    """Today's daily candle has not closed. Acting on it means an intraday
    decision influenced by a day that has not finished — the same class of error
    the intraday flip-stamping fix exists to prevent.

    The entry frame was already truncated for this reason; the bias frame was
    not, which is half of why the two engines disagreed.
    """
    complete = daily_frame(n=300, seed=3, end_today=False)

    # Same history, plus a wild partial bar for today.
    partial = complete.copy()
    today = pd.Timestamp.now(tz="UTC").normalize()
    partial.loc[today] = {
        "open": 100.0, "high": 10_000.0, "low": 1.0, "close": 9_000.0, "volume": 1.0,
    }

    assert causal_bias_now(complete, P.swing_length) == causal_bias_now(partial, P.swing_length), (
        "a still-forming daily bar changed the bias — live would act on an "
        "incomplete candle while the backtest would not"
    )


def test_a_trailing_window_is_used_not_the_whole_series():
    """smc's broken_index depends on bars AFTER a break, so running it over an
    entire long series gives a different answer than the windowed recompute the
    backtest performs. Ancient history must not move today's bias."""
    recent = daily_frame(n=300, seed=11)

    # Prepend two years of unrelated history. Anything beyond the window must
    # not change the current answer.
    ancient = daily_frame(n=700, seed=77)
    ancient.index = pd.date_range(end=recent.index[0] - pd.Timedelta(days=1),
                                  periods=700, freq="D", tz="UTC")
    long_series = pd.concat([ancient, recent])

    assert causal_bias_now(recent, P.swing_length) == causal_bias_now(long_series, P.swing_length), (
        "history older than the trailing window changed today's bias"
    )


# ---------------------------------------------------------------------------
# Behaviour at the edges
# ---------------------------------------------------------------------------
def test_too_little_history_abstains():
    """Abstain rather than invent a direction — the engine's core principle."""
    assert causal_bias_now(daily_frame(n=5), P.swing_length) is None
    assert causal_bias_now(pd.DataFrame(), P.swing_length) is None
    assert causal_bias_now(None, P.swing_length) is None


def test_a_frame_of_only_todays_bar_abstains():
    """After dropping the partial bar nothing is left; it must not crash."""
    today = pd.Timestamp.now(tz="UTC").normalize()
    df = pd.DataFrame(
        {"open": [1.0], "high": [2.0], "low": [0.5], "close": [1.5], "volume": [1.0]},
        index=pd.DatetimeIndex([today], tz="UTC"),
    )
    assert causal_bias_now(df, P.swing_length) is None


def test_the_live_entry_brain_uses_the_shared_helper():
    """Guard the wiring itself: strategy_step must not go back to computing bias
    its own way. The parity tests above only protect the helper — this protects
    that the live path actually calls it."""
    import inspect

    from app.services.live import strategy_step

    src = inspect.getsource(strategy_step)
    assert "causal_bias_now" in src, "the live entry brain no longer uses the shared bias"
    assert "_daily_bias_events(" not in src, (
        "strategy_step is computing bias directly again — that is the divergence "
        "this task removed"
    )
