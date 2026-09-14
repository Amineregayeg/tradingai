"""`T-0144` §2 — the position-event source: ONE awaited call site for every broker (`B428b` commit (ii)).

The loop awaits `events.tick(pair, mark)` on every pass and gets back the settle events that pass produced. Two
implementations:

* `SimulatorEvents(paper)` — the simulators keep enforcing their own SL/TP: `tick` is `paper.on_tick(pair, price)`,
  unchanged, and a pass with no price does nothing, as before (§2.1).
* `VenueEvents(adapter, book, hooks)` — the in-process manager for a VENUE broker (§2.2–§2.6). It reads the venue
  position, and for each ENGINE position on the pair (the book, keyed by decision id) decides, in this order:
  gone without our close -> settle from FILLs; blind -> close (`STOP_BLIND`) and block this symbol's entries; stop
  crossed -> full close (`STOP_HIT`); take-profit crossed -> full close (`TP_HIT`); EXIT-001's 2R partial -> partial
  close (`PARTIAL_2R`). Every close is an ordinary SELL order with the decision's client id, sent after cancelling the
  symbol's resting orders (R14), sized from the ENGINE's units (R5'', GX-6), resolved through the adapter's resolver.

Persistence is delivered the same way for both: `hooks.on_settle(event)` (the loop's `_on_settle_cb`, whose tasks it
keeps — `B460`). The venue's "in flight" marker lasts until that settle's database write COMMITS (GX-2).

Stated, not observable today (revision 6, GX-1): the stop is evaluated before the partial. The live stop is passive, so
for a long stop < entry < the 2R level and one mark cannot satisfy both.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Awaitable, Callable, Protocol, TypedDict

from app.core.logging import logger
from app.services.broker.symbols import same_pair

# ---------------------------------------------------------------------------------------------------
# vocabulary
# ---------------------------------------------------------------------------------------------------

#: Close legs (DESIGN §4.1): s stop, t take-profit, p partial, b blind, x stop-button, e external-reconcile close.
LEG_STOP, LEG_TP, LEG_PARTIAL, LEG_BLIND, LEG_STOP_BUTTON, LEG_RECONCILE = "s", "t", "p", "b", "x", "e"
#: G-1: the legs that PROTECT a position (they escalate and keep sending) and the legs that take PROFIT (they stop at 9).
PROTECTIVE_LEGS: frozenset[str] = frozenset({LEG_STOP, LEG_BLIND, LEG_STOP_BUTTON, LEG_RECONCILE})
PROFIT_LEGS: frozenset[str] = frozenset({LEG_TP, LEG_PARTIAL})

#: G-1: two-digit attempts. A protective leg escalates AT attempt 10 and keeps sending to 99; a profit leg stops past 9.
PROTECTIVE_ATTEMPT_ESCALATE_AT = 10
PROTECTIVE_ATTEMPT_MAX = 99
PROFIT_ATTEMPT_MAX = 9

#: §2.3 / GX-3: consecutive passes before an escalation (about a minute at 10 s polls).
POSITIONS_UNREADABLE_ALERT_AFTER = 6
CLOSE_BLOCKED_ESCALATE_AFTER = 6
#: Revision (ii) ruling 2: a FILLED close with no readable price is re-read by client id every pass; every this-many passes
#: it is settled from its OWN FILL activities instead (matched by its exact order), and re-evaluated that often while
#: the FILLs cannot account for it.
UNPRICED_FILL_SETTLE_EVERY = 6

#: R1''': a symbol is BLIND when no Binance mark for this long AND no Alpaca quote younger than `ALPACA_QUOTE_STOP_MAX_AGE_S`.
#: Distinct from commit (i)'s ENTRY reference bounds (60 s / 120 s): an entry may wait, a stop may not fail open.
BINANCE_MARK_BLIND_AFTER_S = 180.0
ALPACA_QUOTE_STOP_MAX_AGE_S = 600.0

#: R5'' / C-6: the SELL fee on a crypto close, 0.25% of the notional. Source: probe rounds 4/5 measured the BUY fee in
#: kind at 0.25% (`alpaca.ALPACA_CRYPTO_FEE_RATE`); Alpaca's crypto fee schedule charges the same taker rate on a sell.
SELL_FEE_RATE = Decimal("0.0025")

REASON_STOP_HIT = "STOP_HIT"
REASON_TP_HIT = "TP_HIT"
REASON_PARTIAL = "PARTIAL_2R"
REASON_STOP_BLIND = "STOP_BLIND"
REASON_EXTERNAL_EXIT = "EXTERNAL_EXIT"
REASON_UNSETTLED_EXTERNAL_EXIT = "UNSETTLED_EXTERNAL_EXIT"
REASON_ENGINE_CLOSE_FROM_FILLS = "ENGINE_CLOSE_SETTLED_FROM_FILLS"

ALERT_POSITIONS_UNREADABLE = "POSITIONS_UNREADABLE"
ALERT_STOP_BLIND_CLOSE = "STOP_BLIND_CLOSE"
ALERT_CLOSE_NOT_SENT_RESTING_ORDER = "CLOSE_NOT_SENT_RESTING_ORDER"
ALERT_CLOSE_ATTEMPTS_EXHAUSTED = "CLOSE_ATTEMPTS_EXHAUSTED"
ALERT_UNSETTLED_EXTERNAL_EXIT = "UNSETTLED_EXTERNAL_EXIT"
ALERT_CLOSE_UNPRICED = "CLOSE_FILL_PRICE_UNREADABLE"
ALERT_CLOSE_BELOW_MINIMUM = "CLOSE_BELOW_VENUE_MINIMUM"

HALT_CLOSE_ATTEMPTS_EXHAUSTED = "a protective close has failed 10 attempts; use the kill switch"
HALT_CLOSE_BLOCKED = "a protective close is blocked by a resting order that cannot be cancelled"

#: Entry-block keys the loop reads (`_entry_block_reason`): per symbol for blindness, engine-wide for an unreadable venue.
BLOCK_KEY_POSITIONS_UNREADABLE = "positions_unreadable"


def blind_block_key(pair: str) -> str:
    return f"blind:{pair}"


def unsettled_block_key(pair: str) -> str:
    return f"unsettled:{pair}"


# exit modes (`app.models.trade.EXIT_MODES`), by value, so this module stays importable without the models
EXIT_MODE_EXTERNAL = "EXTERNAL"
EXIT_MODE_UNRECORDED = "UNRECORDED"

ENGINE_PREFIX = "tai-"
_CLOSE_ID = re.compile(r"^tai-([0-9a-f]{32})-([stpbxe])(\d{2})$")


def close_client_order_id(decision_id: str, leg: str, attempt: int) -> str:
    """`tai-<32 hex>-<leg><2-digit attempt>`: 40 characters (G-1). The decision id's WHOLE hex, never a slice."""
    hex_id = str(decision_id).replace("-", "").lower()
    if len(hex_id) != 32 or leg not in PROTECTIVE_LEGS | PROFIT_LEGS or not 1 <= int(attempt) <= PROTECTIVE_ATTEMPT_MAX:
        raise ValueError(f"not a close id: decision={decision_id!r} leg={leg!r} attempt={attempt!r}")
    return f"{ENGINE_PREFIX}{hex_id}-{leg}{int(attempt):02d}"


def parse_close_client_order_id(client_order_id: object) -> tuple[str, str, int] | None:
    """`(decision hex, leg, attempt)` for an engine CLOSE id, else `None` (an entry id, a foreign id, or nothing)."""
    if not isinstance(client_order_id, str):
        return None
    match = _CLOSE_ID.match(client_order_id)
    return (match.group(1), match.group(2), int(match.group(3))) if match else None


def _dec(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return out if out.is_finite() else None


# ---------------------------------------------------------------------------------------------------
# shapes
# ---------------------------------------------------------------------------------------------------

class SettleEvent(TypedDict, total=False):
    """ONE shape for both sources (§2.4). Simulators fill what they have; persistence reads the optional fields with an
    explicit `None` (no `or 0`, `B415`)."""
    decision_id: str | None
    pair: str                       # the LOOP's spelling, never the venue symbol (F-g)
    direction: str
    position_id: str                # the decision id for a venue; the paper id for a simulator
    units: float
    entry: float | None
    exit: float | None              # the FILL
    pnl: float | None
    fee_usd: float | None
    open_time: datetime | None
    close_time: datetime | None
    partial: bool
    remaining_units: float | None
    reason: str
    leg: str | None
    stop_level: float | None        # the position's STOP (persisted as trades.sl)
    trigger_level: float | None     # the level that triggered THIS close (the stop, the tp, the 2R level)
    mark_at_detection: float | None
    mark_source: str | None
    detection_slippage: float | None     # mark − trigger level
    execution_slippage: float | None     # fill − mark
    execution_slippage_label: str | None  # "PAPER" on a paper venue
    detection_interval_s: float | None   # the measured pass wall time (R1')
    close_client_order_id: str | None
    venue_order_id: str | None
    venue: str | None
    exit_mode: str | None
    resolves: bool                  # R5': the ENGINE's units are all closed and every closing fill is settled


@dataclass(frozen=True)
class Mark:
    """The price a pass manages with. `price is None` with `blind=True` is R1''''s blind symbol; `price is None` with
    `blind=False` is "no price yet" (not blind), and nothing is decided on it."""
    price: float | None
    source: str | None
    at: datetime | None
    blind: bool = False


@dataclass
class EnginePosition:
    """What the ENGINE opened, keyed by decision id in the loop's book (§4.3). Units are the engine's own, never the
    venue's total: foreign units on the symbol are never the engine's to sell (R5'', GX-6)."""
    decision_id: str
    pair: str
    direction: str
    units: Decimal
    stop: float
    entry_price: float | None = None
    tp: float | None = None
    partial_price: float | None = None
    partial_fraction: float | None = None
    partial_taken: bool = False
    partial_skipped: str | None = None
    entry_order_id: str | None = None
    entry_client_order_id: str | None = None
    entry_filled_at: datetime | None = None
    opened_at: datetime | None = None
    run_id: str | None = None
    #: the last attempt number USED per leg (a cache; the venue is the durable counter, §4.5)
    attempts: dict[str, int] = field(default_factory=dict)
    #: settles whose database write has not committed, by close id (GX-2); `persist_failed` marks a retry
    in_flight: dict[str, dict] = field(default_factory=dict)
    #: an UNRESOLVED close, re-read by client id before anything else is sent for this position
    pending_close: dict | None = None
    #: closes that FILLED with an unreadable price, by close id: `{event, passes}`. The units are already taken off; the
    #: close holds GX-2's marker until its Trade row commits, so the position is never re-classified EXTERNAL meanwhile.
    unpriced: dict[str, dict] = field(default_factory=dict)
    #: venue order ids this position has already SETTLED in this process: a later "gone" settle from FILLs never counts
    #: them again (GX-2's other half: a partial written before the runner was sold elsewhere is not the runner's exit)
    settled_order_ids: set[str] = field(default_factory=set)
    blocked_passes: dict[str, int] = field(default_factory=dict)
    #: edge-trigger memory for escalations and alerts
    alerted: set[str] = field(default_factory=set)


class PositionEventSource(Protocol):
    async def tick(self, pair: str, mark: Mark) -> list[SettleEvent]: ...


# ---------------------------------------------------------------------------------------------------
# simulators
# ---------------------------------------------------------------------------------------------------

class SimulatorEvents:
    """The simulators' own SL/TP, unchanged (V-1's must-miss): a pass with a price is `paper.on_tick`; without one,
    nothing happens, as before."""

    kind = "simulator"

    def __init__(self, paper: Any) -> None:
        self.paper = paper

    async def tick(self, pair: str, mark: Mark) -> list[SettleEvent]:
        if mark.price is None:
            return []
        return self.paper.on_tick(pair, mark.price)

    def settle_persisted(self, event: dict, ok: bool) -> bool:
        return bool(ok)


# ---------------------------------------------------------------------------------------------------
# venues
# ---------------------------------------------------------------------------------------------------

@dataclass
class VenueHooks:
    """What `VenueEvents` needs from the loop, as callables, so every rule is armed with doubles.

    `on_settle(event)`            schedules the settle's persistence (the loop keeps the task, `B460`)
    `alert(kind, message, context, critical)`   an engine alert; never raises into the pass
    `declare_halt(reason)`        halts entries engine-wide (the loop's `_declare_halt`; it does not clear by itself)
    `block_entries(key, reason)`  sets (`reason`) or clears (`None`) a named entry block
    `write_hint(decision_id, leg, n, mode)`     best-effort hint write BEFORE a close (G-2); may raise
    `read_hint(decision_id)`      the stored hint dict or `None`; may raise
    `decided_mode()`              the loop's mode when a close is decided (RUNNING until commit (iii))
    `last_pass_s()`               the measured wall time of the last complete pass, or `None`
    """
    on_settle: Callable[[SettleEvent], None]
    alert: Callable[..., Awaitable[None]]
    declare_halt: Callable[[str], None]
    block_entries: Callable[[str, str | None], None]
    write_hint: Callable[[str, str, int, str], Awaitable[None]]
    read_hint: Callable[[str], Awaitable[dict | None]]
    decided_mode: Callable[[], str]
    last_pass_s: Callable[[], float | None]


class VenueEvents:
    """The in-process position manager for a venue broker (§2.2–§2.6).

    The adapter provides: `position_quantity(pair) -> Decimal` (raises when it cannot read; 0 only when not listed),
    `asset_limits(pair)` (`min_order_size`, `quantise_down`), `cancel_open_orders_for(pair)`, `place_close(pair, qty,
    client_order_id)`, `find_order_by_client_id(client_order_id)` (`None` on a 404), `fill_activities(pair, after)` and
    `order_client_id(order_id)`; `broker_name` and `is_paper_venue`.
    """

    kind = "venue"

    def __init__(self, adapter: Any, book: dict[str, dict], hooks: VenueHooks) -> None:
        self.adapter = adapter
        self.book = book
        self.hooks = hooks
        self._unreadable: dict[str, int] = {}

    # -- the book --------------------------------------------------------------------------------------------------
    def positions_for(self, pair: str) -> list[EnginePosition]:
        out = []
        for entry in self.book.values():
            pos = entry.get("position") if isinstance(entry, dict) else None
            if isinstance(pos, EnginePosition) and same_pair(pos.pair, pair):
                out.append(pos)
        return out

    # -- one pass for one symbol ---------------------------------------------------------------------------------------
    async def tick(self, pair: str, mark: Mark) -> list[SettleEvent]:
        """R1'': NOTHING returns before the positions are evaluated except "no engine position on this pair"."""
        if mark.price is not None:
            self.hooks.block_entries(blind_block_key(pair), None)          # B-3: a fresh price clears the blind block
        positions = [p for p in self.positions_for(pair) if p.units > 0 or p.in_flight or p.pending_close or p.unpriced]
        if not positions:
            return []
        try:
            venue_qty = await self.adapter.position_quantity(pair)
        except Exception as exc:  # noqa: BLE001 - V-6: unreadable is neither blind nor gone
            count = self._unreadable[pair] = self._unreadable.get(pair, 0) + 1
            logger.error("live.venue_positions_unreadable — no stop, blind close or exit is decided on an unknown quantity",
                         pair=pair, consecutive=count, error=f"{type(exc).__name__}: {exc}",
                         decisions=[p.decision_id for p in positions])
            if count == POSITIONS_UNREADABLE_ALERT_AFTER:
                reason = f"venue positions unreadable for {count} consecutive passes ({pair})"
                self.hooks.block_entries(BLOCK_KEY_POSITIONS_UNREADABLE, reason)
                await self._alert(ALERT_POSITIONS_UNREADABLE, f"ENTRIES HALTED: {reason}; stops cannot be enforced "
                                  f"without the quantity", {"pair": pair, "decisions": [p.decision_id for p in positions],
                                                            "error": f"{type(exc).__name__}"}, critical=True)
            return []
        if self._unreadable.pop(pair, 0) >= POSITIONS_UNREADABLE_ALERT_AFTER:
            self.hooks.block_entries(BLOCK_KEY_POSITIONS_UNREADABLE, None)
            logger.warning("live.venue_positions_readable_again", pair=pair)

        events: list[SettleEvent] = []
        for pos in positions:
            try:
                events.extend(await self._manage(pos, venue_qty, mark))
            except Exception as exc:  # noqa: BLE001 - V-5: one position's failure never skips another's stop
                logger.error("live.venue_position_pass_failed — this position's pass raised; the others still run",
                             decision_id=pos.decision_id, pair=pos.pair, error=f"{type(exc).__name__}: {exc}")
        return events

    async def _manage(self, pos: EnginePosition, venue_qty: Decimal, mark: Mark) -> list[SettleEvent]:
        events: list[SettleEvent] = []
        self._retry_failed_settles(pos)
        if pos.unpriced:
            events.extend(await self._price_unpriced(pos))
        if pos.pending_close is not None:
            done, settled = await self._follow_pending_close(pos, mark)
            events.extend(settled)
            if not done:
                return events
        if pos.units <= 0:
            return events

        limits = await self.adapter.asset_limits(pos.pair)
        if venue_qty < limits.min_order_size:
            # GONE WITHOUT OUR CLOSE (§2.2a) — unless one of ours is still being written (GX-2, V-7c)
            if pos.in_flight or pos.unpriced:
                return events
            events.extend(await self._settle_gone(pos, limits))
            return events

        if mark.price is None:
            if mark.blind:
                self.hooks.block_entries(blind_block_key(pos.pair),
                                         f"{pos.pair} is BLIND: no Binance mark for {BINANCE_MARK_BLIND_AFTER_S:.0f}s and no "
                                         f"Alpaca quote younger than {ALPACA_QUOTE_STOP_MAX_AGE_S:.0f}s")
                if f"blind:{pos.decision_id}" not in pos.alerted:
                    pos.alerted.add(f"blind:{pos.decision_id}")
                    await self._alert(ALERT_STOP_BLIND_CLOSE, f"{pos.pair} is blind; closing decision {pos.decision_id} "
                                      f"at market and blocking its entries", {"decision_id": pos.decision_id,
                                                                              "pair": pos.pair}, critical=True)
                events.extend(await self._close(pos, LEG_BLIND, "full", REASON_STOP_BLIND, mark, venue_qty, limits, None))
            return events

        long = str(pos.direction).upper() == "LONG"
        price = float(mark.price)
        if (price <= pos.stop) if long else (price >= pos.stop):
            events.extend(await self._close(pos, LEG_STOP, "full", REASON_STOP_HIT, mark, venue_qty, limits, pos.stop))
        elif pos.tp is not None and ((price >= pos.tp) if long else (price <= pos.tp)):
            events.extend(await self._close(pos, LEG_TP, "full", REASON_TP_HIT, mark, venue_qty, limits, pos.tp))
        elif (pos.partial_price is not None and pos.partial_fraction is not None and not pos.partial_taken
              and pos.partial_skipped is None
              and ((price >= pos.partial_price) if long else (price <= pos.partial_price))):
            events.extend(await self._close(pos, LEG_PARTIAL, "partial", REASON_PARTIAL, mark, venue_qty, limits,
                                            pos.partial_price))
        return events

    # -- closes as orders (§2.5) ----------------------------------------------------------------------------------------
    async def _close(self, pos: EnginePosition, leg: str, kind: str, reason: str, mark: Mark, venue_qty: Decimal,
                     limits: Any, level: float | None) -> list[SettleEvent]:
        protective = leg in PROTECTIVE_LEGS
        # R14: the symbol's resting orders first. A failed or incomplete cancel sends NOTHING this pass (B448's lock).
        try:
            cancel = await self.adapter.cancel_open_orders_for(pos.pair)
        except Exception as exc:  # noqa: BLE001
            cancel = {"cancelled": [], "failed": [("?", f"{type(exc).__name__}: {exc}")], "resting": [], "complete": False}
        if cancel.get("failed") or not cancel.get("complete", False):
            blocked = pos.blocked_passes[leg] = pos.blocked_passes.get(leg, 0) + 1
            resting = [str(i) for i in (cancel.get("resting") or [])] + [str(i) for i, _e in (cancel.get("failed") or [])]
            logger.warning("live.close_not_sent_resting_order — a resting order could not be cancelled; the close waits",
                           decision_id=pos.decision_id, pair=pos.pair, leg=leg, consecutive=blocked, resting=resting)
            key = f"blocked:{leg}"
            if blocked >= CLOSE_BLOCKED_ESCALATE_AFTER and key not in pos.alerted:
                pos.alerted.add(key)
                message = (f"the {leg} close for decision {pos.decision_id} ({pos.pair}) has not been sent for "
                           f"{blocked} consecutive passes: resting order(s) {resting} could not be cancelled")
                if protective:
                    self.hooks.declare_halt(HALT_CLOSE_BLOCKED)
                    message = "ENTRIES HALTED: " + message
                await self._alert(ALERT_CLOSE_NOT_SENT_RESTING_ORDER, message,
                                  {"decision_id": pos.decision_id, "leg": leg, "resting_order_ids": resting},
                                  critical=protective)
            return []
        pos.blocked_passes[leg] = 0                               # CONSECUTIVE (C-3a): a pass that sends resets it
        pos.alerted.discard(f"blocked:{leg}")

        held = min(pos.units, venue_qty)                          # R5'' / GX-6: never foreign units
        wanted = held if kind == "full" else held * Decimal(str(pos.partial_fraction))
        qty = limits.quantise_down(wanted)
        if qty <= 0 or qty < limits.min_order_size:
            note = (f"{kind} close of {wanted} for decision {pos.decision_id} quantises to {qty}, below the venue minimum "
                    f"{limits.min_order_size}")
            if kind == "partial":
                pos.partial_skipped = note                        # C-5: skipped WITH a reason, and not an attempt
                logger.warning("live.partial_skipped_below_minimum", decision_id=pos.decision_id, pair=pos.pair,
                               reason=note)
            elif f"below_min:{leg}" not in pos.alerted:
                pos.alerted.add(f"below_min:{leg}")
                await self._alert(ALERT_CLOSE_BELOW_MINIMUM, note, {"decision_id": pos.decision_id, "leg": leg},
                                  critical=protective)
            return []

        attempt = await self._next_attempt(pos, leg)
        if attempt is None:
            return []
        client_id = close_client_order_id(pos.decision_id, leg, attempt)
        mode = self.hooks.decided_mode()                          # decided NOW; a retried settle never re-reads it
        try:
            await self.hooks.write_hint(pos.decision_id, leg, attempt, mode)     # G-2: BEFORE the send, best-effort
        except Exception as exc:  # noqa: BLE001 - protection never depends on the database
            logger.warning("live.close_hint_write_failed — the close is sent anyway", decision_id=pos.decision_id,
                           leg=leg, attempt=attempt, error=f"{type(exc).__name__}: {exc}")
        pos.attempts[leg] = attempt
        try:
            out = await self.adapter.place_close(pos.pair, qty, client_id)
        except Exception as exc:  # noqa: BLE001 - the attempt number is spent; the next pass uses the next one
            logger.error("live.close_send_failed — the next pass retries with the next attempt",
                         decision_id=pos.decision_id, pair=pos.pair, leg=leg, client_order_id=client_id,
                         error=f"{type(exc).__name__}: {exc}")
            return []
        return await self._on_close_result(pos, leg, client_id, qty, out, reason, mark, mode, level)

    async def _next_attempt(self, pos: EnginePosition, leg: str) -> int | None:
        """G-1 / G-2 / §4.5: the next attempt number for `leg`, or `None` when nothing may be sent."""
        protective = leg in PROTECTIVE_LEGS
        ceiling = PROTECTIVE_ATTEMPT_MAX if protective else PROFIT_ATTEMPT_MAX
        last = pos.attempts.get(leg)
        if last is not None:
            attempt = last + 1
        else:
            # LAZY PROBE (G-2): from the hint + 1 until a 404, at this leg's FIRST send. A correct hint is one read; a
            # stale-low hint costs reads and never reuses an id; a hint ahead only skips numbers.
            start = 0
            try:
                hint = await self.hooks.read_hint(pos.decision_id)
                entry = (hint or {}).get(leg)
                if isinstance(entry, dict) and isinstance(entry.get("n"), int) and not isinstance(entry.get("n"), bool):
                    start = max(0, entry["n"])
            except Exception as exc:  # noqa: BLE001 - a missing hint only moves where the probe starts
                logger.warning("live.close_hint_read_failed", decision_id=pos.decision_id, leg=leg,
                               error=f"{type(exc).__name__}: {exc}")
            attempt = start + 1
            while attempt <= ceiling:
                found = await self.adapter.find_order_by_client_id(close_client_order_id(pos.decision_id, leg, attempt))
                if found is None:
                    break
                attempt += 1
        if attempt > ceiling:
            key = f"exhausted_max:{leg}"
            if protective or key not in pos.alerted:              # protective: repeats every pass; profit: once
                pos.alerted.add(key)
                await self._alert(ALERT_CLOSE_ATTEMPTS_EXHAUSTED,
                                  f"the {leg} close for decision {pos.decision_id} ({pos.pair}) has used all {ceiling} "
                                  f"attempts; NOTHING more is sent" + ("; use the kill switch" if protective else
                                                                      "; the position keeps its stop"),
                                  {"decision_id": pos.decision_id, "leg": leg, "attempts": ceiling}, critical=protective)
            return None
        if protective and attempt >= PROTECTIVE_ATTEMPT_ESCALATE_AT and f"exhausted:{leg}" not in pos.alerted:
            pos.alerted.add(f"exhausted:{leg}")
            self.hooks.declare_halt(HALT_CLOSE_ATTEMPTS_EXHAUSTED)
            await self._alert(ALERT_CLOSE_ATTEMPTS_EXHAUSTED,
                              f"ENTRIES HALTED: the {leg} close for decision {pos.decision_id} ({pos.pair}) reached "
                              f"attempt {attempt}; it keeps sending every pass. Use the kill switch.",
                              {"decision_id": pos.decision_id, "leg": leg, "attempt": attempt}, critical=True)
        return attempt

    async def _on_close_result(self, pos: EnginePosition, leg: str, client_id: str, qty: Decimal, out: dict,
                               reason: str, mark: Mark, mode: str, level: float | None) -> list[SettleEvent]:
        status = out.get("status") if isinstance(out, dict) else None
        filled = _dec(out.get("filled_units")) if isinstance(out, dict) else None
        if type(status) is str and status in ("FILLED", "PARTIALLY_FILLED") and filled is not None and filled > 0:
            if status == "PARTIALLY_FILLED" and not out.get("terminal", False):
                # still working at the venue: what filled so far is settled when the order ends
                pos.pending_close = {"leg": leg, "client_order_id": client_id, "qty": str(qty), "reason": reason,
                                     "mode": mode, "level": level}
                logger.error("live.close_still_working — re-read by client id before anything else is sent",
                             decision_id=pos.decision_id, client_order_id=client_id, filled=str(filled))
                return []
            return await self._settle_fill(pos, leg, client_id, out, filled, reason, mark, mode, level)
        if type(status) is str and status == "REJECTED":
            # refused, or accepted and ended unfilled (S6): nothing to settle; the next pass sends attempt + 1
            logger.warning("live.close_not_filled — the next pass sends the next attempt", decision_id=pos.decision_id,
                           client_order_id=client_id, status=status, code=out.get("rejection_code"))
            return []
        pos.pending_close = {"leg": leg, "client_order_id": client_id, "qty": str(qty), "reason": reason, "mode": mode,
                             "level": level}
        logger.error("live.close_unresolved — re-read by client id before anything else is sent for this position",
                     decision_id=pos.decision_id, client_order_id=client_id, status=repr(status))
        return []

    async def _follow_pending_close(self, pos: EnginePosition, mark: Mark) -> tuple[bool, list[SettleEvent]]:
        pending = pos.pending_close
        try:
            found = await self.adapter.find_order_by_client_id(pending["client_order_id"])
        except Exception as exc:  # noqa: BLE001 - unknown: keep waiting, send nothing
            logger.error("live.pending_close_unreadable", decision_id=pos.decision_id,
                         client_order_id=pending["client_order_id"], error=f"{type(exc).__name__}")
            return False, []
        if found is None:
            pos.pending_close = None                          # never created: the next close uses the next attempt
            return True, []
        status, filled = found.get("status"), _dec(found.get("filled_units"))
        if type(status) is str and status in ("FILLED", "PARTIALLY_FILLED") and filled is not None and filled > 0:
            if status == "PARTIALLY_FILLED" and not found.get("terminal", False):
                return False, []
            pos.pending_close = None
            return True, await self._settle_fill(pos, pending["leg"], pending["client_order_id"], found, filled,
                                                 pending["reason"], mark, pending["mode"], pending.get("level"))
        if found.get("terminal", False):
            pos.pending_close = None                          # ended unfilled
            return True, []
        return False, []

    async def _settle_fill(self, pos: EnginePosition, leg: str, client_id: str, out: dict, filled: Decimal, reason: str,
                           mark: Mark, mode: str, level: float | None) -> list[SettleEvent]:
        units = min(filled, pos.units)
        pos.units -= units
        if leg == LEG_PARTIAL:
            pos.partial_taken = True
        fill = out.get("fill")
        event = self._event(pos, leg=leg, client_id=client_id, venue_order_id=out.get("position_id") or out.get("order_id"),
                            units=units, fill=fill, reason=reason, mark=mark, mode=mode, level=level,
                            close_time=out.get("filled_at"))
        if not isinstance(fill, (int, float)) or isinstance(fill, bool) or fill <= 0:
            pos.unpriced[client_id] = {"event": dict(event), "passes": 0}
            await self._alert(ALERT_CLOSE_UNPRICED, f"the {leg} close {client_id} for decision {pos.decision_id} FILLED "
                              f"{units} with no readable price; no trade row until a price is read",
                              {"decision_id": pos.decision_id, "client_order_id": client_id}, critical=False)
            return []
        self._emit(pos, event)
        return [event]

    async def _price_unpriced(self, pos: EnginePosition) -> list[SettleEvent]:
        """Revision (ii) ruling 2 (UP-1..UP-3). Each pass re-reads the close by client id; a price -> ONE settle, and the
        marker clears when its row commits. Every `UNPRICED_FILL_SETTLE_EVERY` passes without one, the close is settled
        from its OWN FILL activities (its exact order, confirmed by client id) at their qty-weighted average. FILLs that
        cannot account for the filled quantity -> CRITICAL `UNSETTLED_EXTERNAL_EXIT`, the marker STAYS and this symbol's
        entries are blocked; re-evaluated at the same cadence, and lifted only when the FILLs account for it."""
        out: list[SettleEvent] = []
        for client_id, entry in list(pos.unpriced.items()):
            entry["passes"] += 1
            event = entry["event"]
            try:
                found = await self.adapter.find_order_by_client_id(client_id)
            except Exception:  # noqa: BLE001 - still unpriced this pass
                found = None
            fill = (found or {}).get("fill")
            if isinstance(fill, (int, float)) and not isinstance(fill, bool) and fill > 0:
                out.extend(self._settle_unpriced(pos, client_id, float(fill)))
                continue
            if entry["passes"] % UNPRICED_FILL_SETTLE_EVERY != 0:
                continue
            vwap, why = await self._own_fills_price(pos, client_id, event)
            if vwap is not None:
                out.extend(self._settle_unpriced(pos, client_id, vwap))
                continue
            block_key = unsettled_block_key(pos.pair)
            self.hooks.block_entries(block_key, f"{pos.pair}: close {client_id} filled with no price and its FILLs "
                                                f"do not account for it ({why})")
            if f"unsettled:{client_id}" not in pos.alerted:
                pos.alerted.add(f"unsettled:{client_id}")
                await self._alert(ALERT_UNSETTLED_EXTERNAL_EXIT,
                                  f"ENTRIES ON {pos.pair} BLOCKED: close {client_id} for decision {pos.decision_id} "
                                  f"filled {event.get('units')} with no readable price, and its FILL activities do not "
                                  f"account for it ({why}). No row is written; re-evaluated every "
                                  f"{UNPRICED_FILL_SETTLE_EVERY} passes.",
                                  {"decision_id": pos.decision_id, "client_order_id": client_id}, critical=True)
        return out

    async def _own_fills_price(self, pos: EnginePosition, client_id: str, event: dict) -> tuple[float | None, str]:
        order_id = event.get("venue_order_id")
        if not order_id or pos.entry_filled_at is None:
            return None, "the close's order id or the entry's venue fill time is unknown"
        try:
            if await self.adapter.order_client_id(order_id) != client_id:
                return None, f"order {order_id} does not carry client id {client_id}"
            rows = await self.adapter.fill_activities(pos.pair, after=pos.entry_filled_at)
            side = "sell" if str(pos.direction).upper() == "LONG" else "buy"
            mine = [o for o in aggregate_closing_fills(rows, pair=pos.pair, exclude_order_id=pos.entry_order_id, side=side)
                    if o["order_id"] == str(order_id)]
        except Exception as exc:  # noqa: BLE001 - unreadable FILLs account for nothing
            return None, f"FILL activities unreadable ({type(exc).__name__})"
        units = Decimal(str(event.get("units")))
        got = mine[0]["qty"] if mine else Decimal(0)
        if got < units:
            return None, f"FILLs for order {order_id} total {got}, the close filled {units}"
        return float(mine[0]["vwap"]), ""

    def _settle_unpriced(self, pos: EnginePosition, client_id: str, price: float) -> list[SettleEvent]:
        entry = pos.unpriced.pop(client_id)
        priced = self._priced(entry["event"], price)
        if not any(parse_close_client_order_id(k) and self._is_unsettled(pos, k) for k in pos.unpriced):
            self.hooks.block_entries(unsettled_block_key(pos.pair), None)
        pos.alerted.discard(f"unsettled:{client_id}")
        self._emit(pos, priced)
        return [priced]

    @staticmethod
    def _is_unsettled(pos: EnginePosition, client_id: str) -> bool:
        return f"unsettled:{client_id}" in pos.alerted

    # -- venue-side exits (§2.6) ----------------------------------------------------------------------------------------
    async def _settle_gone(self, pos: EnginePosition, limits: Any) -> list[SettleEvent]:
        if pos.entry_filled_at is None:
            return await self._unsettled(pos, "the entry order's venue fill time is unknown, so no fill can be attributed")
        rows = await self.adapter.fill_activities(pos.pair, after=pos.entry_filled_at)
        orders = [o for o in aggregate_closing_fills(rows, pair=pos.pair, exclude_order_id=pos.entry_order_id,
                                                     side="sell" if str(pos.direction).upper() == "LONG" else "buy")
                  if o["order_id"] not in pos.settled_order_ids]          # a close already settled here is not this exit
        total = sum((o["qty"] for o in orders), Decimal(0))
        if pos.units - total >= limits.min_order_size:
            return await self._unsettled(pos, f"closing fills total {total}, the engine held {pos.units}")
        hint = None
        events: list[SettleEvent] = []
        remaining = pos.units
        external: list[dict] = []
        for order in orders:
            if remaining <= 0:
                break
            client_id = await self.adapter.order_client_id(order["order_id"])
            parsed = parse_close_client_order_id(client_id)
            if parsed is not None and parsed[0] == str(pos.decision_id).replace("-", "").lower():
                # an ENGINE close the process did not live to settle (M7): settled as that leg, its mode from the hint
                if hint is None:
                    try:
                        hint = await self.hooks.read_hint(pos.decision_id) or {}
                    except Exception:  # noqa: BLE001
                        hint = {}
                leg = parsed[1]
                leg_hint = hint.get(leg) if isinstance(hint, dict) else None
                mode = leg_hint.get("mode") if isinstance(leg_hint, dict) and isinstance(leg_hint.get("mode"), str) \
                    else EXIT_MODE_UNRECORDED
                units = min(remaining, order["qty"])
                remaining -= units
                events.append(self._event(pos, leg=leg, client_id=client_id, venue_order_id=order["order_id"], units=units,
                                          fill=float(order["vwap"]), reason=REASON_ENGINE_CLOSE_FROM_FILLS, mark=None,
                                          mode=mode, level=None, close_time=order["last_time"], after_units=None))
            else:
                external.append(order)
        if external and remaining > 0:
            qty = sum((o["qty"] for o in external), Decimal(0))
            notional = sum((o["qty"] * o["vwap"] for o in external), Decimal(0))
            units = min(remaining, qty)                            # GX-4: the ENGINE's units, at the fills' VWAP
            remaining -= units
            events.append(self._event(pos, leg=None, client_id=None, venue_order_id=",".join(o["order_id"] for o in external),
                                      units=units, fill=float(notional / qty), reason=REASON_EXTERNAL_EXIT, mark=None,
                                      mode=EXIT_MODE_EXTERNAL, level=None,
                                      close_time=max(o["last_time"] for o in external), after_units=None))
        settled: list[SettleEvent] = []
        for event in events:
            pos.units -= Decimal(str(event["units"]))
            event["remaining_units"] = float(max(pos.units, Decimal(0)))
            event["partial"] = pos.units > 0
            self._emit(pos, event)
            settled.append(event)
        if pos.units < limits.min_order_size:
            pos.units = Decimal(0)
        return settled

    async def _unsettled(self, pos: EnginePosition, why: str) -> list[SettleEvent]:
        """X-4: nothing is settled and no price is guessed. The event (for the dashboard, never persisted) and the alert are
        both on the EDGE: a position that stays unaccountable is re-checked every pass without re-reporting it."""
        key = "unsettled"
        logger.error("live.unsettled_external_exit", decision_id=pos.decision_id, pair=pos.pair, why=why)
        if key in pos.alerted:
            return []
        pos.alerted.add(key)
        await self._alert(ALERT_UNSETTLED_EXTERNAL_EXIT, f"decision {pos.decision_id} ({pos.pair}) is gone at the venue "
                          f"and cannot be settled: {why}. It stays OPEN; no price is guessed.",
                          {"decision_id": pos.decision_id, "pair": pos.pair}, critical=True)
        return [SettleEvent(decision_id=pos.decision_id, pair=pos.pair, direction=pos.direction,
                            position_id=pos.decision_id, units=float(pos.units), entry=pos.entry_price, exit=None,
                            pnl=None, reason=REASON_UNSETTLED_EXTERNAL_EXIT, partial=False, resolves=False,
                            venue=getattr(self.adapter, "broker_name", None))]

    # -- events and persistence -----------------------------------------------------------------------------------------
    def _event(self, pos: EnginePosition, *, leg, client_id, venue_order_id, units: Decimal, fill, reason: str,
               mark: Mark | None, mode: str, level: float | None, close_time=None, after_units=None) -> SettleEvent:
        long = str(pos.direction).upper() == "LONG"
        exit_price = float(fill) if isinstance(fill, (int, float)) and not isinstance(fill, bool) else None
        mark_price = float(mark.price) if mark is not None and mark.price is not None else None
        event = SettleEvent(
            decision_id=pos.decision_id, pair=pos.pair, direction=pos.direction, position_id=pos.decision_id,
            units=float(units), entry=pos.entry_price, exit=exit_price, open_time=pos.opened_at,
            close_time=close_time if isinstance(close_time, datetime) else datetime.now(timezone.utc),
            partial=pos.units > 0, remaining_units=float(pos.units), reason=reason, leg=leg,
            stop_level=pos.stop, trigger_level=level, mark_at_detection=mark_price,
            mark_source=mark.source if mark is not None else None,
            detection_slippage=(mark_price - level) if mark_price is not None and level is not None else None,
            execution_slippage=(exit_price - mark_price) if exit_price is not None and mark_price is not None else None,
            execution_slippage_label="PAPER" if getattr(self.adapter, "is_paper_venue", False) else None,
            detection_interval_s=self.hooks.last_pass_s(),
            close_client_order_id=client_id, venue_order_id=venue_order_id,
            venue=getattr(self.adapter, "broker_name", None), exit_mode=mode, resolves=False,
        )
        return self._priced(event, exit_price, long=long)

    @staticmethod
    def _priced(event: SettleEvent, exit_price: float | None, *, long: bool | None = None) -> SettleEvent:
        event = SettleEvent(**event)
        if long is None:
            long = str(event.get("direction")).upper() == "LONG"
        event["exit"] = exit_price
        units, entry = event.get("units"), event.get("entry")
        if exit_price is None or units is None:
            event["fee_usd"], event["pnl"] = None, None
            return event
        fee = float(Decimal(str(units)) * Decimal(str(exit_price)) * SELL_FEE_RATE)
        event["fee_usd"] = fee
        event["pnl"] = (((exit_price - entry) if long else (entry - exit_price)) * units - fee) if entry is not None else None
        mark = event.get("mark_at_detection")
        event["execution_slippage"] = (exit_price - mark) if mark is not None else None
        return event

    def _emit(self, pos: EnginePosition, event: SettleEvent) -> None:
        key = event.get("close_client_order_id") or f"external:{event.get('venue_order_id')}"
        others_pending = any(k != key for k in pos.in_flight) or bool(pos.unpriced) or pos.pending_close is not None
        event["resolves"] = pos.units <= 0 and not others_pending
        pos.in_flight[key] = {"event": dict(event), "persist_failed": False}
        pos.settled_order_ids.update(i for i in str(event.get("venue_order_id") or "").split(",") if i)
        self.hooks.on_settle(event)

    def settle_persisted(self, event: dict, ok: bool) -> bool:
        """The loop reports a settle's write. Returns True when the decision should be RESOLVED now (P-5): every engine
        unit closed and no other closing fill still waiting for its write. A failed write keeps the marker and is
        retried at the next pass (GX-2, V-7b)."""
        pos = None
        for candidate in self.positions_for(str(event.get("pair"))):
            if candidate.decision_id == event.get("decision_id"):
                pos = candidate
                break
        if pos is None:
            return bool(ok and event.get("resolves"))
        key = event.get("close_client_order_id") or f"external:{event.get('venue_order_id')}"
        if not ok:
            if key in pos.in_flight:
                pos.in_flight[key]["persist_failed"] = True
            return False
        pos.in_flight.pop(key, None)
        return pos.units <= 0 and not pos.in_flight and not pos.unpriced and pos.pending_close is None

    def _retry_failed_settles(self, pos: EnginePosition) -> None:
        for key, entry in list(pos.in_flight.items()):
            if entry.get("persist_failed"):
                entry["persist_failed"] = False
                event = SettleEvent(**entry["event"])
                others_pending = any(k != key for k in pos.in_flight) or bool(pos.unpriced) or pos.pending_close is not None
                event["resolves"] = pos.units <= 0 and not others_pending
                self.hooks.on_settle(event)

    async def _alert(self, kind: str, message: str, context: dict, *, critical: bool) -> None:
        try:
            await self.hooks.alert(kind, message, context, critical)
        except Exception as exc:  # noqa: BLE001 - an alert never breaks a pass
            logger.error("live.venue_alert_failed", kind=kind, error=f"{type(exc).__name__}: {exc}")


def aggregate_closing_fills(rows: list[dict], *, pair: str, exclude_order_id: str | None, side: str) -> list[dict]:
    """X-1 / X-3b: FILL activity rows summed per `order_id`, for `pair` (canonically), on the closing `side`, excluding the
    entry order BY ID. Each: `{order_id, qty, vwap, first_time, last_time}`, ordered by `first_time` (transaction_time,
    never the activity id). A row whose qty or price cannot be read raises: an unreadable fill is not a zero."""
    grouped: dict[str, dict] = {}
    for row in rows:
        if not same_pair(row.get("symbol"), pair):
            continue
        if str(row.get("side", "")).lower() != side:
            continue
        order_id = str(row.get("order_id") or "")
        if not order_id or (exclude_order_id is not None and order_id == str(exclude_order_id)):
            continue
        qty, price, when = _dec(row.get("qty")), _dec(row.get("price")), row.get("transaction_time")
        if qty is None or price is None or qty <= 0 or price <= 0 or not isinstance(when, datetime):
            raise ValueError(f"an unreadable FILL row for order {order_id}: {row!r}")
        agg = grouped.setdefault(order_id, {"order_id": order_id, "qty": Decimal(0), "notional": Decimal(0),
                                            "first_time": when, "last_time": when})
        agg["qty"] += qty
        agg["notional"] += qty * price
        agg["first_time"] = min(agg["first_time"], when)
        agg["last_time"] = max(agg["last_time"], when)
    out = []
    for agg in grouped.values():
        out.append({"order_id": agg["order_id"], "qty": agg["qty"], "vwap": agg["notional"] / agg["qty"],
                    "first_time": agg["first_time"], "last_time": agg["last_time"]})
    return sorted(out, key=lambda o: o["first_time"])
