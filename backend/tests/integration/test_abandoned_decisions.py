"""A decision the engine died holding is resolved, not left claiming to be open.

KNOWN_ISSUES A11, from run `7d788ad6`. On 2026-08-08 06:00 the engine opened an
ETH long at 1917.55. ETH traded between 1914.00 and 1926.72 for the next twelve
hours — it reached neither the stop nor the target — and then the api container
was recreated for a deploy. The simulated broker holds positions in memory, so the
position ceased to exist. Its decision record still read `outcome = OPEN`, no
trade row was ever written, and the run's headline said **0 trades** for a run
that had taken one.

TWO THINGS WERE WRONG AND ONLY ONE IS ABOUT A COUNT
The visible error is the missing trade. The costly one is that `OPEN` keeps a
record out of the feedback loop permanently — the loop learns only from closed
outcomes — so every restart quietly deleted evidence from the learning path
rather than merely from a total.

`ABANDONED` is therefore its own outcome and not a synonym for breakeven: the
trade happened, and its result is unknowable. Recording a zero would put a number
nobody observed into the population that tunes the strategy.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.decision_record import (
    COHORT_PAPER,
    OUTCOME_ABANDONED,
    OUTCOME_ABSTAINED,
    OUTCOME_OPEN,
    OUTCOME_WIN,
    DecisionRecord,
)
from app.services.live.crypto_loop import LiveCryptoLoop

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def bound(engine, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    import app.db.session as dbsession

    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(dbsession, "async_session_maker", maker)
    monkeypatch.setattr(dbsession, "AsyncSessionLocal", maker)
    return maker


def record(outcome=OUTCOME_OPEN, symbol="ETH/USD") -> DecisionRecord:
    return DecisionRecord(
        symbol=symbol, timeframe="1H",
        inputs_hash="a" * 16, code_path_hash="b" * 16,
        abstained=False, reasons=["PASS history: 324 bars available, 60 required"],
        outcome=outcome, cohort=COHORT_PAPER,
    )


async def outcomes(maker) -> list[str]:
    async with maker() as db:
        return [r.outcome for r in (await db.execute(select(DecisionRecord))).scalars().all()]


# ---------------------------------------------------------------------------
async def test_a_record_left_open_by_a_dead_process_is_resolved(bound):
    """The exact shape of A11: a record with no live position behind it."""
    async with bound() as db:
        db.add(record())
        await db.commit()

    n = await LiveCryptoLoop().reconcile_abandoned_decisions()

    assert n == 1
    assert await outcomes(bound) == [OUTCOME_ABANDONED]


async def test_the_record_says_what_happened_to_it(bound):
    """`ABANDONED` alone requires the reader to know that it implies a restart.
    The row should explain itself years later, to someone who does not."""
    async with bound() as db:
        db.add(record())
        await db.commit()

    await LiveCryptoLoop().reconcile_abandoned_decisions()

    async with bound() as db:
        rec = (await db.execute(select(DecisionRecord))).scalars().one()
    assert any("ABANDONED" in r for r in rec.reasons)
    assert any("never observed" in r or "absence" in r for r in rec.reasons)


async def test_a_position_this_process_is_holding_is_left_alone(bound):
    """This runs at Start, not only at boot. A record belonging to a live
    position must survive it, or pressing Start would resolve the trade the
    engine is in the middle of."""
    async with bound() as db:
        rec = record()
        db.add(rec)
        await db.commit()
        await db.refresh(rec)
        live_id = rec.id

    loop = LiveCryptoLoop()
    loop._open_decision["ETH/USD"] = str(live_id)
    n = await loop.reconcile_abandoned_decisions()

    assert n == 0
    assert await outcomes(bound) == [OUTCOME_OPEN]


async def test_resolved_records_are_not_touched(bound):
    """Reconciliation must be idempotent and must never rewrite a real result."""
    async with bound() as db:
        db.add(record(outcome=OUTCOME_WIN))
        db.add(record(outcome=OUTCOME_ABSTAINED))
        await db.commit()

    assert await LiveCryptoLoop().reconcile_abandoned_decisions() == 0
    assert sorted(await outcomes(bound)) == sorted([OUTCOME_WIN, OUTCOME_ABSTAINED])


async def test_running_it_twice_changes_nothing_the_second_time(bound):
    async with bound() as db:
        db.add(record())
        await db.commit()

    loop = LiveCryptoLoop()
    assert await loop.reconcile_abandoned_decisions() == 1
    assert await loop.reconcile_abandoned_decisions() == 0


async def test_start_reconciles_before_opening_its_own_run(bound, monkeypatch):
    """The abandoned records belong to the run that created them. Reconciling
    after the new run opened would file someone else's casualty under it."""
    async def noop(self):
        return None
    monkeypatch.setattr(LiveCryptoLoop, "_loop", noop)

    async with bound() as db:
        db.add(record())
        await db.commit()

    loop = LiveCryptoLoop()
    await loop.start()

    async with bound() as db:
        rec = (await db.execute(select(DecisionRecord))).scalars().one()
    assert rec.outcome == OUTCOME_ABANDONED
    assert rec.run_id != loop.run_id, "the abandoned record was adopted by the new run"


async def test_abandoned_never_reaches_the_learning_population(bound):
    """The reason it is its own outcome rather than a breakeven. A fabricated
    zero would be indistinguishable from a measured one inside the loop."""
    from app.services.evaluation.feedback import _classify_outcome

    assert _classify_outcome({"outcome": OUTCOME_ABANDONED}, None) == "abandoned"
    assert _classify_outcome({"outcome": OUTCOME_ABANDONED}, 0.0) == "abandoned"
    # and it is not quietly read as a result
    assert _classify_outcome({"outcome": OUTCOME_ABANDONED}, -1.4) == "abandoned"


async def test_the_feedback_loop_never_counts_an_abandoned_trade(bound):
    """The mutation this exists for: dropping "abandoned" from the exclusion at
    the call site while `_classify_outcome` keeps returning it correctly. The
    classifier being right is not the property that matters — what matters is
    that the analysis never sees the record.

    An abandoned trade carries a realized_r only because something had to be
    written in the column. Letting that reach the population means the loop tunes
    the strategy on a number nobody measured.
    """
    from app.services.evaluation.feedback import analyze

    def row(outcome, r):
        return {
            "symbol": "BTCUSDT", "timeframe": "1H", "signal_dir": "LONG",
            "signal_entry": 100.0, "signal_sl": 99.0, "signal_tp": 103.0,
            "sized_units": 1000.0, "expected_r": 3.0, "realized_r": r,
            "gap_r": r - 3.0, "outcome": outcome, "fill_price": 100.0,
            "cohort": "paper", "abstained": False,
        }

    real = [row(OUTCOME_WIN, 3.0) for _ in range(4)]
    ghosts = [row(OUTCOME_ABANDONED, -1.0) for _ in range(40)]

    without = analyze(real, {"risk_pct": 0.01}, min_evidence=1)
    with_ghosts = analyze(real + ghosts, {"risk_pct": 0.01}, min_evidence=1)

    assert without["n"] == 4, "the real population changed shape"
    assert with_ghosts["n"] == 4, (
        f"{with_ghosts['n'] - 4} abandoned trade(s) entered the learning population"
    )
    assert (with_ghosts["expected_vs_actual"]["mean_realized_r"]
            == without["expected_vs_actual"]["mean_realized_r"]), (
        "abandoned trades moved the measured mean"
    )
