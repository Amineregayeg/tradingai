"""Abstract market-data source interface.

Keeps detection / backtest / live code agnostic to the underlying vendor.
Swap in a paid feed (TradingView export, Kaiko, Coinglass, …) by implementing
this protocol — strategy logic never changes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

import pandas as pd

# Canonical engine timeframes.
TIMEFRAMES: tuple[str, ...] = ("1m", "5m", "15m", "1H", "4H", "D", "W")

# Canonical OHLCV column order for every DataFrame returned by a source.
OHLCV_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume")


class MarketDataSource(ABC):
    """A source of historical (and optionally live) OHLCV bars."""

    #: short stable identifier used in cache filenames and logs
    name: str = "base"

    @abstractmethod
    def fetch_ohlcv(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> pd.DataFrame:
        """Return bars in ``[start, end)`` as a UTC-time-indexed DataFrame.

        Index: tz-aware UTC ``DatetimeIndex`` named ``time`` (ascending, unique).
        Columns: exactly :data:`OHLCV_COLUMNS` (floats).
        Empty range → empty DataFrame with the right columns.
        """
        raise NotImplementedError


def empty_ohlcv() -> pd.DataFrame:
    """An empty OHLCV frame with the canonical schema."""
    df = pd.DataFrame(columns=list(OHLCV_COLUMNS))
    df.index = pd.DatetimeIndex([], tz="UTC", name="time")
    return df
