"""Alpaca — the venue Malek ruled on 2026-09-10, and the reason `T-0076` stopped being a blocker.

**WHY THIS ADAPTER CAN DO WHAT THE MT5 ONE COULD NOT.**

    TradingClient(key, secret, paper=True)      # `paper` is a CONSTRUCTOR FLAG WE PASS

`ExecutionService` refuses any adapter reporting `is_simulation=False` and `ExecMode` has no LIVE
member — both deliberately. An MT5 broker demo could not honestly answer that flag (`T-0076`,
unruled since 2026-08-24). **An Alpaca paper account can.**

⚠ **AND THE SENTENCE THAT USED TO FOLLOW WAS FALSE, IN THE SAFETY LAYER, FOR A WHOLE TASK CYCLE.**
It read: *"the flag is derived from a value we passed rather than a venue field we interpret — the
safety model is satisfied truthfully rather than bypassed."* **A value we passed is not a fact
about the world.** The SDK resolves the endpoint as

    base_url = url_override if url_override else (TRADING_PAPER if paper else TRADING_LIVE)

so `url_override` OUTRANKS `paper`, and `TradingClient(k, s, paper=True, url_override=<live>)`
points at real money while `is_simulation` returns `True` (`B389`, settled by construction). The
flag tracked an ARGUMENT that a second argument overrides.

**Worse, the parameter was in my own introspection output the whole time.**
`agents/tasks/T-0136/SDK_SHAPES.md:36` records the constructor signature INCLUDING
`url_override: Optional[str] = None`. The document built so the mock could not encode my own
reading captured the fact, and I wrote three lines about how trustworthy `paper` is without reading
it. **The instrument had no blind spot; the reader did** — which is the inverse of the usual failure
here, and it means *introspect before writing* only works if someone reads the output AGAINST the
claims it is supposed to check.

**`T-0138` removes the latency instead of documenting it:** the adapter reads where the client
actually points and REFUSES TO CONSTRUCT on a known disagreement.

**WRITTEN AFTER INTROSPECTING THE INSTALLED SDK, WHICH IS THE WHOLE DIFFERENCE FROM `T-0106`.**
That adapter was written from documentation and its mock encoded its own reading, so no arm could
fail on a fact the two shared — three defects came out of it and all three were ARRANGEMENT or
RETURN SHAPE rather than naming (`B341`, `B356`, `B359`). Nine of nine names were right. Every shape
this module relies on is recorded in `agents/tasks/T-0136/SDK_SHAPES.md` as `inspect` output.

**THE SDK IS NOT IMPORTED AT MODULE SCOPE**, for `B328`'s reason: the contract arm's discovery walk
does `except Exception: continue`, so an adapter whose module cannot be imported is skipped IN
SILENCE by the arm that exists to cover it. The client is injected, and the venue's vocabulary is
carried as the enum VALUES rather than the enum objects so that no import is needed to read it.

**FLAT MODULE, DELIBERATELY** — `B267`: `pkgutil.iter_modules` does not recurse, so an adapter one
directory deep is invisible to the discovery walk while the suite stays green.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import math
import threading
import time
import weakref
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from app.core.exceptions import BrokerError, DirectionNotSupported
from app.services.broker.symbols import same_pair
from app.core.kill_switch_state import KILL_SWITCH_RESPONSE_DEADLINE_S, refuse_if_armed
from app.core.logging import logger, redact_for_storage
from app.db.enums import DirectionType, OrderType
from app.models.decision_record import REJECTION_VENUE_ENDED_UNFILLED
from app.schemas.broker import Position
from app.services.broker.base import (
    Account, BrokerAdapter, DirectionPolicy, OrderRequest, readable_price, readable_quantity,
)

#: `PositionSide` values, read from the installed package: `['short', 'long']`.
#:
#: **A POSITION is long/short and an ORDER is buy/sell — two vocabularies for one concept**, and
#: reading one with the other's set is `B336`/`B376`'s defect with a new surface. Both were the
#: ABSENCE of a mapping; here there are two mappings and this is the position one.
POSITION_SIDES: dict[str, DirectionType] = {
    "long": DirectionType.LONG,
    "short": DirectionType.SHORT,
}

#: `OrderSide` values: `['buy', 'sell']`. Kept apart from the above ON PURPOSE.
ORDER_SIDES: dict[str, DirectionType] = {
    "buy": DirectionType.LONG,
    "sell": DirectionType.SHORT,
}

#: The document recording every shape this module reads.
SHAPES = "agents/tasks/T-0136/SDK_SHAPES.md"

#: **MALEK'S RULING, 2026-09-10, EXPRESSED AS THE VENUE FACT IT IS** (`T-0137`).
#:
#: The platform trades LONG ONLY because *Alpaca crypto is non-marginable and not shortable*.
#: The constraint is the venue's, so the SENTENCE is the venue's too, and it is defined here —
#: in the Alpaca module — rather than where it is enforced. Nothing else may compose this text:
#: `paper.py` and `cft_sim.py` import this object, and a second copy of the reason is `B184`
#: with a string, drifting from this one the first time either is edited.
#:
#: **IT IS NOT A HYPOTHESIS.** 147 shorts against 146 longs were measured in real executed
#: trades, so a long-only venue removes roughly half of what this strategy does. That is exactly
#: why the refusals must be recorded and split by direction: a run whose strategy produced no
#: shorts and a run that produced 147 and had every one refused have the same trade list, and
#: only the refusal record tells them apart.
#:
#: **The wording names the CONSTRAINT, not the refusal.** "Order rejected" would be
#: indistinguishable from a transport failure in `DecisionRecord.rejection_reason` months later.
ALPACA_CRYPTO_LONG_ONLY = DirectionPolicy(
    venue="alpaca",
    supported=frozenset({DirectionType.LONG}),
    reason=(
        "Alpaca crypto is non-marginable and not shortable, so this venue cannot take a SHORT. "
        "The platform is LONG ONLY (ruled 2026-09-10). This is a permanent venue capability, "
        "not a transient failure: the same order will be refused every time it is sent."
    ),
)


#: **THE ENDPOINTS, AS THE SDK'S OWN ENUM VALUES** — read from the installed package, not typed
#: from memory: `BaseURL.TRADING_PAPER` / `BaseURL.TRADING_LIVE`.
#:
#: Hardcoded rather than imported because **`B328`**: this module must stay importable without
#: `alpaca-py`, and `BaseURL` lives inside it. `test_t0138_endpoint_agreement` pins these against
#: the installed enum, so a venue that changes its host turns an arm red instead of turning the
#: safety flag into a lie.
PAPER_ENDPOINT = "https://paper-api.alpaca.markets"
LIVE_ENDPOINT = "https://api.alpaca.markets"


def _endpoint_of(client: Any) -> str | None:
    """WHERE THIS CLIENT ACTUALLY POINTS, or `None` if it cannot say (`B389`).

    **TWO TYPES FOR ONE CONCEPT, AND `str()` IS THE TRAP** — measured, not assumed:

    ```
    TradingClient(k, s, paper=True)                      _base_url -> BaseURL.TRADING_PAPER
    TradingClient(k, s, paper=True, url_override=<live>) _base_url -> 'https://api...'  (plain str)

    "paper-api" in BaseURL.TRADING_PAPER        -> True    the MEMBER is a string
    "paper-api" in str(BaseURL.TRADING_PAPER)   -> False   str() of it is not
    str(BaseURL.TRADING_PAPER)                  -> 'BaseURL.TRADING_PAPER'
    ```

    ⚠ **THE EXPLANATION HERE WAS WRONG BEFORE IT WAS RIGHT, AND THE WRONG VERSION WAS THE
    DANGEROUS ONE.** It said *"`BaseURL` is a plain `Enum`, not a `str, Enum`"*. **It IS a
    `str, Enum`** — `issubclass(BaseURL, str)` is `True`, the member compares equal to the URL and
    supports containment. **The actual mechanism is that `Enum.__str__` wins over `str.__str__` for
    a mixin enum**, so the member *is* a string while `str()` of it is the member NAME. The
    conclusion and the code were right for a reason that was not the real one — and a reader
    trusting the old sentence would believe the member is not string-comparable at all, which would
    send them to `.value` in places where plain comparison is fine. Corrected by the manager, who
    drove it. *The claim held, the reason was wrong, and the reason is the load-bearing half for
    whoever reads this next.*

    So a check written `"paper-api" in str(client._base_url)` is `False` for a genuine paper client
    and would refuse every legitimate construction while passing the override case it was written
    to catch. `getattr(raw, "value", raw)` handles both shapes: the enum yields its URL, a plain
    string yields itself. This is `Order.qty`'s `Union[str, float, None]` trap with a second
    surface.

    `None` means the question could not be asked — a test double, or an SDK that renamed a private
    attribute. **It is not an answer**, and the caller must not read it as one.
    """
    raw = getattr(client, "_base_url", None)
    if raw is None:
        return None
    return str(getattr(raw, "value", raw))


class AlpacaEndpointMismatch(BrokerError):
    """`is_simulation` would have disagreed with where the client is POINTED (`B389`).

    **The flag we passed is a record of our intent; the base URL is where the money is.** The SDK
    resolves them as

        base_url = url_override if url_override else (TRADING_PAPER if paper else TRADING_LIVE)

    so `url_override` outranks `paper` entirely, and `TradingClient(k, s, paper=True,
    url_override=<live>)` points at real money while `is_simulation` returns `True` — the assertion
    gating ALL execution passing on a real-money client. Settled by CONSTRUCTION, not by reading
    the constructor.

    **Raised at construction rather than reported by `is_simulation`.** A flag that quietly starts
    returning something else moves the failure away from the mistake; refusing to build the adapter
    puts it on the line that made it. Nothing downstream has to remember to check.
    """

    def __init__(self, *, paper: bool, endpoint: str) -> None:
        super().__init__(
            f"Alpaca adapter was constructed with paper={paper}, but its client points at "
            f"{endpoint!r}. `is_simulation` reports the flag, and ExecutionService refuses any "
            f"adapter reporting False — so this combination would have presented a client at "
            f"{endpoint!r} as a simulation. `url_override` takes precedence over `paper` in the "
            f"SDK (B389). Refusing to construct rather than reporting a flag that is not true.",
            broker="alpaca",
        )
        self.paper = paper
        self.endpoint = endpoint


class AlpacaBelowMinimumSize(BrokerError):
    """The size was POSITIVE but below the venue's published minimum for this asset (`T-0140`).

    **ITS OWN TYPE BECAUSE IT MAPS TO ITS OWN CODE.** `ExecutionService` catches `BrokerError` and
    files it as `VENUE_TRANSPORT` — a transient failure. A size floor is neither transient nor our
    arithmetic: `NON_POSITIVE_SIZE` is `units <= 0` on our side, and this is a well-formed order
    the venue will not take. Sharing either code would be `B375`'s confusion in a third place.

    **REFUSE, NEVER ROUND TO ZERO.** Rounding a sub-minimum size to zero would send a quantity the
    venue rejects — or worse, one our own `lot_size > 0` guard rejects after the decision was
    recorded as taken.
    """

    def __init__(self, *, symbol: str, requested: Decimal, minimum: Decimal) -> None:
        super().__init__(
            f"Alpaca will not take {requested} {symbol}: below its published minimum of "
            f"{minimum}. The minimum is roughly one dollar of notional and MOVES WITH PRICE "
            f"(measured T-0139: BTC 0.000012941, ETH 0.000397984), so this is a venue floor for "
            f"this asset at this moment, not a constant and not a defect in the size.",
            broker="alpaca",
        )
        self.symbol = symbol
        self.requested = requested
        self.minimum = minimum


#: Order statuses after which an order can no longer fill. Anything NOT here — including a status
#: nobody has named yet — is treated as still able to fill: `B427`'s resolver keeps reading it, and
#: `_order_result` reports it `terminal=False`.
#:
#: **This set decides when an order's outcome is FINAL, so the costs are asymmetric:** wrongly
#: including a resumable status reads a live order as finished — resolution stops and reports as the
#: last word an order that can still fill — while wrongly excluding a terminal one only costs reads
#: until the budget is spent and the order is reported unresolved, which halts. Hence:
#:
#:     `done_for_day` is NOT terminal — it names its own impermanence and can fill on a later day.
#:                    (Probably unreachable on crypto, which trades continuously; excluded anyway,
#:                    because it is the finished-too-early direction.)
#:     `stopped`, `suspended`, `calculated` are NOT terminal — anything that might still fill is live.
#:     `replaced` IS terminal for the object itself: the replaced order cannot fill and its successor
#:                    carries a NEW id. This path never calls `replace_order`, so no successor arises
#:                    here — do not reason "replaced is terminal, therefore done" about a
#:                    venue-initiated replacement, whose successor this set says nothing about.
#:
#: (`T-0144` R2 deleted `B429`'s venue-protection code, which also read this set to decide FLAT.)
TERMINAL_ORDER_STATUSES: frozenset[str] = frozenset(
    {"filled", "canceled", "expired", "rejected", "replaced"}
)

#: **`B427`. HOW LONG `place_order` AND THE CLOSES WAIT FOR AN ORDER TO REACH A TERMINAL STATE.**
#:
#: A TRADING PARAMETER, and MALEK'S TO SET (re-exported as `fixed_config.ORDER_RESOLUTION_BUDGET_S`, an
#: arm asserts they are the same object). It is latency before the loop proceeds: `TradingClient` is
#: synchronous, the loop ticks symbols one after another every `POLL_INTERVAL` (10s), so a slow order
#: delays every later symbol in that tick by up to this much, and each re-read blocks the event loop for
#: its round trip. 5.0 is the proposed conservative default — half a tick. **The design does not depend
#: on the value:** a different budget changes how many reads happen, never what an unresolved order does.
#:
#: **FAIL-SAFE ON EXPIRY.** An order still non-terminal when the budget is spent is reported with its
#: last venue status, which the loop classifies UNRESOLVED and HALTS on (`_on_unresolved_order`).
#:
#: **RESIDUAL, stated (manager's ruling D):** an order still `partially_filled` at expiry is reported
#: PARTIALLY_FILLED at the filled size with `terminal=False` — `T-0141`'s ruling — and **its remainder may
#: still fill, untracked (`B411`).** Resolution makes that rarer, not worse: most partials reach a terminal
#: state inside the budget. Cancelling the remainder would be a new trading action, and is not taken.
ORDER_RESOLUTION_BUDGET_S: float = 5.0

#: **`T-0144` R6'. THE MINIMUM ENTRY NOTIONAL THE ENGINE ENFORCES FOR ALPACA CRYPTO, in USD at the reference price.**
#: Measured: an OPENING order under $10 of cost basis is refused with 403 "minimal amount of order 10" (`B451`); closes
#: below it fill ($4.49, probe round 4). $11, not $10, so the mark moving between sizing and the fill does not cross it.
ALPACA_MIN_ENTRY_NOTIONAL_USD: float = 11.0

#: `T-0144` §2.6 / X-1: FILL activities are read in pages (`page_token` = the last row's id, probe round 7: 30 fills in pages
#: of 2 matched one page of 100, no duplicates). Bounded: a listing that has not ended after `FILL_ACTIVITY_MAX_PAGES` REFUSES
#: rather than settle from a partial list.
FILL_ACTIVITY_PAGE_SIZE = 100
FILL_ACTIVITY_MAX_PAGES = 50
#: R14: how many OPEN orders one cancel-first listing reads. A FULL page is not complete: an order for the symbol may be past it.
CANCEL_SCAN_ORDER_LIMIT = 200


def _venue_time(value: Any) -> datetime | None:
    """A venue timestamp as an aware `datetime` at FULL precision, or `None` (X-3c: never truncated, never a local clock)."""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    return None

#: **`T-0144` R5''. Alpaca's crypto fee per leg**, taken IN KIND on a buy (the position holds `filled × (1 − rate)`).
#: Pinned by probe round 5 on this paper account: buy 0.2500%, sell 0.2505%. The venue's schedule is volume-TIERED, so
#: this is the rate for this account's tier, not a property of the venue.
ALPACA_CRYPTO_FEE_RATE = Decimal("0.0025")

#: **`T-0144` R5''. How far `filled × (1 − fee)` may sit from the measured position delta** before the entry HALTS as
#: "another actor filled in between". Measured residues on real round-4 buys: 9.1e-10 and 8.95e-10 — the fee applied
#: in kind on the venue's 1e-9 grid — so the window is twice the larger.
OPENED_UNITS_WINDOW = Decimal("2e-9")


def venue_quantity_text(quantity: Decimal) -> str:
    """**`B457`. A venue quantity as FIXED-POINT text.** `str(Decimal)` switches to exponent form below 1e-6 even on a
    quantised value (`str(Decimal("4.88E-7"))` is `'4.88E-7'`), and `str(float)` does it below 1e-4 (`'5.8413e-05'`, the
    remainder probe round 3 measured). Refuses a non-finite or negative quantity rather than formatting it."""
    if not isinstance(quantity, Decimal) or not quantity.is_finite() or quantity < 0:
        raise ValueError(f"not a venue quantity: {quantity!r}")
    return format(quantity, "f")


def quantise_quantity_down(value: Any, increment: Decimal = Decimal("1e-9")) -> Decimal:
    """A quantity as a `Decimal` floored (ROUND_DOWN, never HALF_EVEN) to `increment` — never more than was held or asked.
    A float is read through its shortest `str`, so `0.1 * 0.7` does not bring its binary tail with it."""
    quantity = Decimal(str(value))
    if not quantity.is_finite():
        raise ValueError(f"not a quantity: {value!r}")
    return (quantity // increment) * increment

#: The read schedule, in seconds from the start of resolution. Past the last offset, reads continue at
#: the schedule's final gap for as long as the budget allows — so a larger budget adds reads rather than
#: leaving the tail unwatched, and a smaller one simply stops earlier.
ORDER_RESOLUTION_READ_OFFSETS_S: tuple[float, ...] = (0.0, 0.25, 0.75, 1.75, 3.0, 4.5)

#: **`B441`. EVERY ALPACA REQUEST HAS A TIMEOUT: 3s to connect, 10s to read.** The SDK passes none
#: (`RESTClient._one_request` calls `self._session.request(method, url, **opts)`), so a hung connection
#: blocked the event loop forever. Set ONCE, on the client's Session, by `build_trading_client` — never at
#: a call site, where one would be forgotten.
#:
#: **HOW THIS BOUNDS THE BUDGET, stated (review's X-10):** no read STARTS after the budget is spent, but a read
#: that has started cannot be interrupted — so a resolution's wall time is the budget plus ONE call's maximum:
#: 5s + 13s ≈ 18s without a 429, ~5s + ~61s with three. A resolver read started at 4.5s can run to 14.5s; one call is
#: bounded at connect + read = 13s per attempt, and a 429 adds up to three retries with the SDK's 3s sleep
#: (~61s worst case for one call). A kill switch close per position is then ~13s + resolution (budget +
#: last read, ~14.5s) ≈ 27.5s without 429s — and the closes run one after another, so ~27.5s × N for N
#: positions. Bounded, and visible rather than assumed.
#:
#: **A timeout creates AMBIGUOUS submissions** — a read timeout after the order was sent — which is why it
#: lands with `classify_submission_failure` and the client-order-id lookup, never alone.
ALPACA_HTTP_CONNECT_TIMEOUT_S: float = 3.0
ALPACA_HTTP_READ_TIMEOUT_S: float = 10.0

#: **`B440`. THE ONLY STATUS THE SDK MAY RETRY ON.** Its default is `[429, 504]` for EVERY method. A 429 was
#: refused before processing and is safe to re-send; a 504 is a gateway timeout after which the order MAY
#: exist — measured on loopback, the SDK re-POSTed the same `client_order_id` (then got 422 "must be
#: unique", filed as a transport refusal for an order that may exist) and re-sent a partial close with
#: the same `qty` (the quantity sold twice). One setting for every method, not per-method logic.
#:
#: **ASSUMPTION, UNMEASURED (review's X-14):** a 429 means the venue did NOT process the request — Alpaca's
#: documented rate-limit behaviour, not observed here. The retry still RE-SENDS and still SLEEPS INLINE
#: (the SDK's `time.sleep`, 3s, up to three times), so a 429 costs event-loop time until `B437`'s executor.
ALPACA_RETRY_STATUS_CODES: tuple[int, ...] = (429,)


def _timeout_adapter():
    """An `HTTPAdapter` whose `send` supplies the timeout whenever the caller gave none. `Session.request`
    ALWAYS passes `timeout=None` explicitly, so a `setdefault` would never fire; `None` is replaced. The
    constants are read at SEND time, where they are set."""
    from requests.adapters import HTTPAdapter

    class _AlpacaTimeoutAdapter(HTTPAdapter):
        def send(self, request, **kwargs):
            if kwargs.get("timeout") is None:
                kwargs["timeout"] = (ALPACA_HTTP_CONNECT_TIMEOUT_S, ALPACA_HTTP_READ_TIMEOUT_S)
            return super().send(request, **kwargs)

    return _AlpacaTimeoutAdapter()


def build_trading_client(api_key: str, api_secret: str, *, paper: bool, url_override: str | None = None):
    """**The ONE way this codebase builds an Alpaca `TradingClient`** (`B440`/`B441`), used by the broker
    manager and the live loop so the two cannot drift apart.

    `raw_data=False` pinned (a model, not a dict — `B356`'s trap on our side). Retries only on 429, and a
    timeout on every request. **The SDK takes neither as a constructor argument** — `TradingClient.__init__`
    does not forward them — so they are set on its private `_retry_codes` and on its `_session`. If the SDK
    no longer HAS those attributes this REFUSES rather than returning a client that would retry a POST on
    504 and hang forever; an arm reads the SDK's source so a rename fails a test before it reaches here.
    The SDK is imported inside (`B328`: this module must stay importable without it).
    """
    from alpaca.trading.client import TradingClient

    kwargs: dict = {"paper": paper, "raw_data": False}
    if url_override is not None:
        kwargs["url_override"] = url_override
    client = TradingClient(api_key, api_secret, **kwargs)
    missing = [name for name in ("_retry_codes", "_session", "_api_key") if not hasattr(client, name)]
    if missing:
        raise BrokerError(
            f"refusing to build an Alpaca client: the SDK no longer exposes {missing}, so its retry codes, "
            f"request timeout or account identity cannot be set or read — the client it would return retries a "
            f"POST on 504, can hang forever (B440, B441), or shares no order lock with another adapter on the "
            f"same account (B442). Re-derive build_trading_client against the installed SDK.",
            broker="alpaca",
        )
    client._retry_codes = list(ALPACA_RETRY_STATUS_CODES)
    adapter = _timeout_adapter()
    client._session.mount("https://", adapter)
    client._session.mount("http://", adapter)
    return client


def build_crypto_data_client(api_key: str | None, api_secret: str | None, *, url_override: str | None = None):
    """**The Alpaca crypto MARKET-DATA client** (`T-0144` R3'), built like `build_trading_client`: `raw_data=False`, retries
    only on 429 (the data API is GET-only, so a retry never repeats a write), and B441's timeout mounted on its OWN
    session. It is a different object from the trading client, and `AlpacaAdapter` runs it on a different worker.
    Refuses, as the trading builder does, when the SDK no longer exposes the attributes it sets."""
    from alpaca.data.historical.crypto import CryptoHistoricalDataClient

    kwargs: dict = {"raw_data": False}
    if url_override is not None:
        kwargs["url_override"] = url_override
    client = CryptoHistoricalDataClient(api_key, api_secret, **kwargs)
    missing = [name for name in ("_retry_codes", "_session") if not hasattr(client, name)]
    if missing:
        raise BrokerError(
            f"refusing to build an Alpaca data client: the SDK no longer exposes {missing}, so its retry codes or "
            f"request timeout cannot be set. Re-derive build_crypto_data_client against the installed SDK.",
            broker="alpaca",
        )
    client._retry_codes = list(ALPACA_RETRY_STATUS_CODES)
    adapter = _timeout_adapter()
    client._session.mount("https://", adapter)
    client._session.mount("http://", adapter)
    return client


# ---------------------------------------------------------------------------------------------------
# `B442` — ONE ORDER LOCK PER ACCOUNT
# ---------------------------------------------------------------------------------------------------
#
# The kill switch is read at the SEND (`refuse_if_armed`), which closes the window for an entry that has not
# reached `submit_order`. It cannot close the other half: an entry ALREADY SUBMITTED and still resolving can
# fill after the switch enumerates the book. So `place_order` holds its account's lock from the switch check
# through the verdict, and `close_all_positions`' second sweep takes it before re-enumerating: a switch armed
# first is seen by the entry, and an entry already in progress is seen by the switch.
#
# **PER ACCOUNT, NOT PER ADAPTER.** `broker_manager` builds an adapter per stored connection and the loop builds
# its own, so two instances can trade one account; a per-instance lock excludes nothing between them.
#
# **ONE LOCK PER ACCOUNT, NEVER ONE PER EVENT LOOP** (manager's ruling 4). An `asyncio.Lock` contended on a
# second loop raises (measured). Keying by (loop, account) would silence that by handing a second live loop a
# second lock — no mutual exclusion at all, with the arm green. In production there is ONE loop: the engine is
# `asyncio.create_task` on the app's loop, and the kill-switch route runs on that same loop. The two-loop case
# is pytest's fresh loop per test. So: a lock whose loop is CLOSED is replaced, and a DIFFERENT LIVE loop
# raises `AccountLockLoopConflict` — loudly, before anything is sent.


class AccountLockLoopConflict(RuntimeError):
    """This account's order lock belongs to a DIFFERENT, still-open event loop. No mutual exclusion is possible
    across loops, so nothing proceeds as though it had one. Not a `BrokerError`: nothing reached the venue, and
    nothing downstream may read it as a transport failure to retry."""

    def __init__(self, holder: dict | None) -> None:
        self.holder = dict(holder) if holder else None
        super().__init__(
            "this Alpaca account's order lock belongs to a DIFFERENT live event loop, so no mutual exclusion is "
            f"possible between an entry and the kill switch; refusing to proceed as if there were (holder: "
            f"{_describe_holder(self.holder)})"
        )


@dataclass
class _AccountLock:
    lock: asyncio.Lock
    loop: asyncio.AbstractEventLoop
    #: What holds it, for the kill switch's report: `{"symbol", "client_order_id", "what", "since"}`. Never the
    #: account key.
    holder: dict | None = None


_ACCOUNT_LOCKS: dict[str, _AccountLock] = {}


def account_key_of(client: Any) -> str:
    """The key an order lock is registered under: a SHA-256 of the client's API key id. **Never logged** — not
    the key, not the hash. `build_trading_client` refuses a client without `_api_key`, and production reaches
    this adapter only through the builder (`B1d`); a test double without a string key gets a lock of its own
    (`client:<id>`), which excludes nothing between two doubles — and `AlpacaAdapter` says so when built."""
    api_key = getattr(client, "_api_key", None)
    if isinstance(api_key, str) and api_key:
        return "account:" + hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    return f"client:{id(client)}"


def _account_lock(account_key: str) -> _AccountLock:
    running = asyncio.get_running_loop()
    entry = _ACCOUNT_LOCKS.get(account_key)
    if entry is None or entry.loop.is_closed():
        entry = _AccountLock(lock=asyncio.Lock(), loop=running)
        _ACCOUNT_LOCKS[account_key] = entry
    elif entry.loop is not running:
        raise AccountLockLoopConflict(entry.holder)
    return entry


@contextlib.asynccontextmanager
async def _holding_with_bounded_wait(lock: asyncio.Lock, wait_s: float):
    """The account lock with a BOUNDED wait — yields whether it was acquired — and released on EVERY exit
    (review's K2-13). `async with lock` cannot bound a wait, so this is the one place the lock is acquired by
    hand, and its release is this context manager's `finally`. `place_order` takes the lock with `async with`.

    A zero wait still acquires a FREE lock: `Lock.acquire` returns without suspending, before the timeout's
    callback can run. A cancellation from outside is not a timeout and propagates."""
    acquired = False
    try:
        try:
            async with asyncio.timeout(max(0.0, wait_s)):
                await lock.acquire()
            acquired = True
        except TimeoutError:
            pass
        yield acquired
    finally:
        if acquired:
            lock.release()


# ---------------------------------------------------------------------------------------------------
# `B437` — ONE WORKER THREAD PER ACCOUNT
# ---------------------------------------------------------------------------------------------------
#
# `TradingClient` is synchronous (`requests`), and `_call` used to invoke it INLINE: every Alpaca round trip blocked the
# event loop — the other symbols' ticks, the websocket, the API, all waited on it (measured with a ticker, B437). Now
# every call runs on ONE worker thread for its ACCOUNT (manager's ruling, option (c)):
#
#   * the loop is free while the venue answers;
#   * calls on one account are SERIALISED, across every client and adapter on it — so no `requests.Session` is ever used
#     by two threads at once (the property B437's concurrency measurement could show evidence for but not guarantee),
#     and the kill switch waits behind at most ONE in-flight call per queued job, never a whole resolution;
#   * a WRITE is SHIELDED: a cancellation that arrives while the request is on the wire waits for the answer, logs the
#     order's ids, and re-raises. A cancelled READ is abandoned at once; nothing changed at the venue.
#
# Keyed by `account_key_of` (a hash, never logged). The registry holds executors WEAKLY: an adapter holds its executor,
# so the thread lives as long as some adapter on the account does, and exits when the last one is gone (and a queued or
# running job holds it too, `B462`). B428b's market-data QUOTE client does NOT use this worker: by T-0144 R3' it is its
# own data client with its own timeout mount and its own single worker (`data:<key>`, `AlpacaAdapter._quote_worker`), so
# a held trading call never delays a quote and a quote never queues a trading call. `account_executor(key).run(...)`
# still takes any callable, not only a TradingClient method. B441's timeouts bound every call, which is what keeps one
# hung call from stalling the account for ever.

#: `B463`. **Which SDK calls CHANGE something at the venue is DERIVED, never listed.** A hand-kept list of six names left
#: seven of alpaca-py 0.44.0's thirteen writing members out, and a write under a name nobody added would have run as a READ:
#: unshielded, withdrawable while queued, abandoned while running, with nothing logged. The class of a call is read from the
#: member's SOURCE: it calls `self.post` / `self.delete` / `self.patch` / `self.put` -> WRITE; it calls only `self.get` -> READ;
#: anything else — no request verb, or a source that cannot be read — is NEITHER, and `_call` REFUSES it rather than guess.
CALL_WRITE, CALL_READ = "write", "read"
_WRITE_VERBS = frozenset({"post", "delete", "patch", "put"})

#: **`T-0144` §2.6: the ONE name registered as a read rather than derived** (manager's ruling on (ii) decision (a)). alpaca-py
#: 0.44's `TradingClient` has no account-activities member, so FILL activities are read with its `RESTClient.get`, whose
#: source calls `self._request("GET", ...)` — no verb attribute the derivation can see. The registration does not trust
#: the name: `_issues_only_http_get` requires every `self._request` call in the member's source to pass the literal "GET",
#: or the name is refused like any other. Every other name still classifies by its verbs or is refused.
REGISTERED_READ_SEAMS: dict[str, str] = {
    "get": "RESTClient.get: an HTTP GET through self._request (FILL activities, T-0144 §2.6)",
}


def _issues_only_http_get(tree: Any) -> bool:
    import ast

    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and isinstance(n.func.value, ast.Name) and n.func.value.id == "self" and n.func.attr == "_request"]
    return bool(calls) and all(c.args and isinstance(c.args[0], ast.Constant) and c.args[0].value == "GET" for c in calls)
_CALL_CLASSES: dict[tuple[type, str], str | None] = {}
_CALL_CLASSES_GUARD = threading.Lock()


def _sdk_trading_client_class() -> type:
    from alpaca.trading.client import TradingClient   # `B328`: this module stays importable without the SDK

    return TradingClient


def classify_call(client: Any, name: str) -> str | None:
    """`CALL_WRITE`, `CALL_READ`, or `None` (refuse) for `client.<name>`.

    The member is read from the client's own class when the client IS a `TradingClient` (a subclass may add or override
    a member), and from `TradingClient` otherwise — a test double's members are stand-ins for the SDK's, so they are
    classified by the SDK member they stand in for. **Introspection failure RAISES** (`BrokerError`): an unreadable source
    would otherwise yield no verbs, and "no verbs" silently becomes "not a write" (review's W-4)."""
    import ast
    import inspect
    import textwrap

    sdk = _sdk_trading_client_class()
    owner = type(client) if isinstance(client, sdk) else sdk
    key = (owner, name)
    with _CALL_CLASSES_GUARD:
        if key in _CALL_CLASSES:
            return _CALL_CLASSES[key]
    member = inspect.getattr_static(owner, name, None)
    function = getattr(member, "__func__", member)
    if not inspect.isfunction(function):
        verdict = None
    else:
        try:
            tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
        except (OSError, TypeError, SyntaxError) as exc:
            raise BrokerError(
                f"cannot classify Alpaca call {name!r}: its source on {owner.__name__} is unreadable "
                f"({type(exc).__name__}: {exc}), so whether it writes cannot be decided. Nothing was sent.",
                broker="alpaca",
            ) from exc
        verbs = {
            node.func.attr for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "self"
            and node.func.attr in _WRITE_VERBS | {"get"}
        }
        verdict = CALL_WRITE if verbs & _WRITE_VERBS else CALL_READ if verbs == {"get"} else None
        if verdict is None and name in REGISTERED_READ_SEAMS and _issues_only_http_get(tree):
            verdict = CALL_READ
    with _CALL_CLASSES_GUARD:
        _CALL_CLASSES[key] = verdict
    return verdict


class AccountExecutor:
    """ONE worker thread for one Alpaca account. `run` dispatches any callable to it."""

    #: A constant, never the key: a thread name reaches thread dumps and log records.
    THREAD_NAME_PREFIX = "alpaca-account"

    def __init__(self) -> None:
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix=self.THREAD_NAME_PREFIX)

    async def run(self, fn: Callable, args: tuple = (), kwargs: dict | None = None, *, write: bool = False,
                  call: str = "", describe: Callable[[Any], dict] | None = None,
                  guard: Callable[[], None] | None = None) -> Any:
        """`fn(*args, **kwargs)` on this account's worker, in submission order (FIFO).

        `guard`, when given, runs ON THE WORKER immediately before `fn` — the kill switch's check at the send, for a
        submission that may have waited in the queue (review's E-11). A `NotSent` it returns is returned INSTEAD of
        calling `fn`: nothing is sent.

        `write=True` SHIELDS the call, in two cases (review's E-8, E-10):
          * cancelled while still QUEUED — nothing has been sent, so the job is withdrawn and NOTHING is sent;
          * cancelled once STARTED — the request is on the wire, so it is awaited to completion (a repeated cancel does
            not cut that short; the call is bounded by B441's timeouts and the SDK's retries), an ERROR naming what
            reached the venue is logged (`describe(result)` supplies the order's ids), and `CancelledError` is re-raised.
            It never returns normally after a cancellation.
        A READ is not shielded (S-2): a cancelled read is abandoned at once, and a queued one never runs."""
        def _job(_holds_its_executor=self):
            # `B462`. **THE QUEUED JOB HOLDS ITS `AccountExecutor` UNTIL IT ENDS** (a default argument keeps a strong reference on
            # the function object, which the pool's work item holds until the call returns). The registry is WEAK: without
            # this, an abandoned READ whose caller and adapter were dropped left its executor collectable while its thread
            # still ran, and the next adapter on the account got a SECOND worker — two calls on one account at once.
            if guard is not None:
                declined = guard()
                if declined is not None:
                    return declined      # NOT sent: the marker goes back as the result, never as an exception
            return fn(*args, **(kwargs or {}))

        job = self._pool.submit(_job)
        future = asyncio.wrap_future(job)
        if not write:
            return await future
        caller_cancelled = False
        while not future.done():
            try:
                await asyncio.shield(future)
            except asyncio.CancelledError:
                if not caller_cancelled and job.cancel():
                    facts = _safe_describe(describe, None)
                    logger.warning(
                        "alpaca.write_cancelled_before_sending — this task was cancelled while the call was still "
                        "QUEUED on the account's worker; it was withdrawn and NOTHING was sent.",
                        call=call, **facts,
                    )
                    raise
                if future.cancelled():
                    raise
                caller_cancelled = True
            except BaseException:
                # THE WRITE RAISED. Without a cancellation that is the call's own failure, and it propagates as such.
                # AFTER one, it must NOT escape from here: the caller was cancelled and must see `CancelledError`, with
                # the failure logged below (review's E-9 — measured: it escaped, was classified, looked up six times,
                # and the cancelled task RETURNED normally).
                if not caller_cancelled:
                    raise
        if not caller_cancelled:
            return future.result()
        failure = future.exception()   # RETRIEVED here, so the loop never reports it as unretrieved (E-9)
        facts = _safe_describe(describe, None if failure is not None else future.result())
        logger.error(
            "alpaca.write_cancelled_in_flight — this task was cancelled while the call was ON THE WIRE; it was awaited "
            "to completion. What it did at the venue is below. Check the venue before trading this symbol again.",
            call=call, outcome="raised" if failure is not None else "returned",
            error=f"{type(failure).__name__}: {failure}" if failure is not None else None, **facts,
        )
        raise asyncio.CancelledError(f"cancelled while {call} was in flight")


def _safe_describe(describe: Callable[[Any], dict] | None, result: Any) -> dict:
    """A log line's facts, which must never fail the cancellation they accompany."""
    if describe is None:
        return {}
    try:
        return describe(result)
    except Exception as exc:  # noqa: BLE001
        return {"describe_error": f"{type(exc).__name__}: {exc}"}


_ACCOUNT_EXECUTORS: "weakref.WeakValueDictionary[str, AccountExecutor]" = weakref.WeakValueDictionary()
_ACCOUNT_EXECUTORS_GUARD = threading.Lock()


def account_executor(account_key: str) -> AccountExecutor:
    """The executor for this account — the SAME object for every client and adapter on it while any holds it."""
    with _ACCOUNT_EXECUTORS_GUARD:
        executor = _ACCOUNT_EXECUTORS.get(account_key)
        if executor is None:
            executor = AccountExecutor()
            _ACCOUNT_EXECUTORS[account_key] = executor
        return executor


def _describe_write(call: str, args: tuple, kwargs: dict) -> Callable[[Any], dict]:
    """The ids a cancelled write's log line carries: the order the venue returned, and what was sent."""
    sent_client_id = getattr(args[0], "client_order_id", None) if args and call == "submit_order" else None
    sent_target = args[0] if args and call in ("close_position", "cancel_order_by_id", "replace_order_by_id") else None

    def _describe(result: Any) -> dict:   # `result` is None when nothing came back (queued, or the call raised)
        return {
            "order_id": str(getattr(result, "id", "") or "") or None,
            # the id WE SENT is what finds the order again; the venue's echo is kept beside it
            "client_order_id": sent_client_id or getattr(result, "client_order_id", None),
            "venue_client_order_id": getattr(result, "client_order_id", None),
            "symbol": getattr(result, "symbol", None) or (sent_target if call == "close_position" else None),
            "status": str(getattr(getattr(result, "status", None), "value", getattr(result, "status", None)) or "") or None,
            "target": sent_target,
        }
    return _describe


class NotSent:
    """**A submission the WORKER declined to send**, returned — never raised — so nothing reaches `_call`'s wrapping or
    B440's classifier (manager's ruling on E-11; K2-8's trap: a `KillSwitchArmed` wrapped by `_call` becomes a
    `BrokerError`, is classified UNANSWERED, is looked up, and halts). `place_order` turns it into the refusal OUTSIDE
    the submission `try`."""

    __slots__ = ("refusal",)

    def __init__(self, refusal: BaseException) -> None:
        self.refusal = refusal


def _switch_check_at_the_send(args: tuple) -> Callable[[], "NotSent | None"]:
    """**B442's check, repeated ON THE WORKER right before `submit_order` runs** (review's E-11, manager's ruling 2).
    `place_order` checks the switch before queueing; behind one worker the send can start up to one call's C later, and
    a switch armed in that wait must still refuse it. SUBMISSION ONLY (K2-9): closes never read the switch. The flag is
    a single bool written on the event loop's thread and read here; its read is atomic."""
    order = args[0] if args else None
    pair, client_order_id = getattr(order, "symbol", None), getattr(order, "client_order_id", None)

    def _check() -> "NotSent | None":
        try:
            refuse_if_armed(venue="alpaca", pair=str(pair), client_order_id=client_order_id)
        except Exception as refusal:  # noqa: BLE001 - only KillSwitchArmed is raised; it is carried, not raised
            return NotSent(refusal)
        return None
    return _check


def _describe_holder(holder: dict | None) -> str:
    if not holder:
        return "nothing recorded"
    if holder.get("symbol") or holder.get("client_order_id"):
        return f"an entry for {holder.get('symbol')} (client_order_id {holder.get('client_order_id')})"
    return str(holder.get("what") or "unnamed")


def _client_retry_settings(client: Any) -> tuple[int, float]:
    """The retries and inter-retry sleep THIS client will actually make, read live; the SDK's own defaults for a
    client that does not carry them (a test double)."""
    try:
        from alpaca.common.constants import DEFAULT_RETRY_ATTEMPTS, DEFAULT_RETRY_WAIT_SECONDS
    except ImportError:  # `B328`: importable without the SDK — and then there is no client to retry
        DEFAULT_RETRY_ATTEMPTS, DEFAULT_RETRY_WAIT_SECONDS = 0, 0
    retry = getattr(client, "_retry", None)
    wait = getattr(client, "_retry_wait", None)
    if not isinstance(retry, int) or isinstance(retry, bool) or retry < 0:
        retry = DEFAULT_RETRY_ATTEMPTS
    if not isinstance(wait, (int, float)) or isinstance(wait, bool) or not math.isfinite(wait) or wait < 0:
        wait = DEFAULT_RETRY_WAIT_SECONDS
    return retry, float(wait)


def entry_lock_normal_hold_bound_s(client: Any) -> float:
    """**An ESTIMATE of how long an entry on the normal path holds its account's lock: 8C + B** — sweep (b)'s wait for it.
    The HARD bound is `KILL_SWITCH_RESPONSE_DEADLINE_S`, counted from the start of `close_all_positions`, and nothing
    else (manager's ruling on S-1, from review's arithmetic).

        C = one SDK call = (retry + 1) · (connect + read) + retry · retry_wait     retries and sleep read LIVE
        B = ORDER_RESOLUTION_BUDGET_S
        calls on the normal path: the position before (T-0144 R5'), submit,
        one resolver read past the budget, the position after                                             4C + B
        `B437`: each of those calls QUEUES on the account's single worker, and may start one C late      + 4C
        (`T-0144` R2 deleted B429's protection re-read, which was a fifth call on this path — review's Q-9.)

    ASSUMPTION, which is why this is an estimate and not a bound: ONE call ahead of each of the entry's calls. The queue
    is per CALL, and unlocked reads — `/api/positions`, `/api/brokers/accounts`, the loop's own reads once it trades
    Alpaca — can be ahead of any of them in NUMBERS NOTHING LIMITS.

    **RESIDUALS, stated (manager's rulings on S-1, with review's reading):**
      * The ONLY hard bound here is on SWEEP (b)'s WAIT FOR THE LOCK: `KILL_SWITCH_RESPONSE_DEADLINE_S` from the start of
        `close_all_positions`. It is NOT a bound on the close-all response. The KILL SWITCH'S OWN CLOSES — sweep (a)'s
        closes, and (b)'s re-listing and closes — also run on the account's worker and queue behind unlocked reads;
        before `B437` a close ran inline, so this cost is new.
      * The measured polling source: `frontend/src/components/dashboard/BrokerAccountsPanel.tsx:128` polls
        `/api/brokers/accounts` (-> `get_account`) every 30s PER OPEN DASHBOARD.
      * Under 429s (C = 61s), UI polling can delay an order, or a kill-switch close, by several calls.
      * MEASURED (E-S1r, doubles, 0.2s per queued read, deadline patched to 0.6s, one entry holding the lock):
        close-all took 0.80s with 0 queued reads and 1.40s with 5, the extra 0.6s being the reads its own calls waited
        behind; (b)'s lock wait was capped both times.
      * THE FIX is `B428b`'s R10 (single-flight positions/account reads), recorded in T-0144's brief; not built here.

    Read from the live module constants and the client at call time, never a literal (review's K2-14). For
    `build_trading_client`'s client at alpaca-py 0.44.0 — retry 3, retry_wait 3s, connect 3s, read 10s, budget 5s —
    C = 61s and **8C + B = 493s**; with no 429 retry C = 13s and it is 109s. Both exceed the 100s response deadline,
    which is why sweep (b)'s wait is capped by that deadline and its expiry row reports what it did not wait for.
    """
    retry, wait = _client_retry_settings(client)
    call = (retry + 1) * (ALPACA_HTTP_CONNECT_TIMEOUT_S + ALPACA_HTTP_READ_TIMEOUT_S) + retry * wait
    return 8 * call + ORDER_RESOLUTION_BUDGET_S


#: **The venue's code for "position does not exist"** — measured in probe round 3 (2026-09-14, paper account, flat):
#: `get_open_position("BTCUSD")` -> `APIError 404 {"code":40410000,"message":"position does not exist"}`. The SAME code
#: answers "order not found" on the order endpoints, so it is read ONLY on a `close_position` refusal, where the only
#: resource is the position. `B449`'s 404 (a `BTC/USD` path) carries `Not Found` and NO JSON code, and is not this.
ALPACA_POSITION_DOES_NOT_EXIST_CODE = 40410000


def _venue_says_position_does_not_exist(exc: BaseException) -> bool:
    """A 404 whose body carries `ALPACA_POSITION_DOES_NOT_EXIST_CODE` — read from the typed field, never from text.
    A body that is not JSON (`.code` json-decodes it and raises) is NOT this answer."""
    if _http_status_of(exc) != 404:
        return False
    for link in _exception_chain(exc):
        if type(link).__name__ == "APIError" and type(link).__module__.startswith("alpaca."):
            try:
                return link.code == ALPACA_POSITION_DOES_NOT_EXIST_CODE
            except Exception:  # noqa: BLE001 - an unreadable body is not the venue saying the position is gone
                return False
    return False


SUBMISSION_NOT_CREATED = "not_created"
#: The server ANSWERED this POST (a 422): a lookup's 404 then proves the order was not created.
SUBMISSION_ANSWERED = "answered"
#: SENT and NOT ANSWERED (5xx, a read timeout, a reset, anything unplaced): a 404 proves nothing — the backend
#: may still be storing the order (manager's ruling), so the lookup repeats within the budget.
SUBMISSION_UNANSWERED = "unanswered"


def _exception_chain(exc: BaseException) -> list[BaseException]:
    """`exc` and what it EXPLICITLY wraps: `__cause__` (our `_call` raises `from exc`), an exception in `args[0]`
    (requests: `ConnectionError(MaxRetryError(...))`) and urllib3's `.reason` (`MaxRetryError.reason` is the
    `NewConnectionError`). Measured on a real refused connection (review's X-8, manager). **Implicit
    `__context__` is NOT followed** — it depends on where a raise happened, not on what the library built.
    Bounded and cycle-safe."""
    out: list[BaseException] = []
    pending = [exc]
    while pending and len(out) < 16:
        current = pending.pop(0)
        if current is None or any(current is seen for seen in out):
            continue
        out.append(current)
        for nxt in (current.__cause__, getattr(current, "reason", None), current.args[0] if current.args else None):
            if isinstance(nxt, BaseException):
                pending.append(nxt)
    return out


def _http_status_of(exc: BaseException) -> int | None:
    """The HTTP status an `APIError` in the chain carries, or None. **Only `.status_code` is read**: `.code`
    and `.message` are properties that `json.loads` the body and RAISE on a non-JSON one (measured)."""
    for link in _exception_chain(exc):
        if type(link).__name__ == "APIError" and type(link).__module__.startswith("alpaca."):
            try:
                status = link.status_code
            except Exception:  # noqa: BLE001 - unreadable is "no status", which is ambiguous
                return None
            return status if isinstance(status, int) else None
    return None


def classify_submission_failure(exc: BaseException) -> str:
    """**`B440`/`B441`. Did a failed order submission CREATE an order? By exception TYPE, never by text.**

    MEASURED on loopback (`requests` 2.34, urllib3 2.7): *connection refused* and *reset after the server
    read the order* raise the SAME class, `requests.ConnectionError` — only the CHAIN separates them. So:

    ```
    NOT CREATED   a urllib3 ConnectTimeoutError in the chain — the connect phase failed; NewConnectionError
                  (refused, DNS) subclasses it, and requests.ConnectTimeout wraps it. Nothing was sent.
                  An APIError 429 — rate-limited, not processed.
                  An APIError with any other 4xx EXCEPT 422 — the server read the order and refused it.
    ANSWERED      an APIError 422. A duplicate client_order_id is a 422 and cannot be told from a validation
                  refusal without reading text, so the venue is ASKED — once, because it answered this POST.
    UNANSWERED    everything else: APIError 5xx; an APIError with no readable status; ReadTimeout; a
                  ConnectionError whose chain is a ProtocolError / RemoteDisconnected / SSLError; any
                  exception type not placed above.
    ```
    """
    try:
        from urllib3.exceptions import ConnectTimeoutError
    except Exception:  # noqa: BLE001 - without urllib3 nothing can be proven unsent
        ConnectTimeoutError = ()  # type: ignore[assignment]
    chain = _exception_chain(exc)
    # FIRST, before anything that could read as a timeout (review's X-9): `requests.ConnectTimeout` is BOTH a
    # ConnectionError and a Timeout, and it is connect-phase — nothing was sent. There is deliberately no
    # generic Timeout branch; a ReadTimeout (sent) falls through to UNANSWERED.
    if ConnectTimeoutError and any(isinstance(link, ConnectTimeoutError) for link in chain):
        return SUBMISSION_NOT_CREATED
    status = _http_status_of(exc)
    if status == 429 or (status is not None and 400 <= status < 500 and status != 422):
        return SUBMISSION_NOT_CREATED
    if status == 422:
        return SUBMISSION_ANSWERED
    return SUBMISSION_UNANSWERED


#: The largest budget accepted. A tick is `POLL_INTERVAL` (10s); a minute of blocking the loop per order is
#: already far past any trading intent, so a larger value is a units mistake (milliseconds typed as
#: seconds), not a choice.
ORDER_RESOLUTION_BUDGET_CEILING_S: float = 60.0


def resolution_budget_problem(value) -> str | None:
    """Why `value` is not a usable resolution budget, or `None` when it is (review's B-2).

    A bool is not a number (`isinstance(True, int)`); NaN compares False to everything, so it would give
    no reads that LOOK like a timeout; inf or a huge int would read forever. Each is refused by name.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return f"not a number of seconds: {value!r}"
    try:
        seconds = float(value)
    except OverflowError:
        return "too large to be a number of seconds"
    if not math.isfinite(seconds):
        return f"not finite: {value!r}"
    if seconds <= 0:
        return f"not positive: {value!r}"
    if seconds > ORDER_RESOLUTION_BUDGET_CEILING_S:
        return f"above the {ORDER_RESOLUTION_BUDGET_CEILING_S}s ceiling: {value!r}"
    return None


#: Refused at IMPORT, so a bad value set here cannot reach a running engine at all.
if resolution_budget_problem(ORDER_RESOLUTION_BUDGET_S) is not None:
    raise ValueError(f"ORDER_RESOLUTION_BUDGET_S is {resolution_budget_problem(ORDER_RESOLUTION_BUDGET_S)}")

#: The terminal statuses after which an order ENDED without completing — derived from the terminal set,
#: not a second list of statuses (`B426`): terminal, minus the one that completed (`filled`) and the one
#: whose successor carries a new id this code never follows (`replaced`).
ENDED_ORDER_STATUSES: frozenset[str] = TERMINAL_ORDER_STATUSES - {"filled", "replaced"}


class AlpacaAssetUnusable(BrokerError):
    """The venue's asset record cannot support an order decision (`T-0140`).

    Raised when the symbol comes back as a DIFFERENT market, or when a limit field is absent.
    `min_order_size`, `min_trade_increment` and `price_increment` are all `Optional[float]` on the
    SDK model — so absence is a real state, and **the alarming reading is the only safe one**:
    treating a missing minimum as zero would admit every size, and treating it as a constant is
    the defect this task exists to remove.
    """


class AlpacaFieldUnreadable(BrokerError):
    """A numeric field was PRESENT and could not be parsed (`B338`).

    **Alpaca sends numbers as STRINGS** — `Position.qty` is `str`, `Position.avg_entry_price` is
    `str` — and `Order.qty` is `Union[str, float, None]`, the same concept with two types. So
    coercion is unavoidable here, which means this distinction is needed from the first commit
    rather than retrofitted after an incident: **a value we cannot read is not a missing one, and
    neither of them is a zero.**
    """

    def __init__(self, field: str, value: Any) -> None:
        super().__init__(
            f"Alpaca sent {field}={value!r}, which is not a number. The venue types this field "
            f"numeric-as-string, so this is a contract violation rather than a missing optional — "
            f"and a value we cannot read must never be floored to zero (B338).",
            broker="alpaca",
        )
        self.field = field
        self.value = value


class AlpacaSideUnrecognised(BrokerError):
    """A position side outside the documented set (`B336`, `B376`).

    Both of those were the absence of a mapping — one over-matched with `endswith`, one
    under-matched with set membership. **There is no value of `DirectionType` that means *I could
    not tell***, so an unknown becomes a question rather than a direction.
    """

    def __init__(self, value: Any) -> None:
        super().__init__(
            f"Alpaca reported position side {value!r}, which is not one of "
            f"{tuple(POSITION_SIDES)}. Refusing to guess a direction. NOTE: an ORDER side is "
            f"buy/sell and a POSITION side is long/short — reading one with the other's "
            f"vocabulary is the same defect with a different surface.",
            broker="alpaca",
        )
        self.value = value


def _dec(value: Any, field: str) -> Decimal | None:
    """`None` stays `None`; a value we cannot READ raises (`B215`, `B338`)."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AlpacaFieldUnreadable(field, value) from exc


def _required_dec(source: Any, field: str) -> Decimal:
    """A field the venue's model marks REQUIRED. Absent is a violation, not a zero."""
    value = _dec(getattr(source, field, None), field)
    if value is None:
        raise AlpacaFieldUnreadable(field, None)
    return value


@dataclass(frozen=True)
class AssetLimits:
    """What the VENUE publishes about one asset's order sizing (`T-0139`/`B409`).

    **THE TWO SIZE FIELDS HAVE DIFFERENT NATURES AND MUST NOT BE TREATED ALIKE.** Measured:

    ```
                         BTC              ETH            nature
    min_order_size       0.000012941      0.000397984    ~$1 NOTIONAL -> MOVES WITH PRICE
    min_trade_increment  0.000000001      0.000000001    a constant
    price_increment      0.000000001      0.000000001    a constant, and NOT the quantity grid
    ```

    So the minimum is read per asset per order and the increment may be held — and the programme
    document's `0.0001` for both was wrong in both directions: **7.7x too large** for the minimum
    (refusing valid orders) and **100,000x too coarse** for the increment (quantising to a grid the
    venue does not use).

    `Decimal`, never `float`. The SDK hands these over as floats and the grid is nine decimal
    places, which is where binary floats stop being safe — `T-0097`'s `0.3 / 0.1 == 2.9999...` one
    module over. Conversion goes through `str()` so the decimal value is the one the venue sent.
    """

    symbol: str
    min_order_size: Decimal
    min_trade_increment: Decimal
    price_increment: Decimal

    def quantise_down(self, quantity: Decimal) -> Decimal:
        """Round `quantity` DOWN to the quantity grid.

        **DOWN, not nearest** (`T-0097`'s direction, already ruled for lots). Rounding up crosses
        the risk the size was computed for: `size_position` derived it from equity, risk-% and
        stop distance, and a larger quantity is a larger loss at the same stop.

        Uses `min_trade_increment` — the QUANTITY grid. `price_increment` is a different field
        that happens to hold the same value on this venue, which is exactly why swapping them is
        invisible to a realistic fixture.
        """
        if self.min_trade_increment <= 0:
            return quantity
        return (quantity // self.min_trade_increment) * self.min_trade_increment


class AlpacaAdapter(BrokerAdapter):
    """Alpaca paper trading. Reads work, and **the one write now places orders** (`T-0140`).

    `order_path_status()` is deliberately NOT overridden any more: the override existed to stop a
    run starting against an adapter that could not place an order, and `place_order`'s body
    discharged it. `test_t0138_order_path_gate` pins the pair together from the far side, so
    re-adding the override without gutting the body goes red, and vice versa.

    ⚠ **Zero orders have been placed through this class.** The sizing numbers are what the venue
    PUBLISHES about itself (`T-0139`), which beats documentation and is still not an executed-order
    measurement. Which exception Alpaca raises for an undersized order, or for a shorting attempt,
    is a could-not-ask (`D4b`) — the arms pin our mapping, not the venue's behaviour.
    """

    #: `T-0144` R6': asked by `ExecutionService` before the pre-send write; the simulators declare none.
    min_entry_notional_usd: float = ALPACA_MIN_ENTRY_NOTIONAL_USD

    broker_name = "alpaca"

    #: `T-0144` §2.1: this adapter's positions are managed by the loop's `VenueEvents` (it has no `on_tick`). The loop asks
    #: the adapter's KIND for its required members, never the venue's name.
    position_events_kind = "venue"

    #: `BTC/USD` is Alpaca's native symbol format **and already our canonical pair name** in
    #: `fixed_config.SYMBOLS`, so unlike MT5 there is no symbol vocabulary to invent (`B305`'s
    #: problem does not arise). Left empty so the caller's list is used.
    default_pairs: list[str] = []

    #: `B427`. The resolver's clock and sleep — CLASS attributes, so an adapter built without `__init__`
    #: (a test double) still has them, and any instance can override them so no arm waits for real time.
    #: `asyncio.sleep`, not `time.sleep`: a wait between re-reads must not block the event loop, even
    #: though each re-read itself does (the SDK is synchronous).
    _clock: Callable[[], float] = staticmethod(time.monotonic)
    _sleep: Callable[[float], Any] = staticmethod(asyncio.sleep)

    def __init__(self, client: Any, *, paper: bool = True) -> None:
        """`client` is an `alpaca.trading.client.TradingClient` — or the mock presenting its shape.

        **`paper` IS PASSED IN RATHER THAN READ BACK.** It is the same value handed to
        `TradingClient(..., paper=paper)`, so `is_simulation` reports what we CONSTRUCTED WITH and
        not something interpreted from an account field. Deriving it from the venue would rebuild
        `T-0076` — a flag whose meaning depends on reading a third party's record.
        """
        self._client = client
        self._paper = bool(paper)
        self.connected: bool = False
        #: `B442`: the key this adapter's ORDER LOCK is registered under — shared with every adapter on the same
        #: account. Never logged.
        self._account_key: str = account_key_of(client)
        #: `B437`: this account's worker — held here, so the thread lives while any adapter on the account does.
        self._executor: AccountExecutor = account_executor(self._account_key)
        if self._account_key.startswith("client:"):
            logger.warning(
                "alpaca.order_lock_per_client — this client carries no readable API key id, so its order lock "
                "is its OWN and excludes nothing between it and another adapter on the same account. "
                "build_trading_client refuses such a client; only a test double reaches this.",
                client_type=type(client).__name__,
            )

        #: WHERE THIS CLIENT POINTS, or `None` if it could not say (`B389`, `T-0138`).
        #:
        #: **A POSITIVE RECORD OF WHICH ANSWER `is_simulation` IS GIVING**, the same shape as
        #: `Position.pnl_source`: *derived from the endpoint* and *taken from the flag because the
        #: endpoint was unreadable* are different claims, and a reader must not have to guess
        #: which one they have.
        self.endpoint: str | None = _endpoint_of(client)
        #: Stored privately and exposed through the property below, because `B395`'s amendment
        #: made `simulation_source` a PROPERTY on `BrokerAdapter` — a data descriptor, which an
        #: instance attribute cannot shadow. The base raising is what makes absence loud; this is
        #: the cost of that, and it is the right trade.
        self._simulation_source: str = (
            "endpoint" if self.endpoint is not None else "flag (client endpoint unreadable)"
        )

        # THE ASSERTION THAT REMOVES `B389` RATHER THAN DOCUMENTING IT.
        #
        # Only a KNOWN disagreement refuses. An unreadable endpoint is a question, not a licence:
        # it is recorded above and left to `is_simulation`'s flag, because raising on it would
        # take the platform down the day the SDK renames a private attribute — trading a latent
        # risk for a certain outage. Test doubles land here too, which is why the mock in
        # `test_t0136_alpaca_adapter.py` now carries a `_base_url`.
        if self.endpoint is not None and (self.endpoint == PAPER_ENDPOINT) != self._paper:
            raise AlpacaEndpointMismatch(paper=self._paper, endpoint=self.endpoint)

        #: `T-0137`. Declared on the INSTANCE so a reader of `manager.py` sees the constraint
        #: attached to the adapter it constructs, and so `ExecutionService` can read it through
        #: the `BrokerAdapter` contract without importing this module.
        self.direction_policy: DirectionPolicy | None = ALPACA_CRYPTO_LONG_ONLY

        #: How many positions the last `get_positions` could not read, by reason. **A positive
        #: statement**: a silent skip and a venue with nothing to report are otherwise identical.
        self.last_unreadable: list[dict] = []

    # ------------------------------------------------------------------
    # Simulation contract — TRUE, and truthfully
    # ------------------------------------------------------------------
    @property
    def is_simulation(self) -> bool:
        """**The `paper` flag — which `__init__` has already checked against the real endpoint.**

        Not derived from an account field and not per-call. `T-0106`'s `is_simulation` returned a
        hardcoded `False` with a docstring explaining that no value was correct for an MT5 demo.

        **THIS USED TO SAY "the value is correct and is simply reported", AND THAT WAS THE WHOLE
        DEFECT** (`B389`). The value is our INTENT; `url_override` can point the client somewhere
        else entirely and this flag would not notice. It is trustworthy now only because
        construction refuses on a known disagreement — so read `simulation_source` to see WHICH
        answer you have: `endpoint` means the client was asked, `flag (...)` means it could not be.

        Kept as a plain flag read rather than a live lookup on purpose: this gates every execution
        and must not be able to raise or to change answer between two calls.
        """
        return self._paper

    @property
    def simulation_source(self) -> str:
        """`endpoint` when the client was ASKED where it points; the unreadable sentence when it
        could not be. See `BrokerAdapter.simulation_source` — the base raises, so every adapter
        must answer and a lost value cannot resolve to something reassuring."""
        return self._simulation_source

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------
    async def connect(self) -> None:
        """Alpaca is REST and stateless — one call proves the credentials.

        A documented act rather than a no-op: `get_account` is the cheapest call that fails on bad
        credentials, so "connected" means "the venue answered us", which is what a caller assumes
        the word means.
        """
        await self.get_account()
        self.connected = True
        logger.info("Alpaca adapter connected", paper=self._paper)

    async def disconnect(self) -> None:
        """**A DOCUMENTED NO-OP** (`B285`). `TradingClient` holds no session to close; the
        docstring is the difference between a no-op and an omission for whoever debugs a
        connection that will not close.
        """
        self.connected = False

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    @staticmethod
    def _require_model(value: Any, member: str) -> Any:
        """**The venue's answer must be a MODEL, not a dict** (`B356`, and worse than it).

        `TradingClient(..., raw_data=False)` is what we construct with, and **`_use_raw_data` is
        MUTABLE AT RUNTIME** — measured: assigning `client._use_raw_data = True` takes, and 28
        methods branch on it. So the constructor argument is a CONVENTION and anything holding the
        client can flip it. **An arm asserting the constructor call passes while the flag is
        flipped downstream**, which is what my first version of that arm did.

        There is no backend type-checker either — `tsc` gates the frontend and nothing gates Python
        — so `Union[Model, Dict[str, Any]]`, the one external fact that could catch a raw-dict
        access, is unenforced. **This check is the enforcement.**

        Without it the failure is silent and misdirected: every `getattr` on a dict returns the
        default, so a raw payload full of good data reads as a payload full of absences, and
        `get_account` would refuse for "no equity" while the equity is right there in the dict.
        """
        if isinstance(value, dict):
            raise BrokerError(
                f"Alpaca {member} returned a RAW DICT rather than a model. The client's "
                f"`_use_raw_data` is set — it is mutable at runtime and 28 SDK methods branch on "
                f"it. Every attribute read in this adapter would silently return None, so a full "
                f"payload would read as an empty one. See {SHAPES}.",
                broker="alpaca",
            )
        return value

    async def _call(self, name: str, *args, _switch_at_send: bool = True, **kwargs) -> Any:
        """One place where a venue call becomes our error (`B340`).

        `_switch_at_send=False` is passed ONLY by `place_close`: the kill switch's check at the send gates ENTRIES, and a
        close is protective (manager's ruling on (ii) decision (b); the switch never refuses its own closes, K2-9).

        `T-0106` grew seven copies of its rate-limit dispatch and five of them could be INVERTED
        with the suite green. One dispatch from the start.
        """
        method = getattr(self._client, name, None)
        if method is None:
            raise BrokerError(
                f"the Alpaca client has no {name!r}. Every member this adapter calls is on "
                f"TradingClient — see {SHAPES}.", broker=self.broker_name,
            )
        # `B463`: the call's class from the SDK member's source. NEITHER is refused here, before anything is queued.
        kind = classify_call(self._client, name)
        if kind is None:
            raise BrokerError(
                f"refusing Alpaca call {name!r}: its SDK source issues no request this adapter can classify as a write "
                f"(post/delete/patch/put) or a read (get only), so it would run unshielded by guess. Nothing was sent.",
                broker=self.broker_name,
            )
        try:
            # `B437`: on this ACCOUNT's worker thread, never inline on the event loop. Writes are shielded.
            write = kind == CALL_WRITE
            result = await self._account_worker().run(
                method, args, kwargs, write=write, call=name,
                describe=_describe_write(name, args, kwargs) if write else None,
                guard=_switch_check_at_the_send(args) if name == "submit_order" and _switch_at_send else None,
            )
            if asyncio.iscoroutine(result):   # a test double's async member: its coroutine is awaited here
                result = await result
            return result
        except BrokerError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise BrokerError(
                f"Alpaca {name} failed: {type(exc).__name__}: {exc}", broker=self.broker_name,
            ) from exc

    def _account_worker(self) -> AccountExecutor:
        executor = getattr(self, "_executor", None)
        if executor is None:   # an adapter built without __init__ (a test double); production always has one
            executor = self._executor = account_executor(self._account_key)
        return executor

    async def get_account(self) -> Account:
        acct = self._require_model(await self._call("get_account"), "get_account")
        # `B377`, SAME FIELD AND A DIFFERENT VENUE. `TradeAccount.equity` is OPTIONAL on the
        # model, and it feeds the prop-firm compliance monitor where a breach closes the account.
        # Substituting another field silently asserts that open P&L is zero.
        equity = getattr(acct, "equity", None)
        if equity is None:
            raise BrokerError(
                "the Alpaca account payload carried no `equity`. Refusing to substitute "
                "`cash` or `portfolio_value`: equity feeds the drawdown monitor and they are not "
                "the same quantity (B377).", broker=self.broker_name,
            )
        # ⚠ `balance` USED TO FALL BACK TO `equity` HERE, WHICH IS `B377` REPRODUCED BY THE PERSON
        # WHO FIXED IT. `cash`, `equity`, `buying_power` and `last_equity` are ALL Optional[str] on
        # this model — B377 four times over — and cash is not equity: substituting one silently
        # asserts that open P&L is zero, which is the exact sentence I wrote about CFT an hour ago.
        cash = _dec(getattr(acct, "cash", None), "cash")
        if cash is None:
            raise BrokerError(
                "the Alpaca account payload carried no `cash`. Refusing to substitute `equity`: "
                "they differ by exactly the open P&L, so falling back asserts that it is zero "
                "(B377). Both are Optional[str] on TradeAccount.",
                broker=self.broker_name,
            )
        return Account(
            account_id=str(getattr(acct, "account_number", "") or ""),
            broker=self.broker_name,
            balance=float(cash),
            equity=float(_dec(equity, "equity")),
            currency=str(getattr(acct, "currency", "USD") or "USD"),
            margin_used=0.0,
            margin_available=float(_dec(getattr(acct, "buying_power", None), "buying_power") or 0),
            unrealized_pl=0.0,
        )

    async def _raw_positions(self) -> list[Any]:
        """The venue's position objects, UNCOERCED (`B349`).

        `close_all_positions` needs a symbol and nothing else. Building a full `Position` per row
        runs every numeric through `_dec`, and after `B349` we know what that costs on a kill
        switch: one unreadable field on one position left every position open. **A position we
        cannot fully PARSE is not a position we cannot CLOSE.**
        """
        rows = await self._call("get_all_positions") or []
        self._require_model(rows, "get_all_positions")
        return [self._require_model(r, "get_all_positions[]") for r in rows]

    async def get_positions(self) -> list[Position]:
        return [self._to_position(raw) for raw in await self._raw_positions()]

    @staticmethod
    def _read_direction(raw: Any) -> DirectionType:
        """`PositionSide` -> ours, mapping what is documented and RAISING on the rest."""
        side = getattr(raw, "side", None)
        value = getattr(side, "value", side)
        if value is None or str(value).strip() == "":
            raise AlpacaSideUnrecognised(None)
        key = str(value).strip().lower()
        if key not in POSITION_SIDES:
            raise AlpacaSideUnrecognised(value)
        return POSITION_SIDES[key]

    @staticmethod
    def _require_mark(current: Decimal | None, raw: Any) -> Decimal:
        """A position we cannot MARK is not a position at breakeven (`B215`)."""
        if current is None:
            raise AlpacaFieldUnreadable("current_price", None)
        return current

    def _to_position(self, raw: Any) -> Position:
        entry = _required_dec(raw, "avg_entry_price")
        qty = _required_dec(raw, "qty")
        current = _dec(getattr(raw, "current_price", None), "current_price")
        reported = _dec(getattr(raw, "unrealized_pl", None), "unrealized_pl")
        direction = self._read_direction(raw)
        if reported is not None:
            pnl, pnl_source = reported, "unrealized_pl"
        else:
            # DERIVED FROM WHAT THE VENUE DID SEND, and marked as such. Sign follows the
            # direction: a SHORT gains when the mark falls.
            mark = self._require_mark(current, raw)
            move = (mark - entry) if direction is DirectionType.LONG else (entry - mark)
            pnl, pnl_source = move * qty, "derived:(mark-entry)*qty"
        return Position(
            id=str(getattr(raw, "asset_id", "") or ""),
            pair=str(getattr(raw, "symbol", "UNKNOWN")),
            direction=direction,
            entry_price=entry,
            # `B215`, AND BOTH OF THESE WERE WRONG WHEN FIRST WRITTEN — in this file, by the seat
            # that had just filed an entry about reproducing this class. Found by a mechanical
            # sweep for the SHAPE, not by remembering.
            #
            # `current_price` FELL BACK TO `entry`, which does not merely default a number — it
            # ASSERTS THE POSITION IS AT BREAKEVEN. A position we cannot mark is not a position
            # worth zero P&L; it is one we cannot price, and our DTO has no value for that, so it
            # raises. `close_all_positions` is unaffected: it reads raw rows and never builds these
            # (`B349`), so an unpriceable position can still be CLOSED.
            current_price=self._require_mark(current, raw),
            unrealized_pnl=pnl,
            # WHICH KEY, recorded (`B286`) — and now it can also say DERIVED. `unrealized_pl` is
            # Optional on the venue's model, so its absence is a fact about the payload. A zero
            # would be a fabricated number flowing into every P&L sum; the derivation uses only
            # fields the venue DID send, and the provenance says which it is.
            pnl_source=pnl_source,
            produced_by=self.broker_name,
            # SPOT CRYPTO CHARGES NO SWAP, so these are structurally absent rather than unread —
            # `B261`'s question disappears on this venue rather than being answered.
            swap=None,
            commission=None,
            r_multiple=None,
            lot_size=qty,
            sl=None,
            tp=None,
            duration_seconds=None,
            open_time=datetime.now(timezone.utc),
        )

    async def get_orders(self, status: str | None = None) -> list[dict]:
        """Orders, with `status` in the ENGINE's spelling and the venue's own beside it (`B427` addendum).

        **TWO DEFECTS, both fixed here.** The `status` argument was DEAD — the SDK was called with no
        filter, so a caller asking for open orders got the server default and could not know it. It is now
        honoured, or refused loudly when the venue's filter cannot express it (`open`, `closed`, `all`).
        And each order's `status` was the enum's lowercase VALUE (`"filled"`) while every other method of
        this adapter returns the uppercase mapping (`"FILLED"`) — one key, two vocabularies, so a caller
        comparing against the loop's sets silently got False. `status` now comes from `_order_result`, the
        one mapping; the raw value is `venue_status`. Unpaginated still: the server's default page size
        applies, and a caller that must see everything should use a bounded query of its own.
        """
        if status is None:
            orders = await self._call("get_orders") or []
        else:
            from alpaca.trading.enums import QueryOrderStatus
            from alpaca.trading.requests import GetOrdersRequest

            try:
                query = QueryOrderStatus(str(status).lower())
            except ValueError:
                raise BrokerError(
                    f"get_orders cannot filter by {status!r}: the venue's order filter takes only "
                    f"{sorted(q.value for q in QueryOrderStatus)}. Refusing rather than returning "
                    f"orders the caller did not ask for.", broker=self.broker_name,
                ) from None
            orders = await self._call("get_orders", GetOrdersRequest(status=query)) or []
        rows = []
        for o in orders:
            mapped = self._order_result(o)
            rows.append({
                "id": str(getattr(o, "id", "")),
                "pair": str(getattr(o, "symbol", "") or ""),
                "status": mapped["status"],
                "venue_status": mapped["venue_status"],
                "filled_units": mapped["filled_units"],
                "side": str(getattr(getattr(o, "side", None), "value", getattr(o, "side", ""))),
                "qty": str(getattr(o, "qty", "") or ""),
            })
        return rows

    async def get_recent_trades(self, since: datetime | None = None) -> list[dict]:
        """Filled orders are this venue's trade record — there is no separate deals endpoint.

        **`get_orders` returns ORDERS, and only a FILLED one is a trade.** Mapping every order as a
        trade would put unfilled intent into the record, which is `B365`'s shape: a predicate
        ranging over the wrong population.
        """
        orders = await self._call("get_orders") or []
        trades: list[dict] = []
        for o in orders:
            state = str(getattr(getattr(o, "status", None), "value", getattr(o, "status", "")))
            if state.lower() != "filled":
                continue
            trades.append({
                "id": str(getattr(o, "id", "")),
                "pair": str(getattr(o, "symbol", "") or ""),
                "side": str(getattr(getattr(o, "side", None), "value", getattr(o, "side", ""))),
                "qty": _dec(getattr(o, "filled_qty", None), "filled_qty"),
                "price": _dec(getattr(o, "filled_avg_price", None), "filled_avg_price"),
            })
        return trades

    async def reference_price(self, pair: str) -> float | None:
        """**Not abstract on the base class, and that asymmetry is a trap** (`base.py:195`).

        An adapter that forgets this rejects EVERY market order as *"no reference price
        available"*, which reads as a market-data fault and sends the debugger to the wrong
        subsystem.
        """
        try:
            position = await self._call("get_open_position", pair)
        except BrokerError:
            return None
        price = _dec(getattr(position, "current_price", None), "current_price")
        return float(price) if price is not None else None

    # ------------------------------------------------------------------
    # The one write — REFUSES, and refuses EVERY direction in this phase
    # ------------------------------------------------------------------
    async def asset_limits(self, symbol: str) -> AssetLimits:
        """Read this ASSET's sizing limits from the venue, now, for this order.

        **PER ASSET AND PER ORDER, and both halves are load-bearing.**

        *Per asset*, because BTC's minimum (`0.000012941`) and ETH's (`0.000397984`) differ by
        **31x** — one asset's limits applied to every symbol would pass any BTC-only check and
        silently refuse valid ETH orders, or admit sub-minimum ones.

        *Per order*, because the minimum is roughly one dollar of notional and therefore moves
        with price: at BTC 150,000 it is ~`0.0000067`, at 40,000 ~`0.000025`. **Any value we hold
        goes stale without failing** — it simply refuses or admits the wrong orders as price
        drifts, which is `B405`'s shape with a number guaranteed to rot rather than merely able to.
        **A cache with no expiry is that pinned constant with extra steps**, so there is no cache:
        one `get_asset` per order, and an arm asserts that count.

        **THE SYMBOL IS COMPARED EXACTLY.** The venue also lists `BTC/USDC`, `BTC/USDT` and
        `ETH/BTC`; review's own probe used `startswith("BTC")`, which would have caught `BTC/USDT`
        and missed `ETH/BTC`. A loose match here does not fail — it prices the wrong market.
        """
        return self._limits_of(await self._fetch_asset(symbol), symbol)

    async def _fetch_asset(self, symbol: str):
        """The venue's record for `symbol`, read once, with the symbol checked EXACTLY.

        Separate from `_limits_of` because `place_order` needs two different answers out of one
        read — `shortable` and the sizing limits. Asking twice would double every order's venue
        traffic and, worse, let the two answers come from *different* reads of a record that moves
        with price.
        """
        asset = self._require_model(await self._call("get_asset", symbol), "get_asset")

        got = getattr(asset, "symbol", None)
        if got != symbol:
            raise AlpacaAssetUnusable(
                f"Asked Alpaca for {symbol!r} and it answered for {got!r}. The venue lists "
                f"BTC/USD, BTC/USDC, BTC/USDT, ETH/USD, ETH/USDC, ETH/USDT and ETH/BTC, so a "
                f"near-match is a DIFFERENT MARKET rather than a formatting difference.",
                broker="alpaca",
            )

        return asset

    @staticmethod
    def _limits_of(asset, symbol: str) -> "AssetLimits":
        """This asset's three sizing numbers, as `Decimal`, refusing any the venue did not give."""
        limits = {}
        for field in ("min_order_size", "min_trade_increment", "price_increment"):
            raw = getattr(asset, field, None)
            if raw is None:
                # `Optional[float]` on the model, so absence is a real state. The alarming
                # reading is the only safe one: a missing minimum treated as zero admits every
                # size, and treated as a constant rebuilds the defect this task removes.
                raise AlpacaAssetUnusable(
                    f"Alpaca reported no {field} for {symbol}. Refusing to size an order against "
                    f"an absent limit — a missing minimum is not a minimum of zero.",
                    broker="alpaca",
                )
            # `str()` first: the SDK hands floats, the grid is 9 dp, and `Decimal(0.000012941)`
            # carries the binary error that `Decimal("0.000012941")` does not.
            limits[field] = Decimal(str(raw))

        return AssetLimits(symbol=symbol, **limits)

    async def place_order(self, request: OrderRequest) -> dict:
        """Place a MARKET order, sized to what the VENUE says it will take (`T-0140`, part D).

        The refusals, **in the order they are checked**, and the order is load-bearing:

        ```
        1. SHORT, by policy            -> DirectionNotSupported   VENUE_DIRECTION_UNSUPPORTED
              no network. a permanent refusal must not need the venue to answer.
        2. symbol answered for another -> AlpacaAssetUnusable     (a venue error, not a size one)
        3. SHORT on a non-shortable asset -> DirectionNotSupported   same code, second gate:
              this one fires only if `supported` is ever WIDENED, i.e. if our policy and the
              venue's per-asset fact diverge.
        4. quantised size below minimum -> AlpacaBelowMinimumSize  MIN_SIZE
        ```

        **`1` BEFORE `2` IS THE WHOLE POINT.** Reversed — and it was, in an intermediate state of
        this very change, because reading the asset first deduplicates the venue call — a SHORT on
        an unreachable venue returns `BrokerError` and is filed `VENUE_TRANSPORT`, **which reads as
        *try again***. The loop would then retry, forever, an order Alpaca will never accept.
        `ExecutionService` does not gate this upstream: `service.py:209` consults
        `direction_policy` only in the SHADOW branch, so for a live order this raise is the ONLY
        gate. `B375`'s shape, arrived at by fixing something else.

        **THE LONG-ONLY RULE READS THE ASSET'S `shortable`, NOT `account.shorting_enabled`.**
        Measured (`T-0139`/`D4a`): the account says `shorting_enabled: TRUE` while every crypto
        asset says `shortable: false, marginable: false`. **A check written against the account
        flag concludes shorts are fine, and they are not.** That is `B386`'s shape — two
        instruments, one complete on the account axis and silent on the instrument axis — and the
        account flag is the one a later reader reaches for, which is why the kill set pairs a
        must-die on the asset field with a must-MISS on the account field.

        **ROUND DOWN, THEN REFUSE.** Down because rounding up crosses the risk the size was
        computed for (`T-0097`'s ruled direction for lots). Refuse rather than round to zero,
        because a zero quantity is an order the venue rejects — or one our own `lot_size > 0`
        guard rejects after the decision has already been recorded as taken.

        ⚠ **THE CODE THIS ORDER'S FAILURES MAP TO IS UNTESTED AGAINST THE VENUE** (`D4b`, and the
        kill set's `M-10` prohibits pretending otherwise). This account has placed **zero** orders,
        so no arm here has met a real Alpaca rejection: the arms pin OUR mapping — that a
        `BrokerError` becomes `VENUE_TRANSPORT`, that this member's refusals become
        `VENUE_DIRECTION_UNSUPPORTED` and `MIN_SIZE` — and say **nothing** about which exception
        Alpaca actually raises for an undersized order or a shorting attempt. **A green suite here
        is not evidence the boundary was tested.** The first real order settles it.
        """
        # ------------------------------------------------------------------
        # 1. POLICY FIRST, AND IT TOUCHES NO NETWORK.
        #
        # **THIS ORDER IS THE POINT, AND I HAD IT WRONG IN BETWEEN.** Reading the asset first
        # deduplicates the venue call, which is why I moved it there — and it converts a
        # PERMANENT refusal into one that needs a SUCCESSFUL venue call to happen at all. On a
        # timeout the SHORT would come back as `BrokerError` -> `VENUE_TRANSPORT`, which reads as
        # *try again*: the loop would retry, forever, an order this venue will never accept.
        # `B375` again, produced by fixing something else.
        #
        # `ExecutionService` does NOT gate this upstream — `service.py:209` consults
        # `direction_policy` only in the SHADOW branch (`status: observed`). For a live order
        # THIS RAISE IS THE ONLY GATE, so it must not depend on the venue answering.
        ALPACA_CRYPTO_LONG_ONLY.enforce(request.direction)

        # ------------------------------------------------------------------
        # 2. ONE read, serving both the direction confirmation and the sizing. Two reads of a
        #    record that MOVES WITH PRICE can disagree with each other.
        asset = await self._fetch_asset(request.pair)

        # ------------------------------------------------------------------
        # 3. THE VENUE'S OWN ANSWER, as an INDEPENDENT gate rather than a duplicate of step 1.
        #
        # Step 1 is our policy; this is Alpaca's per-asset fact, and `T-0139`/`D4a` measured them
        # agreeing today. The gate earns its place in the case where they DIVERGE: if `supported`
        # is ever widened — a future venue, a config change, someone "fixing" the long-only rule —
        # this still refuses a SHORT on an asset the venue marks `shortable: false`.
        #
        # **IT READS THE ASSET, NEVER THE ACCOUNT.** Measured: the account says
        # `shorting_enabled: TRUE` while every crypto asset says `shortable: false`. A check
        # against the account flag concludes shorts are fine and they are not — `B386`'s shape,
        # one instrument complete on the account axis and silent on the instrument axis.
        if request.direction != DirectionType.LONG and not getattr(asset, "shortable", False):
            raise DirectionNotSupported(
                venue="alpaca", direction=request.direction.value,
                reason=ALPACA_CRYPTO_LONG_ONLY.reason,
            )

        limits = self._limits_of(asset, request.pair)
        requested = Decimal(str(request.lot_size))
        quantity = limits.quantise_down(requested)

        if quantity < limits.min_order_size:
            raise AlpacaBelowMinimumSize(
                symbol=request.pair, requested=quantity, minimum=limits.min_order_size,
            )

        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        # ------------------------------------------------------------------
        # **NO STOP OR TARGET GOES TO THE VENUE WITH THIS ORDER** (`T-0144` R2, DESIGN §7).
        #
        # `B429` attached `request.sl`/`request.tp` as a BRACKET or OTO order class and then verified and
        # remediated the attachment. It was deleted, not left dormant: every configured symbol is crypto, the
        # venue refuses that order class for crypto, and nothing branches on asset class — so the code was a
        # safety gate with no reachable success path, which reads as live protection while providing none.
        # `request.sl` still SIZES the order upstream (`ExecutionService`). Enforcing the stop is the engine's job: the
        # loop's `VenueEvents` checks it every pass and closes with an ordinary sell (`T-0144` §2.2–§2.5, `place_close`).
        # ------------------------------------------------------------------
        # `str(quantity)` — the venue types quantities as strings and the SDK does not coerce, so
        # handing it a float would send `0.30000000000000004` for a third of a position.
        order = MarketOrderRequest(
            symbol=request.pair,
            # `B457`: fixed-point text. NOTE, measured on alpaca-py 0.44: `MarketOrderRequest.qty` is typed `float`, so the
            # SDK converts this back and the JSON body carries a NUMBER (exponent form below 1e-4, which the venue parses as a
            # number). The text matters where an SDK quantity field is a `str`. At the ENTRY
            # the exponent appears only when the quantised qty is under 1e-4, i.e. when price > notional / 1e-4: $110,000 at
            # the $11 minimum — and the venue accepted an exponent JSON number: probe round 4's remainder sells went out as
            # 5.7828e-05 and filled at exactly 0.000057828 (B457, amended).
            qty=venue_quantity_text(quantity),
            side=OrderSide.BUY if request.direction == DirectionType.LONG else OrderSide.SELL,
            time_in_force=TimeInForce.GTC,
            client_order_id=request.client_order_id,
        )
        # `B427` (review's B-2): an unusable resolution budget is refused HERE, before submission, where a
        # refusal sends nothing. After submission it could only be clamped.
        problem = resolution_budget_problem(ORDER_RESOLUTION_BUDGET_S)
        if problem is not None:
            raise BrokerError(
                f"refusing to place an order: ORDER_RESOLUTION_BUDGET_S is {problem}, so its outcome could "
                f"not be resolved. Nothing was sent.", broker=self.broker_name,
            )
        # **`B442`. THE KILL SWITCH, READ AT THE SEND, UNDER THIS ACCOUNT'S ORDER LOCK.** The loop's gate read the
        # switch before suspending for data; this reads it again with no suspension before `submit_order`, and the
        # lock is held from here through the verdict, so the kill switch's second sweep sees an entry that was
        # already in progress. The refusal is raised HERE — outside `_call` and outside the submission `try` —
        # because through either it would become a `BrokerError`, be classified an unanswered submission, and be
        # looked up as an order that was never sent (review's K2-8). A second LIVE event loop raises before the
        # lock is taken: nothing is sent.
        account = _account_lock(self._account_key)
        async with account.lock:
            account.holder = {"symbol": request.pair, "client_order_id": request.client_order_id,
                              "what": "place_order", "since": time.monotonic()}
            try:
                refuse_if_armed(venue="alpaca", pair=request.pair, client_order_id=request.client_order_id)
                # `T-0144` R5': the position BEFORE the send — under the account lock and after the switch check, so no
                # other adapter on this account can fill between this read and the submission. A read that fails
                # raises here and NOTHING is sent: an unknown "before" can never become a 0 (Q-6).
                held_before = await self._position_quantity(request.pair)
                result = await self._submit_and_resolve(order, request, quantity, requested, limits)
                return await self._with_opened_units(result, request.pair, held_before)
            finally:
                account.holder = None

    async def _position_quantity(self, pair: str) -> Decimal:
        """**The venue position's quantity for `pair`, read through `get_all_positions` and the canonical pair** (`B449`:
        a position is `BTCUSD`, the pair `BTC/USD`, and `get_open_position` with the slash form 404s).

        No matching position is FLAT, and only that is 0: the listing answered and did not include it. Every failure to
        READ raises — a transport error, a non-list answer, a matching position whose quantity is unreadable — because
        "unknown" treated as 0 would count the whole existing position as this entry's fill (T-0144 Q-6)."""
        positions = await self._call("get_all_positions")
        if not isinstance(positions, list):
            raise BrokerError(f"Alpaca get_all_positions returned {type(positions).__name__}, not a list; "
                              f"the position before/after an entry cannot be read", broker=self.broker_name)
        total = Decimal(0)
        for position in positions:
            if same_pair(getattr(position, "symbol", None), pair):
                qty = _dec(getattr(position, "qty", None), "qty")
                if qty is None:
                    raise AlpacaFieldUnreadable("qty", None)
                total += qty
        return total

    async def _with_opened_units(self, result: dict, pair: str, held_before: Decimal) -> dict:
        """**`T-0144` R5' / R5''. What this entry ADDED to the position**, measured, cross-checked against the fill.

        `held_units = after − before`. `buy_fee_units = filled − held`. The check: `|filled × (1 − fee) − held|` within
        `OPENED_UNITS_WINDOW`, in `Decimal`. Outside it, `units_check.within` is `False` and the loop HALTS with both numbers.
        Only a fill-bearing result is measured. An after-read that fails leaves `held_units` present and `None`: the
        venue acted and we cannot say what we now hold, which the loop treats as unsizeable, never as the order's quantity.
        """
        status = result.get("status") if isinstance(result, dict) else None
        if type(status) is not str or status not in ("FILLED", "PARTIALLY_FILLED"):
            return result
        try:
            held_after = await self._position_quantity(pair)
        except Exception as exc:  # noqa: BLE001 - reported on the result; the order already exists
            result["held_units"] = None
            result["units_check"] = {"error": f"{type(exc).__name__}: {exc}", "held_before": str(held_before)}
            logger.error("alpaca.opened_units_unreadable — the position after the fill could not be read",
                         symbol=pair, client_order_id=result.get("client_order_id"), error=f"{type(exc).__name__}")
            return result
        held = held_after - held_before
        filled = _dec(result.get("filled_units"), "filled_units")
        if filled is None:
            result["held_units"] = float(held) if held > 0 else None
            result["units_check"] = {"filled": None, "held": str(held), "within": None}
            return result
        expected = filled * (Decimal(1) - ALPACA_CRYPTO_FEE_RATE)
        disagreement = abs(expected - held)
        result["held_units"] = float(held) if held > 0 else None
        result["buy_fee_units"] = float(filled - held)
        result["units_check"] = {
            "filled": str(filled), "held_before": str(held_before), "held_after": str(held_after), "held": str(held),
            "expected_held": str(expected), "disagreement": str(disagreement), "window": str(OPENED_UNITS_WINDOW),
            "fee": str(filled - held),
            "within": disagreement <= OPENED_UNITS_WINDOW,
        }
        return result

    async def reference_quote(self, symbol: str) -> "VenueQuote | None":
        """**`T-0144` R3'. Alpaca's latest crypto quote for `symbol`, stamped with the venue's OWN timestamp**, or `None`.

        The FALLBACK reference for an entry when the Binance mark is not usable (`execution.reference.choose_reference`
        applies the 120 s bound from that timestamp and takes the mid). Read through a DATA client that is not the trading
        client: its own timeout mount and its own single worker (review's F10d, R-6), so a held trading call on this account
        cannot delay a quote and a quote cannot queue a trading call. Any failure is `None` — "no usable quote" — never a
        raise into the entry path."""
        from app.services.execution.reference import VenueQuote

        try:
            client = self._quote_client()
            from alpaca.data.requests import CryptoLatestQuoteRequest

            def _latest():
                return client.get_crypto_latest_quote(CryptoLatestQuoteRequest(symbol_or_symbols=symbol))

            quotes = await self._quote_worker().run(_latest, write=False, call="get_crypto_latest_quote")
            quote = quotes.get(symbol) if isinstance(quotes, dict) else None
            if quote is None:
                return None
            return VenueQuote(bid=getattr(quote, "bid_price", None), ask=getattr(quote, "ask_price", None),
                              timestamp=getattr(quote, "timestamp", None))
        except Exception as exc:  # noqa: BLE001 - a missing fallback is None, not a failed entry
            logger.warning("alpaca.reference_quote_unavailable", symbol=symbol, error=f"{type(exc).__name__}")
            return None

    def _quote_client(self):
        client = getattr(self, "_data_client", None)
        if client is None:
            client = self._data_client = build_crypto_data_client(
                getattr(self._client, "_api_key", None), getattr(self._client, "_secret_key", None))
        return client

    def _quote_worker(self) -> AccountExecutor:
        executor = getattr(self, "_data_executor", None)
        if executor is None:
            # NOT the trading worker: a separate key, so a separate single thread (B437's registry is per key).
            executor = self._data_executor = account_executor(f"data:{self._account_key}")
        return executor

    # ------------------------------------------------------------------
    # `T-0144` §2.2–§2.6 — what `VenueEvents` needs from the venue
    # ------------------------------------------------------------------
    @property
    def is_paper_venue(self) -> bool:
        """A PAPER account: execution slippage on its fills is labelled PAPER (R1')."""
        return bool(self._paper)

    async def position_quantity(self, pair: str) -> Decimal:
        """The venue's quantity held for `pair` (canonical match). Raises when it cannot be read; 0 only when not listed."""
        return await self._position_quantity(pair)

    async def cancel_open_orders_for(self, pair: str) -> dict:
        """**R14: cancel the symbol's resting orders before a close** (a resting order locks `qty_available`, `B448`).

        Lists OPEN orders with every field stated (an explicit limit, newest first, nested so legs are visible, NO server
        symbol filter — the canonical match is ours), and cancels each order for `pair` by id (writes are shielded, `B437`).
        Returns `{cancelled, failed: [(id, error)], resting: [ids], complete}`. `complete` is False when the listing FAILED or
        came back FULL (an order for the symbol may be past the page): the caller then sends nothing this pass."""
        from alpaca.common.enums import Sort
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest

        try:
            orders = await self._call("get_orders", GetOrdersRequest(
                status=QueryOrderStatus.OPEN, limit=CANCEL_SCAN_ORDER_LIMIT, direction=Sort.DESC, nested=True)) or []
            self._require_model(orders, "get_orders")
        except Exception as exc:  # noqa: BLE001 - an unreadable listing is not "nothing resting"
            return {"cancelled": [], "failed": [("?", f"open-order listing failed: {type(exc).__name__}: {exc}")],
                    "resting": [], "complete": False}
        complete = len(orders) < CANCEL_SCAN_ORDER_LIMIT
        resting = [str(getattr(o, "id", "")) for o in orders if same_pair(getattr(o, "symbol", None), pair)]
        cancelled: list[str] = []
        failed: list[tuple[str, str]] = []
        for order_id in resting:
            try:
                await self._call("cancel_order_by_id", order_id)
                cancelled.append(order_id)
            except Exception as exc:  # noqa: BLE001 - reported; the close waits for the next pass
                failed.append((order_id, f"{type(exc).__name__}: {exc}"))
        return {"cancelled": cancelled, "failed": failed, "resting": resting, "complete": complete}

    async def place_close(self, pair: str, qty: Decimal, client_order_id: str) -> dict:
        """**An engine close is an ordinary SELL order** (R7', §2.5) — never `close_position`, which sells FOREIGN units and
        carries no client id.

        MARKET, GTC, the quantity quantised DOWN to the asset's increment (never above what was asked) and written
        fixed-point (`B457`); under this account's order lock, so a close and an entry never interleave; submitted WITHOUT
        the kill switch's check at the send (a close is protective, K2-9); an ambiguous submission is looked up by its
        client id (`B440`) and the order is resolved (`B427`). Exempt from the $11 ENTRY minimum (R6': closes fill below it);
        the venue's own minimum order size still applies and is the caller's to check. The result is `place_order`'s shape.
        """
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        requested = qty if isinstance(qty, Decimal) else Decimal(str(qty))
        limits = self._limits_of(await self._fetch_asset(pair), pair)
        quantity = limits.quantise_down(requested)
        if quantity <= 0 or quantity > requested:
            raise BrokerError(f"refusing a close of {requested} {pair}: it quantises to {quantity}. Nothing was sent.",
                              broker=self.broker_name)
        order = MarketOrderRequest(symbol=pair, qty=venue_quantity_text(quantity), side=OrderSide.SELL,
                                   time_in_force=TimeInForce.GTC, client_order_id=client_order_id)
        request = OrderRequest(pair=pair, direction=DirectionType.LONG, order_type=OrderType.MARKET,
                               lot_size=float(quantity), client_order_id=client_order_id)
        account = _account_lock(self._account_key)
        async with account.lock:
            account.holder = {"symbol": pair, "client_order_id": client_order_id, "what": "place_close",
                              "since": time.monotonic()}
            try:
                result = await self._submit_and_resolve(order, request, quantity, requested, limits, switch_at_send=False)
            finally:
                account.holder = None
        result["side"] = "sell"
        return result

    async def find_order_by_client_id(self, client_order_id: str) -> dict | None:
        """The order the venue holds under `client_order_id`, mapped like any result, or `None` when the venue answers 404.
        Any other failure RAISES: "not found" is only ever the venue's answer (G-2's probe counts on it)."""
        try:
            order = self._require_model(await self._call("get_order_by_client_id", client_order_id),
                                        "get_order_by_client_id")
        except BrokerError as exc:
            if _http_status_of(exc) == 404:
                return None
            raise
        verdict = self._order_result(order)
        return {**verdict, "order_id": str(getattr(order, "id", "") or "") or None,
                "position_id": str(getattr(order, "id", "") or "") or None,
                "client_order_id": getattr(order, "client_order_id", None),
                "filled_at": _venue_time(getattr(order, "filled_at", None))}

    async def order_client_id(self, order_id: str) -> str | None:
        """The client id the venue holds for `order_id` (FILL rows carry none, probe rounds 3/4)."""
        order = self._require_model(await self._call("get_order_by_id", order_id), "get_order_by_id")
        value = getattr(order, "client_order_id", None)
        return str(value) if value else None

    async def fill_activities(self, pair: str, after: datetime) -> list[dict]:
        """**FILL activities for `pair` strictly after `after`**, every page (X-1).

        `after` is the entry order's VENUE fill time at full precision (GX-5, X-3c: the venue treats it as exclusive, and a
        truncated bound silently moves it). Rows are returned as `{id, order_id, symbol, side, qty, price, transaction_time}`
        with times from `transaction_time`, never from the activity id. A row that cannot be read, a non-list page, or a
        listing that does not end within `FILL_ACTIVITY_MAX_PAGES` RAISES: a partial list is not the fills."""
        bound = _venue_time(after)
        if bound is None:
            raise BrokerError(f"FILL activities for {pair} need the entry's venue fill time; got {after!r}",
                              broker=self.broker_name)
        rows: list[dict] = []
        seen: set[str] = set()
        page_token: str | None = None
        for _page in range(FILL_ACTIVITY_MAX_PAGES):
            params: dict = {"after": bound.isoformat(), "direction": "desc", "page_size": FILL_ACTIVITY_PAGE_SIZE}
            if page_token is not None:
                params["page_token"] = page_token
            page = await self._call("get", "/account/activities/FILL", params)
            if not isinstance(page, list):
                raise BrokerError(f"Alpaca FILL activities returned {type(page).__name__}, not a list",
                                  broker=self.broker_name)
            for raw in page:
                row = self._fill_row(raw)
                if row["id"] in seen:
                    continue
                seen.add(row["id"])
                if same_pair(row["symbol"], pair):
                    rows.append(row)
            if len(page) < FILL_ACTIVITY_PAGE_SIZE:
                return rows
            page_token = str(page[-1].get("id")) if isinstance(page[-1], dict) else None
            if not page_token:
                raise BrokerError("Alpaca FILL activities: a full page whose last row has no id to continue from",
                                  broker=self.broker_name)
        raise BrokerError(f"Alpaca FILL activities for {pair} did not end within {FILL_ACTIVITY_MAX_PAGES} pages",
                          broker=self.broker_name)

    @staticmethod
    def _fill_row(raw: Any) -> dict:
        if not isinstance(raw, dict):
            raise BrokerError(f"an unreadable FILL activity row: {raw!r}", broker="alpaca")
        when = _venue_time(raw.get("transaction_time"))
        qty, price = _dec(raw.get("qty"), "qty"), _dec(raw.get("price"), "price")
        if when is None or qty is None or price is None or not raw.get("order_id") or not raw.get("id"):
            raise BrokerError(f"an unreadable FILL activity row: {raw!r}", broker="alpaca")
        return {"id": str(raw["id"]), "order_id": str(raw["order_id"]), "symbol": raw.get("symbol"),
                "side": str(raw.get("side", "")).lower(), "qty": qty, "price": price, "transaction_time": when}

    async def _submit_and_resolve(self, order, request, quantity, requested, limits, *, switch_at_send: bool = True) -> dict:
        """Submission, the `B440` lookup, and the verdict — called by `place_order` and `place_close`, under the account
        lock. `switch_at_send` is False only for a close."""
        declined = None
        try:
            sent = await self._call("submit_order", order, _switch_at_send=switch_at_send)
            if isinstance(sent, NotSent):
                declined = sent          # the worker's check at the send refused it; raised OUTSIDE this try, below
            else:
                placed = self._require_model(sent, "submit_order")
        except BrokerError as exc:
            # **`B440`/`B441`. A FAILED SUBMISSION IS NOT PROOF THAT NO ORDER EXISTS.** Only a failure raised
            # before anything was sent, or a refusal the server read and answered, is (`classify_submission_
            # failure`, by exception type). Anything else asks the venue by client_order_id, and an order it
            # cannot find is UNRESOLVED — a halt — never a refusal that a filled order would contradict.
            kind = classify_submission_failure(exc)
            if kind == SUBMISSION_NOT_CREATED:
                raise
            try:
                placed, why = await self._find_submitted_order(order, kind, exc)
            except asyncio.CancelledError:
                logger.error(
                    "alpaca.submission_cancelled_while_unconfirmed — the submission FAILED ambiguously and this "
                    "task was cancelled while looking for the order, which MAY EXIST at the venue",
                    client_order_id=request.client_order_id, symbol=request.pair,
                    failure=f"{type(exc).__name__}", kind=kind,
                )
                raise
            if placed is None:
                return self._unconfirmed_submission(request, quantity, requested, limits, exc, why)

        if declined is not None:
            # `B437` / E-11: the switch was armed while this submission waited on the account's worker. NOTHING was
            # sent. Raised here, outside the submission `try`, so it is a refusal and never a classified failure.
            raise declined.refusal

        # **D3 (`B437`).** From here the order EXISTS at the venue. A cancellation during the resolution used to
        # vanish with it — measured on a451ec1, no log line held the order id. It is logged with everything needed
        # to find the order, and re-raised.
        progress: dict = {"last_status": self._order_status(placed)}
        try:
            return await self._verdict_for_placed(placed, request, quantity, requested, limits, progress)
        except asyncio.CancelledError:
            logger.error(
                "alpaca.order_cancelled_after_submission — the order EXISTS at the venue and this task was "
                "cancelled before its outcome was recorded. Find it by id before trading this symbol again.",
                order_id=str(getattr(placed, "id", "") or ""), client_order_id=request.client_order_id,
                symbol=request.pair, last_status=progress.get("last_status"),
            )
            raise

    async def _verdict_for_placed(self, placed, request, quantity, requested, limits, progress) -> dict:
        """B427's resolution for an order that EXISTS, mapped into the result."""
        # ------------------------------------------------------------------
        # **`B427`. THE ACKNOWLEDGEMENT IS NOT AN OUTCOME — RESOLVE THE ORDER, BOUNDED, THEN REPORT IT.**
        #
        # This returned the SUBMISSION RESPONSE's status and quantity. An order the venue ACCEPTED and
        # filled a moment later was classified at the moment of acceptance: before `T-0130` as a false
        # refusal, since `T-0130` as UNRESOLVED, which halts. So the order is re-read until it is terminal
        # or `ORDER_RESOLUTION_BUDGET_S` is spent, and the result maps the LATEST venue statement.
        # On expiry the last status is reported as it is, and the loop's UNRESOLVED seam
        # halts — no second failure path.
        #
        # **Resolution lives HERE, not in the service or loop (manager's ruling A)**: probe 3 calls this
        # method directly, so this is the only place the real venue will exercise it before the engine does.
        # The acknowledgement is kept beside the verdict (`resolution.ack_*`), never overwritten.
        # ------------------------------------------------------------------
        resolved, resolution = await self._resolve_order(str(getattr(placed, "id", "") or ""), None, progress)
        verdict = self._order_result(resolved if resolved is not None else placed)
        ack = self._order_result(placed)
        status = verdict["status"]

        if status == "PARTIALLY_FILLED":
            # `B414`: keyword arguments, because loguru formats with `str.format` and a `%s` line dropped
            # every value. `B411`: a partial leaves a real position; `terminal` says whether it can grow.
            logger.error(
                "alpaca.partial_fill — the venue opened a position SMALLER than the order",
                symbol=request.pair, requested=str(quantity), filled=str(verdict["filled_units"]),
                venue_status=verdict["venue_status"], terminal=verdict["terminal"],
                resolved=resolution["resolved"],
            )

        result = {
            "status": status,
            # What the VENUE says it filled, `None` when it did not say — never defaulted to the
            # submitted quantity, which would report a fill we have no evidence of. Parsed by
            # `readable_quantity` (`T-0130` K-4b): unreadable is `None`, never raised, never NaN.
            "filled_units": verdict["filled_units"],
            "position_id": str(getattr(placed, "id", "")),
            "pair": request.pair,
            "direction": request.direction.value,
            "units": float(quantity),
            "requested_units": float(requested),
            # Quantised DOWN, and the pair is recorded so a reader can see the venue's grid acting
            # rather than infer it from a difference.
            "quantise_increment": float(limits.min_trade_increment),
            "min_order_size": float(limits.min_order_size),
            "client_order_id": request.client_order_id,
            # `readable_price` (`B433`): a zero, negative, unparseable or non-finite price is None.
            "fill": verdict["fill"],
            "venue_status": verdict["venue_status"],
            "terminal": verdict["terminal"],
            # `T-0144` GX-5: the VENUE's fill time, the lower bound for attributing this position's closing FILLs. Never a
            # local clock. `None` when the venue did not say.
            "filled_at": _venue_time(getattr(resolved if resolved is not None else placed, "filled_at", None)),
            "resolution": {**resolution, "ack_status": ack["venue_status"],
                           "ack_filled_units": ack["filled_units"]},
        }
        if "rejection_code" in verdict:
            result["rejection_code"] = verdict["rejection_code"]
            result["reason"] = verdict["reason"]
        return result

    async def _find_submitted_order(self, order, kind: str, exc: BaseException) -> tuple[Any, str | None]:
        """Ask the venue for the order a failed submission may have created, by its client_order_id.

        ```
        ANSWERED (422)   ONE lookup. The server answered this POST, so a 404 PROVES it was not created: the
                         ORIGINAL refusal is re-raised. Any other lookup failure -> not found -> UNRESOLVED.
        UNANSWERED       lookups on the resolver's schedule within ORDER_RESOLUTION_BUDGET_S. A 404 proves
                         nothing — the backend may still be storing the order — so it is "not yet".
        ```
        A FOUND order is ours only if it MATCHES the request (`_submission_mismatch`); otherwise UNRESOLVED
        with both orders named. Returns `(order, None)` or `(None, why)`. Raises only the original refusal.
        """
        client_id = getattr(order, "client_order_id", None)
        failure = f"{type(exc).__name__}: {redact_for_storage(str(exc), limit=160)}"
        if not client_id:
            return None, f"the submission failed ({failure}) and carried no client_order_id to look it up by"
        offsets = [0.0] if kind == SUBMISSION_ANSWERED else self._resolution_offsets(ORDER_RESOLUTION_BUDGET_S)
        start = self._clock()
        lookups = 0
        seen: list[str] = []
        budget = ORDER_RESOLUTION_BUDGET_S
        for offset in offsets:
            if lookups and self._clock() - start >= budget:
                break                       # wall time, as in the resolver (X-10)
            wait = start + offset - self._clock()
            if wait > 0:
                await self._sleep(wait)
            lookups += 1
            try:
                found = self._require_model(
                    await self._call("get_order_by_client_id", client_id), "get_order_by_client_id")
            except BrokerError as lookup_exc:
                if _http_status_of(lookup_exc) == 404:
                    if kind == SUBMISSION_ANSWERED:
                        raise exc
                    seen.append("404")
                else:
                    seen.append(type(lookup_exc.__cause__ or lookup_exc).__name__)
                continue
            mismatch = self._submission_mismatch(found, order)
            if mismatch:
                return None, (f"an order with client_order_id {client_id!r} EXISTS at the venue but does not "
                              f"match this request ({mismatch}) — not treated as ours; the submission failed "
                              f"with {failure}")
            logger.error(
                "alpaca.submission_ambiguous_found — the submission FAILED but the venue HAS this order; "
                "resolving it instead of recording a refusal",
                client_order_id=client_id, order_id=str(getattr(found, "id", "") or ""), failure=failure,
                lookups=lookups, kind=kind,
            )
            return found, None
        return None, (f"not found at the venue after {lookups} lookup(s) over "
                      f"{round(self._clock() - start, 3)}s — it may still appear (the submission failed with "
                      f"{failure}; lookups answered {seen[:6]})")

    def _submission_mismatch(self, found, order) -> str | None:
        """Why a looked-up order is NOT the one this request sent, or None when symbol, side and qty all match.

        **RESIDUAL, stated (manager):** `service.py` builds client_order_id as `sig-` + 8 hex characters — 32
        bits — so across an account's history two orders sharing one is plausible (even odds at about 77,000
        orders). Matching the request is what keeps a stranger's order from being adopted; widening the id is
        not done here, because `service.py` serves every venue and OANDA's client extensions have limits.
        """
        problems = []
        if not self._same_symbol(getattr(found, "symbol", None), str(getattr(order, "symbol", ""))):
            problems.append(f"symbol venue={getattr(found, 'symbol', None)!r} sent={getattr(order, 'symbol', None)!r}")
        venue_side = getattr(getattr(found, "side", None), "value", getattr(found, "side", None))
        sent_side = getattr(getattr(order, "side", None), "value", getattr(order, "side", None))
        if str(venue_side or "").lower() != str(sent_side or "").lower():
            problems.append(f"side venue={venue_side!r} sent={sent_side!r}")
        try:
            same_qty = Decimal(str(getattr(found, "qty", None))) == Decimal(str(getattr(order, "qty", None)))
        except (InvalidOperation, ValueError, TypeError):
            same_qty = False
        if not same_qty:
            problems.append(f"qty venue={getattr(found, 'qty', None)!r} sent={getattr(order, 'qty', None)!r}")
        return "; ".join(problems) or None

    def _unconfirmed_submission(self, request, quantity, requested, limits, exc, why: str) -> dict:
        """The result for a submission whose outcome cannot be established: UNRESOLVED, which halts."""
        # The reason goes in a FIELD, never into the message: loguru formats the message with `str.format`,
        # and a venue body quoted in `why` carries braces (`B414`'s class — measured here, as a KeyError).
        logger.error("alpaca.submission_unconfirmed — HALT EXPECTED: the order's existence could not be established",
                     reason=why, symbol=request.pair, client_order_id=request.client_order_id)
        return {
            "status": "SUBMISSION_UNCONFIRMED",
            "reason": redact_for_storage(why),
            "filled_units": None,
            "position_id": None,
            "pair": request.pair,
            "direction": request.direction.value,
            "units": float(quantity),
            "requested_units": float(requested),
            "quantise_increment": float(limits.min_trade_increment),
            "min_order_size": float(limits.min_order_size),
            "client_order_id": request.client_order_id,
            "fill": None,
            "venue_status": None,
            "terminal": False,
            "resolution": {"resolved": False, "reads": 0, "elapsed_s": 0.0, "budget_s": ORDER_RESOLUTION_BUDGET_S,
                           "budget_problem": None, "read_errors": [], "ack_status": None,
                           "ack_filled_units": None},
        }

    @staticmethod
    def _resolution_offsets(budget: float) -> list[float]:
        """The offsets (seconds from the start) at which the resolver reads, for `budget`. Every offset is
        at or before the budget, so no read — and no sleep before it — runs past the deadline. A budget of
        zero is one immediate read."""
        schedule = list(ORDER_RESOLUTION_READ_OFFSETS_S)
        offsets = [o for o in schedule if o <= budget] or [0.0]
        gap = schedule[-1] - schedule[-2]
        nxt = schedule[-1] + gap
        while gap > 0 and nxt <= budget:
            offsets.append(nxt)
            nxt += gap
        return offsets

    async def _resolve_order(self, order_id: str, first_read=None, progress: dict | None = None) -> tuple[Any, dict]:
        """**`B427`. Re-read an order until it is TERMINAL or the budget is spent. NEVER raises.**

        Returns `(last_order_read_or_first_read, resolution)`. `first_read` is a read ALREADY made, counted as
        the first read, so a fill that is terminal by then costs no further request. **No caller passes one since
        `T-0144` R2** deleted `B429`'s nested protection re-read, its only source: `place_order` and the closes pass
        `None`, and every read counted here is the resolver's own.
        A read that fails is "not yet", never a verdict: it is recorded and the next read is tried.
        The VERDICT is always the latest venue statement; `resolution["resolved"]` says whether a
        re-read confirmed a terminal state.

        Only `Exception` is caught, so a cancellation during a wait propagates — the callers' abnormal-
        exit handling (`close_all_positions`' in-flight rows) depends on seeing it.
        """
        from alpaca.trading.requests import GetOrderByIdRequest

        # Read at CALL time, where Malek sets it. A value changed at runtime to something unusable is not
        # refused here — this runs AFTER a submission, where raising is K-4b's false refusal — it is
        # CLAMPED to one immediate read and the problem recorded, so it cannot pass for a timeout.
        budget = ORDER_RESOLUTION_BUDGET_S
        problem = resolution_budget_problem(budget)
        if problem is not None:
            budget = 0.0
        start = self._clock()
        last = first_read
        reads = 1 if first_read is not None else 0
        errors: list[str] = []
        progress = progress if progress is not None else {}
        if first_read is not None:
            progress["last_status"] = self._order_status(first_read)

        def _terminal(order) -> bool:
            return order is not None and self._order_status(order) in TERMINAL_ORDER_STATUSES

        if not _terminal(last):
            for offset in self._resolution_offsets(budget):
                if offset == 0.0 and first_read is not None:
                    continue
                # WALL TIME, not the schedule (review's X-10): a slow read pushes later offsets into the past,
                # and without this every one of them would still read. No read STARTS once the budget is spent.
                if reads and self._clock() - start >= budget:
                    break
                wait = start + offset - self._clock()
                if wait > 0:
                    await self._sleep(wait)
                reads += 1
                try:
                    last = self._require_model(
                        await self._call("get_order_by_id", order_id, GetOrderByIdRequest(nested=True)),
                        "get_order_by_id")
                except Exception as exc:  # noqa: BLE001 - a failed read is "not yet", never a verdict
                    errors.append(f"{type(exc).__name__}: {str(exc)[:160]}")
                if last is not None:
                    progress["last_status"] = self._order_status(last)
                if _terminal(last):
                    break

        return last, {
            "resolved": _terminal(last),
            "reads": reads,
            "elapsed_s": round(self._clock() - start, 3),
            "budget_s": budget,
            "budget_problem": problem,
            "read_errors": errors[:6],
        }

    def _order_result(self, order) -> dict:
        """**`B427`. ONE mapping from a venue Order to the engine's result**, for `place_order`, the closes
        and `get_orders`. Built from the vocabularies that exist — `TERMINAL_ORDER_STATUSES` (and
        `ENDED_ORDER_STATUSES`, derived from it), `readable_quantity`, `readable_price` — so what a status
        MEANS to the loop is still decided only by `classify_order_status`.

        ```
        venue status               filled quantity         -> status               note
        filled                     any (None -> unsized)   -> FILLED
        partially_filled           any                     -> PARTIALLY_FILLED     terminal False (ruling D)
        canceled/expired/rejected  readable, > 0           -> PARTIALLY_FILLED     a CLOSED partial: known size
        canceled/expired/rejected  readable, exactly 0     -> REJECTED + VENUE_ENDED_UNFILLED (ruling C)
        canceled/expired/rejected  unreadable or negative  -> the venue status, UPPER -> UNRESOLVED (exposure unknown)
        replaced                   —                       -> REPLACED -> UNRESOLVED (successor id not followed)
        anything else, incl. none  —                       -> the venue status UPPER, or SUBMITTED -> UNRESOLVED
        ```

        `B411`: the status is read by `.value` and matched EXACTLY (`_order_status`) — `str(OrderStatus)`
        is `'OrderStatus.FILLED'`, and `partially_filled` also ends with `filled`.
        """
        venue = self._order_status(order)
        qty = readable_quantity(getattr(order, "filled_qty", None))
        out: dict = {
            "venue_status": venue or None,
            "terminal": venue in TERMINAL_ORDER_STATUSES,
            "filled_units": qty,
            "fill": readable_price(getattr(order, "filled_avg_price", None)),
        }
        if venue == "filled":
            out["status"] = "FILLED"
        elif venue == "partially_filled":
            out["status"] = "PARTIALLY_FILLED"
        elif venue in ENDED_ORDER_STATUSES and qty is not None and qty > 0:
            out["status"] = "PARTIALLY_FILLED"
        elif venue in ENDED_ORDER_STATUSES and qty is not None and qty == 0:
            out["status"] = "REJECTED"
            out["rejection_code"] = REJECTION_VENUE_ENDED_UNFILLED
            out["reason"] = (f"the venue acknowledged the order and then ended it ({venue}) with nothing "
                             f"filled — no position exists")
        else:
            out["status"] = venue.upper() if venue else "SUBMITTED"
        return out

    @staticmethod
    def _order_status(order) -> str:
        """An order's status as a lowercase string, `""` when it cannot be read.

        `.value` explicitly — `str(OrderStatus.HELD)` is `'OrderStatus.HELD'` (`B411`'s trap). An
        unreadable status is `""`, which is not in `TERMINAL_ORDER_STATUSES`: still able to fill.
        """
        raw = getattr(order, "status", None)
        return str(getattr(raw, "value", raw) or "").lower()

    @staticmethod
    def _same_symbol(a: object, b: object) -> bool:
        """Whether two venue spellings name the same pair — `symbols.same_pair`, the ONE canonical comparison (`B461`).

        Measured since this was written (`B449`, probe rounds 1–4): Alpaca writes crypto ORDERS as `BTC/USD` and returns
        POSITIONS as `BTCUSD`. It used to strip `-` as well and turn a missing symbol into `""`, so two MISSING symbols
        compared equal; a missing side is now never the same pair.
        """
        return same_pair(a, b)

    async def close_position(self, position_id: str, lot_size: float | None = None) -> dict:
        """Close the WHOLE position for a symbol, and **REFUSE a `lot_size`** (`T-0038`: honour it or refuse loudly).

        The contract is *honour it or refuse loudly*, and silently closing everything when a caller
        asked for 30% is the ambiguity that contract exists to prevent. **This adapter no longer
        honours it** (`T-0144` R2-4, B457's residual): a partial close was a close request carrying a
        `qty` against the position, and an ENGINE close is an ordinary sell ORDER the engine sizes, resolves
        and identifies (DESIGN §2.5, `place_close`). A `lot_size` is therefore refused before anything is
        sent — never ignored, which would close the whole position under a partial's name.

        The whole close by symbol stays: a person's close from the positions route, and the kill
        switch (`close_all_positions`, which calls the SDK per symbol).
        """
        if lot_size is not None:
            raise BrokerError(
                f"refusing close_position({position_id!r}, lot_size={lot_size!r}): partial closes are engine "
                f"sell orders (T-0144 §2.5); this adapter does not partially close by position. Nothing was sent.",
                broker=self.broker_name,
            )
        # **`B427`/`B438`. THE CLOSE IS AN ORDER, AND AN ACCEPTED ORDER IS NOT A CLOSED POSITION.** This
        # returned `str(result)` and nothing else, so the close order's status and filled quantity were
        # discarded and a caller could not tell "the close was accepted" from "the close filled" —
        # `positions.py` read the missing status as closed. The close order is resolved with the same
        # resolver and budget as an entry, and `close_confirmed` is True ONLY for a terminal FILLED close.
        order = await self._call("close_position", position_id)
        return {"position_id": position_id, "partial": False, **(await self._close_outcome(order))}

    async def _close_outcome(self, order) -> dict:
        """Resolve a close ORDER and report it: the mapped verdict, the acknowledgement beside it, and
        `close_confirmed` — True only when the close is terminal and FILLED. **Never raises.**

        `TradingClient.close_position(symbol)` returns an `Order` (its annotation and its code). It is
        NOT `ClosePositionResponse` — that is the return type of `close_all_positions`, an endpoint this
        adapter never calls; reading an Order as one is `B439`.
        """
        order_id = str(getattr(order, "id", "") or "")
        progress: dict = {"last_status": self._order_status(order)}
        try:
            resolved, resolution = await self._resolve_order(order_id, None, progress)
        except asyncio.CancelledError:
            logger.error(
                "alpaca.close_cancelled_after_submission — the CLOSE order EXISTS at the venue and this task "
                "was cancelled before its outcome was recorded. Check the position at the venue.",
                order_id=order_id, symbol=str(getattr(order, "symbol", "") or ""),
                last_status=progress.get("last_status"),
            )
            raise
        verdict = self._order_result(resolved if resolved is not None else order)
        ack = self._order_result(order)
        return {
            "order_id": order_id or None,
            "status": verdict["status"],
            "venue_status": verdict["venue_status"],
            "terminal": verdict["terminal"],
            "filled_units": verdict["filled_units"],
            "fill": verdict["fill"],
            "close_confirmed": verdict["status"] == "FILLED" and verdict["terminal"],
            "resolution": {**resolution, "ack_status": ack["venue_status"],
                           "ack_filled_units": ack["filled_units"]},
        }

    async def close_all_positions(self) -> list[dict]:
        """**Malek's ruled property, on its third venue** — the shape is reused, not rebuilt.

        > Every position open when the switch was pulled must be reported as CLOSED, FAILED WITH A
        > REASON, or NOT ATTEMPTED.

        The dispositions come from `BrokerAdapter` (`T-0132`) rather than being redefined here — a
        ruled property that lives in one implementation is a property of that implementation.

        **WHAT A ROW SAYS, AFTER `B439` AND `B427`.** Each close is `close_position(symbol)`, which returns an
        `Order` — not `ClosePositionResponse`, the type of an endpoint this adapter never calls. The close
        order is RESOLVED (`_close_outcome`) and reported CLOSED only when it is terminal and FILLED; a close
        the venue refused raises inside `_call` and is FAILED with its reason; a close submitted and not
        confirmed within the budget is FAILED WITH A REASON saying exactly that (`B337`). The resolved
        order is attached to the row as `close`.

        **TWO SWEEPS (`B442`, manager's ruling 3).** An entry already SUBMITTED and still resolving when the switch
        is pulled can fill after the book is enumerated. Waiting for it BEFORE the first close would hold every
        open position hostage to one entry — an estimated 8C + B, 493s for the builder's client
        (`entry_lock_normal_hold_bound_s`) — on the degraded venue where the switch is most likely pulled. So:

            (a) enumerate and close NOW, taking no lock;
            (b) then take this account's order lock — the entry holds it through its verdict — with a wait of
                min(8C + B, KILL_SWITCH_RESPONSE_DEADLINE_S − elapsed since this method started), floored at 0;
                re-enumerate; close what (a) did not see, or confirmed CLOSED and is open again.

        (b) NEVER re-closes a position whose close in (a) FAILED or is unconfirmed: that close order may still be
        working, and a second close is a second sell. Every row from both sweeps is kept — a symbol can appear
        twice, closed in (a) and then a new position closed in (b) — and each row's reason names its sweep.
        If the wait expires, or the lock belongs to another live event loop, (b) enumerates anyway and a
        NOT_ATTEMPTED row names the in-flight entry, which MAY EXIST at the venue.

        The switch never refuses its own closes: nothing on this path reads the kill switch (review's K2-9).
        """
        report: dict[str, dict] = {}
        self.last_close_all_report = report
        started = self._clock()
        try:
            positions = await self._raw_positions()
        except Exception as exc:  # noqa: BLE001
            raise BrokerError(
                f"Alpaca close_all_positions could not enumerate the open positions, so it cannot "
                f"report on them: {exc}. Nothing was attempted.", broker=self.broker_name,
            ) from exc

        try:
            await self._close_sweep(report, "a", positions)
            await self._close_sweep_b(report, started)
        except BaseException as exc:  # noqa: BLE001 - CancelledError is not an Exception
            for _row in report.values():
                if _row.pop("_in_flight", False):
                    _row["reason"] = (
                        f"[sweep {_row.get('sweep')}] {type(exc).__name__}: the close for this position was SENT "
                        f"and the outcome was NEVER OBSERVED — the loop did not survive to record it "
                        f"({exc}). It MUST be checked at the venue."
                    )
            # `B446`: a CANCELLATION is re-raised as itself, carrying the report; anything else is the BrokerError it was.
            failure = self._abnormal_exit(exc, report, "Alpaca", self.broker_name)
            if failure is exc:
                raise
            raise failure from exc

        for row in report.values():
            row.pop("_in_flight", None)
        return list(report.values())

    async def _close_sweep(self, report: dict[str, dict], sweep: str, positions: list, *,
                           confirmed_in_a: dict[str, dict] | None = None, **fields) -> None:
        """Publish a NOT_ATTEMPTED row for every position FIRST (`B303`), then close them one by one. ANY exception
        on one position is that position's FAILED row and the loop CONTINUES; only a `BaseException` ends it,
        and `close_all_positions` turns that into a partial report.

        `confirmed_in_a` (sweep b only) maps a symbol sweep (a) CONFIRMED CLOSED to that row. **VENUE LISTING LAG**
        (manager's ruling, from probe round 3): the venue can still list a position for a read after its close has
        filled. Sweep (b) then sees it "open again" and sends a second close, which the venue refuses with
        `position does not exist`. That position IS closed — sweep (a) confirmed the fill — so the refusal is
        recorded on (a)'s row, naming the lag, and (b)'s row is removed: CLOSED, once. Any other refusal stays FAILED."""
        keys = []
        for index, raw in enumerate(positions):
            key = f"{sweep}#{index}"
            report[key] = {
                "position_id": str(getattr(raw, "symbol", "") or "").strip(),
                "pair": str(getattr(raw, "symbol", "UNKNOWN")),
                "disposition": self.NOT_ATTEMPTED,
                "status": "failed",
                "sweep": sweep,
                "reason": f"[sweep {sweep}] the close loop never reached this position",
                **fields,
            }
            keys.append(key)

        for key in keys:
            row = report[key]
            symbol = row["position_id"]
            if not symbol:
                row.update(
                    disposition=self.FAILED, status="failed",
                    reason=f"[sweep {sweep}] the venue sent no symbol, so this position could not be addressed "
                           "and no close was sent for it",
                )
                continue
            row.update(
                disposition=self.FAILED, status="failed", _in_flight=True,
                reason=f"[sweep {sweep}] the close for this position was SENT and the outcome was never "
                       "observed. The position may or may not be closed and MUST be checked at the venue.",
            )
            try:
                order = await self._call("close_position", symbol)
            except Exception as exc:  # noqa: BLE001 - ANY exception, loop CONTINUES
                earlier = self._confirmed_row_for(confirmed_in_a, symbol)
                if earlier is not None and _venue_says_position_does_not_exist(exc):
                    earlier["reason"] = (
                        f"{earlier['reason']}; [sweep b] the venue still LISTED this position after that close "
                        f"filled (listing lag), and refused the re-close: position does not exist "
                        f"(404, code {ALPACA_POSITION_DOES_NOT_EXIST_CODE})")
                    del report[key]
                    continue
                # `B440`: a close that failed ambiguously may have reached the venue — the operator is told which.
                kind = classify_submission_failure(exc)
                if kind == SUBMISSION_UNANSWERED:
                    prefix = ("the close MAY HAVE REACHED the venue and no answer came — the position may be "
                              "closed or still open and MUST be checked at the venue")
                else:
                    prefix = "the venue did not take this close"
                row.update(
                    disposition=self.FAILED, status="failed", _in_flight=False,
                    reason=f"[sweep {sweep}] {prefix}: {type(exc).__name__}: {exc}",
                )
                continue
            try:
                # `B427`: the close order is RESOLVED; CLOSED only for a confirmed fill (`_close_disposition`).
                outcome = await self._close_outcome(order)
                disposition = self._close_disposition(outcome)
                disposition["reason"] = (f"[sweep {sweep}] {disposition['reason']}" if disposition.get("reason")
                                         else f"[sweep {sweep}] the close order was confirmed FILLED")
                row.update(**disposition, close=outcome, _in_flight=False)
            except Exception as exc:  # noqa: BLE001 - ANY exception, loop CONTINUES (review's X-16)
                row.update(
                    disposition=self.FAILED, status="failed", _in_flight=False,
                    reason=(f"[sweep {sweep}] the close was SENT (order {getattr(order, 'id', None)}) but its "
                            f"outcome could not be read ({type(exc).__name__}: {exc}) — the position MUST be "
                            f"checked at the venue"),
                )

    async def _close_sweep_b(self, report: dict[str, dict], started: float) -> None:
        """Sweep (b): wait (bounded) for an entry in flight on this account, re-enumerate, close what is new."""
        derived = entry_lock_normal_hold_bound_s(self._client)
        remaining = KILL_SWITCH_RESPONSE_DEADLINE_S - (self._clock() - started)
        wait = max(0.0, min(derived, remaining))
        deadline_bounded = remaining < derived
        try:
            account = _account_lock(self._account_key)
        except AccountLockLoopConflict as conflict:
            self._in_flight_entry_row(report, conflict.holder, 0.0, derived, deadline_bounded, conflict=True)
            await self._sweep_b_closes(report, derived)
            return

        async with _holding_with_bounded_wait(account.lock, wait) as acquired:
            if not acquired:
                self._in_flight_entry_row(report, account.holder, wait, derived, deadline_bounded, conflict=False)
                await self._sweep_b_closes(report, derived)
                return
            account.holder = {"symbol": None, "client_order_id": None,
                              "what": "close_all_positions sweep (b)", "since": time.monotonic()}
            try:
                await self._sweep_b_closes(report, derived)
            finally:
                account.holder = None

    async def _sweep_b_closes(self, report: dict[str, dict], derived: float) -> None:
        try:
            positions = await self._raw_positions()
        except Exception as exc:  # noqa: BLE001 - (a)'s rows stand; what (b) could not see is said, not dropped
            report["b#enumeration"] = {
                "position_id": "", "pair": "UNKNOWN", "disposition": self.NOT_ATTEMPTED, "status": "failed",
                "sweep": "b", "lock_wait_bound_s": derived,
                "reason": (f"[sweep b] the second enumeration FAILED ({type(exc).__name__}: {exc}), so a position "
                           f"opened after sweep (a) enumerated — by an entry that was in flight when the switch "
                           f"was pulled — is NOT in this report and was NOT closed. Check the venue."),
            }
            return

        swept = [r for r in report.values() if r.get("sweep") == "a" and r.get("position_id")]
        to_close, left = [], []
        for raw in positions:
            symbol = str(getattr(raw, "symbol", "") or "").strip()
            earlier = [r for r in swept if symbol and self._same_symbol(r["position_id"], symbol)]
            if earlier and any(r["disposition"] != self.CLOSED for r in earlier):
                left.append(symbol)   # (a)'s close FAILED or is unconfirmed and may still be working: never a second sell
                continue
            to_close.append(raw)
        if left:
            logger.warning(
                "alpaca.close_all.sweep_b_left_open — still open after sweep (a) sent a close that FAILED or is "
                "unconfirmed; NOT closed again (a second close is a second sell). Sweep (a)'s rows report them.",
                symbols=left,
            )
        confirmed = {r["position_id"]: r for r in swept if r["disposition"] == self.CLOSED}
        await self._close_sweep(report, "b", to_close, confirmed_in_a=confirmed, lock_wait_bound_s=derived)

    def _confirmed_row_for(self, confirmed_in_a: dict[str, dict] | None, symbol: str) -> dict | None:
        """The row in which sweep (a) CONFIRMED this symbol CLOSED, or None."""
        for position_id, row in (confirmed_in_a or {}).items():
            if self._same_symbol(position_id, symbol):
                return row
        return None

    def _in_flight_entry_row(self, report, holder, waited, derived, deadline_bounded, *, conflict: bool) -> None:
        """**The expiry row** (manager's ruling 5, review's K2-15): NOT_ATTEMPTED, naming the entry's symbol AND
        client_order_id, saying it MAY EXIST — counted among NOT ATTEMPTED (still open). It over-alarms when the
        entry ends unfilled, which is the right direction."""
        holder = holder or {}
        who = _describe_holder(holder)
        if conflict:
            why = ("this account's order lock belongs to a DIFFERENT live event loop, so no mutual exclusion was "
                   "possible and sweep (b) did not wait")
        elif deadline_bounded:
            why = (f"sweep (b) waited {waited:.1f}s of the up to {derived:.1f}s (8C + B, an estimate) an in-flight entry may need, "
                   f"because the report must return before the proxy cuts the request "
                   f"(KILL_SWITCH_RESPONSE_DEADLINE_S = {KILL_SWITCH_RESPONSE_DEADLINE_S:.0f}s from the start of "
                   f"close_all_positions)")
        else:
            why = (f"sweep (b)'s {waited:.1f}s wait for it expired — the up to {derived:.1f}s (8C + B, an estimate) an in-flight "
                   f"entry may need")
        report["b#in_flight_entry"] = {
            "position_id": str(holder.get("symbol") or ""),
            "pair": str(holder.get("symbol") or "UNKNOWN"),
            "client_order_id": holder.get("client_order_id"),
            "disposition": self.NOT_ATTEMPTED,
            "status": "failed",
            "sweep": "b",
            "lock_wait_bound_s": derived,
            "waited_s": round(waited, 3),
            "deadline_bounded": bool(deadline_bounded and not conflict),
            "reason": (f"[sweep b] {who} was still being placed: {why}. That entry MAY EXIST at the venue — any "
                       f"position it opens was NOT enumerated and NOT closed. Check the venue."),
        }
        logger.error(
            "alpaca.close_all.in_flight_entry_not_waited_for — sweep (b) enumerated WITHOUT the account's order "
            "lock; a position the in-flight entry opens is not in this report",
            symbol=holder.get("symbol"), client_order_id=holder.get("client_order_id"), holder=holder.get("what"),
            waited_s=round(waited, 3), lock_wait_bound_s=derived, deadline_bounded=deadline_bounded,
            loop_conflict=conflict,
        )

    def _close_disposition(self, outcome: dict) -> dict:
        """A resolved close, in the kill switch's ruled vocabulary. **A response is not a close** (`B367`).

        **`B439`. THIS REPLACED `_classify_close`, WHICH READ THE WRONG METHOD'S RETURN TYPE.** It treated
        the result of `close_position(symbol)` as a `ClosePositionResponse` and did `int(result.status)`;
        on the `Order` that method really returns, `.status` is an `OrderStatus`, so `int()` raised for
        EVERY status — outside the per-position `try` — and the kill switch ended after its first
        position, reporting every other one NOT_ATTEMPTED. Its tests stayed green because their double
        returned the other method's type.

        CLOSED only for a CONFIRMED close — terminal and FILLED. Anything else is FAILED WITH A REASON,
        because that is where *outcome unknown* belongs and why no fourth disposition exists (`B337`):
        a close SUBMITTED and not confirmed inside the budget may still fill, or may not, and the reason
        says so.
        """
        if outcome["close_confirmed"]:
            return {"disposition": self.CLOSED, "status": "closed", "reason": None}
        seen = (f"venue status {outcome['venue_status']!r}, filled {outcome['filled_units']!r}, "
                f"{outcome['resolution']['reads']} read(s) over {outcome['resolution']['elapsed_s']}s")
        if outcome["status"] == "REJECTED":
            reason = (f"the venue ENDED this close unfilled ({seen}) — the position is still OPEN "
                      f"and must be closed another way")
        elif outcome["status"] == "PARTIALLY_FILLED":
            reason = (f"the close PARTIALLY filled ({seen}) — part of the position is still OPEN "
                      f"and MUST be checked at the venue")
        else:
            reason = (f"the close was SUBMITTED and NOT CONFIRMED within "
                      f"{outcome['resolution']['budget_s']}s ({seen}) — the position may still be open "
                      f"and MUST be checked at the venue")
        return {"disposition": self.FAILED, "status": "failed", "reason": reason}

    async def stream_prices(self, pairs: list[str], callback: Callable) -> None:
        """Poll per pair. Alpaca has a websocket feed; this shape is what the contract requires."""
        while self.connected:
            for pair in pairs:
                price = await self.reference_price(pair)
                if price is not None:
                    result = callback(pair, price)
                    if asyncio.iscoroutine(result):
                        await result
            await asyncio.sleep(1)
