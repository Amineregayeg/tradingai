"""Storing engine-contract telemetry (M1).

The conformance suite is a pure function of stored records. That single sentence sets every
property tested here:

  * an invalid record must never reach the store, or every downstream number is computed
    over a population that does not match the contract;
  * a record must be reproducible verbatim, because anything normalised away is evidence we
    cannot produce in an audit;
  * records must be joinable — a trade to the evaluation that produced it — or fidelity
    cannot be attributed to anything.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.models.telemetry_record import TelemetryRecord
from app.services.telemetry import records as rec
from app.services.telemetry import store
from app.services.telemetry import validate as val

pytestmark = pytest.mark.asyncio


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


def _take_blocks() -> dict:
    """The blocks the schema requires before a TAKE may be claimed.

    Not boilerplate — this is the contract refusing to let an engine record a trade without
    the ladder it chose from, the target it aimed at, and the criteria it says were met.
    """
    return {
        "stop_evaluation": {
            "entry_reference_price": 64000.0,
            "target_price": 64900.0,
            "best_rr": 3.0,
            "selected_rung": 3,
            # Despite the name, this field's enum is the READING, not a rule id —
            # GATE-028's resolved selector. Stamped on every trade so outcomes can be
            # attributed to the reading that produced them.
            "selection_rule_id": "CLOSEST_TO_3R_TIES_TO_LARGER",
            "ladder": [
                {"rung": 1, "anchor": "DEEPEST_SWING", "locatable": True, "accepted": False,
                 "stop_price": 63100.0, "rr": 1.0, "rejection_reason": "RR_BELOW_2R"},
                {"rung": 3, "anchor": "LIQUIDITY_SWEEP_QML", "locatable": True, "accepted": True,
                 "stop_price": 63700.0, "rr": 3.0},
            ],
        },
        "target_selection": {"stand_aside_reason": ""},
        "entry_criteria": {
            "liquidity": {}, "imbalance_primary_poi": {}, "structure_and_momentum": {},
            "forward_reverse_context": {}, "magic_alignment_confirmation": {},
        },
    }


def _evaluation(declared, *, decision="SKIP", seq=1, evaluation_id=None) -> dict:
    extra = _take_blocks() if decision == "TAKE" else {}
    return rec.setup_evaluation(
        timestamp=datetime(2026, 8, 4, 13, 0, tzinfo=timezone.utc),
        declared=declared,
        evaluation_id=evaluation_id,
        scan_context={
            "scan_id": "scan-1", "sequence_no": seq,
            "candidate_origin": "SCHEDULED_BAR_CLOSE",
            "bar_close_time_ny": "2026-08-04T09:00:00-04:00",
            "data_as_of_ny": "2026-08-04T09:00:05-04:00",
            "pre_filters_applied": [],
        },
        instrument={"symbol": "BTCUSDT.P", "instrument_class": "ALIGNED_MAJOR"},
        mode={"trading_mode": "DAY_TRADE", "direction_mode": "FORWARD"},
        timeframes={"signal_tf": "1H", "alignment_tf": "1H", "analysis_tfs_scanned": ["1H"]},
        session={"ny_local_time": "2026-08-04T09:00:00-04:00", "tz_offset_used": "-04:00",
                 "in_magic_zone": False, "minutes_from_nyo": -30},
        primitives={"swing_points": [], "structure_boxes": [], "imbalances": [],
                    "liquidity_pools": [], "sweeps": [], "breaks": []},
        correlates={"layout_size": 4, "disturbed_count": 0, "disturbance_grade": "NONE", "states": []},
        rule_evaluations=[rec.RuleEvaluation(
            rule_id="GATE-012", verdict="PASS", values={"minutes_to_event": 120},
            value_provenance={"minutes_to_event": rec.from_record("news_context")})],
        decision=decision,
        deciding_rule_id="GATE-012",
        risk_assessment={"box_grade": "STANDARD", "risk_pct": 0.01},
        **extra,
    )


# ---------------------------------------------------------------------------
# Nothing invalid is stored
# ---------------------------------------------------------------------------
async def test_an_invalid_record_is_refused_and_stores_nothing(db_session, declared):
    """The store is the only door, so "stored" and "valid" cannot come apart."""
    broken = _evaluation(declared)
    del broken["risk_assessment"]

    with pytest.raises(val.TelemetryInvalid):
        await store.store(db_session, broken)

    from sqlalchemy import select
    rows = (await db_session.execute(select(TelemetryRecord))).scalars().all()
    assert rows == [], "an invalid record reached the store"


async def test_a_batch_is_all_or_nothing(db_session, declared):
    """A partial write would leave the census disagreeing with the evaluations it counts —
    exactly the population problem the census exists to detect."""
    good = _evaluation(declared, evaluation_id="eval-good")
    bad = _evaluation(declared, evaluation_id="eval-bad")
    del bad["decision"]

    with pytest.raises(val.TelemetryInvalid):
        await store.store_many(db_session, [good, bad])

    from sqlalchemy import select
    rows = (await db_session.execute(select(TelemetryRecord))).scalars().all()
    assert rows == [], "a batch stored some records before failing"


# ---------------------------------------------------------------------------
# What is stored is the evidence
# ---------------------------------------------------------------------------
async def test_the_record_is_kept_verbatim(db_session, declared):
    """Anything normalised away is evidence that cannot be produced in an audit."""
    record = _evaluation(declared)
    await store.store(db_session, record)

    from sqlalchemy import select
    row = (await db_session.execute(select(TelemetryRecord))).scalar_one()
    assert row.payload == record


async def test_query_columns_mirror_the_payload(db_session, declared):
    """They are duplicates for querying; the payload stays authoritative."""
    record = _evaluation(declared, decision="TAKE")
    await store.store(db_session, record)

    from sqlalchemy import select
    row = (await db_session.execute(select(TelemetryRecord))).scalar_one()
    assert row.record_type == "setup_evaluation"
    assert row.instrument == "BTCUSDT.P"
    assert row.signal_tf == "1H"
    assert row.decision == "TAKE"
    assert row.deciding_rule_id == "GATE-012"
    assert row.timestamp_ny.endswith("-04:00"), "the NY offset was normalised away"
    assert row.rule_registry_version == "1.2.0"


async def test_a_record_id_cannot_be_reused(db_session, declared):
    """Re-emitting an id means a record was rewritten. Append-only means impossible, not
    discouraged."""
    from sqlalchemy.exc import IntegrityError

    await store.store(db_session, _evaluation(declared, evaluation_id="eval-dup"))
    with pytest.raises(IntegrityError):
        await store.store(db_session, _evaluation(declared, evaluation_id="eval-dup"))


# ---------------------------------------------------------------------------
# Getting it back out
# ---------------------------------------------------------------------------
async def test_export_is_jsonl_the_harness_can_read(db_session, declared):
    """We store in Postgres; their suite assumes append-only JSONL. Exporting keeps both
    true — the suite is a pure function of the records either way."""
    await store.store(db_session, _evaluation(declared, evaluation_id="e1", seq=1))
    await store.store(db_session, _evaluation(declared, evaluation_id="e2", seq=2))

    text = await store.export_jsonl(db_session)
    lines = text.splitlines()
    assert len(lines) == 2
    for line in lines:
        parsed = json.loads(line)
        assert parsed["record_type"] == "setup_evaluation"
        assert val.is_valid(parsed), "an exported line does not validate"


async def test_counts_show_whether_rejections_are_present(db_session, declared):
    """A corpus with no rejections cannot be scored at all — rejections are where most of
    the fidelity signal lives."""
    await store.store(db_session, _evaluation(declared, evaluation_id="e1", decision="SKIP"))
    await store.store(db_session, _evaluation(declared, evaluation_id="e2", decision="TAKE"))

    counts = await store.count_by_type(db_session)
    assert counts["setup_evaluation"] == 2


# ---------------------------------------------------------------------------
# The contract will not let a trade be claimed without its evidence
# ---------------------------------------------------------------------------
async def test_a_take_without_its_stop_ladder_is_refused(db_session, declared):
    """The schema conditionally requires stop_evaluation, target_selection and
    entry_criteria on a TAKE. An engine cannot record a trade without the ladder it chose
    from, the target it aimed at, and the criteria it says were met — which is what makes
    the selection auditable against the alternatives it beat."""
    take = _evaluation(declared, decision="TAKE")
    del take["stop_evaluation"]

    with pytest.raises(val.TelemetryInvalid, match="stop_evaluation"):
        await store.store(db_session, take)


async def test_a_complete_take_is_stored(db_session, declared):
    record = _evaluation(declared, decision="TAKE", evaluation_id="eval-take")
    row = await store.store(db_session, record)
    assert row.decision == "TAKE"
    assert row.payload["stop_evaluation"]["selection_rule_id"] == "CLOSEST_TO_3R_TIES_TO_LARGER"
