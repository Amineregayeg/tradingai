"""Paper-trading broker — simulated fills against a real price feed.

Implements the same ``BrokerAdapter`` interface as the live adapters, so the
execution path is identical for paper and live: flip the adapter, nothing else
changes. Fills are simulated at the mark price; SL/TP are evaluated on every
``on_tick`` so positions close deterministically. This is the safe substrate for
the "make money in simulation first" phase.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable

from app.core.logging import logger
from app.db.enums import DirectionType, OrderType
from app.schemas.broker import Position
from app.services.broker.base import Account, BrokerAdapter, OrderRequest


class PaperPosition:
    __slots__ = ("id", "pair", "direction", "entry", "units", "sl", "tp", "open_time", "mark")

    def __init__(self, pair, direction, entry, units, sl, tp, open_time):
        self.id = f"paper-{uuid.uuid4().hex[:10]}"
        self.pair = pair
        self.direction = direction
        self.entry = float(entry)
        self.units = float(units)
        self.sl = float(sl) if sl is not None else None
        self.tp = float(tp) if tp is not None else None
        self.open_time = open_time
        self.mark = float(entry)

    def upnl(self, price: float) -> float:
        sign = 1.0 if self.direction == DirectionType.LONG else -1.0
        return sign * (price - self.entry) * self.units


class PaperBroker(BrokerAdapter):
    """In-memory simulated exchange with realized/unrealized PnL tracking."""

    broker_name = "paper"

    def __init__(
        self,
        starting_balance: float = 50_000.0,
        currency: str = "USDT",
        price_fn: Callable[[str], float] | None = None,
    ) -> None:
        self.balance = float(starting_balance)        # realized equity
        self.currency = currency
        self._price_fn = price_fn
        self._marks: dict[str, float] = {}
        self._positions: dict[str, PaperPosition] = {}
        self._closed: list[dict] = []
        self._fill_log: list[dict] = []

    # ---- connection lifecycle ----
    async def connect(self) -> None:
        logger.info(f"PaperBroker connected (balance={self.balance} {self.currency})")

    async def disconnect(self) -> None:
        pass

    # ---- price handling ----
    def _price(self, pair: str) -> float:
        if pair in self._marks:
            return self._marks[pair]
        if self._price_fn is not None:
            px = float(self._price_fn(pair))
            self._marks[pair] = px
            return px
        raise RuntimeError(f"No mark price for {pair} (set via on_tick or price_fn)")

    def on_tick(self, pair: str, price: float, ts: datetime | None = None) -> list[dict]:
        """Advance the simulation one tick; auto-close any SL/TP hits.

        Returns a list of close events that fired on this tick.
        """
        price = float(price)
        self._marks[pair] = price
        events: list[dict] = []
        for pos in list(self._positions.values()):
            if pos.pair != pair:
                continue
            pos.mark = price
            hit = None
            if pos.direction == DirectionType.LONG:
                if pos.sl is not None and price <= pos.sl:
                    hit = ("SL", pos.sl)
                elif pos.tp is not None and price >= pos.tp:
                    hit = ("TP", pos.tp)
            else:
                if pos.sl is not None and price >= pos.sl:
                    hit = ("SL", pos.sl)
                elif pos.tp is not None and price <= pos.tp:
                    hit = ("TP", pos.tp)
            if hit:
                events.append(self._settle(pos, hit[1], reason=hit[0], ts=ts))
        return events

    def _settle(self, pos: PaperPosition, exit_price: float, reason: str, ts=None) -> dict:
        pnl = pos.upnl(exit_price)
        self.balance += pnl
        self._positions.pop(pos.id, None)
        ev = {
            "position_id": pos.id, "pair": pos.pair, "direction": pos.direction.value,
            "entry": pos.entry, "exit": float(exit_price), "units": pos.units,
            "pnl": round(pnl, 4), "reason": reason,
            "open_time": pos.open_time, "close_time": ts or datetime.now(timezone.utc),
            "balance_after": round(self.balance, 2),
        }
        self._closed.append(ev)
        logger.info(f"PaperBroker close {pos.pair} {reason} pnl={pnl:.2f} bal={self.balance:.2f}")
        return ev

    # ---- account / positions ----
    async def get_account(self) -> Account:
        upl = sum(p.upnl(self._marks.get(p.pair, p.entry)) for p in self._positions.values())
        return Account(
            account_id="paper", broker=self.broker_name,
            balance=round(self.balance, 2), equity=round(self.balance + upl, 2),
            currency=self.currency, open_trade_count=len(self._positions),
            unrealized_pl=round(upl, 2),
        )

    async def get_positions(self) -> list[Position]:
        out = []
        for p in self._positions.values():
            mark = self._marks.get(p.pair, p.entry)
            risk = abs(p.entry - p.sl) if p.sl else None
            rmult = None
            if risk:
                sign = 1 if p.direction == DirectionType.LONG else -1
                rmult = Decimal(str(round(sign * (mark - p.entry) / risk, 3)))
            out.append(Position(
                id=p.id, pair=p.pair, direction=p.direction,
                entry_price=Decimal(str(p.entry)), current_price=Decimal(str(mark)),
                unrealized_pnl=Decimal(str(round(p.upnl(mark), 4))), r_multiple=rmult,
                lot_size=Decimal(str(p.units)),
                sl=Decimal(str(p.sl)) if p.sl else None,
                tp=Decimal(str(p.tp)) if p.tp else None,
                duration_seconds=0, open_time=p.open_time,
            ))
        return out

    async def get_orders(self, status: str | None = None) -> list[dict]:
        return []

    async def get_recent_trades(self, since: datetime | None = None) -> list[dict]:
        if since is None:
            return list(self._closed)
        return [c for c in self._closed if c["close_time"] >= since]

    # ---- order management ----
    async def place_order(self, request: OrderRequest) -> dict:
        if request.lot_size <= 0:
            raise ValueError("lot_size must be > 0")
        fill = request.price if (request.order_type != OrderType.MARKET and request.price) else self._price(request.pair)
        pos = PaperPosition(
            pair=request.pair, direction=request.direction, entry=fill,
            units=request.lot_size, sl=request.sl, tp=request.tp,
            open_time=datetime.now(timezone.utc),
        )
        self._positions[pos.id] = pos
        rec = {
            "position_id": pos.id, "pair": pos.pair, "direction": pos.direction.value,
            "fill": float(fill), "units": pos.units, "sl": pos.sl, "tp": pos.tp,
            "client_order_id": request.client_order_id, "status": "FILLED",
        }
        self._fill_log.append(rec)
        logger.info(f"PaperBroker FILL {pos.pair} {pos.direction.value} {pos.units}@{fill} sl={pos.sl} tp={pos.tp}")
        return rec

    async def close_position(self, position_id: str, lot_size: float | None = None) -> dict:
        pos = self._positions.get(position_id)
        if not pos:
            return {"status": "not_found", "position_id": position_id}
        return self._settle(pos, self._price(pos.pair), reason="MANUAL")

    async def close_all_positions(self) -> list[dict]:
        return [self._settle(p, self._price(p.pair), reason="CLOSE_ALL")
                for p in list(self._positions.values())]

    async def stream_prices(self, pairs: list[str], callback: Callable) -> None:
        raise NotImplementedError("PaperBroker is driven via on_tick(), not streaming")
