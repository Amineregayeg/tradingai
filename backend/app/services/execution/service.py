"""ExecutionService: approved strategy signal -> sized, risk-managed broker order.

This is the piece the engine was missing (place_order had zero callers). It:
  * sizes the position from account equity + risk-% + stop distance,
  * attaches SL/TP,
  * routes through a single MODE GATE (OBSERVE = compute only, PAPER = simulate).

Safety: there is NO real-money mode here. The former ExecMode.LIVE branch was
removed — this service only ever runs against a simulation broker. Real brokers
are reached (if at all) through the broker manager, which is separately guarded
by the is_simulation contract. Mode defaults to PAPER.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum

from app.core.logging import logger
from app.db.enums import DirectionType, OrderType
from app.services.broker.base import BrokerAdapter, OrderRequest


class ExecMode(str, Enum):
    OBSERVE = "observe"   # compute only, never place (current legacy default)
    PAPER = "paper"       # place against a SIMULATION broker (PaperBroker / SimPropFirmBroker)
    # NOTE: there is deliberately NO LIVE member. This service cannot place a
    # real-money order. Any adapter it receives must be is_simulation=True
    # (asserted in execute()).


@dataclass
class Signal:
    symbol: str
    direction: DirectionType
    entry: float
    sl: float
    tp: float | None = None
    risk_pct: float = 0.01
    order_type: OrderType = OrderType.MARKET
    approved: bool = False        # must be True for LIVE
    client_order_id: str | None = None


def size_position(equity: float, risk_pct: float, entry: float, sl: float) -> float:
    """Units = (equity * risk%) / per-unit stop distance. Leverage-independent."""
    risk_per_unit = abs(entry - sl)
    if risk_per_unit <= 0:
        return 0.0
    return (equity * risk_pct) / risk_per_unit


class ExecutionService:
    def __init__(self, broker: BrokerAdapter, mode: ExecMode = ExecMode.PAPER) -> None:
        self.broker = broker
        self.mode = mode

    async def execute(self, sig: Signal) -> dict:
        # HARD SAFETY: this service only ever runs against a simulation broker.
        # A non-simulation adapter here is a programming error, not a runtime
        # condition — fail loud rather than risk a real order.
        if not getattr(self.broker, "is_simulation", False):
            raise RuntimeError(
                "ExecutionService requires a simulation broker "
                f"(is_simulation=True); got {type(self.broker).__name__}"
            )

        acct = await self.broker.get_account()
        units = size_position(acct.equity, sig.risk_pct, sig.entry, sig.sl)
        if units <= 0:
            return {"status": "rejected", "reason": "non-positive size / stop"}

        if self.mode == ExecMode.OBSERVE:
            return {"status": "observed", "would_size": round(units, 6),
                    "symbol": sig.symbol, "direction": sig.direction.value}

        req = OrderRequest(
            pair=sig.symbol, direction=sig.direction, order_type=sig.order_type,
            lot_size=round(units, 8),
            price=None if sig.order_type == OrderType.MARKET else sig.entry,
            sl=sig.sl, tp=sig.tp,
            client_order_id=sig.client_order_id or f"sig-{uuid.uuid4().hex[:8]}",
        )
        res = await self.broker.place_order(req)
        res.setdefault("status", "FILLED")
        res["mode"] = self.mode.value
        res["sized_units"] = round(units, 8)
        res["equity_at_entry"] = acct.equity
        logger.info(f"ExecutionService[{self.mode.value}] {sig.symbol} {sig.direction.value} "
                    f"units={units:.6f} -> {res.get('status')}")
        return res
