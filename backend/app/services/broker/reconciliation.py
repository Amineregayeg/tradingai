"""Broker reconciliation — detect anything at the broker we cannot account for.

WHAT THIS IS FOR (task 4.6)
The platform keeps its own record of what it did. The broker keeps its own record
of what happened. Those two must agree, and when they disagree you want to learn
it from a flag rather than from a number that quietly stopped making sense.

WHY IT ONLY REPORTS, AND NEVER FIXES
There is already a `reconcile_positions` in this package that SYNCS: it marks DB
trades closed when the broker no longer shows them. That is reasonable for
keeping state fresh and wrong for an audit, because silently making the two sides
agree destroys the evidence that they ever disagreed.

That is the same failure this project was rebuilt to remove. The phantom equity
curve was numbers made to look right rather than understood; a reconciler that
auto-corrects is the same mistake wearing an operations hat. So this module
computes findings and writes NOTHING. Deciding what a disagreement means is a
human's job, and they cannot do it if the disagreement has been tidied away.

WHAT IT CAN DETECT TODAY
The engine executes against a PaperBroker and the CFT connection is observe-only,
so the two are independent by design — this is not "do our books match theirs".
Today, ANY change at CFT is either a human trading in the web terminal or a
malfunction, and both are worth surfacing:

  * a position exists at the broker that we never opened
  * an order is resting at the broker that we never placed
  * the balance moved while we recorded no trade of our own

WHAT IT BECOMES ONCE TRADING IS ENABLED
The same checks answer a sharper question: did every order we sent actually
arrive, and does their position match ours. Building it before it is needed is
deliberate — after real money has moved is too late to discover the check was
missing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.models.prop_firm_snapshot import PropFirmSnapshot
from app.models.trade import Trade
from app.services.broker.base import BrokerAdapter

#: Ignore balance moves smaller than this. Financing, rounding and fee dust
#: produce constant sub-cent noise; flagging it trains people to ignore the
#: report, which is worse than not having one.
BALANCE_EPSILON = 0.01

#: How far back to look for one of our own trades that could explain a balance
#: move. Generous on purpose — a false "unexplained" is much more expensive in
#: attention than a missed one is in risk, because this is a monitoring surface
#: and the next run will catch a genuine drift again.
EXPLAIN_WINDOW = timedelta(hours=24)

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"


@dataclass
class Finding:
    """One disagreement between our records and the broker's."""

    kind: str
    severity: str
    summary: str
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "summary": self.summary,
            "detail": self.detail,
        }


@dataclass
class ReconciliationReport:
    broker: str
    checked_at: str
    reachable: bool
    findings: list[Finding] = field(default_factory=list)
    error: str | None = None
    #: What we managed to compare. A report with no findings means different
    #: things depending on whether the checks actually ran, so say which did.
    checks_run: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.reachable and not self.findings

    def as_dict(self) -> dict:
        return {
            "broker": self.broker,
            "checked_at": self.checked_at,
            "reachable": self.reachable,
            "ok": self.ok,
            "error": self.error,
            "checks_run": self.checks_run,
            "finding_count": len(self.findings),
            "worst_severity": (
                max(
                    (f.severity for f in self.findings),
                    key=lambda s: [SEVERITY_INFO, SEVERITY_WARNING, SEVERITY_CRITICAL].index(s),
                    default=None,
                )
                if self.findings
                else None
            ),
            "findings": [f.as_dict() for f in self.findings],
        }


async def reconcile_broker(
    adapter: BrokerAdapter,
    db: AsyncSession,
    user_id: str = "system",
) -> ReconciliationReport:
    """Compare a broker's live state against our records. Read-only.

    Never raises: this feeds a monitoring surface, and a check that dies when
    things are wrong is useless exactly when it is needed.
    """
    now = datetime.now(tz=timezone.utc)
    report = ReconciliationReport(
        broker=adapter.broker_name,
        checked_at=now.isoformat(),
        reachable=False,
    )

    # ---- live state -----------------------------------------------------
    try:
        account = await adapter.get_account()
        positions = await adapter.get_positions()
    except Exception as exc:  # noqa: BLE001 - report, never propagate
        report.error = f"{type(exc).__name__}: {exc}"
        logger.warning(
            "Reconciliation could not read the broker",
            broker=adapter.broker_name, error=report.error,
        )
        return report

    report.reachable = True

    try:
        orders = await adapter.get_orders()
    except Exception:  # noqa: BLE001 - orders are optional; positions matter more
        orders = []

    # ---- our own records ------------------------------------------------
    try:
        our_open = list(
            (
                await db.execute(
                    select(Trade).where(
                        Trade.user_id == user_id,
                        Trade.broker == adapter.broker_name,
                        Trade.status == "OPEN",
                    )
                )
            ).scalars().all()
        )
    except Exception as exc:  # noqa: BLE001
        report.error = f"could not read our own trades: {exc}"
        return report

    our_position_ids = {t.broker_id for t in our_open if t.broker_id}
    our_pairs = {t.pair for t in our_open}

    # ---- CHECK 1: positions at the broker we did not open ---------------
    report.checks_run.append("positions")
    for pos in positions:
        if pos.id in our_position_ids or pos.pair in our_pairs:
            continue
        report.findings.append(
            Finding(
                kind="untracked_position",
                # Critical, not a warning: an open position we did not create is
                # real exposure that nothing in this system is managing — no
                # stop is being watched, and no decision record explains it.
                severity=SEVERITY_CRITICAL,
                summary=(
                    f"{pos.pair} {pos.direction.value} {pos.lot_size} is open at "
                    f"{adapter.broker_name} but this platform did not open it"
                ),
                detail={
                    "position_id": pos.id,
                    "pair": pos.pair,
                    "direction": pos.direction.value,
                    "lot_size": str(pos.lot_size),
                    "likely_cause": (
                        "opened manually in the broker's own terminal, or by "
                        "something outside this platform"
                    ),
                },
            )
        )

    # ---- CHECK 2: our open trades the broker does not show --------------
    broker_ids = {p.id for p in positions}
    broker_pairs = {p.pair for p in positions}
    for trade in our_open:
        if trade.broker_id in broker_ids or trade.pair in broker_pairs:
            continue
        report.findings.append(
            Finding(
                kind="missing_position",
                severity=SEVERITY_CRITICAL,
                summary=(
                    f"we record {trade.pair} as OPEN but {adapter.broker_name} "
                    "does not show it"
                ),
                detail={
                    "trade_id": str(trade.id),
                    "broker_id": trade.broker_id,
                    "pair": trade.pair,
                    "likely_cause": (
                        "closed at the broker without us seeing it, or never "
                        "actually opened despite us recording it"
                    ),
                },
            )
        )

    # ---- CHECK 3: resting orders we did not place -----------------------
    if orders:
        report.checks_run.append("orders")
        report.findings.append(
            Finding(
                kind="untracked_orders",
                severity=SEVERITY_WARNING,
                summary=(
                    f"{len(orders)} order(s) resting at {adapter.broker_name}; "
                    "this platform places none while observe-only"
                ),
                detail={"count": len(orders)},
            )
        )

    # ---- CHECK 4: balance moved with nothing of ours to explain it ------
    await _check_balance_drift(report, adapter, account, db, user_id, now)

    if report.findings:
        logger.warning(
            "Reconciliation found disagreements",
            broker=adapter.broker_name,
            findings=len(report.findings),
            kinds=[f.kind for f in report.findings],
        )
    return report


async def _check_balance_drift(
    report: ReconciliationReport,
    adapter: BrokerAdapter,
    account,
    db: AsyncSession,
    user_id: str,
    now: datetime,
) -> None:
    """Flag a balance change that none of our own trades accounts for.

    Uses the PropFirmSnapshot history that ``observe_sync`` already records every
    two minutes, so this needs no new table and no migration — and it means the
    comparison runs against data captured independently of this check.
    """
    try:
        previous = (
            await db.execute(
                select(PropFirmSnapshot)
                .order_by(PropFirmSnapshot.timestamp.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    except Exception as exc:  # noqa: BLE001 - a missing history is not a failure
        logger.info("No snapshot history for drift check", error=str(exc))
        return

    if previous is None:
        # First run, or observe-sync has not written yet. Say so rather than
        # reporting a clean bill of health for a check that never ran.
        return

    report.checks_run.append("balance_drift")
    delta = float(account.balance) - float(previous.balance)
    if abs(delta) < BALANCE_EPSILON:
        return

    # Did we close anything of our own that could explain it?
    since = now - EXPLAIN_WINDOW
    try:
        ours = list(
            (
                await db.execute(
                    select(Trade).where(
                        Trade.user_id == user_id,
                        Trade.broker == adapter.broker_name,
                        Trade.exit_time.is_not(None),
                        Trade.exit_time >= since,
                    )
                )
            ).scalars().all()
        )
    except Exception:  # noqa: BLE001
        ours = []

    explained = sum(float(t.pnl_dollars or 0) for t in ours)
    unexplained = delta - explained

    if abs(unexplained) < BALANCE_EPSILON:
        return

    report.findings.append(
        Finding(
            kind="unexplained_balance_change",
            severity=SEVERITY_WARNING,
            summary=(
                f"{adapter.broker_name} balance moved {delta:+.2f} since the last "
                f"snapshot; our own trades explain {explained:+.2f}, leaving "
                f"{unexplained:+.2f} unaccounted for"
            ),
            detail={
                "previous_balance": float(previous.balance),
                "current_balance": float(account.balance),
                "delta": round(delta, 2),
                "explained_by_our_trades": round(explained, 2),
                "unexplained": round(unexplained, 2),
                "our_closed_trades_considered": len(ours),
                "since": previous.timestamp.isoformat() if previous.timestamp else None,
                "likely_cause": (
                    "manual trading in the broker's terminal, financing/fees, or "
                    "a trade of ours that was never recorded"
                ),
            },
        )
    )
