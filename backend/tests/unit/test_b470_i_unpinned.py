"""B470 — (i)t: the arms B428b (i) lost or never had. Production at 8fa3ef1 is correct; nothing pinned these lines.

Named by review's rows (`_runs/b428b_it/KILL_SET.md`):
  iR7 / iR8 / iR8b   the REAL loop's tick reaches an entry priced by THIS tick's Binance mark, stamped with the tick's
                     recorded READ time, while a fresh and DIFFERENT venue quote and a different broker price are present
  iR8s               a mark older than 60 s (and younger than 600 s) is not used: the entry prices off the quote's mid
  iM6b / iM6c        a book entry keeps its SUBMITTING row out of the abandonment, keyed by DECISION ID, not by pair
  iQ6c               a non-list positions answer on the BEFORE read refuses, and nothing is sent
  iQ6d               an unreadable quantity on a MATCHING position refuses before, and is unsized after; a non-matching
                     one is ignored

Self-contained: every fixture and double is defined here and helpers from other test modules are imported INSIDE the
functions that use them, so importing this file changes nothing outside it (DC-2). Every drive is bounded (DC-4), and
every network call on a driven path is replaced under the suite's B432 guard (DC-3).
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy import select

from app.db.enums import DirectionType, OrderType
from app.services.broker.base import OrderRequest

pytestmark = pytest.mark.asyncio

PAIR, BSYM = "BTC/USD", "BTCUSDT"
MARK = 100.0
QUOTE_BID, QUOTE_ASK = 100.4, 100.6            # a fresh venue quote whose mid (100.5) differs from the mark
BROKER_PRICE = 102.0                           # a broker reference price that differs from both
FEE = Decimal("0.0025")


# ---------------------------------------------------------------------------------------------------
# the suite's guard is what keeps these arms off the network (DC-3)
# ---------------------------------------------------------------------------------------------------

async def test_DC3_the_suites_network_guard_is_installed_for_this_file():
    import socket

    from tests._network_guard import GUARD

    assert GUARD._installed, "the B432 guard is not installed, so a network call on a driven path would go out"
    assert socket.socket.connect.__qualname__.startswith("NetworkGuard.install"), socket.socket.connect
    assert socket.getaddrinfo.__qualname__.startswith("NetworkGuard.install"), socket.getaddrinfo


# ---------------------------------------------------------------------------------------------------
# iR7 / iR8 / iR8b / iR8s — the loop's Binance-first wiring
# ---------------------------------------------------------------------------------------------------

def _bars():
    base = [MARK] * 60
    return pd.DataFrame({"open": base, "high": [b + 1 for b in base], "low": [b - 1 for b in base],
                         "close": base, "volume": [10.0] * 60})


def _signal():
    from app.services.execution.service import Signal

    return Signal(symbol=PAIR, direction=DirectionType.LONG, entry=MARK, sl=MARK - 10.0, risk_pct=0.01)


def _loop_with_competing_prices(monkeypatch):
    """The REAL loop on its simulator broker, its REAL `ExecutionService` (built by the loop, with the loop's own
    `_binance_mark`), and two competing prices a wrong wiring would show: a FRESH venue quote with a different mid, and a
    broker reference price that differs from both. Every I/O dependency of the tick is replaced; the order is filled by
    the simulator itself. The executed result is captured by a spy that DELEGATES to the loop's own `execute`."""
    from app.services.execution.reference import VenueQuote
    from app.services.live import crypto_loop as mod

    loop = mod.LiveCryptoLoop(broker_mode="paper")
    record = {"ticker": [], "quotes": [], "broker_prices": [], "executed": [], "presend": []}

    class _Trace:
        reasons = ["b470"]

        def __getattr__(self, _):
            return None

    async def _noop(*a, **k):
        return None

    async def _fetch(*a, **k):
        return _bars()

    async def _false(*a, **k):
        return False

    async def _zero(*a, **k):
        return 0

    def _ticker(bsym):
        record["ticker"].append(bsym)
        return MARK

    async def _quote(symbol):
        record["quotes"].append(symbol)
        return VenueQuote(bid=QUOTE_BID, ask=QUOTE_ASK, timestamp=datetime.now(timezone.utc))

    async def _broker_price(symbol):
        record["broker_prices"].append(symbol)
        return BROKER_PRICE

    async def _presend(*a, **k):
        record["presend"].append(a)

    execute = loop.execution.execute

    async def _spy(sig):
        res = await execute(sig)
        record["executed"].append(res)
        return res

    sig = _signal()
    monkeypatch.setattr(mod, "_ticker_price", _ticker)
    monkeypatch.setattr(mod, "evaluate_latest_bar_traced", lambda *a, **k: (sig, _Trace()))
    monkeypatch.setattr(mod.exit_shadow, "record_from_loop", lambda *a, **k: None)
    for name in ("push_tick", "push_position_open", "push_position_close", "push_position_update", "broadcast",
                 "push_alert"):
        monkeypatch.setattr(mod.ws_manager, name, _noop)
    for name in ("_act", "_close_at_session_end", "_shadow_evaluate", "_maybe_emit_census", "_news_context",
                 "_record_abstention", "_record_signal_decision", "_record_rejected_signal", "_on_unresolved_order"):
        monkeypatch.setattr(loop, name, _noop)
    monkeypatch.setattr(loop, "_fetch_bars", _fetch)
    monkeypatch.setattr(loop, "_has_position", _false)
    monkeypatch.setattr(loop, "_open_count", _zero)
    monkeypatch.setattr(loop, "_write_submitting", _presend)
    monkeypatch.setattr(loop.paper, "reference_quote", _quote, raising=False)
    monkeypatch.setattr(loop.paper, "reference_price", _broker_price, raising=False)
    monkeypatch.setattr(loop.execution, "execute", _spy)
    return loop, sig, record


async def test_iR7_iR8_iR8b_the_REAL_tick_prices_its_entry_off_THIS_ticks_BINANCE_mark_stamped_with_its_READ_time(
        monkeypatch):
    loop, _sig, record = _loop_with_competing_prices(monkeypatch)
    async with asyncio.timeout(20):
        await loop._tick_symbol(PAIR, BSYM)

    assert record["ticker"] == [BSYM], f"the tick did not read its mark through the patched ticker: {record['ticker']}"
    assert record["presend"], "the tick never reached the order path, so nothing below was measured"
    assert len(record["executed"]) == 1, record["executed"]
    res = record["executed"][0]
    read_at = loop._mark_at.get(PAIR)
    assert read_at is not None, "the tick did not record when it read the mark"
    assert res.get("status") == "FILLED", res
    assert res.get("reference_source") == "binance_mark", (
        f"the entry was not priced by the loop's Binance mark: {res.get('reference_source')!r} (a fallback, or the "
        f"mark never reached the service)")
    assert res.get("sizing_price") == MARK, f"priced at {res.get('sizing_price')!r}, not the tick's mark {MARK}"
    assert res.get("reference_at") == read_at.isoformat(), (
        f"reference_at {res.get('reference_at')!r} is not the tick's RECORDED read time {read_at.isoformat()!r}")
    assert record["quotes"] == [] and record["broker_prices"] == [], (
        f"a usable mark was present and a fallback was still read: quotes {record['quotes']}, "
        f"broker prices {record['broker_prices']}")


async def test_iR8s_a_mark_older_than_60s_is_NOT_used_the_entry_prices_off_the_fresh_quote_and_NAMES_it(monkeypatch):
    """Older than `BINANCE_MARK_MAX_AGE_S` (60 s) and younger than 600 s, so a 600 s bound would still use it."""
    loop, sig, record = _loop_with_competing_prices(monkeypatch)
    loop.paper.on_tick(PAIR, MARK)                       # the simulator fills at its own mark
    loop._marks[PAIR] = MARK
    loop._mark_at[PAIR] = datetime.now(timezone.utc) - timedelta(seconds=300)
    async with asyncio.timeout(20):
        res = await loop.execution.execute(sig)          # the loop's own service and its own `_binance_mark`

    assert res.get("status") == "FILLED", res
    assert res.get("reference_source") == "alpaca_quote_mid", (
        f"a 300 s old Binance mark was used as the entry's reference: {res.get('reference_source')!r}")
    assert res.get("sizing_price") == (QUOTE_BID + QUOTE_ASK) / 2, res.get("sizing_price")
    assert record["quotes"] == [PAIR] and record["broker_prices"] == [], record


# ---------------------------------------------------------------------------------------------------
# iM6b / iM6c — the book keeps its SUBMITTING row out of the abandonment, by decision id
# ---------------------------------------------------------------------------------------------------

@pytest.fixture
async def b470_db(engine, monkeypatch):
    """The suite's in-memory database, bound as the loop's session maker for THIS test only."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    import app.db.session as dbsession

    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(dbsession, "async_session_maker", maker)
    return maker


async def _submitting_row(maker, pair: str) -> str:
    from app.models.decision_record import COHORT_PAPER, OUTCOME_SUBMITTING, DecisionRecord

    rec = DecisionRecord(id=uuid.uuid4(), symbol=pair, timeframe="1H", inputs_hash="a" * 16, code_path_hash="b" * 16,
                         abstained=False, outcome=OUTCOME_SUBMITTING, cohort=COHORT_PAPER)
    async with maker() as db:
        db.add(rec)
        await db.commit()
    return str(rec.id)


async def test_iM6b_iM6c_a_BOOK_entry_keeps_its_SUBMITTING_row_by_DECISION_ID_while_a_same_pair_row_is_ABANDONED(b470_db):
    from app.models.decision_record import OUTCOME_ABANDONED, OUTCOME_OPEN, OUTCOME_SUBMITTING, DecisionRecord
    from app.services.live.crypto_loop import LiveCryptoLoop

    in_book = await _submitting_row(b470_db, PAIR)
    stranded = await _submitting_row(b470_db, PAIR)          # SAME pair, different decision id
    loop = LiveCryptoLoop(broker_mode="paper")
    loop._book[in_book] = {"pair": PAIR, "record_pending": (OUTCOME_OPEN, {"sized_units": Decimal("0.01")})}

    async with asyncio.timeout(20):
        abandoned = await loop.reconcile_abandoned_decisions()

    async with b470_db() as db:
        outcomes = {str(r.id): r.outcome for r in (await db.execute(select(DecisionRecord))).scalars().all()}
    assert outcomes[stranded] == OUTCOME_ABANDONED and abandoned == 1, (
        f"the call did not abandon the stranded row, so it proves nothing about the book: {outcomes}, {abandoned}")
    assert outcomes[in_book] == OUTCOME_SUBMITTING, (
        f"the book's own SUBMITTING row (decision {in_book}) was abandoned: {outcomes}")


# ---------------------------------------------------------------------------------------------------
# iQ6c / iQ6d — the BEFORE and AFTER position reads
# ---------------------------------------------------------------------------------------------------

class _PositionsVenue:
    """A synchronous `TradingClient` double: an entry fills on its first re-read. `answers` scripts `get_all_positions`
    one call at a time (the last answer repeats)."""

    def __init__(self, answers):
        self._api_key = f"PK-B470-{uuid.uuid4().hex}"
        self.answers = list(answers)
        self.calls: list[tuple] = []
        self.orders: dict[str, dict] = {}

    def get_asset(self, symbol):
        from tests.unit.test_t0140_order_body import _asset

        return _asset(symbol, min_order_size=1e-9)

    def submit_order(self, order_data):
        from tests.unit.test_b442_kill_switch_at_send import _sdk_order

        self.calls.append(("submit_order", order_data.qty))
        oid = uuid.uuid4()
        self.orders[str(oid)] = {"symbol": order_data.symbol, "qty": Decimal(repr(order_data.qty))}
        return _sdk_order(oid, order_data.symbol, "accepted", "0")

    def get_order_by_id(self, order_id, filter=None):
        from tests.unit.test_b442_kill_switch_at_send import _sdk_order

        o = self.orders[str(order_id)]
        order = _sdk_order(uuid.UUID(str(order_id)), o["symbol"], "filled", str(o["qty"]))
        object.__setattr__(order, "filled_qty", str(o["qty"]))
        return order

    def get_all_positions(self):
        self.calls.append(("get_all_positions",))
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        return answer() if callable(answer) else answer

    def get_open_position(self, symbol):
        raise RuntimeError(f"404 position does not exist: {symbol}")

    def get_order_by_client_id(self, client_id):
        raise RuntimeError("not scripted")


def _adapter(venue):
    from tests.unit.test_b442_kill_switch_at_send import _alpaca

    adapter, _clock = _alpaca(venue)
    return adapter


def _req(lot=0.01):
    return OrderRequest(pair=PAIR, direction=DirectionType.LONG, order_type=OrderType.MARKET, lot_size=lot,
                        client_order_id=f"tai-{uuid.uuid4().hex}")


def _position(symbol, qty):
    from tests.unit.test_t0136_alpaca_adapter import _Position

    return _Position(symbol=symbol, qty=qty)


def _submits(venue):
    return [c for c in venue.calls if c[0] == "submit_order"]


@pytest.mark.parametrize("answer", [None, {"BTCUSD": "0.5"}], ids=["None", "dict"])
async def test_iQ6c_a_NON_LIST_positions_answer_on_the_BEFORE_read_REFUSES_and_sends_NOTHING(answer):
    from app.core.exceptions import BrokerError

    venue = _PositionsVenue([answer])
    adapter = _adapter(venue)
    async with asyncio.timeout(10):
        with pytest.raises(BrokerError):
            await adapter.place_order(_req())
    assert [c for c in venue.calls if c[0] == "get_all_positions"], "the BEFORE read never ran"
    assert _submits(venue) == [], f"a non-list positions answer was read as flat and the order was SENT: {venue.calls}"


@pytest.mark.parametrize("qty", [None, "garbage"], ids=["None", "garbage"])
async def test_iQ6d_an_UNREADABLE_qty_on_a_MATCHING_position_REFUSES_on_the_BEFORE_read_and_sends_NOTHING(qty):
    from app.core.exceptions import BrokerError

    venue = _PositionsVenue([[_position("BTCUSD", qty)]])
    adapter = _adapter(venue)
    async with asyncio.timeout(10):
        with pytest.raises(BrokerError):
            await adapter.place_order(_req())
    assert _submits(venue) == [], f"an unreadable held quantity counted as 0 and the order was SENT: {venue.calls}"


@pytest.mark.parametrize("qty", [None, "garbage"], ids=["None", "garbage"])
async def test_iQ6d_an_UNREADABLE_qty_on_the_AFTER_read_is_UNSIZED_never_a_number(qty):
    from app.services.live.crypto_loop import LiveCryptoLoop

    venue = _PositionsVenue([[], [_position("BTCUSD", qty)]])     # flat before; the after read cannot be read
    adapter = _adapter(venue)
    async with asyncio.timeout(10):
        res = await adapter.place_order(_req())
    assert len(_submits(venue)) == 1 and res.get("status") == "FILLED", (venue.calls, res)
    assert res.get("held_units") is None, f"an unreadable AFTER quantity became a number: {res.get('held_units')!r}"
    check = res.get("units_check") or {}
    assert "error" in check and "within" not in check, (
        f"the unreadable AFTER read was measured as a quantity instead of reported unreadable: {check}")
    assert LiveCryptoLoop._position_units(res) is None, "the loop would size this entry instead of taking the unsized path"


async def test_iQ6d_MUST_MISS_an_unreadable_qty_on_a_NON_matching_position_is_IGNORED_and_the_entry_proceeds():
    venue = _PositionsVenue([
        [_position("ETHUSD", "garbage")],
        lambda: [_position("ETHUSD", "garbage"), _position("BTCUSD", str(Decimal("0.01") * (1 - FEE)))],
    ])
    adapter = _adapter(venue)
    async with asyncio.timeout(10):
        res = await adapter.place_order(_req(0.01))
    assert len(_submits(venue)) == 1, f"a foreign symbol's unreadable quantity refused this entry: {venue.calls}"
    assert res.get("status") == "FILLED" and res.get("units_check", {}).get("within") is True, res


# ---------------------------------------------------------------------------------------------------
# iD5b — the REAL pre-send writer's failure stops the send; iD7a2 — NOT_SENT stays outside the classifier
# ---------------------------------------------------------------------------------------------------

@pytest.fixture
async def b470_file_db(tmp_path, monkeypatch):
    """A FILE database with NullPool (every session its own connection, so a read inside the send sees only COMMITTED
    rows), bound as the loop's session maker for THIS test only. `state["commit_fails"]` makes every commit raise."""
    from sqlalchemy import JSON, MetaData
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    import app.db.session as dbsession
    import app.models  # noqa: F401 - register every model
    from app.db.base import Base

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'b470.db'}", poolclass=NullPool)
    # A COPY of the models' metadata, so SQLite's JSON stand-in for JSONB never touches the shared `Base.metadata` (DC-2).
    metadata = MetaData()
    for table in Base.metadata.sorted_tables:
        table.to_metadata(metadata)
    for table in metadata.sorted_tables:
        for col in table.columns:
            if isinstance(col.type, JSONB):
                col.type = JSON()
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    state = {"commit_fails": False}

    class _Session(AsyncSession):
        async def commit(self):
            if state["commit_fails"]:
                raise RuntimeError("database is down (b470: the session's commit raises)")
            return await super().commit()

    maker = async_sessionmaker(bind=engine, class_=_Session, expire_on_commit=False)
    healthy = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(dbsession, "async_session_maker", maker)
    yield state, healthy
    await engine.dispose()


def _loop_to_the_send(monkeypatch, place_order):
    """The REAL loop's tick to the order path with the REAL `_write_submitting` and the REAL `ExecutionService`; only the
    broker's `place_order`, the tick's I/O, and the post-verdict recorders are replaced."""
    from app.services.live import crypto_loop as mod

    loop = mod.LiveCryptoLoop(broker_mode="paper")
    alerts: list = []

    class _Trace:
        reasons = ["b470"]

        def __getattr__(self, _):
            return None

    async def _noop(*a, **k):
        return None

    async def _fetch(*a, **k):
        return _bars()

    async def _false(*a, **k):
        return False

    async def _zero(*a, **k):
        return 0

    async def _alert(kind, **k):
        alerts.append(kind)

    sig = _signal()
    monkeypatch.setattr(mod, "_ticker_price", lambda _bsym: MARK)
    monkeypatch.setattr(mod, "evaluate_latest_bar_traced", lambda *a, **k: (sig, _Trace()))
    monkeypatch.setattr(mod.exit_shadow, "record_from_loop", lambda *a, **k: None)
    for name in ("push_tick", "push_position_open", "push_position_close", "push_position_update", "broadcast",
                 "push_alert"):
        monkeypatch.setattr(mod.ws_manager, name, _noop)
    for name in ("_act", "_close_at_session_end", "_shadow_evaluate", "_maybe_emit_census", "_news_context",
                 "_record_abstention", "_record_signal_decision", "_record_rejected_signal", "_on_unresolved_order"):
        monkeypatch.setattr(loop, name, _noop)
    monkeypatch.setattr(loop, "_raise_record_alert", _alert)
    monkeypatch.setattr(loop, "_fetch_bars", _fetch)
    monkeypatch.setattr(loop, "_has_position", _false)
    monkeypatch.setattr(loop, "_open_count", _zero)
    monkeypatch.setattr(loop.paper, "place_order", place_order)
    return loop, sig, alerts


async def _decision_rows(maker):
    from app.models.decision_record import DecisionRecord

    async with maker() as db:
        return list((await db.execute(select(DecisionRecord))).scalars().all())


async def test_iD5b_the_REAL_presend_writer_failing_INSIDE_its_commit_sends_NOTHING_and_writes_no_row(
        monkeypatch, b470_file_db):
    state, healthy = b470_file_db
    sent: list = []

    async def _place(req):
        sent.append(req)
        return {"status": "FILLED", "filled_units": req.lot_size, "units": req.lot_size, "fill": MARK,
                "position_id": "b470", "client_order_id": req.client_order_id}

    loop, sig, alerts = _loop_to_the_send(monkeypatch, _place)
    execute = loop.execution.execute
    results: list = []

    async def _spy(s):
        res = await execute(s)
        results.append(res)
        return res

    monkeypatch.setattr(loop.execution, "execute", _spy)
    state["commit_fails"] = True
    async with asyncio.timeout(20):
        await loop._tick_symbol(PAIR, BSYM)

    assert results, "the tick never reached execute, so nothing below was measured"
    assert sent == [], f"the pre-send record's commit FAILED and the order was still SENT: {sent}"
    assert results[0].get("status") == "NOT_SENT", results[0]
    assert getattr(sig, "submitting_written", False) is False
    state["commit_fails"] = False
    assert await _decision_rows(healthy) == [], "a row exists although the commit failed"


async def test_iD5b_MUST_MISS_a_HEALTHY_database_sends_exactly_ONCE_with_the_SUBMITTING_row_already_COMMITTED(
        monkeypatch, b470_file_db):
    from app.models.decision_record import OUTCOME_SUBMITTING

    _state, healthy = b470_file_db
    sent: list = []
    at_send: list = []

    async def _place(req):
        at_send.append([(str(r.id), r.outcome) for r in await _decision_rows(healthy)])
        sent.append(req)
        return {"status": "FILLED", "filled_units": req.lot_size, "units": req.lot_size, "fill": MARK,
                "position_id": "b470", "client_order_id": req.client_order_id}

    loop, sig, _alerts = _loop_to_the_send(monkeypatch, _place)
    async with asyncio.timeout(20):
        await loop._tick_symbol(PAIR, BSYM)

    assert len(sent) == 1, f"a healthy pre-send write did not lead to exactly one send: {sent}"
    assert at_send == [[(str(sig.decision_id), OUTCOME_SUBMITTING)]], (
        f"the SUBMITTING row was not committed AT the send: {at_send}")


async def test_iD7a2_NOT_SENT_is_in_NONE_of_the_classifiers_sets_and_classifies_UNRESOLVED():
    from app.services.execution.service import STATUS_NOT_SENT
    from app.services.live.crypto_loop import (
        FILL_BEARING_STATUSES, NOT_FROM_THIS_LOOP_STATUSES, ORDER_UNRESOLVED, REFUSAL_STATUSES, classify_order_status,
    )

    assert STATUS_NOT_SENT not in FILL_BEARING_STATUSES, FILL_BEARING_STATUSES
    assert STATUS_NOT_SENT not in REFUSAL_STATUSES, REFUSAL_STATUSES
    assert STATUS_NOT_SENT not in NOT_FROM_THIS_LOOP_STATUSES, NOT_FROM_THIS_LOOP_STATUSES
    assert classify_order_status(STATUS_NOT_SENT) == ORDER_UNRESOLVED, classify_order_status(STATUS_NOT_SENT)
