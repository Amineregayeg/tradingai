"""M9 Stage A — the contract engine runs on live bars and changes nothing.

The cutover is staged rather than done in one step because the two strategies have
never been compared on the same bars, and there is no way to compare them without
running both. Stage A is that: the rule layer evaluates every closed bar, emits a
schema-valid `setup_evaluation` with a real `deciding_rule_id`, and its verdict is
discarded.

THE TWO PROPERTIES THAT MATTER, AND THEY PULL IN OPPOSITE DIRECTIONS

  1. **It must produce a real contract record.** Anything less and the shadow
     window measures nothing — a record that would not validate is a record the
     conformance suite cannot read.
  2. **It must be incapable of affecting a trade.** A broken rule, a dead
     database or a malformed frame must cost an observation and nothing else.

The second is why every test below that breaks something asserts on what the
TRADING path did, not on what the shadow returned.

WHAT IT HONESTLY CANNOT DO, WHICH IS THE POINT OF RUNNING IT NOW
Without the correlate panels there is no alignment to grade, so every record is a
STAND_ASIDE citing the missing roster. That is not a stub — it is the correct
output, and the schema agrees: a TAKE additionally requires a stop ladder, a
target and entry criteria, none of which exists before M6. The value of Stage A on
day one is that the missing dependency becomes production evidence accumulating
hourly instead of a line in a planning document.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from app.services.live import shadow
from app.services.live.crypto_loop import LiveCryptoLoop
from app.services.telemetry import validate as val

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 8, 1, tzinfo=timezone.utc)


def frame(n: int = 200, seed: int = 7) -> pd.DataFrame:
    """A believable OHLC series. The point is shape, not realism — the detectors
    are tested against hand-built series elsewhere."""
    idx = pd.DatetimeIndex([T0 + timedelta(hours=i) for i in range(n)])
    rs = np.random.default_rng(seed)
    close = 60_000 + np.cumsum(rs.normal(0, 120, n))
    return pd.DataFrame(
        {
            "open": close,
            "high": close + rs.uniform(20, 200, n),
            "low": close - rs.uniform(20, 200, n),
            "close": close + rs.normal(0, 40, n),
            "volume": 1.0,
        },
        index=idx,
    )


def evaluate(tf: str = "5M", df: pd.DataFrame | None = None) -> dict | None:
    return shadow.evaluate(
        "BTCUSDT.P",
        frame() if df is None else df,
        signal_tf=tf,
        declared=shadow.declared_parameters(),
        sequence_no=1,
        scan_id="scan-test",
    )


# ---------------------------------------------------------------------------
# It produces a real contract record
# ---------------------------------------------------------------------------
async def test_the_record_validates_against_the_delivered_schema():
    """Against Salim's own schema, not our reading of it. A record that would not
    validate is one the conformance suite cannot read, which makes the whole
    shadow window unmeasurable."""
    record = evaluate()
    assert record is not None
    assert val.errors(record) == []


async def test_the_record_carries_a_real_deciding_rule_id():
    """The exit criterion for the entire cutover, and the thing that was
    impossible to produce before this module existed: a decision citing a rule id
    from the pinned registry."""
    from app.services.telemetry import contract_loader as contract

    record = evaluate()
    assert record["deciding_rule_id"] in contract.known_rule_ids()
    assert all(r["rule_id"] in contract.known_rule_ids() for r in record["rule_evaluations"])


async def test_every_rule_it_could_not_run_says_so_rather_than_passing():
    """C-04: silence is not a pass. A rule reported as PASS because nothing asked
    it is the single most dangerous record this system can write — it inflates
    coverage with rules that have never refused anything."""
    record = evaluate()
    blocked = {
        r["rule_id"]: r for r in record["rule_evaluations"]
        if r["verdict"] == "NOT_APPLICABLE"
    }
    assert set(shadow.BLOCKED_ON_CORRELATES) <= set(blocked)
    for rule_id in shadow.BLOCKED_ON_CORRELATES:
        assert blocked[rule_id]["values"]["not_evaluated_because"], (
            f"{rule_id} is not evaluated and does not say why"
        )
    assert not any(
        r["verdict"] == "PASS" for r in record["rule_evaluations"]
        if r["rule_id"] in shadow.BLOCKED_ON_CORRELATES
    )


async def test_it_never_claims_a_trade_it_cannot_substantiate():
    """A TAKE requires a stop ladder, a target and entry criteria — none of which
    exists before M6. Emitting one would be rejected by the validator, so this is
    a correctness property enforced twice over."""
    for seed in range(1, 12):
        record = evaluate(df=frame(seed=seed))
        assert record["decision"] == "STAND_ASIDE", (
            f"seed {seed}: claimed {record['decision']} with no graded box"
        )
        assert record["risk_assessment"]["risk_pct"] == 0.0


async def test_the_primitives_actually_ran():
    """A stand-aside that computed nothing would be indistinguishable from one
    that computed everything and found no alignment. The primitives are the
    evidence that the rule layer did real work on these bars."""
    record = evaluate()
    counts = {k: len(v) for k, v in record["primitives"].items()}
    assert counts["swing_points"] > 0 and counts["breaks"] > 0, counts


async def test_a_below_ruled_timeframe_is_flagged_and_a_ruled_one_is_not():
    """Malek's 1M second shadow run. GATE-018 flags rather than excludes it, and
    the flag is what keeps that run distinguishable from the 5M one afterwards."""
    assert evaluate(tf="1M")["flags"] == ["SIGNAL_TF_OUTSIDE_RULED_SET"]
    assert "flags" not in evaluate(tf="5M") or not evaluate(tf="5M").get("flags")


async def test_an_analysis_timeframe_is_not_softened_into_a_flag():
    """1H is a HARD_GATE violation under HG-12, not a deviation. Pre-labelling it
    as an acceptable flag would hide it from the assertion meant to catch it."""
    assert not evaluate(tf="1H").get("flags")


# ---------------------------------------------------------------------------
# It cannot affect a trade
# ---------------------------------------------------------------------------
async def test_a_broken_frame_costs_an_observation_and_nothing_else():
    """No high/low columns at all. The contract of this function is that the
    caller never has to care."""
    bad = pd.DataFrame({"nonsense": [1, 2, 3]})
    assert evaluate(df=bad) is None


async def test_a_rule_that_raises_does_not_escape():
    """The realistic failure once more rules are wired: one detector throws on an
    edge case and takes the trading loop down with it."""
    import app.services.rules.prim_002_imbalances as prim2

    original = prim2.ImbalanceInventory.detect

    def explode(*_a, **_k):
        raise RuntimeError("detector blew up")

    prim2.ImbalanceInventory.detect = staticmethod(explode)
    try:
        assert evaluate() is None
    finally:
        prim2.ImbalanceInventory.detect = original


async def test_a_dead_database_does_not_stop_the_engine_ticking():
    """`_shadow_evaluate` is called from the tick. If a telemetry write could
    raise, one unreachable database would stop the engine trading."""
    loop = LiveCryptoLoop()
    loop.run_id = None
    await loop._shadow_evaluate("BTC/USD", frame())   # no DB bound in this test


async def test_the_shadow_runs_before_the_ict_decision_in_the_tick():
    """Ordering is deliberate: if the shadow ever did have a side effect, it
    should show up as a disagreeing record rather than as a trade that quietly
    changed. A regression here is silent, so it is asserted on the source."""
    from pathlib import Path

    src = Path("app/services/live/crypto_loop.py").read_text(encoding="utf-8")
    assert src.index("_shadow_evaluate(pair, entry)") < src.index(
        "sig, trace = evaluate_latest_bar_traced"
    )


# ---------------------------------------------------------------------------
# The parameters are declared as ours
# ---------------------------------------------------------------------------
async def test_the_declared_parameters_are_stamped_on_every_record():
    """These are OUR choices, and the contract is explicit that a proxy must be
    labelled a proxy in both code and telemetry."""
    record = evaluate()
    declared = record["declared_parameters"]
    # v2 since 2026-08-14. v1 claimed "every closed bar" while the shadow sat below
    # the entry gates and never saw a blocked bar — false, and stamped on every record
    # (KNOWN_ISSUES B34). The name now describes what actually happens: gates no longer
    # suppress, insufficient history still does, and that residue is data-availability
    # rather than strategy state, so the sample stays unbiased with respect to market
    # conditions.
    assert declared["emission_policy_id"] == "every-closed-bar-with-sufficient-history-v2"
    assert declared["stop_selection_reading"] == "CLOSEST_TO_3R_TIES_TO_LARGER"


async def test_the_account_size_comes_from_the_engine_not_a_second_constant():
    """A record claiming a different account size from the one the engine sizes
    with would make every risk figure in the telemetry unauditable."""
    from app.services.live import fixed_config as fixed

    assert shadow.declared_parameters().virtual_account_size == fixed.STARTING_BALANCE


async def test_the_unquantified_quorum_is_left_undeclared():
    """K-13 asserts any quorum applied equals a DECLARED one. The source never
    quantifies "multiple", so an integer here would be hard-coded doctrine."""
    assert shadow.declared_parameters().reverse_quorum is None
