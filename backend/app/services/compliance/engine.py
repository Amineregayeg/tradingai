"""Compliance engine — prop firm rule evaluation and state machine."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.db.enums import ComplianceState
from app.models.prop_firm_profile import PropFirmProfile
from app.models.prop_firm_snapshot import PropFirmSnapshot


class ComplianceEngine:
    """
    Evaluate prop firm rules against current account state.
    Called periodically and on each position change.

    State machine thresholds (based on daily_loss vs daily_limit):
    - daily_loss < 80% of daily_limit  → ACTIVE
    - daily_loss >= 80%                → AT_RISK
    - daily_loss >= 95%                → CRITICAL
    - daily_loss >= 100%               → HALTED (triggers kill switch)

    Also evaluates max drawdown (total_loss vs initial_balance).
    """

    async def evaluate(
        self,
        db: AsyncSession,
        user_id: str,
        profile: PropFirmProfile,
        equity: float,
        balance: float,
        daily_pnl: float,
        total_pnl: float,
        open_positions: list,
    ) -> str:
        """
        Evaluate rules from profile.rules_json and persist a snapshot.
        Returns the ComplianceState value string.
        """
        rules = profile.rules_json or {}

        daily_dd_pct = float(rules.get("daily_dd_pct", 5.0))   # e.g. 5.0 = 5%
        max_dd_pct = float(rules.get("max_dd_pct", 10.0))       # e.g. 10.0 = 10%
        initial_balance = float(rules.get("initial_balance", balance))

        # Calculate losses (positive = loss)
        daily_loss = max(0.0, -daily_pnl)
        total_loss = max(0.0, initial_balance - equity)

        daily_limit = initial_balance * (daily_dd_pct / 100.0)
        max_limit = initial_balance * (max_dd_pct / 100.0)

        state = ComplianceState.ACTIVE

        # Evaluate daily drawdown
        if daily_limit > 0:
            daily_usage_pct = daily_loss / daily_limit
            if daily_usage_pct >= 1.0:
                state = ComplianceState.HALTED
            elif daily_usage_pct >= 0.95:
                state = ComplianceState.CRITICAL
            elif daily_usage_pct >= 0.80:
                state = ComplianceState.AT_RISK

        # Evaluate max drawdown (override to HALTED if breached)
        if max_limit > 0 and total_loss >= max_limit:
            state = ComplianceState.HALTED

        # Persist snapshot
        snapshot = PropFirmSnapshot(
            user_id=user_id,
            profile_id=profile.id,
            equity=Decimal(str(round(equity, 2))),
            balance=Decimal(str(round(balance, 2))),
            daily_loss=Decimal(str(round(daily_loss, 2))),
            total_loss=Decimal(str(round(total_loss, 2))),
            state=state,
            timestamp=datetime.now(timezone.utc),
        )
        db.add(snapshot)
        await db.flush()

        logger.info(
            "Compliance evaluated",
            profile_id=str(profile.id),
            state=state.value,
            daily_loss=daily_loss,
            daily_limit=daily_limit,
            total_loss=total_loss,
            max_limit=max_limit,
        )

        # Trigger kill switch if HALTED
        if state == ComplianceState.HALTED:
            logger.warning(
                "Compliance HALTED — triggering kill switch",
                profile_id=str(profile.id),
                daily_loss=daily_loss,
                total_loss=total_loss,
            )
            from app.services.compliance.kill_switch import kill_switch

            kill_switch.arm(
                reason=f"Compliance rule breached for profile {profile.firm_name}: "
                f"daily_loss={daily_loss:.2f} limit={daily_limit:.2f} "
                f"total_loss={total_loss:.2f} max_limit={max_limit:.2f}"
            )
            await kill_switch.trigger(
                db=db,
                user_id=user_id,
                reason=kill_switch._reason,
            )

        return state.value


compliance_engine = ComplianceEngine()
