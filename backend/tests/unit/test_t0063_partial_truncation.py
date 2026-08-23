"""T-0063 — `B223`: the 70% partial popped the decision key, so every winner's record
described 70% of itself.

```
paper.py:139        the broker DOES emit  "partial": remaining > 0
crypto_loop.py      _on_settle_cb fired on EVERY close with NO branch on ev["partial"]
                    _resolve_decision POPPED _open_decision[pair] and wrote realized_r
                    from the 70% TRANCHE
the 30% runner      closed later, found dec_id None, returned
```

**THE BIAS IS NOT SYMMETRIC.** Under `EXIT-001` the partial fires only on a WINNER reaching 2R;
a loser closes whole at its stop. So losses were recorded complete and wins truncated, in the
field `crypto_loop.py` calls *"the feedback loop's core input"*. `ETH 2026-08-19 13:17:01`
recorded `realized_r = 1.5276` for a `+76.38` tranche while its runner made `+152.30` — twice
as much — for a true `+228.68`.

**AND THE OBVIOUS REPAIR IS A TRAP.** Branching on `partial` and holding the 70% in an
in-memory accumulator is `B224` at smaller scale: if the runner never closes — the state both
symbols are in at 66 h and 94 h — the accumulator dies with the process and *the 70% is lost
too*. A truncated record traded for no record. The durable accumulator already exists in the
`trades` rows, and `ARM 1` is what tells the two fixes apart.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models.decision_record import (
    OUTCOME_OPEN, OUTCOME_WIN, DecisionRecord,
)
from app.models.trade import Trade
from app.services.live.crypto_loop import (
    LiveCryptoLoop,
    _as_decision_id,
    _with_exit_plan,
)

pytestmark = pytest.mark.asyncio

PAIR = "BTC/USD"
POSITION_ID = "cftsim-abc123"
ENTRY, STOP, UNITS = 70_000.0, 69_000.0, 0.1
#: risk = |entry - sl| * units = 1000 * 0.1 = $100, so R is dollars/100.
RISK_DOLLARS = abs(ENTRY - STOP) * UNITS


@pytest.fixture
async def bound(engine, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    import app.db.session as dbsession

    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(dbsession, "async_session_maker", maker)
    monkeypatch.setattr(dbsession, "AsyncSessionLocal", maker)
    return maker


async def _seed_decision(maker, *, pair: str = PAIR) -> str:
    opened = datetime.now(tz=timezone.utc) - timedelta(hours=2)
    rec = DecisionRecord(
        created_at=opened, symbol=pair, timeframe="5m",
        inputs_hash="i", code_path_hash="c",
        signal_dir="LONG",
        signal_entry=Decimal(str(ENTRY)), signal_sl=Decimal(str(STOP)),
        fill_price=Decimal(str(ENTRY)), sized_units=Decimal(str(UNITS)),
        outcome=OUTCOME_OPEN, cohort="paper",
    )
    async with maker() as db:
        db.add(rec)
        await db.commit()
        await db.refresh(rec)
    return str(rec.id)


def _settle(*, pnl: float, units: float, partial: bool, position_id: str = POSITION_ID) -> dict:
    now = datetime.now(tz=timezone.utc)
    return {
        "position_id": position_id, "pair": PAIR, "direction": "LONG",
        "entry": ENTRY, "exit": ENTRY + pnl / units, "units": units,
        "remaining_units": 0.03 if partial else 0.0,
        "partial": partial,
        "pnl": pnl, "reason": "partial" if partial else "stop",
        "open_time": now - timedelta(hours=2), "close_time": now,
        "balance_after": 5000.0,
    }


async def _read(maker, dec_id: str) -> DecisionRecord:
    from sqlalchemy import select

    async with maker() as db:
        return (await db.execute(
            select(DecisionRecord).where(
                DecisionRecord.id == _as_decision_id(dec_id)))).scalar_one()


# ======================================================================================
# ARM 1 — THE ONE THE FIX LIVES OR DIES ON
# ======================================================================================


async def test_arm1_the_record_resolves_IN_FULL_after_the_accumulator_is_DISCARDED(bound):
    """**Settle the 70%, throw the in-memory state away entirely, settle the 30%.**

    A new loop object with an empty `_open_decision` is exactly what a process restart
    leaves behind — and it is the state both live symbols would be in if the engine were
    restarted while their runners are open.

    **An accumulator-in-a-dict fix passes every other arm in this file and fails this one.**
    That is the whole reason it exists.
    """
    dec_id = await _seed_decision(bound)

    first = LiveCryptoLoop()
    first._open_decision[PAIR] = dec_id
    await first._persist_and_resolve(_settle(pnl=76.38, units=0.07, partial=True))

    part_closed = await _read(bound, dec_id)
    assert part_closed.realized_r is None, "a part-closed position has no honest realized R"
    assert part_closed.outcome == OUTCOME_OPEN

    # THE ACCUMULATOR IS DISCARDED. Nothing carries over but the database.
    second = LiveCryptoLoop()
    assert second._open_decision == {}, "the fixture must actually start from nothing"
    await second._persist_and_resolve(_settle(pnl=152.30, units=0.03, partial=False))

    resolved = await _read(bound, dec_id)
    assert resolved.realized_r is not None, (
        "the runner's close resolved NOTHING — the link between the decision and the "
        "position lives only in memory, so a restart loses the larger half of the P&L"
    )
    assert float(resolved.realized_r) == pytest.approx((76.38 + 152.30) / RISK_DOLLARS, abs=1e-4)
    assert resolved.outcome == OUTCOME_WIN


# ======================================================================================
# ARM 2 — the truncation is gone, measured against the known row
# ======================================================================================


async def test_arm2_a_partialled_winner_covers_BOTH_tranches(bound):
    """`ETH 2026-08-19 13:17:01`'s shape: the runner made TWICE the tranche."""
    dec_id = await _seed_decision(bound)
    loop = LiveCryptoLoop()
    loop._open_decision[PAIR] = dec_id

    await loop._persist_and_resolve(_settle(pnl=76.38, units=0.07, partial=True))
    await loop._persist_and_resolve(_settle(pnl=152.30, units=0.03, partial=False))

    resolved = await _read(bound, dec_id)
    truncated = 76.38 / RISK_DOLLARS
    full = (76.38 + 152.30) / RISK_DOLLARS

    assert float(resolved.realized_r) == pytest.approx(full, abs=1e-4)
    assert float(resolved.realized_r) != pytest.approx(truncated, abs=1e-3), (
        "the record still describes only the tranche"
    )
    assert float(resolved.realized_r) > truncated * 2, "the runner was the larger half"


# ======================================================================================
# ARM 3 — losses are UNCHANGED
# ======================================================================================


async def test_arm3_a_whole_closing_loser_still_records_exactly_minus_one(bound):
    """Both losers in the live run record `-1.0000` exactly. **A fix that moves the losses
    has changed something it was not asked to** — and it would move the bias the other way
    rather than remove it."""
    dec_id = await _seed_decision(bound)
    loop = LiveCryptoLoop()
    loop._open_decision[PAIR] = dec_id

    await loop._persist_and_resolve(
        _settle(pnl=-RISK_DOLLARS, units=UNITS, partial=False)
    )

    resolved = await _read(bound, dec_id)
    assert float(resolved.realized_r) == pytest.approx(-1.0, abs=1e-9)
    assert resolved.outcome == "LOSS"


# ======================================================================================
# ARM 4 — realized_r is NULL while part-closed, and that is AFFORDABLE
# ======================================================================================


async def test_arm4_a_part_closed_position_is_NULL_and_a_filtering_consumer_sees_one_fewer(
    bound,
):
    """Nothing honest exists for a 70%-closed, 30%-open position: the closed leg has a
    realized R, the open leg has an unrealised one that moves every tick, and **no weighting
    of them is a fact about the trade.**

    *The current behaviour is STRICTLY WORSE than NULL* — a truncated figure is INCLUDED and
    drags `mean_winner_realized_r` down, so the system produces a confidently wrong number
    where NULL produces no number. A smaller true evidence base beats a larger false one.
    """
    dec_id = await _seed_decision(bound)
    loop = LiveCryptoLoop()
    loop._open_decision[PAIR] = dec_id

    await loop._persist_and_resolve(_settle(pnl=76.38, units=0.07, partial=True))

    rec = await _read(bound, dec_id)
    assert rec.realized_r is None and rec.gap_r is None
    assert rec.outcome == OUTCOME_OPEN, "part-closed is still OPEN, not resolved"

    # The consumer shape: `feedback.py:282-284` and `:438` filter `is not None`.
    assert [r for r in [rec] if r.realized_r is not None] == [], (
        "a filtering consumer must see one fewer row, never a wrong one"
    )


# ======================================================================================
# ARM 5 — expected_r records the PLAN, and a scalar must turn this RED
# ======================================================================================


async def test_arm5_the_exit_plan_names_BOTH_legs_and_the_runner_is_UNDEFINED():
    line = _with_exit_plan(["PASS history"])[-1]

    assert "0.70 @ 2.0R" in line, "the ratified leg, PARTIAL_AT_R"
    assert "0.30 @ UNDEFINED" in line, (
        "the runner's leg must be UNDEFINED, not a number — EXIT-003 is OPEN and any scalar "
        "here invents the value the registry deliberately leaves open"
    )
    assert "EXIT-003" in line, "and it must name WHY it is undefined"

    import re

    runner = line.split("+", 1)[1]
    assert not re.search(r"0\.30 @ [0-9]", runner), (
        "a numeric target appeared on the runner's leg — that is EXIT-003 invented"
    )


async def test_arm5b_expected_r_stays_NULL_because_the_position_level_plan_has_an_open_leg(
    bound,
):
    """The column can hold one number and the plan has an undefined leg, so it holds none.

    **`gap_r` therefore stays NULL too, and that is NOT fixed here** — stated rather than
    left to be discovered. Giving the feedback loop a comparison means a PER-LEG gap, the
    70% leg against 2.0R, which is a change to `feedback.py`'s consumers.
    """
    dec_id = await _seed_decision(bound)
    loop = LiveCryptoLoop()
    loop._open_decision[PAIR] = dec_id

    await loop._persist_and_resolve(_settle(pnl=228.68, units=UNITS, partial=False))

    rec = await _read(bound, dec_id)
    assert rec.expected_r is None
    assert rec.gap_r is None, "no expected_r means no gap_r; the loop still cannot learn"
    assert rec.realized_r is not None, "but the REALIZED side is now correct"


# ======================================================================================
# ARM 6 — B227 INHERITED MIRRORED. Finality comes from the KEY, never the arithmetic.
# ======================================================================================


async def test_arm6_finality_uses_the_brokers_own_partial_flag_not_a_SUM_comparison(bound):
    """**`B227` mirrored.** T-0057's `SUM(closed) < sized_units` misreads a settled
    two-tranche trade as still open ~12.9% of the time; here the same arithmetic would leave
    a FINISHED trade unresolved forever.

    The tranche lots below sum to `0.099999`, NOT the `0.1` the decision was sized to — the
    rounding chain `service.py` 8dp -> `decision_records` 6dp -> each settle lot 8dp then 6dp
    makes that ordinary. A SUM-based finality test would refuse to resolve this trade. The
    broker's `partial` flag is computed once at 10dp and handed over, so it cannot disagree.

    *Not repaired with an epsilon: a tolerance must exceed 1e-6 and would then be blind to a
    genuine smaller remainder, and choosing its size is a tuned threshold.*
    """
    dec_id = await _seed_decision(bound)
    loop = LiveCryptoLoop()
    loop._open_decision[PAIR] = dec_id

    await loop._persist_and_resolve(_settle(pnl=76.38, units=0.069999, partial=True))
    await loop._persist_and_resolve(_settle(pnl=152.30, units=0.030000, partial=False))

    assert 0.069999 + 0.030000 < UNITS, "the fixture must actually undershoot sized_units"
    resolved = await _read(bound, dec_id)
    assert resolved.realized_r is not None, (
        "a finished trade went unresolved — finality is being decided by arithmetic that "
        "cannot equal the sized figure"
    )


# ======================================================================================
# B225 — the key that makes the durable sum possible
# ======================================================================================


async def test_the_tranche_rows_share_the_POSITION_ID_not_the_literal_paper(bound):
    """`reconciler.py:75` keys `{broker_id: Trade}` against `pos.id`, so the column already
    MEANS the broker's position id. Writing `"paper"` gave one distinct value across all 274
    rows while `ev["position_id"]` sat unused in the same dict."""
    from sqlalchemy import select

    dec_id = await _seed_decision(bound)
    loop = LiveCryptoLoop()
    loop._open_decision[PAIR] = dec_id

    await loop._persist_and_resolve(_settle(pnl=76.38, units=0.07, partial=True))
    await loop._persist_and_resolve(_settle(pnl=152.30, units=0.03, partial=False))

    async with bound() as db:
        rows = (await db.execute(select(Trade))).scalars().all()

    assert len(rows) == 2
    assert {r.broker_id for r in rows} == {POSITION_ID}, (
        f"the tranches must share the position key: {[r.broker_id for r in rows]}"
    )
    assert sum(float(r.pnl_dollars) for r in rows) == pytest.approx(228.68, abs=1e-2)


async def test_a_settle_event_with_NO_position_id_degrades_to_the_OLD_behaviour(bound):
    """Every row written before this change has `broker_id = "paper"`. The fallback is the
    event's own P&L — what the system already did — so a failure here degrades to a
    too-small figure rather than to `0.0`. *A bookkeeping path that can report zero profit is
    worse than one that reports too little.*"""
    dec_id = await _seed_decision(bound)
    loop = LiveCryptoLoop()
    loop._open_decision[PAIR] = dec_id

    ev = _settle(pnl=110.0, units=UNITS, partial=False)
    ev.pop("position_id")
    await loop._persist_and_resolve(ev)

    rec = await _read(bound, dec_id)
    assert float(rec.realized_r) == pytest.approx(110.0 / RISK_DOLLARS, abs=1e-4)
