"""Candle OHLCV endpoint for chart rendering — backed by real Binance data.

On a cache miss (no/insufficient rows in the DB) we backfill the requested
crypto pair from Binance, upsert into the ``candles`` table, and serve. No
synthetic data — the chart always shows real prices.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.deps import CurrentUser, DBSession
from app.core.logging import logger
from app.models.candle import Candle
from app.services.market_data.sources.binance import BinanceSource

router = APIRouter(prefix="/candles", tags=["candles"])

_TF_MINUTES: dict[str, int] = {
    "1m": 1, "5m": 5, "15m": 15, "30m": 30,
    "1H": 60, "4H": 240, "D": 1440, "W": 10080,
}

_binance = BinanceSource()


def _to_binance_symbol(pair: str) -> str:
    """'BTC/USD' | 'ETH/USDT' | 'SOL' -> Binance USDT pair ('BTCUSDT')."""
    p = pair.upper().replace("/", "").replace("-", "").replace("_", "")
    for q in ("USDT", "USDC", "USD"):
        if p.endswith(q):
            p = p[: -len(q)]
            break
    return f"{p}USDT"


def _serialize(time, o, h, low, c, v) -> dict:
    return {
        "time": time.isoformat() if hasattr(time, "isoformat") else time,
        "open": float(o), "high": float(h), "low": float(low),
        "close": float(c), "volume": float(v),
    }


async def _backfill_from_binance(
    db: DBSession, user_id: str, pair: str, timeframe: str, count: int
) -> list[dict]:
    """Fetch the latest *count* real bars from Binance, persist, and return them."""
    tfm = _TF_MINUTES.get(timeframe, 60)
    end = datetime.now(tz=timezone.utc)
    start = end - timedelta(minutes=tfm * (count + 5))
    symbol = _to_binance_symbol(pair)
    try:
        df = await asyncio.to_thread(_binance.fetch_ohlcv, symbol, timeframe, start, end)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Binance candle backfill failed", pair=pair, error=str(exc))
        return []

    out = [
        _serialize(ts, r.open, r.high, r.low, r.close, r.volume)
        for ts, r in df.iterrows()
    ][-count:]

    # Best-effort persist (don't fail the request if the DB write errors)
    try:
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
        if values:
            await db.execute(pg_insert(Candle).values(values).on_conflict_do_nothing())
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Candle persist failed (serving live data anyway)", error=str(exc))

    return out


@router.get("", response_model=list[dict])
async def get_candles(
    db: DBSession,
    user_id: CurrentUser,
    pair: str = Query(..., description="Crypto pair e.g. BTC/USD"),
    timeframe: str = Query(default="1H"),
    limit: int = Query(default=500, ge=1, le=2000),
) -> list[dict]:
    """Return OHLCV candles (oldest → newest) from the DB, backfilling from Binance."""
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
    candles = list((await db.execute(stmt)).scalars().all())

    if candles and len(candles) >= limit // 2:
        candles.sort(key=lambda c: c.time)
        return [_serialize(c.time, c.open, c.high, c.low, c.close, c.volume) for c in candles]

    return await _backfill_from_binance(db, user_id, pair, timeframe, limit)
