"""B428b commit (ii) — `position_events.VenueEvents` / `SimulatorEvents` (`T-0144` DESIGN §2.2–§2.6, revisions 5–6, the (ii)
rulings on price-pending closes). Arms named by review's rows (`_runs/b428b_ii/KILL_SET.md`): V, B, C, X, P-5, GX-2 and UP.

Driven with an adapter double and a hooks recorder: every rule here is `VenueEvents`' own; the adapter's members and the
loop's wiring have their own arms. Every drive is bounded.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal

import pytest

from app.services.live import position_events as pe

pytestmark = pytest.mark.asyncio

PAIR = "BTC/USD"
T0 = datetime(2026, 9, 14, 12, 0, 0, 123456, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------------------------------
# doubles
# ---------------------------------------------------------------------------------------------------

class _Limits:
    def __init__(self, min_order_size="0.000001", increment="0.000000001"):
        self.min_order_size = Decimal(min_order_size)
        self.min_trade_increment = Decimal(increment)

    def quantise_down(self, quantity):
        return (Decimal(quantity) / self.min_trade_increment).to_integral_value(rounding=ROUND_DOWN) * self.min_trade_increment


class _Venue:
    """An adapter double for `VenueEvents`: a venue position quantity, resting-order cancels, close orders that fill at
    `fill_price`, orders found by client id, and FILL activity rows. Every call is logged in order in `log`."""

    broker_name = "alpaca"
    is_paper_venue = True

    def __init__(self, qty="0.0002", fill_price=90.0, limits=None, log=None):
        self.qty = Decimal(qty)
        self.fill_price = fill_price
        self.limits = limits or _Limits()
        self.log = log if log is not None else []
        self.positions_error: Exception | None = None
        self.cancel_answer = {"cancelled": [], "failed": [], "resting": [], "complete": True}
        self.close_answer = None            # callable(pair, qty, cid) -> dict, or None for a full fill at fill_price
        self.orders_by_client: dict[str, dict] = {}
        self.fills: list[dict] = []
        self.client_ids: dict[str, str] = {}
        self.fills_after: list = []

    async def position_quantity(self, pair):
        self.log.append(("position_quantity", pair))
        if self.positions_error is not None:
            raise self.positions_error
        return self.qty

    async def asset_limits(self, pair):
        return self.limits

    async def cancel_open_orders_for(self, pair):
        self.log.append(("cancel_open_orders_for", pair))
        return dict(self.cancel_answer)

    async def place_close(self, pair, qty, client_order_id):
        self.log.append(("place_close", pair, qty, client_order_id))
        if self.close_answer is not None:
            out = self.close_answer(pair, qty, client_order_id)
        else:
            out = {"status": "FILLED", "filled_units": float(qty), "fill": self.fill_price, "terminal": True,
                   "position_id": f"order-{client_order_id[-3:]}", "client_order_id": client_order_id, "filled_at": T0}
        self.orders_by_client[client_order_id] = out
        if out.get("status") in ("FILLED", "PARTIALLY_FILLED") and out.get("filled_units"):
            self.qty -= Decimal(str(out["filled_units"]))
        return out

    async def find_order_by_client_id(self, client_order_id):
        self.log.append(("find_order_by_client_id", client_order_id))
        return self.orders_by_client.get(client_order_id)

    async def fill_activities(self, pair, after):
        self.log.append(("fill_activities", pair, after))
        self.fills_after.append(after)
        return list(self.fills)

    async def order_client_id(self, order_id):
        self.log.append(("order_client_id", order_id))
        return self.client_ids.get(order_id)


class _Hooks:
    def __init__(self, log=None):
        self.log = log if log is not None else []
        self.settles: list[dict] = []
        self.alerts: list[tuple] = []
        self.halts: list[str] = []
        self.blocks: dict[str, str] = {}
        self.block_calls: list[tuple] = []
        self.hints: dict[str, dict] = {}
        self.mode = "RUNNING"
        self.hint_error: Exception | None = None

    def build(self):
        async def _alert(kind, message, context, critical):
            self.alerts.append((kind, critical, message, context))

        def _block(key, reason):
            self.block_calls.append((key, reason))
            if reason is None:
                self.blocks.pop(key, None)
            else:
                self.blocks[key] = reason

        async def _write_hint(decision_id, leg, n, mode):
            self.log.append(("write_hint", leg, n, mode))
            if self.hint_error is not None:
                raise self.hint_error
            self.hints.setdefault(decision_id, {})[leg] = {"n": n, "mode": mode}

        async def _read_hint(decision_id):
            return self.hints.get(decision_id)

        return pe.VenueHooks(on_settle=self.settles.append, alert=_alert, declare_halt=self.halts.append,
                             block_entries=_block, write_hint=_write_hint, read_hint=_read_hint,
                             decided_mode=lambda: self.mode, last_pass_s=lambda: 1.25)


def _position(units="0.0002", stop=95.0, tp=None, partial_price=110.0, partial_fraction=0.7, **kw):
    return pe.EnginePosition(decision_id=str(uuid.uuid4()), pair=PAIR, direction="LONG", units=Decimal(units), stop=stop,
                             entry_price=100.0, tp=tp, partial_price=partial_price, partial_fraction=partial_fraction,
                             entry_order_id="entry-order", entry_filled_at=T0, opened_at=T0, **kw)


def _events(venue=None, positions=None, hooks=None):
    log: list = []
    venue = venue or _Venue(log=log)
    venue.log = log
    hooks = hooks or _Hooks(log=log)
    hooks.log = log
    book = {}
    for pos in positions or [_position()]:
        book[pos.decision_id] = {"pair": pos.pair, "record_pending": None, "position": pos}
    return pe.VenueEvents(venue, book, hooks.build()), venue, hooks, book


def _mark(price, source="binance_mark", blind=False):
    return pe.Mark(price=price, source=source, at=T0, blind=blind)


async def _tick(events, mark, pair=PAIR):
    async with asyncio.timeout(10):
        return await events.tick(pair, mark)


def _closes(venue):
    return [c for c in venue.log if c[0] == "place_close"]


# ---------------------------------------------------------------------------------------------------
# V — the tick
# ---------------------------------------------------------------------------------------------------

async def test_V1_SIMULATOR_events_are_paper_on_tick_UNCHANGED_and_nothing_without_a_price():
    calls = []

    class _Paper:
        def on_tick(self, pair, price):
            calls.append((pair, price))
            return [{"pair": pair, "reason": "SL"}]

    source = pe.SimulatorEvents(_Paper())
    assert await source.tick(PAIR, _mark(99.0)) == [{"pair": PAIR, "reason": "SL"}]
    assert await source.tick(PAIR, pe.Mark(price=None, source=None, at=None, blind=True)) == []
    assert calls == [(PAIR, 99.0)]


async def test_V3_the_STOP_at_mark_EQUAL_to_the_level_closes_the_ENGINE_units_only_STOP_HIT():
    pos = _position(units="0.0002", stop=95.0)
    events, venue, hooks, _ = _events(_Venue(qty="0.0010"), [pos])       # 0.0008 foreign units on the symbol
    out = await _tick(events, _mark(95.0))
    closes = _closes(venue)
    assert len(closes) == 1 and closes[0][2] == Decimal("0.0002"), f"not the engine's units at mark == stop: {closes}"
    assert closes[0][3] == pe.close_client_order_id(pos.decision_id, "s", 1) and closes[0][3].endswith("-s01")
    assert [e["reason"] for e in out] == [pe.REASON_STOP_HIT] and hooks.settles == out
    assert out[0]["pair"] == PAIR and out[0]["position_id"] == pos.decision_id                      # V-8
    assert pos.units == 0 and out[0]["resolves"] is True


async def test_V3b_a_venue_holding_LESS_than_the_book_is_closed_at_the_VENUEs_quantity_never_more():
    pos = _position(units="0.0003", stop=95.0)
    events, venue, _hooks, _ = _events(_Venue(qty="0.0002"), [pos])       # 0.0001 of the engine's units already gone
    await _tick(events, _mark(94.0))
    closes = _closes(venue)
    assert len(closes) == 1 and closes[0][2] == Decimal("0.0002"), f"a close larger than the venue holds: {closes}"


async def test_V4_the_2R_PARTIAL_is_taken_ONCE_and_sized_from_the_ENGINES_units_GX6():
    pos = _position(units="0.0002", stop=95.0, partial_price=110.0, partial_fraction=0.7)
    events, venue, hooks, _ = _events(_Venue(qty="0.0012"), [pos])       # engine 0.0002 + foreign 0.0010
    first = await _tick(events, _mark(111.0))
    second = await _tick(events, _mark(112.0))
    closes = _closes(venue)
    assert len(closes) == 1, f"the partial was sent again on the next pass: {closes}"
    assert closes[0][2] == Decimal("0.00014"), f"partial {closes[0][2]} is not 0.7 x min(book 0.0002, venue 0.0012)"
    assert closes[0][3].endswith("-p01") and [e["reason"] for e in first] == [pe.REASON_PARTIAL] and second == []
    assert pos.partial_taken and pos.units == Decimal("0.00006") and first[0]["partial"] is True


async def test_V5_one_positions_RAISE_never_skips_anothers_STOP_and_is_logged_with_its_decision_id():
    from tests.unit.test_b442_kill_switch_at_send import _capture_logs

    broken = _position(units="0.0001", stop=95.0)
    broken.stop = None                                  # its comparison raises inside the pass
    healthy = _position(units="0.0001", stop=95.0)
    events, venue, _hooks, _ = _events(_Venue(qty="0.0002"), [broken, healthy])
    lines, stop = _capture_logs()
    try:
        await _tick(events, _mark(94.0))
    finally:
        stop()
    assert [c[3] for c in _closes(venue)] == [pe.close_client_order_id(healthy.decision_id, "s", 1)]
    assert [l for l in lines if l["message"].startswith("live.venue_position_pass_failed")
            and l.get("decision_id") == broken.decision_id], lines


async def test_V6_UNREADABLE_positions_are_neither_BLIND_nor_GONE_and_six_passes_ALERT_and_HALT_entries_then_clear():
    pos = _position()
    events, venue, hooks, _ = _events(positions=[pos])
    venue.positions_error = TimeoutError("positions read timed out")
    for _ in range(5):
        assert await _tick(events, pe.Mark(price=None, source=None, at=None, blind=True)) == []
    assert _closes(venue) == [] and hooks.settles == [] and not [c for c in venue.log if c[0] == "fill_activities"]
    assert hooks.alerts == [] and pe.BLOCK_KEY_POSITIONS_UNREADABLE not in hooks.blocks
    await _tick(events, _mark(94.0))
    assert [a[:2] for a in hooks.alerts] == [(pe.ALERT_POSITIONS_UNREADABLE, True)]
    assert pe.BLOCK_KEY_POSITIONS_UNREADABLE in hooks.blocks and _closes(venue) == []
    await _tick(events, _mark(94.0))
    assert len(hooks.alerts) == 1, "the alert repeated (level-triggered)"
    venue.positions_error = None
    await _tick(events, _mark(99.0))
    assert pe.BLOCK_KEY_POSITIONS_UNREADABLE not in hooks.blocks, "the entry block did not clear when reads recovered"


async def test_V7a_V7c_qty_ZERO_while_a_settle_is_UNWRITTEN_is_never_EXTERNAL_and_V7b_a_failed_write_RETRIES():
    pos = _position(units="0.0002", stop=95.0)
    events, venue, hooks, _ = _events(_Venue(qty="0.0002"), [pos])
    (settle,) = await _tick(events, _mark(94.0))
    assert venue.qty == 0 and pos.in_flight
    assert await _tick(events, _mark(94.0)) == []
    assert not [c for c in venue.log if c[0] == "fill_activities"] and len(hooks.settles) == 1, (
        "venue qty 0 with the settle still being written was settled again")
    assert events.settle_persisted(settle, ok=False) is False
    await _tick(events, _mark(94.0))
    assert len(hooks.settles) == 2 and hooks.settles[1]["close_client_order_id"] == settle["close_client_order_id"]
    assert events.settle_persisted(hooks.settles[1], ok=True) is True and not pos.in_flight
    await _tick(events, _mark(94.0))
    assert len(hooks.settles) == 2 and len(_closes(venue)) == 1


async def test_V7c_GX2_a_runner_SOLD_ELSEWHERE_while_the_partials_write_is_pending_waits_then_settles_ONLY_that_sale():
    """V-7c with units still on the book: the partial filled and its row is not written yet, and the venue then shows 0 (the
    runner sold externally). Nothing is settled while the partial's marker stands; once it commits, the FILL settle counts
    the EXTERNAL sale only — the partial's own close order is never settled again as the runner's exit."""
    pos = _position(units="0.0002", stop=95.0, partial_price=110.0, partial_fraction=0.7)
    events, venue, hooks, _ = _events(_Venue(qty="0.0002", fill_price=111.0), [pos])
    (partial,) = await _tick(events, _mark(111.0))
    p_cid = partial["close_client_order_id"]
    assert pos.units == Decimal("0.00006") and venue.qty == Decimal("0.00006")
    venue.qty = Decimal(0)
    venue.client_ids = {partial["venue_order_id"]: p_cid}
    venue.fills = [
        {"order_id": partial["venue_order_id"], "symbol": "BTC/USD", "side": "sell", "qty": "0.00014", "price": "111",
         "transaction_time": T0 + timedelta(seconds=1)},
        {"order_id": "ext", "symbol": "BTC/USD", "side": "sell", "qty": "0.00006", "price": "100",
         "transaction_time": T0 + timedelta(seconds=2)},
    ]
    assert await _tick(events, _mark(100.0)) == []
    assert not [c for c in venue.log if c[0] == "fill_activities"], "settled as gone while the partial's write was pending"
    assert events.settle_persisted(partial, ok=True) is False
    (external,) = await _tick(events, _mark(100.0))
    assert external["reason"] == pe.REASON_EXTERNAL_EXIT and external["exit"] == 100.0, external
    assert external["units"] == pytest.approx(0.00006) and external["close_client_order_id"] is None
    assert [e["close_client_order_id"] for e in hooks.settles] == [p_cid, None], "the partial's order was settled twice"


async def test_V7d_X2_after_a_RESTART_a_cut_off_ENGINE_close_settles_as_ITS_LEG_by_the_client_id_prefix():
    pos = _position(units="0.0002", stop=95.0)
    events, venue, hooks, _ = _events(_Venue(qty="0"), [pos])
    cid = pe.close_client_order_id(pos.decision_id, "s", 3)
    hooks.hints[pos.decision_id] = {"s": {"n": 3, "mode": "RUNNING"}}
    venue.client_ids = {"close-order": cid}
    venue.fills = [{"order_id": "close-order", "symbol": "BTC/USD", "side": "sell", "qty": "0.0002", "price": "94.5",
                    "transaction_time": T0 + timedelta(minutes=5)}]
    out = await _tick(events, _mark(94.0))
    assert [(e["reason"], e["leg"], e["exit_mode"], e["close_client_order_id"]) for e in out] == [
        (pe.REASON_ENGINE_CLOSE_FROM_FILLS, "s", "RUNNING", cid)], out
    assert out[0]["exit"] == 94.5 and _closes(venue) == []


async def test_V7d_an_engine_close_with_NO_hint_settles_UNRECORDED_never_RUNNING():
    pos = _position(units="0.0002")
    events, venue, hooks, _ = _events(_Venue(qty="0"), [pos])
    venue.client_ids = {"close-order": pe.close_client_order_id(pos.decision_id, "b", 1)}
    venue.fills = [{"order_id": "close-order", "symbol": "BTCUSD", "side": "sell", "qty": "0.0002", "price": "90",
                    "transaction_time": T0 + timedelta(seconds=1)}]
    (event,) = await _tick(events, _mark(94.0))
    assert event["exit_mode"] == pe.EXIT_MODE_UNRECORDED and event["leg"] == "b"


# ---------------------------------------------------------------------------------------------------
# B — blindness
# ---------------------------------------------------------------------------------------------------

async def test_B2_a_BLIND_symbol_is_CLOSED_and_ONLY_its_entries_blocked_never_a_halt_and_B3_a_fresh_price_CLEARS():
    pos = _position(units="0.0002", stop=95.0)
    events, venue, hooks, _ = _events(_Venue(qty="0.0002"), [pos])
    out = await _tick(events, pe.Mark(price=None, source=None, at=None, blind=True))
    assert [e["reason"] for e in out] == [pe.REASON_STOP_BLIND] and _closes(venue)[0][3].endswith("-b01")
    assert list(hooks.blocks) == [pe.blind_block_key(PAIR)] and hooks.halts == [], (hooks.blocks, hooks.halts)
    assert [a[:2] for a in hooks.alerts] == [(pe.ALERT_STOP_BLIND_CLOSE, True)]
    await _tick(events, _mark(99.0))
    assert pe.blind_block_key(PAIR) not in hooks.blocks


async def test_B_no_price_that_is_NOT_blind_decides_NOTHING():
    pos = _position()
    events, venue, hooks, _ = _events(positions=[pos])
    assert await _tick(events, pe.Mark(price=None, source=None, at=None, blind=False)) == []
    assert _closes(venue) == [] and hooks.blocks == {}


# ---------------------------------------------------------------------------------------------------
# C — closes as orders
# ---------------------------------------------------------------------------------------------------

async def test_C1_a_close_is_a_SELL_with_the_40_char_engine_id_and_C2_resting_orders_are_CANCELLED_FIRST():
    pos = _position()
    events, venue, _hooks, _ = _events(positions=[pos])
    await _tick(events, _mark(94.0))
    names = [c[0] for c in venue.log if c[0] in ("cancel_open_orders_for", "place_close", "write_hint")]
    assert names == ["cancel_open_orders_for", "write_hint", "place_close"], names
    cid = _closes(venue)[0][3]
    assert len(cid) == 40 and cid == f"tai-{uuid.UUID(pos.decision_id).hex}-s01"
    assert not hasattr(venue, "close_position")


async def test_C3a_a_PROTECTIVE_close_blocked_SIX_CONSECUTIVE_passes_HALTS_once_naming_the_resting_ids_C3b_no_attempt_spent():
    pos = _position()
    events, venue, hooks, _ = _events(positions=[pos])
    venue.cancel_answer = {"cancelled": [], "failed": [("rest-1", "403")], "resting": ["rest-1"], "complete": False}
    for _ in range(5):
        await _tick(events, _mark(94.0))
    assert hooks.halts == [] and hooks.alerts == [] and _closes(venue) == []
    await _tick(events, _mark(94.0))
    await _tick(events, _mark(94.0))
    assert hooks.halts == [pe.HALT_CLOSE_BLOCKED]
    crit = [a for a in hooks.alerts if a[0] == pe.ALERT_CLOSE_NOT_SENT_RESTING_ORDER]
    assert len(crit) == 1 and crit[0][1] is True and "rest-1" in crit[0][3]["resting_order_ids"], hooks.alerts
    venue.cancel_answer = {"cancelled": ["rest-1"], "failed": [], "resting": [], "complete": True}
    await _tick(events, _mark(94.0))
    assert [c[3][-3:] for c in _closes(venue)] == ["s01"], "blocked passes consumed attempt numbers"


async def test_C3a_the_count_is_CONSECUTIVE_a_pass_that_sends_resets_it():
    pos = _position(units="0.0004")
    events, venue, hooks, _ = _events(_Venue(qty="0.0004"), [pos])
    blocked = {"cancelled": [], "failed": [("rest-1", "403")], "resting": ["rest-1"], "complete": False}
    venue.close_answer = lambda pair, qty, cid: {"status": "REJECTED", "rejection_code": "VENUE_ENDED_UNFILLED",
                                                 "filled_units": 0.0, "fill": None, "terminal": True}
    venue.cancel_answer = blocked
    for _ in range(5):
        await _tick(events, _mark(94.0))
    venue.cancel_answer = {"cancelled": ["rest-1"], "failed": [], "resting": [], "complete": True}
    await _tick(events, _mark(94.0))
    venue.cancel_answer = blocked
    for _ in range(5):
        await _tick(events, _mark(94.0))
    assert hooks.halts == [] and not [a for a in hooks.alerts if a[0] == pe.ALERT_CLOSE_NOT_SENT_RESTING_ORDER]


async def test_C3c_a_blocked_PROFIT_leg_only_ALERTS():
    pos = _position(stop=80.0, partial_price=110.0)
    events, venue, hooks, _ = _events(positions=[pos])
    venue.cancel_answer = {"cancelled": [], "failed": [("rest-1", "403")], "resting": ["rest-1"], "complete": False}
    for _ in range(6):
        await _tick(events, _mark(111.0))
    assert hooks.halts == [] and [a[:2] for a in hooks.alerts] == [(pe.ALERT_CLOSE_NOT_SENT_RESTING_ORDER, False)]


async def test_C4_quantised_DOWN_and_C5_a_partial_below_the_minimum_is_SKIPPED_with_a_reason_not_an_attempt():
    pos = _position(units="0.0000025", partial_price=110.0, partial_fraction=0.7)       # held >= the minimum,
    events, venue, hooks, _ = _events(_Venue(qty="0.0000025", limits=_Limits(min_order_size="0.000002",   # 70% is not
                                                                              increment="0.000001")), [pos])
    await _tick(events, _mark(111.0))
    await _tick(events, _mark(111.0))
    assert _closes(venue) == [] and not [c for c in venue.log if c[0] == "find_order_by_client_id"]
    assert pos.partial_skipped and "below the venue minimum" in pos.partial_skipped and not pos.partial_taken
    pos2 = _position(units="0.0001999", stop=95.0)
    events2, venue2, _h2, _ = _events(_Venue(qty="0.0001999", limits=_Limits(increment="0.000001")), [pos2])
    await _tick(events2, _mark(94.0))
    assert _closes(venue2)[0][2] == Decimal("0.000199"), "not quantised DOWN"


async def test_C6_the_settle_is_the_RESOLVED_fill_with_the_SELL_fee_and_P4_carries_every_price_field():
    pos = _position(units="0.0002", stop=95.0)
    events, venue, _hooks, _ = _events(_Venue(qty="0.0002", fill_price=94.2), [pos])
    (event,) = await _tick(events, _mark(94.5, source="alpaca_quote_mid"))
    assert event["exit"] == 94.2 and event["units"] == 0.0002
    assert event["fee_usd"] == pytest.approx(0.0002 * 94.2 * 0.0025)
    assert event["pnl"] == pytest.approx((94.2 - 100.0) * 0.0002 - 0.0002 * 94.2 * 0.0025)
    assert (event["stop_level"], event["trigger_level"], event["mark_at_detection"], event["mark_source"]) == (
        95.0, 95.0, 94.5, "alpaca_quote_mid")
    assert event["detection_slippage"] == pytest.approx(94.5 - 95.0)
    assert event["execution_slippage"] == pytest.approx(94.2 - 94.5)
    assert event["execution_slippage_label"] == "PAPER" and event["detection_interval_s"] == 1.25
    assert event["venue"] == "alpaca" and event["exit_mode"] == "RUNNING"


async def test_C7_a_PROTECTIVE_leg_ESCALATES_at_10_ONCE_keeps_SENDING_and_stops_past_99():
    pos = _position(units="0.0002")
    events, venue, hooks, _ = _events(positions=[pos])
    venue.close_answer = lambda pair, qty, cid: {"status": "REJECTED", "rejection_code": "VENUE_ENDED_UNFILLED",
                                                 "filled_units": 0.0, "fill": None, "terminal": True}
    for _ in range(11):
        await _tick(events, _mark(94.0))
    ids = [c[3][-3:] for c in _closes(venue)]
    assert ids == [f"s{n:02d}" for n in range(1, 12)], ids
    assert hooks.halts == [pe.HALT_CLOSE_ATTEMPTS_EXHAUSTED]
    assert len([a for a in hooks.alerts if a[0] == pe.ALERT_CLOSE_ATTEMPTS_EXHAUSTED]) == 1
    pos.attempts["s"] = 99
    await _tick(events, _mark(94.0))
    await _tick(events, _mark(94.0))
    assert len(_closes(venue)) == 11, "a 100th attempt was sent"
    assert len([a for a in hooks.alerts if a[0] == pe.ALERT_CLOSE_ATTEMPTS_EXHAUSTED]) == 3, "past 99 must alert every pass"


async def test_C8_a_PROFIT_leg_stops_past_NINE():
    pos = _position(stop=80.0, partial_price=110.0)
    events, venue, hooks, _ = _events(positions=[pos])
    venue.close_answer = lambda pair, qty, cid: {"status": "REJECTED", "filled_units": 0.0, "fill": None, "terminal": True}
    for _ in range(11):
        await _tick(events, _mark(111.0))
    assert [c[3][-3:] for c in _closes(venue)] == [f"p{n:02d}" for n in range(1, 10)]
    assert hooks.halts == [] and len([a for a in hooks.alerts if a[0] == pe.ALERT_CLOSE_ATTEMPTS_EXHAUSTED]) == 1


async def test_C9_the_HINT_is_written_BEFORE_the_send_with_the_DECIDED_mode_and_its_failure_never_blocks_the_send():
    pos = _position()
    hooks = _Hooks()
    hooks.mode = "RUNNING"
    events, venue, hooks, _ = _events(positions=[pos], hooks=hooks)
    original = venue.place_close

    async def _mode_changes_before_the_send(pair, qty, cid):
        hooks.mode = "MANAGE_ONLY"
        return await original(pair, qty, cid)

    venue.place_close = _mode_changes_before_the_send
    await _tick(events, _mark(94.0))
    assert hooks.hints[pos.decision_id] == {"s": {"n": 1, "mode": "RUNNING"}}
    assert [e["exit_mode"] for e in hooks.settles] == ["RUNNING"], "the settle re-read the mode after the decision"
    order = [c[0] for c in venue.log if c[0] in ("write_hint", "place_close")]
    assert order[0] == "write_hint", order

    pos2 = _position()
    failing = _Hooks()
    failing.hint_error = RuntimeError("database is down")
    events2, venue2, _h, _ = _events(positions=[pos2], hooks=failing)
    await _tick(events2, _mark(94.0))
    assert len(_closes(venue2)) == 1, "a failed hint write blocked the close"


async def test_C10_the_LAZY_probe_starts_at_the_hints_n_plus_1_and_C10a_reads_the_NEW_shape():
    pos = _position()
    events, venue, hooks, _ = _events(positions=[pos])
    hooks.hints[pos.decision_id] = {"s": {"n": 3, "mode": "RUNNING"}}
    await _tick(events, _mark(94.0))
    probes = [c[1] for c in venue.log if c[0] == "find_order_by_client_id"]
    assert probes == [pe.close_client_order_id(pos.decision_id, "s", 4)], probes
    assert _closes(venue)[0][3].endswith("-s04")


async def test_C10_with_NO_hint_the_probe_walks_from_1_past_EVERY_used_id():
    pos = _position()
    events, venue, _hooks, _ = _events(positions=[pos])
    for n in (1, 2, 3):
        venue.orders_by_client[pe.close_client_order_id(pos.decision_id, "s", n)] = {"status": "REJECTED", "terminal": True}
    await _tick(events, _mark(94.0))
    assert len([c for c in venue.log if c[0] == "find_order_by_client_id"]) == 4
    assert _closes(venue)[0][3].endswith("-s04")


async def test_C11_an_ACCEPTED_but_UNFILLED_close_is_resent_with_the_NEXT_attempt_never_the_same_id():
    pos = _position()
    events, venue, _hooks, _ = _events(positions=[pos])
    sent: set = set()

    def _answer(pair, qty, cid):
        if cid in sent:
            return {"status": "REJECTED", "rejection_code": "40010001", "reason": "client_order_id must be unique",
                    "filled_units": 0.0, "fill": None, "terminal": True}
        sent.add(cid)
        return {"status": "REJECTED", "rejection_code": "VENUE_ENDED_UNFILLED", "filled_units": 0.0, "fill": None,
                "terminal": True}

    venue.close_answer = _answer
    await _tick(events, _mark(94.0))
    await _tick(events, _mark(94.0))
    assert [c[3][-3:] for c in _closes(venue)] == ["s01", "s02"]


# ---------------------------------------------------------------------------------------------------
# X — venue-side exits
# ---------------------------------------------------------------------------------------------------

def test_X1_fills_are_SUMMED_per_order_and_X3b_the_ENTRY_is_excluded_by_ORDER_ID_ordered_by_TRANSACTION_TIME():
    rows = [
        # ids that sort OPPOSITE to transaction time (X-3c: order by the time, never by an id)
        {"order_id": "a-later", "symbol": "BTC/USD", "side": "sell", "qty": "0.0001", "price": "96", "transaction_time": T0 + timedelta(seconds=9)},
        {"order_id": "z-first", "symbol": "BTCUSD", "side": "sell", "qty": "0.0001", "price": "90", "transaction_time": T0 + timedelta(seconds=2)},
        {"order_id": "z-first", "symbol": "BTC/USD", "side": "sell", "qty": "0.0003", "price": "94", "transaction_time": T0 + timedelta(seconds=3)},
        {"order_id": "entry-order", "symbol": "BTC/USD", "side": "sell", "qty": "0.0004", "price": "100", "transaction_time": T0},
        {"order_id": "e2", "symbol": "BTC/USD", "side": "buy", "qty": "0.0004", "price": "100", "transaction_time": T0},
        {"order_id": "eth", "symbol": "ETH/USD", "side": "sell", "qty": "1", "price": "3000", "transaction_time": T0},
    ]
    out = pe.aggregate_closing_fills(rows, pair=PAIR, exclude_order_id="entry-order", side="sell")
    assert [(o["order_id"], o["qty"]) for o in out] == [("z-first", Decimal("0.0004")), ("a-later", Decimal("0.0001"))]
    assert out[0]["vwap"] == (Decimal("0.0001") * 90 + Decimal("0.0003") * 94) / Decimal("0.0004")


async def test_X3a_X3c_the_fill_bound_is_the_ENTRYs_VENUE_fill_time_at_FULL_precision():
    pos = _position(units="0.0002")
    pos.opened_at = T0 + timedelta(seconds=5)                                   # the LOCAL clock, 5 s ahead of the venue
    events, venue, _hooks, _ = _events(_Venue(qty="0"), [pos])
    venue.fills = [{"order_id": "ext", "symbol": "BTC/USD", "side": "sell", "qty": "0.0002", "price": "91",
                    "transaction_time": T0 + timedelta(microseconds=1)}]
    await _tick(events, _mark(94.0))
    assert venue.fills_after == [T0] and venue.fills_after[0].microsecond == 123456


async def test_X4_fills_that_CANNOT_account_settle_NOTHING_no_price_ALERT_once_and_the_decision_stays_OPEN():
    pos = _position(units="0.0002")
    events, venue, hooks, _ = _events(_Venue(qty="0"), [pos])
    venue.fills = [{"order_id": "ext", "symbol": "BTC/USD", "side": "sell", "qty": "0.0001", "price": "91",
                    "transaction_time": T0 + timedelta(seconds=1)}]
    out = await _tick(events, _mark(94.0))
    again = await _tick(events, _mark(94.0))
    assert again == [], "the unaccountable exit is re-reported to the dashboard every pass"
    assert len([c for c in venue.log if c[0] == "fill_activities"]) == 2, "the second pass did not re-check the FILLs"
    assert hooks.settles == [] and [e["reason"] for e in out] == [pe.REASON_UNSETTLED_EXTERNAL_EXIT]
    assert out[0]["exit"] is None and out[0]["pnl"] is None and pos.units == Decimal("0.0002")
    assert len([a for a in hooks.alerts if a[0] == pe.ALERT_UNSETTLED_EXTERNAL_EXIT]) == 1


async def test_X5_GX4_an_external_sale_with_FOREIGN_units_settles_the_ENGINEs_units_at_the_fills_VWAP():
    pos = _position(units="0.0002")
    events, venue, hooks, _ = _events(_Venue(qty="0"), [pos])
    venue.fills = [
        {"order_id": "ks", "symbol": "BTCUSD", "side": "sell", "qty": "0.0001", "price": "90", "transaction_time": T0 + timedelta(seconds=1)},
        {"order_id": "ks", "symbol": "BTCUSD", "side": "sell", "qty": "0.0002", "price": "93", "transaction_time": T0 + timedelta(seconds=2)},
    ]
    (event,) = await _tick(events, _mark(94.0))
    assert event["reason"] == pe.REASON_EXTERNAL_EXIT and event["units"] == 0.0002 and event["exit_mode"] == "EXTERNAL"
    assert event["exit"] == pytest.approx(float((Decimal("0.0001") * 90 + Decimal("0.0002") * 93) / Decimal("0.0003")))
    assert event["close_client_order_id"] is None and hooks.settles == [event]


# ---------------------------------------------------------------------------------------------------
# P-5 — resolution only when every closing fill is written
# ---------------------------------------------------------------------------------------------------

async def test_P5_RESOLUTION_waits_for_an_earlier_partials_WRITE():
    pos = _position(units="0.0002", stop=95.0, partial_price=110.0)
    events, venue, hooks, _ = _events(_Venue(qty="0.0002"), [pos])
    (partial,) = await _tick(events, _mark(111.0))
    (full,) = await _tick(events, _mark(94.0))
    assert partial["resolves"] is False and full["resolves"] is False, "resolved while the partial's write is pending"
    assert events.settle_persisted(full, ok=True) is False
    assert events.settle_persisted(partial, ok=True) is True


# ---------------------------------------------------------------------------------------------------
# UP — a close that FILLED with no readable price (the (ii) rulings)
# ---------------------------------------------------------------------------------------------------

def _unpriced(pair, qty, cid):
    return {"status": "FILLED", "filled_units": float(qty), "fill": None, "terminal": True, "position_id": "close-order",
            "client_order_id": cid, "filled_at": T0}


async def test_UP1_an_UNPRICED_fill_writes_NO_row_reduces_units_alerts_ONCE_and_is_never_EXTERNAL_then_ONE_row_on_a_price():
    pos = _position(units="0.0002", stop=95.0)
    events, venue, hooks, _ = _events(_Venue(qty="0.0002"), [pos])
    venue.close_answer = _unpriced
    assert await _tick(events, _mark(94.0)) == []
    assert hooks.settles == [] and pos.units == 0 and venue.qty == 0
    assert [a[0] for a in hooks.alerts] == [pe.ALERT_CLOSE_UNPRICED]
    assert await _tick(events, _mark(94.0)) == []
    assert not [c for c in venue.log if c[0] == "fill_activities"] and len(hooks.alerts) == 1
    cid = _closes(venue)[0][3]
    venue.orders_by_client[cid] = dict(venue.orders_by_client[cid], fill=93.9)
    (event,) = await _tick(events, _mark(94.0))
    assert event["exit"] == 93.9 and len(hooks.settles) == 1 and pos.in_flight and not pos.unpriced
    assert events.settle_persisted(event, ok=True) is True


async def test_UP2_SIX_passes_with_no_price_settle_from_its_OWN_fills_by_exact_order_at_the_VWAP():
    pos = _position(units="0.0002", stop=95.0)
    events, venue, hooks, _ = _events(_Venue(qty="0.0002"), [pos])
    venue.close_answer = _unpriced
    await _tick(events, _mark(94.0))
    cid = _closes(venue)[0][3]
    venue.client_ids = {"close-order": cid}
    venue.fills = [
        {"order_id": "close-order", "symbol": "BTC/USD", "side": "sell", "qty": "0.00005", "price": "93", "transaction_time": T0 + timedelta(seconds=1)},
        {"order_id": "close-order", "symbol": "BTC/USD", "side": "sell", "qty": "0.00015", "price": "95", "transaction_time": T0 + timedelta(seconds=2)},
        # ANOTHER order's fill, FIRST by transaction time: matching by anything but this close's exact order prices it at 50
        {"order_id": "other", "symbol": "BTC/USD", "side": "sell", "qty": "0.001", "price": "50", "transaction_time": T0 + timedelta(milliseconds=500)},
    ]
    for _ in range(5):
        assert await _tick(events, _mark(94.0)) == []
    (event,) = await _tick(events, _mark(94.0))
    assert event["exit"] == pytest.approx(float((Decimal("0.00005") * 93 + Decimal("0.00015") * 95) / Decimal("0.0002")))
    assert event["close_client_order_id"] == cid and len(hooks.settles) == 1


async def test_UP2b_fills_of_an_order_the_venue_says_carries_ANOTHER_client_id_price_NOTHING():
    """The close's order id is only a lead: the venue must confirm that order carries THIS close's client id before its
    FILLs price it. Here it names another close's id, so six passes end in the CRITICAL, with no row."""
    pos = _position(units="0.0002", stop=95.0)
    events, venue, hooks, _ = _events(_Venue(qty="0.0002"), [pos])
    venue.close_answer = _unpriced
    await _tick(events, _mark(94.0))
    cid = _closes(venue)[0][3]
    venue.client_ids = {"close-order": pe.close_client_order_id(pos.decision_id, "s", 2)}
    venue.fills = [{"order_id": "close-order", "symbol": "BTC/USD", "side": "sell", "qty": "0.0002", "price": "93",
                    "transaction_time": T0 + timedelta(seconds=1)}]
    for _ in range(6):
        assert await _tick(events, _mark(94.0)) == []
    assert hooks.settles == [] and cid in pos.unpriced
    assert [a for a in hooks.alerts if a[0] == pe.ALERT_UNSETTLED_EXTERNAL_EXIT and a[1] is True], hooks.alerts


async def test_UP3_fills_that_do_NOT_account_are_CRITICAL_BLOCK_that_symbol_KEEP_the_marker_and_LIFT_only_when_they_do():
    pos = _position(units="0.0002", stop=95.0)
    events, venue, hooks, _ = _events(_Venue(qty="0.0002"), [pos])
    venue.close_answer = _unpriced
    await _tick(events, _mark(94.0))
    cid = _closes(venue)[0][3]
    venue.client_ids = {"close-order": cid}
    venue.fills = [{"order_id": "close-order", "symbol": "BTC/USD", "side": "sell", "qty": "0.0001", "price": "93",
                    "transaction_time": T0 + timedelta(seconds=1)}]
    for _ in range(12):
        await _tick(events, _mark(94.0))
    crit = [a for a in hooks.alerts if a[0] == pe.ALERT_UNSETTLED_EXTERNAL_EXIT]
    assert len(crit) == 1 and crit[0][1] is True and pe.unsettled_block_key(PAIR) in hooks.blocks
    assert hooks.settles == [] and pos.unpriced and not [e for e in hooks.settles if e.get("reason") == "EXTERNAL_EXIT"]
    venue.fills.append({"order_id": "close-order", "symbol": "BTC/USD", "side": "sell", "qty": "0.0001", "price": "95",
                        "transaction_time": T0 + timedelta(seconds=2)})
    for _ in range(6):
        await _tick(events, _mark(94.0))
    assert len(hooks.settles) == 1 and hooks.settles[0]["exit"] == pytest.approx(94.0)
    assert pe.unsettled_block_key(PAIR) not in hooks.blocks
