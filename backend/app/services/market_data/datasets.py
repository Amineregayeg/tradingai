"""Backtest dataset loader with on-disk cache.

Pulls historical OHLCV via a ``MarketDataSource`` (Binance by default) and caches
each (source, symbol, timeframe, range) as CSV under ``data/backtest/`` so the
backtest harness (M6) runs offline and deterministically after a one-time fetch.
"""
from __future__ import annotations

import os
from datetime import datetime

import pandas as pd

from app.core.logging import logger
from app.services.market_data.sources.base import MarketDataSource
from app.services.market_data.sources.binance import BinanceSource

_DEFAULT_CACHE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "..",
    "data",
    "backtest",
)
CACHE_DIR = os.path.abspath(os.environ.get("BACKTEST_DATA_DIR", _DEFAULT_CACHE))


def _cache_path(source: str, symbol: str, timeframe: str, start: datetime, end: datetime) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    fname = f"{source}_{symbol.upper()}_{timeframe}_{start:%Y%m%d}_{end:%Y%m%d}.csv"
    return os.path.join(CACHE_DIR, fname)


def load_ohlcv(
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    source: MarketDataSource | None = None,
    refresh: bool = False,
) -> pd.DataFrame:
    """Load one symbol/timeframe over ``[start, end)``, using the disk cache."""
    source = source or BinanceSource()
    path = _cache_path(source.name, symbol, timeframe, start, end)
    if os.path.exists(path) and not refresh:
        df = pd.read_csv(path, parse_dates=["time"]).set_index("time")
        df.index = pd.DatetimeIndex(df.index, tz="UTC", name="time") if df.index.tz is None else df.index
        return df

    df = source.fetch_ohlcv(symbol, timeframe, start, end)
    if not df.empty:
        df.reset_index().to_csv(path, index=False)
    logger.info(
        f"dataset {symbol}/{timeframe} {start:%Y-%m-%d}..{end:%Y-%m-%d}: "
        f"{len(df)} bars -> {path}"
    )
    return df


def load_multi(
    symbols: list[str],
    timeframes: list[str],
    start: datetime,
    end: datetime,
    source: MarketDataSource | None = None,
    refresh: bool = False,
) -> dict[str, dict[str, pd.DataFrame]]:
    """Load a {symbol: {timeframe: DataFrame}} matrix for the backtest."""
    source = source or BinanceSource()
    out: dict[str, dict[str, pd.DataFrame]] = {}
    for sym in symbols:
        out[sym] = {}
        for tf in timeframes:
            out[sym][tf] = load_ohlcv(sym, tf, start, end, source=source, refresh=refresh)
    return out
