"""TA indicators computed from a candles DataFrame using pandas-ta."""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd

from app.core.logging import logger

# Attempt to import pandas_ta; fall back to manual calculations if not available
try:
    import pandas_ta as ta  # type: ignore[import-untyped]

    _PTA_AVAILABLE = True
except ImportError:
    _PTA_AVAILABLE = False
    logger.warning("pandas_ta not installed; falling back to manual TA calculations.")

# Redis TTL per timeframe (seconds)
_TF_TTL: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1H": 3600,
    "4H": 14400,
    "D": 86400,
}


def _safe_val(series: pd.Series) -> float:
    """Return the last non-NaN value of *series*, or NaN if the series is empty / all NaN."""
    if series is None or len(series) == 0:
        return float("nan")
    last = series.iloc[-1]
    try:
        f = float(last)
        return f
    except (TypeError, ValueError):
        return float("nan")


def _ema_manual(series: pd.Series, period: int) -> pd.Series:
    """Compute EMA manually using pandas ewm."""
    return series.ewm(span=period, adjust=False).mean()


def _rsi_manual(close: pd.Series, period: int = 14) -> pd.Series:
    """Compute RSI manually."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _macd_manual(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return (macd_line, signal_line, histogram)."""
    ema_fast = _ema_manual(close, fast)
    ema_slow = _ema_manual(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema_manual(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def _atr_manual(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Compute ATR manually."""
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    tr = pd.concat(
        [
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(com=period - 1, min_periods=period).mean()


def _stoch_manual(
    df: pd.DataFrame,
    k_period: int = 14,
    d_period: int = 3,
    smooth_k: int = 3,
) -> tuple[pd.Series, pd.Series]:
    """Return (%K, %D) stochastic oscillator."""
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    low_min = low.rolling(k_period).min()
    high_max = high.rolling(k_period).max()
    raw_k = 100 * (close - low_min) / (high_max - low_min).replace(0, np.nan)
    k = raw_k.rolling(smooth_k).mean()
    d = k.rolling(d_period).mean()
    return k, d


class Indicators:
    """Compute TA indicators from an OHLCV DataFrame."""

    def compute_all(self, df: pd.DataFrame) -> dict[str, Any]:
        """Compute all TA indicators and return latest values.

        Args:
            df: DataFrame with columns [open, high, low, close, volume],
                sorted ascending.

        Returns:
            Dict with keys: rsi_14, ema_21, ema_50, ema_200, atr_14,
            macd_histogram, macd_signal, stoch_k, stoch_d, ema_stack.
        """
        close = df["close"].astype(float)

        if _PTA_AVAILABLE:
            return self._compute_with_pandas_ta(df, close)
        return self._compute_manual(df, close)

    def _compute_with_pandas_ta(
        self, df: pd.DataFrame, close: pd.Series
    ) -> dict[str, Any]:
        rsi_series = ta.rsi(close, length=14)
        ema21 = ta.ema(close, length=21)
        ema50 = ta.ema(close, length=50)
        ema200 = ta.ema(close, length=200)
        atr_series = ta.atr(df["high"].astype(float), df["low"].astype(float), close, length=14)

        macd_df = ta.macd(close, fast=12, slow=26, signal=9)
        if macd_df is not None and not macd_df.empty:
            macd_hist = _safe_val(macd_df.iloc[:, 2])  # histogram is 3rd column
            macd_sig = _safe_val(macd_df.iloc[:, 1])   # signal is 2nd column
        else:
            macd_hist = float("nan")
            macd_sig = float("nan")

        stoch_df = ta.stoch(
            df["high"].astype(float),
            df["low"].astype(float),
            close,
            k=14,
            d=3,
            smooth_k=3,
        )
        if stoch_df is not None and not stoch_df.empty:
            stoch_k = _safe_val(stoch_df.iloc[:, 0])
            stoch_d = _safe_val(stoch_df.iloc[:, 1])
        else:
            stoch_k = float("nan")
            stoch_d = float("nan")

        e21 = _safe_val(ema21)
        e50 = _safe_val(ema50)
        e200 = _safe_val(ema200)

        return {
            "rsi_14": _safe_val(rsi_series),
            "ema_21": e21,
            "ema_50": e50,
            "ema_200": e200,
            "atr_14": _safe_val(atr_series),
            "macd_histogram": macd_hist,
            "macd_signal": macd_sig,
            "stoch_k": stoch_k,
            "stoch_d": stoch_d,
            "ema_stack": self._ema_stack(e21, e50, e200),
        }

    def _compute_manual(
        self, df: pd.DataFrame, close: pd.Series
    ) -> dict[str, Any]:
        rsi = _rsi_manual(close, 14)
        ema21 = _ema_manual(close, 21)
        ema50 = _ema_manual(close, 50)
        ema200 = _ema_manual(close, 200)
        atr = _atr_manual(df, 14)
        _, macd_sig, macd_hist = _macd_manual(close)
        stoch_k, stoch_d = _stoch_manual(df)

        e21 = _safe_val(ema21)
        e50 = _safe_val(ema50)
        e200 = _safe_val(ema200)

        return {
            "rsi_14": _safe_val(rsi),
            "ema_21": e21,
            "ema_50": e50,
            "ema_200": e200,
            "atr_14": _safe_val(atr),
            "macd_histogram": _safe_val(macd_hist),
            "macd_signal": _safe_val(macd_sig),
            "stoch_k": _safe_val(stoch_k),
            "stoch_d": _safe_val(stoch_d),
            "ema_stack": self._ema_stack(e21, e50, e200),
        }

    def _ema_stack(self, ema21: float, ema50: float, ema200: float) -> str:
        """Classify EMA alignment."""
        if any(np.isnan(v) for v in [ema21, ema50, ema200]):
            return "mixed"
        if ema21 > ema50 > ema200:
            return "bullish"
        if ema21 < ema50 < ema200:
            return "bearish"
        return "mixed"

    def cache_to_redis(
        self,
        redis_client: Any,
        pair: str,
        timeframe: str,
        values: dict[str, Any],
    ) -> None:
        """Store indicator values in Redis with TTL matching the timeframe period.

        Args:
            redis_client: A redis-py (sync or async) client instance.
            pair: Instrument symbol (e.g. ``"EURUSD"``).
            timeframe: Bar timeframe (e.g. ``"1H"``).
            values: The dict returned by ``compute_all``.
        """
        key = f"indicators:{pair}:{timeframe}"
        ttl = _TF_TTL.get(timeframe, 60)

        # Convert NaN to None for JSON serialisation
        serialisable = {
            k: (None if isinstance(v, float) and np.isnan(v) else v)
            for k, v in values.items()
        }

        try:
            payload = json.dumps(serialisable)
            # Support both sync and async redis clients
            import asyncio

            if asyncio.iscoroutinefunction(getattr(redis_client, "set", None)):
                # Schedule the coroutine; caller is responsible for awaiting via event loop
                loop = asyncio.get_event_loop()
                loop.create_task(redis_client.set(key, payload, ex=ttl))
            else:
                redis_client.set(key, payload, ex=ttl)
        except Exception as exc:
            logger.warning(f"Failed to cache indicators for {pair}/{timeframe}: {exc}")

    async def cache_to_redis_async(
        self,
        redis_client: Any,
        pair: str,
        timeframe: str,
        values: dict[str, Any],
    ) -> None:
        """Async version of ``cache_to_redis`` for use with async redis clients."""
        key = f"indicators:{pair}:{timeframe}"
        ttl = _TF_TTL.get(timeframe, 60)

        serialisable = {
            k: (None if isinstance(v, float) and np.isnan(v) else v)
            for k, v in values.items()
        }

        try:
            payload = json.dumps(serialisable)
            await redis_client.set(key, payload, ex=ttl)
        except Exception as exc:
            logger.warning(f"Failed to async-cache indicators for {pair}/{timeframe}: {exc}")


# Module-level singleton
indicators = Indicators()
