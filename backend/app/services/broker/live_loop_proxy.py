"""T-0062 / `B221` — a forwarding proxy so the manager can never hold a stale broker.

`main.py` registers the live loop's broker with `broker_manager` ONCE at startup. Every
`POST /engine/start` runs `_reset_broker_state`, which REBINDS `loop.paper` to a freshly
constructed broker and does not re-register — so `_adapters["paper"]` held an orphan, and in
`PROP_FIRM_SIM` (this deployment) it was a different CLASS, not merely a stale instance.
`close_all_positions` iterated it, got `[]`, and the kill switch reported success while the
position stayed open.

**THE SHAPE: register something that IS a `BrokerAdapter` and resolves the target AT CALL
TIME.** Not "re-register after the reset" — that synchronises ONE construction site, and its
failure mode is a third site that does not exist yet, which no behavioural test can range
over; the only guard would be a structural predicate over assignments to `self.paper`, which
is `B191`/`B196` exactly. Not "store a callable in `_adapters`" either — six sites iterate
that dict and call methods on the value, one of which IS `close_all_positions`, so the kill
switch's own loop would have to be edited in order to fix the kill switch.

**The proxy holds the LOOP, which is never rebound, and forwards by ATTRIBUTE rather than by
type** — so it survives the class change between `PaperBroker` and `SimPropFirmBroker`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from app.core.logging import logger
from app.schemas.broker import Position
from app.services.broker.base import Account, BrokerAdapter, OrderRequest


class LiveLoopBrokerProxy(BrokerAdapter):
    """A `BrokerAdapter` that forwards every member to `loop.paper` at call time."""

    def __init__(self, loop: Any) -> None:
        self._loop = loop
        #: Why the last forward found no broker, or `None`. **A positive statement.**
        #: `get_all_positions()` returning `[]` is ambiguous by construction — no adapters,
        #: adapters with nothing, or every adapter threw (`manager.py:373` swallows) — and
        #: that ambiguity is NOT this task's to close. This field lets a caller tell "the
        #: loop held no broker" apart from the other causes without widening the return type.
        self.unavailable_reason: str | None = None

    # ------------------------------------------------------------------
    def _resolve(self) -> Any | None:
        """Resolve the held broker AND record why, with no logging. **One writer of the field.**

        `B300`: `broker_name`, `default_pairs` and `is_simulation` each did their own
        `getattr(self._loop, "paper", None)` and never touched `unavailable_reason`, so on an
        unbound proxy `is_simulation` answered `False` while the field still read `None` — and
        `None` is defined above as *the forward found a broker*. **The field did not merely fail
        to tell the two states apart; it asserted the wrong one**, on the flag `ExecutionService`,
        the kill switch and position-close routing all read.

        **RESOLUTION AND RECORDING BELONG TOGETHER; ONLY THE LOGGING WAS COUPLED TO THEM.**
        Splitting here keeps a SINGLE writer of `unavailable_reason` — two places encoding one
        fact is its own defect — while letting a property read stay silent. A property is read at
        safety chokepoints, and routing it through the loud path would emit a warning at whatever
        rate those chokepoints run.
        """
        target = getattr(self._loop, "paper", None)
        self.unavailable_reason = (
            None if target is not None else "the live loop is holding no broker"
        )
        return target

    def _target(self) -> Any | None:
        """The broker the loop is holding RIGHT NOW, or `None`. **The loud path, unchanged.**

        **Never raises.** `manager.py:373` and `:571` swallow per-adapter exceptions and
        continue, so a proxy that threw when the loop had no broker would reproduce `[]` —
        the same symptom this class exists to remove, with a new cause.
        """
        target = self._resolve()
        if target is None:
            logger.warning("Broker proxy: the live loop is holding no broker")
        return target

    @property
    def simulation_source(self) -> str:  # type: ignore[override]
        """Forward the held broker's provenance (`B395` amendment).

        **THIS CLASS HAS NO `__getattr__`** — it forwards only what it explicitly defines, so any
        member added to `BrokerAdapter` after it was written is silently NOT forwarded. That is
        how `order_path_status` was missed one member ago, and the fix then forwarded *that
        member* instead of making non-forwarding loud, so the lesson did not generalise.

        **THE UNBOUND ANSWER IS THE ALARM, NOT THE ALL-CLEAR**, and that is the opposite choice
        from `order_path_status` above — deliberately. There, refusing to answer would block
        callers over a venue the proxy cannot even name. Here, *not knowing whether the safety
        flag was ever checked* IS the alarming state, so resolving it to a benign default would
        be the exact defect this amendment exists to remove.
        """
        target = self._resolve()
        if target is None:
            return "unreadable (the live loop is holding no broker)"
        return target.simulation_source

    def order_path_status(self) -> str | None:
        """Forward the venue's order-path answer (`T-0138`).

        **THIS CLASS PROMISES TO FORWARD *EVERY* MEMBER AND DID NOT FORWARD THIS ONE** — I added
        `order_path_status` to `BrokerAdapter` after this proxy was written, leaving the class
        docstring false about its own contract (`B238`). Anything asking the manager's `paper`
        adapter whether orders can be placed got the permissive base `None` while the real broker
        said otherwise.

        An unbound proxy answers `None` — permissive — deliberately: the loop's `start()` reads
        `self.paper` directly, so this exists for callers reached through the manager, and a proxy
        holding nothing must not block them on a venue it cannot even name.
        """
        target = self._resolve()
        return None if target is None else target.order_path_status()

    @property
    def broker_name(self) -> str:  # type: ignore[override]
        target = self._resolve()
        return getattr(target, "broker_name", "paper-proxy(unbound)")

    @property
    def default_pairs(self) -> list[str]:  # type: ignore[override]
        target = self._resolve()
        return list(getattr(target, "default_pairs", []) or [])

    # ------------------------------------------------------------------
    @property
    def is_simulation(self) -> bool:
        """**FORWARDED DYNAMICALLY, AND NEVER HARD-CODED.**

        `base.py:59-63` says why: *"a new real-money adapter can never silently pass as safe.
        Safety-critical chokepoints (ExecutionService, the kill switch, position-close
        routing) read this."* Returning a literal `True` here — tempting, since the loop
        holds a simulation today — **would launder a live adapter as simulated past three
        named chokepoints** on the day the loop holds one.

        With no broker the answer is `False`, not `True`: *unknown must not read as safe.*
        """
        target = self._resolve()
        if target is None:
            return False
        return bool(target.is_simulation)

    # ------------------------------------------------------------------
    async def connect(self) -> None:
        target = self._target()
        if target is not None:
            await target.connect()

    async def disconnect(self) -> None:
        target = self._target()
        if target is not None:
            await target.disconnect()

    async def get_account(self) -> Account:
        target = self._target()
        if target is None:
            return Account(
                account_id="paper-proxy", broker="paper", balance=0.0, equity=0.0,
                currency="USDT",
            )
        return await target.get_account()

    async def get_positions(self) -> list[Position]:
        target = self._target()
        return [] if target is None else await target.get_positions()

    async def get_orders(self, status: str | None = None) -> list[dict]:
        target = self._target()
        return [] if target is None else await target.get_orders(status)

    async def get_recent_trades(self, since: datetime | None = None) -> list[dict]:
        target = self._target()
        return [] if target is None else await target.get_recent_trades(since)

    async def place_order(self, request: OrderRequest) -> dict:
        target = self._target()
        if target is None:
            return {"status": "rejected", "reason": self.unavailable_reason}
        return await target.place_order(request)

    async def close_position(self, position_id: str, lot_size: float | None = None) -> dict:
        target = self._target()
        if target is None:
            return {"status": "error", "error": self.unavailable_reason}
        return await target.close_position(position_id, lot_size)

    async def close_all_positions(self) -> list[dict]:
        """**The kill switch's path.**

        With no broker this returns `[]` and NOT a synthetic status row. `kill_switch.py:71`
        counts any row whose status is not `error`/`failed` as CLOSED, so a `"no_broker"`
        marker would be counted as a position successfully closed — inflating the number the
        operator reads at exactly the moment it must not be inflated. The `[]`-means-three-
        things ambiguity is real and is explicitly another task's; `unavailable_reason` is
        how a caller tells this cause from the others without widening the return type.
        """
        target = self._target()
        return [] if target is None else await target.close_all_positions()

    async def stream_prices(self, pairs: list[str], callback: Callable) -> None:
        target = self._target()
        if target is not None:
            await target.stream_prices(pairs, callback)

    async def reference_price(self, pair: str) -> float | None:
        target = self._target()
        return None if target is None else await target.reference_price(pair)
