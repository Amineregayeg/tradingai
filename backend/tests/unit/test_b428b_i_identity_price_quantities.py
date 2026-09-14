"""B428b commit (i) — identity, price, pair, minimum, quantities (`T-0144` DESIGN §4-§6, rulings R3', R4, R5', R5'',
R6', R11', revision 5's G-5/G-6/M-6). Arms are named by review's registered rows (`_runs/b428b_i/KILL_SET.md`): P, D, T,
M-6, R, S, Q, B. The pair-scan-as-a-test (P-5) is `test_b428b_i_pair_scan.py`; migration 0017 and the vocabulary (M-1..M-5)
are in `test_decision_record_schema.py` and the consumers' own files.

Every drive is bounded (`asyncio.timeout`); nothing here touches the network (the Binance ticker is replaced on every
loop drive — `B432`). Rows that must be durable use a real SQLite database; the arms that read the pre-send row from a
SEPARATE session use a FILE database with no shared connection, because an in-memory StaticPool shares one connection
and would show an uncommitted row (review's D-6).
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy import select

from app.db.enums import DirectionType, OrderType
from app.services.broker.base import OrderRequest

pytestmark = pytest.mark.asyncio

FEE = Decimal("0.0025")


# ---------------------------------------------------------------------------------------------------
# databases
# ---------------------------------------------------------------------------------------------------

async def _create_all(engine):
    import app.models  # noqa: F401 - register every model
    from sqlalchemy import JSON
    from sqlalchemy.dialects.postgresql import JSONB

    from app.db.base import Base

    for table in Base.metadata.sorted_tables:
        for col in table.columns:
            if isinstance(col.type, JSONB):
                col.type = JSON()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture
async def bound(engine, monkeypatch):
    """The suite's in-memory database, bound as the loop's session maker."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    import app.db.session as dbsession

    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(dbsession, "async_session_maker", maker)
    return maker


@pytest.fixture
async def file_bound(tmp_path, monkeypatch):
    """A FILE database with NullPool: every session is its own connection, so an uncommitted row is invisible to it."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    import app.db.session as dbsession

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'b428b_i.db'}", poolclass=NullPool)
    await _create_all(engine)
    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(dbsession, "async_session_maker", maker)
    yield maker
    await engine.dispose()


async def _rows(maker):
    from app.models.decision_record import DecisionRecord

    async with maker() as db:
        return list((await db.execute(select(DecisionRecord))).scalars().all())


# ---------------------------------------------------------------------------------------------------
# a loop driven to the order path with the REAL ExecutionService
# ---------------------------------------------------------------------------------------------------

def _bars():
    base = [100.0 + i * 0.0 for i in range(60)]
    return pd.DataFrame({"open": base, "high": [b + 1 for b in base], "low": [b - 1 for b in base],
                         "close": base, "volume": [10.0] * 60})


def _driven_loop(monkeypatch, place_order, *, sl: float = 99.0):
    """`_tick_symbol` to the order path with every I/O dependency replaced EXCEPT the pre-send write, the real
    `ExecutionService` and the recorders. `place_order` replaces the paper broker's."""
    from app.services.execution.service import Signal
    from app.services.live import crypto_loop as mod

    loop = mod.LiveCryptoLoop(broker_mode="paper")
    acts: list[tuple[str, str]] = []
    sig = Signal(symbol="BTC/USD", direction=DirectionType.LONG, entry=100.0, sl=sl, risk_pct=0.01)

    class _Trace:
        reasons = ["b428b-i"]

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

    async def _act(kind, msg):
        acts.append((kind, msg))

    monkeypatch.setattr(mod, "_ticker_price", lambda _bsym: 100.0)
    monkeypatch.setattr(mod, "evaluate_latest_bar_traced", lambda *a, **k: (sig, _Trace()))
    monkeypatch.setattr(mod.exit_shadow, "record_from_loop", lambda *a, **k: None)
    for name in ("push_tick", "push_position_open", "push_position_close", "push_position_update", "broadcast",
                 "push_alert"):
        monkeypatch.setattr(mod.ws_manager, name, _noop)
    monkeypatch.setattr(loop, "_fetch_bars", _fetch)
    monkeypatch.setattr(loop, "_act", _act)
    monkeypatch.setattr(loop, "_close_at_session_end", _noop)
    monkeypatch.setattr(loop, "_shadow_evaluate", _noop)
    monkeypatch.setattr(loop, "_maybe_emit_census", _noop)
    monkeypatch.setattr(loop, "_news_context", _noop)
    monkeypatch.setattr(loop, "_record_abstention", _noop)
    monkeypatch.setattr(loop, "_has_position", _false)
    monkeypatch.setattr(loop, "_open_count", _zero)
    monkeypatch.setattr(loop.paper, "place_order", place_order)
    return loop, acts, sig


async def _tick(loop, *, swallow: bool = False):
    async with asyncio.timeout(20):
        try:
            await loop._tick_symbol("BTC/USD", "BTCUSDT")
        except Exception:  # noqa: BLE001 - the raised-verdict arm expects the loop to re-raise
            if not swallow:
                raise


def _capture_logs():
    from tests.unit.test_b442_kill_switch_at_send import _capture_logs as capture

    return capture()


def _filled(req, **extra):
    return {"status": "FILLED", "units": req.lot_size, "filled_units": req.lot_size, "fill": 100.0,
            "position_id": "order-1", "client_order_id": req.client_order_id, **extra}


# ---------------------------------------------------------------------------------------------------
# P — the canonical pair
# ---------------------------------------------------------------------------------------------------

def test_P1_EQUALITY_not_substring_and_P3_the_QUOTE_CURRENCY_is_kept():
    from app.services.broker.symbols import canonical_pair, same_pair

    assert same_pair("BTC/USD", "BTCUSD") and same_pair(" btc/usd ", "BTCUSD")
    for other in ("BTC/USDT", "BTCUSDT", "BTC/USDC", "XBTC/USD", "BTC/USDX"):
        assert not same_pair("BTC/USD", other), other
        assert not same_pair(other, "BTC/USD"), other
    assert canonical_pair("BTC/USDT") != canonical_pair("BTC/USD")


def test_P2_NONE_and_EMPTY_refuse():
    from app.services.broker.symbols import canonical_pair, same_pair

    for value in (None, "", "   ", 5):
        with pytest.raises(ValueError):
            canonical_pair(value)
    assert not same_pair(None, None) and not same_pair("", "") and not same_pair(None, "")


@pytest.mark.parametrize("venue_symbol,blocks", [("BTCUSD", True), ("BTC/USD", True), ("BTCUSDT", False)])
async def test_P4_8_has_position_sees_the_VENUE_spelling_and_only_the_same_pair(monkeypatch, venue_symbol, blocks):
    """`B449`'s stack: a `BTCUSD` venue position must block a `BTC/USD` entry; a `BTCUSDT` one must not."""
    from app.services.live.crypto_loop import LiveCryptoLoop

    loop = LiveCryptoLoop(broker_mode="paper")

    async def _positions():
        return [SimpleNamespace(pair=venue_symbol)]

    monkeypatch.setattr(loop.paper, "get_positions", _positions)
    assert await loop._has_position("BTC/USD") is blocks


class _ReconBroker:
    broker_name = "alpaca"
    is_simulation = False

    def __init__(self, positions):
        self._positions = positions

    async def get_account(self):
        from app.services.broker.base import Account

        return Account(account_id="A", broker="alpaca", balance=1000.0, equity=1000.0, currency="USD")

    async def get_positions(self):
        return self._positions

    async def get_orders(self, status=None):
        return []

    async def get_recent_trades(self):
        return []


def _venue_position(pair="BTCUSD", pid="asset-btc"):
    from tests.integration.test_broker_reconciliation import position

    return position(pair=pair, pid=pid)


def _open_trade(pair="BTC/USD", broker_id="order-entry-1"):
    from tests.integration.test_broker_reconciliation import our_trade

    trade = our_trade(pair=pair, broker_id=broker_id)
    trade.broker = "alpaca"
    return trade


async def test_P4_16_17_reconciler_does_NOT_close_an_OPEN_trade_the_venue_spells_differently(db_session):
    """`B461`: a miss here marks a live trade CLOSED (the ids never match: order id vs asset id)."""
    from app.db.enums import TradeStatus
    from app.models.trade import Trade
    from app.services.broker.reconciler import reconcile_positions

    db_session.add(_open_trade())
    await db_session.commit()
    lines, stop = _capture_logs()
    try:
        await reconcile_positions(_ReconBroker([_venue_position("BTCUSD")]), db_session, "system")
    finally:
        stop()
    trade = (await db_session.execute(select(Trade))).scalars().one()
    assert trade.status == TradeStatus.OPEN, "a live BTCUSD position did not keep its BTC/USD trade OPEN"
    assert not [l for l in lines if "not tracked in DB" in l["message"]], "the position was reported as external"


async def test_P4_18_reconciliation_raises_NO_false_CRITICAL_for_the_venue_spelling(db_session):
    from app.services.broker.reconciliation import reconcile_broker

    db_session.add(_open_trade())
    await db_session.commit()
    report = await reconcile_broker(_ReconBroker([_venue_position("BTCUSD")]), db_session, "system")
    kinds = [f.kind for f in report.findings]
    assert "untracked_position" not in kinds and "missing_position" not in kinds, kinds


# ---------------------------------------------------------------------------------------------------
# D — identity and the pre-send write
# ---------------------------------------------------------------------------------------------------

async def test_D1_D2_D4_D6_the_client_id_derives_from_the_decision_and_its_COMMITTED_row_exists_AT_THE_SEND(
        monkeypatch, file_bound):
    """`place_order`'s double reads the database from a SEPARATE connection and must find the SUBMITTING row whose id
    the client order id carries — whole, 32 hex."""
    from app.models.decision_record import OUTCOME_SUBMITTING, DecisionRecord

    seen: dict = {}

    async def _place(req):
        hexpart = req.client_order_id.removeprefix("tai-")
        async with file_bound() as other:   # a different connection: only a COMMITTED row is visible
            seen["row"] = (await other.execute(
                select(DecisionRecord).where(DecisionRecord.id == uuid.UUID(hexpart)))).scalars().first()
        seen["client_order_id"] = req.client_order_id
        return _filled(req)

    loop, _acts, sig = _driven_loop(monkeypatch, _place)
    await _tick(loop)
    cid = seen["client_order_id"]
    assert cid == f"tai-{sig.decision_id.hex}" and len(cid) == 36, cid
    assert seen["row"] is not None and seen["row"].outcome == OUTCOME_SUBMITTING, (
        "the pre-send row was not COMMITTED (or not written) by the time the order was sent")


@pytest.mark.parametrize("refusal", ["drift", "through_stop", "size", "observe"])
async def test_D3_the_hook_runs_AFTER_every_no_send_refusal(refusal):
    from app.services.execution.service import ExecMode, ExecutionService, Signal
    from app.services.execution.reference import ReferencePrice

    calls: list = []

    class _Broker:
        is_simulation = True

        async def get_account(self):
            return SimpleNamespace(equity=10_000.0)

        async def place_order(self, req):
            raise AssertionError("an order was sent on a refusal that sends nothing")

    mark = {"drift": 102.0, "through_stop": 98.5, "size": 100.0, "observe": 100.0}[refusal]
    sl = {"size": 100.0 - 1e12}.get(refusal, 99.0)
    service = ExecutionService(_Broker(), ExecMode.OBSERVE if refusal == "observe" else ExecMode.PAPER,
                               binance_mark=lambda _s: ReferencePrice(mark, "binance_mark", datetime.now(timezone.utc)))
    sig = Signal(symbol="BTC/USD", direction=DirectionType.LONG, entry=100.0, sl=sl, risk_pct=0.01)
    sig.decision_id = uuid.uuid4()

    async def _hook(req, sizing):
        calls.append(req)

    sig.before_send = _hook
    res = await service.execute(sig)
    assert calls == [], f"{refusal}: a SUBMITTING row would exist for a signal that sent nothing ({res})"
    assert res.get("status") in ("rejected", "observed"), res


async def test_D5_D7_a_FAILED_pre_send_write_sends_NOTHING_writes_no_row_never_halts_and_alerts_on_EDGES(
        monkeypatch, bound):
    from app.services.live import crypto_loop as mod

    sent: list = []
    alerts: list = []
    classified: list = []

    async def _place(req):
        sent.append(req)
        return _filled(req)

    loop, acts, sig = _driven_loop(monkeypatch, _place)
    real_classify = mod.classify_order_status
    monkeypatch.setattr(mod, "classify_order_status", lambda s: classified.append(s) or real_classify(s))
    fail = {"on": True}
    real_write = loop._write_submitting

    async def _write(*a, **k):
        if fail["on"]:
            raise RuntimeError("database is down")
        return await real_write(*a, **k)

    async def _alert(kind, **k):
        alerts.append((kind, k.get("recovered", False)))

    rejected: list = []

    async def _rejected(*a, **k):
        rejected.append(a)

    monkeypatch.setattr(loop, "_write_submitting", _write)
    monkeypatch.setattr(loop, "_raise_record_alert", _alert)
    monkeypatch.setattr(loop, "_record_rejected_signal", _rejected)
    lines, stop = _capture_logs()
    try:
        await _tick(loop)
        first_id = str(sig.decision_id)
        loop._last_eval.clear()
        await _tick(loop)
    finally:
        stop()
    assert sent == [], "an order was sent although its pre-send record failed"
    assert await _rows(bound) == [], "a row exists for an entry whose pre-send record failed"
    assert classified == [], "NOT_SENT reached classify_order_status"
    assert rejected == [], "NOT_SENT was routed to the rejection recorder (a second write against the failed DB)"
    assert loop.halt_reason is None, "a failed pre-send write halted the engine"
    errors = [l for l in lines if l["message"].startswith("live.presend_write_failed")]
    assert errors and errors[0].get("decision_id") == first_id, errors
    assert alerts == [("PRESEND_WRITE_FAILED", False)], f"two consecutive failures must raise ONE alert: {alerts}"

    fail["on"] = False
    monkeypatch.setattr(loop, "_record_rejected_signal", _rejected)
    loop._last_eval.clear()
    await _tick(loop)
    assert sent, "the entry was not sent once the write succeeded"
    assert alerts == [("PRESEND_WRITE_FAILED", False), ("PRESEND_WRITE_FAILED", True)], alerts


async def test_D8_a_SUBMITTING_row_is_NOT_the_open_decision(bound):
    from app.models.decision_record import COHORT_PAPER, OUTCOME_SUBMITTING, DecisionRecord
    from app.services.live.crypto_loop import LiveCryptoLoop

    async with bound() as db:
        db.add(DecisionRecord(symbol="BTC/USD", timeframe="1H", inputs_hash="a" * 16, code_path_hash="b" * 16,
                              abstained=False, outcome=OUTCOME_SUBMITTING, cohort=COHORT_PAPER,
                              sized_units=Decimal("0.01")))
        await db.commit()
    assert await LiveCryptoLoop(broker_mode="paper")._open_decision_id_from_db("BTC/USD") is None


# ---------------------------------------------------------------------------------------------------
# T — transitions
# ---------------------------------------------------------------------------------------------------

async def _row_with(maker, outcome):
    from app.models.decision_record import COHORT_PAPER, DecisionRecord

    rec = DecisionRecord(id=uuid.uuid4(), symbol="BTC/USD", timeframe="1H", inputs_hash="a" * 16,
                         code_path_hash="b" * 16, abstained=False, outcome=outcome, cohort=COHORT_PAPER)
    async with maker() as db:
        db.add(rec)
        await db.commit()
    return str(rec.id)


async def test_T1_T2_T3_COMPARE_AND_SET_never_rewrites_a_stored_outcome_and_says_so(bound):
    from app.models.decision_record import OUTCOME_OPEN, OUTCOME_REJECTED, OUTCOME_SUBMITTING, OUTCOME_WIN
    from app.services.live.crypto_loop import LiveCryptoLoop

    loop = LiveCryptoLoop(broker_mode="paper")
    for stored in (OUTCOME_OPEN, OUTCOME_WIN):
        dec = await _row_with(bound, stored)
        lines, stop = _capture_logs()
        try:
            done = await loop._transition_decision(dec, OUTCOME_REJECTED, {"rejection_code": "MIN_SIZE"})
        finally:
            stop()
        assert done is False
        row = [r for r in await _rows(bound) if str(r.id) == dec][0]
        assert row.outcome == stored, f"a stored {stored} was rewritten to {row.outcome}"
        assert [l for l in lines if l["message"].startswith("live.decision_transition_refused")
                and l.get("current") == stored], lines
    dec = await _row_with(bound, OUTCOME_SUBMITTING)
    assert await loop._transition_decision(dec, OUTCOME_REJECTED, {"rejection_code": "MIN_SIZE"}) is True
    row = [r for r in await _rows(bound) if str(r.id) == dec][0]
    assert (row.outcome, row.rejection_code) == (OUTCOME_REJECTED, "MIN_SIZE")


def _raises_after_submitting(exc):
    async def _place(req):
        raise exc
    return _place


@pytest.mark.parametrize("verdict", ["filled", "unsized", "refused", "raised", "unresolved"])
async def test_T4_each_VERDICT_moves_the_ONE_pre_send_row_to_its_TARGET(monkeypatch, bound, verdict):
    from app.models import decision_record as dr
    from app.services.live import crypto_loop as mod

    async def _place(req):
        if verdict == "filled":
            return _filled(req, held_units=float(Decimal(str(req.lot_size)) * (1 - FEE)))
        if verdict == "unsized":
            return {"status": "PARTIALLY_FILLED", "units": req.lot_size, "filled_units": None,
                    "position_id": "order-1", "client_order_id": req.client_order_id}
        if verdict == "refused":
            return {"status": "REJECTED", "reason": "venue refused", "rejection_code": dr.REJECTION_MIN_SIZE}
        if verdict == "raised":
            raise RuntimeError("the adapter raised after the pre-send write")
        return {"status": "NEW", "units": req.lot_size, "position_id": "order-1"}

    loop, acts, sig = _driven_loop(monkeypatch, _place)
    await _tick(loop, swallow=verdict == "raised")
    rows = await _rows(bound)
    assert len(rows) == 1 and str(rows[0].id) == str(sig.decision_id), [(r.id, r.outcome) for r in rows]
    row = rows[0]
    if verdict == "filled":
        assert row.outcome == dr.OUTCOME_OPEN
        assert row.sized_units is not None
        expected_held = (Decimal(str(row.sizing_equity)) * Decimal("0.01") / Decimal(1)) * (1 - FEE)
        assert abs(Decimal(str(row.sized_units)) - expected_held) < Decimal("1e-6"), (
            f"OPEN carries {row.sized_units}, not the VENUE units {expected_held}")
        assert loop._open_decision.get("BTC/USD") == str(sig.decision_id)
    elif verdict == "unsized":
        assert row.outcome == dr.OUTCOME_UNSIZED_FILL and row.sized_units is None
        assert loop.halt_reason == mod.HALT_PARTIAL_UNSIZED
    elif verdict == "refused":
        assert (row.outcome, row.rejection_code) == (dr.OUTCOME_REJECTED, dr.REJECTION_MIN_SIZE)
    elif verdict == "raised":
        assert (row.outcome, row.rejection_code) == (dr.OUTCOME_REJECTED, dr.REJECTION_VENUE_RAISED)
    else:
        assert row.outcome == dr.OUTCOME_SUBMITTING, "an unresolved order's record was moved (an order may exist)"
        assert loop.halt_reason == mod.HALT_ORDER_UNRESOLVED
        assert any(str(sig.decision_id) in text for kind, text in acts if kind == "halt"), acts


async def test_T6_a_transition_that_RAISES_after_a_fill_keeps_the_position_BOOKED_refuses_entries_and_RETRIES(
        monkeypatch, bound):
    from app.models import decision_record as dr

    loop, _acts, sig = _driven_loop(monkeypatch, None)
    real_place = type(loop.paper).place_order.__get__(loop.paper)
    monkeypatch.setattr(loop.paper, "place_order", real_place)   # the simulator OPENS the position (its stop is live)
    real = loop._transition_decision
    alerts: list = []
    fail = {"n": 1}

    async def _flaky(*a, **k):
        if fail["n"]:
            fail["n"] -= 1
            raise RuntimeError("database went away during the transition")
        return await real(*a, **k)

    async def _alert(kind, **k):
        alerts.append((kind, k.get("recovered", False)))

    monkeypatch.setattr(loop, "_transition_decision", _flaky)
    monkeypatch.setattr(loop, "_raise_record_alert", _alert)
    await _tick(loop)
    dec = str(sig.decision_id)
    assert loop.paper._positions, "the position is not held — the stop only exists on a held position"
    assert loop._book[dec]["record_pending"][0] == dr.OUTCOME_OPEN
    block = await loop._entry_block_reason("ETH/USD")
    assert block is not None and "decision record" in str(block), f"entries were not refused while pending: {block}"
    assert alerts == [("TRANSITION_WRITE_FAILED", False)], alerts
    assert (await _rows(bound))[0].outcome == dr.OUTCOME_SUBMITTING

    await loop._retry_pending_records()
    assert (await _rows(bound))[0].outcome == dr.OUTCOME_OPEN
    assert loop._book[dec]["record_pending"] is None and loop._open_decision.get("BTC/USD") == dec
    assert await loop._entry_block_reason("ETH/USD") is None
    assert alerts[-1] == ("TRANSITION_WRITE_FAILED", True)


async def test_T6b_a_write_that_COMMITTED_then_raised_is_cleared_by_the_retry_with_NO_second_error(monkeypatch, bound):
    from app.models import decision_record as dr

    loop, _acts, sig = _driven_loop(monkeypatch, None)
    monkeypatch.setattr(loop.paper, "place_order", type(loop.paper).place_order.__get__(loop.paper))
    real = loop._transition_decision
    once = {"n": 1}

    async def _commits_then_raises(*a, **k):
        done = await real(*a, **k)
        if once["n"]:
            once["n"] -= 1
            raise RuntimeError("the connection dropped after COMMIT")
        return done

    async def _alert(kind, **k):
        return None

    monkeypatch.setattr(loop, "_transition_decision", _commits_then_raises)
    monkeypatch.setattr(loop, "_raise_record_alert", _alert)
    await _tick(loop)
    assert (await _rows(bound))[0].outcome == dr.OUTCOME_OPEN
    lines, stop = _capture_logs()
    try:
        await loop._retry_pending_records()
    finally:
        stop()
    assert loop._book[str(sig.decision_id)]["record_pending"] is None
    assert not [l for l in lines if "transition_refused" in l["message"] or "was not SUBMITTING" in l["message"]], (
        [l["message"] for l in lines])


async def test_M6_the_simulators_ABANDONMENT_includes_a_stranded_SUBMITTING_row(bound):
    from app.models import decision_record as dr
    from app.services.live.crypto_loop import LiveCryptoLoop

    dec = await _row_with(bound, dr.OUTCOME_SUBMITTING)
    assert await LiveCryptoLoop(broker_mode="paper").reconcile_abandoned_decisions() == 1
    row = [r for r in await _rows(bound) if str(r.id) == dec][0]
    assert row.outcome == dr.OUTCOME_ABANDONED and "being submitted" in " ".join(row.reasons or [])


# ---------------------------------------------------------------------------------------------------
# R — the reference price
# ---------------------------------------------------------------------------------------------------

def _now():
    return datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)


def test_R1_BINANCE_first_and_R4_the_source_is_named():
    from app.services.execution.reference import ReferencePrice, VenueQuote, choose_reference

    got = choose_reference(ReferencePrice(100.0, "x", _now()), VenueQuote(90.0, 91.0, _now()), now=_now())
    assert (got.price, got.source) == (100.0, "binance_mark")


@pytest.mark.parametrize("age_s,used", [(110, True), (120, True), (130, False), (600, False)])
def test_R2_the_quote_is_aged_by_its_OWN_timestamp_against_120s(age_s, used):
    from app.services.execution.reference import VenueQuote, choose_reference

    got = choose_reference(None, VenueQuote(99.0, 101.0, _now() - timedelta(seconds=age_s)), now=_now())
    assert (got is not None) is used, (age_s, got)
    if used:
        assert got.source == "alpaca_quote_mid" and got.at == _now() - timedelta(seconds=age_s)


def test_R3_the_MID_not_a_side():
    from app.services.execution.reference import VenueQuote, choose_reference

    got = choose_reference(None, VenueQuote(90.0, 110.0, _now()), now=_now())
    assert got.price == 100.0


@pytest.mark.parametrize("case", ["neither", "stale_mark_no_quote", "zero_mark"])
async def test_R5_NEITHER_usable_is_NO_REFERENCE_PRICE_never_zero_never_an_old_mark(case):
    from app.models.decision_record import REJECTION_NO_REFERENCE_PRICE
    from app.services.execution.reference import ReferencePrice
    from app.services.execution.service import ExecMode, ExecutionService, Signal

    class _Venue:
        is_simulation = True

        async def get_account(self):
            return SimpleNamespace(equity=10_000.0)

        async def reference_quote(self, symbol):
            return None

        async def reference_price(self, symbol):
            raise AssertionError("a venue that declares a quote must not fall back to reference_price")

        async def place_order(self, req):
            raise AssertionError("sized without a reference price")

    mark = {"neither": None,
            "stale_mark_no_quote": ReferencePrice(100.0, "binance_mark", datetime.now(timezone.utc) - timedelta(minutes=5)),
            "zero_mark": ReferencePrice(0.0, "binance_mark", datetime.now(timezone.utc))}[case]
    service = ExecutionService(_Venue(), ExecMode.PAPER, binance_mark=lambda _s: mark)
    res = await service.execute(Signal(symbol="BTC/USD", direction=DirectionType.LONG, entry=100.0, sl=99.0))
    assert res.get("rejection_code") == REJECTION_NO_REFERENCE_PRICE, res


async def test_R4_the_executed_result_NAMES_its_reference_source():
    from app.services.execution.reference import ReferencePrice
    from app.services.execution.service import ExecMode, ExecutionService, Signal

    class _Sim:
        is_simulation = True

        async def get_account(self):
            return SimpleNamespace(equity=10_000.0)

        async def place_order(self, req):
            return {"status": "FILLED", "units": req.lot_size, "fill": 100.0}

    service = ExecutionService(_Sim(), ExecMode.PAPER,
                               binance_mark=lambda _s: ReferencePrice(100.0, "binance_mark", datetime.now(timezone.utc)))
    res = await service.execute(Signal(symbol="BTC/USD", direction=DirectionType.LONG, entry=100.0, sl=99.0))
    assert res["reference_source"] == "binance_mark" and res["reference_at"], res


def test_R6a_the_DATA_client_has_its_OWN_timeout_mount_and_429_only_retries():
    from app.services.broker.alpaca import build_crypto_data_client, build_trading_client

    data = build_crypto_data_client("PKFAKE", "s")
    trading = build_trading_client("PKFAKE", "s", paper=True)
    assert data._retry_codes == [429]
    for scheme in ("https://", "http://"):
        assert type(data._session.adapters[scheme]).__name__ == "_AlpacaTimeoutAdapter", scheme
    assert data._session is not trading._session


async def test_R6b_a_HELD_trading_call_does_NOT_delay_the_quote():
    """E-4's shape: the quote runs on its own worker, not behind the trading account's single thread."""
    import threading

    from tests.unit.test_b437_account_executor import GATE_S, _Traced, _hold_worker
    from tests.unit.test_b442_kill_switch_at_send import _alpaca

    book = _Traced()
    adapter, _ = _alpaca(book)

    class _Data:
        def get_crypto_latest_quote(self, request):
            return {"BTC/USD": SimpleNamespace(bid_price=99.0, ask_price=101.0,
                                               timestamp=datetime.now(timezone.utc))}

    adapter._data_client = _Data()
    release = threading.Event()
    held = asyncio.create_task(_hold_worker(adapter, release, "a held trading read"))
    try:
        await asyncio.sleep(0.05)
        quote = await asyncio.wait_for(adapter.reference_quote("BTC/USD"), 2.0)
    finally:
        release.set()
    await asyncio.wait_for(held, GATE_S)
    assert quote is not None and quote.bid == 99.0 and quote.ask == 101.0


# ---------------------------------------------------------------------------------------------------
# S — the $11 minimum
# ---------------------------------------------------------------------------------------------------

def _min_service(equity: float, mark: float):
    from app.services.execution.reference import ReferencePrice
    from app.services.execution.service import ExecMode, ExecutionService

    sent: list = []

    class _Venue:
        is_simulation = True
        min_entry_notional_usd = 11.0

        async def get_account(self):
            return SimpleNamespace(equity=equity)

        async def place_order(self, req):
            sent.append(req)
            return {"status": "FILLED", "units": req.lot_size, "fill": mark}

    service = ExecutionService(_Venue(), ExecMode.PAPER,
                               binance_mark=lambda _s: ReferencePrice(mark, "binance_mark", datetime.now(timezone.utc)))
    return service, sent


@pytest.mark.parametrize("notional,refused", [(10.50, True), (10.99, True), (11.00, False), (11.50, False)])
async def test_S1_S4_the_minimum_is_ELEVEN_dollars_and_refuses_as_MIN_SIZE(notional, refused):
    from app.models.decision_record import REJECTION_MIN_SIZE
    from app.services.execution.service import Signal

    # units = equity x 1% / (mark - sl); with sl = mark - 1, units = equity / 100 and notional = units x 100 = equity
    service, sent = _min_service(equity=notional, mark=100.0)
    res = await service.execute(Signal(symbol="BTC/USD", direction=DirectionType.LONG, entry=100.0, sl=99.0))
    assert bool(sent) is not refused, (notional, res)
    if refused:
        assert res.get("rejection_code") == REJECTION_MIN_SIZE and "11.00" in res.get("reason", ""), res


async def test_S2_priced_by_the_REFERENCE_price_not_the_signal_entry():
    """Reference 98, signal entry 100, stop 90: 0.1115 units is $10.93 at the reference (refused) and $11.15 at the
    entry (a mutant pricing by the entry would send it)."""
    from app.services.execution.service import Signal

    service, sent = _min_service(equity=89.2, mark=98.0)
    res = await service.execute(Signal(symbol="BTC/USD", direction=DirectionType.LONG, entry=100.0, sl=90.0))
    assert sent == [] and res.get("rejection_code") == "MIN_SIZE", res


# ---------------------------------------------------------------------------------------------------
# Q — opened units as a position delta; B — fixed-point quantities
# ---------------------------------------------------------------------------------------------------

class _QtyVenue:
    """A synchronous `TradingClient` double whose POSITION the fills move: an entry order fills on its first re-read and
    adds `filled x (1 - fee) + skew` to the held quantity (the fee in kind, probe rounds 4/5). `get_open_position` 404s
    for the slash form, as the venue does (`B449`)."""

    def __init__(self, *, held=Decimal(0), skew=Decimal(0), positions_raise=False, api_key=None, min_order_size=1e-9,
                 fill_on_read=1):
        self.fill_on_read = fill_on_read
        self._api_key = api_key or f"PK-Q-{uuid.uuid4().hex}"
        self.held, self.skew, self.positions_raise, self.min_order_size = held, skew, positions_raise, min_order_size
        self.calls: list[tuple] = []
        self.orders: dict[str, dict] = {}
        self.enumerations = 0

    def get_asset(self, symbol):
        from tests.unit.test_t0140_order_body import _asset

        return _asset(symbol, min_order_size=self.min_order_size)

    def submit_order(self, order_data):
        from tests.unit.test_b442_kill_switch_at_send import _sdk_order

        self.calls.append(("submit_order", order_data.qty))
        oid = uuid.uuid4()
        self.orders[str(oid)] = {"symbol": order_data.symbol, "qty": Decimal(repr(order_data.qty)), "filled": False,
                                 "reads": 0}
        return _sdk_order(oid, order_data.symbol, "accepted", "0")

    def get_order_by_id(self, order_id, filter=None):
        from tests.unit.test_b442_kill_switch_at_send import _sdk_order

        o = self.orders[str(order_id)]
        o["reads"] += 1
        if not o["filled"] and o["reads"] < self.fill_on_read:
            return _sdk_order(uuid.UUID(str(order_id)), o["symbol"], "accepted", "0")
        if not o["filled"]:
            o["filled"] = True
            self.held += o["qty"] * (1 - FEE) + self.skew
        order = _sdk_order(uuid.UUID(str(order_id)), o["symbol"], "filled", str(o["qty"]))
        object.__setattr__(order, "filled_qty", str(o["qty"]))
        return order

    def get_all_positions(self):
        from tests.unit.test_t0136_alpaca_adapter import _Position

        self.enumerations += 1
        if self.positions_raise:
            raise TimeoutError("position listing timed out")
        return [_Position(symbol="BTCUSD", qty=str(self.held))] if self.held > 0 else []

    def get_open_position(self, symbol):
        raise RuntimeError(f"404 position does not exist: {symbol}")

    def get_order_by_client_id(self, client_id):
        raise RuntimeError("not scripted")


def _q_adapter(venue, **kw):
    from tests.unit.test_b442_kill_switch_at_send import _alpaca

    return _alpaca(venue, **kw)


def _q_req(lot=0.01, cid=None):
    return OrderRequest(pair="BTC/USD", direction=DirectionType.LONG, order_type=OrderType.MARKET, lot_size=lot,
                        client_order_id=cid or f"tai-{uuid.uuid4().hex}")


async def test_Q1_Q5_Q8_opened_units_are_the_POSITION_DELTA_with_the_FEE_recorded():
    venue = _QtyVenue()
    adapter, _clock = _q_adapter(venue)
    async with asyncio.timeout(10):
        res = await adapter.place_order(_q_req(0.01))
    expected = Decimal("0.01") * (1 - FEE)
    assert res["held_units"] == float(expected), res
    assert Decimal(res["units_check"]["fee"]) == Decimal("0.01") - expected, res["units_check"]
    assert abs(res["buy_fee_units"] - float(Decimal("0.01") - expected)) < 1e-15, res
    assert res["units_check"]["within"] is True and res["units_check"]["filled"] == "0.01"


async def test_Q2_the_BEFORE_read_precedes_the_send_so_an_EXISTING_position_is_not_this_fill():
    venue = _QtyVenue(held=Decimal("0.5"))
    adapter, _clock = _q_adapter(venue)
    async with asyncio.timeout(10):
        res = await adapter.place_order(_q_req(0.01))
    assert res["held_units"] == float(Decimal("0.01") * (1 - FEE)) and res["units_check"]["held_before"] == "0.5", res


@pytest.mark.parametrize("skew,within", [(Decimal("1.5e-9"), True), (Decimal("-1.5e-9"), True),
                                         (Decimal("5e-9"), False), (Decimal("-5e-9"), False)])
async def test_Q3_the_WINDOW_is_2e_9_in_both_directions(skew, within):
    venue = _QtyVenue(skew=skew)
    adapter, _clock = _q_adapter(venue)
    async with asyncio.timeout(10):
        res = await adapter.place_order(_q_req(0.01))
    assert res["units_check"]["within"] is within, res["units_check"]


async def test_Q4_a_DISAGREEMENT_halts_with_BOTH_numbers(monkeypatch, bound):
    from app.models import decision_record as dr
    from app.services.live import crypto_loop as mod

    async def _place(req):
        return _filled(req, held_units=0.009, units_check={
            "filled": "0.01", "held": "0.009", "expected_held": "0.009975", "disagreement": "0.000975",
            "window": "2E-9", "within": False})

    loop, acts, sig = _driven_loop(monkeypatch, _place)
    await _tick(loop)
    assert loop.halt_reason == mod.HALT_UNITS_DISAGREE
    row = (await _rows(bound))[0]
    assert row.outcome == dr.OUTCOME_UNSIZED_FILL
    assert "0.009" in row.rejection_reason and "0.009975" in row.rejection_reason, row.rejection_reason


async def test_Q6_a_FAILED_before_read_sends_NOTHING_and_FLAT_is_zero():
    from app.core.exceptions import BrokerError

    failing = _QtyVenue(positions_raise=True)
    adapter, _clock = _q_adapter(failing)
    async with asyncio.timeout(10):
        with pytest.raises(BrokerError):
            await adapter.place_order(_q_req(0.01))
    assert not [c for c in failing.calls if c[0] == "submit_order"], "an unknown BEFORE was read as 0 and sent"

    flat = _QtyVenue()
    adapter, _clock = _q_adapter(flat)
    async with asyncio.timeout(10):
        res = await adapter.place_order(_q_req(0.01))
    assert res["units_check"]["held_before"] == "0" and [c for c in flat.calls if c[0] == "submit_order"]


async def test_Q7_the_BEFORE_read_is_UNDER_the_account_lock_another_adapters_fill_is_not_counted():
    """Two adapters, one account. B's entry parks mid-resolution HOLDING the lock (its fill not yet visible); A starts;
    B is released and fills. Under the lock, A's BEFORE is read after B's fill, so A's delta is A's alone."""
    from tests.unit.test_b442_kill_switch_at_send import _bounded_event, _until

    venue = _QtyVenue(fill_on_read=2)   # B's order fills on its SECOND read, so its resolver sleeps (and parks) between
    gate = _bounded_event()
    gated: set = set()
    adapter_b, _ = _q_adapter(venue, gated=gated, gate=gate)
    adapter_a, _ = _q_adapter(venue)
    async with asyncio.timeout(15):
        entry_b = asyncio.create_task(adapter_b.place_order(_q_req(0.02)))
        gated.add(entry_b)
        await _until(lambda: entry_b in adapter_b.parked, "B parked mid-resolution, holding the lock")
        entry_a = asyncio.create_task(adapter_a.place_order(_q_req(0.01)))
        await asyncio.sleep(0.2)
        gate.set()
        res_b, res_a = await entry_b, await entry_a
    assert res_a["units_check"]["within"] is True, (
        f"A's delta included B's fill: {res_a['units_check']} — its BEFORE was read outside the account lock")
    assert res_b["units_check"]["within"] is True


def test_B1_NO_EXPONENT_below_1e_6_and_B2_quantised_DOWN():
    from app.services.broker.alpaca import quantise_quantity_down, venue_quantity_text

    assert venue_quantity_text(Decimal("4.88E-7")) == "0.000000488"
    assert venue_quantity_text(Decimal("1E-7")) == "0.0000001"
    assert quantise_quantity_down(Decimal("0.0001947075")) == Decimal("0.000194707")
    assert quantise_quantity_down(0.0001 * 0.7) == Decimal("0.00007")
    with pytest.raises(ValueError):
        venue_quantity_text(Decimal("NaN"))


@pytest.mark.parametrize("lot", [4.88e-07, 1e-07, 5.8413e-05, 0.0001947075])
async def test_B3_the_ENTRY_quantity_reaches_the_SDK_as_the_quantised_value_EXACTLY(lot):
    """**Measured: `MarketOrderRequest.qty` is typed `float` in alpaca-py**, so whatever text the adapter passes, the SDK
    holds a float and the JSON body carries a NUMBER (`4.88e-07`). "No exponent in the body" cannot be asserted at this
    site; what can: the number is exactly the quantity quantised DOWN to the 1e-9 grid (B-2), never more than asked, with
    no float arithmetic on the way (`0.0001947075` sends `0.000194707`)."""
    from app.services.broker.alpaca import quantise_quantity_down

    venue = _QtyVenue()
    adapter, _clock = _q_adapter(venue)
    async with asyncio.timeout(10):
        await adapter.place_order(_q_req(lot))
    sent = [qty for name, qty in venue.calls if name == "submit_order"]
    assert sent and Decimal(repr(sent[0])) == quantise_quantity_down(lot), (sent, quantise_quantity_down(lot))


async def test_T6c_the_pending_retry_runs_at_the_TOP_of_every_pass_before_any_symbol():
    """G-6's retry lives in `_loop`, ahead of the symbols; T6 calls it directly, so this pins where it is called."""
    from app.services.live.crypto_loop import LiveCryptoLoop

    loop = LiveCryptoLoop(broker_mode="paper")
    order: list[str] = []

    async def _retry():
        order.append("retry")

    async def _symbol(pair, bsym):
        order.append(f"tick {pair}")
        loop._running = False

    async def _noop(*a, **k):
        return None

    loop._retry_pending_records = _retry
    loop._tick_symbol = _symbol
    loop._push_state = _noop
    loop.symbols = {"BTC/USD": "BTCUSDT"}
    loop.poll_interval = 0
    loop._running = True
    async with asyncio.timeout(5):
        await loop._loop()
    assert order[:2] == ["retry", "tick BTC/USD"], order


async def test_S1b_the_ALPACA_adapter_declares_ELEVEN_and_an_entry_under_it_is_never_submitted():
    """The minimum is the ADAPTER's declared value, through the real service: $10.50 at the reference price is refused
    before the pre-send write, and nothing reaches `submit_order`."""
    from app.models.decision_record import REJECTION_MIN_SIZE
    from app.services.execution.reference import ReferencePrice
    from app.services.execution.service import ExecMode, ExecutionService, Signal

    venue = _QtyVenue()
    adapter, _clock = _q_adapter(venue)

    async def _account():
        return SimpleNamespace(equity=10.50)   # units = equity / 100 at a 1-point stop, so notional = $10.50

    adapter.get_account = _account
    service = ExecutionService(adapter, ExecMode.PAPER,
                               binance_mark=lambda _s: ReferencePrice(100.0, "binance_mark", datetime.now(timezone.utc)))
    wrote: list = []

    async def _hook(req, sizing):
        wrote.append(req)

    sig = Signal(symbol="BTC/USD", direction=DirectionType.LONG, entry=100.0, sl=99.0)
    sig.decision_id, sig.before_send = uuid.uuid4(), _hook
    async with asyncio.timeout(10):
        res = await service.execute(sig)
    assert res.get("rejection_code") == REJECTION_MIN_SIZE, res
    assert wrote == [] and not [c for c in venue.calls if c[0] == "submit_order"], (wrote, venue.calls)
