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
import time
from datetime import datetime, timezone
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from app.core.exceptions import BrokerError, DirectionNotSupported
from app.core.kill_switch_state import KILL_SWITCH_RESPONSE_DEADLINE_S, refuse_if_armed
from app.core.logging import logger, redact_for_storage
from app.db.enums import DirectionType
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


#: **`B429` / R-10. How many open orders the flat-check asks for, and why it is modest.**
#:
#: `TradingClient.get_orders` is ONE request with no pagination, so the answer is a PAGE. A page that
#: comes back FULL may have truncated the order being looked for, so a full page is a failed
#: observation and halts. That test is only sound if a full page is recognisable: request 500 from a
#: server that silently caps at, say, 100, and the page comes back SHORTER than requested — reading
#: as complete while being a prefix. So N is kept well under any plausible cap.
#:
#: **RESIDUAL, NOT CLOSED:** fullness is tested against the requested limit; a server cap below it
#: would defeat this. The cap is unmeasured from this repository.
#:
#: The request also sends `direction=desc`, so the entry and close this remediation JUST created sort
#: onto page one and truncation can only drop OLDER orders. **That narrows the residual; it does not
#: close it** — newest-first is the server's sort order and is as unmeasured as the cap, and a stale
#: resting order for this symbol from earlier still depends on N staying under the cap.
FLAT_CHECK_ORDER_LIMIT = 100

#: **`B429`. The ONLY statuses in which a stop leg counts as protection.** AFFIRMATIVELY WORKING
#: ONLY, and the narrowness is argued from asymmetric cost rather than from any reading of the
#: venue's docs:
#:
#:     wrongly EXCLUDE a working status   -> a needless cancel-and-close. Safe, and unreachable today (B430).
#:     wrongly INCLUDE a non-working one  -> a refused stop reads as protected. That IS B429.
#:
#: `held` is the member that must be right — bracket legs wait in it for the parent to fill, and
#: omitting it would remediate every bracket. `accepted`, `pending_new` and `accepted_for_bidding`
#: are pre-acceptance or pre-routing and are EXCLUDED until measured; so are `partially_filled`,
#: `filled`, `pending_replace`, `pending_review` and anything not yet named.
#:
#: **MEMBERSHIP IS UNMEASURED.** Probe 3 places through `place_order`, so it is the evidence to widen
#: this set: if the venue parks stop legs in `accepted`, probe 3 over-remediates its own position and
#: records the status — an informative outcome, not a failure.
#:
#: RESIDUAL, stated rather than special-cased: a stop leg already `filled` at the re-read means the
#: position was stopped out within milliseconds. Remediation then observes flat and files
#: `PROTECTION_NOT_ACCEPTED`, which is false — the protection was accepted and fired. Near-unreachable.
#:
#: RESIDUAL N-1 (review), stated rather than closed: **a stop leg read `new` may not yet be
#: validated; a refusal that completes after the re-read is not caught here.** `new` is overloaded between
#: "validated and active" and "not yet validated", and one read cannot split them. **`B427` did not close
#: this:** its resolver re-reads the PARENT until terminal and does not re-check the stop leg, so a leg
#: refused after the protection read is still unseen.
#:
#: What always-re-reading DOES buy: it catches a refusal that has COMPLETED by the time of the GET;
#: it returns legs the POST response omitted (`Order.legs` is Optional, `nested=True` rolls them up);
#: and it removes the short-circuit that read protection off the acknowledgement. `new` stays on the list regardless — a filled
#: bracket's working stop plausibly reads `new`, and dropping it would remediate correctly protected
#: positions.
WORKING_STOP_LEG_STATUSES: frozenset[str] = frozenset({"new", "held"})

#: Order statuses after which an order can no longer fill. Anything NOT here — including a status
#: nobody has named yet — is treated as still able to fill: cancelled by remediation, and NOT flat.
#:
#: **This set decides FLAT, so its cost is the allow-list's argument inverted:** wrongly including a
#: resumable status reads a live order as finished — a false flat, which is B429 — while wrongly
#: excluding a terminal one only over-halts. Hence:
#:
#:     `done_for_day` is NOT terminal — it names its own impermanence and can fill on a later day.
#:                    (Probably unreachable on crypto, which trades continuously; excluded anyway,
#:                    because it is the false-flat direction and it must agree with this definition.)
#:     `stopped`, `suspended`, `calculated` are NOT terminal — anything that might still fill is live.
#:     `replaced` IS terminal for the object itself: the replaced order cannot fill and its successor
#:                    carries a NEW id. This path never calls `replace_order`, so no successor arises
#:                    here — do not reason "replaced is terminal, therefore flat" about a
#:                    venue-initiated replacement, whose successor this set says nothing about.
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
    """**How long an entry on the NORMAL path may hold its account's lock: 3C + B** (manager's ruling 3c).

        C = one SDK call = (retry + 1) · (connect + read) + retry · retry_wait     retries and sleep read LIVE
        B = ORDER_RESOLUTION_BUDGET_S
        normal path = submit (C) + protection re-read (C) + resolution (B + C)

    Read from the live module constants and the client at call time, never a literal (review's K2-14). For
    `build_trading_client`'s client at alpaca-py 0.44.0 — retry 3, retry_wait 3s, connect 3s, read 10s, budget
    5s — C = 61s and **3C + B = 188s**; with no 429 retry C = 13s and it is 44s.

    **NOT THE WORST CASE, deliberately.** An ambiguous submission adds a lookup (4C + 2B) and a protection
    failure's remediation reaches 9C + B; the latter closes its own position, and the kill switch's expiry row
    reports whatever was not waited for. `close_all_positions` also caps the wait at
    `KILL_SWITCH_RESPONSE_DEADLINE_S` from its own start, because 188s is past the proxy's cut (`B443`).
    """
    retry, wait = _client_retry_settings(client)
    call = (retry + 1) * (ALPACA_HTTP_CONNECT_TIMEOUT_S + ALPACA_HTTP_READ_TIMEOUT_S) + retry * wait
    return 3 * call + ORDER_RESOLUTION_BUDGET_S


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

#: The largest `FLAT_CHECK_ORDER_LIMIT` the full-page guard is argued safe for — an arm asserts the
#: bound, because a test double never caps and so no behavioural arm can tell 100 from 10000.
FLAT_CHECK_ORDER_LIMIT_CEILING = 200


class AlpacaProtectionNotAccepted(BrokerError):
    """The venue took the order and did NOT take the stop — and FLAT WAS THEN OBSERVED.

    **`B429`.** `place_order` attaches `stop_loss`/`take_profit` and then READS THE RESPONSE BACK.
    A venue that REFUSES a bracket raises, which is safe: no position, loud error. A venue that
    ACCEPTS the order and ignores the attachment leaves a position nobody is protecting, and
    nothing downstream would ever ask — so absence of the protection on the response is treated as
    a failure: the entry is cancelled, any position is closed, and flat is OBSERVED before this is
    raised — no position for the symbol, no open order or live leg for it ON THE OPEN-ORDER PAGE, and
    this order and its legs terminal. Scoped to what was checked, as `_observe_flat`'s own line is.

    **ITS OWN TYPE BECAUSE IT MAPS TO ITS OWN CODE**, for `AlpacaBelowMinimumSize`'s reason: filed
    as `VENUE_TRANSPORT` it would read as a transient blip that clears on its own. It is not
    transient: it recurs for as long as the observed condition holds — the venue created no working
    stop, OR it parked one in a status `WORKING_STOP_LEG_STATUSES` does not yet admit, in which case
    that unmeasured list is too narrow and the venue refused nothing. The message puts the re-read
    leg statuses, the entry's settled status and filled quantity, the remediation counts and the
    order id AHEAD of the prose, because only its first 300 characters are stored — so an operator,
    and probe 3's saved artefact, can tell which, and can tell whether a position ever existed.

    **Raised ONLY on observed flat**, so it is an ordinary rejection — no position exists and the
    decision is correctly recorded as not taken. The first version raised this whenever the close
    call did not throw, which is an ACCEPTED close, not a filled one (review's REVIEW_FAIL).
    """


class AlpacaUnprotectedPositionOpen(BrokerError):
    """**The protection was not accepted AND flat could not be observed afterwards.**

    The one state this codebase must never reach quietly: a live position, no stop at the venue,
    no stop in process (`B428` — this adapter has no `on_tick`), and the size derived from a stop
    that was never placed.

    **NOT A REJECTION, and that distinction is the whole point.** `crypto_loop`'s order-path
    handler records `REJECTION_VENUE_RAISED` for anything the broker raises — a row asserting no
    position was taken. Here a position IS open, so that row would be false in the direction that
    hides the danger, which is the `PARTIALLY_FILLED`-recorded-as-refused defect one venue along.
    The loop branches on this type and HALTS instead.
    """

    def __init__(self, *, symbol: str, order_id: str, detail: str) -> None:
        super().__init__(
            f"UNPROTECTED POSITION MAY BE OPEN at Alpaca on {symbol}: the venue did not accept "
            f"the stop and flat was NOT observed after remediation ({detail}). Order {order_id}. "
            f"There "
            f"is no stop at the venue and none in process — reconcile at the venue before "
            f"restarting.",
            broker="alpaca",
        )
        self.symbol = symbol
        self.order_id = order_id
        self.detail = detail


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

    broker_name = "alpaca"

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

    async def _call(self, name: str, *args, **kwargs) -> Any:
        """One place where a venue call becomes our error (`B340`).

        `T-0106` grew seven copies of its rate-limit dispatch and five of them could be INVERTED
        with the suite green. One dispatch from the start.
        """
        method = getattr(self._client, name, None)
        if method is None:
            raise BrokerError(
                f"the Alpaca client has no {name!r}. Every member this adapter calls is on "
                f"TradingClient — see {SHAPES}.", broker=self.broker_name,
            )
        try:
            result = method(*args, **kwargs)
            if asyncio.iscoroutine(result):
                result = await result
            return result
        except BrokerError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise BrokerError(
                f"Alpaca {name} failed: {type(exc).__name__}: {exc}", broker=self.broker_name,
            ) from exc

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

        from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
        from alpaca.trading.requests import (
            MarketOrderRequest, StopLossRequest, TakeProfitRequest,
        )

        # ------------------------------------------------------------------
        # `B429`. **THE PROTECTION GOES WITH THE ORDER, OR THE ORDER DOES NOT GO.**
        #
        # This method received `request.sl` and `request.tp` and **discarded both**. Not ignored
        # in the harmless sense: `execution/service.py:174` SIZES THE POSITION FROM `sig.sl` and
        # `:166` refuses to trade when price is already through it — so the risk model was
        # computed from a stop nothing placed. Worse than dropping an input, because the dropped
        # input was still being used to justify the quantity.
        #
        # And nothing else would have caught it. The only SL/TP enforcement in this codebase is
        # `PaperBroker.on_tick` and `cft_sim.on_tick`, both simulators; `AlpacaAdapter` has no
        # `on_tick` at all (`B428`). So a live position here had no stop at the venue and no stop
        # in process.
        #
        # **THE CONTRACT IS ALREADY WRITTEN IN THIS FILE**, twenty lines down, on
        # `close_position`: *"HONOUR `lot_size` rather than ignore it — the contract is honour it
        # or refuse loudly, and silently closing everything when a caller asked for 30% is the
        # ambiguity that contract exists to prevent."* Same file, same question, one honoured.
        #
        # `cryptofundtrader.py:666` and `oanda.py:420` both attach the stop. Alpaca was the only
        # adapter that dropped it.
        # ------------------------------------------------------------------
        protection: dict = {}
        if request.sl is not None and request.tp is not None:
            protection = {
                "order_class": OrderClass.BRACKET,
                "stop_loss": StopLossRequest(stop_price=float(request.sl)),
                "take_profit": TakeProfitRequest(limit_price=float(request.tp)),
            }
        elif request.sl is not None:
            # **STOP-ONLY IS ITS OWN SHAPE, not a bracket with a missing leg.** `sig.tp` is
            # legitimately `None` on this path (`crypto_loop.py:1023`, `:1899` both guard it)
            # while `sl` is what the size was computed from, so this is the case that must work.
            # Alpaca spells a stop-only attachment `OTO`; `BRACKET` requires both legs and would
            # be refused.
            protection = {
                "order_class": OrderClass.OTO,
                "stop_loss": StopLossRequest(stop_price=float(request.sl)),
            }

        # `str(quantity)` — the venue types quantities as strings and the SDK does not coerce, so
        # handing it a float would send `0.30000000000000004` for a third of a position.
        order = MarketOrderRequest(
            symbol=request.pair,
            qty=str(quantity),
            side=OrderSide.BUY if request.direction == DirectionType.LONG else OrderSide.SELL,
            time_in_force=TimeInForce.GTC,
            client_order_id=request.client_order_id,
            **protection,
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
                return await self._submit_and_resolve(order, request, protection, quantity, requested, limits)
            finally:
                account.holder = None

    async def _submit_and_resolve(self, order, request, protection, quantity, requested, limits) -> dict:
        """Submission, the `B440` lookup, and the verdict — called ONLY by `place_order`, under the account lock."""
        try:
            placed = self._require_model(await self._call("submit_order", order), "submit_order")
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

        # ------------------------------------------------------------------
        # **AND VERIFY IT LANDED, because the dangerous failure is the SILENT one.**
        #
        # A venue that REFUSES a bracket raises, which is safe — no position, loud error. A venue
        # that ACCEPTS the order and ignores the protection leaves a naked position we believe is
        # protected, and nothing downstream would ever ask. Whether Alpaca supports brackets on
        # CRYPTO is not established — the SDK imposes no asset-class restriction, so the answer
        # lives on the server and no test here can reach it.
        #
        # So this does not assume either way: it reads back what the venue SAYS it created. The
        # response carries `order_class` and `legs`, so an ignored attachment is detectable rather
        # than invisible. **This turns the unknown into a loud failure instead of a quiet one**,
        # which is the only property available without placing a real order.
        # ------------------------------------------------------------------
        # **D3 (`B437`).** From here the order EXISTS at the venue. A cancellation during the protection check
        # or the resolution used to vanish with it — measured on a451ec1, no log line held the order id. It is
        # logged with everything needed to find the order, and re-raised.
        progress: dict = {"last_status": self._order_status(placed)}
        try:
            return await self._verdict_for_placed(placed, request, protection, quantity, requested, limits, progress)
        except asyncio.CancelledError:
            logger.error(
                "alpaca.order_cancelled_after_submission — the order EXISTS at the venue and this task was "
                "cancelled before its outcome was recorded. Find it by id before trading this symbol again.",
                order_id=str(getattr(placed, "id", "") or ""), client_order_id=request.client_order_id,
                symbol=request.pair, last_status=progress.get("last_status"),
            )
            raise

    async def _verdict_for_placed(self, placed, request, protection, quantity, requested, limits, progress) -> dict:
        """B429's protection check and B427's resolution for an order that EXISTS, mapped into the result."""
        first_read = None
        if protection:
            first_read = await self._require_protection(placed, request)

        # ------------------------------------------------------------------
        # **`B427`. THE ACKNOWLEDGEMENT IS NOT AN OUTCOME — RESOLVE THE ORDER, BOUNDED, THEN REPORT IT.**
        #
        # This returned the SUBMISSION RESPONSE's status and quantity. An order the venue ACCEPTED and
        # filled a moment later was classified at the moment of acceptance: before `T-0130` as a false
        # refusal, since `T-0130` as UNRESOLVED, which halts. So the order is re-read until it is terminal
        # or `ORDER_RESOLUTION_BUDGET_S` is spent, and the result maps the LATEST venue statement.
        # `B429`'s nested protection read is the first read, so a fill already terminal by then costs no
        # further request. On expiry the last status is reported as it is, and the loop's UNRESOLVED seam
        # halts — no second failure path.
        #
        # **Resolution lives HERE, not in the service or loop (manager's ruling A)**: probe 3 calls this
        # method directly, so this is the only place the real venue will exercise it before the engine does.
        # The acknowledgement is kept beside the verdict (`resolution.ack_*`), never overwritten.
        # ------------------------------------------------------------------
        resolved, resolution = await self._resolve_order(str(getattr(placed, "id", "") or ""), first_read, progress)
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

    async def _require_protection(self, placed, request):
        """**`B429`: the order stands only if a WORKING STOP LEG is observed. Otherwise remediate.**

        Detection alone is not a fix — raising without closing leaves exactly the state this entry
        describes. The achievable invariant is **NEVER LEAVE AN UNPROTECTED POSITION OPEN**:
        placement and protection are not atomic at this venue as far as anyone has established.

        **THE EVIDENCE, AND HOW IT GOT NARROWER THREE TIMES:**

            first      `order_class == wanted or legs`   any leg, any class — a take-profit alone passed
            S-1        a leg that is itself a STOP        a CANCELED stop leg still has a stop type
            this       a stop leg WHOSE STATUS IS WORKING, read from a nested RE-READ, every time

        *Order class alone is not evidence* — a parent can report `bracket` with its stop child
        `rejected` (review's P-1). *The POST response is not evidence either* — it is the
        ACKNOWLEDGEMENT, `B427`'s subject. So the order is re-read with `nested=True` on every call
        and the POST legs are logged, never the verdict. That catches a refusal already COMPLETE at
        the GET and legs the POST omitted; it does NOT catch a refusal completing after the GET on a
        leg that read `new` (residual N-1, stated at `WORKING_STOP_LEG_STATUSES`). One GET is the cost.

        A re-read that FAILS is not evidence of protection, and remediates.

        Not claimed: that Alpaca accepts a bracket or OTO on crypto, or which statuses its stop legs
        pass through. Everything here is driven against doubles; the venue was not consulted.
        """
        from alpaca.trading.requests import GetOrderByIdRequest

        wanted = "bracket" if (request.sl is not None and request.tp is not None) else "oto"
        got = self._protection_class(placed)
        post_legs = getattr(placed, "legs", None) or []
        order_id = str(getattr(placed, "id", "") or "unknown")

        reread = None
        reread_error = None
        try:
            reread = self._require_model(
                await self._call("get_order_by_id", order_id, GetOrderByIdRequest(nested=True)),
                "get_order_by_id")
        except Exception as exc:  # noqa: BLE001 - a failed re-read is not evidence; it remediates
            reread_error = f"{type(exc).__name__}: {exc}"

        legs = (getattr(reread, "legs", None) or []) if reread is not None else []
        if any(self._is_working_stop_leg(leg) for leg in legs):
            # `B427`: the nested re-read is handed back, to be the resolver's FIRST read.
            return reread

        logger.error(
            "alpaca.protection_not_observed — no WORKING stop leg on the nested re-read. "
            "Cancelling the entry and every live leg, closing any position, then OBSERVING flat.",
            symbol=request.pair, order_id=order_id, wanted=wanted, order_class=got,
            post_legs=[(self._order_status(l), self._leg_kind(l)) for l in post_legs],
            reread_legs=[(self._order_status(l), self._leg_kind(l)) for l in legs],
            reread_error=reread_error, sl=request.sl, tp=request.tp,
        )

        # ------------------------------------------------------------------
        # **REMEDIATION NOW RUNS ON A TREE WITH CHILDREN**, which the earlier version never saw:
        # parent `bracket`, stop child REFUSED, take-profit child STILL RESTING. Cancelling only the
        # parent leaves that TP live — and cancelling a FILLED parent raises anyway (R-9). So every
        # leg the re-read shows as non-terminal is cancelled by its own id, after the parent.
        #
        # **The verdict comes only from observation**, and a step failure is never the verdict: each
        # is attempted, logged at ERROR, and carried into the detail of whichever exception is raised.
        # ------------------------------------------------------------------
        steps: list[str] = []
        if reread_error is not None:
            steps.append(f"re-read FAILED ({reread_error}) — legs unknown, parent cancel only")

        to_cancel = [order_id] + [
            str(getattr(leg, "id", "")) for leg in legs
            if getattr(leg, "id", None) and self._order_status(leg) not in TERMINAL_ORDER_STATUSES
        ]
        cancel_ok = cancel_failed = 0
        for oid in to_cancel:
            try:
                await self._call("cancel_order_by_id", oid)
                cancel_ok += 1
                steps.append(f"cancel {oid} accepted")
            except Exception as exc:  # noqa: BLE001 - recorded; the observation decides
                cancel_failed += 1
                steps.append(f"cancel {oid} FAILED ({type(exc).__name__}: {exc})")
                logger.error("alpaca.protection_remediation.cancel_failed", symbol=request.pair,
                             order_id=oid, error=f"{type(exc).__name__}: {exc}")

        try:
            # BY SYMBOL: the entry may already have filled, and what has to go is the POSITION.
            # **The SDK call, not `self.close_position`** (`B427`): the public method now RESOLVES the close
            # order, and this remediation's verdict is the flat OBSERVATION below, not the close — a
            # manager's ruling on `B429` put no poll and no bound here. Whether remediation should wait for
            # its close to resolve is an open question for that ruling, not a side effect of this one.
            await self._call("close_position", request.pair)
            # **A SUBMISSION, not a fill** — named that way so an operator reading the halt can
            # tell a slow close from a failed one.
            close_view = "submitted"
            steps.append("close SUBMITTED, not yet observed filled")
        except Exception as exc:  # noqa: BLE001 - recorded; the observation decides
            close_view = "failed"
            steps.append(f"close FAILED ({type(exc).__name__}: {exc})")
            logger.error("alpaca.protection_remediation.close_failed", symbol=request.pair,
                         order_id=order_id, error=f"{type(exc).__name__}: {exc}")

        flat, observed, settled = await self._observe_flat(request.pair, order_id)
        detail = "; ".join(steps + [observed])

        if not flat:
            # NO POLL AND NO BOUND HERE (manager's ruling on `B429`). A close that has not filled YET is
            # "flat not observed" and halts. That over-halts, which is the right direction. `B427` added
            # bounded resolution to `place_order` and the public closes but deliberately NOT to this
            # remediation's close (it calls the SDK directly), so this behaviour is unchanged; whether
            # remediation should wait for its close is a separate ruling. Unreachable today (`B430`).
            raise AlpacaUnprotectedPositionOpen(symbol=request.pair, order_id=order_id,
                                                detail=detail)

        # **FACTS FIRST, PROSE LAST** (manager's ruling, from review's REVIEW_PASS finding on a4b9a34).
        #
        # This string is stored as `redact_for_storage(str(exc))`, bounded at 300 characters, and
        # `rejection_reason` is the ONLY durable link from the decision row to the venue order — none of
        # the 29 `DecisionRecord` columns holds an order id. At a real 36-character id, a4b9a34's layout
        # stored BYTE-IDENTICAL rows for "entry filled, a real unprotected position existed, remediation
        # closed it" and "entry never filled": the steps that told them apart sat past the bound. So
        # every fact gets a compact token ahead of the prose, and `{detail}` may truncate harmlessly.
        #
        #   entry=   the parent's TERMINAL status and filled quantity from the POST-remediation read,
        #            once the state has settled. NOT the protection re-read, which happens BEFORE
        #            remediation: a market entry can read `new` there and fill before the cancel lands.
        #            And NOT status alone: a partial fill whose remainder is cancelled ends `canceled`
        #            with a NON-ZERO filled quantity — a real position existed. `unknown` only if that
        #            read is missing, which cannot happen on this path: a failed observation raises
        #            AlpacaUnprotectedPositionOpen instead of reaching here.
        #   cancel=  accepted/failed counts across the parent and every live leg
        #   close=   submitted / failed
        #   order=   the venue order id, so an operator can find it
        #
        # legs= stays FIRST because the (status, kind) pairs are the datum probe 3 exists to produce:
        # which status the venue parks a stop leg in. And the message makes NO PREDICTION that the
        # venue will refuse the same order again — that is false in exactly the case where a working
        # stop sits in a status the allow-list does not admit, and then the venue refused nothing.
        leg_view = ("re-read FAILED" if reread_error is not None else
                    ",".join(f"{self._order_status(l) or '?'}/{self._leg_kind(l) or '?'}" for l in legs)
                    or "none")
        if settled is None:
            entry_view = "unknown"
        else:
            entry_view = (f"{self._order_status(settled) or '?'}/"
                          f"{self._qty_token(getattr(settled, 'filled_qty', None))}")
        raise AlpacaProtectionNotAccepted(
            f"{request.pair} legs=[{leg_view}] entry={entry_view} "
            f"cancel={cancel_ok}ok/{cancel_failed}failed close={close_view} order={order_id} "
            f"(no working stop leg; a stop in another working status means the allow-list is too "
            f"narrow) Remediation: {detail}",
            broker="alpaca",
        )

    @staticmethod
    def _qty_token(raw) -> str:
        """A filled quantity as it goes into the stored refusal: the VENUE'S OWN VALUE, or `?`.

        `Order.filled_qty` is `str | float | None`, default `None`, and it has THREE states — every
        collapse of two of them is a false fact in the one field that records whether exposure happened:

            absent / blank / unparseable / non-finite   -> "?"
            present, numerically zero           -> the value as sent, whitespace-stripped ("0", "0.000")
            present, numerically non-zero       -> the value as sent, whitespace-stripped ("0.00001294")

        * **Absent is not zero** (review): rendering `None` as `0` stores `canceled/0`, "never filled",
          for a quantity nobody read.
        * **NaN is neither branch** (manager): `nan == 0` and `nan > 0` are both False, so any zero test
          files it on one side or the other. It is tested for explicitly.
        * **Parse to decide, store what came in** (manager): `str(float("0.00001294"))` is `1.294e-05`,
          which no longer matches the venue and will not be found by anyone searching for it. A string
          is kept as sent with only surrounding whitespace STRIPPED (not verbatim: " 0.5 " stores `0.5`,
          which keeps the token free of the space that terminates it); a float — which has no text of its
          own — is written positionally via Decimal.
        """
        from decimal import Decimal

        value = readable_quantity(raw)
        if value is None:
            return "?"
        if isinstance(raw, str):
            return raw.strip()
        return format(Decimal(repr(value)), "f")

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

        Returns `(last_order_read_or_first_read, resolution)`. `first_read` is a re-read ALREADY made —
        `B429`'s nested protection read — so a fill that is terminal by then costs no further request.
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
        unreadable status is `""`, which is in neither `WORKING_STOP_LEG_STATUSES` nor
        `TERMINAL_ORDER_STATUSES`: not protection, and still able to fill.
        """
        raw = getattr(order, "status", None)
        return str(getattr(raw, "value", raw) or "").lower()

    @staticmethod
    def _leg_kind(leg) -> str:
        raw = getattr(leg, "order_type", None) or getattr(leg, "type", None)
        return str(getattr(raw, "value", raw) or "").lower()

    @classmethod
    def _is_working_stop_leg(cls, leg) -> bool:
        """A stop leg AND in an affirmatively working status. Both halves are required: a canceled
        stop leg is still a stop type with a `stop_price` (P-2)."""
        return cls._is_stop_leg(leg) and cls._order_status(leg) in WORKING_STOP_LEG_STATUSES

    @staticmethod
    def _is_stop_leg(leg) -> bool:
        """True only for a leg the venue created AS A STOP: a stop-family order type, or a
        `stop_price`. A limit leg is a take-profit and protects nothing on the downside.

        Reads `.value` for the enum (`B411`'s trap — `str(OrderType.STOP)` is `'OrderType.STOP'`),
        and treats an unreadable leg as NOT a stop, because this is the check that must refuse on
        doubt.
        """
        raw = getattr(leg, "order_type", None) or getattr(leg, "type", None)
        kind = str(getattr(raw, "value", raw) or "").lower()
        if kind in ("stop", "stop_limit", "trailing_stop"):
            return True
        return getattr(leg, "stop_price", None) not in (None, "", 0, "0")

    @staticmethod
    def _same_symbol(a: object, b: str) -> bool:
        """Compare venue symbols with the separator removed.

        Alpaca writes crypto ORDERS as `BTC/USD`; whether a POSITION comes back as `BTC/USD` or
        `BTCUSD` has not been observed from this repository. An exact comparison would, under the
        second form, report *no position for this symbol* and read as FLAT — a false flat on the
        one check whose whole job is to refuse one. Normalising both sides is correct under either
        form, so the question does not need answering to be safe.
        """
        norm = lambda v: str(v or "").replace("/", "").replace("-", "").upper()  # noqa: E731
        return norm(a) == norm(b)

    async def _observe_flat(self, symbol: str, order_id: str) -> tuple[bool, str, object | None]:
        """**Positive evidence of flat, or not flat.** Returns `(flat, what_was_observed, settled_parent)`.

        `settled_parent` is this order as re-read AFTER remediation — returned as DATA, not only
        printed, because the refusal's `entry=` token is built from its terminal status and filled
        quantity. It is `None` whenever flat was not observed that far.

        THREE observations, because each alone reads a live state as flat:

            positions          a resting close, entry, or take-profit leg is invisible
            open orders        a filled position with no order left is invisible
            THIS order, by id  a filled PARENT may be excluded by `status=OPEN`, taking its still-resting
                               take-profit leg (rolled up under it by `nested=True`) out of the list with
                               it — so the orders this remediation created are re-read directly and every
                               leg must be terminal

        **AN OBSERVATION THAT CANNOT BE MADE IS NOT EVIDENCE OF FLAT.** Every failure returns `False`: a
        query that raises, and an open-orders page that came back FULL, which could have truncated the
        order this is looking for. No helper that turns an error into an empty list is used —
        `_raw_positions` raises through `_call`, and orders are queried here directly because
        a bounded, newest-first, nested query is needed that the adapter's `get_orders` does not make —
        it honours a status filter since `B427` but is still unpaginated.

        Orders are fetched with `nested=True` so child legs are visible, and the symbol is NOT flat if
        any order OR ANY OF ITS LEGS for it is non-terminal. R-10's page limit counts parents; legs
        arrive with them.
        """
        from alpaca.common.enums import Sort
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrderByIdRequest, GetOrdersRequest

        limit = FLAT_CHECK_ORDER_LIMIT
        try:
            positions = await self._raw_positions()
        except Exception as exc:  # noqa: BLE001 - an unmakeable observation is NOT flat
            return False, f"flat NOT OBSERVED: position query failed ({type(exc).__name__}: {exc})", None

        held = [p for p in positions if self._same_symbol(getattr(p, "symbol", None), symbol)]
        if held:
            return False, f"flat NOT OBSERVED: {len(held)} position(s) still open for {symbol}", None

        try:
            # EVERY FIELD STATED, none left to a server default: OPEN, an explicit limit (R-10),
            # newest first (narrows R-10), nested so legs are visible, and NO `symbols` filter —
            # server-side filtering matches on a spelling nobody has measured (R-7).
            orders = await self._call("get_orders", GetOrdersRequest(
                status=QueryOrderStatus.OPEN, limit=limit, direction=Sort.DESC, nested=True)) or []
            self._require_model(orders, "get_orders")
        except Exception as exc:  # noqa: BLE001 - an unmakeable observation is NOT flat
            return False, f"flat NOT OBSERVED: open-order query failed ({type(exc).__name__}: {exc})", None

        if len(orders) >= limit:
            return False, (f"flat NOT OBSERVED: open-order page returned {len(orders)} — full, so "
                           f"an order for {symbol} may have been truncated"), None

        resting = [o for o in orders if self._same_symbol(getattr(o, "symbol", None), symbol)]
        if resting:
            return False, f"flat NOT OBSERVED: {len(resting)} open order(s) still resting for {symbol}", None
        live_legs = [
            leg for o in orders for leg in (getattr(o, "legs", None) or [])
            if self._same_symbol(getattr(leg, "symbol", None), symbol)
            and self._order_status(leg) not in TERMINAL_ORDER_STATUSES
        ]
        if live_legs:
            return False, f"flat NOT OBSERVED: {len(live_legs)} child leg(s) still live for {symbol}", None

        try:
            mine = self._require_model(
                await self._call("get_order_by_id", order_id, GetOrderByIdRequest(nested=True)),
                "get_order_by_id")
        except Exception as exc:  # noqa: BLE001 - an unmakeable observation is NOT flat
            return False, (f"flat NOT OBSERVED: re-read of order {order_id} failed "
                           f"({type(exc).__name__}: {exc})"), None

        unfinished = [o for o in [mine] + list(getattr(mine, "legs", None) or [])
                      if self._order_status(o) not in TERMINAL_ORDER_STATUSES]
        if unfinished:
            parts = ", ".join(self._order_status(o) or "?" for o in unfinished)
            return False, (f"flat NOT OBSERVED: order {order_id} still has {len(unfinished)} "
                           f"non-terminal part(s) ({parts})"), None

        # **SCOPED TO WHAT WAS CHECKED** (review). The earlier "no position, no open order or live leg
        # for <symbol>" was false in exactly one tree: a DIFFERENT filled parent's take-profit still
        # resting, rolled up under a parent the OPEN listing excludes. A log line is read in the
        # moment, so the scope goes in the line, not in a caveat after it. The "flat OBSERVED" prefix
        # is kept — four arms assert it, and it is not a substring of "flat NOT OBSERVED".
        return True, (f"flat OBSERVED: no position for {symbol}; no open order or live leg for it on "
                      f"the open-order page; order {order_id} and its legs terminal"), mine

    @staticmethod
    def _protection_class(placed) -> str | None:
        """`placed.order_class` as a plain lowercase string, or `None` when it cannot be read.

        The SDK types it as an enum, and `str(OrderClass.BRACKET)` is `'OrderClass.BRACKET'` while
        the member equals `'bracket'` — the `B411` trap, which cost a fill predicate that never
        fired. Read `.value` explicitly.
        """
        raw = getattr(placed, "order_class", None)
        if raw is None:
            return None
        return str(getattr(raw, "value", raw)).lower() or None

    async def close_position(self, position_id: str, lot_size: float | None = None) -> dict:
        """Close by symbol, and **HONOUR `lot_size` rather than ignore it** (`T-0038`).

        The contract is *honour it or refuse loudly*, and silently closing everything when a
        caller asked for 30% is the ambiguity that contract exists to prevent. **This is not
        theoretical here:** the exit ladder is 70% at 2R with a 30% runner (`EXIT-001`), and
        `crypto_loop.py:1006` calls this with a `lot_size` on every partial exit — so ignoring it
        would liquidate the runner and make the ladder unobservable.

        Alpaca expresses it as `ClosePositionRequest(qty=...)`. **Imported inside the method**, for
        `B328`'s reason: this module must stay importable without the SDK.
        """
        # **`B427`/`B438`. THE CLOSE IS AN ORDER, AND AN ACCEPTED ORDER IS NOT A CLOSED POSITION.** This
        # returned `str(result)` and nothing else, so the close order's status and filled quantity were
        # discarded and a caller could not tell "the close was accepted" from "the close filled" —
        # `positions.py` read the missing status as closed. The close order is resolved with the same
        # resolver and budget as an entry, and `close_confirmed` is True ONLY for a terminal FILLED close.
        if lot_size is None:
            order = await self._call("close_position", position_id)
            return {"position_id": position_id, "partial": False, **(await self._close_outcome(order))}

        from alpaca.trading.requests import ClosePositionRequest

        # `qty` IS A STRING ON THIS VENUE. Passing a float would send `0.30000000000000004` for a
        # third of a position; the venue types it as a string and the SDK does not coerce.
        options = ClosePositionRequest(qty=str(lot_size))
        order = await self._call("close_position", position_id, options)
        return {"position_id": position_id, "partial": True, "qty": str(lot_size),
                **(await self._close_outcome(order))}

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
        open position hostage to one entry — up to 3C + B, 188s for the builder's client — on the degraded venue
        where the switch is most likely pulled. So:

            (a) enumerate and close NOW, taking no lock;
            (b) then take this account's order lock — the entry holds it through its verdict — with a wait of
                min(3C + B, KILL_SWITCH_RESPONSE_DEADLINE_S − elapsed since this method started), floored at 0;
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
            why = (f"sweep (b) waited {waited:.1f}s of the up to {derived:.1f}s (3C + B) an in-flight entry may need, "
                   f"because the report must return before the proxy cuts the request "
                   f"(KILL_SWITCH_RESPONSE_DEADLINE_S = {KILL_SWITCH_RESPONSE_DEADLINE_S:.0f}s from the start of "
                   f"close_all_positions)")
        else:
            why = (f"sweep (b)'s {waited:.1f}s wait for it expired — the up to {derived:.1f}s (3C + B) an in-flight "
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
