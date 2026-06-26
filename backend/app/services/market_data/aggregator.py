"""OHLCV aggregation from 1-minute base candles to higher timeframes."""

from datetime import datetime

import pandas as pd

TIMEFRAMES = ["1m", "5m", "15m", "1H", "4H", "D"]

# Mapping from our timeframe labels to pandas resample frequency aliases
_TF_TO_RESAMPLE: dict[str, str] = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "1H": "1h",
    "4H": "4h",
    "D": "1D",
}


def should_close(timeframe: str, candle_time: datetime) -> bool:
    """Return True if the given datetime is the close bar for the timeframe.

    Args:
        timeframe: One of TIMEFRAMES (e.g. "1m", "5m", "1H", …).
        candle_time: The timestamp of the 1-minute candle being processed.

    Returns:
        True when this 1m candle is the *last* 1m bar in the higher-TF period.
    """
    m = candle_time.minute
    h = candle_time.hour

    if timeframe == "1m":
        return True
    if timeframe == "5m":
        return m % 5 == 4
    if timeframe == "15m":
        return m % 15 == 14
    if timeframe == "1H":
        return m == 59
    if timeframe == "4H":
        return h % 4 == 3 and m == 59
    if timeframe == "D":
        return h == 23 and m == 59
    return False


def aggregate_candles(df_1m: pd.DataFrame, target_tf: str) -> pd.DataFrame:
    """Aggregate a 1m OHLCV DataFrame to *target_tf*.

    Args:
        df_1m: DataFrame with a DatetimeIndex named "time" and columns
               [open, high, low, close, volume].  Must be sorted ascending.
        target_tf: Target timeframe string, one of TIMEFRAMES.

    Returns:
        DataFrame with the same schema (DatetimeIndex "time", OHLCV columns),
        resampled to *target_tf*.  Empty bars are dropped.
    """
    if target_tf not in _TF_TO_RESAMPLE:
        raise ValueError(f"Unknown timeframe '{target_tf}'. Valid: {TIMEFRAMES}")

    freq = _TF_TO_RESAMPLE[target_tf]

    # Ensure DatetimeIndex
    if not isinstance(df_1m.index, pd.DatetimeIndex):
        df_1m = df_1m.copy()
        df_1m.index = pd.to_datetime(df_1m.index, utc=True)

    agg_rules: dict[str, str | object] = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }

    df_agg = (
        df_1m[list(agg_rules.keys())]
        .resample(freq, label="left", closed="left")
        .agg(agg_rules)
        .dropna(subset=["open"])
    )
    df_agg.index.name = "time"
    return df_agg
