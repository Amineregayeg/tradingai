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
