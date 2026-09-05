"""MetaTrader 5 through MetaApi — **PHASE 1 SKELETON, written before an account exists.**

The point of building it now: when credentials arrive, the difference between *connect-and-test*
and *build-from-scratch* is days. Everything here derives from documentation already read and
quoted (`T-0100`, `T-0104`, `B291`), so **connecting becomes a test rather than a build.**

**THE SDK IS NOT IMPORTED, AND THAT IS A CORRECTNESS REQUIREMENT RATHER THAN A CONVENIENCE.**
`metaapi_cloud_sdk` is not installed in this image. A module-level import would make this file
unimportable — and `B328` measured that the contract arm's discovery walk does
`except Exception: continue`, so **an adapter whose module cannot be imported is SILENTLY skipped
by the very arm that exists to cover it.** The adapter would ship uncovered and the suite would
stay green. So the client is INJECTED: this class talks to an object with MetaApi's method names,
which is the real SDK in production and the mock in tests.

**FLAT MODULE, DELIBERATELY.** `B267` measured that `pkgutil.iter_modules` does not recurse, and
`B328` re-measured it after the `B296` fix: a probe adapter at `broker/sub/zz_probe.py` is
invisible and the suite passes. One directory deep is not covered.

WHAT THIS FILE IS NOT
---------------------
**Every arm written against a mock passes if our reading of the documentation is wrong** — `B256`:
a differential over synthetic inputs tests the predicate and cannot test the producer, and **a mock
is a hand-built corpus for an adapter.** So every assumption is marked `ASSUMES:` in the tests, and
each marker names the item in `MT5_FIRST_CONNECTION.md` that would falsify it. When Malek runs that
checklist, **the arms resting on a falsified answer are findable by grep rather than by memory.**
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from app.core.exceptions import BrokerConnectionError, BrokerError, BrokerRateLimitError
from app.core.logging import logger
from app.db.enums import DirectionType
from app.schemas.broker import Position
from app.services.broker.base import Account, BrokerAdapter, OrderRequest

#: The document whose items settle this adapter's assumptions. Named as a constant so the join
#: between an `ASSUMES:` marker and the test that falsifies it is greppable from both ends.
CHECKLIST = "MT5_FIRST_CONNECTION.md"

#: The three values MetaApi documents for `getAccountInformation().type`. **A value outside this
#: set is not an error — it is an ANSWER WE DO NOT UNDERSTAND**, and the two must stay
#: distinguishable (`B284`, checklist 1.2).
ACCOUNT_TRADE_MODES = ("ACCOUNT_TRADE_MODE_DEMO", "ACCOUNT_TRADE_MODE_CONTEST", "ACCOUNT_TRADE_MODE_REAL")

#: The two values MetaApi documents for `MetatraderPosition.type` — verified against the installed
#: package (`T-0133`), whose model says *"Position type (one of POSITION_TYPE_BUY,
#: POSITION_TYPE_SELL)"*. **Exactly two, both strings.** `B336`: the previous mapping was
#: `endswith("BUY")`, which silently made EVERYTHING ELSE — an integer code, an absent field, a
#: typo — into a SHORT. A position's direction decides the sign of every number downstream.
POSITION_TYPES = {
    "POSITION_TYPE_BUY": DirectionType.LONG,
    "POSITION_TYPE_SELL": DirectionType.SHORT,
}

#: The SDK's rate-limit exception, MATCHED BY CLASS NAME because this module deliberately does
#: not import the SDK (see the module docstring). **A string match is weaker than an isinstance
#: check and it is what not-importing costs**, so it is named here rather than inlined, and the
#: test file carries the must-miss control that proves the name is doing the work.
SDK_RATE_LIMIT_EXCEPTION = "TooManyRequestsException"


# ======================================================================================
# Failure vocabulary — DISTINCT TYPES, because collapsing them costs a day (checklist 0.1)
# ======================================================================================


class MT5ServerNotFound(BrokerConnectionError):
    """`E_SRV_NOT_FOUND` — the broker server name does not resolve. **Fix the server name.**"""


class MT5AuthFailed(BrokerConnectionError):
    """`E_AUTH` — the server resolved and rejected the credentials. **Fix the password.**"""


class MT5BrokerUnreachable(BrokerConnectionError):
    """Connected to MetaApi, NOT connected to the broker (`B292`, checklist 1.1).

    **This is not a connection failure — it is a failure to be able to ANSWER.** MetaApi reports
    two connection states, and in this one `getPositions()` returns an empty list that means
    nothing. An empty list from a broker we cannot see is *could not ask*, not *flat*.
    """


class MT5AccountTypeUnreadable(BrokerError):
    """The account-type field could not be READ — absent, or the call failed (checklist 1.2)."""


class MT5AccountTypeUnrecognised(BrokerError):
    """The field was read and carries a value outside the three documented enums.

    **Deliberately a different type from `MT5AccountTypeUnreadable`.** Both fail closed; if they
    were one type, a new enum value from the vendor would read as an outage forever — `B215` on
    the one field the whole safety argument rests on.
    """

    def __init__(self, value: str) -> None:
        super().__init__(
            f"the venue reported account type {value!r}, which is not one of "
            f"{ACCOUNT_TRADE_MODES}. Failing closed. This is an ANSWER WE DO NOT UNDERSTAND and "
            f"not a failed read — see {CHECKLIST} item 1.2.",
            broker="mt5",
        )
        self.value = value


class MT5PositionTypeUnrecognised(BrokerError):
    """`MetatraderPosition.type` carried a value outside the two documented ones (`B336`).

    **Deliberately loud, and deliberately the same shape as `MT5AccountTypeUnrecognised`.** The
    old mapping asked `endswith("BUY")` and made everything else a SHORT, so an integer code — the
    representation native MT5 actually uses — or an absent field produced a confident wrong
    direction rather than a failure. There is no value of `DirectionType` that means *I could not
    tell*, so the only honest option the type leaves is to raise (`B215`, and `get_positions`'
    own argument for raising rather than returning `[]`).
    """

    def __init__(self, value: Any) -> None:
        super().__init__(
            f"the venue reported position type {value!r}, which is not one of "
            f"{tuple(POSITION_TYPES)}. Refusing to guess a direction: every value of the field "
            f"that is not a documented one used to become SHORT. See {CHECKLIST} item 1.1.",
            broker="mt5",
        )
        self.value = value


class MT5FieldUnreadable(BrokerError):
    """A numeric field was PRESENT and could not be parsed (`B338`).

    **Distinct from absent, which is the whole point.** `_dec` used to return `None` for both, and
    both callers then wrote `or Decimal("0")` — so a price the adapter could not parse became a
    position with an entry price of ZERO, a number every downstream P&L and risk calculation would
    happily consume. `or Decimal("0")` also cannot tell a parse failure from a legitimate zero,
    which is why the fix is not a different default.
    """

    def __init__(self, field: str, value: Any) -> None:
        super().__init__(
            f"MT5 sent {field}={value!r}, which is not a number. The venue's own model types this "
            f"field numeric, so this is a contract violation and not a missing optional value — "
            f"and a value we cannot read must never be floored to zero (B338).",
            broker="mt5",
        )
        self.field = field
        self.value = value


def _dec(value: Any, field: str) -> Decimal | None:
    """`None` stays `None`. **A field the venue did not send is not a zero** (`B215`).

    **And a field we could not READ is not a missing one** (`B338`) — that raises, because the two
    were previously the same return value and the callers floored both.
    """
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise MT5FieldUnreadable(field, value) from exc


def _required_dec(raw: dict, field: str) -> Decimal:
    """A field the venue's model marks REQUIRED. Absent is a violation, not a zero."""
    value = _dec(raw.get(field), field)
    if value is None:
        raise MT5FieldUnreadable(field, None)
    return value


class MetaTrader5Adapter(BrokerAdapter):
    """MT5 over MetaApi. Reads work; the one write refuses."""

    broker_name = "mt5"

    #: EMPTY ON PURPOSE. `B305` is ruled — MT5 trades **crypto CFDs, BTC and ETH** — and that
    #: settles the ASSET CLASS, not the venue's symbol STRINGS. MT5 brokers name the same
    #: instrument `BTCUSD`, `BTCUSD.x`, `BTCUSDm`… and no MT5 account has been observed. Filling
    #: these in from the ruling would be inventing a venue's vocabulary (checklist 1.3).
    default_pairs: list[str] = []

    def __init__(self, client: Any, *, account_id: str = "") -> None:
        """`client` is an object carrying MetaApi's method names — the SDK, or the mock.

        Injected rather than constructed here: see the module docstring. An unimportable adapter
        module is skipped in silence by the arm that covers it.
        """
        self._client = client
        self._account_id = str(account_id or "")
        self.connected: bool = False

        #: The venue's own answer to *what kind of account is this*, verbatim, or `None` if it has
        #: not been read. **EXPOSED AND NOT CONSULTED** — see `is_simulation`.
        self.venue_account_type: str | None = None

        #: How many deals the last `get_recent_trades` SKIPPED as balance entries. **A positive
        #: statement**: a silent skip and a venue with no balance entries are otherwise identical.
        self.last_trades_skipped: int = 0

        #: The most recent `close_all_positions` report, published BEFORE its loop runs so the
        #: partial record survives an abnormal exit (`B303`). `None` until the switch is pulled.
        self.last_close_all_report: dict[str, dict] | None = None

    # ------------------------------------------------------------------
    # Simulation contract
    # ------------------------------------------------------------------
    @property
    def is_simulation(self) -> bool:
        """**`False`, explicitly, and NOT derived from the venue's `type`.**

        `T-0076` is in front of Malek and unruled: `ExecutionService` asks *is real money at
        risk* — an MT5 demo says no. The reconciler asks *are these records a third party's* — an
        MT5 demo says yes. **There is no value of this flag that is correct for an MT5 demo**, so
        the mapping is his to make.

        *"Leave it unwired"* is not an available state: the member is abstract, a defined member
        returns something, and **every value it can return IS the mapping.** `True` would ship the
        unruled mapping write-enabled. All eight built members are READS and the one write refuses,
        so `False` costs nothing today and refuses by default until he rules.

        `self.venue_account_type` carries the broker-reported fact his decision needs. **It is
        exposed and this property does not read it.** That is deliberate, not an oversight.
        """
        return False

    # ------------------------------------------------------------------
    # Rate limiting — USE THE SERVER'S NUMBER (checklist 1.5)
    # ------------------------------------------------------------------
    @staticmethod
    def _rate_limited(exc: Any) -> BrokerRateLimitError:
        """Translate MetaApi's `TooManyRequests` into ours, carrying the server's own retry time.

        **The quota is denominated in CPU credits, not requests** (*"1000 cpu credits per 1s"*),
        and nothing documents what our calls cost. **So the adapter must not invent a backoff** —
        it uses `recommendedRetryTime`, and when that field is absent it says so rather than
        defaulting, because a guessed retry against an unmeasured cost model is exactly what this
        state exists to prevent.
        """
        metadata = getattr(exc, "metadata", None) or {}
        recommended = metadata.get("recommendedRetryTime")
        if recommended is None:
            return BrokerRateLimitError(
                "MetaApi rate limit hit and the response carried NO recommendedRetryTime. Not "
                "guessing a backoff: the quota is in CPU credits and our per-call cost has never "
                f"been measured ({CHECKLIST} item 1.5).",
                broker="mt5",
                retry_after_seconds=None,
            )
        return BrokerRateLimitError(
            f"MetaApi rate limit hit; the server asks for {recommended}s.",
            broker="mt5",
            retry_after_seconds=int(recommended),
        )

    # ------------------------------------------------------------------
    # 1. connect — connect() THEN wait_synchronized(). BOTH.
    # ------------------------------------------------------------------
    async def connect(self) -> None:
        """`connect()` then `wait_synchronized()`, and neither is optional (`T-0100`).

        **`connect()` returning is not "connected".** It establishes the MetaApi link;
        synchronisation with the broker terminal is a second step, and the state between them is
        real. Treating the first as sufficient is correct against any mock and wrong against a
        venue (checklist 1.1).
        """
        try:
            await self._client.connect()
            await self._client.wait_synchronized()
        except Exception as exc:  # noqa: BLE001 - classified immediately below
            raise self._classify_connect_error(exc) from exc
        self.connected = True
        logger.info("MT5 adapter connected and synchronized")

    @staticmethod
    def _classify_connect_error(exc: Exception) -> Exception:
        """`E_SRV_NOT_FOUND` and `E_AUTH` are DIFFERENT PROBLEMS with an identical symptom.

        A single generic failure collapses *"you typed the server name wrong"* into *"your
        password is wrong"* — the two a first connection actually meets (checklist 0.1).
        """
        code = getattr(exc, "code", None) or getattr(exc, "error", None) or ""
        if code == "E_SRV_NOT_FOUND":
            return MT5ServerNotFound(
                "MetaApi could not find that broker SERVER. The server name is wrong — the "
                "password was never checked.", broker="mt5",
            )
        if code == "E_AUTH":
            return MT5AuthFailed(
                "The broker server resolved and REJECTED the credentials. The server name is "
                "right; the login or password is wrong.", broker="mt5",
            )
        if type(exc).__name__ == SDK_RATE_LIMIT_EXCEPTION:
            return MetaTrader5Adapter._rate_limited(exc)
        return BrokerConnectionError(
            f"MT5 connection failed with an unclassified error: {type(exc).__name__}: {exc}. "
            f"Neither E_SRV_NOT_FOUND nor E_AUTH — so it is NOT known to be a server-name or a "
            f"password problem, and the message says so rather than guessing.", broker="mt5",
        )

    async def disconnect(self) -> None:
        """**A DOCUMENTED NO-OP, not a silent `pass`** (`B285`, checklist 1.4).

        The MetaApi SDK documents `connect()` and `wait_synchronized()` and **no close or
        disconnect**. Whether one exists is unanswered. Until checklist item 1.4 settles it this
        does nothing — and the docstring is the difference between a no-op and an omission when
        somebody later debugs a connection that will not close.
        """
        self.connected = False

    # ------------------------------------------------------------------
    # 2. get_account — and the account-type read
    # ------------------------------------------------------------------
    async def get_account(self) -> Account:
        try:
            info = await self._client.get_account_information()
        except Exception as exc:  # noqa: BLE001
            if type(exc).__name__ == SDK_RATE_LIMIT_EXCEPTION:
                raise self._rate_limited(exc) from exc
            raise BrokerError(f"MT5 get_account failed: {exc}", broker="mt5") from exc

        self.venue_account_type = self._read_account_type(info)

        return Account(
            account_id=str(info.get("login", self._account_id or "mt5")),
            broker=self.broker_name,
            balance=float(info.get("balance", 0.0)),
            equity=float(info.get("equity", 0.0)),
            currency=str(info.get("currency", "USD")),
            margin_used=float(info.get("margin", 0.0) or 0.0),
            margin_available=float(info.get("freeMargin", 0.0) or 0.0),
        )

    @staticmethod
    def _read_account_type(info: dict) -> str:
        """Read `type`, and keep *could not read* and *read something new* apart.

        **`type` means three unrelated things in this one SDK** — the deployment kind on
        `createAccount` (`'cloud'`), the trade mode here, and DIRECTION on `MetatraderPosition`.
        Same name, same vendor, and only one of them is a safety property, so this adapter never
        passes a bare `type` between layers: it is read here and stored under a name that says
        which one it is.
        """
        if "type" not in info or info.get("type") is None:
            raise MT5AccountTypeUnreadable(
                "the account-information payload carried no `type` field, so the account trade "
                f"mode could NOT BE READ. Failing closed — see {CHECKLIST} item 1.2.",
                broker="mt5",
            )
        value = str(info["type"])
        if value not in ACCOUNT_TRADE_MODES:
            raise MT5AccountTypeUnrecognised(value)
        return value

    # ------------------------------------------------------------------
    # 3. get_positions — RAISES when the broker cannot be seen
    # ------------------------------------------------------------------
    async def get_positions(self) -> list[Position]:
        """**Raises rather than returning `[]` when the broker link is down** (`B292`).

        The return type is a list, and **there is no value in a list that means "I could not
        ask."** An empty list from an unreachable broker is indistinguishable from a flat book —
        which would silently defeat any kill-switch confirmation that re-reads positions to check
        the book is empty. **Raising is the only option the type leaves.**
        """
        self._require_broker_link()
        try:
            raw_positions = await self._client.get_positions()
        except Exception as exc:  # noqa: BLE001
            if type(exc).__name__ == SDK_RATE_LIMIT_EXCEPTION:
                raise self._rate_limited(exc) from exc
            raise BrokerError(f"MT5 get_positions failed: {exc}", broker="mt5") from exc

        return [self._to_position(raw) for raw in raw_positions]

    def _require_broker_link(self) -> None:
        """Both booleans, not one (`B292`, checklist 1.1)."""
        state = getattr(self._client, "terminal_state", None)
        if state is None:
            return
        if not getattr(state, "connected", False):
            raise MT5BrokerUnreachable(
                "not connected to MetaApi, so nothing can be read.", broker="mt5",
            )
        if not getattr(state, "connected_to_broker", False):
            raise MT5BrokerUnreachable(
                "connected to MetaApi but NOT to the broker. Any position list read now would be "
                "empty because we cannot see, not because the book is flat — and the two must "
                f"never share a representation ({CHECKLIST} item 1.1).", broker="mt5",
            )

    def _to_position(self, raw: dict) -> Position:
        """Normalise one `MetatraderPosition`. **21 required of 28; 7 optional** (`B291`)."""
        # `B338`. REQUIRED ON THE VENUE'S OWN MODEL, so absent-or-unparseable RAISES rather than
        # becoming a zero. These two used to end in `or Decimal("0")`, which floored a price the
        # adapter could not read into a position worth nothing at a price of nothing.
        volume = _required_dec(raw, "volume")
        entry = _required_dec(raw, "openPrice")
        current = _dec(raw.get("currentPrice"), "currentPrice")
        profit = _dec(raw.get("profit"), "profit")
        open_time = self._parse_time(raw.get("time"))
        direction = self._read_direction(raw)
        return Position(
            id=str(raw.get("id", "")),
            pair=str(raw.get("symbol", "UNKNOWN")),
            direction=direction,
            entry_price=entry,
            current_price=current if current is not None else entry,
            unrealized_pnl=profit if profit is not None else Decimal("0"),
            # WHICH KEY, recorded (`T-0102`/`B286`). MetaApi calls it `profit` and does not say
            # whether it is gross or net of swap and commission — checklist 3.1 settles that, and
            # until it does the provenance is the only thing keeping the number interpretable.
            pnl_source="profit" if "profit" in raw else None,
            produced_by=self.broker_name,
            # OPTIONAL ON THE VENUE'S OWN MODEL, so `None` when absent and never `0` (`B215`).
            # These are the fields MT5 has and both venues we have normalised from do not.
            swap=_dec(raw.get("swap"), "swap"),
            commission=_dec(raw.get("commission"), "commission"),
            r_multiple=None,
            lot_size=volume,
            sl=_dec(raw.get("stopLoss"), "stopLoss"),
            tp=_dec(raw.get("takeProfit"), "takeProfit"),
            duration_seconds=(
                int((datetime.now(timezone.utc) - open_time).total_seconds())
                if open_time else None
            ),
            open_time=open_time or datetime.now(timezone.utc),
        )

    @staticmethod
    def _read_direction(raw: dict) -> DirectionType:
        """`B336`. THE MAPPING, EXPLICIT, AND IT FAILS CLOSED.

        This was `str(raw.get("type", "")).upper().endswith("BUY")`. Three things were wrong with
        it and only one was a spelling:

        * **It was a DEFAULT, not a mapping.** Everything that is not a string ending in `BUY`
          became a SHORT — including `0`/`1`, the integer codes native MT5 uses, and an ABSENT
          field. It never failed; it just answered.
        * **`endswith` matched more than the vocabulary.** `POSITION_TYPE_SELL_BUY_STOP` is not a
          real value, but the test of a mapping is what it does with an input it was not given.
        * **`B336` measured that no arm saw any of it:** making every position LONG passed 30 of
          30, and the word `SELL` occurred nowhere in the file.

        `T-0133` put the SDK on disk, and its model says *"Position type (one of
        POSITION_TYPE_BUY, POSITION_TYPE_SELL)"* — **two values, both strings**. So this maps those
        two and raises on anything else, exactly as `_read_account_type` does for the other
        safety-critical enum in this file. **Direction decides the sign of every number
        downstream; there is no value of `DirectionType` that means *I could not tell*.**
        """
        if "type" not in raw or raw.get("type") is None:
            raise MT5PositionTypeUnrecognised(None)
        value = raw["type"]
        if not isinstance(value, str) or value not in POSITION_TYPES:
            raise MT5PositionTypeUnrecognised(value)
        return POSITION_TYPES[value]

    @staticmethod
    def _parse_time(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        return None

    # ------------------------------------------------------------------
    # 4. get_orders
    # ------------------------------------------------------------------
    async def get_orders(self, status: str | None = None) -> list[dict]:
        """Pending orders. `status` is accepted for the contract and MetaApi has one list."""
        self._require_broker_link()
        try:
            orders = await self._client.get_orders()
        except Exception as exc:  # noqa: BLE001
            if type(exc).__name__ == SDK_RATE_LIMIT_EXCEPTION:
                raise self._rate_limited(exc) from exc
            raise BrokerError(f"MT5 get_orders failed: {exc}", broker="mt5") from exc
        return list(orders)

    # ------------------------------------------------------------------
    # 5. get_recent_trades — SKIPS balance entries AND COUNTS THE SKIPS
    # ------------------------------------------------------------------
    async def get_recent_trades(self, since: datetime | None = None) -> list[dict]:
        """`MetatraderDeal` is **6 required of 22** (`B291`), and the shortfall is the subject.

        **A deal with no `volume` or `price` is a BALANCE ENTRY** — a credit, a correction, a
        commission posting. It is not a fill. Mapping one as a trade with zeroes would put a
        fabricated fill into the record; raising a `KeyError` on it would make a normal venue
        event look like a bug.

        **So it is skipped, and the skip is COUNTED** on `last_trades_skipped`. A silent skip and
        a venue that sends no balance entries are otherwise identical, and a caller reconciling a
        deal count against a trade count needs to know which it is looking at.

        `positionId` is optional too, which breaks the join a caller would make — so a deal
        without one is also not a fill for our purposes and is skipped the same way.
        """
        since_dt = since or datetime.fromtimestamp(0, tz=timezone.utc)
        try:
            deals = await self._client.get_deals_by_time_range(
                start_time=since_dt, end_time=datetime.now(timezone.utc)
            )
        except Exception as exc:  # noqa: BLE001
            if type(exc).__name__ == SDK_RATE_LIMIT_EXCEPTION:
                raise self._rate_limited(exc) from exc
            raise BrokerError(f"MT5 get_recent_trades failed: {exc}", broker="mt5") from exc

        trades: list[dict] = []
        skipped = 0
        for deal in deals:
            if deal.get("volume") is None or deal.get("price") is None or deal.get("positionId") is None:
                skipped += 1
                continue
            trades.append({
                "id": str(deal.get("id", "")),
                "position_id": str(deal["positionId"]),
                "pair": str(deal.get("symbol", "UNKNOWN")),
                "volume": float(deal["volume"]),
                "price": float(deal["price"]),
                # REQUIRED on the venue's model — `profit number Yes` — so its absence would be a
                # contract violation rather than an optional field. `swap` and `commission` are
                # optional and stay `None` when absent.
                "profit": float(deal["profit"]) if "profit" in deal else None,
                "swap": float(deal["swap"]) if deal.get("swap") is not None else None,
                "commission": (
                    float(deal["commission"]) if deal.get("commission") is not None else None
                ),
                "time": deal.get("time"),
            })
        self.last_trades_skipped = skipped
        if skipped:
            logger.info(f"MT5 get_recent_trades skipped {skipped} balance entr(y/ies)")
        return trades

    # ------------------------------------------------------------------
    # 6. reference_price
    # ------------------------------------------------------------------
    async def reference_price(self, pair: str) -> float | None:
        """**Not abstract on the base class, and that asymmetry is a trap** (`base.py:195`).

        An adapter that forgets this silently rejects EVERY market order as *"no reference price
        available"* — which reads as a market-data fault and sends the debugger to the wrong
        subsystem. The language will not enforce it, so it is here on purpose.
        """
        try:
            quote = await self._client.get_symbol_price(symbol=pair)
        except Exception as exc:  # noqa: BLE001
            if type(exc).__name__ == SDK_RATE_LIMIT_EXCEPTION:
                raise self._rate_limited(exc) from exc
            return None
        if not quote:
            return None
        bid, ask = quote.get("bid"), quote.get("ask")
        if bid is None or ask is None:
            return float(bid if bid is not None else ask) if (bid or ask) else None
        return (float(bid) + float(ask)) / 2.0

    # ------------------------------------------------------------------
    # 7. get_symbol_specification — THE NINTH MEMBER
    # ------------------------------------------------------------------
    async def get_symbol_specification(self, symbol: str) -> dict:
        """The per-instrument bounds `units_to_lots` needs. **Deliberately NOT on `BrokerAdapter`.**

        `MT5_FIRST_CONNECTION.md` item 1.3 tells Malek to call this and capture `volume_min`,
        `volume_step`, `volume_max` and `contract_size` — and the adapter had no member for it, so
        the instruction was unactionable and the numbers he captures had nowhere to go.

        **It stays off the base class on purpose.** Exactly one venue has the concept so far, and
        **generalising a venue's concept from one venue is precisely how `oanda.py:401`'s
        hardcoded `100_000` happened** (`B302`) — a conversion factor invented in an adapter
        nobody exercises, wrong by five orders of magnitude, in the same file that writes raw
        units back into the same field.

        **The SUBJECT is Malek's to fill.** `B305` rules the asset class — crypto CFDs, BTC and
        ETH — and MT5 brokers name the same instrument differently, so the symbol strings come
        from a real account and not from this file.
        """
        try:
            spec = await self._client.get_symbol_specification(symbol=symbol)
        except Exception as exc:  # noqa: BLE001
            if type(exc).__name__ == SDK_RATE_LIMIT_EXCEPTION:
                raise self._rate_limited(exc) from exc
            raise BrokerError(
                f"MT5 get_symbol_specification({symbol!r}) failed: {exc}", broker="mt5",
            ) from exc
        return dict(spec or {})

    # ------------------------------------------------------------------
    # 8. place_order — REFUSES, and the refusal message is the deliverable
    # ------------------------------------------------------------------
    async def place_order(self, request: OrderRequest) -> dict:
        """**REFUSES. `B302`, and refusing is not deferral — it is the only correct answer today.**

        `OrderRequest.lot_size` is **units-or-lots by adapter and by direction**, measured:

            service.py:162            lot_size=round(units, 8)              the producer puts UNITS in
            cryptofundtrader.py:549   "volume": float(request.lot_size)     RAW to a live venue
            paper.py / cft_sim.py     units=request.lot_size                read as UNITS
            oanda.py:401 / :471       int(request.lot_size * 100_000)       read as LOTS, hardcoded
            oanda.py:303              lot_size=Decimal(units)               and UNITS back out

        **MetaApi's `volume` is MT5 LOTS.** Passing `request.lot_size` straight through is the
        most natural line in this file to write — the field name says it is already lots — and on
        a 100 000-contract-size instrument it is **100 000× too large.**

        *"Submit units with a docstring"* is **not** deferral: MT5 reads what arrives as lots, so
        it is a wrong decision with a note attached. And the conversion cannot be done here —
        `units_to_lots` exists and needs `volume_min`/`volume_step`/`volume_max`/`contract_size`
        from `get_symbol_specification`, **which no account has ever been asked** (checklist 1.3).

        Wrong only by being too strict, which is the safe direction for the one write in this
        phase.
        """
        raise NotImplementedError(
            "MT5 place_order REFUSES (B302). The size arriving in OrderRequest.lot_size is in "
            "UNITS — service.py:162 puts `round(units, 8)` there despite the field's name — and "
            "MetaApi's `volume` parameter is MT5 LOTS. Submitting it unconverted is wrong by the "
            "instrument's contract_size, 100000x on a standard instrument. The conversion needs "
            "volume_min / volume_step / volume_max / contract_size from get_symbol_specification, "
            f"and no MT5 account has ever been asked for them — see {CHECKLIST} item 1.3. This "
            "refusal is deliberate and is not a TODO: it is wrong only by being too strict, and "
            "the alternative is a wrong size on a live venue."
        )

    async def close_position(self, position_id: str, lot_size: float | None = None) -> dict:
        """**DEFINED, NOT IMPLEMENTED.** It dispatches on size between two MetaApi calls, so it
        carries `place_order`'s defect exactly: `lot_size` here is the same units-or-lots field
        (`B302`). A partial close needs the same conversion and the same unfetched bounds.
        """
        # `lot_size` IS READ, AND NOT TO SATISFY A SCANNER. `T-0038`'s contract is *honour it or
        # refuse loudly*, and a refusal that cannot say WHICH request it refused is the ambiguity
        # that contract exists to prevent: a caller asking for 30% and a caller asking for
        # everything would get the identical message. The two requests fail for different reasons
        # and the message says which.
        if lot_size is None:
            raise NotImplementedError(
                f"MT5 close_position({position_id!r}) refuses a WHOLE close: it is defined and "
                "not implemented in this phase. Use close_all_positions, which is built and "
                "satisfies the ruled three-state property."
            )
        raise NotImplementedError(
            f"MT5 close_position({position_id!r}, lot_size={lot_size!r}) refuses a PARTIAL "
            "close. The value is in UNITS — service.py:162 puts `round(units, 8)` in that field "
            "despite its name — and MetaApi's volume is MT5 LOTS (B302). The conversion needs "
            "volume_min / volume_step / volume_max / contract_size from get_symbol_specification, "
            "which no MT5 account has ever been asked for. This is the same unresolved conversion "
            "that makes place_order refuse."
        )

    # ------------------------------------------------------------------
    # 9. close_all_positions — MALEK'S PROPERTY, not any existing shape
    # ------------------------------------------------------------------
    #: The three dispositions Malek's ruling requires. **Every position open when the switch was
    #: pulled must be reported as exactly one of these.**
    CLOSED, FAILED, NOT_ATTEMPTED = "CLOSED", "FAILED", "NOT_ATTEMPTED"

    async def close_all_positions(self) -> list[dict]:
        """**Ruled by Malek as a PROPERTY, 2026-08-31**, and this satisfies the property:

        > *Every position that was open when the switch was pulled must be reported as CLOSED,
        > FAILED WITH A REASON, or NOT ATTEMPTED. A position in none of those three states is a
        > bug by construction.*

        **MetaApi has no close-all** — the only bulk call closes one symbol — so this iterates,
        and a loop can partially fail.

        **THE POSITIONS ARE ENUMERATED BEFORE THE LOOP AND THE REPORT IS BUILT AGAINST THAT LIST**,
        every row starting at `NOT_ATTEMPTED`. Accumulating results as you go cannot express *"I
        never got to this one"*, which is the state that matters at 3am and the state **none of
        the four shapes in this tree can express** (`B303`, `B315`).

        **THE REPORT SURVIVES AN ABNORMAL EXIT.** `B303`: CFT catches `BrokerError` only, so a
        `ConnectTimeout` aborts the loop and the results die with the frame — zero-closed and
        four-closed produce identical output. Here the rows are built first, and there are TWO
        exits that carry them: `self.last_close_all_report` is published BEFORE the loop starts,
        and an abnormal exit re-raises a `BrokerError` carrying `partial_report`. So an exception
        on position 2 of 4 still reports 4 rows to a caller that has only the exception, and to
        one that has only the adapter.

        (`T-0106` landing. This paragraph previously said the rows were *"returned from a
        `finally`"*. **There is no `finally` in this method and there never was** — the outcome
        the sentence claimed is real and the mechanism it named was not, which is `B184` inside a
        single file: the docstring and the code encoded one fact and one of them was wrong. It
        was corrected to the two exits that exist rather than adding the `finally` it described,
        because a third exit returning a report after re-raising is not reachable.)

        **`status` IS NOT THE DISPOSITION, AND THAT IS `B330`.** `kill_switch.py:71` counts any
        row whose `status` is not `error`/`failed` as CLOSED — so a `not_attempted` status would
        be reported to the operator as a **closed position**, inflating the number at exactly the
        moment it must not be inflated. So every row carries BOTH: `disposition` is the ruled
        three-state answer, and `status` maps `NOT_ATTEMPTED` onto the **safe side of a two-state
        consumer**. A position nobody reached is not closed.
        """
        report: dict[str, dict] = {}
        try:
            positions = await self.get_positions()
        except Exception as exc:  # noqa: BLE001
            # COULD NOT ENUMERATE. Returning `[]` here would say "there was nothing to close",
            # which is the `B292` collapse on the kill switch's own path.
            raise BrokerError(
                f"MT5 close_all_positions could not enumerate the open positions, so it cannot "
                f"report on them: {exc}. Nothing was attempted.", broker="mt5",
            ) from exc

        for position in positions:
            report[position.id] = {
                "position_id": position.id,
                "pair": position.pair,
                "disposition": self.NOT_ATTEMPTED,
                "status": "failed",
                "reason": "the close loop never reached this position",
            }

        # PUBLISHED BEFORE THE LOOP RUNS, so the partial record outlives the frame no matter how
        # the loop ends — including a cancellation, which no `except Exception` can catch.
        self.last_close_all_report = report

        try:
            for position in positions:
                row = report[position.id]
                try:
                    result = await self._client.close_position(position_id=position.id)
                except Exception as exc:  # noqa: BLE001 - ANY exception, not just BrokerError
                    # A PER-POSITION FAILURE IS `FAILED`, AND THE LOOP CONTINUES. `B303`'s defect
                    # is CFT catching `BrokerError` only, so a `ConnectTimeout` aborts and the
                    # remaining positions are never attempted. Abandoning positions 3 and 4
                    # because position 2 timed out would MANUFACTURE `NOT_ATTEMPTED` rows for
                    # positions we could have closed — a worse outcome that satisfies the
                    # property just as well, which is why the property alone does not decide it.
                    row.update(
                        disposition=self.FAILED, status="failed",
                        reason=f"{type(exc).__name__}: {exc}",
                    )
                    continue
                row.update(
                    disposition=self.CLOSED, status="closed", reason=None, result=result,
                )
        except BaseException as exc:  # noqa: BLE001 - CancelledError is not an Exception
            # THE LOOP ITSELF DIED. Everything still `NOT_ATTEMPTED` genuinely was not attempted,
            # and that is the state the ruling exists for. Carry the report ON the exception so a
            # caller that only has the exception still has the record.
            failure = BrokerError(
                f"MT5 close_all_positions ended abnormally after "
                f"{sum(1 for r in report.values() if r['disposition'] != self.NOT_ATTEMPTED)} of "
                f"{len(report)} position(s): {type(exc).__name__}: {exc}",
                broker="mt5",
            )
            failure.partial_report = list(report.values())  # type: ignore[attr-defined]
            raise failure from exc
        return list(report.values())

    # ------------------------------------------------------------------
    # 10. stream_prices
    # ------------------------------------------------------------------
    async def stream_prices(self, pairs: list[str], callback: Callable) -> None:
        """Poll `get_symbol_price` per pair. MetaApi pushes over its own socket in production;
        this shape is what the contract requires and what a mock can drive.
        """
        while self.connected:
            for pair in pairs:
                price = await self.reference_price(pair)
                if price is not None:
                    result = callback(pair, price)
                    if asyncio.iscoroutine(result):
                        await result
            await asyncio.sleep(1)
