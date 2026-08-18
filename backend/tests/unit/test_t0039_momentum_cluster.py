"""T-0039 stage 1 — the momentum producers, built with no invented scale.

`GRADE-032` (BULLET TRAIN), `GRADE-027` (forward signs), `GRADE-028` (slowdown signs).

**Two properties are asserted throughout and they are what this cluster is about:**

    NO INVENTED SCALE     seven of the nine rules have `values: null`, so any threshold would be
                          ours. Every test here is structural or ORDINAL, and a conformance arm
                          asserts the banned inputs appear nowhere in the new modules.
    ABSENT != EMPTY       a sign with nothing to compare returns `None`, never `False`. "Could
                          not look" and "looked and found nothing" must not share a value.

**And the deliverable is a census, not a coverage figure.** `GRADE-028` moves `GATE-041`'s three
`NOT_EVALUABLE` conditions to `NOT_READ` — the producer now exists and the rule still does not call
it — **so effective coverage is UNCHANGED at `50/79` and that is the honest, pre-recorded result.**
Clearing `CANNOT_FIRE_WITHOUT` would have moved it to `51/79` for an edit rather than a capability.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from app.services.rules.base import implementations
from app.services.rules.gate_041_reverse_switch import CONDITIONS as G41_CONDITIONS
from app.services.rules.grade_027_momentum_signs import (
    MOMENTUM_CLASSIFICATION_NOTE,
    ForwardMomentumSigns,
    MomentumLeg,
    MomentumSlowdownSigns,
    _is_decreasing,
    legs_from_breaks,
    unmitigated,
)
from app.services.rules.grade_032_bullet_train import DIAGNOSTIC_CHECKLIST, BulletTrainRegime
from app.services.rules.prim_001_swings import SwingPoints
from app.services.rules.prim_002_imbalances import Imbalance, ImbalanceInventory
from app.services.rules.prim_005_breaks import BreakEvents
from app.services.telemetry import contract_loader as contract

BACKEND = Path(__file__).resolve().parents[2]
RULES = BACKEND / "app" / "services" / "rules"
NEW_MODULES = ("grade_027_momentum_signs.py", "grade_032_bullet_train.py")


@pytest.fixture(scope="module")
def corpus():
    df = (
        pd.read_csv(BACKEND / "tests/fixtures/btcusdtp_5m_1500.csv", parse_dates=["time"])
        .set_index("time")
        .rename_axis("timestamp")
    )
    from app.services.live.shadow import _bars_from_frame

    bars = _bars_from_frame(df.tail(320))
    swings = SwingPoints.detect(bars, tf="M5")
    breaks = BreakEvents.detect(bars, swings, tf="M5")
    inventory = ImbalanceInventory.detect(bars, tf="M5")
    return bars, swings, breaks, inventory, legs_from_breaks(breaks, inventory, swings)


def _imb(idx: int, *, fill_state: str = "UNFILLED", width: float = 10.0, direction="UP") -> Imbalance:
    return Imbalance(
        id=f"imb-{idx}", tf="M5", bar_time=datetime(2026, 5, 1, tzinfo=timezone.utc),
        price_high=100.0 + width, price_low=100.0, type="FVG", direction=direction,
        fill_state=fill_state, formed_index=idx,
    )


# ---------------------------------------------------------------------------
# NO INVENTED SCALE — the constraint the whole cluster turns on
# ---------------------------------------------------------------------------


def _code_identifiers(module: str) -> set[str]:
    """Identifiers and numeric literals a module USES, from its AST.

    **AST, not text.** These modules discuss the banned vocabulary at length in order to refuse
    it — `MOMENTUM_CLASSIFICATION_NOTE` names `momentum_min_width` on purpose, so that a later
    seat cannot close the `None` by passing it. **A text grep fails on the prose that exists to
    prevent the thing**, which is `T-0032`'s lesson and `B145`'s recorded instance.
    """
    import ast

    names: set[str] = set()
    for node in ast.walk(ast.parse((RULES / module).read_text(encoding="utf-8"))):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.keyword) and node.arg:
            names.add(node.arg)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
                and not isinstance(node.value, bool):
            names.add(str(node.value))
    return names


@pytest.mark.parametrize("module", NEW_MODULES)
def test_the_new_modules_never_pass_momentum_min_width(module):
    """`PRIM-002` marks momentum imbalances only via a fixed WIDTH test, and `GATE-035` bans
    `imbalance_tiers_0.8_0.4` by name. **The tidy fix is the banned one**: a later reader meets an
    unpopulated field beside a working writer and closes the gap."""
    assert "momentum_min_width" not in _code_identifiers(module), (
        f"{module} passes the banned width parameter as code"
    )


def test_the_none_on_is_momentum_imbalance_is_explained_where_a_reader_meets_it():
    """A note that only exists in a docstring nobody opens is not a guard. This asserts the note
    names BOTH the banned parameter and the rule that bans it, so the connection cannot be lost."""
    assert "momentum_min_width" in MOMENTUM_CLASSIFICATION_NOTE
    assert "GATE-035" in MOMENTUM_CLASSIFICATION_NOTE
    assert "DO NOT" in MOMENTUM_CLASSIFICATION_NOTE


@pytest.mark.parametrize(
    "banned", ["atr", "0.8", "0.4", "0.6", "retrace", "body_size", "impulse_count",
               "momentum_min_width"]
)
@pytest.mark.parametrize("module", NEW_MODULES)
def test_no_banned_input_class_appears_as_code_in_the_new_modules(module, banned):
    """GATE-035's banned list is the rule, not a guideline."""
    offenders = [n for n in _code_identifiers(module) if banned in n.lower()]
    assert not offenders, f"{module}: banned input {banned!r} used as code: {sorted(offenders)}"


def test_the_banned_input_walk_can_actually_see_a_banned_identifier():
    """CONTROL PAIR on the instrument. An all-clean sweep proves nothing unless the sweep has
    been shown to find something — and the must-miss half is the whole point here, because these
    modules contain the banned words in PROSE."""
    import ast

    planted = ast.parse("x = compute(momentum_min_width=0.8)")
    found = {n.arg for n in ast.walk(planted) if isinstance(n, ast.keyword) and n.arg}
    found |= {str(n.value) for n in ast.walk(planted)
              if isinstance(n, ast.Constant) and isinstance(n.value, float)}
    assert "momentum_min_width" in found and "0.8" in found

    # MUST-MISS: the same tokens inside a string are prose and must NOT be seen.
    prose = _code_identifiers("grade_027_momentum_signs.py")
    assert "momentum_min_width" not in prose
    assert "momentum_min_width" in MOMENTUM_CLASSIFICATION_NOTE, (
        "the note must still name the parameter — that naming is what stops the tidy fix"
    )


def test_the_banned_list_this_arm_asserts_against_is_the_registry_s_own():
    """CONTROL. An arm asserting a stale vocabulary passes forever and guards nothing."""
    statement = str(contract.rule("GATE-035").get("statement", "")).lower()
    for token in ("atr", "retrace", "0.8", "0.4"):
        assert token in statement, f"{token!r} is no longer in GATE-035's statement"


# ---------------------------------------------------------------------------
# ABSENT != EMPTY — the ordinal reads return None, never False
# ---------------------------------------------------------------------------


def test_nothing_to_compare_is_None_and_not_False():
    assert _is_decreasing([]) is None
    assert _is_decreasing([5.0]) is None, "one value has no ordering — that is not 'not decreasing'"
    assert _is_decreasing([5.0, 3.0]) is True
    assert _is_decreasing([3.0, 5.0]) is False


def test_a_leg_with_one_imbalance_does_not_claim_a_shrinking_sequence():
    leg = MomentumLeg(0, 10, "UP", imbalances=(_imb(1),))
    signs = MomentumSlowdownSigns.signs(leg)
    assert signs["momentum_imbalances_reduce_and_shrink"]["fired"] is None


def test_fewer_than_two_breaks_bound_no_leg_and_none_is_invented():
    """Eight rule statements use the word "leg" and NONE defines one. Emitting a leg from a
    single break would be inventing the boundary this function exists to avoid inventing."""
    assert legs_from_breaks([]) == []


# ---------------------------------------------------------------------------
# MUST-FIRE ARMS — one mutation per rule
# ---------------------------------------------------------------------------


def test_grade_027_sign_1_fires_on_unmitigated_and_not_on_filled():
    left = MomentumLeg(0, 10, "UP", imbalances=(_imb(1), _imb(2)))
    none = MomentumLeg(0, 10, "UP", imbalances=(_imb(1, fill_state="FILLED"),))

    assert ForwardMomentumSigns.signs(left)["momentum_imbalances_left_unfilled"]["fired"] is True
    assert ForwardMomentumSigns.signs(none)["momentum_imbalances_left_unfilled"]["fired"] is False
    assert ForwardMomentumSigns.evaluate(left).verdict == "PASS"


def test_grade_027_the_discriminator_is_mitigation_state_and_nothing_else():
    """GRADE-037: "the discriminator is MITIGATION STATE, not candle size". A one-unit-wide
    unfilled gap counts and a hundred-unit-wide filled one does not."""
    assert len(unmitigated([_imb(1, width=0.01)])) == 1
    assert len(unmitigated([_imb(1, width=1000.0, fill_state="FILLED")])) == 0


def test_grade_028_sign_4_fires_on_an_opposite_side_imbalance():
    same = MomentumLeg(0, 10, "UP", imbalances=(_imb(1, direction="UP"),))
    opp = MomentumLeg(0, 10, "UP", imbalances=(_imb(1, direction="DOWN"),))

    assert MomentumSlowdownSigns.signs(same)["opposite_side_momentum_imbalance"]["fired"] is False
    assert MomentumSlowdownSigns.signs(opp)["opposite_side_momentum_imbalance"]["fired"] is True


def test_grade_028_sign_1_reads_the_sequence_ordinally():
    shrinking = MomentumLeg(0, 10, "UP", imbalances=(_imb(1, width=50.0), _imb(2, width=5.0)))
    growing = MomentumLeg(0, 10, "UP", imbalances=(_imb(1, width=5.0), _imb(2, width=50.0)))

    assert MomentumSlowdownSigns.signs(shrinking)["momentum_imbalances_reduce_and_shrink"]["fired"] is True
    assert MomentumSlowdownSigns.signs(growing)["momentum_imbalances_reduce_and_shrink"]["fired"] is False


def test_grade_028_reports_the_purpose_sign_as_NOT_READ_rather_than_evaluating_a_None_field():
    """MEASURED, and it is why: `purpose_verdict` has ONE assignment site and
    `target_cleared_at_failure` has ZERO anywhere in `app/`. On a real inventory both are `None`
    for every imbalance. **A verdict over fields we invented values for is worth less than an
    honest NOT_READ** — and populating them here would be absorbing T-0033 to make a verdict
    appear."""
    leg = MomentumLeg(0, 10, "UP", imbalances=(_imb(1),))
    sign = MomentumSlowdownSigns.signs(leg)["imbalances_fail_their_purpose"]

    assert sign["fired"] is None
    assert sign["not_read"] == "purpose_verdict"
    assert "GRADE-038" in sign["producer"]
    assert "imbalances_fail_their_purpose" in MomentumSlowdownSigns.evaluate(leg).values["signs_not_read"]


def test_the_four_fields_grade_038_would_need_are_still_unpopulated(corpus):
    """CONTROL for the arm above: the fields really are `None`, so the NOT_READ is a fact rather
    than caution. If a later task populates them, this fails and the NOT_READ can be revisited."""
    _bars, _sw, _br, inventory, _legs = corpus
    for field in ("is_momentum_imbalance", "purpose_verdict", "target_cleared_at_failure"):
        assert {getattr(i, field) for i in inventory} == {None}, f"{field} is now populated"


def test_grade_032_a_counter_micro_break_flips_the_regime_condition(corpus):
    """MUST-FIRE, built SYNTHETICALLY because the corpus cannot exercise it — see below."""
    import dataclasses

    _bars, _sw, breaks, _inv, legs = corpus
    leg = next(l for l in legs if l.imbalances)
    clean = BulletTrainRegime.conditions(leg, breaks)["no_counter_micro_breaks"]

    inside = next(b for b in breaks
                  if b.bar_index is not None and leg.start_index < b.bar_index <= leg.end_index)
    counter = dataclasses.replace(
        inside, scale="MICRO",
        direction="DOWN" if str(leg.direction) == "UP" else "UP",
    )
    flipped = BulletTrainRegime.conditions(leg, [*breaks, counter])["no_counter_micro_breaks"]

    assert clean["state"] is True and flipped["state"] is False, (
        f"the condition did not move: {clean['state']} -> {flipped['state']}"
    )


def test_the_pinned_corpus_contains_NO_micro_breaks_at_all(corpus):
    """AN HONEST LIMIT, MEASURED. All 69 breaks in the 320-bar window are scale MAIN, so
    `no_counter_micro_breaks` is structurally present and **never observed to fire on real
    data**. The must-fire arm above is therefore synthetic BY NECESSITY — and saying so is the
    difference between a condition that holds and one that has never been tested."""
    _bars, _sw, breaks, _inv, _legs = corpus
    scales = {str(getattr(b, "scale", "")) for b in breaks}

    assert scales == {"MAIN"}, f"the corpus now contains other scales: {scales}"
    assert len(breaks) > 20, "must-hit: there are breaks to have scales at all"


def test_grade_032_names_the_condition_it_cannot_read_rather_than_dropping_it():
    leg = MomentumLeg(0, 10, "UP", imbalances=(_imb(1),))
    values = BulletTrainRegime.evaluate(leg).values

    assert "fresh_gaps_through_the_concerning_area" in values["conditions_not_read"]
    assert values["conditions_total"] == 4, "the denominator is published, not the read count"
    assert values["conditions_read"] < values["conditions_total"]


def test_grade_032_records_the_checklist_and_does_not_report_it_clear():
    """B157: a checklist rendered all-clear because nothing could be checked is the richer
    format making the empty case more convincing."""
    checklist = BulletTrainRegime.checklist(economic_release=None)

    assert len(checklist) == len(DIAGNOSTIC_CHECKLIST) == 6
    assert all(c["state"] is None for c in checklist.values())
    assert sum(1 for c in checklist.values() if c["answered"]) == 0
    answered = BulletTrainRegime.checklist(economic_release=False)
    assert answered["economic_data_release"]["answered"] is True, (
        "a calendar that was READ and had nothing is a different fact from one not asked"
    )


# ---------------------------------------------------------------------------
# THE DELIVERABLE — a census that moves, and a coverage figure that does not
# ---------------------------------------------------------------------------


def test_gate_041s_three_conditions_moved_from_NO_PRODUCER_to_NOT_READ():
    """THE DELIVERABLE. GRADE-028 exists, so "no producer exists" is now false for these three —
    and GATE-041 still does not call it, so they are NOT_READ. **A category change backed by a
    capability, not a number moved by an edit.**"""
    values = dict(implementations()["GATE-041"].evaluate().values)

    assert values["not_evaluable_count"] == 0, "GRADE-028 exists; nothing should say it does not"
    assert values["unread_count"] == 7
    for name in ("price_slows_after_destination", "momentum_deteriorating",
                 "momentum_imbalance_failures"):
        assert values["not_read"][name] == "GRADE-028"


def test_gate_041_cannot_fire_without_is_DELIBERATELY_still_set():
    """Clearing it moves effective coverage 50/79 -> 51/79 with NO capability change — measured.
    **The seat graded on the number can write the number**, so the flag stays telling the truth:
    GATE-041's MANDATORY condition is `micro_msb_confirms`, whose producer is PRIM-005 and which
    this rule does not read."""
    assert implementations()["GATE-041"].CANNOT_FIRE_WITHOUT == ("GRADE-028",)
    mandatory = dict(implementations()["GATE-041"].evaluate().values)["mandatory_condition"]
    assert mandatory == "micro_msb_confirms"
    assert dict(G41_CONDITIONS)[mandatory] == "PRIM-005", (
        "the mandatory condition's producer moved; the reason for not clearing the flag changed"
    )


def test_gate_034_is_WITHDRAWN_and_stays_unimplemented():
    """MUST-MISS ARM ON THE WAVE. A wave that "completes the momentum layer" is exactly how a
    withdrawn id gets built — its momentum band 15–20 is unreachable and that is what the id
    records."""
    assert contract.rule("GATE-034").get("status") == "WITHDRAWN"
    assert "GATE-034" not in implementations()

    # MUST-HIT: the same lookup finds the ids this wave DID implement, so the miss is a fact
    # about GATE-034 rather than about the lookup.
    for rid in ("GRADE-027", "GRADE-028", "GRADE-032"):
        assert rid in implementations()


def test_the_nine_targets_have_no_declared_values_so_any_threshold_would_be_invented():
    """The constraint that shaped every design decision in this cluster, asserted rather than
    remembered. If a later ratification supplies numbers, this fails and the ordinal reads can
    be revisited against real ones."""
    unquantified = [
        rid for rid in ("GRADE-032", "GRADE-027", "GRADE-028", "GATE-039",
                        "GRADE-036", "GRADE-037", "GRADE-038")
        if contract.rule(rid).get("values") is None
    ]
    assert len(unquantified) == 7, f"a declared value appeared: {unquantified}"


# ---------------------------------------------------------------------------
# The rules run on real bars and their answers move
# ---------------------------------------------------------------------------


def test_the_signs_fire_on_real_bars_and_are_not_constant(corpus):
    """DENOMINATOR OBSERVED NON-ZERO, nothing injected — the arm that a must-fire arm cannot
    substitute for. A rule that never fires and one that always fires are both useless, and the
    verdict alone distinguishes neither."""
    _bars, _sw, breaks, _inv, legs = corpus
    assert len(legs) > 10, "too few legs for this to mean anything"

    forward = [ForwardMomentumSigns.evaluate(l, breaks).verdict for l in legs]
    slowdown = [MomentumSlowdownSigns.evaluate(l).verdict for l in legs]
    regime = [BulletTrainRegime.evaluate(l, breaks).verdict for l in legs]

    for name, verdicts in (("GRADE-027", forward), ("GRADE-028", slowdown), ("GRADE-032", regime)):
        assert "PASS" in verdicts, f"{name} never passes on real bars — it cannot discriminate"
        assert "FAIL" in verdicts, f"{name} always passes on real bars — it cannot discriminate"


def test_a_leg_is_the_span_between_consecutive_breaks(corpus):
    _bars, _sw, breaks, _inv, legs = corpus
    indexed = sorted(b.bar_index for b in breaks if b.bar_index is not None)

    assert len(legs) == len(indexed) - 1, "the breaks ARE the boundaries; nothing else defines one"
    for leg in legs:
        assert leg.start_index <= leg.end_index

    # ZERO-WIDTH LEGS ARE REAL AND ARE NOT AN ERROR: 16 pairs of consecutive breaks in this
    # corpus print on the SAME bar. Such a leg spans no bars and therefore contains nothing --
    # which is the honest answer, not a defect to be smoothed away by merging them.
    empty = [l for l in legs if l.start_index == l.end_index]
    assert empty, "must-hit: the corpus does contain same-bar consecutive breaks"
    assert all(not l.imbalances and not l.swings for l in empty)


# ---------------------------------------------------------------------------
# A DORMANT BRANCH IN THE COVERAGE RESOLVER WOKE WHEN GRADE-028 LANDED
# ---------------------------------------------------------------------------


def _resolver():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "crc", BACKEND.parent / "scripts" / "check_rule_coverage.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_block_chain_survives_an_implemented_terminal_blocker():
    """THE DEFECT `GRADE-028` WOKE, AND IT REPORTED A BLOCKED RULE AS CLEAR.

    `resolve_block_chain` recurses only when the named blocker is itself IMPLEMENTED. Until
    `GRADE-028` landed every terminal blocker in the tree was unimplemented, so the leaf return
    was always taken and the `if not blockers: return [rule_id]` branch was never reached on a
    recursive call. **The day `GRADE-028` was implemented, that branch woke and discarded
    `_seen`:** `chain("GATE-040")` collapsed from three elements to `["GRADE-028"]` — **and a
    single-element list is the function's own documented signal for NOT BLOCKED.**

    Same shape as the multi-blocker branch below it, which the function's own comment calls
    *"currently DORMANT ... activates silently the first time someone declares two."* **One
    branch over, and it activated first.**
    """
    crc = _resolver()
    from app.services.telemetry import contract_loader as c

    impl, ids = implementations(), c.known_rule_ids()

    assert crc.resolve_block_chain("GATE-040", impl, ids) == [
        "GATE-040", "GATE-041", "GRADE-028",
    ], "the two-hop chain collapsed — the resolver dropped its accumulator again"
    assert crc.resolve_block_chain("GATE-041", impl, ids) == ["GATE-041", "GRADE-028"]

    # MUST-MISS: a genuinely unblocked rule still returns the single-element form, so the fix
    # did not make everything look blocked.
    assert crc.resolve_block_chain("GRADE-028", impl, ids) == ["GRADE-028"]

    # MUST-HIT on the OTHER path: a blocker that is NOT a rule id still terminates as a leaf,
    # which is the branch that was carrying the whole tree before GRADE-028 existed.
    assert crc.resolve_block_chain("GATE-027", impl, ids) == [
        "GATE-027", "order_block_detector",
    ]


def test_the_coverage_figure_CANNOT_DISTINGUISH_the_honest_work_from_the_refused_edit():
    """**MEASURED AFTER STAGE 2, AND IT IS THE SHARPEST THING IN THIS WAVE.**

    Stage 1 held effective coverage at `50/79` and the refused twelve-character edit would have
    made it `51/79`. **Stage 2 implemented six more rules and the honest figure is now `51/79`
    — the same number.**

    Of the nine rules this wave built, exactly ONE is `HARD_GATE` (`GATE-035`); seven are
    `SOFT_PREFERENCE` and one `ADVISORY`, so only one lands in the `79` population. **So nine
    rules of real work move the headline by the same `+1` that deleting `"GRADE-028",` from a
    tuple would have moved it.**

    > **The figure is identical either way, so the figure cannot tell them apart.** `B150`'s
    > family: a number that moves for two incomparable reasons and reports neither. **What
    > distinguishes them is the CANNOT-FIRE list, which the edit would have shortened and the
    > work did not** — and that is why the census, not the coverage number, is this task's
    > deliverable.
    """
    import subprocess
    import sys

    # `sys.executable`, not "python": the interpreter running this suite is the one with the
    # dependencies, and a bare name resolves against PATH or not at all.
    out = subprocess.run(
        [sys.executable, str(BACKEND.parent / "scripts" / "check_rule_coverage.py")],
        capture_output=True, text=True, cwd=BACKEND.parent,
    ).stdout
    # T-0045 moved the DENOMINATOR and not the numerator: registering PRIM-007 (a HARD_GATE
    # nothing implements) enlarges the space of rules without implementing one, so 79 -> 80
    # while 51 stands. THE NUMERATOR IS THE CLAIM; the denominator is the size of the problem.
    assert "51 / 80 distinct" in out, (
        "effective coverage is not where stage 2 left it — say which rule became able to reach "
        "a verdict, which CANNOT_FIRE_WITHOUT was cleared, or which HARD_GATE was registered"
    )
    # THE DISTINGUISHING EVIDENCE, and it is not the coverage number. The refused edit would
    # have SHORTENED this list; nine rules of honest work left it exactly as it was.
    assert "implemented but CANNOT FIRE    6 distinct" in out
    assert "GATE-040" in out and "GATE-041" in out

    # And the +1 is attributable: exactly one of the nine is HARD_GATE, so exactly one lands in
    # the 79-rule population. A figure whose movement cannot be attributed is not evidence.
    hard = [
        rid for rid in ("GRADE-032", "GRADE-027", "GRADE-028", "GATE-035", "GATE-039",
                        "GRADE-036", "GRADE-037", "GRADE-038", "GRADE-034")
        if contract.rule(rid).get("enforceability") == "HARD_GATE"
    ]
    assert hard == ["GATE-035"], f"the +1's attribution changed: {hard}"


# ===========================================================================
# STAGE 2 — GATE-035, GATE-039, GRADE-034, GRADE-036, GRADE-037, GRADE-038
# ===========================================================================

from app.services.rules.gate_035_structural_momentum import (  # noqa: E402
    MOMENTUM_MODULES,
    SELF_EXEMPT,
    MomentumIsStructural,
    MomentumScoreIsNotDoctrine,
    _tokens,
)
from app.services.rules.gate_039_do_not_fade import DoNotFadeABulletTrain  # noqa: E402
from app.services.rules.grade_036_momentum_preference import (  # noqa: E402
    PURPOSE_FIELDS,
    ImbalancePurposeTest,
    PreferSlowedMomentum,
    TwoTierTrendGrade,
)


def test_gate_035_passes_over_the_cluster_and_publishes_its_denominator():
    values = MomentumIsStructural.evaluate().values
    assert MomentumIsStructural.evaluate().verdict == "PASS"
    assert values["modules_examined"] > 0, "a clean result over zero modules is not a result"
    assert values["modules_examined"] == len(MOMENTUM_MODULES) - len(values["modules_exempt"])
    assert values["modules_missing"] == []


def test_gate_035_can_see_a_banned_input_when_one_is_there(tmp_path):
    """MUST-FIRE on the guard itself. The offenders map must be reachable."""
    planted = tmp_path / "grade_planted.py"
    planted.write_text("def f(atr_ratio=0.8):\n    return atr_ratio\n", encoding="utf-8")

    import app.services.rules.gate_035_structural_momentum as mod

    original = mod._RULES_DIR
    try:
        mod._RULES_DIR = tmp_path
        offenders = MomentumIsStructural.offenders(("grade_planted.py",))
    finally:
        mod._RULES_DIR = original

    assert offenders, "the guard cannot see a planted banned input"
    assert "atr_ratio" in offenders["grade_planted.py"]


def test_the_token_split_does_not_collide_with_ordinary_english():
    """MEASURED, NOT FORESEEN. The first version matched `atr` inside `RISK_MATRIX_MODULE` —
    m-**atr**-ix — and reported a banned ATR input inside the guard that bans ATR inputs."""
    assert "atr" not in _tokens("RISK_MATRIX_MODULE")
    assert "atr" in _tokens("atr_period")
    assert "atr" in _tokens("computeAtrRatio")


def test_the_enforcing_module_is_exempt_from_its_own_scan_and_says_so():
    """`B136`'s control-token contamination, hit while citing `B136`.

    `GRADE-034` cannot forbid a *score* without naming one — `MomentumScoreIsNotDoctrine`,
    `SCORE_FRAGMENTS`, `scoring` — so the vocabulary the guard needs is the vocabulary it bans.
    **A prohibition guard cannot be inside its own population**, and the exemption is exactly one
    module, named, and PUBLISHED in `values` rather than silently applied.
    """
    assert SELF_EXEMPT == "gate_035_structural_momentum.py"
    assert SELF_EXEMPT in MOMENTUM_MODULES, "exempting a module outside the set would hide nothing"
    for values in (MomentumIsStructural.evaluate().values,
                   MomentumScoreIsNotDoctrine.evaluate().values):
        assert values["modules_exempt"] == [SELF_EXEMPT]


def test_grade_034_publishes_its_arm_count_so_a_dropped_assertion_is_visible():
    """A guard that stops checking a property while still reporting PASS is `B150`'s shape: the
    count of assertions stops corresponding to the count of properties checked."""
    values = MomentumScoreIsNotDoctrine.evaluate().values
    assert values["arms_checked"] == values["arms_expected"] == 3
    assert values["arms_failed"] == []


def test_grade_034s_coupling_arm_names_a_real_path():
    """RANKED FIRST because it is the only arm naming a PATH rather than a vocabulary, and the
    only one with a live consequence — the scale it names sets `risk_pct`."""
    from app.services.rules.gate_035_structural_momentum import (
        RISK_MATRIX_MODULE, RISK_SCALE_MODULE, imported_modules,
    )

    matrix = RULES / f"{RISK_MATRIX_MODULE}.py"
    assert matrix.exists()
    assert any(RISK_SCALE_MODULE in m for m in imported_modules(matrix)), (
        "the coupling this arm guards no longer exists — the arm is asserting a stale path"
    )
    arm = MomentumScoreIsNotDoctrine.arms()["no_path_from_momentum_to_the_risk_scale"]
    assert arm["held"] is True and arm["offenders"] == {}


def test_gate_039_computes_no_trigger_and_says_the_rule_says_so():
    """*"Documented preference with NO automatable trigger."* A rule that says it has no trigger
    and is given one is off-doctrine even if the trigger is sensible."""
    values = DoNotFadeABulletTrain.evaluate(fade_proposed=True).values
    assert values["automatable_trigger"] is False
    assert "no automatable trigger" in values["declared_preference"].lower()


def test_gate_039_is_NOT_APPLICABLE_when_nobody_is_fading():
    """A rule about what to do BEFORE fading has nothing to say when no fade was proposed.
    `None` means NOT ASKED and is distinct from `False`, which means considered and declined."""
    assert DoNotFadeABulletTrain.evaluate().verdict == "NOT_APPLICABLE"
    assert DoNotFadeABulletTrain.evaluate(fade_proposed=False).verdict == "NOT_APPLICABLE"
    assert DoNotFadeABulletTrain.evaluate(fade_proposed=True).verdict == "FAIL", (
        "five of six checklist questions have no producer, so a proposed fade cannot pass today"
    )


def test_gate_039_reads_the_checklist_rather_than_rebuilding_it():
    """A second construction of the same list is `GATE-011`'s shape."""
    from app.services.rules.grade_032_bullet_train import BulletTrainRegime

    assert (
        DoNotFadeABulletTrain.evaluate(fade_proposed=True).values["checklist"]
        == BulletTrainRegime.checklist(None)
    )


def test_grade_037s_two_tiers_separate_on_mitigation_and_not_on_size():
    """THE RULE THE WHOLE CLUSTER LEANS ON. A hundred-unit filled box and a one-unit unfilled one
    must land in different tiers, which no size test could produce."""
    consumed_only = MomentumLeg(0, 10, "UP", imbalances=(_imb(1, fill_state="FILLED", width=1000.0),))
    plus_momentum = MomentumLeg(
        0, 10, "UP",
        imbalances=(_imb(1, fill_state="FILLED", width=1000.0), _imb(2, width=0.01)),
    )
    nothing = MomentumLeg(0, 10, "UP", imbalances=(_imb(1),))

    assert TwoTierTrendGrade.grade(consumed_only) == "STRONG_TREND"
    assert TwoTierTrendGrade.grade(plus_momentum) == "STRONG_TREND_PLUS_MOMENTUM"
    assert TwoTierTrendGrade.grade(nothing) == "NOT_A_TREND", (
        "a leg that consumed no imbalance is not a weak trend — it is not this rule's subject"
    )


def test_grade_037_reports_both_sides_of_the_count_the_statement_asks_for(corpus):
    """*"Count the IMB boxes that were retested versus the Momentum IMB boxes that never were."*
    A comparison, and either number alone cannot express it."""
    _b, _s, _br, _inv, legs = corpus
    leg = next(l for l in legs if len(l.imbalances) > 1)
    values = TwoTierTrendGrade.evaluate(leg).values

    assert values["retested_boxes"] + values["never_retested_boxes"] == values["imbalances_in_leg"]
    assert "fill_state" in values["discriminator"]


def test_grade_037_discriminates_on_real_bars(corpus):
    _b, _s, _br, _inv, legs = corpus
    tiers = {TwoTierTrendGrade.grade(l) for l in legs}
    assert tiers == {"NOT_A_TREND", "STRONG_TREND", "STRONG_TREND_PLUS_MOMENTUM"}, (
        f"a tier is unreachable on real bars: {tiers}"
    )


def test_grade_036_is_NOT_APPLICABLE_when_there_is_nothing_to_compare():
    one = MomentumLeg(0, 10, "UP", imbalances=(_imb(1),))
    slowing = MomentumLeg(0, 10, "UP", imbalances=(_imb(1, width=50.0), _imb(2, width=5.0)))
    speeding = MomentumLeg(0, 10, "UP", imbalances=(_imb(1, width=5.0), _imb(2, width=50.0)))

    assert PreferSlowedMomentum.evaluate(one).verdict == "NOT_APPLICABLE"
    assert PreferSlowedMomentum.evaluate(slowing).verdict == "PASS"
    assert PreferSlowedMomentum.evaluate(speeding).verdict == "FAIL"
    assert PreferSlowedMomentum.evaluate(speeding).values["deviation_is_a_flag_not_a_failure"] is True


def test_grade_038_reports_its_own_declared_inputs_as_unpopulated(corpus):
    """T-0033's SUBJECT, FOUND BY THE RULE THOSE FIELDS WERE DECLARED FOR — the best available
    witness. **A rule reporting that its own declared inputs have no producer is a stronger
    finding than a verdict computed from defaults.**"""
    _b, _s, _br, inventory, _l = corpus
    ev = ImbalancePurposeTest.evaluate(inventory)

    assert ev.verdict == "NOT_APPLICABLE", "a verdict here would be computed from None"
    assert ev.values["imbalances_examined"] == len(inventory) > 100
    assert ev.values["imbalances_classified"] == 0
    assert set(ev.values["fields_not_read"]) == {f for f, _ in PURPOSE_FIELDS}


def test_grade_038s_location_rule_is_implemented_and_reachable():
    """The rule is not merely deferred: the day the fields are populated, the INDUCEMENT versus
    PERMANENT_TREND_CHANGE distinction already works. Asserted on constructed imbalances so the
    NOT_READ above is a statement about the DATA, not about missing logic."""
    import dataclasses

    base = _imb(1)
    before = dataclasses.replace(base, purpose_verdict="FAILED", target_cleared_at_failure=False)
    after = dataclasses.replace(base, purpose_verdict="FAILED", target_cleared_at_failure=True)
    served = dataclasses.replace(base, purpose_verdict="SERVED")

    assert ImbalancePurposeTest.classify(before)["meaning"] == "INDUCEMENT"
    assert ImbalancePurposeTest.classify(after)["meaning"] == "PERMANENT_TREND_CHANGE"
    assert ImbalancePurposeTest.classify(served)["meaning"] == "SERVED"
    assert ImbalancePurposeTest.classify(base)["not_read"] == "purpose_verdict"


def test_all_nine_targets_are_now_implemented_and_gate_034_still_is_not():
    """THE WAVE'S OWN CENSUS, with the must-miss arm on the same lookup."""
    impl = implementations()
    for rid in ("GRADE-032", "GRADE-027", "GRADE-028", "GATE-035", "GATE-039",
                "GRADE-036", "GRADE-037", "GRADE-038", "GRADE-034"):
        assert rid in impl, f"{rid} was named by T-0039 and is not implemented"

    assert "GATE-034" not in impl, "GATE-034 is WITHDRAWN and a wave must not complete it"
    assert contract.rule("GATE-034").get("status") == "WITHDRAWN"


def test_the_guarded_set_is_the_cluster_this_task_built():
    """MOMENTUM_MODULES is ENUMERATED — these rules share no registry `layer` and no filename
    pattern, so `T-0032`'s derivation has nothing to key on. **This is the converse assertion:**
    every module implementing one of the nine must be in the guarded set, so a member added
    without being watched fails BY NAME rather than going quietly unguarded."""
    impl = implementations()
    modules = {
        impl[rid].__module__.rsplit(".", 1)[-1] + ".py"
        for rid in ("GRADE-032", "GRADE-027", "GRADE-028", "GATE-035", "GATE-039",
                    "GRADE-036", "GRADE-037", "GRADE-038", "GRADE-034")
    }
    missing = modules - set(MOMENTUM_MODULES)
    assert not missing, f"momentum modules outside GATE-035's guarded set: {sorted(missing)}"
