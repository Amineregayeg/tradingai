"""Abstract broker adapter base class."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from app.db.enums import DirectionType, OrderType
from app.schemas.broker import Position


@dataclass
class Account:
    """Normalised broker account summary."""

    account_id: str
    broker: str
    balance: float
    equity: float
    currency: str
    margin_used: float = 0.0
    margin_available: float = 0.0
    open_trade_count: int = 0
    unrealized_pl: float = 0.0


@dataclass
class OrderRequest:
    """Broker-agnostic order request."""

    pair: str
    direction: DirectionType
    order_type: OrderType
    lot_size: float
    price: float | None = None  # None for MARKET orders
    sl: float | None = None
    tp: float | None = None
    client_order_id: str | None = None


class BrokerAdapter(ABC):
    """Abstract base class every broker integration must implement."""

    broker_name: str = "unknown"

    # Instruments this broker should stream by default. Empty ⇒ use the caller's
    # requested list. Lets a crypto broker (CFT) stream crypto while a forex
    # broker (OANDA) streams the forex pairs passed in from startup.
    default_pairs: list[str] = []

    # ------------------------------------------------------------------
    # Simulation contract (SAFETY)
    # ------------------------------------------------------------------
    # Every adapter MUST declare whether it is a simulation. There is NO default:
    # a subclass that forgets to implement this cannot be instantiated (abstract),
    # so a new real-money adapter can never silently pass as safe. Safety-critical
    # chokepoints (ExecutionService, the kill switch, position-close routing) read
    # this and refuse to send writes to a non-simulation broker unless a real,
    # explicit live path is chosen.
    @property
    @abstractmethod
    def is_simulation(self) -> bool:
        """True iff this adapter can never place a real-money order."""
        ...

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    async def connect(self) -> None:
        """Open connection and validate credentials."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Close all open connections gracefully."""
        ...

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    @abstractmethod
    async def get_account(self) -> Account:
        """Return current account summary."""
        ...

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    @abstractmethod
    async def get_positions(self) -> list[Position]:
        """Return all currently open positions."""
        ...

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    @abstractmethod
    async def get_orders(self, status: str | None = None) -> list[dict]:
        """Return pending / historical orders.

        Args:
            status: Optional filter (e.g. ``"PENDING"``). Broker-specific values.
        """
        ...

    # ------------------------------------------------------------------
    # Trade history
    # ------------------------------------------------------------------

    @abstractmethod
    async def get_recent_trades(self, since: datetime | None = None) -> list[dict]:
        """Return recently closed trades.

        Args:
            since: Only return trades closed after this timestamp.
        """
        ...

    # ------------------------------------------------------------------
    # Order management
    # ------------------------------------------------------------------

    @abstractmethod
    async def place_order(self, request: OrderRequest) -> dict:
        """Place a new order and return the broker response."""
        ...

    @abstractmethod
    async def close_position(
        self,
        position_id: str,
        lot_size: float | None = None,
    ) -> dict:
        """Close an open position.

        Args:
            position_id: Broker instrument identifier (e.g. ``"EUR_USD"``).
            lot_size: Partial close volume.  ``None`` means close all units.
        """
        ...

    @abstractmethod
    async def close_all_positions(self) -> list[dict]:
        """Close every open position.  Returns list of per-position results."""
        ...

    # ------------------------------------------------------------------
    # Price streaming
    # ------------------------------------------------------------------

    @abstractmethod
    async def stream_prices(
        self,
        pairs: list[str],
        callback: Callable,
    ) -> None:
        """Stream live price ticks.

        Args:
            pairs: List of instrument identifiers.
            callback: Async or sync callable called with each price tick dict.
        """
        ...

    # ------------------------------------------------------------------
    async def reference_price(self, pair: str) -> float | None:
        """Price a MARKET order would fill at right now, or None if unknown.

        Deliberately NOT abstract. Adding an abstract method here would make
        every existing adapter un-instantiable, and the ``is_simulation``
        contract already uses that lever for the one property worth enforcing
        that way. Returning None is a safe default: ``ExecutionService`` refuses
        to size a market order without a reference price rather than guessing.

        Why this exists: a market order does not fill at the price the strategy
        named, it fills at the market. Sizing off the strategy's intended price
        makes the position's real risk differ from the configured risk_pct by
        however far the market has moved — silently, and in whichever direction
        the market happened to go.
        """
        return None
