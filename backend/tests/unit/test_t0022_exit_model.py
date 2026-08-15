"""T-0022 — EXIT-001's 70/30 model and EXIT-002's ladder-off constraint.

These tests exist to fail. Where a test could pass with the defect its criterion names
still in place, the test says so in its own docstring and asserts the distinguishing thing
instead — five of the previous session's seven "passing" mutations turned out to be vacuous
tests rather than correct code (register B70/B80), so a green count here is not the claim.
"""
from __future__ import annotations

import ast
import inspect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services.rules import exit_001_v1_model as model
from app.services.rules.exit_001_v1_model import (
    EXIT_001_REASONS,
    FINAL_TARGET,
    PARTIAL_2R,
    PARTIAL_AT_R,
    PARTIAL_FRACTION,
    RUNNER_FRACTION,
    SCHEMA_ONLY_REASONS,
    SESSION_CLOSE,
    STOP_HIT,
    TERMINAL_REASONS,
    DECLARED_SESSION_CLOSE,
    DegenerateRunner,
    ExitEvent,
    TradePlan,
    V1ExitModel,
    next_session_close_after,
    ticks_from_prices,
)
from app.services.rules.exit_002_ladder_off import (
    LADDER_SIGNATURE,
    MAX_TRANCHES,
    LadderOffForV1,
    assert_v1_exit_shape,
    ladder_violations,
)
from app.services.telemetry import contract_loader as contract

UTC = timezone.utc

#: A long with 5 points of risk: entry 100, stop 95, 2R at 110, target well beyond it.
#: Every level is a round number so a wrong one is visible in the failure message rather
#: than needing to be recomputed by the reader.
LONG_PLAN = TradePlan(side="LONG", entry=100.0, stop=95.0, final_target=130.0)
SHORT_PLAN = TradePlan(side="SHORT", entry=100.0, stop=105.0, final_target=70.0)

#: 10:00 EDT — mid-session, hours before the 19:00 close, so no test that is not ABOUT the
#: session close accidentally depends on it.
MORNING_EDT = datetime(2026, 7, 15, 14, 0, tzinfo=UTC)


def _ev(reason: str, fraction: float, price: float = 100.0, minutes: int = 0) -> ExitEvent:
    return ExitEvent(
        timestamp=MORNING_EDT + timedelta(minutes=minutes),
        fraction=fraction,
        price=price,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Criterion 1 — exactly three terminal conditions, and a fourth is a defect
# ---------------------------------------------------------------------------
def test_the_terminal_conditions_are_exactly_three_and_the_partial_is_not_one():
    assert TERMINAL_REASONS == ("FINAL_TARGET", "STOP_HIT", "SESSION_CLOSE")
    assert PARTIAL_2R not in TERMINAL_REASONS, (
        "the 2R partial CREATES the runner; counting it as a terminal condition is how "
        "'70% at 2R' silently becomes 'close at 2R'"
    )
    assert set(EXIT_001_REASONS) == {*TERMINAL_REASONS, PARTIAL_2R}
    assert len(EXIT_001_REASONS) == 4


@pytest.mark.parametrize("bad", ["LIQUIDATION", "MANUAL_OVERRIDE", "TRAILING_STOP", ""])
def test_a_fifth_exit_reason_cannot_be_constructed(bad):
    with pytest.raises(ValueError, match="not one of EXIT-001's four"):
        _ev(bad, 1.0)


def test_the_telemetry_schema_permits_reasons_this_rule_does_not_so_the_check_is_ours():
    """CRITERION 1 IS NOT ENFORCEABLE BY SCHEMA VALIDATION, and this is the proof.

    A test that only asserted "our four reasons validate against the schema" would pass
    while `LIQUIDATION` also validated — which is exactly the hole criterion 1 names. So
    this asserts the SUPERSET relationship directly: the schema is wider on purpose
    (SIZE-003 keeps a margin liquidation distinct from the strategy's stop working), and
    the narrowing to four is therefore the rule's job and nobody else's.
    """
    schema = json.loads(
        (
            Path(model.__file__).parents[2]
            / "services"
            / "telemetry"
            / "contract"
            / "TELEMETRY_SCHEMA.json"
        ).read_text()
    )
    schema_reasons = set(schema["$defs"]["exit_event"]["properties"]["reason"]["enum"])

    assert set(EXIT_001_REASONS) < schema_reasons, (
        "EXIT-001's reasons must be a STRICT subset of the schema's enum — if they were "
        "equal, schema validation would enforce criterion 1 and this rule's own check "
        "would be redundant; if they were not a subset, our records would not validate"
    )
    assert schema_reasons - set(EXIT_001_REASONS) == set(SCHEMA_ONLY_REASONS)
    # The narrowing is real: something the schema accepts, the rule refuses.
    for extra in SCHEMA_ONLY_REASONS:
        with pytest.raises(ValueError):
            _ev(extra, 1.0)


def test_a_closed_position_with_no_terminal_condition_is_a_violation():
    """Criterion 1's 'a runner that ends without one of the three'."""
    sim = model.ExitSimulation(
        plan=LONG_PLAN,
        events=(_ev(PARTIAL_2R, 1.0, price=110.0),),  # the whole position, on the partial
        runner_open=False,
        remaining_fraction=0.0,
        session_close_active=True,
    )
    ev = V1ExitModel.evaluate(sim)
    assert ev.verdict == "FAIL"
    assert any("no terminal condition" in v for v in ev.values["violations"])


def test_an_unfinished_path_is_not_applicable_rather_than_a_pass():
    """Silence is not a pass (C-04), and it is not a violation either.

    'The path ran out' and 'the runner ended without one of the three' are different facts.
    Collapsing them would make every open position read as a broken rule.
    """
    sim = V1ExitModel.simulate(LONG_PLAN, ticks_from_prices(MORNING_EDT, [100, 105]))
    ev = V1ExitModel.evaluate(sim)
    assert ev.verdict == "NOT_APPLICABLE"
    assert "still open" in ev.values["not_applicable_reason"]
    assert "violations" not in ev.values


# ---------------------------------------------------------------------------
# Criterion 2 — 70% and 30% are doctrine, not parameters
# ---------------------------------------------------------------------------
def test_the_split_comes_from_the_registry_not_from_a_literal():
    values = contract.rule("EXIT-001")["values"]
    assert (PARTIAL_FRACTION, PARTIAL_AT_R, RUNNER_FRACTION) == (
        values["partial_fraction"],
        values["partial_at_r"],
        values["runner_fraction"],
    )
    assert (PARTIAL_FRACTION, PARTIAL_AT_R, RUNNER_FRACTION) == (0.7, 2.0, 0.3)
    assert PARTIAL_FRACTION + RUNNER_FRACTION == pytest.approx(1.0)


def test_no_call_site_can_choose_a_different_split():
    """CRITERION 2 IS A STRUCTURAL CLAIM, so this is a structural test.

    Asserting `PARTIAL_FRACTION == 0.7` does not show the split is unconfigurable — a
    module constant plus a `partial_fraction=` keyword would satisfy it and hand every
    caller a knob. So this reads the signature: there must be no parameter through which a
    fraction or an R-multiple can be supplied. A declared parameter is for a value the
    trader declined to fix; these are quoted doctrine, so a knob would invent discretion.
    """
    params = set(inspect.signature(V1ExitModel.simulate).parameters)
    assert params == {"plan", "ticks", "session_close_active"}, (
        "simulate() grew a parameter. If it is a way to vary the 70/30 split or the 2R "
        "level, criterion 2 forbids it."
    )
    forbidden = ("fraction", "partial", "runner", "_r", "ratio", "split")
    for name in params:
        assert not any(f in name.lower() for f in forbidden), name

    # And the plan itself carries no override — 2R is derived from entry and stop alone.
    plan_fields = set(inspect.signature(TradePlan).parameters)
    assert plan_fields == {"side", "entry", "stop", "final_target"}


# ---------------------------------------------------------------------------
# Criterion 3 / 3a — the partial banks 70% and the runner SURVIVES it
# ---------------------------------------------------------------------------
def test_reaching_2r_closes_exactly_70_percent_and_leaves_30_open():
    """Criterion 3. The current live behaviour — close 100% at tp — fails this."""
    sim = V1ExitModel.simulate(
        LONG_PLAN, ticks_from_prices(MORNING_EDT, [100, 105, 110])
    )
    assert len(sim.events) == 1
    partial = sim.events[0]
    assert partial.reason == PARTIAL_2R
    assert partial.fraction == 0.7
    assert partial.price == 110.0                      # entry 100 + 2 * 5R
    assert partial.realised_r == pytest.approx(2.0)
    assert sim.runner_open is True
    assert sim.remaining_fraction == pytest.approx(0.3)


def test_the_runner_is_still_open_at_30_percent_on_the_tick_after_the_partial():
    """CRITERION 3a — the failure mode that passes criterion 3's first half alone.

    Banking 70% and closing the remaining 30% in the same tick produces a correct-looking
    partial event and a flat position. So the assertion has to be about the tick AFTER: the
    partial fires at 110, and at 112 the position is still open, still 30%, with no second
    event.
    """
    ticks = ticks_from_prices(MORNING_EDT, [100, 110, 112])
    sim = V1ExitModel.simulate(LONG_PLAN, ticks)

    assert [e.reason for e in sim.events] == [PARTIAL_2R]
    assert sim.runner_open is True
    assert sim.remaining_fraction == pytest.approx(RUNNER_FRACTION)
    # The tick after the partial is real and was processed: it is past the partial level
    # and produced NO event, which is what "the runner survives" means.
    assert ticks[-1][1] == 112.0 > LONG_PLAN.partial_level
    assert len(sim.events) == 1


def test_the_runner_carries_the_original_stop_and_is_passive():
    """EXIT-003 is OPEN, so the runner does not trail, scale, or move its stop.

    Proven by outcome rather than by inspection: price runs to 125 (well past 2R, short of
    the 130 target) and then falls back to the ORIGINAL stop at 95. A trailing or
    break-even stop would have closed the runner on the way down at a better price; a
    passive one takes the original stop.
    """
    sim = V1ExitModel.simulate(
        LONG_PLAN, ticks_from_prices(MORNING_EDT, [100, 110, 125, 120, 101, 95])
    )
    assert [e.reason for e in sim.events] == [PARTIAL_2R, STOP_HIT]
    stop_event = sim.events[1]
    assert stop_event.price == 95.0, "the runner moved its stop — EXIT-003 is OPEN/PASSIVE"
    assert stop_event.fraction == pytest.approx(RUNNER_FRACTION)
    assert stop_event.realised_r == pytest.approx(-1.0)


@pytest.mark.parametrize(
    "plan,prices,expected_price",
    [
        (LONG_PLAN, [100, 110, 130], 130.0),
        (SHORT_PLAN, [100, 90, 70], 70.0),
    ],
)
def test_the_runner_ends_on_the_final_target(plan, prices, expected_price):
    sim = V1ExitModel.simulate(plan, ticks_from_prices(MORNING_EDT, prices))
    assert [e.reason for e in sim.events] == [PARTIAL_2R, FINAL_TARGET]
    assert sim.events[1].price == expected_price
    assert sim.events[1].fraction == pytest.approx(RUNNER_FRACTION)
    assert sim.runner_open is False
    assert V1ExitModel.evaluate(sim).verdict == "PASS"


def test_a_stop_before_2r_closes_the_whole_position_with_no_partial():
    """"Any remaining position" is the whole of it when the partial never fired."""
    sim = V1ExitModel.simulate(LONG_PLAN, ticks_from_prices(MORNING_EDT, [100, 98, 95]))
    assert [e.reason for e in sim.events] == [STOP_HIT]
    assert sim.events[0].fraction == pytest.approx(1.0)
    assert sim.remaining_fraction == 0.0


def test_the_short_side_is_not_the_long_side_with_a_sign_bolted_on():
    plan = SHORT_PLAN
    assert plan.r_distance == 5.0
    assert plan.partial_level == 90.0     # 100 - 2 * 5
    sim = V1ExitModel.simulate(plan, ticks_from_prices(MORNING_EDT, [100, 95, 90, 88]))
    assert [e.reason for e in sim.events] == [PARTIAL_2R]
    assert sim.events[0].price == 90.0
    assert sim.events[0].realised_r == pytest.approx(2.0)
    assert sim.runner_open is True


# ---------------------------------------------------------------------------
# Criterion 4 / 4a — EXIT-002 is a negative constraint with a negative test
# ---------------------------------------------------------------------------
def test_two_partials_are_rejected():
    """Criterion 4. A constraint with no test that violates it is a comment."""
    events = [_ev(PARTIAL_2R, 0.35, minutes=0), _ev(PARTIAL_2R, 0.35, minutes=5)]
    codes = {f.code for f in ladder_violations(events)}
    assert "MULTIPLE_PARTIALS" in codes
    assert LadderOffForV1.evaluate(events).verdict == "FAIL"
    with pytest.raises(ValueError, match="MULTIPLE_PARTIALS"):
        assert_v1_exit_shape(events)


def test_the_25_percent_ladder_is_refused_by_name_and_by_count():
    """CRITERION 4a — the check must exist, and it must refuse four tranches.

    Before T-0022 this constraint held because nothing could produce a tranche at all.
    EXIT-001's 70/30 split is the constructor that ends that, so 25/25/25/25 is now
    buildable and must be blocked by a check rather than by impossibility.
    """
    ladder = [_ev(PARTIAL_2R, 0.25, minutes=i * 5) for i in range(3)]
    ladder.append(_ev(FINAL_TARGET, 0.25, minutes=15))
    assert tuple(e.fraction for e in ladder) == LADDER_SIGNATURE

    codes = {f.code for f in ladder_violations(ladder)}
    assert "SCALE_OUT_LADDER" in codes
    assert "TOO_MANY_TRANCHES" in codes
    assert "MULTIPLE_PARTIALS" in codes
    assert LadderOffForV1.evaluate(ladder).verdict == "FAIL"


def test_a_three_legged_ladder_is_still_refused_though_it_matches_no_signature():
    """The signature match is a LABEL, never the test.

    A check that recognised only the four-legged 25/25/25/25 form would be defeated by
    using three legs. So this asserts the counts catch it while `SCALE_OUT_LADDER` does not
    fire — if the label were doing the work, this test goes red.
    """
    three = [
        _ev(PARTIAL_2R, 0.33, minutes=0),
        _ev(PARTIAL_2R, 0.33, minutes=5),
        _ev(FINAL_TARGET, 0.34, minutes=10),
    ]
    codes = {f.code for f in ladder_violations(three)}
    assert "SCALE_OUT_LADDER" not in codes
    assert {"MULTIPLE_PARTIALS", "TOO_MANY_TRANCHES"} <= codes


def test_two_terminal_tranches_are_rejected():
    events = [_ev(FINAL_TARGET, 0.5), _ev(STOP_HIT, 0.5, minutes=5)]
    assert "MULTIPLE_TERMINALS" in {f.code for f in ladder_violations(events)}


def test_exits_summing_past_the_whole_position_are_rejected():
    events = [_ev(PARTIAL_2R, 0.7), _ev(FINAL_TARGET, 0.7, minutes=5)]
    assert "OVERSIZED_EXIT" in {f.code for f in ladder_violations(events)}


def test_the_check_reads_stored_records_not_only_live_objects():
    """The constraint is on the RECORD, so the check must run over `trade_execution.exits`.

    A guard that could only read live `ExitEvent` objects could not be run over history —
    which is the only place a violation would ever actually be found, since the live path
    that could produce one does not exist yet.
    """
    stored = [
        {"timestamp_ny": "2026-07-15T10:00:00-04:00", "fraction": 0.25,
         "price": 110.0, "reason": "PARTIAL_2R"},
        {"timestamp_ny": "2026-07-15T10:05:00-04:00", "fraction": 0.25,
         "price": 115.0, "reason": "PARTIAL_2R"},
        {"timestamp_ny": "2026-07-15T10:10:00-04:00", "fraction": 0.25,
         "price": 120.0, "reason": "PARTIAL_2R"},
        {"timestamp_ny": "2026-07-15T10:15:00-04:00", "fraction": 0.25,
         "price": 130.0, "reason": "FINAL_TARGET"},
    ]
    codes = {f.code for f in ladder_violations(stored)}
    assert {"SCALE_OUT_LADDER", "TOO_MANY_TRANCHES", "MULTIPLE_PARTIALS"} <= codes


def test_a_reason_the_schema_allows_and_the_rule_does_not_is_caught_in_stored_records():
    """`LIQUIDATION` validates against the schema. It is still not a v1 exit.

    THIS TEST IS VERIFIED AGAINST ITS OWN FIXTURE AND THAT IS NOT A COMPLAINT ABOUT IT — it
    is the honest description. `REASON_OUTSIDE_V1` cannot fire over anything this codebase
    produces today (see the test below), so a hand-built dict is the only way to reach it.
    It guards a FUTURE writer. Kept, and labelled, rather than deleted or oversold.
    """
    stored = [{"timestamp_ny": "2026-07-15T10:00:00-04:00", "fraction": 1.0,
               "price": 95.0, "reason": "LIQUIDATION"}]
    findings = ladder_violations(stored)
    assert [f.code for f in findings] == ["REASON_OUTSIDE_V1"]
    assert "schema" in findings[0].detail


def test_nothing_in_this_repository_writes_a_stored_exit_record():
    """WHY `REASON_OUTSIDE_V1` IS UNREACHABLE TODAY, ASSERTED RATHER THAN CLAIMED.

    The question that separates "this check guards records" from "this check guards its own
    fixture" is: what writes a stored exit record, and does it go through `ExitEvent`?
    Measured answer: `records.trade_execution()` — the only builder of a record with an
    `exits` array — has NO callers anywhere, so nothing writes one at all, and every exit
    event that exists came through a constructor that already refused the bad value.

    This test is the tripwire on that claim. It goes red the moment a writer appears, which
    is exactly when the tranche checks start guarding real records and when
    `REASON_OUTSIDE_V1` becomes reachable — and when the ExitEvent/LIQUIDATION hazard in
    KNOWN_ISSUES has to be settled before the writer ships.
    """
    # PARSED, NOT GREPPED. A substring search matches the name in a docstring — including
    # the one in exit_002_ladder_off.py that states this very fact — so the first version of
    # this test failed on its own documentation. An AST walk sees call sites only.
    # The REPOSITORY root, not `backend/` — `scripts/` at the top level is exactly where a
    # one-off exporter or migration would write records from, so a scan that stopped at
    # backend/ would miss the likeliest future writer.
    root = Path(model.__file__).parents[4]
    builder = root / "backend/app/services/telemetry/records.py"
    callers = []
    candidates = [
        p for p in root.rglob("*.py")
        if "__pycache__" not in str(p)
        and p != builder                       # the definition is not a call site
        and p != Path(__file__)                # nor is this test's own prose
    ]
    parsed = 0
    unparseable = []
    for path in candidates:
        try:
            tree = ast.parse(path.read_text())
        except (SyntaxError, UnicodeDecodeError) as exc:
            # NOT skipped. A file the walker could not read is a file it did not search,
            # and "could not look" must never share a result with "looked and found
            # nothing" — a tripwire that silently stops scanning is read as evidence.
            unparseable.append(f"{path.relative_to(root)}: {exc.__class__.__name__}")
            continue
        parsed += 1
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (
                func.attr if isinstance(func, ast.Attribute)
                else func.id if isinstance(func, ast.Name)
                else None
            )
            if name == "trade_execution":
                callers.append(f"{path.relative_to(root)}:{node.lineno}")
    # THE DENOMINATOR, ASSERTED. Without this, a walker that parsed nothing reports the
    # same empty `callers` as one that parsed everything — "could not look" and "looked and
    # found nothing" collapsing into one green, which is the failure class this whole test
    # exists to prevent for a different quantity.
    assert unparseable == [], f"the scan could not read these, so it did not search them: {unparseable}"
    assert parsed == len(candidates)
    # A floor, measured rather than guessed: the repository held 270 .py files, 268 of them
    # candidates after excluding the builder's own definition and this test file,
    # when this was written. The point is not the exact number — it is that a scan which
    # has quietly stopped covering the tree cannot report an empty result as evidence.
    assert parsed >= 200, (
        f"only {parsed} files parsed — the scan has stopped covering the repository and "
        "its empty result means nothing"
    )
    # And the thing being searched for still exists. A scan for a name nothing could call
    # returns empty forever and looks identical to a clean result.
    assert builder.is_file() and "def trade_execution(" in builder.read_text(), (
        "the builder this test looks for callers of has moved or gone; the scan is now "
        "searching for a name nothing could call"
    )

    assert callers == [], (
        "something now writes a trade_execution record. The EXIT-002 check's reach has "
        f"changed and the KNOWN_ISSUES entries must be revisited: {callers}"
    )


def test_the_model_itself_cannot_produce_a_second_partial():
    """Structural, on top of the check: price crosses 2R repeatedly and banks once."""
    sim = V1ExitModel.simulate(
        LONG_PLAN, ticks_from_prices(MORNING_EDT, [100, 110, 105, 111, 106, 112])
    )
    assert [e.reason for e in sim.events] == [PARTIAL_2R]
    assert LadderOffForV1.evaluate(sim.events).verdict == "PASS"


def test_a_conformant_exit_and_an_empty_one_both_pass():
    conformant = V1ExitModel.simulate(
        LONG_PLAN, ticks_from_prices(MORNING_EDT, [100, 110, 130])
    )
    assert len(conformant.events) == MAX_TRANCHES
    assert LadderOffForV1.evaluate(conformant.events).verdict == "PASS"
    # An open position has zero tranches. That is conformant, not unevaluable — otherwise
    # the commonest state in the record reads as a rule that could not run.
    assert LadderOffForV1.evaluate([]).verdict == "PASS"


# ---------------------------------------------------------------------------
# Criteria 5 / 5a — the 19:00 close is declared, unratified, and load-bearing
# ---------------------------------------------------------------------------
def test_the_session_close_is_declared_ours_and_unratified():
    assert DECLARED_SESSION_CLOSE.ratified is False
    assert DECLARED_SESSION_CLOSE.local_time.strftime("%H:%M") == "19:00"
    assert DECLARED_SESSION_CLOSE.zone == "America/New_York"
    source = DECLARED_SESSION_CLOSE.source
    assert "EURUSD" in source, "the provenance strand must be named"
    assert "24/7" in source, "our instrument's mismatch with it must be named"
    assert "GATE-022" in source
    assert "UNANSWERED" in source, "Salim was asked on 2026-08-15 and has not answered"

    sim = V1ExitModel.simulate(LONG_PLAN, ticks_from_prices(MORNING_EDT, [100, 110]))
    ev = V1ExitModel.evaluate(sim)
    assert ev.declared_parameter_used == "session_close_ny"
    assert ev.values["session_close_ny_ratified"] is False


def test_the_session_close_parameter_changes_the_outcome_in_both_directions():
    """CRITERION 5a — a declared parameter that cannot change any outcome is decorative.

    Same plan, same ticks, same runner open at 19:00 New York. Active: it is closed with
    SESSION_CLOSE. Inactive: it survives. Both directions, or the parameter is not
    load-bearing.
    """
    # 18:55 EDT -> 19:00 EDT, runner open (2R hit at 110, target 130 never reached).
    ticks = [
        (datetime(2026, 7, 15, 22, 50, tzinfo=UTC), 110.0),
        (datetime(2026, 7, 15, 22, 55, tzinfo=UTC), 112.0),
        (datetime(2026, 7, 15, 23, 0, tzinfo=UTC), 113.0),
    ]

    active = V1ExitModel.simulate(LONG_PLAN, ticks, session_close_active=True)
    assert [e.reason for e in active.events] == [PARTIAL_2R, SESSION_CLOSE]
    assert active.events[1].fraction == pytest.approx(RUNNER_FRACTION)
    assert active.runner_open is False

    inactive = V1ExitModel.simulate(LONG_PLAN, ticks, session_close_active=False)
    assert [e.reason for e in inactive.events] == [PARTIAL_2R]
    assert inactive.runner_open is True
    assert inactive.remaining_fraction == pytest.approx(RUNNER_FRACTION)


def test_the_default_is_on_because_a_close_that_never_fires_generates_no_evidence():
    """Criterion 5: implemented as the rule states, NOT defaulted off for being 24/7."""
    assert (
        inspect.signature(V1ExitModel.simulate).parameters["session_close_active"].default
        is True
    )


def test_a_session_close_records_the_r_the_runner_was_carrying():
    """CRITERION 5-ii's evidence, named rather than left to be re-derived.

    The wiring task must bring "the count of runners that would have been cut and the R
    they were carrying" to the ratification decision. That number is worthless if it can
    only be recovered by replaying the trade.
    """
    ticks = [
        (datetime(2026, 7, 15, 22, 50, tzinfo=UTC), 110.0),   # 2R, partial fires
        (datetime(2026, 7, 15, 23, 0, tzinfo=UTC), 115.0),    # 19:00 EDT, 3R on the runner
    ]
    ev = V1ExitModel.evaluate(V1ExitModel.simulate(LONG_PLAN, ticks))
    assert ev.verdict == "PASS"
    assert ev.values["runner_cut_by_session_close"] is True
    assert ev.values["runner_r_at_session_close"] == pytest.approx(3.0)


def test_a_runner_that_ended_another_way_records_no_session_close_evidence():
    """The counter to the test above: the key must not be present on every record.

    A field that is always there cannot be counted. If `runner_cut_by_session_close` were
    emitted unconditionally, "how many runners did the session cut" would need the VALUE
    read rather than the key counted, and a default of False would be indistinguishable
    from an absent one on a record written before the field existed.
    """
    ev = V1ExitModel.evaluate(
        V1ExitModel.simulate(LONG_PLAN, ticks_from_prices(MORNING_EDT, [100, 110, 130]))
    )
    assert ev.values["terminal_reason"] == FINAL_TARGET
    assert "runner_cut_by_session_close" not in ev.values
    assert "runner_r_at_session_close" not in ev.values


# ---------------------------------------------------------------------------
# Criterion 6 — 19:00 New York is a real zone, and it is not 19:00 UTC
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "label,ticks,expected_utc,expected_ny",
    [
        # EDT — entry 18:00 EDT; 19:00 EDT is 23:00 UTC the SAME day.
        (
            "EDT",
            [
                (datetime(2026, 7, 15, 22, 0, tzinfo=UTC), 110.0),
                (datetime(2026, 7, 15, 22, 55, tzinfo=UTC), 112.0),
                (datetime(2026, 7, 15, 23, 0, tzinfo=UTC), 113.0),
            ],
            datetime(2026, 7, 15, 23, 0, tzinfo=UTC),
            "2026-07-15T19:00:00-04:00",
        ),
        # EST — entry 18:00 EST; 19:00 EST is 00:00 UTC the NEXT day.
        (
            "EST",
            [
                (datetime(2026, 1, 15, 23, 0, tzinfo=UTC), 110.0),
                (datetime(2026, 1, 15, 23, 55, tzinfo=UTC), 112.0),
                (datetime(2026, 1, 16, 0, 0, tzinfo=UTC), 113.0),
            ],
            datetime(2026, 1, 16, 0, 0, tzinfo=UTC),
            "2026-01-15T19:00:00-05:00",
        ),
    ],
)
def test_the_session_close_fires_at_the_right_utc_instant(
    label, ticks, expected_utc, expected_ny
):
    """CRITERION 6. Two dates, expected instants as LITERALS, reported SEPARATELY.

    19:00 New York is 23:00 UTC on 2026-07-15 (EDT, UTC-4) and 00:00 UTC on 2026-01-16
    (EST, UTC-5). A hardcoded UTC-4 passes the first and fires an hour early on the second;
    a hardcoded UTC-5 does the reverse.

    PARAMETRISED RATHER THAN A LOOP INSIDE ONE TEST, deliberately. As a loop both dates
    share a single test name, so a failure cannot say WHICH date broke — and "one EDT and
    one EST" is a claim about two distinguishable outcomes. Under a hardcoded-UTC-4
    mutation this reports `[EST]` red and `[EDT]` green, which is the evidence; one merged
    red would have been consistent with the conversion being broken in both directions.
    """
    sim = V1ExitModel.simulate(LONG_PLAN, ticks)
    assert [e.reason for e in sim.events] == [PARTIAL_2R, SESSION_CLOSE], label
    close = sim.events[1]
    assert close.timestamp == expected_utc, (
        f"[{label}] session close fired at {close.timestamp}, expected {expected_utc}"
    )
    # The offset in the stored string is the evidence a tz database was consulted.
    assert close.as_dict()["timestamp_ny"] == expected_ny


def test_a_hardcoded_edt_offset_would_cut_the_winter_runner_an_hour_early():
    """The discriminating case, stated as its own assertion.

    23:00 UTC on 2026-01-15 is 18:00 EST — an hour BEFORE the close. An implementation
    using a fixed UTC-4 would close here. The runner must survive.
    """
    ticks = [
        (datetime(2026, 1, 15, 22, 0, tzinfo=UTC), 110.0),
        (datetime(2026, 1, 15, 23, 0, tzinfo=UTC), 112.0),   # 18:00 EST
    ]
    sim = V1ExitModel.simulate(LONG_PLAN, ticks)
    assert [e.reason for e in sim.events] == [PARTIAL_2R]
    assert sim.runner_open is True


def test_a_feed_gap_across_the_boundary_does_not_skip_the_close():
    """NOT IN CRITERION 6, AND CRITERION 6 CANNOT CATCH IT.

    `to_ny(tick).time() >= 19:00` is a genuine timezone conversion, so it passes both DST
    fixtures above and is still wrong: a runner whose last tick before a feed gap is 18:55
    and whose next is 01:00 the following morning reads 01:00 < 19:00, no close fires, and
    the position survives an extra full day. On a 24/7 instrument the path does not stop at
    the boundary, so this is the ordinary case. The close is a BOUNDARY CROSSING.
    """
    ticks = [
        (datetime(2026, 7, 15, 22, 50, tzinfo=UTC), 110.0),   # 18:50 EDT
        (datetime(2026, 7, 16, 5, 0, tzinfo=UTC), 113.0),     # 01:00 EDT, next day
    ]
    sim = V1ExitModel.simulate(LONG_PLAN, ticks)
    assert [e.reason for e in sim.events] == [PARTIAL_2R, SESSION_CLOSE]
    close = sim.events[1]
    assert close.timestamp == datetime(2026, 7, 16, 5, 0, tzinfo=UTC), (
        "the close must fire on the first tick at or after the boundary, not be skipped "
        "because that tick's local time-of-day is before 19:00"
    )
    # THE TIMESTAMP AND THE PRICE MUST COME FROM THE SAME TICK. Stamping the 19:00 boundary
    # while carrying the 01:00 price would record a fill at an instant when that price did
    # not exist — lookahead in the telemetry, invisible to any test that only asserts a
    # close fired. The boundary was crossed at 19:00; the fill happened at 01:00.
    assert close.price == 113.0
    assert (close.timestamp, close.price) == ticks[-1]
    assert close.as_dict()["timestamp_ny"].startswith("2026-07-16T01:00:00")


def test_the_boundary_is_added_on_the_wall_clock_not_as_24_absolute_hours():
    """Adding `timedelta(days=1)` to an aware NY datetime is GATE-023's bug one layer up.

    2026-11-01 is the EST transition. From 20:00 EDT on 10-31 the next close is 19:00 EST
    on 11-01 — 24 hours would be a 23:00 UTC instant reading 19:00 EDT, which no longer
    exists that day. The offset in the answer is what proves which arithmetic was used.
    """
    after = next_session_close_after(datetime(2026, 11, 1, 0, 0, tzinfo=UTC))  # 20:00 EDT
    assert after.strftime("%H:%M") == "19:00"
    assert after.utcoffset() == timedelta(hours=-5), "landed on the wrong side of the DST change"
    assert after == datetime(2026, 11, 2, 0, 0, tzinfo=UTC)


def test_a_position_opened_exactly_at_1900_runs_a_full_session_rather_than_closing_at_once():
    """A CHOICE, PINNED — not a property that fell out of the implementation.

    `strictly after` means an entry tick at 19:00:00 NY holds to the NEXT 19:00. `>=` would
    close it on its own entry tick for a zero-length hold. Both readings survive the text
    and they differ by a whole session of exposure, so nothing about this is self-evident;
    it is pinned here so changing it is a deliberate act with a red test attached.

    (It also happens to be why the boundary is fixed from the first tick rather than
    recomputed per tick: a per-tick boundary is always in that tick's future and would
    never be crossed at all.)
    """
    entry = datetime(2026, 7, 15, 23, 0, tzinfo=UTC)   # exactly 19:00 EDT
    assert next_session_close_after(entry) == datetime(2026, 7, 16, 23, 0, tzinfo=UTC)

    sim = V1ExitModel.simulate(LONG_PLAN, [(entry, 110.0),
                                           (entry + timedelta(hours=1), 112.0)])
    assert [e.reason for e in sim.events] == [PARTIAL_2R]
    assert sim.runner_open is True, "a trade opened at the close held zero time"


# ---------------------------------------------------------------------------
# GATE-031 — a degenerate runner is refused, not silently widened
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("target", [110.0, 105.0])
def test_a_target_at_or_inside_2r_is_refused_and_cites_gate_031(target):
    with pytest.raises(DegenerateRunner, match="GATE-031"):
        TradePlan(side="LONG", entry=100.0, stop=95.0, final_target=target)


def test_an_inverted_or_zero_stop_is_refused():
    with pytest.raises(ValueError, match="non-positive risk"):
        TradePlan(side="LONG", entry=100.0, stop=100.0, final_target=130.0)
    with pytest.raises(ValueError, match="non-positive risk"):
        TradePlan(side="LONG", entry=100.0, stop=105.0, final_target=130.0)


# ---------------------------------------------------------------------------
# Criterion 7 — shadow only. Nothing wires this into the live exit path.
# ---------------------------------------------------------------------------
def test_no_live_or_broker_module_imports_the_exit_model():
    """CRITERION 7. A green suite here must not be readable as a live 70/30 exit.

    `broker/paper.py:on_tick` still closes positions WHOLE at sl/tp. Wiring this in is a
    live behaviour change with its own deploy. This test is what makes that statement
    checkable rather than a claim in a report — it goes red the moment someone wires it,
    which is the moment the claim stops being true.
    """
    app_dir = Path(model.__file__).parents[2]
    needles = ("exit_001_v1_model", "exit_002_ladder_off", "V1ExitModel", "LadderOffForV1")
    offenders = []
    for sub in ("live", "broker"):
        for path in (app_dir / "services" / sub).rglob("*.py"):
            text = path.read_text()
            for needle in needles:
                if needle in text:
                    offenders.append(f"{path.name}: {needle}")
    assert offenders == [], (
        "the v1 exit model is wired into the live path, which T-0022 criterion 7 puts out "
        f"of scope: {offenders}"
    )


def test_the_paper_broker_still_closes_whole_positions():
    """The finding this task was asked to report, asserted so it cannot rot silently.

    `PaperPosition` has ONE `units`, ONE `sl`, ONE `tp` and `_settle` pops the whole
    position. There is no representation of a tranche, so the 70/30 model does not fit the
    existing shape — recorded in KNOWN_ISSUES rather than forced.
    """
    from app.services.broker.paper import PaperPosition

    assert PaperPosition.__slots__ == (
        "id", "pair", "direction", "entry", "units", "sl", "tp", "open_time", "mark"
    ), (
        "PaperPosition changed shape. If it grew tranches, the T-0022 finding is stale and "
        "the wiring task has started; if it grew something else, check this still holds."
    )


# ---------------------------------------------------------------------------
# Telemetry shape
# ---------------------------------------------------------------------------
def test_every_value_names_its_provenance_on_every_verdict():
    """ALL THREE VERDICTS, because the branches are where a value gets added unpinned.

    Checking only the PASS record is how this passed while the NOT_APPLICABLE one carried
    `not_applicable_reason` with no provenance entry — found by a mutation run turning this
    test red for a reason unrelated to the mutation, not by the test as first written.
    """
    passing = V1ExitModel.evaluate(
        V1ExitModel.simulate(LONG_PLAN, ticks_from_prices(MORNING_EDT, [100, 110, 130]))
    )
    unfinished = V1ExitModel.evaluate(
        V1ExitModel.simulate(LONG_PLAN, ticks_from_prices(MORNING_EDT, [100, 105]))
    )
    violating = V1ExitModel.evaluate(
        model.ExitSimulation(
            plan=LONG_PLAN,
            events=(_ev(PARTIAL_2R, 1.0, price=110.0),),
            runner_open=False,
            remaining_fraction=0.0,
            session_close_active=True,
        )
    )
    assert [e.verdict for e in (passing, unfinished, violating)] == [
        "PASS", "NOT_APPLICABLE", "FAIL"
    ]
    for ev in (passing, unfinished, violating):
        assert set(ev.values) == set(ev.value_provenance), ev.verdict
        assert all("source" in p for p in ev.value_provenance.values())
    assert "not_applicable_reason" in unfinished.values
    assert "violations" in violating.values
    assert passing.value_provenance["partial_fraction"]["source"] == "REGISTRY_CONSTANT"


def test_exit_events_match_the_schema_shape():
    sim = V1ExitModel.simulate(
        LONG_PLAN, ticks_from_prices(MORNING_EDT, [100, 110, 130])
    )
    for raw in sim.as_exit_events():
        assert set(raw) >= {"timestamp_ny", "fraction", "price", "reason"}
        assert 0 < raw["fraction"] <= 1
        assert raw["rule_id"] == "EXIT-001"
        # iso_ny: NY local WITH offset, which is what proves a zone was consulted.
        assert raw["timestamp_ny"][-6] in "+-"


def test_both_rules_are_registered_under_their_contract_ids():
    from app.services.rules import implemented_ids

    assert {"EXIT-001", "EXIT-002"} <= implemented_ids()
    assert V1ExitModel.RULE_ID == "EXIT-001"
    assert LadderOffForV1.RULE_ID == "EXIT-002"
    for cls in (V1ExitModel, LadderOffForV1):
        assert cls.COVERAGE_NOTE, "both rules ship partial coverage and must say so"
