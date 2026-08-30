"""Reconciliation reports disagreements and never repairs them (task 4.6).

THE PROPERTY THAT MATTERS MOST HERE IS THE ABSENCE OF WRITES.
There is an older `reconcile_positions` in this package that SYNCS — it marks DB
trades closed when the broker stops showing them. Reasonable for keeping state
fresh, wrong for an audit: making the two sides agree destroys the evidence that
they ever disagreed.

That is the same failure this project was rebuilt to remove. The phantom equity
curve was numbers made to look right rather than understood. A reconciler that
auto-corrects is that mistake wearing an operations hat, so several tests below
assert that nothing was written.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.enums import DirectionType, OutcomeType, TradeStatus
from app.models.trade import Trade
from app.schemas.broker import Position
from app.services.broker.base import Account
from app.services.broker.reconciliation import (
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
    reconcile_broker,
)

pytestmark = pytest.mark.asyncio

USER = "system"


class FakeBroker:
    """A broker whose live state the test dictates."""

    broker_name = "cryptofundtrader"
    is_simulation = False
    observe_only = True

    def __init__(self, balance=5090.95, positions=None, orders=None, fail=False):
        self._balance = balance
        self._positions = positions or []
        self._orders = orders or []
        self._fail = fail

    async def get_account(self) -> Account:
        if self._fail:
            raise ConnectionError("bridge is down")
        return Account(
            account_id="ACC", broker=self.broker_name, balance=self._balance,
            equity=self._balance, currency="USD",
        )

    async def get_positions(self):
        return self._positions

    async def get_orders(self, status=None):
        return self._orders


def position(pair="BTC/USD", pid="pos-1", direction=DirectionType.LONG, lots="0.05") -> Position:
    return Position(
        id=pid, pair=pair, direction=direction, lot_size=Decimal(lots),
        entry_price=Decimal("62000"), current_price=Decimal("62100"),
        unrealized_pnl=Decimal("5"),
        # `B286`. A hand-built Position is a Position PRODUCER, and the provenance is now the
        # producer's obligation — the same lesson `T-0059`'s flag taught. `"computed"`
        # because this fixture derives the number itself; recording a KEY NAME here would
        # claim a payload that does not exist.
        pnl_source="computed",
        # `T-0105`. A hand-built Position is a PRODUCER, and `produced_by` is required — a
        # fixture that could omit it would be the one place the field is optional, which is
        # what it exists to prevent. Named for what this fixture actually stands in for.
        produced_by="paper",
        swap=None, commission=None,
        duration_seconds=3600,
        open_time=datetime.now(timezone.utc),
    )


def our_trade(pair="BTC/USD", broker_id="pos-1", status=TradeStatus.OPEN, pnl=0.0) -> Trade:
    now = datetime.now(timezone.utc)
    return Trade(
        user_id=USER, broker_id=broker_id, broker="cryptofundtrader", pair=pair,
        direction=DirectionType.LONG,
        entry_price=Decimal("62000"), lot_size=Decimal("0.05"),
        entry_time=now - timedelta(hours=1),
        exit_time=now if status == TradeStatus.CLOSED else None,
        outcome=OutcomeType.WIN if pnl > 0 else OutcomeType.LOSS,
        status=status, pnl_dollars=Decimal(str(pnl)),
    )


def kinds(report) -> set[str]:
    return {f.kind for f in report.findings}


# ---------------------------------------------------------------------------
# It must never write. This is the point of the module.
# ---------------------------------------------------------------------------
async def test_reconciliation_writes_nothing(db_session):
    """A position at the broker that we do not have recorded is exactly the case
    the OLD reconciler would have 'fixed'. This one must only report it."""
    before = list((await db_session.execute(select(Trade))).scalars().all())

    broker = FakeBroker(positions=[position()])
    report = await reconcile_broker(broker, db_session, USER)

    after = list((await db_session.execute(select(Trade))).scalars().all())
    assert len(after) == len(before), "reconciliation created or removed a trade row"
    assert report.findings, "it reported nothing about an untracked position"


async def test_a_missing_position_is_reported_not_closed(db_session):
    """We think a trade is OPEN; the broker does not show it. The old
    reconciler marked such trades CLOSED. Silently closing it would erase the
    only evidence that our record and reality had diverged."""
    trade = our_trade()
    db_session.add(trade)
    await db_session.commit()

    report = await reconcile_broker(FakeBroker(positions=[]), db_session, USER)

    await db_session.refresh(trade)
    assert trade.status == TradeStatus.OPEN, "the trade was silently closed"
    assert "missing_position" in kinds(report)


# ---------------------------------------------------------------------------
# What it detects
# ---------------------------------------------------------------------------
async def test_untracked_position_is_critical(db_session):
    """An open position nobody here created is live exposure that nothing is
    managing — no stop watched, no decision record explaining it."""
    report = await reconcile_broker(FakeBroker(positions=[position()]), db_session, USER)

    found = next(f for f in report.findings if f.kind == "untracked_position")
    assert found.severity == SEVERITY_CRITICAL
    assert "BTC/USD" in found.summary


async def test_a_matched_position_produces_no_finding(db_session):
    """Guard against an alarm that always fires: agreement must be silent."""
    db_session.add(our_trade(broker_id="pos-1"))
    await db_session.commit()

    report = await reconcile_broker(FakeBroker(positions=[position(pid="pos-1")]), db_session, USER)

    assert "untracked_position" not in kinds(report)
    assert "missing_position" not in kinds(report)


async def test_resting_orders_are_flagged_while_observe_only(db_session):
    report = await reconcile_broker(
        FakeBroker(orders=[{"id": "o-1"}, {"id": "o-2"}]), db_session, USER
    )
    found = next(f for f in report.findings if f.kind == "untracked_orders")
    assert found.detail["count"] == 2
    assert found.severity == SEVERITY_WARNING


# ---------------------------------------------------------------------------
# Balance drift
# ---------------------------------------------------------------------------
async def _snapshot(db_session, balance: float):
    """Insert one PropFirmSnapshot to compare against, via the same table
    observe_sync already populates every two minutes."""
    from app.models.prop_firm_profile import PropFirmProfile
    from app.models.prop_firm_snapshot import PropFirmSnapshot
    from app.db.enums import ComplianceState

    profile = PropFirmProfile(
        user_id=USER, firm_name="test-firm",
        rules_json={"initial_balance": 5000, "daily_drawdown_pct": 5,
                    "max_drawdown_pct": 10, "profit_target_pct": 10},
    )
    db_session.add(profile)
    await db_session.flush()
    db_session.add(PropFirmSnapshot(
        profile_id=profile.id, equity=Decimal(str(balance)), balance=Decimal(str(balance)),
        daily_loss=Decimal("0"), total_loss=Decimal("0"),
        state=ComplianceState.ACTIVE, timestamp=datetime.now(timezone.utc) - timedelta(minutes=5),
    ))
    await db_session.commit()


async def test_unexplained_balance_change_is_flagged(db_session):
    """The balance moved and none of our trades accounts for it."""
    await _snapshot(db_session, 5000.00)

    report = await reconcile_broker(FakeBroker(balance=5090.95), db_session, USER)

    found = next(f for f in report.findings if f.kind == "unexplained_balance_change")
    assert found.detail["delta"] == pytest.approx(90.95)
    assert found.detail["explained_by_our_trades"] == 0.0


async def test_a_balance_change_our_own_trade_explains_is_not_flagged(db_session):
    """Otherwise every real trade would raise an alarm, and the report becomes
    noise people learn to skip."""
    await _snapshot(db_session, 5000.00)
    db_session.add(our_trade(status=TradeStatus.CLOSED, pnl=90.95, broker_id="closed-1"))
    await db_session.commit()

    report = await reconcile_broker(FakeBroker(balance=5090.95), db_session, USER)

    assert "unexplained_balance_change" not in kinds(report)


async def test_dust_sized_moves_are_ignored(db_session):
    """Financing and rounding produce constant sub-cent noise; flagging it
    trains people to ignore the report."""
    await _snapshot(db_session, 5090.95)
    report = await reconcile_broker(FakeBroker(balance=5090.955), db_session, USER)
    assert "unexplained_balance_change" not in kinds(report)


# ---------------------------------------------------------------------------
# Failure behaviour
# ---------------------------------------------------------------------------
async def test_an_unreachable_broker_reports_rather_than_raising(db_session):
    """A check that dies when things are wrong is useless exactly when needed."""
    report = await reconcile_broker(FakeBroker(fail=True), db_session, USER)

    assert report.reachable is False
    assert report.ok is False, "unreachable must not read as a clean bill of health"
    assert "bridge is down" in report.error


async def test_checks_run_distinguishes_clean_from_not_checked(db_session):
    """'No findings' means nothing unless you know which checks executed."""
    report = await reconcile_broker(FakeBroker(), db_session, USER)
    assert "positions" in report.checks_run
    assert report.ok is True


async def test_report_serialises_for_the_api(db_session):
    report = await reconcile_broker(FakeBroker(positions=[position()]), db_session, USER)
    d = report.as_dict()
    assert d["broker"] == "cryptofundtrader"
    assert d["ok"] is False
    assert d["worst_severity"] == SEVERITY_CRITICAL
    assert d["finding_count"] == len(d["findings"]) == 1


# ---------------------------------------------------------------------------
# The endpoint
# ---------------------------------------------------------------------------
async def test_endpoint_returns_a_list_and_never_500s(client):
    """With no brokers connected this must be an empty list, not an error."""
    resp = await client.get("/api/brokers/reconciliation")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_simulation_brokers_are_skipped(db_session):
    """The engine's own PaperBroker is not a third party whose records could
    disagree with ours — it IS our records. Reconciling it against itself would
    produce noise, not signal."""
    from app.services.broker import broker_manager

    class SimBroker(FakeBroker):
        is_simulation = True
        broker_name = "paper"

    original = dict(broker_manager._adapters)  # noqa: SLF001
    broker_manager._adapters.clear()           # noqa: SLF001
    broker_manager._adapters["paper"] = SimBroker(positions=[position()])  # noqa: SLF001
    try:
        results = await broker_manager.reconcile_all(db_session, USER)
        assert results == [], "a simulation broker was reconciled"
    finally:
        broker_manager._adapters.clear()       # noqa: SLF001
        broker_manager._adapters.update(original)  # noqa: SLF001
