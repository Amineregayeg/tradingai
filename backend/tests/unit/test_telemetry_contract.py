"""The engine-contract telemetry layer (M1).

The contract's instruction is to implement the telemetry schema BEFORE strategy logic,
because everything downstream — conformance, fidelity, the learning loop — is a pure
function of stored records, and retrofitting telemetry is expensive.

These tests pin the properties that make a stored record worth anything:

  * it validates against the schema the knowledge team actually shipped, not our reading
    of it;
  * a rule id that is not in the registry cannot reach telemetry;
  * the versions stamped on a record are the versions really in force, even when that is
    inconvenient;
  * timestamps carry a DST-aware New York offset, which is the only evidence of which zone
    was used.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.telemetry import contract_loader as contract
from app.services.telemetry import records as rec
from app.services.telemetry import validate as val
from app.services.telemetry.ny_time import iso_ny, to_ny


@pytest.fixture
def declared() -> rec.DeclaredParameters:
    return rec.DeclaredParameters(
        virtual_account_size=50_000.0,
        evaluation_order_id="magic-v1",
        emission_policy_id="every-closed-bar-roster-v1",
        layout_size_frozen=True,
        main_asset_counts=True,
        box_scope="ENTRY_BOX_EXEC_TF",
        stop_selection_reading="CLOSEST_TO_3R_TIES_TO_LARGER",
        runner_management_policy="70_30_partial_then_runner",
        reverse_quorum=None,
    )


@pytest.fixture
def evaluation(declared) -> dict:
    """A minimal but genuinely schema-valid setup_evaluation for a SKIP."""
    return rec.setup_evaluation(
        timestamp=datetime(2026, 8, 4, 13, 0, tzinfo=timezone.utc),
        declared=declared,
        scan_context={
            "scan_id": "scan-1",
            "sequence_no": 1,
            "candidate_origin": "SCHEDULED_BAR_CLOSE",
            "bar_close_time_ny": "2026-08-04T09:00:00-04:00",
            "data_as_of_ny": "2026-08-04T09:00:05-04:00",
            "pre_filters_applied": [],
        },
        instrument={"symbol": "BTCUSDT.P", "instrument_class": "ALIGNED_MAJOR", "venue": "BINANCE_FUTURES"},
        mode={"trading_mode": "DAY_TRADE", "direction_mode": "FORWARD"},
        timeframes={"signal_tf": "1H", "alignment_tf": "1H", "analysis_tfs_scanned": ["1D", "4H", "1H"]},
        session={
            "ny_local_time": "2026-08-04T09:00:00-04:00",
            "tz_offset_used": "-04:00",
            "in_magic_zone": False,
            "minutes_from_nyo": -30,
        },
        primitives={
            "swing_points": [], "structure_boxes": [], "imbalances": [],
            "liquidity_pools": [], "sweeps": [], "breaks": [],
        },
        correlates={"layout_size": 4, "disturbed_count": 0, "disturbance_grade": "NONE", "states": []},
        rule_evaluations=[
            rec.RuleEvaluation(
                rule_id="GATE-012",
                verdict="PASS",
                values={"minutes_to_event": 120},
                value_provenance={"minutes_to_event": rec.from_record("news_context.events_considered")},
            )
        ],
        decision="SKIP",
        deciding_rule_id="GATE-012",
        risk_assessment={"box_grade": "STANDARD", "risk_pct": 0.01},
    )


# ---------------------------------------------------------------------------
# The contract as delivered
# ---------------------------------------------------------------------------
def test_the_vendored_artefacts_are_byte_for_byte_the_ones_analysed():
    """Pins the CONTENT, not just the version string.

    A package drop that changes a rule without bumping the version would otherwise be
    invisible, and every stored record would claim conformance to a registry nobody
    reviewed. This failing is not a bug — it is the prompt to read the diff, re-run the
    conformance suite, and update these hashes deliberately.
    """
    import hashlib

    expected = {
        "RULE_REGISTRY.json": "d85f979078815202",
        "TELEMETRY_SCHEMA.json": "1364ab11ae0703e7",
    }
    for name, prefix in expected.items():
        got = hashlib.sha256((contract.CONTRACT_DIR / name).read_bytes()).hexdigest()[:16]
        assert got == prefix, f"{name} changed: {got} != {prefix} — review the diff"


def test_the_pinned_registry_is_the_one_we_analysed():
    """Guards against a package drop changing the rules underneath the engine."""
    assert contract.registry_version() == "1.2.0"
    assert len(contract.known_rule_ids()) == 117
    assert len(contract.ids_with_enforceability("HARD_GATE")) == 91
    assert len(contract.ids_with_status("OPEN")) == 14


def test_an_unknown_rule_id_cannot_be_referenced():
    """Rule ids are the contract's join key; they are never invented locally."""
    with pytest.raises(KeyError, match="GATE-999"):
        contract.rule("GATE-999")


def test_the_delivered_artefacts_are_mutually_incompatible_and_we_say_so():
    """A DEFECT IN THE DELIVERED PACKAGE, pinned here so it cannot be forgotten.

    The schema hard-pins rule_registry_version to "1.1.0"; the registry ships as 1.2.0.
    Left unhandled, no record we emit could ever validate. This test exists so that when a
    regenerated schema arrives, the skew disappears and this test fails — which is the
    prompt to remove the relaxation in validate._branch_validator.
    """
    skew = contract.contract_version_skew()
    assert skew is not None, "skew resolved — remove the version relaxation in validate.py"
    assert "1.1.0" in skew and "1.2.0" in skew


def test_records_report_the_registry_actually_in_force():
    """Not the version the schema wishes we were on.

    Writing "1.1.0" into telemetry while running 1.2.0 would make stored evidence claim a
    registry it was never evaluated against — which defeats the only purpose of the field.
    """
    assert rec.engine_identity()["rule_registry_version"] == "1.2.0"


# ---------------------------------------------------------------------------
# Records validate
# ---------------------------------------------------------------------------
def test_a_built_setup_evaluation_validates(evaluation):
    assert val.errors(evaluation) == []


def test_a_rejection_is_a_first_class_record(evaluation):
    """The single most important telemetry requirement: an engine that takes three correct
    trades while silently skipping thirty valid ones is failing, and executed-trade logs
    cannot show that."""
    assert evaluation["decision"] == "SKIP"
    assert val.is_valid(evaluation)


def test_a_missing_required_field_is_refused(evaluation):
    broken = {k: v for k, v in evaluation.items() if k != "risk_assessment"}
    with pytest.raises(val.TelemetryInvalid, match="risk_assessment"):
        val.assert_valid(broken)


def test_a_rule_id_absent_from_the_registry_is_refused(evaluation):
    """The schema can only check the id's PATTERN, so GATE-999 satisfies it. Conformance
    C-3 asserts existence, and catching it at emit time is far cheaper than in an audit."""
    evaluation["deciding_rule_id"] = "GATE-999"
    problems = val.errors(evaluation)
    assert any("GATE-999" in p and "RULE_REGISTRY" in p for p in problems)


def test_enforceability_comes_from_the_registry_not_the_caller():
    """So a rule's severity can never be misreported by the code that evaluates it."""
    ev = rec.RuleEvaluation(rule_id="GATE-012", verdict="PASS")
    assert ev.as_dict()["enforceability"] == contract.enforceability_of("GATE-012")


def test_declared_parameters_emit_a_null_choice_rather_than_omitting_it(declared):
    """reverse_quorum is OPEN. "We chose nothing" and "we forgot to declare it" must not
    look the same — that ambiguity is what declared_parameters exists to remove."""
    d = declared.as_dict()
    assert "reverse_quorum" in d
    assert d["reverse_quorum"] is None


# ---------------------------------------------------------------------------
# New York time (GATE-023)
# ---------------------------------------------------------------------------
def test_timestamps_carry_a_dst_aware_new_york_offset():
    """A fixed offset shifts the news blackout, magic zone, 19:00 close and session ranges
    by an hour twice a year. The offset in the string is the proof a tz database was used."""
    summer = iso_ny(datetime(2026, 8, 4, 13, 0, tzinfo=timezone.utc))
    winter = iso_ny(datetime(2026, 1, 4, 13, 0, tzinfo=timezone.utc))
    assert summer.endswith("-04:00"), summer
    assert winter.endswith("-05:00"), winter


def test_a_naive_datetime_is_refused():
    """An implicit zone is how a DST bug survives review: correct in CI, an hour wrong in
    production for half the year."""
    with pytest.raises(ValueError, match="naive"):
        to_ny(datetime(2026, 8, 4, 13, 0))


# ---------------------------------------------------------------------------
# The other two record types
# ---------------------------------------------------------------------------
def test_a_scan_census_validates(declared):
    census = rec.scan_census(
        declared=declared,
        instrument={"symbol": "BTCUSDT.P", "instrument_class": "ALIGNED_MAJOR"},
        signal_tf="1H",
        session_date="2026-08-04",
        window_from=datetime(2026, 8, 4, 4, 0, tzinfo=timezone.utc),
        window_to=datetime(2026, 8, 4, 23, 0, tzinfo=timezone.utc),
        bars_observed=19,
        evaluations_emitted=19,
    )
    assert val.errors(census) == []


def test_the_census_defaults_to_claiming_no_omissions(declared):
    """Under `every-closed-bar-roster-v1` nothing is skipped. If unemitted_bars is ever
    non-empty, that is the finding — a pre-filter citing no rule is undocumented logic."""
    census = rec.scan_census(
        declared=declared,
        instrument={"symbol": "BTCUSDT.P", "instrument_class": "ALIGNED_MAJOR"},
        signal_tf="1H", session_date="2026-08-04",
        window_from=datetime(2026, 8, 4, 4, 0, tzinfo=timezone.utc),
        window_to=datetime(2026, 8, 4, 23, 0, tzinfo=timezone.utc),
        bars_observed=19, evaluations_emitted=19,
    )
    assert census["unemitted_bars"] == []
