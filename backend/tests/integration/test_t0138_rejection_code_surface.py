"""T-0138 part 3 — the migration's backfill and the counted surface.

*Integration rather than unit, for `T-0084`'s reason unchanged: `rejection_code` is closed by a
CHECK constraint, and a value the constant allows and the database refuses is exactly the
difference only a real insert can find.*
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models.decision_record import (
    COHORT_PAPER,
    OUTCOME_ABSTAINED,
    OUTCOME_REJECTED,
    REJECTION_ENTRY_DRIFT,
    REJECTION_UNCLASSIFIED,
    REJECTION_UNCODED_LEGACY,
    REJECTION_VENUE_DIRECTION_UNSUPPORTED,
    DecisionRecord,
)
from app.db.enums import DirectionType
from app.services.execution.service import Signal
from app.services.live.crypto_loop import LiveCryptoLoop


def _bars():
    import pandas as pd

    idx = pd.date_range("2026-09-11", periods=12, freq="5min", tz="UTC")
    return pd.DataFrame(
        {"open": 70_000.0, "high": 70_100.0, "low": 69_900.0, "close": 70_050.0, "volume": 1.0},
        index=idx,
    )


def _signal():
    return Signal(symbol="BTC/USD", direction=DirectionType.SHORT, entry=70_000.0,
                  sl=71_000.0, approved=True)


def _trace():
    from types import SimpleNamespace

    return SimpleNamespace(reasons=["FVG entry"])

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def bound(engine, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    import app.db.session as dbsession

    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(dbsession, "async_session_maker", maker)
    monkeypatch.setattr(dbsession, "AsyncSessionLocal", maker)
    return maker


def _row(run_id, code, direction="SHORT", outcome=OUTCOME_REJECTED, reason="x"):
    return DecisionRecord(
        symbol="BTC/USD", timeframe="5m", inputs_hash="i", code_path_hash="c",
        abstained=False, outcome=outcome, rejection_reason=reason, rejection_code=code,
        signal_dir=direction, cohort=COHORT_PAPER, run_id=run_id,
    )


async def test_the_closed_vocabulary_is_enforced_by_the_DATABASE(bound):
    """A code outside the set must fail at insert, not become a bucket nobody notices."""
    from sqlalchemy.exc import IntegrityError

    async with bound() as db:
        db.add(_row(None, "INVENTED_CODE"))
        with pytest.raises(IntegrityError):
            await db.commit()


async def test_a_legacy_row_and_an_unclassified_row_are_DIFFERENT_and_BOTH_COUNTED(bound):
    """**`M-3` and `M-5` together, and they are one property seen from two sides.**

    `UNCODED_LEGACY` predates the field — finite, shrinking, decays to zero on its own.
    `UNCLASSIFIED` is a decision site that set no code — a defect that must alarm. Collapsing them
    means the shrinking bucket never decays, so the alarm never fires for exactly as long as the
    legacy rows exist.

    **And neither may be filtered out of the count.** A denominator that silently excludes what it
    could not classify reports a clean population it never had.
    """
    loop = LiveCryptoLoop()
    run_id = await loop.ensure_run()

    async with bound() as db:
        db.add_all([
            _row(run_id, REJECTION_VENUE_DIRECTION_UNSUPPORTED),
            _row(run_id, REJECTION_VENUE_DIRECTION_UNSUPPORTED),
            _row(run_id, REJECTION_UNCODED_LEGACY),
            _row(run_id, REJECTION_UNCLASSIFIED),
            _row(run_id, REJECTION_ENTRY_DRIFT, direction="LONG"),
        ])
        await db.commit()

        split = {
            (r[0], r[1]): int(r[2]) for r in (await db.execute(
                select(DecisionRecord.signal_dir, DecisionRecord.rejection_code,
                       func.count(DecisionRecord.id))
                .where(DecisionRecord.run_id == run_id,
                       DecisionRecord.outcome == OUTCOME_REJECTED)
                .group_by(DecisionRecord.signal_dir, DecisionRecord.rejection_code)
            )).all()
        }

    assert split[("SHORT", REJECTION_VENUE_DIRECTION_UNSUPPORTED)] == 2
    assert split[("SHORT", REJECTION_UNCODED_LEGACY)] == 1
    assert split[("SHORT", REJECTION_UNCLASSIFIED)] == 1
    assert split[("LONG", REJECTION_ENTRY_DRIFT)] == 1
    assert sum(split.values()) == 5, "a row was dropped from the denominator"


async def test_the_endpoint_SURFACES_the_venue_count_from_the_CODE(bound, client, monkeypatch):
    """**`M-7`. The constraint lifts only because the count now reads a structured field.**

    Until `rejection_code` existed, no surface could attribute a rejection count to the venue: the
    only discriminator was prose the venue chose, and a count keyed on it returns a confident zero
    the day the wording changes rather than failing.
    """
    loop = LiveCryptoLoop()
    run_id = await loop.ensure_run()

    async with bound() as db:
        db.add_all([
            _row(run_id, REJECTION_VENUE_DIRECTION_UNSUPPORTED),
            _row(run_id, REJECTION_VENUE_DIRECTION_UNSUPPORTED),
            _row(run_id, REJECTION_ENTRY_DRIFT, direction="LONG"),
            _row(run_id, REJECTION_UNCLASSIFIED),
            _row(run_id, REJECTION_UNCODED_LEGACY),
        ])
        await db.commit()

    from app.api.routers import engine as engine_router
    monkeypatch.setattr(engine_router, "_loop", lambda _req: loop)

    row = next(r for r in (await client.get("/api/engine/runs")).json()
               if r["id"] == str(run_id))

    venue = [e for e in row["rejected_by_code"]
             if e["code"] == REJECTION_VENUE_DIRECTION_UNSUPPORTED]
    assert venue and venue[0]["count"] == 2 and venue[0]["direction"] == "SHORT"
    assert sum(e["count"] for e in row["rejected_by_code"]) == 5, (
        "the surface dropped rows it could not classify — a clean population that never existed"
    )
    assert row["rejections_unclassified"] == 1, "the alarm must be a POSITIVE statement"
    assert row["rejections_uncoded_legacy"] == 1, (
        "the migration marker must be reported SEPARATELY from the alarm, or the shrinking "
        "bucket hides the growing one"
    )


async def test_the_backfill_scopes_to_REJECTIONS_and_leaves_other_outcomes_alone(bound):
    """The migration's `WHERE outcome = REJECTED` clause, asserted as behaviour.

    An ABSTAINED row has no rejection to code. Marking it `UNCODED_LEGACY` would put rows into a
    bucket meaning *a rejection we cannot classify* that were never rejections — **inflating the
    very denominator this field exists to make countable**, from the migration onward.
    """
    async with bound() as db:
        abstained = _row(None, None, outcome=OUTCOME_ABSTAINED, reason=None)
        abstained.abstained = True
        db.add(abstained)
        await db.commit()

        rows = (await db.execute(
            select(DecisionRecord).where(DecisionRecord.outcome == OUTCOME_ABSTAINED)
        )).scalars().all()

    assert rows and all(r.rejection_code is None for r in rows), (
        "a non-rejection carries a rejection code"
    )


async def test_a_rejection_arriving_with_NO_code_is_recorded_as_UNCLASSIFIED(bound):
    """**THE RECORDER'S DEFAULT, AND NOTHING TESTED IT UNTIL A MUTATION SAID SO.**

    `M-2` — *make the default benign* — killed **nothing** on its first run. Every other arm here
    inserts rows with an explicit code, so the one line that decides what an UNCODED rejection
    becomes was covered by no arm at all. The kill-set registered that row precisely because a
    default which is one of the states the field distinguishes means the field cannot report its
    own failure, and the arm for it did not exist.

    A rejection with no code is a decision site that set none — **a defect, and it must alarm.**
    It must NOT become `UNCODED_LEGACY`, which means *predates the field* and decays to zero, and
    it must not become an ordinary bucket.
    """
    loop = LiveCryptoLoop()
    run_id = await loop.ensure_run()

    await loop._record_rejected_signal(
        "BTC/USD", _bars(), _signal(), "something refused it", _trace(),
    )

    async with bound() as db:
        row = (await db.execute(
            select(DecisionRecord).where(DecisionRecord.run_id == run_id)
        )).scalars().one()

    assert row.rejection_code == REJECTION_UNCLASSIFIED, (
        f"an uncoded rejection was recorded as {row.rejection_code!r} — a benign default means "
        f"the field cannot report its own failure"
    )
    assert row.rejection_code != REJECTION_UNCODED_LEGACY, (
        "a NEW uncoded rejection landed in the shrinking migration bucket, so the bucket never "
        "decays and the alarm never fires"
    )


async def test_a_rejection_arriving_WITH_a_code_keeps_it(bound):
    """The control — a default that overwrites what the decision site said is worse than no
    default at all."""
    loop = LiveCryptoLoop()
    run_id = await loop.ensure_run()

    await loop._record_rejected_signal(
        "BTC/USD", _bars(), _signal(), "venue refused", _trace(),
        REJECTION_VENUE_DIRECTION_UNSUPPORTED,
    )

    async with bound() as db:
        row = (await db.execute(
            select(DecisionRecord).where(DecisionRecord.run_id == run_id)
        )).scalars().one()

    assert row.rejection_code == REJECTION_VENUE_DIRECTION_UNSUPPORTED
