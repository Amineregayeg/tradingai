"""B428b commit (ii) — the LOOP's side of venue position events (`T-0144` DESIGN §2.2–§2.4, R1'''/R13/M3, B460, the (ii)
rulings). Arms named by review's rows (`_runs/b428b_ii/KILL_SET.md`): V-1, V-2, V-8, B-1, B-4, B-5, T-1, T-2, P-1..P-5,
M18-2, M18-3, UP-3.

`VenueEvents`' own rules are `test_b428b_ii_position_events.py`; here the REAL loop drives them: `_tick_symbol` with its mark
chain, `_on_settle_cb`'s tasks, `_persist_and_resolve`, the Trade row and the decision's resolution, on the suite's SQLite
database. The Binance ticker is replaced on every drive (`B432`); every drive is bounded.
"""
from __future__ import annotations

import asyncio
import gc
import uuid
import weakref
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy import select

from app.services.live import position_events as pe
from tests.unit.test_b428b_ii_position_events import T0, _Venue

pytestmark = pytest.mark.asyncio

PAIR, BSYM = "BTC/USD", "BTCUSDT"


@pytest.fixture
async def bound(engine, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    import app.db.session as dbsession

    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(dbsession, "async_session_maker", maker)
    return maker


class _LoopVenue(_Venue):
    """`_Venue` plus the one member the loop's mark chain reads."""

    def __init__(self, *a, quote=None, **k):
        super().__init__(*a, **k)
        self.quote = quote

    async def reference_quote(self, pair):
        self.log.append(("reference_quote", pair))
        return self.quote


def _venue_loop(monkeypatch, venue=None, *, binance=None):
    """A real `LiveCryptoLoop` bound to a VENUE double through `_build_events`, with the strategy half stubbed out: a pass
    manages positions and returns at the bar fetch. `binance["price"]` is the Binance ticker's answer (None: an outage)."""
    from app.services.live import crypto_loop as mod

    loop = mod.LiveCryptoLoop(broker_mode="paper")
    venue = venue or _LoopVenue()
    loop.paper = venue
    loop.events = loop._build_events(venue)
    assert loop.events.kind == "venue"
    ticker = binance if binance is not None else {"price": 100.0}

    async def _noop(*a, **k):
        return None

    async def _empty(*a, **k):
        return pd.DataFrame()

    monkeypatch.setattr(mod, "_ticker_price", lambda _bsym: ticker["price"])
    for name in ("push_tick", "push_position_open", "push_position_close", "push_position_update", "broadcast",
                 "push_alert"):
        monkeypatch.setattr(mod.ws_manager, name, _noop)
    monkeypatch.setattr(loop, "_fetch_bars", _empty)
    monkeypatch.setattr(loop, "_close_at_session_end", _noop)
    monkeypatch.setattr(loop, "_act", _noop)
    return loop, venue, ticker


async def _decision(maker, *, run_id=None, units="0.2", fill=100.0, sl=95.0):
    from app.models.decision_record import COHORT_PAPER, OUTCOME_OPEN, DecisionRecord

    rec = DecisionRecord(id=uuid.uuid4(), symbol=PAIR, timeframe="1H", inputs_hash="a" * 16, code_path_hash="b" * 16,
                         abstained=False, outcome=OUTCOME_OPEN, cohort=COHORT_PAPER, sized_units=Decimal(units),
                         fill_price=Decimal(str(fill)), signal_entry=Decimal(str(fill)), signal_sl=Decimal(str(sl)),
                         run_id=run_id)
    async with maker() as db:
        db.add(rec)
        await db.commit()
    return str(rec.id)


def _book(loop, decision_id, *, units="0.2", stop=95.0, partial_price=110.0, partial_fraction=0.7):
    pos = pe.EnginePosition(decision_id=decision_id, pair=PAIR, direction="LONG", units=Decimal(units), stop=stop,
                            entry_price=100.0, tp=None, partial_price=partial_price, partial_fraction=partial_fraction,
                            entry_order_id="entry-order", entry_filled_at=T0, opened_at=T0)
    loop._book[decision_id] = {"pair": PAIR, "record_pending": None, "position": pos}
    loop._open_decision[PAIR] = decision_id
    return pos


async def _pass(loop):
    async with asyncio.timeout(20):
        await loop._tick_symbol(PAIR, BSYM)
        while loop._settle_tasks:
            await asyncio.gather(*list(loop._settle_tasks), return_exceptions=True)


async def _trades(maker):
    from app.models.trade import Trade

    async with maker() as db:
        return list((await db.execute(select(Trade))).scalars().all())


async def _record(maker, decision_id):
    from app.models.decision_record import DecisionRecord

    async with maker() as db:
        return (await db.execute(select(DecisionRecord).where(DecisionRecord.id == uuid.UUID(decision_id)))).scalar_one()


def _closes(venue):
    return [c for c in venue.log if c[0] == "place_close"]


# ---------------------------------------------------------------------------------------------------
# V-1 / V-8 / P-2 / P-3 / M18-2 — one venue stop, through the loop, to the row and the resolution
# ---------------------------------------------------------------------------------------------------

async def test_V1_V8_a_VENUE_stop_through_the_LOOP_writes_the_row_under_the_LOOPS_PAIR_and_the_DECISIONS_run_and_resolves(
        bound, monkeypatch):
    decision_run, loop_run = uuid.uuid4(), uuid.uuid4()
    loop, venue, _ = _venue_loop(monkeypatch, _LoopVenue(qty="0.2"), binance={"price": 94.0})
    loop.run_id = loop_run
    loop._last_pass_s = 2.5
    dec = await _decision(bound, run_id=decision_run)
    _book(loop, dec)

    await _pass(loop)

    (close,) = _closes(venue)
    sent_id = close[3]
    assert sent_id == pe.close_client_order_id(dec, "s", 1) and len(sent_id) == 40
    assert close[1] == PAIR, "the adapter is asked with the LOOP's pair; it canonicalises for the venue itself"
    (row,) = await _trades(bound)
    assert row.pair == PAIR, f"V-8: the row carries {row.pair!r}, not the loop's pair"
    assert row.broker == "alpaca", f"P-2: broker {row.broker!r}"
    assert row.run_id == decision_run and row.run_id != loop_run, "P-3: the row is filed under the DECISION's run"
    assert row.broker_id == dec
    assert row.close_client_order_id == sent_id, "M18-2: the stored close id is the id SENT, whole"
    assert row.exit_mode == "RUNNING"
    assert float(row.mark_at_detection) == 94.0 and row.mark_source == "binance_mark"
    assert float(row.detection_interval_s) == 2.5, "B-5: the event's interval is the loop's measured pass"
    assert float(row.sl) == 95.0 and float(row.lot_size) == 0.2
    rec = await _record(bound, dec)
    assert rec.outcome == "LOSS" and rec.realized_r is not None, (rec.outcome, rec.realized_r)
    assert dec not in loop._book, "the resolved position's book entry is done"


# ---------------------------------------------------------------------------------------------------
# V-2 / B-1 / B-4 — the mark chain and blindness, through `_mark_for`
# ---------------------------------------------------------------------------------------------------

def _quote(bid, ask, age_s):
    from app.services.execution.reference import VenueQuote

    return VenueQuote(bid=bid, ask=ask, timestamp=datetime.now(timezone.utc) - timedelta(seconds=age_s))


async def test_V2_B4_a_BINANCE_outage_with_a_FRESH_venue_quote_still_STOPS_OUT_and_the_row_names_the_QUOTE(bound, monkeypatch):
    venue = _LoopVenue(qty="0.2", quote=_quote(93.0, 94.0, age_s=300))
    loop, venue, _ = _venue_loop(monkeypatch, venue, binance={"price": None})
    loop._mark_at[PAIR] = datetime.now(timezone.utc) - timedelta(seconds=30)
    dec = await _decision(bound)
    _book(loop, dec)

    await _pass(loop)

    assert len(_closes(venue)) == 1, "no stop-out on a Binance outage with a fresh venue quote below the stop"
    (row,) = await _trades(bound)
    assert row.mark_source == "alpaca_quote_mid" and float(row.mark_at_detection) == 93.5, (row.mark_source,
                                                                                            row.mark_at_detection)


@pytest.mark.parametrize("binance_age_s, quote, blind", [
    (100, None, False),                             # a minute's Binance failure is not blindness (180 s, not 60)
    (170, _quote(99.0, 99.2, age_s=599), False),    # a quote under 600 s by its OWN stamp is a price, above the stop
    (200, _quote(99.0, 99.2, age_s=300), False),    # Binance stale AND a fresh quote: NOT blind (AND, not OR)
    (200, _quote(99.0, 99.2, age_s=700), True),     # the quote is 700 s old by its stamp, however recently it was READ
    (181, None, True),                              # past 180 s with no quote: blind
])
async def test_B1_BLIND_is_no_Binance_mark_for_180s_AND_no_quote_younger_than_600s_by_its_OWN_stamp(
        bound, monkeypatch, binance_age_s, quote, blind):
    venue = _LoopVenue(qty="0.2", quote=quote)
    loop, venue, _ = _venue_loop(monkeypatch, venue, binance={"price": None})
    loop._mark_at[PAIR] = datetime.now(timezone.utc) - timedelta(seconds=binance_age_s)
    dec = await _decision(bound)
    _book(loop, dec)

    await _pass(loop)

    closes = _closes(venue)
    if blind:
        assert len(closes) == 1 and closes[0][3] == pe.close_client_order_id(dec, "b", 1), closes
        assert pe.blind_block_key(PAIR) in loop._entry_blocks, loop._entry_blocks
        assert loop.halt_reason is None, "B-2: blindness blocks ONE symbol's entries, never a halt of the engine"
    else:
        assert closes == [], f"closed with Binance {binance_age_s}s stale and quote {quote}"
        assert pe.blind_block_key(PAIR) not in loop._entry_blocks


async def test_B1_the_constants_are_the_ruled_values():
    assert pe.BINANCE_MARK_BLIND_AFTER_S == 180.0 and pe.ALPACA_QUOTE_STOP_MAX_AGE_S == 600.0


# ---------------------------------------------------------------------------------------------------
# B-5 — the interval is measured
# ---------------------------------------------------------------------------------------------------

async def test_B5_the_pass_interval_is_MEASURED_wall_time_not_the_poll_constant(monkeypatch):
    from app.services.live import crypto_loop as mod

    loop = mod.LiveCryptoLoop(broker_mode="paper", symbols={PAIR: BSYM})
    loop.poll_interval = 0

    async def _slow_tick(pair, bsym):
        await asyncio.sleep(0.25)
        loop._running = False

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(loop, "_tick_symbol", _slow_tick)
    monkeypatch.setattr(loop, "_retry_pending_records", _noop)
    monkeypatch.setattr(loop, "_push_state", _noop)
    loop._running = True
    async with asyncio.timeout(10):
        await loop._loop()
    assert 0.25 <= loop._last_pass_s < 5, loop._last_pass_s
    assert loop.events.kind == "simulator" and loop.events is not None
    vloop, _venue, _ = _venue_loop(monkeypatch)
    vloop._last_pass_s = 7.125
    assert vloop.events.hooks.last_pass_s() == 7.125, "the hook reads the loop's measurement when asked, not a copy"


# ---------------------------------------------------------------------------------------------------
# T-1 / T-2 — B460
# ---------------------------------------------------------------------------------------------------

async def test_T1_a_pending_settle_task_is_HELD_through_a_gc_and_RELEASED_when_it_finishes(monkeypatch):
    from app.services.live import crypto_loop as mod

    loop = mod.LiveCryptoLoop(broker_mode="paper")
    running = asyncio.get_running_loop()
    reported: list[dict] = []
    previous = running.get_exception_handler()
    running.set_exception_handler(lambda _l, ctx: reported.append(ctx))
    futures: list[weakref.ref] = []
    finished: list[dict] = []

    async def _persist(ev):
        fut = running.create_future()               # referenced only by this frame: the task is all that holds it
        futures.append(weakref.ref(fut))
        await fut
        finished.append(ev)

    monkeypatch.setattr(loop, "_persist_and_resolve", _persist)
    try:
        loop._on_settle_cb({"pair": PAIR, "pnl": 1.0})
        for _ in range(3):
            await asyncio.sleep(0)
        assert len(loop._settle_tasks) == 1 and futures
        gc.collect()
        for _ in range(3):
            await asyncio.sleep(0)
        fut = futures[0]()
        assert fut is not None, "the pending settle was COLLECTED: nothing held its task"
        assert not [c for c in reported if "destroyed but it is pending" in str(c.get("message"))], reported
        fut.set_result(None)
        async with asyncio.timeout(5):
            while loop._settle_tasks:
                await asyncio.sleep(0)
        assert finished == [{"pair": PAIR, "pnl": 1.0}]
    finally:
        running.set_exception_handler(previous)


async def test_T1_control_an_UNHELD_task_of_the_same_shape_IS_collected_so_the_arm_can_see_it():
    running = asyncio.get_running_loop()
    reported: list[dict] = []
    previous = running.get_exception_handler()
    running.set_exception_handler(lambda _l, ctx: reported.append(ctx))
    futures: list[weakref.ref] = []

    async def _persist():
        fut = running.create_future()
        futures.append(weakref.ref(fut))
        await fut

    try:
        running.create_task(_persist())
        for _ in range(3):
            await asyncio.sleep(0)
        gc.collect()
        for _ in range(3):
            await asyncio.sleep(0)
        assert futures and futures[0]() is None, "the control task survived a gc: the T-1 arm cannot distinguish"
        assert [c for c in reported if "destroyed but it is pending" in str(c.get("message"))], reported
    finally:
        running.set_exception_handler(previous)


async def test_T2_a_RAISING_settle_is_RETRIEVED_and_logged_never_reported_as_never_retrieved(monkeypatch):
    from app.services.live import crypto_loop as mod
    from tests.unit.test_b442_kill_switch_at_send import _capture_logs

    loop = mod.LiveCryptoLoop(broker_mode="paper")
    running = asyncio.get_running_loop()
    reported: list[dict] = []
    previous = running.get_exception_handler()
    running.set_exception_handler(lambda _l, ctx: reported.append(ctx))

    async def _persist(ev):
        raise RuntimeError("the database went away")

    monkeypatch.setattr(loop, "_persist_and_resolve", _persist)
    lines, stop = _capture_logs()
    try:
        loop._on_settle_cb({"pair": PAIR})
        async with asyncio.timeout(5):
            while loop._settle_tasks:
                await asyncio.sleep(0)
        for _ in range(3):
            await asyncio.sleep(0)
        gc.collect()
        for _ in range(3):
            await asyncio.sleep(0)
    finally:
        stop()
        running.set_exception_handler(previous)
    assert not [c for c in reported if "never retrieved" in str(c.get("message"))], reported
    assert [l for l in lines if l["message"].startswith("live.settle_task_failed")
            and "the database went away" in str(l.get("error"))], lines


# ---------------------------------------------------------------------------------------------------
# P-1 / P-4 / M18-3 / UP-3 — the row
# ---------------------------------------------------------------------------------------------------

def _venue_event(dec, **over):
    ev = dict(decision_id=dec, pair=PAIR, direction="LONG", position_id=dec, units=0.0002, entry=100.0, exit=94.0,
              pnl=-1.25, fee_usd=0.047, open_time=T0, close_time=T0 + timedelta(hours=1), partial=False,
              remaining_units=0.0, reason=pe.REASON_STOP_HIT, leg="s", stop_level=95.0, trigger_level=95.0,
              mark_at_detection=94.2, mark_source="binance_mark", detection_slippage=-0.8, execution_slippage=-0.2,
              execution_slippage_label="PAPER", detection_interval_s=1.5,
              close_client_order_id=pe.close_client_order_id(dec, "s", 1), venue_order_id="o-1", venue="alpaca",
              exit_mode="RUNNING", resolves=True)
    ev.update(over)
    return ev


async def test_P1_a_venue_event_with_NO_pnl_writes_NO_row_and_leaves_the_decision_OPEN_never_a_zero(bound):
    from app.services.live.crypto_loop import LiveCryptoLoop

    loop = LiveCryptoLoop(broker_mode="paper")
    dec = await _decision(bound)
    ev = _venue_event(dec, pnl=None, exit=None)
    assert await loop._persist_live_close(ev) is False
    assert await _trades(bound) == []
    assert await loop._realised_pnl_for_position(ev) is None, "an unknown venue P&L became a number"
    await loop._resolve_decision(ev)
    rec = await _record(bound, dec)
    assert rec.outcome == "OPEN" and rec.realized_r is None, (rec.outcome, rec.realized_r)
    # the pair: a simulator event without a P&L is the simulators' unchanged rule
    assert await loop._realised_pnl_for_position({"pnl": None}) == 0.0


async def test_P4_the_row_takes_its_mark_FROM_THE_EVENT_and_M18_3_EXTERNAL_and_SIMULATOR_rows_carry_no_engine_id(bound):
    from app.services.live.crypto_loop import LiveCryptoLoop

    loop = LiveCryptoLoop(broker_mode="paper")
    loop._marks[PAIR] = 80.0                              # the loop's mark at PERSIST time differs from the event's
    loop._last_pass_s = 9.0
    dec = await _decision(bound)
    assert await loop._persist_live_close(_venue_event(dec)) is True
    external = _venue_event(dec, leg=None, close_client_order_id=None, exit_mode="EXTERNAL", mark_at_detection=None,
                            mark_source=None, reason=pe.REASON_EXTERNAL_EXIT, venue_order_id="o-9")
    assert await loop._persist_live_close(external) is True
    sim = {"pair": PAIR, "direction": "LONG", "position_id": "paper-1", "units": 0.01, "entry": 100.0, "exit": 101.0,
           "pnl": 1.0, "open_time": T0, "close_time": T0, "partial": False, "reason": "TP_HIT"}
    assert await loop._persist_live_close(sim) is True
    by_id = {r.close_client_order_id: r for r in await _trades(bound)}
    venue_row = by_id[pe.close_client_order_id(dec, "s", 1)]
    assert float(venue_row.mark_at_detection) == 94.2 and venue_row.mark_source == "binance_mark"
    assert float(venue_row.detection_interval_s) == 1.5
    ext_row = [r for r in await _trades(bound) if r.exit_mode == "EXTERNAL"]
    assert len(ext_row) == 1 and ext_row[0].close_client_order_id is None, "M18-3: an external exit has no engine id"
    (sim_row,) = [r for r in await _trades(bound) if r.broker_id == "paper-1"]
    assert (sim_row.close_client_order_id, sim_row.exit_mode, sim_row.mark_at_detection, sim_row.mark_source,
            sim_row.detection_interval_s) == (None, None, None, None, None), "a SIMULATOR row wrote a venue field"
    assert sim_row.broker == "paper"


@pytest.mark.parametrize("pnl, outcome", [(0.40, "WIN"), (0.004, "BE"), (-0.004, "BE"), (0.0, "BE"), (-0.40, "LOSS"),
                                          (0.005, "WIN")])
async def test_UP3_a_VENUE_outcome_is_by_sign_TO_THE_CENT(bound, pnl, outcome):
    from app.services.live.crypto_loop import LiveCryptoLoop

    loop = LiveCryptoLoop(broker_mode="paper")
    dec = await _decision(bound)
    assert await loop._persist_live_close(_venue_event(dec, pnl=pnl)) is True
    (row,) = await _trades(bound)
    got = row.outcome.value if hasattr(row.outcome, "value") else row.outcome
    assert got == outcome, (pnl, got)


@pytest.mark.parametrize("pnl, outcome", [(0.004, "WIN"), (0.0, "LOSS"), (-0.004, "LOSS")])
async def test_UP3_pair_the_SIMULATOR_outcome_rule_is_UNCHANGED(bound, pnl, outcome):
    from app.services.live.crypto_loop import LiveCryptoLoop

    loop = LiveCryptoLoop(broker_mode="paper")
    sim = {"pair": PAIR, "direction": "LONG", "position_id": "paper-1", "units": 0.01, "entry": 100.0, "exit": 100.0,
           "pnl": pnl, "open_time": T0, "close_time": T0, "partial": False, "reason": "TP_HIT"}
    assert await loop._persist_live_close(sim) is True
    (row,) = await _trades(bound)
    got = row.outcome.value if hasattr(row.outcome, "value") else row.outcome
    assert got == outcome, (pnl, got)


# ---------------------------------------------------------------------------------------------------
# P-5 — through the loop: the write that completes the position is an EARLIER partial's
# ---------------------------------------------------------------------------------------------------

async def test_P5_through_the_LOOP_the_decision_resolves_when_the_LAST_write_is_the_PARTIALs_and_counts_BOTH_legs(
        bound, monkeypatch):
    loop, venue, ticker = _venue_loop(monkeypatch, _LoopVenue(qty="0.2"), binance={"price": 111.0})
    dec = await _decision(bound)
    _book(loop, dec)
    gate = asyncio.Event()
    real = loop._persist_live_close

    async def _gated(ev):
        if ev.get("leg") == "p":
            await gate.wait()
        return await real(ev)

    monkeypatch.setattr(loop, "_persist_live_close", _gated)
    async with asyncio.timeout(20):
        await loop._tick_symbol(PAIR, BSYM)                 # the 2R partial: its write is held
        for _ in range(5):
            await asyncio.sleep(0)
        ticker["price"] = 94.0
        venue.fill_price = 94.0
        await loop._tick_symbol(PAIR, BSYM)                 # the stop: the runner closes and writes first
        assert [c[3][-3:] for c in _closes(venue)] == ["p01", "s01"], _closes(venue)
        while len(loop._settle_tasks) > 1:                   # the runner's settle finishes; the partial's stays held
            await asyncio.sleep(0.01)
        assert len(await _trades(bound)) == 1
        assert (await _record(bound, dec)).outcome == "OPEN", "resolved while the partial's write was pending"
        gate.set()
        while loop._settle_tasks:
            await asyncio.gather(*list(loop._settle_tasks), return_exceptions=True)
    rows = await _trades(bound)
    assert len(rows) == 2
    rec = await _record(bound, dec)
    total = sum(float(r.pnl_dollars) for r in rows)
    assert rec.outcome == ("WIN" if total > 0 else "LOSS"), (rec.outcome, total)
    expected_r = total / (abs(100.0 - 95.0) * 0.2)
    assert rec.realized_r is not None and abs(float(rec.realized_r) - round(expected_r, 4)) < 1e-4, (rec.realized_r,
                                                                                                    expected_r)


# ---------------------------------------------------------------------------------------------------
# X-3a — the book entry at the fill; C-9a — the hint in the record; B-2 / UP-1c3 — the loop's entry blocks
# ---------------------------------------------------------------------------------------------------

async def test_X3a_a_VENUE_fill_BOOKS_the_position_with_the_ENTRY_ORDERs_venue_fill_time_id_and_MEASURED_units(
        file_bound, monkeypatch):
    """Through the real order path (commit (i)'s driven loop), with the loop's event source a VENUE: the fill result's
    `filled_at` (the venue's, full precision) is the FILL bound, never a local clock; the units are the measured
    `held_units`, not the size asked for."""
    from tests.unit.test_b428b_i_identity_price_quantities import _driven_loop, _filled, _tick

    venue_time = datetime(2026, 9, 14, 11, 59, 58, 987654, tzinfo=timezone.utc)

    async def _place(req):
        return _filled(req, filled_at=venue_time, held_units=0.0099)

    loop, _acts, sig = _driven_loop(monkeypatch, _place)
    loop.events = loop._build_events(_LoopVenue())
    await _tick(loop)

    (entry,) = loop._book.values()
    pos = entry["position"]
    assert pos.decision_id == str(sig.decision_id) and pos.pair == PAIR
    assert pos.entry_filled_at == venue_time, f"the FILL bound is {pos.entry_filled_at!r}, not the venue's fill time"
    assert pos.entry_order_id == "order-1" and pos.entry_client_order_id == f"tai-{sig.decision_id.hex}"
    assert pos.units == Decimal("0.0099") and pos.stop == float(sig.sl), (pos.units, pos.stop)
    assert loop._tranche_plans == {}, "a venue position's plan went to the simulators' tranche plans"


@pytest.fixture
async def file_bound(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    import app.db.session as dbsession
    from tests.unit.test_b428b_i_identity_price_quantities import _create_all

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'b428b_ii.db'}", poolclass=NullPool)
    await _create_all(engine)
    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(dbsession, "async_session_maker", maker)
    yield maker
    await engine.dispose()


async def test_C9a_the_loops_HINT_write_stores_n_AND_the_DECIDED_mode_per_leg_and_reads_back_the_same_shape(bound):
    from app.services.live.crypto_loop import LiveCryptoLoop

    loop = LiveCryptoLoop(broker_mode="paper")
    dec = await _decision(bound)
    await loop._write_close_hint(dec, "s", 3, "MANAGE_ONLY")
    await loop._write_close_hint(dec, "p", 1, "RUNNING")
    await loop._write_close_hint(dec, "s", 4, "STOPPING")
    assert await loop._read_close_hint(dec) == {"s": {"n": 4, "mode": "STOPPING"}, "p": {"n": 1, "mode": "RUNNING"}}
    assert (await _record(bound, dec)).close_attempt_hint == {"s": {"n": 4, "mode": "STOPPING"},
                                                              "p": {"n": 1, "mode": "RUNNING"}}
    with pytest.raises(LookupError):
        await loop._write_close_hint(str(uuid.uuid4()), "s", 1, "RUNNING")


async def test_B2_UP1c3_a_SYMBOLs_block_refuses_only_THAT_symbol_and_an_unreadable_venue_refuses_EVERY_symbol():
    from app.services.live.crypto_loop import LiveCryptoLoop

    loop = LiveCryptoLoop(broker_mode="paper")
    assert await loop._entry_block_reason("BTC/USD") is None and await loop._entry_block_reason("ETH/USD") is None
    loop._set_entry_block(pe.blind_block_key("BTC/USD"), "BTC/USD is BLIND")
    assert "BLIND" in str(await loop._entry_block_reason("BTC/USD"))
    assert await loop._entry_block_reason("ETH/USD") is None, "another symbol's blindness blocked ETH"
    loop._set_entry_block(pe.blind_block_key("BTC/USD"), None)
    loop._set_entry_block(pe.unsettled_block_key("ETH/USD"), "ETH/USD unsettled close")
    assert "unsettled" in str(await loop._entry_block_reason("ETH/USD"))
    assert await loop._entry_block_reason("BTC/USD") is None
    loop._set_entry_block(pe.unsettled_block_key("ETH/USD"), None)
    loop._set_entry_block(pe.BLOCK_KEY_POSITIONS_UNREADABLE, "venue positions unreadable")
    for pair in ("BTC/USD", "ETH/USD"):
        assert "unreadable" in str(await loop._entry_block_reason(pair)), pair
    loop._set_entry_block(pe.BLOCK_KEY_POSITIONS_UNREADABLE, None)
    assert await loop._entry_block_reason("BTC/USD") is None and loop.halt_reason is None
