"""Tests for the trade journal service.

Covers the actual code paths in app.services.journal.service:
- close_trade_from_broker: outcome mapping (WIN/LOSS/BE) + status transitions
- update_trade_notes: notes/setup_tag persistence
- get_trades: pair/outcome/date filters + pagination
- export_trades_csv: shape + filter respect
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.db.enums import DirectionType, OutcomeType, TradeStatus
from app.models.trade import Trade
from app.services.journal.service import (
    close_trade_from_broker,
    export_trades_csv,
    get_trades,
    update_trade_notes,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


async def _make_open_trade(db, *, broker_id="OANDA-1", broker="oanda", pair="EUR/USD",
                            entry_price=1.0850, entry_time=None) -> Trade:
    """Create and persist an OPEN trade."""
    t = Trade(
        user_id="system",
        broker_id=broker_id,
        broker=broker,
        pair=pair,
        direction=DirectionType.LONG,
        entry_price=Decimal(str(entry_price)),
        lot_size=Decimal("0.1"),
        entry_time=entry_time or datetime.now(tz=timezone.utc),
        outcome=OutcomeType.OPEN,
        status=TradeStatus.OPEN,
    )
    db.add(t)
    await db.flush()
    return t


# ---------------------------------------------------------------------------
# close_trade_from_broker — outcome mapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_trade_with_positive_pnl_marks_win(db_session):
    t = await _make_open_trade(db_session)
    closed = await close_trade_from_broker(
        db=db_session, user_id="system",
        broker_id=t.broker_id, broker=t.broker,
        exit_price=1.09000, exit_time=datetime.now(tz=timezone.utc),
        pnl_dollars=50.0, pnl_pips=50.0,
    )
    assert closed is not None
    assert closed.outcome == OutcomeType.WIN
    assert closed.status == TradeStatus.CLOSED
    assert closed.pnl_dollars == Decimal("50.0")


@pytest.mark.asyncio
async def test_close_trade_with_negative_pnl_marks_loss(db_session):
    t = await _make_open_trade(db_session)
    closed = await close_trade_from_broker(
        db=db_session, user_id="system",
        broker_id=t.broker_id, broker=t.broker,
        exit_price=1.08000, exit_time=datetime.now(tz=timezone.utc),
        pnl_dollars=-50.0, pnl_pips=-50.0,
    )
    assert closed.outcome == OutcomeType.LOSS


@pytest.mark.asyncio
async def test_close_trade_with_zero_pnl_marks_be(db_session):
    t = await _make_open_trade(db_session)
    closed = await close_trade_from_broker(
        db=db_session, user_id="system",
        broker_id=t.broker_id, broker=t.broker,
        exit_price=1.08500, exit_time=datetime.now(tz=timezone.utc),
        pnl_dollars=0.0, pnl_pips=0.0,
    )
    assert closed.outcome == OutcomeType.BE


@pytest.mark.asyncio
async def test_close_trade_with_naive_exit_time_accepted(db_session):
    """Service must accept a naive datetime without crashing (it tags it UTC).
    SQLite-aiosqlite strips tzinfo on roundtrip so we can only verify the value persisted."""
    t = await _make_open_trade(db_session)
    naive = datetime(2026, 5, 29, 12, 30, 0)
    closed = await close_trade_from_broker(
        db=db_session, user_id="system",
        broker_id=t.broker_id, broker=t.broker,
        exit_price=1.09, exit_time=naive, pnl_dollars=10.0, pnl_pips=10.0,
    )
    assert closed.exit_time is not None
    assert closed.exit_time.year == 2026
    assert closed.exit_time.hour == 12


@pytest.mark.asyncio
async def test_close_trade_returns_none_when_no_open_trade(db_session):
    closed = await close_trade_from_broker(
        db=db_session, user_id="system",
        broker_id="DOES-NOT-EXIST", broker="oanda",
        exit_price=1.0, exit_time=datetime.now(tz=timezone.utc),
        pnl_dollars=0.0, pnl_pips=0.0,
    )
    assert closed is None


# ---------------------------------------------------------------------------
# update_trade_notes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_notes_persists(db_session):
    t = await _make_open_trade(db_session)
    updated = await update_trade_notes(
        db=db_session, user_id="system", trade_id=t.id,
        notes="Took it at London open", setup_tag="FVG-fill long",
    )
    assert updated.notes == "Took it at London open"
    assert updated.setup_tag == "FVG-fill long"


@pytest.mark.asyncio
async def test_update_notes_returns_none_when_not_found(db_session):
    import uuid
    result = await update_trade_notes(
        db=db_session, user_id="system",
        trade_id=uuid.uuid4(), notes="x", setup_tag=None,
    )
    assert result is None


@pytest.mark.asyncio
async def test_update_notes_user_scoping(db_session):
    """A trade owned by user A is invisible to user B."""
    import uuid
    t = await _make_open_trade(db_session)
    # Same trade_id, different user_id — must return None
    result = await update_trade_notes(
        db=db_session, user_id="other-user",
        trade_id=t.id, notes="x", setup_tag=None,
    )
    assert result is None


# ---------------------------------------------------------------------------
# get_trades — pagination + filters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_trades_returns_total_count(db_session):
    for i in range(3):
        await _make_open_trade(db_session, broker_id=f"OANDA-{i}")
    await db_session.flush()
    trades, total = await get_trades(db_session, "system")
    assert total == 3
    assert len(trades) == 3


@pytest.mark.asyncio
async def test_get_trades_filters_by_pair(db_session):
    await _make_open_trade(db_session, broker_id="A", pair="EUR/USD")
    await _make_open_trade(db_session, broker_id="B", pair="GBP/USD")
    await db_session.flush()
    trades, total = await get_trades(db_session, "system", pair="GBP/USD")
    assert total == 1
    assert trades[0].pair == "GBP/USD"


@pytest.mark.asyncio
async def test_get_trades_filters_by_outcome(db_session):
    t1 = await _make_open_trade(db_session, broker_id="A")
    t2 = await _make_open_trade(db_session, broker_id="B")
    t1.outcome = OutcomeType.WIN
    t2.outcome = OutcomeType.LOSS
    await db_session.flush()
    trades, total = await get_trades(db_session, "system", outcome="WIN")
    assert total == 1
    assert trades[0].outcome == OutcomeType.WIN


@pytest.mark.asyncio
async def test_get_trades_filters_by_date_range(db_session):
    now = datetime.now(tz=timezone.utc)
    yesterday = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)
    await _make_open_trade(db_session, broker_id="A", entry_time=yesterday)
    await _make_open_trade(db_session, broker_id="B", entry_time=week_ago)
    await db_session.flush()
    trades, total = await get_trades(
        db_session, "system", from_dt=now - timedelta(days=3), to_dt=now,
    )
    assert total == 1
    assert trades[0].broker_id == "A"


@pytest.mark.asyncio
async def test_get_trades_pagination(db_session):
    for i in range(7):
        # different entry_time so ordering is deterministic
        await _make_open_trade(db_session, broker_id=f"OANDA-{i:02d}",
                                entry_time=datetime(2026, 5, 1 + i, tzinfo=timezone.utc))
    await db_session.flush()
    page1, total = await get_trades(db_session, "system", page=1, per_page=3)
    page2, _ = await get_trades(db_session, "system", page=2, per_page=3)
    assert total == 7
    assert len(page1) == 3
    assert len(page2) == 3
    # No overlap between pages
    assert {t.id for t in page1}.isdisjoint({t.id for t in page2})


@pytest.mark.asyncio
async def test_get_trades_invalid_outcome_filter_does_not_crash(db_session):
    """Bad outcome filter is logged and ignored, not raised."""
    await _make_open_trade(db_session)
    await db_session.flush()
    trades, total = await get_trades(db_session, "system", outcome="NOT_A_VALID_OUTCOME")
    assert total == 1


@pytest.mark.asyncio
async def test_get_trades_user_scoping(db_session):
    """A user only sees their own trades."""
    await _make_open_trade(db_session)
    await db_session.flush()
    trades, total = await get_trades(db_session, "other-user")
    assert total == 0
    assert trades == []


# ---------------------------------------------------------------------------
# export_trades_csv
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_csv_includes_header_row(db_session):
    await _make_open_trade(db_session)
    await db_session.flush()
    csv = await export_trades_csv(db_session, "system", None, None)
    first_line = csv.splitlines()[0]
    # Header must include the key columns the spec calls out
    for col in ["id", "broker_id", "pair", "direction", "entry_price", "exit_price",
                "lot_size", "entry_time", "outcome", "pnl_dollars", "pnl_pips"]:
        assert col in first_line, f"CSV header missing {col}"


@pytest.mark.asyncio
async def test_export_csv_respects_date_filter(db_session):
    now = datetime.now(tz=timezone.utc)
    await _make_open_trade(db_session, broker_id="recent", entry_time=now)
    await _make_open_trade(db_session, broker_id="old",
                            entry_time=now - timedelta(days=30))
    await db_session.flush()
    csv = await export_trades_csv(db_session, "system",
                                    from_dt=now - timedelta(days=7), to_dt=None)
    assert "recent" in csv
    assert "old" not in csv


@pytest.mark.asyncio
async def test_export_csv_empty_when_no_trades(db_session):
    csv = await export_trades_csv(db_session, "system", None, None)
    # Just the header row
    assert csv.count("\n") == 1
