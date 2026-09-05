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
import inspect
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

#: The three values MetaApi documents for `MetatraderAccount.connection_status` — read from the
#: installed package (`T-0133`): *"one of CONNECTED, DISCONNECTED, DISCONNECTED_FROM_BROKER"*.
#: **`DISCONNECTED_FROM_BROKER` is `B292`'s distinction named by the vendor** — connected to
#: MetaApi and not to the broker is not a state we inferred from two flags.
CONNECTION_STATUSES = ("CONNECTED", "DISCONNECTED", "DISCONNECTED_FROM_BROKER")

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


class MT5ConnectionStatusUnrecognised(BrokerError):
    """`connection_status` carried a value outside the three documented ones.

    **A different failure from `MT5BrokerUnreachable`, on purpose.** Unreachable is *we asked and
    the link is down*; this is *we asked and did not understand the answer*. Collapsing them would
    make a new vendor value read as a permanent outage — `B215` on the field the read guard rests
    on, and the same split `MT5AccountTypeUnrecognised` makes for the same reason.
    """

    def __init__(self, value: Any) -> None:
        super().__init__(
            f"the account reported connection status {value!r}, which is not one of "
            f"{CONNECTION_STATUSES}. Failing closed: this is an ANSWER WE DO NOT UNDERSTAND and "
            f"not a known outage — see {CHECKLIST} item 1.1.",
            broker="mt5",
        )
        self.value = value


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

    def __init__(self, account: Any, *, account_id: str = "") -> None:
        """`account` is a MetaApi **`MetatraderAccount`** — or the mock that presents its shape.

        **`T-0134` CHANGED WHAT THIS TAKES, AND `B341` IS WHY.** It used to take a single `client`
        carrying all ten members the adapter calls. **No SDK object has all ten**, and the split is
        not arbitrary:

            RpcMetaApiConnectionInstance        all six reads       NO terminal_state
            StreamingMetaApiConnectionInstance  terminal_state      NONE of the reads

        Every member is real and correctly named — that part of the reading held up — but **no
        single connection can serve both the data and the guard.** The account is the object that
        owns both: `get_rpc_connection()` for the reads, and `connection_status` for reachability.

        Injected rather than constructed here: see the module docstring. An unimportable adapter
        module is skipped in silence by the arm that covers it.
        """
        self._account = account
        self._connection: Any = None
        self._account_id = str(account_id or "")
        self.connected: bool = False

        #: When the broker link was last CHECKED, not when it was last known good. `None` until
        #: the first guarded read. Published because `connection_status` is a cached field and a
        #: reader deserves to know the age of the answer rather than infer it.
        self.last_link_check_at: datetime | None = None

        #: The venue's own answer to *what kind of account is this*, verbatim, or `None` if it has
        #: not been read. **EXPOSED AND NOT CONSULTED** — see `is_simulation`.
        self.venue_account_type: str | None = None

        #: How many deals the last `get_recent_trades` SKIPPED as balance entries. **A positive
        #: statement**: a silent skip and a venue with no balance entries are otherwise identical.
        self.last_trades_skipped: int = 0

        #: Whether the venue said it was still SYNCHRONIZING on the last `get_recent_trades`
        #: (`B356`). **A short list during synchronisation is not a short history**, and the two
        #: are otherwise identical to a caller.
        self.last_trades_synchronizing: bool = False

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
        # `B342`. **IT IS AN ABSOLUTE INSTANT, NOT A DURATION**, and this used to call `int()` on
        # it — so a real 429 raised `ValueError` from inside the translator whose only job is to
        # return a clean error. The vendor's own handler is
        # `date(metadata['recommendedRetryTime']).timestamp()` then `sleep(retry_time - now)`,
        # and the model types the field `str` / *"Recommended date to retry request."*
        retry_at = MetaTrader5Adapter._parse_time(recommended)
        if retry_at is None:
            # UNPARSEABLE. Not guessing, and not raising either: the caller asked us to translate
            # a rate limit, and failing to read one field must not turn a throttle into a crash.
            return BrokerRateLimitError(
                f"MetaApi rate limit hit and recommendedRetryTime={recommended!r} could not be "
                f"read as a time. Not guessing a backoff: the quota is in CPU credits and our "
                f"per-call cost has never been measured ({CHECKLIST} item 1.5).",
                broker="mt5",
                retry_after_seconds=None,
            )
        seconds = (retry_at - datetime.now(timezone.utc)).total_seconds()
        # A retry time already in the past means retry now, not sleep for a negative time.
        seconds = max(0, int(seconds))
        return BrokerRateLimitError(
            f"MetaApi rate limit hit; the server asks us to wait until {recommended} "
            f"({seconds}s from now).",
            broker="mt5",
            retry_after_seconds=seconds,
        )

    def _translate(self, exc: Exception, what: str) -> BrokerError:
        """One dispatch, seven call sites — `B340`, and this is the SECOND half of that fix.

        **The order was measured and it is the reverse of the intuitive one.** Consolidating first
        would have produced one site covered by two arms, and the parametrized arm would then have
        been written against the consolidated code, where it can only ever prove that ONE
        implementation works. Landing the arm first, against seven copies, proved every copy
        behaved — and only then is collapsing them safe, because the arm that would notice a
        divergence already exists and already passed against the divergent version.

        `B340` measured what the copies cost: **33 of 67 semantic mutations survived all 30 arms,
        and five of these seven sites could be INVERTED with the suite green.**

        Returns rather than raises so the caller keeps `raise ... from exc` and the original
        traceback.
        """
        if type(exc).__name__ == SDK_RATE_LIMIT_EXCEPTION:
            return self._rate_limited(exc)
        return BrokerError(f"MT5 {what} failed: {exc}", broker="mt5")

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
            # `T-0134`. The reads live on the RPC connection, which the ACCOUNT hands out
            # (`B341`). `get_rpc_connection` is not a coroutine on the SDK, so it is called and
            # awaited only if it returns something awaitable — which keeps an async mock working.
            self._account = await self._resolve_account()
            connection = self._account.get_rpc_connection()
            if inspect.isawaitable(connection):
                connection = await connection
            self._connection = connection
            await self._connection.connect()
            await self._connection.wait_synchronized()
        except Exception as exc:  # noqa: BLE001 - classified immediately below
            raise self._classify_connect_error(exc) from exc
        self.connected = True
        logger.info("MT5 adapter connected and synchronized")

    async def _resolve_account(self) -> Any:
        """The account, or the result of calling the thing that makes one.

        **`T-0134`.** `manager._make_adapter` is SYNCHRONOUS and building a `MetatraderAccount`
        is not — it needs `MetaApi(token).metatrader_account_api.get_account(id)`. Rather than
        make the whole factory async, the adapter accepts either a ready account **or a callable
        that produces one**, and resolves it here, at `connect()`, which is already the async
        boundary.

        **That also keeps the SDK import out of this module** (`B328`): the callable the factory
        builds imports `metaapi_cloud_sdk` inside itself, so this file stays importable in an
        image where the package is missing and the contract arm can still see the adapter.
        """
        account = self._account
        if callable(account) and not hasattr(account, "get_rpc_connection"):
            account = account()
            if inspect.isawaitable(account):
                account = await account
        return account

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
        connection = self._require_connection()
        try:
            info = await connection.get_account_information()
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc, "get_account") from exc

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
        return [self._to_position(raw) for raw in await self._raw_positions()]

    async def _raw_positions(self) -> list[dict]:
        """The venue's position payloads, guarded and **UNCOERCED** (`B349`).

        **This split exists so that no numeric field can disable the kill switch.**
        `close_all_positions` needs `id` and `symbol` — two strings the venue sends as strings —
        and it used to obtain them by building a full `Position`, which runs every numeric field
        through `_dec`. After `T-0106` cycle 1 those raise, so **one unparseable `swap` on one
        position aborted the enumeration and left all four open.**

        The reads that need typed numbers still get them; the read that needs two strings no
        longer pays for numbers it never looks at.
        """
        await self._require_broker_link()
        connection = self._require_connection()
        try:
            return list(await connection.get_positions())
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc, "get_positions") from exc

    def _connection_statuses(self) -> list:
        """The primary's status first, then every replica's — the vendor's own population.

        Returned as a list rather than a boolean so the caller can still say WHICH failure it is:
        collapsing to *connected / not connected* here would throw away the
        `DISCONNECTED` versus `DISCONNECTED_FROM_BROKER` distinction that `B292` exists for.
        """
        statuses = [getattr(self._account, "connection_status", None)]
        for replica in (getattr(self._account, "replicas", None) or []):
            statuses.append(getattr(replica, "connection_status", None))
        return statuses

    def _require_connection(self) -> Any:
        """The RPC connection, or a refusal saying `connect()` was never called.

        **`B341`.** The previous shape let every read run against whatever object was injected, so
        an adapter that had never connected produced venue-shaped answers from nothing.
        """
        if self._connection is None:
            raise BrokerConnectionError(
                "MT5 adapter has no connection: connect() has not been called, so there is "
                "nothing to read from. This is 'could not ask', not an empty account.",
                broker="mt5",
            )
        return self._connection

    async def _require_broker_link(self) -> None:
        """Both links, and **the answer is refreshed before it is trusted** (`B292`, `B341`).

        **`connection_status` IS A CACHED FIELD** — `self._data['connectionStatus']` on the
        account, and `self._data` changes only when `reload()` is awaited. Reading it without one
        answers `CONNECTED` from the payload fetched at connect time, **arbitrarily long after the
        broker link dropped**, which replaces a guard that never runs with a guard that lies. The
        second is worse because it looks like it works.

        **THE COST, STATED RATHER THAN HIDDEN:** one REST call per guarded read, against a quota
        denominated in **CPU credits nobody has measured** (checklist 1.5).

        **WHY NOT THE STREAMING CONNECTION, WHICH IS GENUINELY LIVE.** `TerminalState.connected`
        and `connected_to_broker` are push-updated and are exactly the pair this adapter wants —
        **the adapter's names were right all along.** But `StreamingMetaApiConnectionInstance`
        carries **none of the six reads**, so taking the guard from there means holding a second
        connection permanently alongside the RPC one **whose entire job is to answer one boolean
        pair**. That is the upgrade once 1.5 prices a call. It is not phase 1.
        """
        # `B353`. THESE TWO HALVES USED TO FAIL IN OPPOSITE DIRECTIONS, SEVEN LINES APART. A
        # missing `connection_status` raised; a missing `reload` was **skipped in silence** and
        # the cached value read anyway — so an account object that cannot refresh answered
        # `CONNECTED` from whenever it was built, which is exactly the staleness this guard was
        # rewritten to prevent. **An account we cannot refresh is one whose answer we cannot
        # date**, and that is not an answer.
        reload_ = getattr(self._account, "reload", None)
        if reload_ is None:
            raise MT5BrokerUnreachable(
                "the account cannot be refreshed — it exposes no `reload`, so `connection_status` "
                "could only be read as a CACHED value of unknown age. Failing closed: an "
                f"undateable answer is not an answer ({CHECKLIST} item 1.1).", broker="mt5",
            )
        result = reload_()
        if inspect.isawaitable(result):
            await result
        self.last_link_check_at = datetime.now(timezone.utc)

        # `B359`. **THE VENDOR COUNTS THE PRIMARY *OR ANY REPLICA*, AND THIS READ ONLY THE
        # PRIMARY.** `MetatraderAccount.wait_connected` decides it like this:
        #
        #     'CONNECTED' in [self.connection_status] + [r.connection_status for r in self.replicas]
        #
        # So on a replicated account whose primary is `DISCONNECTED_FROM_BROKER` while a replica
        # is up, this guard raised on **every read** while the SDK considered the account
        # connected. On `close_all_positions` that is a refusal to act, and **refusing to act is
        # leaving every position open** — `B349`'s consequence reached by a second route.
        #
        # A missing `replicas` is read as NONE rather than as an unknown: it is a property on
        # every real `MetatraderAccount`, so its absence means a non-replicated double, and the
        # primary alone then decides exactly as the vendor's expression does. That is not the
        # `B353` case — a missing `reload` made the answer UNDATEABLE, whereas a missing
        # `replicas` leaves the primary's answer intact.
        statuses = self._connection_statuses()
        status = statuses[0]
        if any(s == "CONNECTED" for s in statuses):
            return
        if status is None:
            # FAIL CLOSED (`B335`). This branch used to `return`, so an object without the
            # attribute was treated as reachable. An account that cannot say whether it is
            # connected has not said that it is.
            raise MT5BrokerUnreachable(
                "the account reports no connection status at all, so the broker link CANNOT BE "
                f"ESTABLISHED as up. Failing closed ({CHECKLIST} item 1.1).", broker="mt5",
            )
        for seen in statuses:
            if seen is not None and seen not in CONNECTION_STATUSES:
                # An answer we do not understand, from the primary OR a replica. Checked across
                # the whole population because a replica reporting a value we cannot read is
                # exactly as undecidable as the primary doing so.
                raise MT5ConnectionStatusUnrecognised(seen)
        if status == "DISCONNECTED":
            raise MT5BrokerUnreachable(
                "not connected to MetaApi, so nothing can be read.", broker="mt5",
            )
        if status == "DISCONNECTED_FROM_BROKER":
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
        await self._require_broker_link()
        connection = self._require_connection()
        try:
            orders = await connection.get_orders()
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc, "get_orders") from exc
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
        # `B335` SECOND HALF. Two of the three reads were guarded and this one was not, **with
        # nothing said either way** — and in a file that gives `disconnect` a docstring explaining
        # why it is a no-op, an unstated asymmetry on the property the file is built around is
        # itself the defect.
        #
        # IT IS GUARDED, AND THE ARGUMENT FOR THE OTHER CHOICE IS RECORDED RATHER THAN DISMISSED:
        # deals plausibly come from MetaApi's own history store rather than from the broker
        # terminal, in which case a read during a broker outage would succeed and guarding
        # needlessly refuses it. **That is a real possibility and it is unobserved.** What decides
        # it is which error is worse: an unguarded read during an outage returns a deal list
        # MISSING THE MOST RECENT FILLS and indistinguishable from a quiet period — `B292`'s
        # collapse on the reconciliation path. A needless refusal is loud and retryable.
        # **Checklist gap: no item reads deals with the broker link deliberately down.**
        await self._require_broker_link()
        since_dt = since or datetime.fromtimestamp(0, tz=timezone.utc)
        connection = self._require_connection()
        try:
            deals = await connection.get_deals_by_time_range(
                start_time=since_dt, end_time=datetime.now(timezone.utc)
            )
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc, "get_recent_trades") from exc

        # `B356`. **THE DEALS READ IS THE ONE WRAPPED READ, AND THE ADAPTER ITERATED THE
        # WRAPPER.** `get_deals_by_time_range` returns `MetatraderDeals`
        # — `{deals: List[MetatraderDeal], synchronizing: bool}` — while the other five reads
        # return their payload bare. Iterating the wrapper yields its KEYS, so `"deals".get(...)`
        # raised `AttributeError` **outside** the `try` and neither handler caught it.
        #
        # **Every arm was green because the mock returned a list.** That is `B334`'s class
        # arriving for real: a mock encodes the adapter's reading, and the one place the reading
        # was wrong is the one place no arm could see. Five of six bare is what a careful
        # documentation reading produces; the sixth is what only the installed package says. The
        # discoverable rule is that the **time-range** queries wrap —
        # `get_history_orders_by_time_range -> {historyOrders, synchronizing}` is the same shape.
        deals, synchronizing = self._unwrap_deals(deals)

        # `synchronizing` MEANS *"search results may be incomplete"*, and dropping it presents a
        # SHORT list as a COMPLETE one — a silent undercount on the reconciliation path (`B215`).
        # Published rather than raised: a read that refuses during synchronisation is unusable at
        # startup, and a caller reconciling a deal count against a trade count needs the flag, not
        # an exception. Same shape as `last_trades_skipped` for the same reason.
        self.last_trades_synchronizing = bool(synchronizing)
        if synchronizing:
            logger.warning(
                "MT5 get_recent_trades: the venue is still SYNCHRONIZING, so this deal list may "
                "be INCOMPLETE. Do not reconcile a count against it."
            )

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

    @staticmethod
    def _unwrap_deals(payload: Any) -> tuple[list, bool]:
        """`MetatraderDeals` in, `(deals, synchronizing)` out — and a BARE LIST is REFUSED.

        Tolerating both shapes would be the tempting choice and it is the wrong one: the pinned
        SDK declares the wrapper, so a bare list means the venue or the SDK changed underneath us,
        and **silently iterating it is how this defect existed in the first place.** Refusing
        names the shape that arrived.
        """
        if isinstance(payload, dict):
            if "deals" not in payload:
                raise BrokerError(
                    f"MT5 get_recent_trades: the deals payload is a mapping with no `deals` key "
                    f"(keys: {sorted(payload)}). MetatraderDeals is documented as "
                    f"{{deals, synchronizing}}.", broker="mt5",
                )
            return list(payload["deals"] or []), bool(payload.get("synchronizing", False))
        raise BrokerError(
            f"MT5 get_recent_trades expected a MetatraderDeals wrapper "
            f"({{deals, synchronizing}}) and got {type(payload).__name__}. Refusing to iterate it: "
            f"iterating the wrapper yields its KEYS, which is B356 — the defect this refusal "
            f"exists to make loud.", broker="mt5",
        )

    # ------------------------------------------------------------------
    # 6. reference_price
    # ------------------------------------------------------------------
    async def reference_price(self, pair: str) -> float | None:
        """**Not abstract on the base class, and that asymmetry is a trap** (`base.py:195`).

        An adapter that forgets this silently rejects EVERY market order as *"no reference price
        available"* — which reads as a market-data fault and sends the debugger to the wrong
        subsystem. The language will not enforce it, so it is here on purpose.
        """
        connection = self._require_connection()
        try:
            quote = await connection.get_symbol_price(symbol=pair)
        except Exception as exc:  # noqa: BLE001
            # ROUTED THROUGH THE ONE DISPATCH, AND STILL SWALLOWING (`B340`).
            #
            # This member kept its OWN copy of the name comparison after the other five were
            # consolidated, and every arm stayed green — **which is B340's own lesson aimed at
            # B340's own fix: a behavioural arm cannot see that one member is structurally
            # different from its five siblings.** The manager caught it by reading.
            #
            # It is not routed by simply raising what `_translate` returns, because this member
            # must NOT raise on a generic failure: it returns `float | None`, and swallowing a
            # market-data error is deliberate (`base.py:195`). So the dispatch decides WHAT the
            # failure is, in one place, and this member decides what to DO with it — which is the
            # asymmetry stated rather than left for a reader to infer from a missing branch.
            translated = self._translate(exc, f"reference_price({pair!r})")
            if isinstance(translated, BrokerRateLimitError):
                raise translated from exc
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
        connection = self._require_connection()
        try:
            spec = await connection.get_symbol_specification(symbol=symbol)
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc, f"get_symbol_specification({symbol!r})") from exc
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
            # `B349`. UNCOERCED. This used to call `get_positions()`, which builds a full
            # `Position` per row and runs every numeric field through `_dec` — so after cycle 1
            # ONE unparseable `swap`, a field this member never reads, raised and left all four
            # positions open. **On a kill switch, refusing to act is leaving every position
            # open.** The fix is not to soften the raise (that would restore the zero-price
            # defect cycle 1 correctly removed) but to stop depending on coercion we do not use:
            # `id` and `symbol` arrive as strings. **A position we cannot fully PARSE is not a
            # position we cannot CLOSE.**
            raw_positions = await self._raw_positions()
        except Exception as exc:  # noqa: BLE001
            # COULD NOT ENUMERATE. Returning `[]` here would say "there was nothing to close",
            # which is the `B292` collapse on the kill switch's own path.
            raise BrokerError(
                f"MT5 close_all_positions could not enumerate the open positions, so it cannot "
                f"report on them: {exc}. Nothing was attempted.", broker="mt5",
            ) from exc

        # KEYED BY ENUMERATION INDEX, NOT BY POSITION ID — `B338` second half. `id` is REQUIRED on
        # `MetatraderPosition`, but the report used to key on it while `_to_position` defaulted a
        # missing one to `""`, so **two positions with no id collapsed into ONE row** and a
        # position open when the switch was pulled was reported NOWHERE. The index is unique by
        # construction; the id travels inside the row where a duplicate is visible instead of
        # destructive.
        for index, raw in enumerate(raw_positions):
            position_id = str(raw.get("id", "") or "").strip()
            report[f"#{index}"] = {
                "position_id": position_id,
                "pair": str(raw.get("symbol", "UNKNOWN")),
                "disposition": self.NOT_ATTEMPTED,
                "status": "failed",
                "reason": "the close loop never reached this position",
            }

        # PUBLISHED BEFORE THE LOOP RUNS, so the partial record outlives the frame no matter how
        # the loop ends — including a cancellation, which no `except Exception` can catch.
        self.last_close_all_report = report

        try:
            for index, raw in enumerate(raw_positions):
                row = report[f"#{index}"]
                position_id = row["position_id"]

                if not position_id:
                    # UNADDRESSABLE, AND SAID SO RATHER THAN SKIPPED. Without an id there is no
                    # close to send. It is FAILED WITH A REASON — never NOT_ATTEMPTED, which
                    # would imply the loop simply had not got here yet.
                    row.update(
                        disposition=self.FAILED, status="failed",
                        reason="the venue sent no position id, so this position could not be "
                               "addressed and no close was sent for it",
                    )
                    continue

                # `B337`. THE IN-FLIGHT STATE IS WRITTEN BEFORE THE AWAIT, AND IT IS THE TRUTH.
                # The row used to keep its pre-loop default while the close was in the air, so a
                # cancellation reported the position whose close WAS SENT as
                # `NOT_ATTEMPTED / "the close loop never reached this position"` — affirmatively
                # false about our own action, at 3am. Malek ruled **FAILED WITH A REASON**, and
                # the reason clause is where *outcome unknown* belongs; that is what makes three
                # states sufficient and why no fourth disposition is added. Every path below
                # overwrites this, so it survives only when nothing else got to.
                row.update(
                    disposition=self.FAILED, status="failed", _in_flight=True,
                    reason="the close for this position was SENT and the outcome was never "
                           "observed. The position may or may not be closed and MUST be checked "
                           "at the venue.",
                )
                try:
                    result = await self._require_connection().close_position(
                        position_id=position_id
                    )
                except Exception as exc:  # noqa: BLE001 - ANY exception, not just BrokerError
                    # A PER-POSITION FAILURE IS `FAILED`, AND THE LOOP CONTINUES. `B303`'s defect
                    # is CFT catching `BrokerError` only, so a `ConnectTimeout` aborts and the
                    # remaining positions are never attempted. Abandoning positions 3 and 4
                    # because position 2 timed out would MANUFACTURE `NOT_ATTEMPTED` rows for
                    # positions we could have closed.
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
            # THE LOOP ITSELF DIED. Rows still `NOT_ATTEMPTED` genuinely were not attempted; the
            # row carrying the in-flight reason above was SENT and is not among them.
            #
            # NAME WHAT KILLED IT, IN THE ROW. The pre-await reason cannot know the exception — it
            # is written before the call — so without this the operator reads *the outcome was
            # never observed* with no way to tell a cancellation from a process death. **A reason
            # that says only what did NOT happen is `B337`'s defect one level down:** true, and
            # not informative.
            for _row in report.values():
                if _row.pop("_in_flight", False):
                    _row["reason"] = (
                        f"{type(exc).__name__}: the close for this position was SENT and the "
                        f"outcome was NEVER OBSERVED — the loop did not survive to record it "
                        f"({exc}). The position may or may not be closed and MUST be checked at "
                        f"the venue."
                    )
            failure = BrokerError(
                f"MT5 close_all_positions ended abnormally after "
                f"{sum(1 for r in report.values() if r['disposition'] != self.NOT_ATTEMPTED)} of "
                f"{len(report)} position(s): {type(exc).__name__}: {exc}",
                broker="mt5",
            )
            failure.partial_report = list(report.values())  # type: ignore[attr-defined]
            raise failure from exc
        for row in report.values():
            row.pop("_in_flight", None)      # internal bookkeeping never reaches a caller
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
