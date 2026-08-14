"""The LIVE write path must attribute its rows, not merely be able to (T-0013).

WHY THIS EXISTS SEPARATELY FROM `test_decision_attribution.py`
That file proves the `Attribution` value object behaves. It builds rows with
`_row(**Attribution.ict().as_columns())` — which tests the object, and would keep
passing if `crypto_loop` never called it. The gap is real and was raised in review
as a suspected defect: a grep for `decided_by` across `backend/app` finds nothing
outside the model, because the call site reads `**Attribution.ict().as_columns()`
and the column names live inside the helper. **The wiring is invisible to a textual
search**, so it needs a test that runs the actual writer rather than one that reads
like the writer.

WHAT WOULD BREAK WITHOUT IT
Criterion 6 expects every new row to be case 1 (`ICT`). If a write site dropped the
attribution, every row would be written `UNSET` — the "nobody said" state — and the
`UNSET` defect query would then return 100% of new rows, permanently. A detector
that fires on every row is the liveness-signal failure: routinely wrong, therefore
ignored, therefore useless when it matters.

And note which way the sentinel cuts here. Before `decided_by` defaulted to `UNSET`
it defaulted to `ICT`, so an unwired write path would have produced `ICT` on every
row — indistinguishable from criterion 6 being satisfied, and reportable as green
while being entirely false. The sentinel is what makes an unwired path visible at
all; this test is what turns "visible if someone queries" into "red in CI".
"""
from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy import select

from app.models.decision_record import (
    DECIDED_BY_ICT,
    DECIDED_BY_UNSET,
    OUTCOME_ABSTAINED,
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


def _bars() -> pd.DataFrame:
    idx = pd.date_range("2026-08-14", periods=12, freq="5min", tz="UTC")
    return pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1.0},
        index=idx,
    )


async def _rows(maker) -> list[DecisionRecord]:
    async with maker() as db:
        return list((await db.execute(select(DecisionRecord))).scalars().all())


async def test_the_live_abstention_path_attributes_its_row_to_ICT(bound):
    """Runs `_record_abstention` itself. Nothing here constructs an Attribution."""
    await LiveCryptoLoop()._record_abstention(
        "BTC/USD", _bars(), SimpleNamespace(reasons=["no alignment"])
    )

    rows = await _rows(bound)
    assert len(rows) == 1, "the live path wrote no row at all"
    assert rows[0].outcome == OUTCOME_ABSTAINED
    assert rows[0].decided_by == DECIDED_BY_ICT, (
        f"the live write path recorded decided_by={rows[0].decided_by!r}. "
        "UNSET means the writer never attributed the row, so the 'nobody said' "
        "query would return every new record and stop discriminating."
    )
    assert rows[0].decided_by != DECIDED_BY_UNSET
    # Case 1 is ICT with NO rule id — the ICT path does not consult the registry.
    assert rows[0].deciding_rule_id is None


async def test_the_live_taken_trade_path_attributes_its_row_to_ICT(bound):
    """The other write site. A taken trade is the row that actually moves money."""
    sig = SimpleNamespace(
        direction=SimpleNamespace(value="LONG"), entry=100.0, sl=99.0, tp=103.0
    )
    await LiveCryptoLoop()._record_signal_decision(
        "BTC/USD", _bars(), sig, sized_units=0.5, fill_price=100.2,
        trace=SimpleNamespace(reasons=["entry taken"]),
    )

    rows = await _rows(bound)
    assert len(rows) == 1, "the live path wrote no row at all"
    assert rows[0].decided_by == DECIDED_BY_ICT, (
        f"a TAKEN TRADE was written with decided_by={rows[0].decided_by!r} — the row "
        "that moves money cannot say who decided it"
    )
    assert rows[0].deciding_rule_id is None
