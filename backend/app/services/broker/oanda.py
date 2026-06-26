"""OANDA v20 REST + streaming broker adapter."""
from __future__ import annotations

import asyncio
import inspect
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable

import httpx

from app.core.exceptions import BrokerConnectionError, BrokerError, BrokerRateLimitError
from app.core.logging import logger
from app.db.enums import DirectionType, OrderType
from app.schemas.broker import Position
from app.services.broker.base import Account, BrokerAdapter, OrderRequest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OANDA_BASE_URLS: dict[str, str] = {
    "practice": "https://api-fxpractice.oanda.com",
    "live": "https://api-fxtrade.oanda.com",
}

OANDA_STREAM_URLS: dict[str, str] = {
    "practice": "https://stream-fxpractice.oanda.com",
    "live": "https://stream-fxtrade.oanda.com",
}

OANDA_PRICE_RATE_LIMIT = 10  # max ticks/s per pair to forward

# ---------------------------------------------------------------------------
# Pair normalisation helpers
# ---------------------------------------------------------------------------


def to_oanda_pair(pair: str) -> str:
    """Convert ``EUR/USD`` → ``EUR_USD``.  Already-normalised strings pass through."""
    return pair.replace("/", "_").upper()


def from_oanda_pair(instrument: str) -> str:
    """Convert ``EUR_USD`` → ``EUR/USD``."""
    return instrument.replace("_", "/")


# ---------------------------------------------------------------------------
# OANDAAdapter
# ---------------------------------------------------------------------------


class OANDAAdapter(BrokerAdapter):
    """OANDA v20 REST + streaming implementation."""

    broker_name: str = "oanda"

    def __init__(
        self,
        api_key: str,
        account_id: str,
        environment: str = "practice",
    ) -> None:
        env = environment.lower()
        if env not in OANDA_BASE_URLS:
            raise ValueError(f"Unknown OANDA environment: {environment!r}")

        self._api_key = api_key
        self._account_id = account_id
        self._environment = env
        self._base_url = OANDA_BASE_URLS[env]
        self._stream_url = OANDA_STREAM_URLS[env]
        self.connected: bool = False

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept-Datetime-Format": "RFC3339",
            },
            timeout=httpx.Timeout(30.0, connect=10.0),
        )

        # Per-pair last-forwarded timestamp for rate limiting
        self._last_tick_ts: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _account_url(self, path: str) -> str:
        """Build account-scoped OANDA URL path."""
        return f"/v3/accounts/{self._account_id}{path}"

    def _handle_response(self, response: httpx.Response, context: str) -> dict:
        """Raise typed exceptions for error HTTP status codes."""
        if response.status_code == 401:
            raise BrokerConnectionError(
                f"OANDA authentication failed for {context}",
                broker="oanda",
                detail=f"HTTP 401 — check API key. Context: {context}",
            )
        if response.status_code == 429:
            retry_after: int | None = None
            raw = response.headers.get("Retry-After")
            if raw:
                try:
                    retry_after = int(raw)
                except ValueError:
                    pass
            raise BrokerRateLimitError(
                f"OANDA rate limit hit during {context}",
                broker="oanda",
                retry_after_seconds=retry_after,
                detail=f"HTTP 429 — retry after {retry_after}s",
            )
        if response.status_code >= 400:
            try:
                body = response.json()
            except Exception:
                body = response.text
            raise BrokerError(
                f"OANDA API error {response.status_code} during {context}",
                broker="oanda",
                detail=str(body),
            )
        return response.json()

    @staticmethod
    def _parse_oanda_time(ts: str | None) -> datetime | None:
        """Parse RFC 3339 timestamp returned by OANDA into an aware datetime."""
        if not ts:
            return None
        try:
            # Python 3.11+ supports Z suffix directly; older versions don't
            ts_clean = ts.replace("Z", "+00:00")
            return datetime.fromisoformat(ts_clean)
        except Exception:
            return None

    @staticmethod
    def _duration_seconds(open_time: datetime | None) -> int:
        """Seconds elapsed since *open_time*.  Returns 0 if unknown."""
        if open_time is None:
            return 0
        now = datetime.now(tz=timezone.utc)
        if open_time.tzinfo is None:
            open_time = open_time.replace(tzinfo=timezone.utc)
        delta = now - open_time
        return max(0, int(delta.total_seconds()))

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Validate credentials by calling the account summary endpoint."""
        logger.info("Connecting to OANDA", environment=self._environment, account_id=self._account_id)
        try:
            response = await self._client.get(self._account_url("/summary"))
        except httpx.RequestError as exc:
            raise BrokerConnectionError(
                "Network error connecting to OANDA",
                broker="oanda",
                detail=str(exc),
            ) from exc

        self._handle_response(response, "connect/summary")
        self.connected = True
        logger.info("Connected to OANDA successfully", account_id=self._account_id)

    async def disconnect(self) -> None:
        """Close the underlying HTTP client."""
        logger.info("Disconnecting from OANDA", account_id=self._account_id)
        await self._client.aclose()
        self.connected = False

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    async def get_account(self) -> Account:
        response = await self._client.get(self._account_url("/summary"))
        data = self._handle_response(response, "get_account")
        acct = data.get("account", {})

        return Account(
            account_id=acct.get("id", self._account_id),
            broker="oanda",
            balance=float(acct.get("balance", 0)),
            equity=float(acct.get("NAV", acct.get("balance", 0))),
            currency=acct.get("currency", "USD"),
            margin_used=float(acct.get("marginUsed", 0)),
            margin_available=float(acct.get("marginAvailable", 0)),
            open_trade_count=int(acct.get("openTradeCount", 0)),
            unrealized_pl=float(acct.get("unrealizedPL", 0)),
        )

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    async def get_positions(self) -> list[Position]:
        """Return all open positions mapped to the Position schema."""
        response = await self._client.get(self._account_url("/openPositions"))
        data = self._handle_response(response, "get_positions")

        positions: list[Position] = []
        for raw in data.get("positions", []):
            instrument = raw.get("instrument", "UNKNOWN")
            pair = from_oanda_pair(instrument)

            long_units = int(raw.get("long", {}).get("units", 0))
            short_units = int(raw.get("short", {}).get("units", 0))

            # Determine which side is actually open
            if long_units > 0:
                side = raw["long"]
                direction = DirectionType.LONG
                units = long_units
            elif short_units < 0:
                side = raw["short"]
                direction = DirectionType.SHORT
                units = abs(short_units)
            else:
                continue  # empty position

            avg_price_str = side.get("averagePrice", "0")
            entry_price = Decimal(avg_price_str)

            unrealized_pnl = Decimal(side.get("unrealizedPL", "0"))

            # Current price isn't in openPositions payload; approximate from entry+PnL
            # OANDA's /pricing endpoint is separate; use entry_price as current approximation
            # The real current price is best obtained from the pricing stream
            current_price = entry_price + (unrealized_pnl / Decimal(units)) if units else entry_price

            # Trade details (first trade gives us SL/TP and open time)
            trade_ids = side.get("tradeIDs", [])
            sl: Decimal | None = None
            tp: Decimal | None = None
            open_time: datetime | None = None
            position_id = instrument  # OANDA groups by instrument

            if trade_ids:
                # Use the instrument as position_id; there may be multiple trade legs
                position_id = trade_ids[0]

            # Attempt to get SL from side.tradeIDs first trade if present
            # OANDA v20 openPositions doesn't return SL/TP directly; we skip for now
            # (reconciler will fill from trade details on demand)
            r_multiple: Decimal | None = None
            if sl is not None and sl > 0 and entry_price != 0:
                risk_per_unit = abs(entry_price - sl)
                if risk_per_unit > 0:
                    pnl_per_unit = unrealized_pnl / Decimal(units) if units else Decimal(0)
                    r_multiple = pnl_per_unit / risk_per_unit

            open_time_str = side.get("openTime") or raw.get("openTime")
            open_time = self._parse_oanda_time(open_time_str)
            duration = self._duration_seconds(open_time)

            positions.append(
                Position(
                    id=position_id,
                    pair=pair,
                    direction=direction,
                    entry_price=entry_price,
                    current_price=current_price.quantize(Decimal("0.000001")),
                    unrealized_pnl=unrealized_pnl,
                    r_multiple=r_multiple,
                    lot_size=Decimal(units),
                    sl=sl,
                    tp=tp,
                    duration_seconds=duration,
                    open_time=open_time or datetime.now(tz=timezone.utc),
                )
            )

        return positions

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    async def get_orders(self, status: str | None = None) -> list[dict]:
        """Return orders, optionally filtered by state."""
        params: dict[str, str] = {"count": "50"}
        if status:
            params["state"] = status.upper()

        response = await self._client.get(self._account_url("/orders"), params=params)
        data = self._handle_response(response, "get_orders")

        orders = []
        for raw in data.get("orders", []):
            instrument = raw.get("instrument", "")
            orders.append(
                {
                    "id": raw.get("id"),
                    "pair": from_oanda_pair(instrument) if instrument else None,
                    "type": raw.get("type"),
                    "state": raw.get("state"),
                    "units": raw.get("units"),
                    "price": raw.get("price"),
                    "stop_loss_on_fill": raw.get("stopLossOnFill"),
                    "take_profit_on_fill": raw.get("takeProfitOnFill"),
                    "create_time": raw.get("createTime"),
                    "raw": raw,
                }
            )
        return orders

    # ------------------------------------------------------------------
    # Trade history
    # ------------------------------------------------------------------

    async def get_recent_trades(self, since: datetime | None = None) -> list[dict]:
        """Return recently closed trades (last 50)."""
        params: dict[str, str] = {"state": "CLOSED", "count": "50"}

        response = await self._client.get(self._account_url("/trades"), params=params)
        data = self._handle_response(response, "get_recent_trades")

        trades = []
        for raw in data.get("trades", []):
            open_time = self._parse_oanda_time(raw.get("openTime"))
            close_time = self._parse_oanda_time(raw.get("closeTime"))

            if since and close_time and close_time < since:
                continue

            instrument = raw.get("instrument", "")
            units = int(raw.get("initialUnits", 0))
            direction = DirectionType.LONG if units > 0 else DirectionType.SHORT

            trades.append(
                {
                    "id": raw.get("id"),
                    "pair": from_oanda_pair(instrument) if instrument else None,
                    "direction": direction.value,
                    "units": abs(units),
                    "open_price": raw.get("price"),
                    "close_price": raw.get("averageClosePrice"),
                    "open_time": open_time.isoformat() if open_time else None,
                    "close_time": close_time.isoformat() if close_time else None,
                    "realized_pl": raw.get("realizedPL"),
                    "financing": raw.get("financing"),
                    "raw": raw,
                }
            )
        return trades

    # ------------------------------------------------------------------
    # Order placement
    # ------------------------------------------------------------------

    async def place_order(self, request: OrderRequest) -> dict:
        """Place an order via OANDA v20 OrderCreate."""
        instrument = to_oanda_pair(request.pair)

        # Units: positive = long, negative = short
        units_sign = 1 if request.direction == DirectionType.LONG else -1
        # Convert lot size to units (OANDA uses units not lots)
        # 1 lot = 100,000 units for standard forex
        units = int(request.lot_size * 100_000) * units_sign

        order_body: dict = {
            "instrument": instrument,
            "units": str(units),
        }

        # Order type mapping
        if request.order_type == OrderType.MARKET:
            order_body["type"] = "MARKET"
        elif request.order_type == OrderType.LIMIT:
            order_body["type"] = "LIMIT"
            if request.price is not None:
                order_body["price"] = str(request.price)
        elif request.order_type == OrderType.STOP:
            order_body["type"] = "STOP"
            if request.price is not None:
                order_body["price"] = str(request.price)

        if request.sl is not None:
            order_body["stopLossOnFill"] = {"price": str(round(request.sl, 5))}

        if request.tp is not None:
            order_body["takeProfitOnFill"] = {"price": str(round(request.tp, 5))}

        if request.client_order_id:
            order_body["clientExtensions"] = {"id": request.client_order_id}

        payload = {"order": order_body}
        logger.info(
            "Placing OANDA order",
            instrument=instrument,
            order_type=request.order_type,
            direction=request.direction,
            units=units,
        )

        response = await self._client.post(
            self._account_url("/orders"),
            json=payload,
        )
        data = self._handle_response(response, "place_order")
        logger.info("OANDA order placed", order_create_transaction=data.get("orderCreateTransaction", {}).get("id"))
        return data

    # ------------------------------------------------------------------
    # Position close
    # ------------------------------------------------------------------

    async def close_position(
        self,
        position_id: str,
        lot_size: float | None = None,
    ) -> dict:
        """Close an open position.

        Args:
            position_id: Instrument name (``EUR_USD``) or trade ID. If it looks
                like a numeric trade ID we still map it to the instrument for the
                positions/close endpoint.
            lot_size: Partial close in units (lots × 100_000). ``None`` = ALL.
        """
        # OANDA close endpoint works on instruments, not individual trade IDs
        instrument = to_oanda_pair(position_id)

        if lot_size is not None:
            units = int(lot_size * 100_000)
            body = {"longUnits": str(units)}
        else:
            body = {"longUnits": "ALL", "shortUnits": "ALL"}

        logger.info("Closing OANDA position", instrument=instrument, lot_size=lot_size)

        response = await self._client.put(
            self._account_url(f"/positions/{instrument}/close"),
            json=body,
        )
        try:
            data = self._handle_response(response, f"close_position({instrument})")
        except BrokerError as exc:
            # If long side has no units, try short side
            if "shorUnits" not in body and lot_size is not None:
                short_body = {"shortUnits": str(int(lot_size * 100_000))}
                response2 = await self._client.put(
                    self._account_url(f"/positions/{instrument}/close"),
                    json=short_body,
                )
                data = self._handle_response(response2, f"close_position_short({instrument})")
            else:
                raise

        logger.info("OANDA position closed", instrument=instrument)
        return data

    async def close_all_positions(self) -> list[dict]:
        """Close all open positions.  Returns results list."""
        positions = await self.get_positions()
        results = []
        for pos in positions:
            try:
                instrument = to_oanda_pair(pos.pair)
                result = await self.close_position(instrument)
                results.append({"pair": pos.pair, "status": "closed", "result": result})
            except BrokerError as exc:
                logger.error("Failed to close position", pair=pos.pair, error=str(exc))
                results.append({"pair": pos.pair, "status": "error", "error": str(exc)})
        return results

    # ------------------------------------------------------------------
    # Price streaming
    # ------------------------------------------------------------------

    async def stream_prices(
        self,
        pairs: list[str],
        callback: Callable,
    ) -> None:
        """Stream live price ticks from OANDA pricing stream API.

        Rate-limits forwarded ticks to OANDA_PRICE_RATE_LIMIT per pair per second.
        """
        instruments = ",".join(to_oanda_pair(p) for p in pairs)
        stream_client = httpx.AsyncClient(
            base_url=self._stream_url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Accept-Datetime-Format": "RFC3339",
            },
            timeout=httpx.Timeout(None, connect=10.0),
        )

        tick_interval = 1.0 / OANDA_PRICE_RATE_LIMIT  # min seconds between forwarded ticks

        logger.info("Starting OANDA price stream", instruments=instruments)

        try:
            async with stream_client.stream(
                "GET",
                f"/v3/accounts/{self._account_id}/pricing/stream",
                params={"instruments": instruments},
            ) as response:
                if response.status_code == 401:
                    raise BrokerConnectionError(
                        "OANDA stream auth failed", broker="oanda"
                    )
                if response.status_code == 429:
                    raise BrokerRateLimitError(
                        "OANDA stream rate limited", broker="oanda"
                    )
                if response.status_code >= 400:
                    raise BrokerError(
                        f"OANDA stream error {response.status_code}", broker="oanda"
                    )

                async for line in response.aiter_lines():
                    if not line.strip():
                        continue

                    try:
                        import json
                        tick = json.loads(line)
                    except Exception:
                        continue

                    msg_type = tick.get("type", "")

                    if msg_type == "HEARTBEAT":
                        continue

                    if msg_type != "PRICE":
                        continue

                    instrument = tick.get("instrument", "")
                    now = time.monotonic()
                    last = self._last_tick_ts.get(instrument, 0.0)

                    if now - last < tick_interval:
                        continue  # rate-limit exceeded for this pair

                    self._last_tick_ts[instrument] = now

                    # Normalise tick before forwarding
                    normalised = {
                        "pair": from_oanda_pair(instrument),
                        "instrument": instrument,
                        "bid": tick.get("bids", [{}])[0].get("price") if tick.get("bids") else None,
                        "ask": tick.get("asks", [{}])[0].get("price") if tick.get("asks") else None,
                        "time": tick.get("time"),
                        "tradeable": tick.get("tradeable", False),
                        "type": "PRICE",
                        "broker": "oanda",
                    }

                    try:
                        if inspect.iscoroutinefunction(callback):
                            await callback(normalised)
                        else:
                            callback(normalised)
                    except Exception as cb_exc:
                        logger.warning("Price callback error", error=str(cb_exc))

        except (httpx.RemoteProtocolError, httpx.ReadError, asyncio.CancelledError):
            logger.info("OANDA price stream ended")
            raise
        except Exception as exc:
            logger.error("OANDA price stream error", error=str(exc))
            raise
        finally:
            await stream_client.aclose()
