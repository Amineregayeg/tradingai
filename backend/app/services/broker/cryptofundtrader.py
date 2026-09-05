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

#: The P&L keys this venue is known to send, in the order the adapter has always preferred.
#: **The ORDER IS UNCHANGED by `T-0102`** — that task records which key was read and decides
#: nothing about which one the venue actually sends, because asking the live API is `T-0114`
#: and is gated: CFT is a third-party production broker.
PNL_KEYS: tuple[str, ...] = ("profit", "netProfit", "openNetProfit")


#: Keys this venue is known to use for a position's size, in the adapter's historical order.
VOLUME_KEYS: tuple[str, ...] = ("volume", "lots", "size")

#: Keys the ACCOUNT payload is known to use for open P&L. `B286`'s pair — `profit` is
#: conventionally GROSS and `netProfit` is net of costs, so they are NOT the same quantity.
#: **`T-0114` fixed the POSITION field and left its sibling twelve lines above** (`B377`).
ACCOUNT_PNL_KEYS: tuple[str, ...] = ("profit", "netProfit")

#: The DOCUMENTED side/type spellings, mapped explicitly. **`B376`.**
#:
#: THE KNOWN SET IS A GUESS AND SAYING SO IS PART OF THE FIX. Unlike MT5 there is no SDK, no
#: capture corpus and no vendor documentation here — the endpoint map was reverse-engineered from
#: the terminal by network capture — so **nothing is known about which spellings CFT actually
#: sends.** If this guess is wrong the adapter will REFUSE rather than trade the wrong way round,
#: which is the safe direction; **one capture of a real open position settles it** and is the
#: cheapest thing anyone could do to this file.
SIDE_DIRECTIONS: dict[str, DirectionType] = {
    "BUY": DirectionType.LONG, "LONG": DirectionType.LONG, "B": DirectionType.LONG,
    "SELL": DirectionType.SHORT, "SHORT": DirectionType.SHORT, "S": DirectionType.SHORT,
}


def first_key_present(raw: dict, keys: tuple[str, ...]) -> str | None:
    """Which of `keys` this payload ACTUALLY carries, or `None` (`B286`, generalised by `B377`).

    **PRESENCE, NOT `.get` WITH A DEFAULT**, and never a fallback to the first key — that
    reintroduces the ambiguity one layer down. A named function so an arm imports it rather than
    re-implementing it: the first `pnl_key_present` test re-implemented the selection inline, and
    a mutation restoring the silent fallback left those arms green because they exercised the copy.
    """
    return next((k for k in keys if k in raw), None)


def pnl_key_present(raw: dict) -> str | None:
    """Which P&L key this payload ACTUALLY carries, or `None` if it carries none (`B286`).

    **A NAMED FUNCTION SO THE ARM CAN IMPORT IT RATHER THAN RE-IMPLEMENT IT.** Its first
    test re-implemented the selection inline, and a mutation restoring the old silent
    fallback in this module left those arms green — they were exercising the copy. Same
    shape as `T-0065`'s vitest duplicate, and the fix is not to pin the copy but to remove it.

    **PRESENCE, NOT `.get` WITH A DEFAULT.** The key may be absent while a value still
    appears, and a provenance taken from a defaulted read would name a key the payload never
    carried. **And never a fallback to `"profit"`** — that reintroduces the ambiguity one
    layer down, in the field whose whole purpose is to remove it.
    """
    return first_key_present(raw, PNL_KEYS)


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

    # CryptoFundTrader has exactly ONE real host and no demo/sandbox host. We
    # keep `environment` (the manager and Settings UI read it) but there is no
    # simulation environment to route to — selecting one raises rather than
    # silently pretending. Simulated CFT testing is done via SimPropFirmBroker.
    CFT_BASE_URLS: dict[str, str] = {"live": DEFAULT_HOST}

    @property
    def is_simulation(self) -> bool:
        return False

    def __init__(
        self,
        email: str,
        password: str,
        base_url: str = DEFAULT_HOST,
        account_id: str = "",
        environment: str = "live",
        observe_only: bool = True,
    ) -> None:
        env = environment.lower()
        if env not in self.CFT_BASE_URLS:
            raise ValueError(
                f"CryptoFundTrader has no {environment!r} environment — only "
                f"'live' exists. Use SimPropFirmBroker for simulation."
            )
        self._email = email
        self._password = password
        self._host = (base_url or self.CFT_BASE_URLS[env]).rstrip("/")
        self._account_id = str(account_id or "")  # tradingAccountId selector
        self._environment = env
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
    def _require_account_key(acct: dict, key: str) -> Any:
        """A key the account payload must actually carry (`B377`).

        `equity` fell back to `balance`. **They are not the same quantity**: with the key absent
        the account asserts open P&L is zero while `unrealized_pl` on the same object may not be.

        **WHERE THIS EQUITY ACTUALLY GOES, TRACED RATHER THAN ASSUMED.** It reaches the prop-firm
        compliance monitor — `observe_sync.sync_account_compliance` does
        `total_loss = max(0.0, initial_balance - account.equity)` and then
        `compute_compliance_state(...)` — and the dashboard. **It does NOT reach position
        sizing.** `size_position(acct.equity, ...)` exists at `execution/service.py:151`, but both
        `ExecutionService` constructions pass the loop's SIMULATOR (`crypto_loop.py:168` and
        `:794`, `B350`), so no CFT account object arrives there.

        I nearly wrote *"it changes how large every position is"* here on a peer's word. It is
        false, and **the error was tracing a CALL SITE instead of tracing what is passed to it**.

        **It matters more than that, not less.** A prop-firm breach CLOSES THE ACCOUNT, and this
        drawdown monitor is what stands in front of that. Substituting `balance` for `equity`
        silently asserts that open P&L is zero, which understates the loss on exactly the number
        the breach is computed from.
        """
        if key not in acct:
            raise BrokerError(
                f"the account payload carried no `{key}`. Refusing to substitute another field: "
                f"`equity` fed position sizing, and falling back to `balance` silently asserts "
                f"that open P&L is zero while changing the size of every position (B377).",
                broker="cryptofundtrader",
            )
        return acct.get(key)

    @staticmethod
    def _side_to_direction(side: Any) -> DirectionType:
        """Map the documented spellings. **RAISE on anything else** (`B376`).

        This was `SHORT if s in {"SELL","SHORT","S"} else LONG`, so **everything unrecognised
        became a LONG on the venue that trades real money**: `''`, `None`, `0`, `1`, `ASK`, `BID`,
        `MARKET`, `LIMIT`, `SELL_LIMIT` — and a payload carrying no `side` and no `type` at all.

        **THIS IS `B336` AGAIN AND IT IS WORSE, THREE WAYS.** MT5 defaulted to SHORT; this
        defaults to LONG, which agrees with the common case and is therefore harder to notice and
        likelier to have been running. MT5's writes refuse; CFT trades. And `SELL_LIMIT -> LONG`
        is the MIRROR of MT5's defect rather than a repeat — `endswith` over-matched,
        set-membership under-matches. **Both are the absence of a mapping**, which is why the same
        fix applies unchanged: map what is known and raise on the rest, so an unknown becomes a
        QUESTION instead of a direction.

        There is no value of `DirectionType` that means *I could not tell*, so raising is the only
        option the type leaves — the same argument `get_positions` already makes for raising
        rather than returning `[]`.
        """
        if side is None or str(side).strip() == "":
            raise BrokerError(
                "the position payload carried NO side and NO type, so its direction cannot be "
                "read. Refusing to guess: this used to become a LONG.",
                broker="cryptofundtrader",
            )
        key = str(side).strip().upper()
        if key not in SIDE_DIRECTIONS:
            raise BrokerError(
                f"the venue reported side/type {side!r}, which is not one of "
                f"{tuple(SIDE_DIRECTIONS)}. Refusing to guess a direction — this used to become a "
                f"LONG, and SELL_LIMIT in particular became a LONG. The known set is inferred "
                f"rather than documented (B376); one capture of a real position settles it.",
                broker="cryptofundtrader",
            )
        return SIDE_DIRECTIONS[key]

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
        return self._account_from_payload(data if isinstance(data, dict) else {})

    def _account_from_payload(self, acct: dict) -> Account:
        """The payload -> `Account` mapping, as a NAMED method (`B377`).

        **Separated from the transport so an arm exercises THIS and not a re-implementation of
        it.** Same argument `pnl_key_present` records: its first test re-implemented the selection
        inline, and a mutation restoring the silent fallback left those arms green because they
        were exercising the copy. A mapping only reachable through an HTTP round-trip gets tested
        by a hand-built stand-in, which is `B368`'s shape.
        """
        self._currency = acct.get("currency", self._currency)
        account_pnl_key = first_key_present(acct, ACCOUNT_PNL_KEYS)
        return Account(
            account_id=self._account_id,
            broker=self.broker_name,
            balance=float(_dec(self._require_account_key(acct, "balance"))),
            equity=float(_dec(self._require_account_key(acct, "equity"))),
            currency=self._currency,
            margin_used=float(_dec(acct.get("margin"))),
            margin_available=float(_dec(acct.get("freeMargin"))),
            open_trade_count=0,
            unrealized_pl=float(_dec(acct.get(account_pnl_key) if account_pnl_key else None)),
            unrealized_pl_source=account_pnl_key,
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
            # `B286`. THIS WAS A THREE-DEEP SILENT FALLBACK ACROSS KEYS THAT ARE NOT THE
            # SAME QUANTITY: `raw.get("profit", raw.get("netProfit", raw.get(
            # "openNetProfit")))`. `profit` is conventionally GROSS and `netProfit` is net of
            # costs, so `unrealized_pnl` held one of three different measurements with nothing
            # recording which — and no definition of the field can be honoured while a caller
            # cannot tell them apart.
            #
            # The ORDER is unchanged: this task records which key was read and decides nothing
            # about which key the venue actually sends, which is `T-0114` and is gated.
            #
            # PRESENCE, not `.get` with a default: the key may be absent while a value still
            # appears, and a provenance taken from a defaulted read would name a key the
            # payload never carried.
            pnl_source = pnl_key_present(raw)
            unrealized_pnl = _dec(raw.get(pnl_source) if pnl_source else None)
            # `B377`. `volume`/`lots`/`size` are not interchangeable units — `B302`'s ambiguity
            # acquired at the venue boundary — so the key is chosen by PRESENCE and recorded,
            # never by a silent three-deep fallback.
            volume_key = first_key_present(raw, VOLUME_KEYS)
            volume = _dec(raw.get(volume_key) if volume_key else None)
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
                    pnl_source=pnl_source,
                    # `T-0105`. The venue's own convention — and this is a POINTER, not a
                    # definition: it says WHOSE convention the fields follow, while
                    # `pnl_source` says WHICH key the P&L came from. Neither replaces the
                    # other.
                    produced_by=self.broker_name,
                    # NOT REPORTED by this venue's open-positions payload, so `None` and not
                    # `0` — `0` would claim it charged nothing (`B215`).
                    swap=None,
                    commission=None,
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

    async def _closable_positions(self) -> list[tuple[str, str]]:
        """`(id, pair)` per open position, read WITHOUT the numeric or direction coercions.

        **`B349`, ported the moment `B376` made it live here.** This member needs an id and a
        symbol — two strings the venue sends as strings — and it used to obtain them by building
        a full `Position` per row. `B376` makes `_side_to_direction` RAISE on an unrecognised
        side, so without this split **one position with a side we cannot read would abort the
        enumeration and leave every position open** — and on a kill switch, refusing to act IS
        leaving every position open.

        The pairing is the point: `B376`'s raise is right, and it is only safe because the close
        path no longer depends on the coercion. **A position we cannot fully PARSE is not a
        position we cannot CLOSE.**
        """
        response = await self._client.get(self._api("/open-positions"))
        data = self._handle_response(response, "close_all_positions:list")
        rows: list[tuple[str, str]] = []
        for raw in self._list_field(data, "positions", "openPositions"):
            symbol = raw.get("symbol") or raw.get("instrument") or "UNKNOWN"
            rows.append((str(raw.get("id", raw.get("positionId", "")) or "").strip(),
                         from_mt_symbol(symbol)))
        return rows

    async def close_all_positions(self) -> list[dict]:
        """**Malek's ruled property, on the venue he actually trades** (`T-0132`, `B303`).

        > Every position open when the switch was pulled must be reported as CLOSED, FAILED WITH A
        > REASON, or NOT ATTEMPTED. A position in none of those three states is a bug by
        > construction.

        WHAT THIS REPLACED, AND WHY IT WAS THE MOST DANGEROUS SHAPE IN THE TREE. The loop caught
        `BrokerError` **only**, so an `httpx.ConnectTimeout` — the failure a kill switch is most
        likely to meet — aborted it, and `results` died with the frame. **Zero-closed and
        four-closed produced identical output: nothing.** The remaining positions were never
        attempted and no record said so.

        Four properties, each of which the old shape lacked:

        * **The rows are enumerated BEFORE the loop**, so *"I never got to this one"* is
          expressible. Accumulating results as you go cannot say it, and that is the state that
          matters at 3am.
        * **The report is published on the adapter BEFORE the loop runs**, so a partial record
          outlives the frame no matter how the loop ends — including a cancellation, which no
          `except Exception` catches.
        * **A per-position failure is FAILED and the loop CONTINUES**, catching `Exception` rather
          than `BrokerError`. Abandoning positions 3 and 4 because position 2 timed out would
          MANUFACTURE `NOT_ATTEMPTED` rows for positions we could have closed — worse, and it
          satisfies the ruled property just as well, which is why the property alone does not
          decide it (`B332`).
        * **The in-flight row says the close was SENT.** Written before the await, so every other
          path overwrites it and it survives only when nothing else got to. `FAILED WITH A REASON`
          is Malek's vocabulary and the reason clause is where *outcome unknown* belongs — no
          fourth disposition (`B337`).

        **Keyed by enumeration index, not by position id** (`B338`): keying on an id loses a row
        to a duplicate or an empty string as surely as to a collision, and a report holding fewer
        rows than there were positions is the ruled property failing SILENTLY.

        ONE DIFFERENCE FROM MT5 THAT IS THE VENUE AND NOT A SHORTCUT: MT5 inspects the close
        response's `stringCode` because `MetatraderTradeResponse` documents one and its success
        list includes `TRADE_RETCODE_DONE_PARTIAL` (`B367`). **CFT's close response shape is
        unobserved** — the endpoint map was reverse-engineered from the terminal by network
        capture — so there is no documented code to check and inventing one would assert a
        vocabulary this venue has never been seen to use. Recorded rather than papered over: a
        partial close here would still read as CLOSED, and that is a real gap awaiting a capture.
        """
        self._guard_trading("close_all_positions")

        report: dict[str, dict] = {}
        try:
            positions = await self._closable_positions()
        except Exception as exc:  # noqa: BLE001
            # COULD NOT ENUMERATE. Returning `[]` would say "there was nothing to close", which is
            # `B292`'s collapse on the kill switch's own path.
            raise BrokerError(
                f"CFT close_all_positions could not enumerate the open positions, so it cannot "
                f"report on them: {exc}. Nothing was attempted.", broker=self.broker_name,
            ) from exc

        for index, (pos_id, pos_pair) in enumerate(positions):
            report[f"#{index}"] = {
                "position_id": pos_id,
                "pair": pos_pair,
                "disposition": self.NOT_ATTEMPTED,
                "status": "failed",
                "reason": "the close loop never reached this position",
            }

        self.last_close_all_report = report

        try:
            for index, _row_source in enumerate(positions):
                row = report[f"#{index}"]
                position_id = row["position_id"]

                if not position_id:
                    row.update(
                        disposition=self.FAILED, status="failed",
                        reason="the venue sent no position id, so this position could not be "
                               "addressed and no close was sent for it",
                    )
                    continue

                row.update(
                    disposition=self.FAILED, status="failed", _in_flight=True,
                    reason="the close for this position was SENT and the outcome was never "
                           "observed. The position may or may not be closed and MUST be checked "
                           "at the venue.",
                )
                try:
                    result = await self.close_position(position_id)
                except Exception as exc:  # noqa: BLE001 - ANY exception, not just BrokerError
                    row.update(
                        disposition=self.FAILED, status="failed", _in_flight=False,
                        reason=f"{type(exc).__name__}: {exc}",
                    )
                    continue
                row.update(
                    disposition=self.CLOSED, status="closed", reason=None, result=result,
                    _in_flight=False,
                )
        except BaseException as exc:  # noqa: BLE001 - CancelledError is not an Exception
            for _row in report.values():
                if _row.pop("_in_flight", False):
                    _row["reason"] = (
                        f"{type(exc).__name__}: the close for this position was SENT and the "
                        f"outcome was NEVER OBSERVED — the loop did not survive to record it "
                        f"({exc}). The position may or may not be closed and MUST be checked at "
                        f"the venue."
                    )
            failure = BrokerError(
                f"CFT close_all_positions ended abnormally after "
                f"{sum(1 for r in report.values() if r['disposition'] != self.NOT_ATTEMPTED)} of "
                f"{len(report)} position(s): {type(exc).__name__}: {exc}",
                broker=self.broker_name,
            )
            failure.partial_report = list(report.values())  # type: ignore[attr-defined]
            raise failure from exc

        for row in report.values():
            row.pop("_in_flight", None)      # internal bookkeeping never reaches a caller
        return list(report.values())

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
