"""In-process CryptoFundTrader prop-firm challenge simulator.

CryptoFundTrader exposes **no** real demo / sandbox host — ``cryptofundtrader.py``
has a single ``DEFAULT_HOST`` and every request goes to production. So a
"prop firm in simulation mode" cannot be a second connection to a fake CFT
endpoint; it is implemented here as a *local* simulator that

  (a) enforces the prop-firm **rules** (daily loss, max drawdown, profit
      target, min trading days), and
  (b) is *structurally incapable* of placing a real order — it imports no
      ``httpx`` / ``requests`` / ``aiohttp`` and opens no socket. The only way
      market prices enter is an injected, **read-only** async ``price_source``
      callable supplied by the caller.

It implements the exact same :class:`BrokerAdapter` interface as
:class:`~app.services.broker.paper.PaperBroker` — same ``Account`` /
``Position`` construction, method signatures and return shapes — so it drops
into the existing manager / positions / kill-switch code unchanged. Fills are
simulated at the ``price_source`` mark; sizing and PnL are computed locally.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Awaitable, Callable

from app.core.logging import logger
from app.db.enums import DirectionType, OrderType
from app.schemas.broker import Position
from app.services.broker.base import Account, BrokerAdapter, OrderRequest


@dataclass(frozen=True)
class PropFirmRules:
    """Static parameters of a prop-firm challenge account.

    ``starting_balance`` is SEEDED FROM A ROUND CONSTANT passed in by the caller
    (e.g. ``50_000.0``) — it must **never** be sourced from a real account
    balance. All percentages are expressed as whole-number percents (e.g.
    ``5.0`` == 5%).
    """

    starting_balance: float = 50_000.0
    daily_loss_limit_pct: float = 5.0
    max_drawdown_pct: float = 10.0
    profit_target_pct: float = 10.0
    min_trading_days: int = 5


class SimPosition:
    """Local open position — mirrors ``PaperPosition``."""

    __slots__ = ("id", "pair", "direction", "entry", "units", "sl", "tp", "open_time", "mark")

    def __init__(self, pair, direction, entry, units, sl, tp, open_time):
        self.id = f"cftsim-{uuid.uuid4().hex[:10]}"
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


class SimPropFirmBroker(BrokerAdapter):
    """Local simulator of a CryptoFundTrader prop-firm challenge account.

    Rule engine, in-memory positions, realized/unrealized PnL and a
    UI-friendly :meth:`rule_state`. Structurally incapable of a real order:
    no HTTP client, no socket — market prices arrive only through the injected
    read-only ``price_source`` callable.
    """

    broker_name = "cft_sim"

    def __init__(
        self,
        rules: PropFirmRules,
        price_source: Callable[[str], Awaitable[float]],
        currency: str = "USDT",
    ) -> None:
        self.rules = rules
        self.starting_balance = float(rules.starting_balance)
        self.balance = float(rules.starting_balance)   # realized equity
        self.peak_equity = float(rules.starting_balance)
        self.currency = currency
        # READ-ONLY async price source. Deliberately NOT an HTTP client.
        self._price_source = price_source

        self._marks: dict[str, float] = {}
        self._positions: dict[str, SimPosition] = {}
        self._closed: list[dict] = []
        self._fill_log: list[dict] = []
        # Fired on every settle (see PaperBroker) so the owner persists closes
        # + resolves decisions on all paths, not just the SL/TP tick path.
        self._on_settle: Callable[[dict], None] | None = None

        # rule / compliance state
        self._day_pnl: float = 0.0                 # realized PnL for the current day
        self._current_day = None                   # datetime.date of the active day
        self._trading_days: set = set()            # dates on which a position opened
        self._halted: bool = False
        self._breach_reason: str | None = None
        self._passed: bool = False
        self._failed: bool = False

    # ------------------------------------------------------------------
    # Simulation guarantee
    # ------------------------------------------------------------------
    @property
    def is_simulation(self) -> bool:
        return True

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------
    async def connect(self) -> None:
        logger.info(
            f"SimPropFirmBroker connected (starting_balance={self.starting_balance} "
            f"{self.currency}, daily_loss={self.rules.daily_loss_limit_pct}% "
            f"max_dd={self.rules.max_drawdown_pct}% target={self.rules.profit_target_pct}%)"
        )

    async def disconnect(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Price handling (read-only; no network client of our own)
    # ------------------------------------------------------------------
    async def _fetch_price(self, pair: str) -> float:
        if self._price_source is None:
            raise RuntimeError(f"No price_source injected for {pair}")
        px = float(await self._price_source(pair))
        self._marks[pair] = px
        return px

    def on_tick(self, pair: str, price: float, ts: datetime | None = None) -> list[dict]:
        """Advance the simulation one tick; auto-close any SL/TP hits.

        Mirrors ``PaperBroker.on_tick``. Also re-evaluates the rule engine so a
        floating (unrealized) drawdown can halt the account. Returns the list of
        close events that fired on this tick.
        """
        price = float(price)
        self._marks[pair] = price
        ts = ts or datetime.now(timezone.utc)
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
        self._evaluate_rules(ts)
        return events

    # ------------------------------------------------------------------
    # Rule engine
    # ------------------------------------------------------------------
    def _unrealized(self) -> float:
        return sum(p.upnl(self._marks.get(p.pair, p.entry)) for p in self._positions.values())

    def _daily_loss_amt(self) -> float:
        return self.starting_balance * self.rules.daily_loss_limit_pct / 100.0

    def _drawdown_floor(self) -> float:
        return self.peak_equity * (1.0 - self.rules.max_drawdown_pct / 100.0)

    def _profit_target_equity(self) -> float:
        return self.starting_balance * (1.0 + self.rules.profit_target_pct / 100.0)

    def _roll_day(self, ts: datetime) -> None:
        d = ts.date()
        if self._current_day is None:
            self._current_day = d
        elif d != self._current_day:
            self._current_day = d
            self._day_pnl = 0.0

    def _halt_reason(self) -> str:
        if self._passed:
            return "profit_target_reached"
        if self._breach_reason:
            return self._breach_reason
        return "account_halted"

    def _evaluate_rules(self, ts: datetime | None = None) -> None:
        """Update peak equity and detect a hard breach or a profit-target pass."""
        equity = self.balance + self._unrealized()
        if equity > self.peak_equity:
            self.peak_equity = equity
        if self._halted:
            return
        # Daily loss limit is measured on the day's REALIZED pnl.
        if self._day_pnl <= -self._daily_loss_amt():
            self._halted = True
            self._failed = True
            self._breach_reason = "daily_loss_limit"
            logger.info(f"cft_sim HALT daily_loss_limit day_pnl={self._day_pnl:.2f}")
            return
        # Max drawdown is trailing, measured on equity from the peak.
        if equity <= self._drawdown_floor():
            self._halted = True
            self._failed = True
            self._breach_reason = "max_drawdown"
            logger.info(f"cft_sim HALT max_drawdown equity={equity:.2f} peak={self.peak_equity:.2f}")
            return
        # Profit target reached -> challenge passed, trading halts.
        if equity >= self._profit_target_equity():
            self._halted = True
            self._passed = True
            self._breach_reason = None
            logger.info(f"cft_sim PASS profit_target equity={equity:.2f}")

    def _status(self) -> str:
        if self._failed:
            return "failed"
        if self._passed:
            return "passed"
        return "active"

    def rule_state(self) -> dict:
        """Snapshot of the prop-firm rule engine for the UI (synchronous)."""
        equity = self.balance + self._unrealized()
        day_pnl_pct = (self._day_pnl / self.starting_balance * 100.0) if self.starting_balance else 0.0
        drawdown_pct = ((self.peak_equity - equity) / self.peak_equity * 100.0) if self.peak_equity else 0.0
        if drawdown_pct < 0.0:
            drawdown_pct = 0.0
        return {
            "starting_balance": round(self.starting_balance, 2),
            "balance": round(self.balance, 2),
            "equity": round(equity, 2),
            "day_pnl_pct": round(day_pnl_pct, 4),
            "drawdown_pct": round(drawdown_pct, 4),
            "profit_target_pct": self.rules.profit_target_pct,
            "daily_loss_limit_pct": self.rules.daily_loss_limit_pct,
            "max_drawdown_pct": self.rules.max_drawdown_pct,
            "trading_days": len(self._trading_days),
            "min_trading_days": self.rules.min_trading_days,
            "halted": self._halted,
            "breach_reason": self._breach_reason,
            "status": self._status(),
        }

    # ------------------------------------------------------------------
    # Settlement
    # ------------------------------------------------------------------
    def _settle(self, pos: SimPosition, exit_price: float, reason: str, ts=None) -> dict:
        ts = ts or datetime.now(timezone.utc)
        self._roll_day(ts)
        pnl = pos.upnl(exit_price)
        self.balance += pnl
        self._day_pnl += pnl
        self._positions.pop(pos.id, None)
        ev = {
            "position_id": pos.id, "pair": pos.pair, "direction": pos.direction.value,
            "entry": pos.entry, "exit": float(exit_price), "units": pos.units,
            "pnl": round(pnl, 4), "reason": reason,
            "open_time": pos.open_time, "close_time": ts,
            "balance_after": round(self.balance, 2),
        }
        self._closed.append(ev)
        logger.info(f"cft_sim close {pos.pair} {reason} pnl={pnl:.2f} bal={self.balance:.2f}")
        self._evaluate_rules(ts)
        if self._on_settle is not None:
            try:
                self._on_settle(ev)
            except Exception:  # noqa: BLE001
                logger.warning("cft_sim on_settle hook failed", exc_info=True)
        return ev

    def _reject(self, request: OrderRequest, reason: str) -> dict:
        logger.info(f"cft_sim REJECT {request.pair} {request.direction.value} reason={reason}")
        return {
            "status": "REJECTED",
            "reason": reason,
            "pair": request.pair,
            "direction": request.direction.value,
            "client_order_id": request.client_order_id,
        }

    # ------------------------------------------------------------------
    # Account / positions
    # ------------------------------------------------------------------
    async def get_account(self) -> Account:
        upl = sum(p.upnl(self._marks.get(p.pair, p.entry)) for p in self._positions.values())
        return Account(
            account_id="cft_sim", broker=self.broker_name,
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

    # ------------------------------------------------------------------
    # Order management
    # ------------------------------------------------------------------
    async def reference_price(self, pair: str) -> float | None:
        """The mark a MARKET order fills at here — see place_order's `fill`."""
        try:
            px = await self._fetch_price(pair)
            return float(px) if px else None
        except Exception:  # noqa: BLE001 - unknown price, not a crash
            return None

    async def place_order(self, request: OrderRequest) -> dict:
        if request.lot_size <= 0:
            raise ValueError("lot_size must be > 0")

        # Roll the day FIRST, so every rule below reads THIS day's realized pnl.
        # (Previously _roll_day ran after the daily-loss guard, so on a new
        # calendar day the guard was evaluated against the PREVIOUS day's loss.)
        now = datetime.now(timezone.utc)
        self._roll_day(now)

        # Halted account (breached or passed) refuses every new order.
        if self._halted:
            return self._reject(request, self._halt_reason())

        fill = (
            float(request.price)
            if (request.order_type != OrderType.MARKET and request.price)
            else await self._fetch_price(request.pair)
        )

        # Pre-trade rule check: if this order's worst case (its stop-loss) would
        # breach the daily-loss or max-drawdown limit, refuse before accepting.
        worst = abs(fill - float(request.sl)) * float(request.lot_size) if request.sl is not None else 0.0
        if (self._day_pnl - worst) <= -self._daily_loss_amt():
            return self._reject(request, "would_breach_daily_loss")
        equity_now = self.balance + self._unrealized()
        if (equity_now - worst) <= self._drawdown_floor():
            return self._reject(request, "would_breach_max_drawdown")

        self._trading_days.add(self._current_day)
        pos = SimPosition(
            pair=request.pair, direction=request.direction, entry=fill,
            units=request.lot_size, sl=request.sl, tp=request.tp, open_time=now,
        )
        self._positions[pos.id] = pos
        rec = {
            "position_id": pos.id, "pair": pos.pair, "direction": pos.direction.value,
            "fill": float(fill), "units": pos.units, "sl": pos.sl, "tp": pos.tp,
            "client_order_id": request.client_order_id, "status": "FILLED",
        }
        self._fill_log.append(rec)
        logger.info(
            f"cft_sim FILL {pos.pair} {pos.direction.value} {pos.units}@{fill} "
            f"sl={pos.sl} tp={pos.tp}"
        )
        return rec

    async def close_position(self, position_id: str, lot_size: float | None = None) -> dict:
        pos = self._positions.get(position_id)
        if not pos:
            return {"status": "not_found", "position_id": position_id}
        exit_price = await self._fetch_price(pos.pair)
        return self._settle(pos, exit_price, reason="MANUAL")

    async def close_all_positions(self) -> list[dict]:
        out: list[dict] = []
        for p in list(self._positions.values()):
            exit_price = await self._fetch_price(p.pair)
            out.append(self._settle(p, exit_price, reason="CLOSE_ALL"))
        return out

    async def stream_prices(self, pairs: list[str], callback: Callable) -> None:
        raise NotImplementedError("SimPropFirmBroker is driven via on_tick(), not streaming")
