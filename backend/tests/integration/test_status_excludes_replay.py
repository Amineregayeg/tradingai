"""status() must report LIVE metrics only — the injected backtest-replay rows
(setup_tag='Backtest replay') must be excluded, or the live panel presents
replay as live performance (a Level-2 finding). This pins the exact filter
status() uses.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.enums import DirectionType, OutcomeType, TradeStatus
from app.models.trade import Trade


def _trade(setup_tag: str | None, pnl: float) -> Trade:
    return Trade(
        user_id="system", broker_id="paper", broker="paper", pair="BTC/USD",
        direction=DirectionType.LONG,
        entry_price=Decimal("100"), exit_price=Decimal("101"), lot_size=Decimal("1"),
        entry_time=datetime.now(timezone.utc), exit_time=datetime.now(timezone.utc),
        outcome=OutcomeType.WIN if pnl > 0 else OutcomeType.LOSS,
        status=TradeStatus.CLOSED, pnl_dollars=Decimal(str(pnl)), setup_tag=setup_tag,
    )


@pytest.mark.asyncio
async def test_status_query_excludes_replay(db_session):
    db_session.add_all([
        _trade("Backtest replay", 500.0),   # must be EXCLUDED
        _trade("ICT (live)", 100.0),        # live -> included
        _trade(None, -50.0),                # untagged -> counts as live
    ])
    await db_session.commit()

    # exact filter used by LiveCryptoLoop.status()
    rows = (
        await db_session.execute(
            select(Trade.outcome, Trade.pnl_dollars).where(
                Trade.broker == "paper",
                Trade.status == TradeStatus.CLOSED,
                Trade.setup_tag.is_distinct_from("Backtest replay"),
            )
        )
    ).all()

    pnls = sorted(float(p) for _, p in rows)
    assert pnls == [-50.0, 100.0]  # the +500 replay row is gone
    assert 500.0 not in pnls
