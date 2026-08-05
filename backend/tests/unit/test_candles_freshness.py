"""The chart's cache is validated by TIME, not by row count (KNOWN_ISSUES A8).

The defect these tests exist for: `/api/candles` decided its cached rows were
usable by counting them (`len(candles) >= limit // 2`). The table held 505 rows
per series, so the condition was true on every request from the day it was
filled, the Binance refresh underneath it never ran again, and the chart served
27-June bars as the current market for 39 days.

Nothing about that was visible from the response — the shape was right, the
prices were real, they were simply a month old. So each test below fixes a point
in time and asserts on WHICH bars come back, because that is the only place the
bug was ever observable.

The mutation that must fail: put `len(rows) >= limit // 2` back as the whole
cache-hit test and `test_a_full_but_stale_cache_is_refused` goes red.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from sqlalchemy import select

from app.api.routers import candles as mod
from app.models.candle import Candle

NOW = datetime(2026, 8, 5, 14, 30, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)
USER = "system"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def frame(start: datetime, count: int, *, step: timedelta = HOUR, base: float = 100.0):
    """A Binance-shaped OHLCV frame: UTC DatetimeIndex, one row per bar."""
    idx = pd.DatetimeIndex([start + step * i for i in range(count)], tz="UTC")
    return pd.DataFrame(
        {
            "open": [base + i for i in range(count)],
            "high": [base + i + 1 for i in range(count)],
            "low": [base + i - 1 for i in range(count)],
            "close": [base + i + 0.5 for i in range(count)],
            "volume": [10.0 + i for i in range(count)],
        },
        index=idx,
    )


async def seed(session, *, newest: datetime, count: int, pair="BTC/USD", tf="1H",
               close: float = 1.0) -> None:
    """Write `count` hourly bars ending at `newest`, oldest first."""
    session.add_all([
        Candle(
            user_id=USER, pair=pair, timeframe=tf,
            time=newest - HOUR * i,
            open=close, high=close, low=close, close=close, volume=1,
        )
        for i in range(count)
    ])
    await session.commit()


@pytest.fixture
def frozen(monkeypatch):
    """Pin `now` inside the router so staleness is arithmetic, not a race."""
    class _DT(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW
    monkeypatch.setattr(mod, "datetime", _DT)


@pytest.fixture
def binance(monkeypatch):
    """Record every fetch and return whatever the test queues up."""
    calls: list[dict] = []
    state: dict = {"result": frame(NOW - HOUR * 3, 3)}

    def fake_fetch(symbol, timeframe, start, end):
        calls.append({"symbol": symbol, "timeframe": timeframe, "start": start, "end": end})
        result = state["result"]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(mod._binance, "fetch_ohlcv", fake_fetch)
    return type("B", (), {"calls": calls, "state": state})()


# ---------------------------------------------------------------------------
# THE BUG
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_full_but_stale_cache_is_refused(client, db_session, frozen, binance):
    """505 rows ending 39 days ago — exactly production's state on 2026-08-05.

    The old code answered this from the cache because 505 >= 250. Row count says
    nothing about whether the rows describe today.
    """
    stale_newest = NOW - timedelta(days=39)
    await seed(db_session, newest=stale_newest, count=505, close=60000)
    binance.state["result"] = frame(NOW - HOUR * 10, 10, base=118000)

    resp = await client.get("/api/candles", params={"pair": "BTC/USD", "timeframe": "1H"})

    assert resp.status_code == 200
    assert binance.calls, "a 39-day-old cache was served without asking Binance"
    newest_returned = datetime.fromisoformat(resp.json()[-1]["time"])
    assert not mod._is_stale(newest_returned, "1H", NOW), (
        f"still serving {newest_returned.isoformat()} at {NOW.isoformat()}"
    )


@pytest.mark.asyncio
async def test_a_fresh_cache_is_served_without_calling_binance(client, db_session, frozen, binance):
    """The other half of the rule. A freshness test that never hits the cache is
    just an uncached endpoint wearing a cache's clothes."""
    await seed(db_session, newest=NOW - HOUR, count=500)

    resp = await client.get("/api/candles", params={"pair": "BTC/USD", "timeframe": "1H"})

    assert resp.status_code == 200
    assert binance.calls == [], "Binance was called for a cache that was up to date"
    assert len(resp.json()) == 500


@pytest.mark.asyncio
async def test_the_newest_closed_bar_is_not_itself_stale(client, db_session, frozen, binance):
    """At 14:30 the newest CLOSED 1H bar opened at 13:00 and is 1.5h old. If that
    counted as stale, every request would re-fetch forever and the cache would
    exist for nothing."""
    assert not mod._is_stale(NOW.replace(minute=0) - HOUR, "1H", NOW)
    assert mod._is_stale(NOW - HOUR * 3, "1H", NOW)


@pytest.mark.asyncio
async def test_staleness_is_measured_in_bars_not_minutes(client):
    """Two hours behind is a fault on a 1m chart and unremarkable on a daily one.
    A single minute count cannot be right for both."""
    two_hours_ago = NOW - timedelta(hours=2)
    assert mod._is_stale(two_hours_ago, "1m", NOW)
    assert not mod._is_stale(two_hours_ago, "D", NOW)


# ---------------------------------------------------------------------------
# What gets written
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_the_forming_bar_is_never_stored(client, db_session, frozen, binance):
    """Binance returns the current interval's bar, whose high/low/close are still
    moving. Storing it in a table keyed by open time records a half-formed bar as
    settled."""
    # 13:00 has closed; 14:00 is still forming at 14:30.
    binance.state["result"] = frame(NOW.replace(minute=0) - HOUR, 2)

    resp = await client.get("/api/candles", params={"pair": "BTC/USD", "timeframe": "1H"})
    assert resp.status_code == 200

    stored = (await db_session.execute(select(Candle.time))).scalars().all()
    forming = NOW.replace(minute=0)
    assert all(t.replace(tzinfo=timezone.utc) != forming for t in stored), (
        "the in-progress bar was persisted as if it were final"
    )
    assert stored, "nothing was written at all"


@pytest.mark.asyncio
async def test_a_bar_written_while_forming_is_corrected(client, db_session, frozen, binance):
    """`on_conflict_do_nothing` would leave a half-formed bar in the table for
    good — the refresh would fetch the finished bar and then discard it."""
    bar_open = NOW - HOUR * 2
    await seed(db_session, newest=bar_open, count=1, close=111.0)
    binance.state["result"] = frame(bar_open, 1, base=999.0)

    await client.get("/api/candles", params={"pair": "BTC/USD", "timeframe": "1H"})

    row = (await db_session.execute(
        select(Candle).where(Candle.time == bar_open)
    )).scalars().first()
    assert row is not None
    assert float(row.close) == pytest.approx(999.5), "the stale bar was kept on conflict"


@pytest.mark.asyncio
async def test_only_the_missing_tail_is_fetched(client, db_session, frozen, binance):
    """A three-hour gap should not re-pull five hundred bars. The window asked
    for is what makes this checkable — the response looks identical either way."""
    await seed(db_session, newest=NOW - HOUR * 5, count=500)

    await client.get("/api/candles", params={"pair": "BTC/USD", "timeframe": "1H"})

    assert len(binance.calls) == 1
    start = binance.calls[0]["start"]
    assert NOW - start < timedelta(hours=12), (
        f"asked for {(NOW - start).total_seconds() / 3600:.0f}h to cover a 5h gap"
    )


@pytest.mark.asyncio
async def test_a_gap_wider_than_the_window_pulls_the_whole_window(client, db_session, frozen, binance):
    """Production's actual case. Covering 39 days of 1H bars costs more than the
    500 the endpoint will ever return, and every bar in the middle is one nobody
    can see."""
    await seed(db_session, newest=NOW - timedelta(days=39), count=505)
    binance.state["result"] = frame(NOW - HOUR * 10, 10)

    await client.get("/api/candles", params={"pair": "BTC/USD", "timeframe": "1H"})

    start = binance.calls[0]["start"]
    span_h = (NOW - start).total_seconds() / 3600
    assert 500 <= span_h <= 520, f"fetched a {span_h / 24:.0f}-day window"


# ---------------------------------------------------------------------------
# Continuity
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_hole_in_the_table_is_never_drawn_across(client, db_session, frozen, binance):
    """A window-sized refresh leaves the block behind the gap stranded, and the
    pipeline that also writes here can stop and start. Joining the two sides with
    one line invents a move that never happened."""
    await seed(db_session, newest=NOW - timedelta(days=39), count=300, close=60000)
    await seed(db_session, newest=NOW - HOUR * 2, count=300, close=118000)

    resp = await client.get(
        "/api/candles", params={"pair": "BTC/USD", "timeframe": "1H", "limit": 600}
    )

    assert resp.status_code == 200
    # SQLite hands back naive datetimes where Postgres gives aware ones; the
    # comparison below is about spacing, not about which of the two we are on.
    times = [as_utc(datetime.fromisoformat(c["time"])) for c in resp.json()]
    gaps = [b - a for a, b in zip(times, times[1:]) if (b - a) > HOUR * 1.5]
    assert not gaps, f"served a series with a {gaps[0]} hole in it"
    assert all(t > NOW - timedelta(days=30) for t in times), "the stranded block came back"


@pytest.mark.asyncio
async def test_continuity_trimming_keeps_the_newest_side(client):
    """The run to keep is the one ending at the newest bar. Keeping the older,
    longer side would answer a request for current prices with old ones."""
    rows = [Candle(user_id=USER, pair="X", timeframe="1H", time=NOW - HOUR * i,
                   open=1, high=1, low=1, close=1, volume=1)
            for i in (400, 399, 398, 5, 4, 3)]
    rows.sort(key=lambda c: c.time)
    kept = mod._contiguous_tail(rows, "1H")
    assert len(kept) == 3
    assert kept[-1].time == NOW - HOUR * 3


# ---------------------------------------------------------------------------
# Failure
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_failed_refresh_errors_instead_of_serving_stale(client, db_session, frozen, binance):
    """The tempting fallback — "we couldn't refresh, show what we have" — is the
    original defect with an excuse attached."""
    await seed(db_session, newest=NOW - timedelta(days=39), count=505, close=60000)
    binance.state["result"] = RuntimeError("binance unreachable")

    resp = await client.get("/api/candles", params={"pair": "BTC/USD", "timeframe": "1H"})

    assert resp.status_code == 503
    assert "60000" not in resp.text, "the stale prices came back in the error body"


@pytest.mark.asyncio
async def test_an_empty_upstream_response_is_an_error_not_an_empty_chart(
    client, db_session, frozen, binance
):
    """An empty list renders as "no data" — a different lie about the same
    missing information (KNOWN_ISSUES E3)."""
    await seed(db_session, newest=NOW - timedelta(days=39), count=505)
    binance.state["result"] = frame(NOW, 0)

    resp = await client.get("/api/candles", params={"pair": "BTC/USD", "timeframe": "1H"})
    assert resp.status_code == 503
