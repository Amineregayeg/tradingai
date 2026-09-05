"""Observe-only sync: turn a connected broker account into prop-firm compliance
monitoring, without ever placing or closing orders.

This is the *monitoring* half of the compliance feature. Unlike
``ComplianceEngine.evaluate`` (which arms and fires the kill switch on a breach),
this path is strictly read-only — it writes a ``PropFirmSnapshot`` so the Prop-Firm
dashboard and drawdown bars reflect the live account, and logs a warning on breach,
but never auto-closes positions. It is the correct path for brokers that forbid
automated execution (e.g. prop firms) or that we connect to in observe-only mode.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.db.enums import ComplianceState
from app.models.prop_firm_profile import PropFirmProfile
from app.models.prop_firm_snapshot import PropFirmSnapshot
from app.services.broker.base import BrokerAdapter


def compute_compliance_state(
    rules: dict,
    initial_balance: float,
    daily_loss: float,
    total_loss: float,
) -> ComplianceState:
    """Pure drawdown state machine (no side effects).

    Mirrors ComplianceEngine thresholds: ACTIVE < 80% of daily limit, AT_RISK >= 80%,
    CRITICAL >= 95%, HALTED >= 100% or max-drawdown breached.
    """
    daily_dd_pct = float(rules.get("daily_dd_pct", 5.0))
    max_dd_pct = float(rules.get("max_dd_pct", 10.0))

    daily_limit = initial_balance * (daily_dd_pct / 100.0)
    max_limit = initial_balance * (max_dd_pct / 100.0)

    state = ComplianceState.ACTIVE
    if daily_limit > 0:
        usage = daily_loss / daily_limit
        if usage >= 1.0:
            state = ComplianceState.HALTED
        elif usage >= 0.95:
            state = ComplianceState.CRITICAL
        elif usage >= 0.80:
            state = ComplianceState.AT_RISK
    if max_limit > 0 and total_loss >= max_limit:
        state = ComplianceState.HALTED
    return state


async def sync_account_compliance(
    adapter: BrokerAdapter,
    db: AsyncSession,
    user_id: str,
    profile: PropFirmProfile,
) -> ComplianceState:
    """Fetch the account and persist one compliance snapshot. Monitoring only.

    Returns the evaluated state. Does NOT trigger the kill switch — a breach is
    surfaced in the UI (state + drawdown) and logged, but positions are never
    auto-closed for an observe-only / prop-firm account.
    """
    account = await adapter.get_account()
    rules = profile.rules_json or {}
    initial_balance = float(rules.get("initial_balance", account.balance))

    total_loss = max(0.0, initial_balance - account.equity)
    # No intraday baseline is tracked here, so daily loss is approximated from the
    # current unrealized P/L (a real daily baseline would come from a day-open snapshot).
    daily_loss = max(0.0, -account.unrealized_pl)

    state = compute_compliance_state(rules, initial_balance, daily_loss, total_loss)

    snapshot = PropFirmSnapshot(
        user_id=user_id,
        profile_id=profile.id,
        equity=Decimal(str(round(account.equity, 2))),
        balance=Decimal(str(round(account.balance, 2))),
        daily_loss=Decimal(str(round(daily_loss, 2))),
        total_loss=Decimal(str(round(total_loss, 2))),
        state=state,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(snapshot)
    await db.flush()

    if state in (ComplianceState.CRITICAL, ComplianceState.HALTED):
        logger.warning(
            "Observe-only compliance breach (monitoring only — no auto-close)",
            profile_id=str(profile.id),
            firm=profile.firm_name,
            state=state.value,
            total_loss=total_loss,
        )
    return state


async def sync_all_observe_only(
    db: AsyncSession,
    user_id: str,
) -> dict:
    """Sync every connected adapter that maps to a prop-firm profile (by account_id).

    Returns `{"synced": int, "unavailable": [...]}`. Safe to call periodically; never trades.

    **`B378`. AN ADAPTER THAT CANNOT BE REACHED IS NO LONGER *SKIPPED*** — it gets an
    `UNAVAILABLE` snapshot with no figures, so the compliance surface can say *could not evaluate*
    instead of showing the last good value indefinitely. The surface reads snapshot HISTORY, and a
    missing row is indistinguishable from a quiet period.
    """
    from app.services.broker.manager import broker_manager

    stmt = select(PropFirmProfile).where(
        PropFirmProfile.user_id == user_id,
        PropFirmProfile.active.is_(True),
    )
    result = await db.execute(stmt)
    profiles = {p.account_id: p for p in result.scalars().all() if p.account_id}

    synced = 0
    #: `B378`. Accounts whose compliance could NOT be evaluated this pass, with a reason. A caller
    #: reading only `synced` cannot tell *nothing to do* from *nothing worked*.
    unavailable: list[dict] = []
    for adapter in broker_manager._adapters.values():
        account_id = getattr(adapter, "_account_id", "") or ""
        profile = profiles.get(account_id)
        if profile is None:
            continue
        try:
            await sync_account_compliance(adapter, db, user_id, profile)
            synced += 1
        except Exception as exc:  # transport/auth/etc — monitoring is best-effort
            # `B378`. **SKIPPING WRITES NOTHING, AND THE SURFACE READS SNAPSHOT HISTORY** — so a
            # missing snapshot is indistinguishable from a quiet period, and the monitor shows the
            # last good value indefinitely. Every two minutes, on the drawdown monitor for a
            # funded account, where a breach closes the account.
            #
            # THIS DEFECT IS CREATED BY `B377` AND MUST LAND WITH IT. Before B377 an absent
            # `equity` silently became `balance` and the monitor showed a WRONG drawdown; after
            # B377 `get_account` raises and the monitor STOPS UPDATING. A wrong number at least
            # moves; a frozen one looks like calm. So the failure is RECORDED as its own state
            # rather than skipped: the monitor can now say *could not evaluate*.
            # **RECORDED, NOT MERELY RETURNED.** An earlier version of this fix built this list,
            # logged it and returned it — and review's line is the one that matters: *an arm
            # asserting the function returns `unavailable` would PASS while the monitor still
            # lies.* The surface reads snapshot HISTORY, so the information has to reach a ROW.
            # That is `B366`'s exact shape, and it was sitting inside the fix for a defect
            # described to me as `B366`'s shape.
            db.add(PropFirmSnapshot(
                user_id=user_id,
                profile_id=profile.id,
                equity=None, balance=None, daily_loss=None, total_loss=None,
                state=ComplianceState.UNAVAILABLE,
            ))
            unavailable.append({
                "account_id": account_id,
                "broker": getattr(adapter, "broker_name", "unknown"),
                "reason": f"{type(exc).__name__}: {exc}",
            })
            logger.warning(
                "Observe-only sync skipped",
                broker=adapter.broker_name,
                account_id=account_id,
                error=str(exc),
            )
    if synced or unavailable:
        # COMMIT ON FAILURE TOO. The UNAVAILABLE rows ARE the deliverable of a failed pass, and a
        # commit guarded by `synced` alone would discard exactly the evidence this fix exists to
        # create.
        await db.commit()
    if unavailable:
        # LOUD, AND SEPARATELY FROM THE PER-ADAPTER WARNING ABOVE. That one says an adapter was
        # skipped; this says the DRAWDOWN MONITOR did not evaluate, which is the fact an operator
        # needs and the one a snapshot history cannot express by omission.
        logger.error(
            "Prop-firm compliance NOT EVALUATED this pass — the monitor is showing stale state, "
            "not a quiet period",
            unavailable=unavailable,
            evaluated=synced,
        )
    return {"synced": synced, "unavailable": unavailable}
