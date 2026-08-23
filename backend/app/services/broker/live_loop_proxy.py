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
    def _target(self) -> Any | None:
        """The broker the loop is holding RIGHT NOW, or `None`.

        **Never raises.** `manager.py:373` and `:571` swallow per-adapter exceptions and
        continue, so a proxy that threw when the loop had no broker would reproduce `[]` —
        the same symptom this class exists to remove, with a new cause.
        """
        target = getattr(self._loop, "paper", None)
        self.unavailable_reason = (
            None if target is not None else "the live loop is holding no broker"
        )
        if target is None:
            logger.warning("Broker proxy: the live loop is holding no broker")
        return target

    @property
    def broker_name(self) -> str:  # type: ignore[override]
        target = getattr(self._loop, "paper", None)
        return getattr(target, "broker_name", "paper-proxy(unbound)")

    @property
    def default_pairs(self) -> list[str]:  # type: ignore[override]
        target = getattr(self._loop, "paper", None)
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
        target = getattr(self._loop, "paper", None)
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
