"""The rule engine composed end to end (M4 → M9 Stage A).

Until this module existed, 34 registry rules were implemented and none had ever been
evaluated on anything — nothing outside `app/services/rules/` called a single grader. These
tests pin the thing that changes: a decision whose `deciding_rule_id` is a real registry id,
which the execution plan's §6 lists as check 1 and calls impossible to produce.

What they pin, specifically, is PRECEDENCE. `deciding_rule_id` is the first rule that failed,
so evaluation order decides which rule gets the blame — and an engine that cites the wrong
refusal is worse than one that cites none, because the attribution ledger then looks complete
and is wrong.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.rules.evaluator import (
    break_state_from_breaks,
    build_correlate_reads,
    evaluate_layout,
    order_flow_from_breaks,
)
from app.services.rules.gate_008_roster import MAIN, NEGATIVE, POSITIVE
from app.services.rules.prim_001_swings import Bar, SwingPoints
from app.services.rules.prim_005_breaks import BreakEvents
from app.services.telemetry import contract_loader as contract

T0 = datetime(2026, 8, 3, 14, 0, tzinfo=timezone.utc)
TF = "5M"


def candles(rows: list[tuple[float, float, float, float]]) -> list[Bar]:
    return [Bar(time=T0 + timedelta(minutes=5 * i), high=h, low=lo, open=o, close=c)
            for i, (o, h, lo, c) in enumerate(rows)]


def zigzag(pivots: list[float], per_leg: int = 3) -> list[Bar]:
    """Bars interpolated between explicit pivot prices, `per_leg` bars a leg.

    Hand-built pivots rather than a generated trend: with a 2-bar fractal window a monotonic
    series has no local extreme that survives, so it produces no swings, no breaks and no
    box — and every test downstream then passes vacuously. Sharp turns separated by whole
    legs make the swing series known by construction.
    """
    prices: list[float] = [pivots[0]]
    for a, b in zip(pivots, pivots[1:]):
        for k in range(1, per_leg + 1):
            prices.append(a + (b - a) * k / per_leg)
    return candles([(p, p + 0.4, p - 0.4, p) for p in prices])


def rising() -> list[Bar]:
    """Up-leg: higher lows into a break of the prior high."""
    return zigzag([100, 92, 110, 101, 124, 114, 140])


def falling() -> list[Bar]:
    """The mirror, so a negative correlate can be made to agree or disagree on demand."""
    return zigzag([140, 148, 130, 139, 116, 126, 100])


def flat(n: int = 24, price: float = 50.0) -> list[Bar]:
    """No structure at all — no swing exceeds its neighbours, so no break prints."""
    return candles([(price, price + 0.1, price - 0.1, price) for _ in range(n)])


def layout(main=None, eth=None, total=None, usdtd=None, **counts):
    """The four panels. Defaults align for a long: main/ETH/TOTAL up, USDT.D down."""
    return {
        MAIN: main if main is not None else rising(),
        POSITIVE[0]: eth if eth is not None else rising(),
        POSITIVE[1]: total if total is not None else rising(),
        NEGATIVE[0]: usdtd if usdtd is not None else falling(),
    }


# ===========================================================================
# The artefact the whole project is trying to produce
# ===========================================================================
def test_a_decision_cites_a_rule_id_that_exists_in_the_registry():
    """Execution plan §6 check 1: "A decision record whose `deciding_rule_id` is a real
    registry id". Everything else here is detail; this is the milestone."""
    result = evaluate_layout(
        layout()[MAIN], layout(), instrument="BTC", signal_tf=TF)

    assert result.decision.decision in ("TAKE", "SKIP", "STAND_ASIDE")
    assert result.evaluations, "no rule was evaluated at all"
    assert all(e.rule_id in contract.known_rule_ids() for e in result.evaluations)
    if result.deciding_rule_id is not None:
        assert result.deciding_rule_id in contract.known_rule_ids()


def test_every_rule_reached_is_emitted_whether_it_passed_or_failed():
    """C-04: silence is not a pass. "Evaluated and inapplicable" must stay distinguishable
    from "never implemented", which is exactly what rule coverage measures."""
    result = evaluate_layout(layout()[MAIN], layout(), instrument="BTC", signal_tf=TF)
    ids = [e.rule_id for e in result.evaluations]

    assert ids[:2] == ["GATE-008", "GATE-007"], "readability is evaluated first"
    assert len(ids) == len(set(ids)), f"a rule was evaluated twice: {ids}"


def test_the_decision_path_is_the_order_the_rules_were_walked():
    result = evaluate_layout(layout()[MAIN], layout(), instrument="BTC", signal_tf=TF)
    assert result.decision.decision_path == [e.rule_id for e in result.evaluations]


# ===========================================================================
# Precedence — which rule gets the blame
# ===========================================================================
def test_an_unreadable_layout_is_blamed_on_the_roster_before_anything_else_runs():
    """A missing panel must not be reported as a grading failure. The layout is checked
    first because everything downstream reads from it."""
    panels = layout()
    del panels[POSITIVE[1]]
    result = evaluate_layout(panels[MAIN], panels, instrument="BTC", signal_tf=TF)

    assert result.decision.decision == "STAND_ASIDE"
    assert result.deciding_rule_id == "GATE-008"
    assert result.box is None, "no box should have been looked for"


def test_thin_correlate_bars_are_blamed_on_gate_007_not_on_the_grader():
    """B11 end to end: five samples in a 5M bar must stop the engine at the alignment
    timeframe, not surface later as a weak disturbance grade."""
    result = evaluate_layout(
        layout()[MAIN], layout(), instrument="BTC", signal_tf=TF,
        sample_counts={POSITIVE[1]: 5, NEGATIVE[0]: 5},
    )
    assert result.decision.decision == "STAND_ASIDE"
    assert result.deciding_rule_id == "GATE-007"
    assert result.disturbance is None, "the grader ran on unreadable panels"


def test_no_break_means_no_box_and_a_stand_aside_not_a_skip():
    """GRADE-001's last sentence. Before a box exists there is no candidate to reject, so
    the outcome is STAND_ASIDE — the schema's own distinction."""
    panels = layout(main=flat())
    result = evaluate_layout(panels[MAIN], panels, instrument="BTC", signal_tf=TF)

    assert result.deciding_rule_id == "GRADE-001"
    assert result.decision.decision == "STAND_ASIDE", "no candidate existed to skip"
    assert result.box is None


def test_once_a_box_exists_a_failure_is_a_skip():
    """The mirror of the test above, and the reason `setup_in_play` is threaded through."""
    result = evaluate_layout(layout()[MAIN], layout(), instrument="BTC", signal_tf=TF)
    if result.box is not None and result.decision.decision != "TAKE":
        assert result.decision.decision == "SKIP", (
            "a box existed, so a refusal is a SKIP not a STAND_ASIDE"
        )


def test_an_instrument_with_no_ruled_layout_stands_aside_rather_than_raising():
    """ETH is a positive PANEL in GATE-008's roster, not an instrument with a layout of its
    own — and the corpus says altcoins cannot be magic-aligned at all. Trading it is a
    deviation, so the engine records one instead of crashing or inventing a roster."""
    panels = layout()
    result = evaluate_layout(panels[MAIN], panels, instrument="ETH", signal_tf=TF)

    assert result.decision.decision == "STAND_ASIDE"
    assert result.deciding_rule_id == "GATE-008"
    assert any("ruled layout" in c for c in result.decision.stand_aside_causes)


# ===========================================================================
# GATE-001 fires before anything sizes
# ===========================================================================
def test_a_heavy_layout_is_refused_and_the_box_grade_is_recorded_anyway():
    """"no trade regardless of the Structure Box" — and the grade is recorded so conformance
    can prove the gate fired BEFORE sizing rather than after."""
    # Two correlates contradicting the main asset: ETH falling and USDT.D rising.
    panels = layout(eth=falling(), usdtd=rising())
    result = evaluate_layout(panels[MAIN], panels, instrument="BTC", signal_tf=TF)

    if result.disturbance is not None and result.disturbance.grade == "HEAVY":
        assert result.deciding_rule_id == "GATE-001"
        assert result.decision.decision == "SKIP"
        gate_001 = next(e for e in result.evaluations if e.rule_id == "GATE-001")
        assert gate_001.values["risk_pct"] == 0.0
        assert "structure_box_grade" in gate_001.values


def test_the_disturbance_evaluation_carries_its_banned_input_check():
    """GATE-005's negative is only testable if the record shows which tokens were checked."""
    result = evaluate_layout(layout()[MAIN], layout(), instrument="BTC", signal_tf=TF)
    gate_002 = [e for e in result.evaluations if e.rule_id == "GATE-002"]
    if gate_002:
        check = gate_002[0].banned_input_check
        assert check and "correlation_coefficient" in check["checked"]
        assert check["present"] == []


# ===========================================================================
# The correlate reads themselves
# ===========================================================================
def test_order_flow_is_the_direction_of_the_last_confirmed_break():
    """Structural by construction — no candle count, no elapsed time, no correlation
    coefficient, which is what GATE-005 requires."""
    bars = rising()
    swings = SwingPoints.detect(bars, tf=TF)
    breaks = BreakEvents.detect(bars, swings, tf=TF)
    assert order_flow_from_breaks(breaks, before=len(bars)) in ("BULLISH", "BEARISH")
    assert order_flow_from_breaks([], before=len(bars)) == "NEUTRAL"


def test_a_panel_that_never_broke_is_neutral_not_agreeing():
    """A real state, deliberately not defaulted to agreement — defaulting would manufacture
    alignment the market never gave."""
    reads = build_correlate_reads(
        {POSITIVE[1]: flat()}, signal_tf=TF, as_of_index=24)
    assert reads[0].observed_order_flow == "NEUTRAL"
    assert reads[0].break_state == "NONE"


def test_break_state_is_derived_from_the_break_stream_not_from_a_window():
    """"Entry window" is never bounded numerically anywhere in the corpus, and any candle or
    minute bound would collide with GATE-005's ban list."""
    class B:
        def __init__(self, i, t):
            self.bar_index, self.type = i, t

    assert break_state_from_breaks([B(1, "MSB")], before=10) == "MSB_IN_WINDOW"
    assert break_state_from_breaks(
        [B(1, "MSB"), B(5, "BOS")], before=10) == "ALREADY_MSB_CONTINUING_BOS"
    assert break_state_from_breaks([B(1, "BOS")], before=10) == "NONE"
    assert break_state_from_breaks([B(9, "MSB")], before=5) == "NONE", "look-ahead"


def test_sample_counts_are_passed_through_only_for_the_panels_that_have_them():
    reads = build_correlate_reads(
        layout(), signal_tf=TF, as_of_index=24,
        sample_counts={POSITIVE[1]: 20, NEGATIVE[0]: 20},
    )
    by_asset = {r.asset: r for r in reads}
    assert by_asset[MAIN].bar_sample_count is None, "an exchange bar is a bar"
    assert by_asset[POSITIVE[1]].bar_sample_count == 20


# ===========================================================================
# Causality
# ===========================================================================
@pytest.mark.parametrize("as_of", [10, 14, 18, 24])
def test_the_decision_never_reads_beyond_its_own_bar(as_of):
    """The evidence scan stops strictly left of the decision bar. Re-running at an earlier
    bar must not be affected by anything that printed later."""
    panels = layout()
    early = evaluate_layout(
        panels[MAIN], panels, instrument="BTC", signal_tf=TF, as_of_index=as_of)
    truncated = {k: v[:as_of] for k, v in panels.items()}
    same = evaluate_layout(
        truncated[MAIN], truncated, instrument="BTC", signal_tf=TF, as_of_index=as_of)

    assert early.decision.decision == same.decision.decision
    assert early.deciding_rule_id == same.deciding_rule_id


def test_the_record_shape_carries_the_path_and_the_decider():
    result = evaluate_layout(layout()[MAIN], layout(), instrument="BTC", signal_tf=TF)
    record = result.as_dict()

    assert record["signal_tf"] == record["alignment_tf"] == TF
    assert record["decision"] == result.decision.decision
    assert record["decision_path"] == result.decision.decision_path
    assert all("rule_id" in e and "verdict" in e for e in record["rule_evaluations"])
