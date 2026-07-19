"""ADVERSARIAL re-verify: a manual/kill-switch close must (a) persist a LIVE
Trade row status() will count and (b) resolve its DecisionRecord out of
OUTCOME_OPEN. Drives the exact coroutine the settle hook schedules
(_persist_and_resolve) against a real DB.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.db.session as dbsession
from app.models.decision_record import (
    COHORT_PAPER,
    OUTCOME_OPEN,
    OUTCOME_WIN,
    DecisionRecord,
)
from app.models.trade import Trade
from app.services.live.crypto_loop import LiveCryptoLoop


@pytest_asyncio.fixture
async def bound_maker(engine, monkeypatch):
    """Point app.db.session.async_session_maker at the StaticPool test engine so
    the loop's internal async_session_maker() calls hit the same in-memory DB the
    test asserts against."""
    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(dbsession, "async_session_maker", maker)
    monkeypatch.setattr(dbsession, "AsyncSessionLocal", maker)
    return maker


async def test_manual_close_persists_and_resolves(bound_maker):
    loop = LiveCryptoLoop()

    # Seed an OPEN decision for BTC/USD, geometry: entry 100, sl 98, 1 unit -> risk $2
    async with bound_maker() as db:
        rec = DecisionRecord(
            symbol="BTC/USD", timeframe="1H",
            inputs_hash="x", code_path_hash="y",
            abstained=False, signal_dir="LONG",
            signal_entry=Decimal("100"), signal_sl=Decimal("98"),
            signal_tp=Decimal("106"), sized_units=Decimal("1"),
            expected_r=Decimal("3.0"), outcome=OUTCOME_OPEN, cohort=COHORT_PAPER,
        )
        db.add(rec)
        await db.commit()
        dec_id = str(rec.id)

    # NOTE: production stores str(rec.id); asyncpg's uuid_encode accepts a str
    # (pgproto/codecs/uuid.pyx). SQLite's Uuid bind processor requires a UUID
    # object (.hex), so under the SQLite test DB we pass the UUID object to
    # exercise the resolve arithmetic. The string-id path is proven separately.
    loop._open_decision["BTC/USD"] = rec.id

    # Simulate the close event a MANUAL/CLOSE_ALL settle would emit: exit 106 -> +6 pnl
    import datetime as _dt
    ev = {
        "position_id": "paper-abc", "pair": "BTC/USD", "direction": "LONG",
        "entry": 100.0, "exit": 106.0, "units": 1.0, "pnl": 6.0, "reason": "MANUAL",
        "open_time": _dt.datetime.now(_dt.timezone.utc),
        "close_time": _dt.datetime.now(_dt.timezone.utc),
        "balance_after": 50006.0,
    }
    await loop._persist_and_resolve(ev)

    async with bound_maker() as db:
        # (a) a LIVE trade row persisted, counted by status() (tag != 'Backtest replay')
        trades = (await db.execute(select(Trade).where(Trade.broker == "paper"))).scalars().all()
        assert len(trades) == 1
        assert trades[0].setup_tag == "ICT (live)"
        assert float(trades[0].pnl_dollars) == 6.0

        # (b) the DecisionRecord is resolved, no longer OPEN forever
        rec2 = (await db.execute(
            select(DecisionRecord).where(DecisionRecord.id == rec.id))).scalar_one()
        assert rec2.outcome == OUTCOME_WIN
        assert rec2.realized_r is not None
        assert float(rec2.realized_r) == pytest.approx(3.0)  # pnl 6 / risk 2
        assert float(rec2.gap_r) == pytest.approx(0.0)       # realized 3 - expected 3

    # popped so a second (duplicate) settle can't re-resolve
    assert "BTC/USD" not in loop._open_decision
