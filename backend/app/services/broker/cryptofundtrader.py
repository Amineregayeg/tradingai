"""Crypto Fund Trader (Match-Trader / QFX) broker adapter.

Crypto Fund Trader runs on the Match-Trade Technologies *Match-Trader* platform.
The endpoint map below was confirmed against the live terminal at
``trading.cryptofundtrader.com`` (read-only network capture), and differs from the
generic "Platform API" docs:

Auth (host-level)
    POST /mtr-core-edge/login            body {email, password}
        -> { tradingAccounts: [ { tradingAccountId, tradingApiToken,
                                   offer: { currency, system: { uuid } } } ],
             selectedTradingAccount: { tradingAccountId, group, ... } }

Account-scoped (header ``Auth-trading-api: <tradingApiToken>``)
    GET  /mtr-api/{uuid}/balance
    GET  /mtr-api/{uuid}/open-positions          -> { positions: [...] }
    GET  /mtr-api/{uuid}/active-orders
    GET  /mtr-api/{uuid}/group                   -> group name (for quotes)
    POST /mtr-api/{uuid}/position/open           (trading; gated by observe_only)
    POST /mtr-api/{uuid}/position/close          (trading; gated by observe_only)

Market data
    POST /market-data-api/{uuid}/api/quotations-with-daily-change
         body {symbols:[...], groupName}         -> [{symbol,bid,ask,timestamp,...}]

Multi-account: the login returns every trading account; ``account_id`` selects one
by its ``tradingAccountId`` (e.g. "365105" = 5k challenge, "373010" = 2.5k instant).
Omit it to use the platform's currently selected account.

Safety: prop firms typically forbid automated order placement. ``observe_only``
defaults to True — reads work; ``place_order`` / ``close_position`` /
``close_all_positions`` raise until trading is explicitly enabled.
"""
from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

import httpx

from app.core.exceptions import BrokerConnectionError, BrokerError, BrokerRateLimitError
from app.core.logging import logger
from app.db.enums import DirectionType
from app.schemas.broker import Position
from app.services.broker.base import Account, BrokerAdapter, OrderRequest

DEFAULT_HOST = "https://trading.cryptofundtrader.com"

# Host-level auth endpoint.
EP_LOGIN = "/mtr-core-edge/login"

# Header the platform expects the per-account trading token in.
AUTH_HEADER = "Auth-trading-api"

# Forwarded-tick rate limit (ticks/s per instrument).
PRICE_RATE_LIMIT = 5
# Seconds between quote polls when streaming (the terminal polls REST quotes).
QUOTE_POLL_INTERVAL = 1.0

# Crypto on this platform quotes against USDT with a ``.cft`` broker suffix.
_QUOTE = "USDT"
_SUFFIX = ".cft"


def to_mt_symbol(pair: str) -> str:
    """``BTC/USD`` → ``BTCUSDT.cft`` (platform crypto symbol)."""
    base = pair.replace("/", "").replace("_", "").upper()
    for q in ("USDT", "USDC", "USD"):
        if base.endswith(q):
            base = base[: -len(q)]
            break
    return f"{base}{_QUOTE}{_SUFFIX}"


def from_mt_symbol(symbol: str) -> str:
    """``BTCUSDT.cft`` → ``BTC/USD`` (app display symbol)."""
    s = symbol.upper().replace(_SUFFIX.upper(), "")
    if "/" in s:
        return s
    for q in ("USDT", "USDC", "USD"):
        if s.endswith(q) and len(s) > len(q):
            return f"{s[: -len(q)]}/USD"
    return s


def _dec(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


class CryptoFundTraderAdapter(BrokerAdapter):
    """Match-Trader / QFX implementation for Crypto Fund Trader."""

    broker_name: str = "cryptofundtrader"
    default_pairs: list[str] = ["BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "BNB/USD"]

    def __init__(
        self,
        email: str,
        password: str,
        base_url: str = DEFAULT_HOST,
        account_id: str = "",
        environment: str = "live",
        observe_only: bool = True,
    ) -> None:
        self._email = email
        self._password = password
        self._host = (base_url or DEFAULT_HOST).rstrip("/")
        self._account_id = str(account_id or "")  # tradingAccountId selector
        self._environment = environment.lower()
        self.observe_only = observe_only

        self.connected: bool = False
        self._token: str | None = None
        self._system_uuid: str = ""
        self._group: str = ""
        self._currency: str = "USD"

        self._client = httpx.AsyncClient(
            base_url=self._host,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=httpx.Timeout(30.0, connect=10.0),
        )
        self._last_tick_ts: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Path builders
    # ------------------------------------------------------------------

    def _api(self, path: str) -> str:
        return f"/mtr-api/{self._system_uuid}{path}"

    def _market(self, path: str) -> str:
        return f"/market-data-api/{self._system_uuid}{path}"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _handle_response(self, response: httpx.Response, context: str) -> Any:
        if response.status_code in (401, 403):
            raise BrokerConnectionError(
                f"Crypto Fund Trader auth failed during {context}",
                broker=self.broker_name,
                detail=f"HTTP {response.status_code} — check credentials/token. Context: {context}",
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
                f"Crypto Fund Trader rate limit during {context}",
                broker=self.broker_name,
                retry_after_seconds=retry_after,
                detail=f"HTTP 429 during {context}",
            )
        if response.status_code >= 400:
            try:
                body = response.json()
            except Exception:
                body = response.text
            raise BrokerError(
                f"Crypto Fund Trader API error {response.status_code} during {context}",
                broker=self.broker_name,
                detail=str(body),
            )
        if not response.content:
            return {}
        try:
            return response.json()
        except Exception:
            return {}

    def _guard_trading(self, action: str) -> None:
        if self.observe_only:
            raise BrokerError(
                f"{action} blocked: this Crypto Fund Trader connection is observe-only. "
                "Enable trading only after confirming the firm permits automated/API orders.",
                broker=self.broker_name,
                detail="observe_only=True",
            )

    @staticmethod
    def _parse_time(ts: Any) -> datetime | None:
        if ts is None or ts == "":
            return None
        if isinstance(ts, (int, float)):
            seconds = float(ts) / 1000.0 if float(ts) > 1e12 else float(ts)
            try:
                return datetime.fromtimestamp(seconds, tz=timezone.utc)
            except (ValueError, OSError, OverflowError):
                return None
        try:
            return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except ValueError:
            return None

    @staticmethod
    def _duration_seconds(open_time: datetime | None) -> int:
        if open_time is None:
            return 0
        if open_time.tzinfo is None:
            open_time = open_time.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(tz=timezone.utc) - open_time).total_seconds()))

    @staticmethod
    def _side_to_direction(side: Any) -> DirectionType:
        s = str(side or "").upper()
        if s in {"SELL", "SHORT", "S"}:
            return DirectionType.SHORT
        return DirectionType.LONG

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Log in, select the trading account, and capture its token + system uuid."""
        logger.info(
            "Connecting to Crypto Fund Trader",
            host=self._host,
            account_id=self._account_id or "(selected)",
            observe_only=self.observe_only,
        )
        try:
            response = await self._client.post(
                EP_LOGIN, json={"email": self._email, "password": self._password}
            )
        except httpx.RequestError as exc:
            raise BrokerConnectionError(
                "Network error connecting to Crypto Fund Trader",
                broker=self.broker_name,
                detail=str(exc),
            ) from exc

        data = self._handle_response(response, "connect/login")
        if not isinstance(data, dict):
            raise BrokerConnectionError(
                "Unexpected login response from Crypto Fund Trader",
                broker=self.broker_name,
            )

        accounts: list[dict] = data.get("tradingAccounts") or []
        selected: dict = data.get("selectedTradingAccount") or {}

        chosen: dict | None = None
        if self._account_id:
            chosen = next(
                (a for a in accounts if str(a.get("tradingAccountId")) == self._account_id),
                None,
            )
            if chosen is None:
                raise BrokerConnectionError(
                    f"Trading account {self._account_id!r} not found on this login",
                    broker=self.broker_name,
                    detail=f"Available: {[a.get('tradingAccountId') for a in accounts]}",
                )
        if chosen is None:
            chosen = selected or (accounts[0] if accounts else None)
        if not chosen:
            raise BrokerConnectionError(
                "No trading accounts returned by Crypto Fund Trader login",
                broker=self.broker_name,
            )

        offer = chosen.get("offer") or {}
        system = offer.get("system") or {}
        self._token = chosen.get("tradingApiToken")
        self._system_uuid = system.get("uuid") or (selected.get("offer") or {}).get(
            "system", {}
        ).get("uuid", "")
        self._account_id = str(chosen.get("tradingAccountId") or self._account_id)
        self._currency = offer.get("currency", "USD")
        # group is needed for quote polling; present on selectedTradingAccount.
        self._group = chosen.get("group") or selected.get("group") or ""

        if not self._token or not self._system_uuid:
            raise BrokerConnectionError(
                "Login succeeded but token/system UUID missing",
                broker=self.broker_name,
                detail=f"token={'set' if self._token else 'missing'} uuid={self._system_uuid!r}",
            )

        self._client.headers[AUTH_HEADER] = self._token

        # Validate by fetching the balance, and backfill the group if absent.
        await self.get_account()
        if not self._group:
            try:
                grp = await self._client.get(self._api("/group"))
                gdata = self._handle_response(grp, "connect/group")
                if isinstance(gdata, dict):
                    self._group = gdata.get("group") or gdata.get("name") or ""
                elif isinstance(gdata, str):
                    self._group = gdata
            except Exception:
                pass

        self.connected = True
        logger.info(
            "Connected to Crypto Fund Trader",
            account_id=self._account_id,
            system_uuid=self._system_uuid,
        )

    async def disconnect(self) -> None:
        logger.info("Disconnecting from Crypto Fund Trader", account_id=self._account_id)
        self.connected = False
        self._token = None
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    async def get_account(self) -> Account:
        response = await self._client.get(self._api("/balance"))
        data = self._handle_response(response, "get_account")
        acct = data if isinstance(data, dict) else {}
        self._currency = acct.get("currency", self._currency)
        return Account(
            account_id=self._account_id,
            broker=self.broker_name,
            balance=float(_dec(acct.get("balance"))),
            equity=float(_dec(acct.get("equity", acct.get("balance")))),
            currency=self._currency,
            margin_used=float(_dec(acct.get("margin"))),
            margin_available=float(_dec(acct.get("freeMargin"))),
            open_trade_count=0,
            unrealized_pl=float(_dec(acct.get("profit", acct.get("netProfit")))),
        )

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    @staticmethod
    def _list_field(data: Any, *keys: str) -> list[dict]:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in keys:
                val = data.get(key)
                if isinstance(val, list):
                    return val
        return []

    async def get_positions(self) -> list[Position]:
        response = await self._client.get(self._api("/open-positions"))
        data = self._handle_response(response, "get_positions")

        positions: list[Position] = []
        for raw in self._list_field(data, "positions", "openPositions"):
            symbol = raw.get("symbol") or raw.get("instrument") or "UNKNOWN"
            pair = from_mt_symbol(symbol)
            direction = self._side_to_direction(raw.get("side", raw.get("type")))

            entry_price = _dec(raw.get("openPrice", raw.get("price")))
            current_price = _dec(
                raw.get("currentPrice", raw.get("marketPrice")), default=str(entry_price)
            )
            unrealized_pnl = _dec(
                raw.get("profit", raw.get("netProfit", raw.get("openNetProfit")))
            )
            volume = _dec(raw.get("volume", raw.get("lots", raw.get("size"))))
            sl = raw.get("stopLoss", raw.get("slPrice", raw.get("sl")))
            tp = raw.get("takeProfit", raw.get("tpPrice", raw.get("tp")))
            sl_dec = _dec(sl) if sl not in (None, "", 0, "0") else None
            tp_dec = _dec(tp) if tp not in (None, "", 0, "0") else None

            r_multiple: Decimal | None = None
            if sl_dec and sl_dec > 0 and entry_price != 0 and volume:
                risk = abs(entry_price - sl_dec)
                if risk > 0:
                    r_multiple = (unrealized_pnl / volume) / risk

            open_time = self._parse_time(raw.get("openTime", raw.get("openTimestamp")))
            positions.append(
                Position(
                    id=str(raw.get("id", raw.get("positionId", symbol))),
                    pair=pair,
                    direction=direction,
                    entry_price=entry_price,
                    current_price=current_price,
                    unrealized_pnl=unrealized_pnl,
                    r_multiple=r_multiple,
                    lot_size=volume,
                    sl=sl_dec,
                    tp=tp_dec,
                    duration_seconds=self._duration_seconds(open_time),
                    open_time=open_time or datetime.now(tz=timezone.utc),
                )
            )
        return positions

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    async def get_orders(self, status: str | None = None) -> list[dict]:
        response = await self._client.get(self._api("/active-orders"))
        data = self._handle_response(response, "get_orders")
        orders = []
        for raw in self._list_field(data, "orders", "activeOrders"):
            symbol = raw.get("symbol") or raw.get("instrument") or ""
            orders.append(
                {
                    "id": raw.get("id", raw.get("orderId")),
                    "pair": from_mt_symbol(symbol) if symbol else None,
                    "type": raw.get("type", raw.get("orderType")),
                    "state": raw.get("status", raw.get("state")),
                    "units": raw.get("volume", raw.get("lots")),
                    "price": raw.get("price", raw.get("openPrice")),
                    "stop_loss_on_fill": raw.get("stopLoss", raw.get("slPrice")),
                    "take_profit_on_fill": raw.get("takeProfit", raw.get("tpPrice")),
                    "create_time": raw.get("createTime", raw.get("openTime")),
                    "raw": raw,
                }
            )
        return orders

    # ------------------------------------------------------------------
    # Trade history
    # ------------------------------------------------------------------

    async def get_recent_trades(self, since: datetime | None = None) -> list[dict]:
        """Closed positions history.

        Endpoint not exercised during read-only discovery; uses the Match-Trader
        ``/closed-positions`` convention and degrades to empty on error.
        """
        params: dict[str, str] = {}
        if since is not None:
            ts = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
            params["from"] = ts.isoformat()
        try:
            response = await self._client.get(self._api("/closed-positions"), params=params)
            data = self._handle_response(response, "get_recent_trades")
        except BrokerError:
            return []

        trades = []
        for raw in self._list_field(data, "positions", "closedPositions"):
            symbol = raw.get("symbol") or raw.get("instrument") or ""
            close_time = self._parse_time(raw.get("closeTime", raw.get("closeTimestamp")))
            if since and close_time and close_time < since:
                continue
            open_time = self._parse_time(raw.get("openTime", raw.get("openTimestamp")))
            trades.append(
                {
                    "id": raw.get("id", raw.get("positionId")),
                    "pair": from_mt_symbol(symbol) if symbol else None,
                    "direction": self._side_to_direction(raw.get("side", raw.get("type"))).value,
                    "units": raw.get("volume", raw.get("lots")),
                    "open_price": raw.get("openPrice", raw.get("price")),
                    "close_price": raw.get("closePrice"),
                    "open_time": open_time.isoformat() if open_time else None,
                    "close_time": close_time.isoformat() if close_time else None,
                    "realized_pl": raw.get("profit", raw.get("netProfit")),
                    "financing": raw.get("swap"),
                    "raw": raw,
                }
            )
        return trades

    # ------------------------------------------------------------------
    # Order placement / close (gated by observe_only)
    # ------------------------------------------------------------------

    async def place_order(self, request: OrderRequest) -> dict:
        self._guard_trading("place_order")
        symbol = to_mt_symbol(request.pair)
        side = "BUY" if request.direction == DirectionType.LONG else "SELL"
        body: dict[str, Any] = {
            "symbol": symbol,
            "instrument": symbol,
            "volume": float(request.lot_size),
            "side": side,
            "type": request.order_type.value,
        }
        if request.price is not None:
            body["price"] = float(request.price)
        if request.sl is not None:
            body["stopLoss"] = float(request.sl)
        if request.tp is not None:
            body["takeProfit"] = float(request.tp)
        logger.info("Placing Crypto Fund Trader order", symbol=symbol, side=side)
        response = await self._client.post(self._api("/position/open"), json=body)
        return self._handle_response(response, "place_order")

    async def close_position(self, position_id: str, lot_size: float | None = None) -> dict:
        self._guard_trading("close_position")
        body: dict[str, Any] = {"id": position_id, "positionId": position_id}
        if lot_size is not None:
            body["volume"] = float(lot_size)
        logger.info("Closing Crypto Fund Trader position", position_id=position_id)
        response = await self._client.post(self._api("/position/close"), json=body)
        return self._handle_response(response, f"close_position({position_id})")

    async def close_all_positions(self) -> list[dict]:
        self._guard_trading("close_all_positions")
        positions = await self.get_positions()
        results: list[dict] = []
        for pos in positions:
            try:
                result = await self.close_position(pos.id)
                results.append({"pair": pos.pair, "position_id": pos.id, "status": "closed", "result": result})
            except BrokerError as exc:
                results.append({"pair": pos.pair, "position_id": pos.id, "status": "error", "error": str(exc)})
        return results

    # ------------------------------------------------------------------
    # Price streaming — poll the quotes endpoint the terminal uses
    # ------------------------------------------------------------------

    async def stream_prices(self, pairs: list[str], callback: Callable) -> None:
        """Poll ``quotations-with-daily-change`` and forward normalised ticks.

        The Match-Trader terminal fetches quotes over REST, so we poll rather than
        guess a WebSocket protocol. Degrades gracefully on error.
        """
        import time as _time

        symbols = [to_mt_symbol(p) for p in pairs]
        tick_interval = 1.0 / PRICE_RATE_LIMIT
        logger.info("Starting Crypto Fund Trader quote polling", symbols=symbols, group=self._group)

        try:
            while True:
                try:
                    resp = await self._client.post(
                        self._market("/api/quotations-with-daily-change"),
                        json={"symbols": symbols, "groupName": self._group},
                    )
                    quotes = self._handle_response(resp, "stream_prices")
                except (BrokerError, httpx.RequestError) as exc:
                    logger.warning("CFT quote poll error", error=str(exc))
                    await asyncio.sleep(QUOTE_POLL_INTERVAL)
                    continue

                for q in quotes if isinstance(quotes, list) else []:
                    symbol = q.get("symbol")
                    if not symbol or (q.get("bid") is None and q.get("ask") is None):
                        continue
                    now = _time.monotonic()
                    if now - self._last_tick_ts.get(symbol, 0.0) < tick_interval:
                        continue
                    self._last_tick_ts[symbol] = now
                    normalised = {
                        "pair": from_mt_symbol(symbol),
                        "instrument": symbol,
                        "bid": q.get("bid"),
                        "ask": q.get("ask"),
                        "time": q.get("timestamp"),
                        "tradeable": True,
                        "type": "PRICE",
                        "broker": self.broker_name,
                    }
                    try:
                        if inspect.iscoroutinefunction(callback):
                            await callback(normalised)
                        else:
                            callback(normalised)
                    except Exception as cb_exc:
                        logger.warning("CFT price callback error", error=str(cb_exc))

                await asyncio.sleep(QUOTE_POLL_INTERVAL)
        except asyncio.CancelledError:
            logger.info("Crypto Fund Trader quote polling cancelled")
            raise
        except Exception as exc:
            logger.warning("Crypto Fund Trader quote polling ended", error=str(exc))
            return
