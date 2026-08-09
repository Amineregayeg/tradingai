"""The engine must record WHY, not just what (task 2.3).

Before this, the engine reported "no valid setup" and discarded the reasoning.
That single phrase covers two opposite situations — a strategy correctly
declining a poor setup, and a detector that never fires at all — and telling
them apart is precisely what a simulation is for.

`DecisionRecord` has carried `abstained`, `reasons` and an ABSTAINED outcome
since it was written; its own docstring says a row is created "whether it
produced a signal or abstained". Nothing ever wrote one. These tests pin that
the reasoning is now captured and persisted.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services.backtest.engine import Params
from app.services.live.decision_trace import DecisionTrace
from app.services.live.strategy_step import (
    evaluate_latest_bar,
    evaluate_latest_bar_traced,
)

P = Params()


def bars(n: int = 200, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1.0, n))
    high = close + rng.uniform(0.1, 0.9, n)
    low = close - rng.uniform(0.1, 0.9, n)
    idx = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("h"), periods=n, freq="h", tz="UTC")
    return pd.DataFrame(
        {"open": np.concatenate([[close[0]], close[:-1]]),
         "high": high, "low": low, "close": close, "volume": np.full(n, 100.0)},
        index=idx,
    )


def daily(n: int = 200, seed: int = 4) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    steps = np.concatenate([rng.normal(0.5, 1.0, n // 2), rng.normal(-0.5, 1.0, n - n // 2)])
    close = 100 + np.cumsum(steps)
    idx = pd.date_range(end=pd.Timestamp.now(tz="UTC").normalize() - pd.Timedelta(days=1),
                        periods=n, freq="D", tz="UTC")
    return pd.DataFrame(
        {"open": np.concatenate([[close[0]], close[:-1]]),
         "high": close + rng.uniform(0.2, 1.0, n),
         "low": close - rng.uniform(0.2, 1.0, n),
         "close": close, "volume": np.full(n, 1000.0)},
        index=idx,
    )


# ---------------------------------------------------------------------------
# Every decision is explained
# ---------------------------------------------------------------------------
def test_a_refusal_always_carries_a_reason():
    """The core property. An abstention with no explanation is the thing this
    task removed."""
    sig, trace = evaluate_latest_bar_traced("BTC/USD", bars(), daily())

    assert trace.gates, "no gates were recorded at all"
    assert trace.summary, "a decision was made with no human-readable summary"
    assert trace.reasons, "nothing was recorded for DecisionRecord.reasons"
    if sig is None:
        assert trace.took_trade is False


def test_insufficient_history_says_how_much_was_missing():
    """'Not enough data' is useless without the numbers — 59 bars of 65 is a
    different problem from 3 of 65."""
    sig, trace = evaluate_latest_bar_traced("BTC/USD", bars(n=10), daily())

    assert sig is None
    assert trace.blocked_by == "history"
    g = trace.gates[0]
    assert g.values["have"] == 10
    assert g.values["required"] >= 60
    assert "10 bars available" in g.detail


def test_missing_daily_bias_is_reported_as_such():
    """Distinguish 'no direction yet' from 'a setup was rejected' — they call
    for completely different responses."""
    sig, trace = evaluate_latest_bar_traced("BTC/USD", bars(), daily(n=8))

    assert sig is None
    assert trace.blocked_by == "daily_bias"
    assert "no daily bias" in trace.summary


def test_passed_gates_are_recorded_not_only_failures():
    """A record of only failures cannot tell you whether the rest were even
    evaluated — the same 'no findings vs nothing checked' ambiguity the
    reconciliation and data-health surfaces avoid."""
    _sig, trace = evaluate_latest_bar_traced("BTC/USD", bars(), daily())

    names = [g.name for g in trace.gates]
    assert "history" in names
    assert any(g.passed for g in trace.gates), "no gate was recorded as passing"
    assert any(r.startswith("PASS ") for r in trace.reasons)


# ---------------------------------------------------------------------------
# Candidate-level detail: the part that answers "is it running the strategy?"
# ---------------------------------------------------------------------------
def test_rejected_candidates_record_the_values_compared():
    """'Rejected by the ATR filter' is an assertion; 'gap 41.2 vs required 58.0'
    is something you can check."""
    seen = []
    for seed in range(1, 25):
        _sig, trace = evaluate_latest_bar_traced("BTC/USD", bars(seed=seed), daily(seed=seed))
        seen.extend(c for c in trace.candidates if not c["accepted"])
    if not seen:
        pytest.skip("no candidates rejected across the sampled seeds")

    for c in seen[:10]:
        assert c["reason"], "a candidate was rejected with no reason"
        assert isinstance(c["values"], dict)
        assert c["direction"] in ("LONG", "SHORT")


def test_summary_distinguishes_no_candidates_from_all_rejected():
    """These look identical as 'no valid setup' and mean opposite things: the
    detector found nothing, versus it found setups the strategy declined."""
    empty = DecisionTrace(symbol="BTC/USD", timeframe="1H")
    empty.gate("history", True, "ok")
    assert "no FVG candidates" in empty.summary

    rejected = DecisionTrace(symbol="BTC/USD", timeframe="1H")
    rejected.gate("history", True, "ok")
    rejected.candidate(0, "LONG", False, "price never retraced into the gap")
    rejected.candidate(1, "LONG", False, "price never retraced into the gap")
    assert "2 FVG candidate(s), none valid" in rejected.summary
    assert "price never retraced" in rejected.summary


def test_a_taken_trade_is_marked_and_explained():
    t = DecisionTrace(symbol="BTC/USD", timeframe="1H")
    t.gate("history", True, "ok")
    t.candidate(0, "LONG", True, "all conditions met", entry=62000.0, stop=61000.0)
    t.took_trade = True
    assert t.summary == "entry taken"
    assert t.blocked_by is None


# ---------------------------------------------------------------------------
# The wrapper must not change behaviour
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("seed", [1, 5, 11, 23])
def test_tracing_does_not_change_the_decision(seed):
    """Instrumentation that alters the outcome is worse than none: every past
    result would be measured against a different strategy."""
    e, d = bars(seed=seed), daily(seed=seed)
    plain = evaluate_latest_bar("BTC/USD", e, d)
    traced, _ = evaluate_latest_bar_traced("BTC/USD", e, d)

    if plain is None:
        assert traced is None
    else:
        assert traced is not None
        assert (plain.direction, plain.entry, plain.sl) == (traced.direction, traced.entry, traced.sl)


def test_trace_serialises_for_storage_and_ui():
    _sig, trace = evaluate_latest_bar_traced("BTC/USD", bars(), daily())
    d = trace.as_dict()
    assert d["symbol"] == "BTC/USD"
    assert isinstance(d["gates"], list) and isinstance(d["candidates"], list)
    assert isinstance(d["summary"], str)
    import json
    json.dumps(d)  # must survive JSON storage
    assert all(isinstance(r, str) for r in trace.reasons)


def test_a_decision_with_no_candidates_still_states_that_in_the_RECORD():
    """KNOWN_ISSUES B10. `summary` already said "no FVG candidates in range", but
    `reasons` is what gets persisted, and it used to omit the census line entirely
    when the candidate list was empty — so the stored row ended after the last
    PASS and read as truncated. Five of the 137 declines in run 7d788ad6 were
    exactly that: a decision that declined and did not say why.

    "0 considered" is a finding. Silence is the "nothing found vs never checked"
    ambiguity that the gates above are listed pass-or-fail to avoid.
    """
    from app.services.live.decision_trace import DecisionTrace

    trace = DecisionTrace(symbol="BTC/USD", timeframe="1H")
    trace.gate("history", True, "324 bars available, 60 required")
    trace.gate("daily_bias", True, "daily bias is LONG")
    trace.gate("ltf_bos", True, "lower-timeframe break is LONG, needs to match bias LONG")

    reasons = trace.reasons
    assert any("candidates: 0 considered" in r for r in reasons), (
        f"a decision that reached scoring and found nothing said nothing: {reasons}"
    )


def test_a_decision_stopped_by_a_gate_does_not_claim_it_considered_zero():
    """The opposite error. A run blocked at ltf_bos never reached the candidate
    stage, and "0 considered" would report that it looked and found nothing —
    a different falsehood from the one B10 fixed."""
    from app.services.live.decision_trace import DecisionTrace

    trace = DecisionTrace(symbol="BTC/USD", timeframe="1H")
    trace.gate("history", True, "324 bars available, 60 required")
    trace.gate("daily_bias", True, "daily bias is SHORT")
    trace.gate("ltf_bos", False, "lower-timeframe break is LONG, needs to match bias SHORT")

    assert not any("considered" in r for r in trace.reasons)
    assert trace.blocked_by == "ltf_bos"
