"""Resetting the engine must give a clean slate WITHOUT destroying evidence (2.1).

Before this, starting a clean run meant an SSH session and a container restart —
so in practice runs were never restarted and results accumulated across
configuration changes, which makes them uninterpretable.

The trap in "reset" is that there were only two obvious implementations and both
are wrong:

  * reset the broker but leave the rows — the dashboard then shows a fresh
    50,000 balance beside trades from before the reset, which is exactly the
    incoherent-numbers defect this project was rebuilt to remove;
  * delete the rows — that destroys `decision_records`, which ARE the evidence
    of whether the strategy works. Backups exist so that evidence survives a
    crash; deleting it on a button press would be worse than any crash.

So a reset ends the current run and starts a new one. These tests pin both
halves: metrics really start at zero, and nothing is deleted.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.enums import DirectionType, OutcomeType, TradeStatus
from app.models.decision_record import COHORT_PAPER, OUTCOME_WIN, DecisionRecord
from app.models.engine_run import EngineRun
from app.models.trade import Trade
from app.services.live.crypto_loop import LiveCryptoLoop

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def bound(engine, monkeypatch):
    """Point the loop's own session maker at the test database."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    import app.db.session as dbsession

    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(dbsession, "async_session_maker", maker)
    monkeypatch.setattr(dbsession, "AsyncSessionLocal", maker)
    return maker


def closed_trade(run_id, pnl: float) -> Trade:
    now = datetime.now(timezone.utc)
    return Trade(
        user_id="system", broker_id="paper", broker="paper", pair="BTC/USD",
        direction=DirectionType.LONG, entry_price=Decimal("100"),
        exit_price=Decimal("101"), lot_size=Decimal("1"),
        entry_time=now, exit_time=now,
        outcome=OutcomeType.WIN if pnl > 0 else OutcomeType.LOSS,
        status=TradeStatus.CLOSED, pnl_dollars=Decimal(str(pnl)),
        setup_tag="ICT (live)", run_id=run_id,
    )


# ---------------------------------------------------------------------------
# A run is adopted, not recreated
# ---------------------------------------------------------------------------
async def test_a_run_is_opened_when_none_exists(bound):
    loop = LiveCryptoLoop()
    run_id = await loop.ensure_run()
    assert run_id is not None

    async with bound() as db:
        rows = (await db.execute(select(EngineRun))).scalars().all()
    assert len(rows) == 1
    assert rows[0].config["risk_pct"] == loop.risk_pct, "config was not snapshotted"


async def test_a_restart_continues_the_same_run(bound):
    """If a restart created a new run, every deploy would silently zero the
    dashboard and no run would ever be long enough to judge."""
    first = LiveCryptoLoop()
    original = await first.ensure_run()

    second = LiveCryptoLoop()          # as if the container was recreated
    adopted = await second.ensure_run()

    assert adopted == original, "a restart started a new run instead of continuing"
    async with bound() as db:
        assert len((await db.execute(select(EngineRun))).scalars().all()) == 1


# ---------------------------------------------------------------------------
# Reset: clean slate, nothing destroyed
# ---------------------------------------------------------------------------
async def test_reset_starts_a_new_run_and_ends_the_old_one(bound):
    loop = LiveCryptoLoop()
    old = await loop.ensure_run()

    await loop.reset_run(note="testing", label="run-2")

    assert loop.run_id != old
    async with bound() as db:
        runs = {r.id: r for r in (await db.execute(select(EngineRun))).scalars().all()}
    assert runs[old].ended_at is not None, "the previous run was left active"
    assert runs[loop.run_id].ended_at is None, "the new run is not active"
    assert runs[loop.run_id].label == "run-2"


async def test_reset_deletes_nothing(bound):
    """The core safety property. decision_records are the evidence that the
    strategy does or does not work."""
    loop = LiveCryptoLoop()
    old = await loop.ensure_run()

    async with bound() as db:
        db.add(closed_trade(old, 250.0))
        db.add(DecisionRecord(
            symbol="BTC/USD", timeframe="1H", inputs_hash="x", code_path_hash="y",
            abstained=False, outcome=OUTCOME_WIN, cohort=COHORT_PAPER, run_id=old,
        ))
        await db.commit()

    await loop.reset_run()

    async with bound() as db:
        trades = (await db.execute(select(Trade))).scalars().all()
        decisions = (await db.execute(select(DecisionRecord))).scalars().all()
    assert len(trades) == 1, "a reset deleted a trade"
    assert len(decisions) == 1, "a reset deleted a decision record — the evidence"
    assert trades[0].run_id == old, "the old row was re-pointed at the new run"


async def test_metrics_start_at_zero_after_a_reset(bound):
    """A clean slate is the whole point: without run scoping the dashboard would
    show a fresh balance beside the previous run's trade count."""
    loop = LiveCryptoLoop()
    old = await loop.ensure_run()

    async with bound() as db:
        db.add_all([closed_trade(old, 250.0), closed_trade(old, -100.0)])
        await db.commit()

    before = await loop.status()
    assert before["closed_trades"] == 2
    assert before["total_pnl"] == pytest.approx(150.0)

    after = await loop.reset_run()
    assert after["closed_trades"] == 0, "the new run inherited the old run's trades"
    assert after["total_pnl"] == pytest.approx(0.0)
    assert after["balance"] == pytest.approx(loop.starting_balance)


async def test_the_old_runs_results_are_still_readable(bound):
    """Scoped away, not erased — the point of scoping rather than deleting."""
    loop = LiveCryptoLoop()
    old = await loop.ensure_run()
    async with bound() as db:
        db.add_all([closed_trade(old, 250.0), closed_trade(old, -100.0)])
        await db.commit()

    await loop.reset_run()

    async with bound() as db:
        rows = (await db.execute(select(Trade).where(Trade.run_id == old))).scalars().all()
    assert len(rows) == 2
    assert sum(float(r.pnl_dollars) for r in rows) == pytest.approx(150.0)


async def test_reset_clears_the_broker_not_just_the_metrics(bound):
    """If the broker kept the old balance, a run whose metrics start at zero
    would show a non-starting balance — the same incoherence in reverse."""
    loop = LiveCryptoLoop()
    await loop.ensure_run()
    loop.paper.balance = 61_234.0
    loop.paused = True

    await loop.reset_run()

    acct = await loop.paper.get_account()
    assert acct.balance == pytest.approx(loop.starting_balance)
    assert loop.paused is False, "a reset left the engine paused"


async def test_reset_does_not_persist_phantom_closes(bound):
    """Closing positions through the normal path would fire the settle hook and
    write closes into the NEW run. A reset must leave no trace in the run it
    starts."""
    loop = LiveCryptoLoop()
    await loop.ensure_run()
    await loop.reset_run()
    new_run = loop.run_id

    async with bound() as db:
        rows = (await db.execute(select(Trade).where(Trade.run_id == new_run))).scalars().all()
    assert rows == [], "the reset itself wrote trades into the new run"


# ---------------------------------------------------------------------------
# New rows belong to the current run
# ---------------------------------------------------------------------------
async def test_new_trades_are_stamped_with_the_active_run(bound):
    loop = LiveCryptoLoop()
    await loop.ensure_run()
    await loop.reset_run()

    import datetime as _dt

    await loop._persist_live_close({  # noqa: SLF001
        "pair": "BTC/USD", "direction": "LONG", "entry": 100.0, "exit": 101.0,
        "units": 1.0, "pnl": 42.0,
        "open_time": _dt.datetime.now(_dt.timezone.utc),
        "close_time": _dt.datetime.now(_dt.timezone.utc),
    })

    async with bound() as db:
        rows = (await db.execute(select(Trade))).scalars().all()
    assert len(rows) == 1
    assert rows[0].run_id == loop.run_id, "a new trade was not stamped with the active run"
    assert (await loop.status())["closed_trades"] == 1
