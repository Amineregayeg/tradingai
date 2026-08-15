"""T-0019 — the entry decision: ENTRY-001, GATE-037, GATE-038.

Two of the three rules are PROHIBITIONS, and a prohibition is satisfied by a check that never
fires. So each negative is mutated in BOTH directions: the thing it forbids must fail, and the
thing it explicitly permits must pass. A one-directional test on a negative gate proves only
that the gate is quiet.

T-0020 LANDED ON 2026-08-15 AND THE PROHIBITION THIS PARAGRAPH CARRIED IS DISCHARGED. It
read: no criterion here may assert what PRIM-002 will classify a band as, because the
promotion had no time bound, the share grew with the caller's lookback, and the shadow (320
bars) and the backtest (250) would disagree about the same setup.

The scan is now causal, direction-constrained and bounded by a declared lookback, and every
band the 250-bar and 999-bar windows both see is classified identically. So the ordering IS
now asserted over detected bars — `test_the_precedence_ordering_holds_over_detected_bars`,
at the bottom of this file, is the assertion the three deferrals were waiting for.

The ranking tests above still use an EXPLICIT candidate list, and that stays: a ranking rule
should be tested on ranking. The difference is that it is now a choice rather than a
restriction.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.rules import (
    AmplifierLevel,
    AmplifiersNeverCreateATrade,
    Block,
    Imbalance,
    ImbalanceIsTheOnlyEntryPOI,
    NoPremiumDiscountOrOTEFilter,
)
from app.services.rules.gate_038_amplifiers import DECLARED_COLLISION_WINDOW, colliding

T0 = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)


def _imb(imb_id: str, kind: str, low: float, high: float, idx: int = 0) -> Imbalance:
    return Imbalance(
        id=imb_id, tf="5m", bar_time=T0, price_high=high, price_low=low,
        type=kind, direction="BULLISH", formed_index=idx,
    )


# ---------------------------------------------------------------------------------------
# ENTRY-001 — criterion 1: an OB or BB must NEVER be an entry POI
# ---------------------------------------------------------------------------------------


def test_an_order_block_alone_produces_NO_entry_poi():
    """THE MUTATION DIRECTION THAT MATTERS. Not a downgraded POI — none at all.

    A version that ranks OB/BB *below* imbalances satisfies the word "precedence" and
    violates the rule: with no imbalance present, the best-ranked candidate is then the
    order block and a trade is taken on it. The statement is a prohibition.
    """
    blocks = [Block("ORDER_BLOCK", price_high=101.0, price_low=99.0, id="ob-1")]
    ev = ImbalanceIsTheOnlyEntryPOI.evaluate([], blocks, at_price=100.0)

    assert ev.values["entry_poi"] is None
    assert ev.verdict == "FAIL"
    # And the refusal is VISIBLE: "no POI" must not read the same whether the location was
    # empty or held a block the rule correctly declined.
    assert ev.values["blocks_at_location_not_eligible"], (
        "a refused block is invisible, so an audit cannot tell an empty location from a "
        "correctly-refused one"
    )


def test_a_breaker_block_alone_also_produces_NO_entry_poi():
    blocks = [Block("BREAKER_BLOCK", price_high=101.0, price_low=99.0, id="bb-1")]
    assert ImbalanceIsTheOnlyEntryPOI.select([], blocks, at_price=100.0) is None


def test_adding_an_imbalance_at_the_same_location_produces_the_poi_with_the_block_as_evidence():
    """The other direction: the block becomes UPGRADE EVIDENCE, never the trigger."""
    blocks = [Block("ORDER_BLOCK", price_high=101.0, price_low=99.0, id="ob-1")]
    poi = ImbalanceIsTheOnlyEntryPOI.select(
        [_imb("fvg-1", "FVG", 99.5, 100.5)], blocks, at_price=100.0
    )

    assert poi is not None
    assert poi.type == "FVG", "the imbalance is the trigger"
    assert [b.id for b in poi.colliding_blocks] == ["ob-1"], "the block is evidence"


def test_a_block_that_does_not_overlap_the_poi_is_not_recorded_as_colliding():
    blocks = [Block("ORDER_BLOCK", price_high=90.0, price_low=89.0, id="far")]
    poi = ImbalanceIsTheOnlyEntryPOI.select(
        [_imb("fvg-1", "FVG", 99.5, 100.5)], blocks, at_price=100.0
    )
    assert poi is not None and poi.colliding_blocks == []


def test_the_precedence_order_is_deterministic_over_an_explicit_candidate_list():
    """The ranking, tested with NO lookback in the fixture.

    This asserts what ENTRY-001 does with candidates it is GIVEN, which is the right scope
    for a ranking rule. It does not assert what PRIM-002 classifies a band as over real
    bars — that is now stable (T-0020, 2026-08-15) and is asserted separately by
    `test_the_precedence_ordering_holds_over_detected_bars`, so the two properties stay
    testable independently rather than one hiding a regression in the other.
    """
    candidates = [
        _imb("plain", "FVG", 99.0, 101.0, idx=0),
        _imb("bpr", "BPR", 99.0, 101.0, idx=1),
        _imb("super", "SUPER_BPR", 99.0, 101.0, idx=2),
    ]
    poi = ImbalanceIsTheOnlyEntryPOI.select(candidates, at_price=100.0)
    assert poi is not None and poi.type == "SUPER_BPR" and poi.sub_rank == 1

    without_super = ImbalanceIsTheOnlyEntryPOI.select(candidates[:2], at_price=100.0)
    assert without_super is not None and without_super.type == "BPR"


def test_every_ranked_type_is_also_admissible():
    """A type that gained a rank but not admissibility would be silently unenterable."""
    from app.services.rules.entry_001_imbalance_poi import ADMISSIBLE_TYPES, SUB_RANK

    assert set(SUB_RANK) == set(ADMISSIBLE_TYPES)


def test_fill_state_is_recorded_and_not_filtered_on():
    """Excluding filled imbalances would be an invented rule wearing this rule's id.

    The registry names fill state as an input and makes no admissibility claim about it, so
    the number travels on the record and a later ruling can be applied to stored history.
    """
    filled = _imb("filled", "FVG", 99.5, 100.5)
    filled.fill_state = "FULLY_FILLED"
    filled.fill_fraction = 1.0

    poi = ImbalanceIsTheOnlyEntryPOI.select([filled], at_price=100.0)
    assert poi is not None, "a fill-state filter was invented"
    assert poi.as_dict()["fill_state"] == "FULLY_FILLED"
    assert poi.as_dict()["fill_fraction"] == 1.0


# ---------------------------------------------------------------------------------------
# GATE-037 — criteria 4, 5, 6: recorded-but-not-deciding vs. absent
# ---------------------------------------------------------------------------------------


def test_an_OTE_value_that_is_only_RECORDED_passes():
    """CRITERION 5, direction one — and this is the direction a strict check gets wrong.

    The statement explicitly permits the geometry to be recorded as reading vocabulary. A
    check failing on mere presence would forbid exactly what the rule protects, while
    looking stricter than the correct one.
    """
    record = {
        "primitives": {"ranges": {"ote_zone": [0.62, 0.79], "equilibrium": 100.0}},
        "decision": {"verdict": "TAKE", "reason": "imbalance at POI"},
    }
    ev = NoPremiumDiscountOrOTEFilter.evaluate(record)

    assert ev.verdict == "PASS"
    assert ev.values["violations"] == []
    assert ev.values["recorded_but_not_deciding"], (
        "the permitted half must be REPORTED, or a PASS cannot distinguish 'recorded and "
        "correctly ignored' from 'never computed'"
    )


def test_the_same_value_routed_into_an_accept_reject_path_FAILS():
    """CRITERION 5, direction two. Same token, different location, opposite verdict."""
    record = {
        "primitives": {"ranges": {"ote_zone": [0.62, 0.79]}},
        "decision": {"verdict": "SKIP", "reason": "price not in discount zone"},
    }
    ev = NoPremiumDiscountOrOTEFilter.evaluate(record)

    assert ev.verdict == "FAIL"
    assert ev.values["violations"], ev.values
    assert "discount" in ev.values["banned_input_check"]["present"]


@pytest.mark.parametrize(
    "token", ["premium", "discount", "equilibrium", "ote", "optimal_trade_entry", "eq_level"]
)
def test_every_named_token_is_actually_caught(token):
    """CRITERION 6. Three vocabularies for one concept; two of three passing is a hole.

    Parameterised over the rule's OWN declared list, so a token added to `BANNED_TOKENS`
    without a working pattern fails here rather than being reported as checked.
    """
    ev = NoPremiumDiscountOrOTEFilter.evaluate({"decision": {token: True}})
    assert ev.verdict == "FAIL", f"{token} is listed as checked and is not caught"
    assert token in ev.values["banned_input_check"]["present"]


def test_the_checked_token_list_travels_on_every_record():
    """CRITERION 6: what was checked is stated, not implied — B33's shape."""
    ev = NoPremiumDiscountOrOTEFilter.evaluate({})
    checked = ev.values["banned_input_check"]["checked"]
    for vocabulary in ("premium", "discount", "equilibrium", "ote"):
        assert vocabulary in checked


@pytest.mark.parametrize("innocent", ["quote", "note", "requote", "discounted_cash"])
def test_the_matcher_does_not_fire_on_words_that_merely_contain_a_token(innocent):
    """`ote` must not fire on `quote` or `note`, or the rule cries wolf and gets disabled."""
    ev = NoPremiumDiscountOrOTEFilter.evaluate({"decision": {innocent: 1}})
    if innocent == "discounted_cash":
        # `discount` IS present as a word here; this documents where the boundary sits
        # rather than pretending the matcher is cleverer than it is.
        assert ev.verdict == "PASS"
    else:
        assert ev.verdict == "PASS", f"{innocent} was matched as a banned token"


def test_every_named_decision_path_is_a_REAL_record_section():
    """A named path that cannot match is indistinguishable from a path that is clean.

    An earlier version of this rule named `gates`, which exists in neither TELEMETRY_SCHEMA
    nor the model — so the check advertised four sections and could only ever scan three,
    silently. Found by the Manager before it landed. This pins the replacement against the
    live vocabulary rather than against a memory of it.
    """
    import json
    from pathlib import Path

    import app.models.telemetry_record as tr_model
    from app.services.telemetry import contract_loader

    def _keys(node, out):
        """Every KEY in the schema — not a substring of its prose.

        The first version of this test did `path in schema_text` and PASSED when `gates`
        was reinstated, because the schema contains the sentence "an engine that fails
        several gates may cite whichever one it prefers". A guard against a phantom path
        that matches on prose is itself a phantom guard, so it is keys or nothing.
        """
        if isinstance(node, dict):
            for k, v in node.items():
                out.add(k)
                _keys(v, out)
        elif isinstance(node, list):
            for v in node:
                _keys(v, out)
        return out

    schema_keys = _keys(json.loads(Path(contract_loader.SCHEMA_PATH).read_text("utf-8")), set())
    columns = {
        c.name for c in tr_model.TelemetryRecord.__table__.columns  # type: ignore[attr-defined]
    }
    assert "decision" in columns, "the model changed shape — re-derive this test's source"
    assert "gates" not in schema_keys | columns, (
        "the phantom path this test exists to exclude has become real — re-read the schema"
    )
    for path in NoPremiumDiscountOrOTEFilter.DECISION_PATHS:
        assert path in columns or path in schema_keys, (
            f"{path!r} is named as a decision path and is neither a TelemetryRecord column "
            "nor a key in TELEMETRY_SCHEMA — it can never match, and a path that cannot "
            "match is indistinguishable from a path that is clean"
        )


def test_a_named_path_absent_from_a_record_is_reported_not_counted_as_clean():
    """The denominator discipline, applied to path names."""
    ev = NoPremiumDiscountOrOTEFilter.evaluate({"decision": {"verdict": "TAKE"}})
    assert ev.values["decision_paths_scanned"] == ["decision"]
    assert "rule_evaluations" in ev.values["decision_paths_not_present"]
    assert ev.values["decision_path_coverage"] == "1 of 4 named"


def test_an_empty_record_reports_its_own_emptiness():
    """A PASS about nothing must not read as a clean audit of a real decision."""
    ev = NoPremiumDiscountOrOTEFilter.evaluate({})
    assert ev.verdict == "PASS"
    assert ev.values["paths_examined"] == 0


# ---------------------------------------------------------------------------------------
# GATE-038 — criteria 7 and 8: an amplifier cannot create a trade
# ---------------------------------------------------------------------------------------


def test_amplifiers_with_no_valid_setup_produce_no_entry():
    """CRITERION 7. The mutation direction, and the violating implementation is one token.

    A version that adds amplifier weight to a score that gates entry passes every other
    criterion in this file and violates this one.
    """
    levels = [AmplifierLevel("ROUND_NUMBER", 100.0), AmplifierLevel("SR_FLIP", 100.1)]
    ev = AmplifiersNeverCreateATrade.evaluate(levels, entry_price=100.0, setup_valid=False)

    assert ev.verdict == "FAIL", "amplifiers created a trade"
    assert ev.values["amplifier_count"] == 2, "the count is still computed and reported"
    assert ev.values["decides_entry"] is False


def test_a_valid_setup_with_no_amplifiers_produces_an_entry_with_count_zero():
    ev = AmplifiersNeverCreateATrade.evaluate([], entry_price=100.0, setup_valid=True)
    assert ev.verdict == "PASS"
    assert ev.values["amplifier_count"] == 0


def test_the_verdict_is_identical_with_and_without_amplifiers():
    """The prohibition stated as an invariance, which is what 'must not influence' means."""
    levels = [AmplifierLevel("ROUND_NUMBER", 100.0)] * 5
    for valid in (True, False):
        bare = AmplifiersNeverCreateATrade.evaluate([], entry_price=100.0, setup_valid=valid)
        loud = AmplifiersNeverCreateATrade.evaluate(
            levels, entry_price=100.0, setup_valid=valid
        )
        assert bare.verdict == loud.verdict, (
            f"amplifiers changed the verdict when setup_valid={valid}"
        )


def test_the_statements_own_worked_example_is_the_boundary_check():
    """CRITERION 8. "entry POI at 100.00 -> any amplifier between 99.80 and 100.20".

    BOTH EDGES ARE INCLUSIVE AND A NAIVE COMPARISON REJECTS BOTH OF THEM. They land on the
    same delta — 0.20000000000000284 against a half of exactly 0.2 — so `<=` excludes the
    two prices the statement names as colliding. Symmetric, and therefore not a bias: the
    rule simply refuses its own documented example. Two of the three natural arithmetics do
    (B59), which is why this test asserts the quoted numbers rather than convenient ones.
    """
    inside = [AmplifierLevel("ROUND_NUMBER", p) for p in (99.80, 100.00, 100.20)]
    outside = [AmplifierLevel("ROUND_NUMBER", p) for p in (99.79, 100.21)]

    assert len(colliding(inside, entry_price=100.0)) == 3, "the statement's own edges"
    assert colliding(outside, entry_price=100.0) == []


def test_the_window_is_declared_and_unratified_on_every_record():
    """CRITERION 8: 'approximately' plus a worked example is not a ruling."""
    ev = AmplifiersNeverCreateATrade.evaluate([], entry_price=100.0, setup_valid=True)
    assert ev.values["amplifier_window_pct"] == 0.2
    assert ev.values["amplifier_window_pct_ratified"] is False
    assert "engineering guideline" in ev.values["amplifier_window_pct_source"]


def test_the_firing_rate_is_reported_with_its_denominator():
    """B46: a corridor catching everything and one catching nothing look the same."""
    levels = [AmplifierLevel("ROUND_NUMBER", p) for p in (100.0, 100.1, 500.0, 900.0)]
    ev = AmplifiersNeverCreateATrade.evaluate(levels, entry_price=100.0, setup_valid=True)
    assert ev.values["amplifier_levels_examined"] == 4
    assert ev.values["amplifier_rate"] == 0.5


def test_the_declared_window_is_not_a_bare_literal_in_the_comparison():
    """Passing a different declared window must move the boundary, or the constant is inert."""
    from app.services.rules.gate_038_amplifiers import DeclaredWindow

    wide = DeclaredWindow(name="amplifier_window_pct", pct=1.0, source="test")
    level = [AmplifierLevel("ROUND_NUMBER", 100.5)]
    assert colliding(level, entry_price=100.0) == []
    assert len(colliding(level, entry_price=100.0, window=wide)) == 1


# ---------------------------------------------------------------------------------------
# STEP 0 item 3 — GAP: answered BY CONSTRUCTION, because a corpus count cannot answer it
# ---------------------------------------------------------------------------------------


def test_the_GAP_type_is_REACHABLE_and_the_zero_count_is_a_market_fact():
    """0 of 1070 live 5m bars produced a GAP. This says whether that means BROKEN or RARE.

    A corpus count can only ever say "not seen yet" — the absent-versus-empty collapse this
    register opens with. A hand-built fixture answers it outright: bodies apart AND wicks
    apart is the documented discriminator ("gaps and volume imbalances are the same thing,
    the only difference is the wicks"), so constructing exactly that either produces a GAP
    or proves the type unreachable.

    IT PRODUCES ONE. So the type is live and the zero count is a property of a 24/7 crypto
    perpetual, which has no session gaps — not a dead branch. No detector needs building,
    which is what the plan put out of scope on the assumption this test would come back
    either way.
    """
    from datetime import timedelta

    from app.services.rules import Bar, ImbalanceInventory

    def _bar(i: int, o: float, h: float, low: float, c: float) -> Bar:
        return Bar(time=T0 + timedelta(minutes=5 * i), high=h, low=low, open=o, close=c)

    # prev: body 98..99, wick high 100.   cur: body 106..107, wick low 105.
    # Bodies apart AND wicks apart -> GAP, not VOLUME_IMBALANCE.
    bars = [_bar(0, 98, 100, 97, 99), _bar(1, 106, 108, 105, 107)]
    found = ImbalanceInventory.detect(bars, tf="5m")

    gaps = [f for f in found if f.type == "GAP"]
    assert gaps, "GAP is unreachable by construction — the discriminator is broken"
    assert (gaps[0].price_low, gaps[0].price_high) == (100, 105), (
        "the band must be the void between the WICKS, not between the bodies"
    )


def test_wicks_that_overlap_give_a_VOLUME_IMBALANCE_and_not_a_GAP():
    """The other side of the one-line discriminator, so the test above is not vacuous."""
    from datetime import timedelta

    from app.services.rules import Bar, ImbalanceInventory

    def _bar(i: int, o: float, h: float, low: float, c: float) -> Bar:
        return Bar(time=T0 + timedelta(minutes=5 * i), high=h, low=low, open=o, close=c)

    # Same bodies, but the wicks now overlap (cur low 99 < prev high 100).
    bars = [_bar(0, 98, 100, 97, 99), _bar(1, 106, 108, 99, 107)]
    found = ImbalanceInventory.detect(bars, tf="5m")

    assert [f.type for f in found if f.type in ("GAP", "VOLUME_IMBALANCE")] == [
        "VOLUME_IMBALANCE"
    ]


# ---------------------------------------------------------------------------------------
# Criterion 9 — registered, canonical, and counted
# ---------------------------------------------------------------------------------------


def test_all_three_are_registered_under_canonical_ids():
    from app.services.rules import implementations
    from app.services.telemetry import contract_loader as contract

    impls = implementations()
    for rid in ("ENTRY-001", "GATE-037", "GATE-038"):
        assert rid in impls, f"{rid} did not register"
        assert contract.alias_target(rid) is None, f"{rid} is an alias id"


def test_none_of_the_three_declares_itself_unable_to_fire():
    """All inputs resolve to producers that exist — so none carries CANNOT_FIRE_WITHOUT.

    Asserted rather than assumed: a rule that quietly gained a blocker would drop out of
    effective coverage while the implemented count still rose.
    """
    from app.services.rules import implementations

    for rid in ("ENTRY-001", "GATE-037", "GATE-038"):
        assert not getattr(implementations()[rid], "CANNOT_FIRE_WITHOUT", ()), rid


def test_every_emitted_field_carries_provenance():
    """T-0016's check enforces this registry-wide; this fails closer to the edit."""
    for ev in (
        ImbalanceIsTheOnlyEntryPOI.evaluate(),
        NoPremiumDiscountOrOTEFilter.evaluate(),
        AmplifiersNeverCreateATrade.evaluate(),
    ):
        missing = set(ev.values) - set(ev.value_provenance)
        assert not missing, f"{ev.rule_id} emits {sorted(missing)} with no provenance"


# ---------------------------------------------------------------------------
# T-0020 criterion 9a — THE ASSERTION THREE DEFERRALS WERE WAITING FOR
# ---------------------------------------------------------------------------
def test_the_precedence_ordering_holds_over_detected_bars():
    """`super BPR > BPR > plain imbalance`, over REAL bars rather than a handed list.

    WHY THIS IS A SEPARATE TEST AND WHY IT COULD NOT BE WRITTEN UNTIL NOW. Three places —
    this file's header, `entry_001_imbalance_poi.py`'s docstring, and PRIM-002's — carried
    the same prohibition: no rule may assert an expected outcome of the precedence ordering
    over detected bars, because the same band classified differently depending on how much
    history the caller passed. Discharging those sentences without writing this test would
    have deleted the debt rather than paid it.

    Every test above hands ENTRY-001 an explicit candidate list, so it proves the RANKING
    is correct given inputs and proves nothing about the inputs. This one runs PRIM-002
    over the committed 999-bar corpus and ranks what it actually finds — which is the
    composition the live engine sees.

    AND WHAT THIS TEST DOES NOT DO, MEASURED RATHER THAN ASSUMED. Removing T-0020's
    lookback bound — reinstating the defect this test was gated on — leaves it GREEN. At
    250 and 320 bars the strongest type present is the same either way, so the chosen POI
    does not move and the agreement assertion below is satisfied by the broken code too.

    So this is not the test that catches the defect. `test_t0020_super_bpr_stability.py
    ::test_the_two_live_callers_never_disagree` is, and dropping the bound turns it red.
    What this one adds is the property nothing else covers: that ENTRY-001 applies its
    precedence order to REAL PRIM-002 output rather than only to lists a test handed it.
    Both are worth having; only one of them discriminates, and saying which is the point.
    """
    import csv
    from pathlib import Path

    from app.services.rules.prim_001_swings import Bar
    from app.services.rules.entry_001_imbalance_poi import SUB_RANK
    from app.services.rules.prim_002_imbalances import ImbalanceInventory

    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "btcusdtp_5m_999.csv"
    bars = []
    with fixture.open() as fh:
        for row in csv.DictReader(fh):
            bars.append(Bar(
                time=datetime.fromisoformat(row["time"]),
                open=float(row["open"]), high=float(row["high"]),
                low=float(row["low"]), close=float(row["close"]),
            ))

    # THE TWO LIVE WINDOW LENGTHS. The whole point is that they must agree — the shadow
    # fetches 320 bars and the backtest 250, and before T-0020 the same band could be a
    # SUPER_BPR in one and a BPR in the other.
    chosen: dict[int, str] = {}
    for window in (250, 320):
        detected = ImbalanceInventory.detect(bars[-window:], tf="5M")
        admissible = [i for i in detected if i.type in SUB_RANK]
        assert admissible, f"no admissible candidates detected at {window} bars"

        # Pick a price the strongest candidate actually covers, so the location filter is
        # not what decides the outcome.
        strongest_rank = min(SUB_RANK[i.type] for i in admissible)
        target = next(i for i in admissible if SUB_RANK[i.type] == strongest_rank)
        at_price = (target.price_low + target.price_high) / 2.0

        ev = ImbalanceIsTheOnlyEntryPOI.evaluate(admissible, [], at_price=at_price)
        poi = ev.values["entry_poi"]
        assert poi is not None, f"nothing selected at {window} bars"

        here = [i for i in admissible if i.price_low <= at_price <= i.price_high]
        best_here = min(SUB_RANK[i.type] for i in here)
        assert poi["sub_rank"] == best_here, (
            f"at {window} bars ENTRY-001 chose sub_rank {poi['sub_rank']} where rank "
            f"{best_here} was available at that price — the precedence order is not "
            "being applied to what PRIM-002 actually detected"
        )
        chosen[window] = poi["type"]

    # AND THE TWO WINDOWS AGREE. This is the half that was impossible to assert before:
    # the ordering was always implemented correctly, but the TYPES it ordered moved with
    # the caller's lookback, so the same bar produced different entries in the shadow and
    # the backtest.
    assert chosen[250] == chosen[320], (
        f"the backtest window chose a {chosen[250]} and the shadow window a "
        f"{chosen[320]} on the same price action"
    )
