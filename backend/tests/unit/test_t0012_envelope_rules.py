"""GATE-017 / GATE-019 / GRADE-031 / GATE-041 — the trading envelope (T-0012).

WHY EVERY TEST HERE IS TWO-DIRECTIONAL
`check_rule_coverage.py` proves REGISTRATION, not behaviour — the package's own
`__init__.py` says "a rule can be registered and still only half built". So the count going
34 -> 38 is not evidence this task worked. Each rule below is therefore proved by a verdict
that can go either way, never by its presence.

Two of these rules cannot fail on live data, which is the trap:

  * GATE-017 passes on every bar, because T-0007 moved the engine to `ENTRY_TF = "5m"`.
  * GATE-041 returns CONTINUE forever, because three of its seven conditions have no
    producer at all.

A gate that has only ever passed is indistinguishable from a gate that cannot fail, so both
are driven from synthetic fixtures in both directions.
"""
from __future__ import annotations

import pytest

from app.services.rules import (
    ANALYSIS_ONLY_TFS,
    CONDITIONS,
    DECLARED_QUORUMS,
    MANDATORY_CONDITION,
    TRADING_MODE,
    AnalysisOnlyTimeframes,
    ConditionReading,
    DayTradingMode,
    DeclaredQuorum,
    QuorumNotDeclared,
    QuorumsAreDeclaredParameters,
    ReverseSwitchConfirmations,
    normalise_tf,
)
from app.services.telemetry import validate as val

# ---------------------------------------------------------------------------
# GATE-017 — criterion 2's mutation: the gate must be MADE to fail
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tf", ["M", "W", "D", "4H", "2H", "1H"])
def test_every_analysis_only_timeframe_is_a_violation(tf):
    """All six from the statement, not a sample. The set is the rule."""
    ev = AnalysisOnlyTimeframes.evaluate(signal_tf=tf)
    assert ev.verdict == "FAIL", f"{tf} is ANALYSIS ONLY and did not fail"
    assert tf in ev.values["violation"]


@pytest.mark.parametrize("tf", ["5m", "15m", "30m", "1m"])
def test_execution_timeframes_pass(tf):
    """The other direction. A gate that only ever fails is as useless as one that never does."""
    assert AnalysisOnlyTimeframes.evaluate(signal_tf=tf).verdict == "PASS"


def test_the_htf_set_is_enumerated_not_inferred_from_duration():
    """THE B33 GUARD. `2H` and `120m` are the same duration and must not be two answers.

    Inferring the set by comparing magnitudes is the seductive implementation, and this
    repo has paid for that class twice — `gate_008_roster.py` compares timeframe STRINGS,
    and `schema_tf()` exists only because lowercase met an uppercase enum.
    """
    assert ANALYSIS_ONLY_TFS == frozenset({"M", "W", "D", "4H", "2H", "1H"})
    # Spellings the codebase actually uses must fold to the statement's vocabulary...
    assert normalise_tf("1h") == "1H" and normalise_tf("1d") == "D"
    assert AnalysisOnlyTimeframes.evaluate(signal_tf="1h").verdict == "FAIL", (
        "a lowercase HTF escaped the gate — the case difference that cost forty minutes"
    )
    # ...and a duration-equivalent spelling that the STATEMENT does not name is not
    # silently promoted into the set. Recording the limit rather than pretending it is
    # covered: `120m` is 2H by arithmetic and is not in the statement's list.
    assert AnalysisOnlyTimeframes.evaluate(signal_tf="120m").verdict == "PASS"


def test_the_live_engine_configuration_is_compliant():
    """`ENTRY_TF` is the trigger and must not be analysis-only; `BIAS_TF` may be."""
    from app.services.live.fixed_config import BIAS_TF, ENTRY_TF

    assert AnalysisOnlyTimeframes.evaluate(signal_tf=ENTRY_TF).verdict == "PASS"
    assert AnalysisOnlyTimeframes.evaluate(signal_tf=BIAS_TF).verdict == "FAIL", (
        "BIAS_TF is Daily and Daily IS analysis-only — this asserts the gate would catch "
        "a bias timeframe used as a trigger, not that the bias is misconfigured"
    )


# ---------------------------------------------------------------------------
# GATE-019 — criterion 5: the consequence, not the constant
# ---------------------------------------------------------------------------

def test_the_mode_constant_uses_the_schema_spelling():
    """One quantity, one spelling. `shadow.py` already emits `DAY_TRADE`.

    Declaring `day_trading` here would have created a second vocabulary for the mode —
    the defect that took the shadow dark for forty minutes, reintroduced deliberately.
    """
    assert TRADING_MODE == "DAY_TRADE"
    assert DayTradingMode.evaluate().values["trading_mode"] == "DAY_TRADE"


def test_gate_019_reports_that_nothing_consumes_it():
    """An honest empty list, not an implied enforcement.

    The rule's substance is that session gates lose their swing-mode false branch. No
    session gate exists, so the consequence is UNENFORCED — and a record claiming
    consumers it does not have would be the coverage count lying one layer down.
    """
    ev = DayTradingMode.evaluate()
    assert ev.values["session_gate_consumers"] == []
    assert ev.values["swing_mode_available"] is False
    assert DayTradingMode.COVERAGE_NOTE and "UNENFORCED" in DayTradingMode.COVERAGE_NOTE


# ---------------------------------------------------------------------------
# GRADE-031 — criterion 9's mutation: a hard-coded quorum must be CAUGHT
# ---------------------------------------------------------------------------

def test_a_bare_number_is_refused_at_the_point_of_use():
    """THE MUTATION. Bypass the declared set, pass a literal, fail on the TYPE.

    A load-time config validation satisfies the words of GRADE-031 and a literal written
    inside a decision function sails past it: by then `4` from the declared set and a
    hard-coded `4` are the same object. The carrier is what makes them different.
    """
    with pytest.raises(QuorumNotDeclared, match="not as int"):
        ReverseSwitchConfirmations.evaluate(quorum=4)


def test_a_quorum_declared_for_another_rule_is_refused():
    """Right type, wrong parameter — this would attribute the decision to the wrong number."""
    other = DeclaredQuorum(name="d4_quorum", value=2, of_total=3)
    with pytest.raises(QuorumNotDeclared, match="expected q6_quorum"):
        ReverseSwitchConfirmations.evaluate(quorum=other)


def test_the_declared_quorum_is_stamped_as_ours_and_unratified():
    """Criterion 7. The record must not imply Salim chose the value."""
    q = DECLARED_QUORUMS["q6_quorum"]
    assert q.ratified is False, "an invented threshold is claiming ratification"
    assert q.rule_id == "GRADE-031" and q.version
    assert "OURS" in q.rationale
    assert q.as_declared_parameter() == "GRADE-031.q6_quorum@ours-v1"


def test_a_quorum_outside_its_range_is_rejected_at_construction():
    with pytest.raises(ValueError):
        DeclaredQuorum(name="q6_quorum", value=8, of_total=7)
    with pytest.raises(ValueError):
        DeclaredQuorum(name="q6_quorum", value=0, of_total=7)


def test_grade_031_reports_observed_counts_beside_the_chosen_value():
    """Criterion 8. Without the observed count the parameter is unfalsifiable.

    A boolean 'quorum met' alone makes it impossible to tell later whether 4-of-7 was
    generous or strict on real data.
    """
    ev = QuorumsAreDeclaredParameters.evaluate(observed_counts={"q6_satisfied": 3})
    assert ev.values["q6_quorum"] == 4
    assert ev.values["observed_q6_satisfied"] == 3
    assert ev.values["q6_quorum_ratified"] is False


# ---------------------------------------------------------------------------
# GATE-041 — criteria 10b / 10c
# ---------------------------------------------------------------------------

def _all(state: str) -> list[ConditionReading]:
    return [ConditionReading(name, state) for name, _ in CONDITIONS]


def test_gate_041_can_authorise_a_reverse():
    """CRITERION 10b. The gate must be shown CAPABLE of firing.

    Live data can never exercise this — three conditions have no producer — so without a
    fixture GATE-041 returns CONTINUE forever and is indistinguishable from a broken gate.
    """
    ev = ReverseSwitchConfirmations.evaluate(_all("TRUE"))
    assert ev.verdict == "PASS"
    assert ev.values["outcome"] == "REVERSE"
    assert ev.values["satisfied_count"] == 7


def test_flipping_the_mandatory_condition_returns_continue():
    """The other direction, on the declared-mandatory member specifically."""
    readings = [
        ConditionReading(n, "FALSE" if n == MANDATORY_CONDITION else "TRUE")
        for n, _ in CONDITIONS
    ]
    ev = ReverseSwitchConfirmations.evaluate(readings)
    assert ev.values["outcome"] == "CONTINUE"
    assert ev.values["mandatory_satisfied"] is False
    # Six of seven is over the quorum, so ONLY the mandatory rule can have stopped it.
    assert ev.values["satisfied_count"] == 6 >= ev.values["q6_quorum"]


def test_below_the_quorum_returns_continue():
    readings = [
        ConditionReading(n, "TRUE" if i < 3 else "FALSE")
        for i, (n, _) in enumerate(CONDITIONS)
    ]
    assert ReverseSwitchConfirmations.evaluate(readings).values["outcome"] == "CONTINUE"


def test_live_evaluation_marks_exactly_the_unproduced_conditions():
    """CRITERION 10b's live half — not zero, and not seven.

    NOTE A PLAN INCONSISTENCY, resolved in favour of the registry: criterion 10b says
    'exactly the two momentum conditions', but the plan's own STEP 0 table lists THREE
    without producers — momentum deteriorating, momentum-imbalance failures, AND price
    slows after the destination (which needs GRADE-035, removed from this task). Three is
    correct; the criterion's 'two' is a miscount.
    """
    ev = ReverseSwitchConfirmations.evaluate()
    assert ev.verdict == "NOT_APPLICABLE"
    assert ev.values["outcome"] == "CONTINUE"
    assert ev.values["not_evaluable_count"] == 3, (
        f"expected 3 unproduced conditions, got {ev.values['not_evaluable_count']}"
    )
    assert set(ev.values["not_evaluable"]) == {
        "price_slows_after_destination",
        "momentum_deteriorating",
        "momentum_imbalance_failures",
    }
    # Each names WHY, so "no producer exists" cannot be read as "the producer found nothing".
    assert all("GRADE-028" in v for v in ev.values["not_evaluable"].values())


def test_no_quorum_is_claimed_while_a_condition_is_unreadable():
    """Scoring 4-of-7 with three unreadable would report a decision never actually taken.

    The denominator would silently be four. The rule's own documented default is the
    faithful answer: 'absent them the default is CONTINUE'.
    """
    ev = ReverseSwitchConfirmations.evaluate()
    assert ev.verdict == "NOT_APPLICABLE", (
        "a verdict of PASS/FAIL claims the quorum was scored against all seven"
    )


def test_the_evaluations_validate_inside_a_real_record():
    """Every rule's telemetry must survive the REAL validator on the REAL record shape.

    T-0007 shipped a shadow that went dark for forty minutes because a block was checked
    against expectations rather than against the schema.

    THE FIRST VERSION OF THIS TEST WAS VACUOUS AND I WROTE IT. It called
    `val.errors_for_rule_evaluation(...)` behind a `hasattr` guard — and that function does
    not exist, so it compared `[] == []` and would have passed against any rule producing
    anything. That is `test_shadow_correlate_panels.py:414`'s defect exactly, reproduced in
    the task whose theme is that a check which cannot fail is decorative. There is no
    per-evaluation validator, so the evaluations are validated where they actually live:
    inside a `setup_evaluation`, through `val.errors`.
    """
    from datetime import datetime, timezone

    from app.services.telemetry import records as rec

    evaluations = [
        AnalysisOnlyTimeframes.evaluate(signal_tf="1H"),
        DayTradingMode.evaluate(),
        QuorumsAreDeclaredParameters.evaluate(),
        ReverseSwitchConfirmations.evaluate(),
        ReverseSwitchConfirmations.evaluate(_all("TRUE")),
    ]
    record = rec.setup_evaluation(
        timestamp=datetime(2026, 8, 14, 13, 0, tzinfo=timezone.utc),
        declared=rec.DeclaredParameters(
            virtual_account_size=5_000.0,
            evaluation_order_id="magic-v1",
            emission_policy_id="every-closed-bar-with-sufficient-history-v2",
            layout_size_frozen=True,
            main_asset_counts=False,
            box_scope="ENTRY_BOX_EXEC_TF",
            stop_selection_reading="CLOSEST_TO_3R_TIES_TO_LARGER",
            runner_management_policy="70_30_partial_then_runner",
            reverse_quorum=None,
        ),
        scan_context={
            "scan_id": "scan-1", "sequence_no": 1,
            "candidate_origin": "SCHEDULED_BAR_CLOSE",
            "bar_close_time_ny": "2026-08-14T09:00:00-04:00",
            "data_as_of_ny": "2026-08-14T09:00:05-04:00",
            "pre_filters_applied": [],
        },
        instrument={"symbol": "BTCUSDT.P", "instrument_class": "ALIGNED_MAJOR",
                    "venue": "BINANCE_FUTURES"},
        mode={"trading_mode": TRADING_MODE, "direction_mode": "FORWARD"},
        timeframes={"signal_tf": "5M", "alignment_tf": "5M", "analysis_tfs_scanned": ["1D"]},
        session={"ny_local_time": "2026-08-14T09:00:00-04:00", "tz_offset_used": "-04:00",
                 "in_magic_zone": False, "minutes_from_nyo": -30},
        primitives={"swing_points": [], "structure_boxes": [], "imbalances": [],
                    "liquidity_pools": [], "sweeps": [], "breaks": []},
        correlates={"layout_size": 4, "disturbed_count": 0,
                    "disturbance_grade": "NONE", "states": []},
        rule_evaluations=evaluations,
        decision="SKIP",
        deciding_rule_id="GATE-017",
        risk_assessment={"box_grade": "STANDARD", "risk_pct": 0.01},
    )

    errs = val.errors(record)
    assert errs == [], f"the four rules produced an invalid record: {errs[:3]}"

    # And the mode this task declares must be the one the schema accepts — proving the
    # spelling decision rather than asserting it in a comment.
    assert record["mode"]["trading_mode"] == "DAY_TRADE"


# ---------------------------------------------------------------------------
# The shared invariant (Manager's second amendment to criterion 9)
# ---------------------------------------------------------------------------

def test_the_blocked_helper_requires_its_default_from_the_caller():
    """No fallback in the signature — a rule must not inherit a default direction.

    GATE-041 defaults to CONTINUE and GRADE-035 will default the opposite way, both
    conservative for their own statement. A helper carrying either default would let the
    other rule silently inherit the wrong one, and that is the mistake nobody can catch by
    reading the two side by side, because they are SUPPOSED to differ there.
    """
    from app.services.rules import quorum_blocked

    with pytest.raises(TypeError):
        quorum_blocked([ConditionReading("x", "TRUE")])  # no default_outcome


def test_the_helper_reports_blocked_only_when_something_is_unreadable():
    from app.services.rules import quorum_blocked

    readable = [ConditionReading("a", "TRUE"), ConditionReading("b", "FALSE")]
    assert quorum_blocked(readable, default_outcome="CONTINUE") is None

    blocked = quorum_blocked(
        readable + [ConditionReading("c", "NOT_EVALUABLE", missing_producer="GRADE-028")],
        default_outcome="CONTINUE",
    )
    assert blocked is not None
    unreadable, default = blocked
    assert unreadable == {"c": "GRADE-028"} and default == "CONTINUE"


def test_a_reading_cannot_be_unevaluable_without_naming_its_missing_producer():
    """An unattributable absence is indistinguishable from a broken check."""
    with pytest.raises(ValueError, match="names no missing producer"):
        ConditionReading("x", "NOT_EVALUABLE")
    with pytest.raises(ValueError):
        ConditionReading("x", "TRUE", missing_producer="GRADE-028")


# ---------------------------------------------------------------------------
# NOT_READ — a producer that exists and was never called (REVIEW_FAIL 0076)
# ---------------------------------------------------------------------------

def test_producer_backed_conditions_are_not_reported_as_FALSE():
    """FALSE asserts the producer RAN and found nothing. None of them have been called.

    The first version of this rule recorded all four producer-backed conditions as FALSE,
    which is the conflation `ConditionReading`'s own docstring forbids — written four lines
    above it.
    """
    ev = ReverseSwitchConfirmations.evaluate()
    states = ev.values["conditions"]
    for name, producer in CONDITIONS:
        if producer is not None:
            assert states[name] == "NOT_READ", (
                f"{name} has producer {producer} and is reported {states[name]} — FALSE "
                "claims the producer ran"
            )
    assert ev.values["unread_count"] == 4
    # The two absences stay APART in the record, each naming its producer.
    assert set(ev.values["not_read"]) == {
        "new_opposite_imbalances", "failed_imbalances_became_sr_flips",
        "new_imbalances_hold_price", "micro_msb_confirms",
    }
    assert ev.values["not_read"]["micro_msb_confirms"] == "PRIM-005"
    assert "micro_msb_confirms" not in ev.values["not_evaluable"]


def test_the_blocked_flag_and_the_unread_conditions_must_agree():
    """THE LOAD-BEARING GUARD, evaluated against the REAL flag, not a patched one.

    Today the three NOT_EVALUABLE conditions short-circuit the quorum, so the unread ones
    change no verdict. The day GRADE-028 lands, someone clears `CANNOT_FIRE_WITHOUT` — and
    if the producers are still unwired, `micro_msb_confirms` (the MANDATORY condition)
    silently decides every evaluation. The flag that currently tells the truth would be
    removed by the same edit that activates the bug.

    So the two are COUPLED here: clearing the flag while anything is still unread turns
    this red. That is the requirement — not the state name — and it is why the assertion
    reads the live class attribute rather than a fixture.
    """
    from app.services.rules.base import quorum_blocked
    from app.services.rules.gate_041_reverse_switch import _live_readings

    readings = _live_readings()
    unread = [r.name for r in readings if r.state == "NOT_READ"]

    if not ReverseSwitchConfirmations.CANNOT_FIRE_WITHOUT:
        assert not unread, (
            f"GATE-041 declares itself unblocked while {len(unread)} producer-backed "
            f"conditions were never read: {unread}. Clearing CANNOT_FIRE_WITHOUT must not "
            "be sufficient to make the rule fire — wire the producers or keep the flag."
        )
        assert quorum_blocked(readings, default_outcome="CONTINUE") is None
    else:
        # The flag is set, so the rule must actually BE blocked. A stale flag on a rule
        # that can score is the same defect pointing the other way.
        assert quorum_blocked(readings, default_outcome="CONTINUE") is not None, (
            "GATE-041 carries CANNOT_FIRE_WITHOUT but every condition is readable — the "
            "flag is stale and is suppressing a rule that could decide"
        )


# ---------------------------------------------------------------------------
# The consolidation detector (T-0014 Part 1) — the threshold is the rule
# ---------------------------------------------------------------------------

def test_the_detector_distinguishes_a_range_from_a_trend():
    """Necessary, and NOT sufficient — see the next test for why."""
    from datetime import datetime, timedelta, timezone

    from app.services.rules import consolidation as C
    from app.services.rules.prim_001_swings import Bar

    t0 = datetime(2026, 8, 14, tzinfo=timezone.utc)

    def bar(i, lo, hi):
        return Bar(time=t0 + timedelta(minutes=5 * i), high=hi, low=lo,
                   open=(lo + hi) / 2, close=(lo + hi) / 2)

    ranging = [bar(i, 100 + (i % 2), 101 + (i % 2)) for i in range(C.WINDOW_BARS)]
    trending = [bar(i, 100 + 3 * i, 101 + 3 * i) for i in range(C.WINDOW_BARS)]

    th = C.DECLARED_THRESHOLD
    assert C.detect_window(ranging, tf="5m", threshold=th).is_consolidation is True
    assert C.detect_window(trending, tf="5m", threshold=th).is_consolidation is False


def test_the_fixture_pair_cannot_bound_the_threshold():
    """THE POINT OF CRITERION 4a, asserted rather than argued.

    Every k from 2.0 to 5.0 passes the test above, because a range fixture is tighter than
    a trend fixture BY CONSTRUCTION — while those same settings call 0.1% and 86.3% of real
    windows consolidation. So the fixtures prove the detector discriminates and say nothing
    about where the boundary sits, and the boundary is the whole rule.
    """
    from datetime import datetime, timedelta, timezone

    from app.services.rules import consolidation as C
    from app.services.rules.prim_001_swings import Bar

    t0 = datetime(2026, 8, 14, tzinfo=timezone.utc)

    def bar(i, lo, hi):
        return Bar(time=t0 + timedelta(minutes=5 * i), high=hi, low=lo,
                   open=(lo + hi) / 2, close=(lo + hi) / 2)

    ranging = [bar(i, 100 + (i % 2), 101 + (i % 2)) for i in range(C.WINDOW_BARS)]
    trending = [bar(i, 100 + 3 * i, 101 + 3 * i) for i in range(C.WINDOW_BARS)]

    for k in (2.0, 3.0, 4.0, 5.0):
        th = C.ConsolidationThreshold(k=k, measured_rate_pct=0.0, measured_tf="5m",
                                      measured_bars=0, measured_span="fixture")
        assert C.detect_window(ranging, tf="5m", threshold=th).is_consolidation is True
        assert C.detect_window(trending, tf="5m", threshold=th).is_consolidation is False


def test_the_declared_threshold_carries_its_measured_rate_and_stays_in_band():
    """A bare k is unfalsifiable. The rate is what makes the declaration checkable.

    A ceiling alone is not enough: the detector could satisfy it by never firing, which
    refuses every reversal instead of permitting every one. Both ends stop discriminating.
    """
    from app.services.rules import consolidation as C

    th = C.DECLARED_THRESHOLD
    assert th.ratified is False, "an invented definition is claiming ratification"
    assert th.rate_is_within_bounds(), (
        f"{th.measured_rate_pct}% is outside {th.rate_floor_pct}-{th.rate_ceiling_pct}%"
    )
    assert th.rate_floor_pct > 0, "a floor of zero permits a detector that never fires"
    assert th.measured_tf == "5m", "the rate must be measured at ENTRY_TF, not at 1H"
    assert "NOT enough to claim it is representative" in th.corpus_caveat


def test_too_few_bars_returns_none_rather_than_not_consolidation():
    """'We cannot say' and 'we looked and it is trending' are different facts."""
    from app.services.rules import consolidation as C

    assert C.detect_window([], tf="5m", threshold=C.DECLARED_THRESHOLD) is None


# ---------------------------------------------------------------------------
# GATE-040 / GRADE-035 (T-0014 part 2)
# ---------------------------------------------------------------------------

def _window(consolidating: bool):
    from datetime import datetime, timedelta, timezone

    from app.services.rules import consolidation as C
    from app.services.rules.prim_001_swings import Bar

    t0 = datetime(2026, 8, 14, tzinfo=timezone.utc)
    step = 0 if consolidating else 3
    bars = [
        Bar(time=t0 + timedelta(minutes=5 * i), high=101 + step * i + (i % 2),
            low=100 + step * i + (i % 2), open=100.5, close=100.5)
        for i in range(C.WINDOW_BARS)
    ]
    return C.detect_window(bars, tf="5m", threshold=C.DECLARED_THRESHOLD)


def _all_readable():
    from app.services.rules.gate_040_cool_off import INPUT_UNION

    return [ConditionReading(n, "TRUE") for n, _ in INPUT_UNION]


def test_the_declared_duration_is_not_compared_by_default():
    """CRITERION 5. `if elapsed >= 24H` is the forbidden implementation.

    The number is in quotation marks in the statement, which is exactly why an implementer
    writes the comparison. Both registry entries bind: 'DO NOT HARDEN THEM INTO A RULE
    WITHOUT A RULING', and the canon omits rather than retires them so they stand
    UNOPPOSED — which is not ratified. The elapsed time is an OUTPUT either way.
    """
    from datetime import timedelta

    from app.services.rules import DECLARED_COOL_OFF, CoolOffBeforeReversal

    assert DECLARED_COOL_OFF.ratified is False
    assert "unopposed is not ratified" in DECLARED_COOL_OFF.source

    # One minute since the sweep, far under 24H — and still satisfied, because the
    # duration is not enforced by default.
    ev = CoolOffBeforeReversal.evaluate(
        consolidation=_window(True), readings=_all_readable(),
        elapsed_since_sweep=timedelta(minutes=1),
    )
    assert ev.values["duration_enforced"] is False
    assert ev.values["cool_off"]["satisfied"] is True, (
        "a 1-minute cool-off was refused — the 24H quotation has been hardened"
    )
    # But the elapsed time is still reported, which is what the output shape asks for.
    assert ev.values["cool_off"]["elapsed_duration"] == 60


def test_enforcing_the_duration_is_opt_in_and_then_it_bites():
    from datetime import timedelta

    from app.services.rules import CoolOffBeforeReversal

    short = CoolOffBeforeReversal.evaluate(
        consolidation=_window(True), readings=_all_readable(),
        elapsed_since_sweep=timedelta(minutes=1), enforce_duration=True,
    )
    assert short.values["cool_off"]["satisfied"] is False
    long = CoolOffBeforeReversal.evaluate(
        consolidation=_window(True), readings=_all_readable(),
        elapsed_since_sweep=timedelta(hours=30), enforce_duration=True,
    )
    assert long.values["cool_off"]["satisfied"] is True


def test_a_sweep_with_no_cool_off_is_refused_and_one_with_cool_off_permitted():
    """CRITERION 7's mutation, both directions."""
    from app.services.rules import CoolOffBeforeReversal

    no_cool = CoolOffBeforeReversal.evaluate(
        consolidation=_window(False), readings=_all_readable()
    )
    assert no_cool.verdict == "FAIL" and no_cool.values["mode"] == "FORWARD"

    cooled = CoolOffBeforeReversal.evaluate(
        consolidation=_window(True), readings=_all_readable()
    )
    assert cooled.verdict == "PASS" and cooled.values["mode"] == "REVERSE"


def test_the_alias_input_union_is_recorded_per_input():
    """CRITERION 4c. GRADE-035 must not read as covered while its inputs are absent.

    The pair declares DIFFERENT inputs, so registering GATE-040 registers GRADE-035 — and
    the alias mechanism cannot see that three of GRADE-035's four declared dependencies
    were missing. Recording the union per input is what stops the coverage line lying.
    """
    from app.services.rules import CoolOffBeforeReversal

    ev = CoolOffBeforeReversal.evaluate()
    assert ev.verdict == "NOT_APPLICABLE"
    assert ev.values["mode"] == "FORWARD", "an unreadable prerequisite authorised a reversal"

    # The 9:30 marker has NO producer — it must not be reported as merely unwired, and it
    # must never be derived from the clock.
    assert "ny_930_open_marker" in ev.values["not_evaluable"]
    assert "ny_930_open_marker" not in ev.values["not_read"]
    # The detector this task built exists, so its input is unwired rather than absent.
    assert "consolidation_detector" in ev.values["not_read"]
    assert ev.values["not_read"]["consolidation_detector"] == "rules/consolidation.py"


def test_grade_035_is_registered_by_alias_and_marked_unable_to_fire():
    from app.services.rules import implementations

    impls = implementations()
    assert impls["GRADE-035"] is impls["GATE-040"]
    assert impls["GRADE-035"].CANNOT_FIRE_WITHOUT == ("GRADE-028",)
