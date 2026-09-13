"""The kill switch's state, one layer below everything that must read it (`B442`).

**WHY IT LIVES HERE.** `crypto_loop._tick_symbol` read `kill_switch.is_armed` at its gate, then SUSPENDED —
the bias fetch, the news fetch, the signal broadcast — before `ExecutionService.execute` sent the order.
A switch pulled in that window armed, enumerated the book and closed it; the entry then opened a
position the switch's report could not mention. Driven at `fb3dab6` on both simulators the loop binds.

The check that closes the window belongs AT THE SEND, inside each adapter, and the broker layer must
not import `compliance`. So the FACT moves down: `compliance.KillSwitch` reads and writes this object,
and every adapter reads it at the moment it sends. **Nobody takes a copy** — a flag snapshotted at
construction is the mutant the arms kill.

**THERE IS NO INSTALL STEP, SO NO DEFAULT TO GET WRONG.** A hook registered on the broker layer, or a
callable passed to constructors, both have an uninstalled state — and that state is "no check". An
adapter cannot be imported without this module.
"""
from __future__ import annotations

from typing import Final

from app.core.exceptions import KillSwitchArmed

#: **THE KILL SWITCH MUST ANSWER BEFORE THE PROXY GIVES UP ON IT** (`B443`). `deploy/nginx-web.conf` cuts
#: `/api/` requests at `proxy_read_timeout 120s`; the 20s below that is margin for what `trigger()` does
#: after the closes — the audit write, the websocket broadcast, the SMTP alert. `AlpacaAdapter`'s second
#: sweep caps its wait for an in-flight entry by this, measured from the START of `close_all_positions`.
#: An arm reads the EFFECTIVE `proxy_read_timeout` for `location /api/` at test time and asserts this is
#: below it, so shortening the proxy fails a test instead of the switch silently answering too late.
#:
#: **RESIDUALS, stated (manager's ruling):** sweep (a) alone can exceed this with enough positions on a
#: degraded venue — sweep (b) then waits zero and the response can still pass 120s; that is `B443`'s
#: unbuilt response-shape fix and needs Malek. And the deadline is PER ADAPTER: `broker_manager` closes
#: adapters one after another, so several connected adapters each take their own share.
KILL_SWITCH_RESPONSE_DEADLINE_S: Final[float] = 100.0


class KillSwitchState:
    """One process, one switch. `armed`/`reason` are what sends read; `trigger_started` is `trigger()`'s
    in-progress mark (monotonic seconds), which a second trigger and `disarm()` both read."""

    __slots__ = ("armed", "reason", "trigger_started", "trigger_started_at")

    def __init__(self) -> None:
        self.armed: bool = False
        self.reason: str | None = None
        self.trigger_started: float | None = None
        self.trigger_started_at: str | None = None


KILL_SWITCH_STATE: Final[KillSwitchState] = KillSwitchState()


def refuse_if_armed(*, venue: str, pair: str, client_order_id: str | None) -> None:
    """Raise `KillSwitchArmed` if the switch is armed NOW. **SUBMISSIONS ONLY** — the switch never refuses
    its own closes (review's K2-9) — and call it with NO suspension between this line and the send.

    Reads `KILL_SWITCH_STATE` at call time, every time. `KillSwitchArmed` is a `ComplianceError`, NOT a
    `BrokerError`, and must stay one: raised through `AlpacaAdapter._call` or inside its submission `try`,
    it would be classified as an unanswered submission and looked up as an order that was never sent (K2-8).
    """
    state = KILL_SWITCH_STATE
    if state.armed:
        exc = KillSwitchArmed(
            f"KILL SWITCH ARMED ({state.reason or 'no reason given'}): {venue} refused this {pair} entry at "
            f"submission. Nothing was sent.",
        )
        exc.venue, exc.pair, exc.client_order_id = venue, pair, client_order_id  # type: ignore[attr-defined]
        raise exc
