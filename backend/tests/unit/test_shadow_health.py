"""A shadow that stops recording must become a field with a number in it (B32).

WHAT THIS REPRODUCES
On 2026-08-13 a vocabulary mismatch in `_correlates_block` made every shadow record
fail schema validation. The engine traded normally; only the evidence base went dark,
for about forty minutes. **Three agents independently explained the silence and all
three were wrong** — none considered that the shadow was crashing, because
`_shadow_evaluate` swallows everything by design and a legitimate wait looks identical
from outside.

THE HARD CONSTRAINT ON HOW, FROM THE PLAN
The reproduction must go through the REAL validator — `validate.assert_valid` — and not
through a key list. `test_shadow_correlate_panels.py:414` imports the validator with
`# noqa: F401` and never calls it, asserting a hardcoded key set while its docstring
claims to check the schema. A key list is the method that CAUSED the outage, with a
better list: the next required property added to `correlate_state` reproduces the
forty-minute silence with a green test.

WHAT CHANGED SINCE THE PLAN WAS WRITTEN
The plan's criteria 2 and 4 describe a shadow that sat BELOW the entry gates, where
`already in a position` suppressed recording and long silences were normal. T-0010
moved the call above the gates. `blocked` is no longer a state and a due bar with no
record now means broken, full stop — which makes this signal considerably sharper than
the one the plan could have specified.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.engine_run import EngineRun
from app.models.telemetry_record import TelemetryRecord
from app.services.monitoring import data_health as dh

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def bound(engine, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    import app.db.session as dbsession

    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(dbsession, "async_session_maker", maker)
    monkeypatch.setattr(dbsession, "AsyncSessionLocal", maker)
    return maker


async def _run(maker, started_minutes_ago: float = 120.0) -> EngineRun:
    row = EngineRun(
        started_at=datetime.now(tz=timezone.utc) - timedelta(minutes=started_minutes_ago)
    )
    async with maker() as db:
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


async def _record(maker, minutes_ago: float, instrument: str = "BTC/USD") -> None:
    async with maker() as db:
        db.add(
            TelemetryRecord(
                record_type="setup_evaluation",
                record_id=f"ev-{instrument}-{minutes_ago}",
                instrument=instrument,
                created_at=datetime.now(tz=timezone.utc) - timedelta(minutes=minutes_ago),
                payload={"record_type": "setup_evaluation"},
            )
        )
        await db.commit()


# ---------------------------------------------------------------------------
# CRITERION 3 — the outage that motivated the task
# ---------------------------------------------------------------------------

async def test_the_forty_minute_outage_is_reported_while_the_engine_runs(bound):
    """THE CRITERION. An engine that is running and a shadow that is not.

    This is the exact shape of 2026-08-13: an active run, the ICT path trading, and no
    telemetry for forty minutes. Before this task the only signal was absence, which is
    indistinguishable from a legitimate wait — and was in fact mistaken for one, three
    times independently.
    """
    await _run(bound)
    await _record(bound, minutes_ago=40)          # last record 40 min ago

    h = await dh.shadow_health()

    assert h["status"] in ("stale", "down"), (
        f"a 40-minute shadow silence reported {h['status']!r} while the engine ran"
    )
    assert h["watching"] is True
    assert h["evaluation_state"] == "due"
    assert h["age_minutes"] == pytest.approx(40, abs=2)
    assert "warning" in h
    # It must not imply it knows WHICH failure this is — the remedies differ.
    assert "ambiguous_between" in h and len(h["ambiguous_between"]) == 2


async def test_a_recording_shadow_reads_healthy(bound):
    """The other half. A signal that only ever says 'broken' is not a signal."""
    await _run(bound)
    await _record(bound, minutes_ago=1)

    h = await dh.shadow_health()
    assert h["status"] == "healthy"
    assert h["evaluation_state"] == "not_due"
    assert "warning" not in h


# ---------------------------------------------------------------------------
# CRITERION 3's REAL-VALIDATOR CLAUSE — the outage went through the validator,
# so the reproduction must too.
# ---------------------------------------------------------------------------

async def test_the_outage_is_reproduced_through_the_real_validator():
    """A record missing a required `correlate_state` property must be REJECTED.

    This is what actually happened: `_correlates_block` emitted the grader's vocabulary
    (`asset`, no `tf`) where the schema requires `symbol` and `tf`. Every record failed
    `assert_valid`, `_shadow_evaluate` swallowed it, and nothing was written.

    Asserted by CALLING `validate.errors`, not by comparing key sets. A key-list test
    passes the moment its list is complete and stops tracking the schema thereafter —
    which is the defect that produced the outage, one level up.
    """
    from app.services.telemetry import validate as val

    good = _minimal_setup_evaluation()
    assert val.errors(good) == [], (
        "the fixture is not schema-valid to begin with, so the mutation below would "
        "prove nothing"
    )

    # THE MUTATION: reproduce the exact defect — drop `tf` from a correlate state.
    broken = _minimal_setup_evaluation()
    states = broken["correlates"]["states"]
    assert states and "tf" in states[0], "fixture drifted; the mutation targets nothing"
    del states[0]["tf"]

    assert val.errors(broken), (
        "the real validator accepted a correlate_state with no `tf` — this is the "
        "record shape that went dark for forty minutes"
    )


def _minimal_setup_evaluation() -> dict:
    """A schema-valid record built by the PRODUCTION builder, not a hand-rolled dict.

    `rec.setup_evaluation` is what the shadow itself calls. Hand-assembling the payload
    here would make this test assert against my idea of the schema — which is exactly
    the error that produced the outage being reproduced.
    """
    from app.services.telemetry import records as rec

    declared = rec.DeclaredParameters(
        virtual_account_size=5_000.0,
        evaluation_order_id="magic-v1",
        emission_policy_id="every-closed-bar-with-sufficient-history-v2",
        layout_size_frozen=True,
        main_asset_counts=False,
        box_scope="ENTRY_BOX_EXEC_TF",
        stop_selection_reading="CLOSEST_TO_3R_TIES_TO_LARGER",
        runner_management_policy="70_30_partial_then_runner",
        reverse_quorum=None,
    )
    return rec.setup_evaluation(
        timestamp=datetime(2026, 8, 14, 13, 0, tzinfo=timezone.utc),
        declared=declared,
        scan_context={
            "scan_id": "scan-1",
            "sequence_no": 1,
            "candidate_origin": "SCHEDULED_BAR_CLOSE",
            "bar_close_time_ny": "2026-08-14T09:00:00-04:00",
            "data_as_of_ny": "2026-08-14T09:00:05-04:00",
            "pre_filters_applied": [],
        },
        instrument={
            "symbol": "BTCUSDT.P",
            "instrument_class": "ALIGNED_MAJOR",
            "venue": "BINANCE_FUTURES",
        },
        mode={"trading_mode": "DAY_TRADE", "direction_mode": "FORWARD"},
        timeframes={"signal_tf": "5M", "alignment_tf": "5M", "analysis_tfs_scanned": ["1D"]},
        session={
            "ny_local_time": "2026-08-14T09:00:00-04:00",
            "tz_offset_used": "-04:00",
            "in_magic_zone": False,
            "minutes_from_nyo": -30,
        },
        primitives={
            "swing_points": [], "structure_boxes": [], "imbalances": [],
            "liquidity_pools": [], "sweeps": [], "breaks": [],
        },
        # A POPULATED state — an empty `states` list cannot carry the defect, so a
        # fixture with `states: []` would make the mutation below unfalsifiable.
        correlates={
            "layout_size": 4,
            "disturbed_count": 0,
            "disturbance_grade": "NONE",
            "states": [
                {
                    "symbol": "USDT.D",
                    "role": "NEGATIVE",
                    "tf": "5M",
                    "expected_sign": "BEARISH",
                    "observed_order_flow": "BEARISH",
                    "disturbed": False,
                }
            ],
        },
        rule_evaluations=[
            rec.RuleEvaluation(
                rule_id="GATE-012",
                verdict="PASS",
                values={"minutes_to_event": 120},
                value_provenance={
                    "minutes_to_event": rec.from_record("news_context.events_considered")
                },
            )
        ],
        decision="SKIP",
        deciding_rule_id="GATE-012",
        risk_assessment={"box_grade": "STANDARD", "risk_pct": 0.01},
    )


# ---------------------------------------------------------------------------
# CRITERION 2 — the cadence is DERIVED
# ---------------------------------------------------------------------------

async def test_the_expected_cadence_follows_entry_tf_rather_than_a_constant(
    bound, monkeypatch
):
    """B21's class. A hardcoded cadence was wrong within a day when 1H became 5m.

    Moving `ENTRY_TF` must move the expectation, and must move what counts as stale —
    eleven minutes of silence is nothing at 1H and two missed bars at 5m.
    """
    from app.services.live import fixed_config

    await _run(bound)
    await _record(bound, minutes_ago=11)

    monkeypatch.setattr(fixed_config, "ENTRY_TF", "5m")
    at_5m = await dh.shadow_health()

    monkeypatch.setattr(fixed_config, "ENTRY_TF", "1H")
    at_1h = await dh.shadow_health()

    assert at_5m["expected_per_hour"] > at_1h["expected_per_hour"], (
        "the expectation did not move with ENTRY_TF — it is hardcoded somewhere"
    )
    assert at_5m["expected_per_hour"] == 12 * at_1h["expected_per_hour"]
    assert at_5m["status"] in ("stale", "down") and at_1h["status"] == "healthy", (
        "the same 11-minute silence must be a problem at 5m and normal at 1H"
    )


# ---------------------------------------------------------------------------
# CRITERION 4 — legitimate silences must not read as broken
# ---------------------------------------------------------------------------

async def test_no_active_run_is_idle_and_not_watching(bound):
    """No run means nothing is due. That is not health and it is not a defect.

    Reported as `idle` + `watching: False` rather than `healthy`, following this
    module's founding rule: a check that is not looking must not read the same as one
    that looked and found nothing wrong.
    """
    h = await dh.shadow_health()
    assert h["status"] == "idle"
    assert h["watching"] is False
    assert "expected_per_hour" in h


async def test_a_just_started_run_is_not_due_rather_than_broken(bound):
    """The first bar has not closed yet. Absence here is correct.

    Without this the signal would report every engine start as a shadow failure, which
    is the cry-wolf failure the plan warns about: routinely wrong, therefore ignored,
    therefore useless when it matters.
    """
    await _run(bound, started_minutes_ago=1)

    h = await dh.shadow_health()
    assert h["status"] == "healthy"
    assert h["evaluation_state"] == "not_due"


# ---------------------------------------------------------------------------
# CRITERION 9 — the payload states what it does NOT attest
# ---------------------------------------------------------------------------

async def test_the_payload_says_it_attests_liveness_only(bound):
    """A field, not a comment.

    A shadow can be alive, writing on every cycle, and grading a still-forming bar —
    a defect this project actually shipped, on GATE-008's MAIN panel, whose grade keys
    the risk matrix. Every liveness field reads healthy throughout. Without this in the
    payload, the first green reading is what gets cited when someone asks whether the
    correlate layer can be trusted.
    """
    await _run(bound)
    await _record(bound, minutes_ago=1)

    h = await dh.shadow_health()
    assert h["attests"] == "liveness_only"
    assert any("correctness" in s for s in h["does_not_attest"])

    # And it must survive into the composed endpoint, which is what anyone actually reads.
    composed = await dh.data_health()
    assert composed["shadow"]["attests"] == "liveness_only"


async def test_an_unhealthy_shadow_makes_the_whole_endpoint_not_ok(bound):
    """Otherwise the section is decoration: present, correct, and read by nobody."""
    await _run(bound)
    await _record(bound, minutes_ago=90)

    composed = await dh.data_health()
    assert composed["ok"] is False
    assert "shadow" in composed["problems"]

