"""T-0023 — EXIT-004, TARGET-001 and TARGET-003: where the profit target goes.

The three rules operate at THREE DIFFERENT LEVELS and the defect this file is mostly written
against is collapsing them:

    LEVEL 1   which objective       TARGET-001   distance BARRED as an input
    LEVEL 2   across timeframes     TARGET-003   SIZE RANKS
    LEVEL 3   within one dir + TF   TARGET-003   proximity wins, size NOT the tie-break

An implementation using distance at level 1, or size at level 3, is wrong in opposite
directions — and both pass a test that only checks a target came out. An implementation that
ignores size entirely passes every level-3 test and violates level 2.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.rules import exit_004_target_object as eo
from app.services.rules.exit_004_target_object import (
    LOSSY_POOL_CLASSES,
    POOL_CLASS_TO_TARGET_TYPE,
    TARGET_OBJECT_TYPES,
    NotATargetObject,
    TargetIsANamedObject,
    TargetObject,
)
from app.services.rules.prim_002_imbalances import Imbalance
from app.services.rules.prim_003_liquidity import LiquidityPool, LiquidityPools
from app.services.rules.target_001_concerning_objective import (
    BANNED_INPUTS,
    ConcerningLiquidityIsStructural,
    InstitutionalDestination,
    Objective,
    why_names_a_destination,
)
from app.services.rules.target_003_nearest_within_tf import (
    NearestWithinTimeframe,
    rank_across_timeframes,
    select_within_tf,
)

from datetime import datetime, timezone

UTC = timezone.utc

DEST_A = InstitutionalDestination(id="dest-A", label="weekly high", direction="BULLISH", tf="1W")
DEST_B = InstitutionalDestination(id="dest-B", label="monthly low", direction="BEARISH", tf="1M")


def pool(pid: str, price: float, pool_class: str = "SWING_LEVEL", tf: str = "4H"):
    return LiquidityPool(id=pid, tf=tf, pool_class=pool_class, price=price)


def target(pid: str, price: float, pool_class: str = "SWING_LEVEL", tf: str = "4H"):
    return TargetIsANamedObject.from_pool(pool(pid, price, pool_class, tf))


def objective(
    pid: str, price: float, *, distance: float, size: float | None = None,
    resolved: bool = False, supports: bool = True, tf: str = "4H",
    pool_class: str = "SWING_LEVEL",
) -> Objective:
    return Objective(
        target=target(pid, price, pool_class, tf),
        resolved=resolved,
        supports_destination=supports,
        distance=distance,
        size=size,
    )


# ---------------------------------------------------------------------------
# Criterion 1 — a target is a NAMED OBJECT and never a bare number
# ---------------------------------------------------------------------------
def test_a_target_carries_a_type_and_an_id_not_only_a_price():
    t = target("pool-7", 118400.0, "EQUAL_HIGHS_LOWS")
    d = t.as_dict()
    assert d["target_object_id"] == "pool-7"
    assert d["target_object_type"] == "EQUAL_HIGHS_LOWS"
    assert d["price"] == 118400.0


def test_a_target_object_with_no_id_cannot_be_constructed():
    """A float target is the defect EXIT-004 exists to forbid."""
    with pytest.raises(NotATargetObject, match="bare number"):
        TargetObject(object_id="", object_type="LIQUIDITY_POOL", price=118400.0,
                     source_class="SWING_LEVEL", tf="4H")


def test_a_pool_with_no_price_is_not_a_target():
    with pytest.raises(NotATargetObject, match="no price"):
        TargetIsANamedObject.from_pool(
            LiquidityPool(id="p", tf="4H", pool_class="SWING_LEVEL", price=None)
        )


def test_the_price_is_read_off_the_object_and_cannot_disagree_with_it():
    """No independent price parameter exists, so a record cannot name an object and carry a
    number that is not on it."""
    import inspect

    params = set(inspect.signature(TargetIsANamedObject.from_pool).parameters)
    assert params == {"pool"}, f"from_pool grew a parameter: {params}"


def test_a_missing_target_is_a_FAIL_not_a_shrug():
    ev = TargetIsANamedObject.evaluate(None)
    assert ev.verdict == "FAIL"
    assert "unexplained decision" in ev.values["violations"][0]


# ---------------------------------------------------------------------------
# Criterion 1a — the type comes from the contract's enum, which is narrower
# ---------------------------------------------------------------------------
def test_the_admissible_types_match_the_schema_exactly():
    schema = json.loads(
        (Path(eo.__file__).parents[2] / "services/telemetry/contract/TELEMETRY_SCHEMA.json")
        .read_text()
    )
    enum = schema["$defs"]["trade_execution"]["properties"]["target"]["properties"][
        "target_object_type"
    ]["enum"]
    assert list(TARGET_OBJECT_TYPES) == enum, (
        "the mirrored enum has drifted from the contract; a record built from it would fail "
        "validation at the store boundary rather than here"
    )


def test_every_pool_class_prim_003_knows_has_an_explicit_mapping():
    """No default. A class becoming buildable later must not fall silently into the generic
    bucket — it must be a deliberate table entry."""
    from app.services.rules.prim_003_liquidity import PoolClass
    import typing

    known = set(typing.get_args(PoolClass))
    assert known == set(POOL_CLASS_TO_TARGET_TYPE), (
        f"unmapped pool classes: {known - set(POOL_CLASS_TO_TARGET_TYPE)}"
    )
    assert set(POOL_CLASS_TO_TARGET_TYPE.values()) <= set(TARGET_OBJECT_TYPES)


def test_an_unmapped_pool_class_is_refused_rather_than_defaulted():
    p = pool("p1", 100.0)
    object.__setattr__(p, "pool_class", "SOMETHING_NEW")
    with pytest.raises(ValueError, match="no entry in"):
        TargetIsANamedObject.from_pool(p)


def test_institutional_candlestick_does_NOT_map_to_institutional_level():
    """THE TRAP. A test against the mistake, not for the behaviour.

    The names differ by one word and the objects are different: INSTITUTIONAL_LEVEL is a
    monthly/weekly/daily DEEP-V SWING EXTREME (TARGET-007, OPEN, because a deep-V has no
    definition), while INSTITUTIONAL_CANDLESTICK is PDH/PDL, PWH/PWL, PMH/PML and the Monday
    range. Mapping one onto the other files every previous-day-high target as a deep-V
    extreme — a CONFIDENT WRONG CLASS, strictly worse than a visibly generic one. A future
    edit "tidying up" the table lands here, which is why the assertion is phrased against it.
    """
    assert POOL_CLASS_TO_TARGET_TYPE["INSTITUTIONAL_CANDLESTICK"] != "INSTITUTIONAL_LEVEL"
    assert POOL_CLASS_TO_TARGET_TYPE["INSTITUTIONAL_CANDLESTICK"] == "LIQUIDITY_POOL"
    t = target("pdh-1", 120.0, "INSTITUTIONAL_CANDLESTICK")
    assert t.object_type == "LIQUIDITY_POOL"
    assert t.lossy is True
    # INSTITUTIONAL_LEVEL is reachable — by the class that actually means it, so the enum
    # value is not dead, it is just not this one's.
    assert POOL_CLASS_TO_TARGET_TYPE["INSTITUTIONAL_LEVEL"] == "INSTITUTIONAL_LEVEL"


def test_the_lossy_set_is_exactly_the_classes_whose_mapping_discards_information():
    derived_lossy = {
        k for k, v in POOL_CLASS_TO_TARGET_TYPE.items()
        if v == "LIQUIDITY_POOL" and k != "LIQUIDITY_POOL"
    }
    assert derived_lossy == set(LOSSY_POOL_CLASSES), (
        "LOSSY_POOL_CLASSES has drifted from the mapping table it describes"
    )


def test_a_widened_type_is_flagged_and_a_faithful_one_is_not():
    assert target("a", 1.0, "SWING_LEVEL").as_dict()["type_is_widened"] is True
    assert "type_is_widened" not in target("b", 1.0, "SESSION_LEVEL").as_dict()


def test_the_true_class_is_NOT_copied_into_the_record_and_the_id_is_the_join_key():
    """The class lives in setup_evaluation.primitives.liquidity_pools[]; the record points
    at it by id. A second copy is the same claim in two homes and the copy nothing checks is
    the one that goes stale.

    The honest cost — a trade_execution read ALONE cannot tell you the pool class — is real
    and is stated in the module rather than fixed with a duplicate.
    """
    d = target("pool-9", 120.0, "INSTITUTIONAL_CANDLESTICK").as_dict()
    assert "source_class" not in d
    assert "tf" not in d
    assert d["target_object_id"] == "pool-9"


@pytest.mark.parametrize(
    "fill_state,expect_lossy", [("UNFILLED", False), ("HALF_FILLED", True)]
)
def test_half_filled_imbalances_map_to_unfilled_imbalance_and_say_so(fill_state, expect_lossy):
    """B77's shape: the enum has one value for a pair the prose distinguishes."""
    imb = Imbalance(
        id="imb-1", tf="4H", bar_time=datetime(2026, 7, 15, 14, 0, tzinfo=UTC),
        price_high=130.0, price_low=128.0, type="FVG", direction="BULLISH",
        fill_state=fill_state,
    )
    t = TargetIsANamedObject.from_imbalance(imb)
    assert t.object_type == "UNFILLED_IMBALANCE"
    assert t.lossy is expect_lossy
    assert t.price == 130.0                      # the far edge in the direction of travel
    assert t.as_dict()["fill_state_at_selection"] == fill_state


def test_the_fill_state_field_is_named_so_it_cannot_be_read_as_current_state():
    """A pool's class is immutable so a copy can only drift; an imbalance's fill state
    ADVANCES, so the join returns the state NOW and never the state WHEN IT WAS CHOSEN.
    That makes this the only copy of a different fact — and the name has to say so."""
    imb = Imbalance(
        id="imb-2", tf="4H", bar_time=datetime(2026, 7, 15, 14, 0, tzinfo=UTC),
        price_high=130.0, price_low=128.0, type="FVG", direction="BEARISH",
        fill_state="HALF_FILLED",
    )
    d = TargetIsANamedObject.from_imbalance(imb).as_dict()
    assert "fill_state_at_selection" in d
    assert "fill_state" not in d, "a bare fill_state invites the misreading the join contradicts"
    assert d["price"] == 128.0                   # bearish: the low edge


def test_a_consumed_imbalance_is_not_a_target():
    for state in ("FULLY_FILLED", "FULLY_FILLED_AND_VIOLATED"):
        imb = Imbalance(
            id="imb-x", tf="4H", bar_time=datetime(2026, 7, 15, 14, 0, tzinfo=UTC),
            price_high=130.0, price_low=128.0, type="FVG", direction="BULLISH",
            fill_state=state,
        )
        with pytest.raises(NotATargetObject, match="unfilled or half filled"):
            TargetIsANamedObject.from_imbalance(imb)


# ---------------------------------------------------------------------------
# Criterion 2 / 2-i — why_selected names the DESTINATION, and a distance fails
# ---------------------------------------------------------------------------
def test_a_distance_phrased_why_is_a_failing_value():
    assert why_names_a_destination("supports the weekly high dest-A") is True
    for bad in ("nearest unresolved high", "the closest pool", "within 0.5% of entry",
                "2.0 x ATR away", ""):
        assert why_names_a_destination(bad) is False, bad


def test_why_selected_names_the_destination_and_DIFFERS_BETWEEN_TWO_DESTINATIONS():
    """CRITERION 2-i — the only assertion that separates DERIVED from TEMPLATED.

    With a single destination in the fixture, a HARDCODED destination-shaped string passes
    every other check: it is non-empty, it contains no distance vocabulary, and it names a
    destination. Two destinations producing two DIFFERENT strings is what a constant cannot
    do.
    """
    obj_a = objective("obj-a", 130.0, distance=30.0)
    obj_b = objective("obj-b", 70.0, distance=30.0)

    why_a = ConcerningLiquidityIsStructural.evaluate([obj_a], DEST_A).values[
        "concerning_objective"]["why_selected"]
    why_b = ConcerningLiquidityIsStructural.evaluate([obj_b], DEST_B).values[
        "concerning_objective"]["why_selected"]

    assert why_a != why_b, "why_selected is templated, not derived from the destination"
    assert DEST_A.label in why_a and DEST_A.id in why_a
    assert DEST_B.label in why_b and DEST_B.id in why_b
    assert DEST_B.label not in why_a
    for why in (why_a, why_b):
        assert why_names_a_destination(why)


# ---------------------------------------------------------------------------
# Criterion 3 — the banned inputs are CHECKED, and `present` is COMPUTED
# ---------------------------------------------------------------------------
def test_the_banned_inputs_match_the_registry():
    from app.services.telemetry import contract_loader as contract

    assert list(BANNED_INPUTS) == contract.rule("TARGET-001")["banned_inputs"]


def test_present_is_computed_rather_than_hardcoded_empty():
    """T-0019's defect: an enumeration that always reported nothing present passes
    identically whether the inputs are absent or nobody looked."""
    clean = ConcerningLiquidityIsStructural.evaluate([objective("o", 130.0, distance=5.0)], DEST_A)
    assert clean.banned_input_check == {"checked": list(BANNED_INPUTS), "present": []}
    assert clean.verdict == "PASS"

    for banned in BANNED_INPUTS:
        dirty = ConcerningLiquidityIsStructural.evaluate(
            [objective("o", 130.0, distance=5.0)], DEST_A,
            supplied_inputs={banned: 1.23},
        )
        assert dirty.verdict == "FAIL", banned
        assert dirty.banned_input_check["present"] == [banned]
        assert banned in dirty.values["violations"][0]


def test_an_unbanned_input_does_not_trip_the_check():
    ev = ConcerningLiquidityIsStructural.evaluate(
        [objective("o", 130.0, distance=5.0)], DEST_A,
        supplied_inputs={"liquidity_inventory": [], "active_destination": "dest-A"},
    )
    assert ev.verdict == "PASS"
    assert ev.banned_input_check["present"] == []


# ---------------------------------------------------------------------------
# Criterion 4 — DISTANCE MUST NOT PICK THE OBJECTIVE. Both directions.
# ---------------------------------------------------------------------------
def test_the_farther_objective_wins_when_it_is_the_one_supporting_the_destination():
    near_wrong = objective("near-wrong", 105.0, distance=5.0, supports=False)
    far_right = objective("far-right", 130.0, distance=30.0, supports=True)
    ev = ConcerningLiquidityIsStructural.evaluate([near_wrong, far_right], DEST_A)
    assert ev.values["concerning_objective"]["id"] == "far-right"


def test_and_inverted_the_nearer_objective_wins_when_IT_supports_the_destination():
    """The inversion matters: a hardcoded preference for the far one passes the test above."""
    near_right = objective("near-right", 105.0, distance=5.0, supports=True)
    far_wrong = objective("far-wrong", 130.0, distance=30.0, supports=False)
    ev = ConcerningLiquidityIsStructural.evaluate([near_right, far_wrong], DEST_A)
    assert ev.values["concerning_objective"]["id"] == "near-right", (
        "the selection followed position rather than the destination"
    )


def test_with_TWO_supporting_candidates_the_STRUCTURAL_order_wins_not_the_nearer_one():
    """THE CASE THAT ACTUALLY BARS DISTANCE, and the two tests above do not reach it.

    Measured, not reasoned: mutating `select` to sort candidates by distance left the whole
    file GREEN. With only ONE candidate supporting the destination, the filter decides and
    the iteration order cannot matter — so a distance-sorting implementation passes both
    direction tests and criterion 4 as written cannot see it.

    The discriminating fixture needs TWO candidates that BOTH support the destination, with
    structural order OPPOSITE to distance order. "The NEXT unresolved objective" is the
    first in the sequence price would encounter, which the caller supplies; a sort by
    distance picks the other one.
    """
    first_in_structure = objective("first", 300.0, distance=200.0, supports=True)
    nearer_but_later = objective("nearer", 110.0, distance=5.0, supports=True)

    ev = ConcerningLiquidityIsStructural.evaluate(
        [first_in_structure, nearer_but_later], DEST_A
    )
    assert ev.values["concerning_objective"]["id"] == "first", (
        "TARGET-001 reordered its candidates by distance — 'distance alone never determines "
        "the destination', and proximity survives only as an ordering input at TARGET-003's "
        "levels, not here"
    )
    assert ev.values["destination_supported_candidates"] == 2, (
        "the fixture must have TWO supporting candidates or it cannot discriminate"
    )


def test_a_resolved_objective_is_skipped_however_close_it_is():
    """'Only fresh not hunted liquidity levels count as objectives.'"""
    hunted = objective("hunted", 105.0, distance=1.0, resolved=True, supports=True)
    fresh = objective("fresh", 130.0, distance=30.0, resolved=False, supports=True)
    ev = ConcerningLiquidityIsStructural.evaluate([hunted, fresh], DEST_A)
    assert ev.values["concerning_objective"]["id"] == "fresh"
    assert ev.values["unresolved_candidates"] == 1


def test_the_record_claims_distance_was_not_used_and_the_claim_is_structural():
    ev = ConcerningLiquidityIsStructural.evaluate(
        [objective("o", 130.0, distance=99.0)], DEST_A
    )
    assert ev.values["distance_used_in_selection"] is False
    # And the claim is true of the code, not merely of the record: `select` reads no
    # distance, so removing every distance leaves the choice unchanged.
    with_distance = ConcerningLiquidityIsStructural.select(
        [objective("a", 130.0, distance=1.0, supports=False),
         objective("b", 140.0, distance=99.0, supports=True)], DEST_A
    )
    without = ConcerningLiquidityIsStructural.select(
        [Objective(target=target("a", 130.0), resolved=False, supports_destination=False),
         Objective(target=target("b", 140.0), resolved=False, supports_destination=True)],
        DEST_A,
    )
    assert with_distance.target.object_id == without.target.object_id == "b"


def test_no_destination_is_NOT_APPLICABLE_and_names_the_missing_producer():
    """THE LIVE CASE TODAY. Nothing in the engine produces an institutional destination."""
    ev = ConcerningLiquidityIsStructural.evaluate([objective("o", 130.0, distance=5.0)], None)
    assert ev.verdict == "NOT_APPLICABLE"
    assert ev.values["missing_producer"] == "active_institutional_destination"
    assert "NOTHING IN THE ENGINE PRODUCES ONE" in ev.values["not_applicable_reason"]


def test_target_001_is_declared_unable_to_fire():
    """Registering must not inflate effective coverage: implemented and unable to fire has
    its own bucket, and putting it there keeps the coverage figure honest."""
    assert ConcerningLiquidityIsStructural.CANNOT_FIRE_WITHOUT == (
        "active_institutional_destination",
    )


def test_nothing_in_the_engine_produces_an_institutional_destination():
    """The measurement behind CANNOT_FIRE_WITHOUT, asserted so it cannot rot.

    Goes red when a producer appears — which is exactly when TARGET-001 becomes able to fire
    and the coverage bucket must change.
    """
    app_dir = Path(eo.__file__).parents[2]
    needles = ("institutional_destination", "active_destination")
    hits = []
    scanned = 0
    for path in app_dir.rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        scanned += 1
        text = path.read_text().lower()
        for n in needles:
            # The rules that CONSUME it name it; a producer would assign or compute it.
            if n in text and path.name not in (
                "target_001_concerning_objective.py", "__init__.py",
            ):
                hits.append(f"{path.name}: {n}")
    assert scanned > 100, f"only {scanned} files scanned — the scan is not covering app/"
    assert hits == [], f"a producer may now exist: {hits}"


# ---------------------------------------------------------------------------
# Criterion 5 — SIZE IS NOT THE TIE-BREAK within one direction and timeframe
# ---------------------------------------------------------------------------
def test_within_one_timeframe_the_nearer_smaller_pool_beats_the_far_large_cluster():
    near_small = objective("near-small", 110.0, distance=5.0, size=1.0)
    far_large = objective("far-large", 200.0, distance=90.0, size=500.0)
    ev = NearestWithinTimeframe.evaluate([near_small, far_large], same_timeframe=True)
    assert ev.verdict == "PASS"
    assert ev.values["selected"] == "near-small"
    assert ev.values["size_ranks_here"] is False


def test_the_rejected_pool_is_reported_with_the_distance_that_beat_its_size():
    """TARGET-003's declared output. A selection recorded alone is unauditable — 'the
    nearest was chosen' is only checkable against the alternatives it beat."""
    near_small = objective("near-small", 110.0, distance=5.0, size=1.0)
    far_large = objective("far-large", 200.0, distance=90.0, size=500.0)
    ev = NearestWithinTimeframe.evaluate([near_small, far_large], same_timeframe=True)

    rejected = ev.values["rejected_pools"]
    assert len(rejected) == 1
    assert rejected[0]["id"] == "far-large"
    assert rejected[0]["distance"] == 90.0
    assert rejected[0]["size"] == 500.0
    assert rejected[0]["size_lost_to_proximity"] is True
    assert "5.0" in rejected[0]["reason"], "the winning distance must appear in the reason"
    # The doctrinal case, counted. If this is always zero over a corpus, the tie-break has
    # never been exercised and the rule is passing without deciding anything.
    assert ev.values["larger_pools_rejected"] == 1


def test_a_rejection_where_the_loser_was_smaller_is_not_flagged():
    """The counter to the flag above: if it fired on every rejection it would count nothing."""
    near_big = objective("near-big", 110.0, distance=5.0, size=500.0)
    far_small = objective("far-small", 200.0, distance=90.0, size=1.0)
    ev = NearestWithinTimeframe.evaluate([near_big, far_small], same_timeframe=True)
    assert ev.values["selected"] == "near-big"
    assert ev.values["rejected_pools"][0]["size_lost_to_proximity"] is False
    assert ev.values["larger_pools_rejected"] == 0


def test_an_unsized_pool_counts_as_zero_not_as_unbounded():
    """Treating absence as 'biggest' is how a detector gap becomes a preference."""
    unsized = objective("unsized", 200.0, distance=10.0, size=None)
    sized = objective("sized", 210.0, distance=20.0, size=5.0)
    ranked = rank_across_timeframes([unsized, sized])
    assert [o.target.object_id for o in ranked] == ["sized", "unsized"]


def test_a_candidate_with_no_distance_is_refused_rather_than_defaulted():
    no_distance = Objective(target=target("x", 100.0), resolved=False, supports_destination=True)
    with pytest.raises(ValueError, match="no distance"):
        select_within_tf([no_distance])


# ---------------------------------------------------------------------------
# Criterion 5a — SIZE RANKS ACROSS TIMEFRAMES, the level criterion 5 does not cover
# ---------------------------------------------------------------------------
def test_across_timeframes_the_larger_pool_ranks_higher_even_though_it_is_farther():
    """CRITERION 5a. 'Size still ranks ACROSS timeframes.'

    An implementation that ignores size entirely satisfies criterion 5 and every level-3
    test, and VIOLATES the rule here. It is also the conservative-looking choice, which this
    register records as the direction that attracts less scrutiny.
    """
    small_near_4h = objective("small-4H", 110.0, distance=5.0, size=1.0, tf="4H")
    large_far_1d = objective("large-1D", 300.0, distance=200.0, size=500.0, tf="1D")
    ev = NearestWithinTimeframe.evaluate([small_near_4h, large_far_1d], same_timeframe=False)
    assert ev.values["selected"] == "large-1D"
    assert ev.values["size_ranks_here"] is True
    assert [r["id"] for r in ev.values["ranking"]] == ["large-1D", "small-4H"]


def test_the_SAME_large_pool_loses_to_a_nearer_one_on_its_own_timeframe():
    """THE PAIR WITH 5a, AND THE PAIRING IS THE POINT.

    'Size still ranks across timeframes; it never beats proximity within one' — both halves,
    with the SAME pool, or the implementation has collapsed the three levels into two. A
    single sort cannot produce both results.
    """
    large_far_1d = objective("large-1D", 300.0, distance=200.0, size=500.0, tf="1D")
    small_near_1d = objective("small-1D", 120.0, distance=8.0, size=1.0, tf="1D")

    across = NearestWithinTimeframe.evaluate(
        [small_near_1d, large_far_1d], same_timeframe=False
    )
    within = NearestWithinTimeframe.evaluate(
        [small_near_1d, large_far_1d], same_timeframe=True
    )
    assert across.values["selected"] == "large-1D", "size must rank across timeframes"
    assert within.values["selected"] == "small-1D", "proximity must win within one"
    assert across.values["selected"] != within.values["selected"], (
        "the same candidate set produced the same winner at both levels — the two orderings "
        "have been collapsed into one sort"
    )


def test_the_level_is_recorded_on_every_record():
    a = NearestWithinTimeframe.evaluate([objective("o", 1.0, distance=1.0)], same_timeframe=True)
    b = NearestWithinTimeframe.evaluate([objective("o", 1.0, distance=1.0)], same_timeframe=False)
    assert a.values["level"] == "WITHIN_TF_PROXIMITY"
    assert b.values["level"] == "ACROSS_TF_SIZE"


def test_an_empty_candidate_set_is_not_a_quiet_pass():
    """B84: an ordering rule over an empty set has ordered nothing."""
    ev = NearestWithinTimeframe.evaluate([], same_timeframe=True)
    assert ev.verdict == "NOT_APPLICABLE"
    assert ev.values["candidates_considered"] == 0


# ---------------------------------------------------------------------------
# Criterion 6 — the three levels must be SHOWN to operate differently
# ---------------------------------------------------------------------------
def test_all_three_levels_operate_and_a_single_sort_cannot_reproduce_them():
    """CRITERION 6. The reconciliation is a claim; this makes it a test.

    Fixture: the destination-supporting objective is on a DIFFERENT timeframe from the
    nearest pool.

      L1  TARGET-001 fixes the objective, ignoring distance -> the 1D pool that supports it
      L2  across timeframes, size ranks                     -> the large 1D pool
      L3  within 1D + one direction, proximity wins         -> the NEAR 1D pool

    Three different winners from one candidate set. A single sort produces one.
    """
    near_4h_wrong = objective(
        "near-4H", 105.0, distance=3.0, size=900.0, tf="4H", supports=False
    )
    near_1d_right = objective(
        "near-1D", 140.0, distance=40.0, size=10.0, tf="1D", supports=True
    )
    far_1d_large = objective(
        "far-1D", 300.0, distance=200.0, size=500.0, tf="1D", supports=True
    )
    candidates = [near_4h_wrong, near_1d_right, far_1d_large]

    # LEVEL 1 — which objective. Distance barred; the nearest candidate is the WRONG one and
    # the biggest is not the answer either.
    l1 = ConcerningLiquidityIsStructural.evaluate(candidates, DEST_A)
    assert l1.values["concerning_objective"]["id"] == "near-1D", (
        "level 1 followed distance or size instead of the destination"
    )

    # LEVEL 2 — across timeframes, size ranks.
    l2 = NearestWithinTimeframe.evaluate(candidates, same_timeframe=False)
    assert l2.values["selected"] == "near-4H"          # size 900, the largest

    # LEVEL 3 — within 1D only, proximity wins over the larger far pool.
    same_tf = [o for o in candidates if o.target.tf == "1D"]
    l3 = NearestWithinTimeframe.evaluate(same_tf, same_timeframe=True)
    assert l3.values["selected"] == "near-1D"
    assert l3.values["rejected_pools"][0]["size_lost_to_proximity"] is True

    assert len({l1.values["concerning_objective"]["id"], l2.values["selected"]}) == 2, (
        "levels 1 and 2 chose the same candidate — one sort could produce both"
    )


# ---------------------------------------------------------------------------
# Criterion 7 — EXIT-004's aligned-asset claim is OUT OF SCOPE and says so
# ---------------------------------------------------------------------------
def test_the_aligned_asset_claim_is_declared_unimplemented_on_every_record():
    """A claim the engine makes about itself, which a conformance test can read.

    'On a magic-aligned setup the target class should be present on all aligned assets' is a
    CROSS-ASSET assertion needing the correlate panels and GATE-002's disturbance state.
    """
    ev = TargetIsANamedObject.evaluate(target("p", 120.0))
    assert ev.values["aligned_asset_claim_evaluated"] is False
    assert "correlate panels" in ev.value_provenance["aligned_asset_claim_evaluated"]["field"]

    missing = TargetIsANamedObject.evaluate(None)
    assert missing.values["aligned_asset_claim_evaluated"] is False


def test_exit_004_says_it_is_partial_in_its_coverage_note():
    note = TargetIsANamedObject.COVERAGE_NOTE
    assert "NOT implemented" in note and "aligned" in note
    assert "LOSSY" in note or "lossy" in note


# ---------------------------------------------------------------------------
# Telemetry shape and registration
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "build",
    [
        lambda: TargetIsANamedObject.evaluate(target("p", 120.0)),
        lambda: TargetIsANamedObject.evaluate(None),
        lambda: ConcerningLiquidityIsStructural.evaluate(
            [objective("o", 130.0, distance=5.0)], DEST_A),
        lambda: ConcerningLiquidityIsStructural.evaluate([], None),
        lambda: ConcerningLiquidityIsStructural.evaluate(
            [objective("o", 130.0, distance=5.0)], DEST_A,
            supplied_inputs={"fixed_pct_distance": 1.0}),
        lambda: NearestWithinTimeframe.evaluate(
            [objective("o", 1.0, distance=1.0, size=2.0)], same_timeframe=True),
        lambda: NearestWithinTimeframe.evaluate(
            [objective("o", 1.0, distance=1.0, size=2.0)], same_timeframe=False),
        lambda: NearestWithinTimeframe.evaluate([], same_timeframe=True),
    ],
)
def test_every_value_names_its_provenance_on_every_branch(build):
    """ALL BRANCHES, because a branch that adds a value is where provenance is forgotten —
    T-0022's own defect, found by a mutation rather than by the test as first written."""
    ev = build()
    assert set(ev.values) == set(ev.value_provenance), (
        f"{ev.rule_id}/{ev.verdict}: "
        f"unpinned {set(ev.values) ^ set(ev.value_provenance)}"
    )
    assert all("source" in p for p in ev.value_provenance.values())


def test_the_three_rules_declare_their_contract_ids():
    assert TargetIsANamedObject.RULE_ID == "EXIT-004"
    assert ConcerningLiquidityIsStructural.RULE_ID == "TARGET-001"
    assert NearestWithinTimeframe.RULE_ID == "TARGET-003"


def test_the_package_registers_these_three_specifically():
    """The general guard is `test_rules_base.py::test_the_package_alone_registers_every_rule
    _module`, which spawns a clean interpreter and covers all 26 modules in the guard's
    domain — B93, found because an `__init__.py` revert during this task left all 50 tests
    here green while `check_rule_coverage.py` correctly reported these three unimplemented.

    This one stays as the task-local canary: it names the three rules T-0023 adds, so a
    failure here says which task regressed rather than only that something did.
    """
    from app.services.rules import implemented_ids

    # NOTE: satisfiable by this file's own top-level imports — see B93. The load-bearing
    # version is the clean-interpreter test in test_rules_base.py.
    assert {"EXIT-004", "TARGET-001", "TARGET-003"} <= implemented_ids()


def test_prim_003_unbuilt_classes_are_still_mapped_so_they_cannot_appear_unhandled():
    """Three of the seven pool classes are not built (each needs a number Salim declined to
    fix). They still have mappings, so if one becomes buildable it does not hit the refusal
    path as a surprise."""
    for cls in LiquidityPools.UNBUILT_CLASSES:
        assert cls in POOL_CLASS_TO_TARGET_TYPE
