"""Candle OHLCV endpoint for chart rendering — backed by real Binance data.

Rows are cached in the ``candles`` table and refreshed from Binance when they go
stale. No synthetic data — the chart always shows real prices.

WHY THIS FILE HAS A FRESHNESS RULE AT ALL (was KNOWN_ISSUES A8)
The cache used to be validated by COUNTING rows:

    if candles and len(candles) >= limit // 2:   # 505 >= 250 — true forever
        return ...

A count is not a freshness test. The table was filled once on 2026-06-27 with
505 rows per series, the condition was true on every request afterwards, and the
backfill underneath it never ran again. The chart served 39-day-old bars as the
current market for over a month, and did it while the price line, the "now"
cursor and the trade markers on the same canvas stayed live — so a 27 July trade
was drawn a month to the right of the last candle. A chart that is wholly stale
is obvious at a glance; one that is stale in the candles and live in the overlays
reads as real. That is the failure this module now exists to prevent.

The lesson generalises: **a cache validated by size will serve one snapshot
forever.** Every cache-hit test here is a test about time.

ONLY CLOSED BARS ARE STORED
Binance returns the in-progress bar for the current interval, and its high, low,
close and volume all still change. Writing it to a table keyed by open time
records a half-formed bar as though it were settled — and with the old
`on_conflict_do_nothing`, that half-formed bar would have been frozen there
permanently. The forming bar is therefore dropped before persisting, and the
conflict clause updates rather than ignores, so a bar written by an older version
of this code gets corrected on the next refresh.

The live edge of the chart is the WebSocket price line. It does not need to come
from here, and it should not: this table is for settled data.

STALE DATA IS NEVER SERVED SILENTLY
If the refresh fails and all we hold is stale, the endpoint returns 503 rather
than the old bars. Serving them is exactly the defect above, and an empty list
would render as "no data" — a lie of a different shape (KNOWN_ISSUES E3). An
error is the only honest answer, and the frontend already renders it as one.
"""
from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.api.deps import CurrentUser, DBSession
from app.core.logging import logger
from app.models.candle import Candle
from app.services.market_data.sources.binance import BinanceSource

router = APIRouter(prefix="/candles", tags=["candles"])

_TF_MINUTES: dict[str, int] = {
    "1m": 1, "5m": 5, "15m": 15, "30m": 30,
    "1H": 60, "4H": 240, "D": 1440, "W": 10080,
}

#: How many bar intervals a cached series may fall behind before it is refreshed.
#:
#: One interval is unavoidable and not staleness: the newest CLOSED bar of a 1H
#: series is always between 1 and 2 hours old, because the current hour has not
#: finished. Two intervals allows that plus a little slack. Anything larger is
#: the chart quietly drifting; anything smaller re-fetches on every request in
#: the last seconds of each bar for no gain.
_STALE_AFTER_BARS = 2

_binance = BinanceSource()


def _to_binance_symbol(pair: str) -> str:
    """'BTC/USD' | 'ETH/USDT' | 'SOL' -> Binance USDT pair ('BTCUSDT')."""
    p = pair.upper().replace("/", "").replace("-", "").replace("_", "")
    for q in ("USDT", "USDC", "USD"):
        if p.endswith(q):
            p = p[: -len(q)]
            break
    return f"{p}USDT"


def _tf_delta(timeframe: str) -> timedelta:
    return timedelta(minutes=_TF_MINUTES.get(timeframe, 60))


def _is_stale(newest: datetime, timeframe: str, now: datetime) -> bool:
    """Is a series whose newest CLOSED bar opened at *newest* out of date?

    Compared against the bar interval rather than a fixed number of minutes: two
    hours behind is fine on a daily chart and a fault on a 1m one, and a single
    constant cannot be right for both.
    """
    if newest.tzinfo is None:
        newest = newest.replace(tzinfo=timezone.utc)
    return (now - newest) > _tf_delta(timeframe) * _STALE_AFTER_BARS


def _serialize(time, o, h, low, c, v) -> dict:
    return {
        "time": time.isoformat() if hasattr(time, "isoformat") else time,
        "open": float(o), "high": float(h), "low": float(low),
        "close": float(c), "volume": float(v),
    }


def _drop_forming_bar(df, timeframe: str, now: datetime):
    """Remove the bar that has not finished yet, if the frame ends in one.

    Tested by arithmetic on the bar's own open time rather than by flooring the
    clock to an interval boundary. Flooring needs to know where each timeframe's
    boundaries fall, and weekly bars do not start where a naive epoch floor puts
    them — this form is exact for every timeframe without knowing any of that.
    """
    if len(df) == 0:
        return df
    last_open = df.index[-1].to_pydatetime()
    if last_open.tzinfo is None:
        last_open = last_open.replace(tzinfo=timezone.utc)
    if last_open + _tf_delta(timeframe) > now:
        return df.iloc[:-1]
    return df


async def _persist(db: DBSession, user_id: str, pair: str, timeframe: str, df) -> bool:
    """Upsert closed bars. Returns whether the write succeeded.

    `on_conflict_do_UPDATE`, not `do_nothing`. A bar already in the table may
    have been written by an older build while it was still forming; ignoring the
    conflict would leave that half-formed bar in place for good.
    """
    values = [
        {
            "user_id": user_id, "pair": pair, "timeframe": timeframe,
            "time": ts.to_pydatetime(),
            "open": Decimal(str(r.open)), "high": Decimal(str(r.high)),
            "low": Decimal(str(r.low)), "close": Decimal(str(r.close)),
            "volume": Decimal(str(r.volume)),
        }
        for ts, r in df.iterrows()
    ]
    if not values:
        return True

    # Dialect-aware so the suite can exercise this path. The alternative is to
    # mock the write in tests, which would mean the one assertion that matters —
    # that a refresh actually REPLACES the stale rows — is never really run.
    dialect = db.bind.dialect.name if db.bind is not None else "postgresql"
    insert = sqlite_insert if dialect == "sqlite" else pg_insert
    try:
        stmt = insert(Candle).values(values)
        await db.execute(
            stmt.on_conflict_do_update(
                index_elements=["user_id", "pair", "timeframe", "time"],
                set_={
                    "open": stmt.excluded.open, "high": stmt.excluded.high,
                    "low": stmt.excluded.low, "close": stmt.excluded.close,
                    "volume": stmt.excluded.volume,
                },
            )
        )
        await db.commit()
        return True
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        logger.warning("Candle persist failed (serving fetched data anyway)",
                       pair=pair, timeframe=timeframe, error=str(exc))
        return False


async def _fetch_closed_bars(pair: str, timeframe: str, start: datetime, now: datetime):
    """Fetch [start, now) from Binance and drop the bar still forming."""
    symbol = _to_binance_symbol(pair)
    try:
        df = await asyncio.to_thread(_binance.fetch_ohlcv, symbol, timeframe, start, now)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Binance candle fetch failed", pair=pair, error=str(exc))
        return None
    return _drop_forming_bar(df, timeframe, now)


def _contiguous_tail(rows: list[Candle], timeframe: str) -> list[Candle]:
    """Trim to the unbroken run of bars ending at the newest one.

    A refresh that covers only the window it serves can leave an older block
    stranded behind a hole — and this table has a second writer (`CandlePipeline`)
    that can stop and start, which makes holes possible independently of anything
    here. Either way, a chart drawn straight across a gap invents a move that
    never happened, joining two prices hours or weeks apart with one line.

    Safe as a plain interval test because every pair in this table is crypto and
    trades 24/7. A market with sessions would need a calendar, and this function
    would be wrong for it rather than merely imprecise.
    """
    tf = _tf_delta(timeframe)
    cut = 0
    for i in range(len(rows) - 1, 0, -1):
        prev, cur = rows[i - 1].time, rows[i].time
        if prev.tzinfo is None:
            prev = prev.replace(tzinfo=timezone.utc)
        if cur.tzinfo is None:
            cur = cur.replace(tzinfo=timezone.utc)
        if (cur - prev) > tf * 1.5:
            cut = i
            break
    return rows[cut:]


async def _read(db: DBSession, user_id: str, pair: str, timeframe: str, limit: int):
    stmt = (
        select(Candle)
        .where(
            Candle.user_id == user_id,
            Candle.pair == pair,
            Candle.timeframe == timeframe,
        )
        .order_by(Candle.time.desc())
        .limit(limit)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    rows.sort(key=lambda c: c.time)
    return _contiguous_tail(rows, timeframe)


@router.get("", response_model=list[dict])
async def get_candles(
    db: DBSession,
    user_id: CurrentUser,
    pair: str = Query(..., description="Crypto pair e.g. BTC/USD"),
    timeframe: str = Query(default="1H"),
    limit: int = Query(default=500, ge=1, le=2000),
) -> list[dict]:
    """Return closed OHLCV bars (oldest → newest), refreshing from Binance when stale."""
    now = datetime.now(tz=timezone.utc)
    tf = _tf_delta(timeframe)
    rows = await _read(db, user_id, pair, timeframe, limit)

    have_enough = len(rows) >= limit // 2
    fresh = bool(rows) and not _is_stale(rows[-1].time, timeframe, now)
    if rows and have_enough and fresh:
        return [_serialize(c.time, c.open, c.high, c.low, c.close, c.volume) for c in rows]

    # ---- refresh ---------------------------------------------------------
    # Fetch only the missing tail when there is one. A gap wider than the window
    # we serve is treated as no cache at all: re-pulling the whole window costs
    # the same as covering the gap, and everything older than the window is
    # outside anything this endpoint will ever return.
    if not rows or not have_enough:
        start = now - tf * (limit + 5)
    else:
        newest = rows[-1].time
        if newest.tzinfo is None:
            newest = newest.replace(tzinfo=timezone.utc)
        missing = math.ceil((now - newest) / tf)
        start = newest - tf if missing <= limit else now - tf * (limit + 5)

    df = await _fetch_closed_bars(pair, timeframe, start, now)

    if df is None or len(df) == 0:
        # Nothing new. Never fall back to the stale rows — that is the whole bug.
        raise HTTPException(
            status_code=503,
            detail=(
                f"Could not refresh {pair} {timeframe} candles from Binance. "
                "Showing nothing rather than out-of-date prices."
            ),
        )

    persisted = await _persist(db, user_id, pair, timeframe, df)
    if persisted:
        rows = await _read(db, user_id, pair, timeframe, limit)
        if rows and not _is_stale(rows[-1].time, timeframe, now):
            return [_serialize(c.time, c.open, c.high, c.low, c.close, c.volume) for c in rows]

    # The write failed, or read back stale anyway. The fetched frame is real,
    # current data — serve it rather than the cache we just declined to trust.
    return [
        _serialize(ts, r.open, r.high, r.low, r.close, r.volume)
        for ts, r in df.iterrows()
    ][-limit:]
