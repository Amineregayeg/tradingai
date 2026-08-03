"""Price bars from the venue we execute on (task 4.4, KNOWN_ISSUES A3).

The strategy read Binance while orders would go to CFT. Measured over 300
matched 1H bars: CFT closes sit a near-constant -0.0485% below Binance (a
BID-side spread — harmless, since BOS/FVG/direction are scale-invariant), but
individual bar RANGES differ by up to 0.117% of price. A high or low that moves
by that much can create or erase the FVG an entry depends on, so analysis has to
read the venue it trades on rather than a correlated proxy.

These tests protect the parts that would fail silently: symbol translation,
timestamp convention, and abstaining instead of crashing the live loop.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.services.market_data.sources.base import OHLCV_COLUMNS
from app.services.market_data.sources.cft import (
    APPROX_HISTORY_DAYS,
    MAX_CANDLES,
    TF_TO_CFT,
    CFTSource,
    to_cft_symbol,
)

T0 = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
WIDE_END = T0 + timedelta(days=30)


def make_source(payload, status: int = 200) -> CFTSource:
    """A CFTSource whose bridge call returns `payload` (dict -> json body)."""
    src = CFTSource(bridge_url="http://bridge:8100", bridge_token="tok")
    body = payload if isinstance(payload, str) else json.dumps(payload)
    src._call = lambda path: {"status": status, "body": body}  # noqa: SLF001
    return src


def candles(n: int = 5, start_ms: int | None = None, step_ms: int = 3_600_000) -> dict:
    base = start_ms if start_ms is not None else int(T0.timestamp() * 1000)
    return {
        "symbol": "BTCUSDT.cft", "interval": "H1",
        "candles": [
            {"time": base + i * step_ms, "open": 100.0 + i, "high": 101.0 + i,
             "low": 99.0 + i, "close": 100.5 + i, "volume": 10 + i}
            for i in range(n)
        ],
    }


# ---------------------------------------------------------------------------
# Symbol translation — silently wrong is the failure mode here
# ---------------------------------------------------------------------------
def test_usd_pairs_become_usdt_cft_symbols():
    """CFT quotes crypto against USDT with a .cft suffix. BTCUSD.cft does not
    exist — it 404s at their candle service — so USD must be normalised."""
    assert to_cft_symbol("BTC/USD") == "BTCUSDT.cft"
    assert to_cft_symbol("ETH/USD") == "ETHUSDT.cft"


def test_usdt_pairs_are_not_double_suffixed():
    assert to_cft_symbol("BTC/USDT") == "BTCUSDT.cft"
    assert to_cft_symbol("BTCUSDT") == "BTCUSDT.cft"


def test_live_loop_translates_symbols_at_the_boundary():
    """The loop passes BINANCE symbols ("BTCUSDT"). Handing that straight to
    CFTSource would build "BTCUSDTUSDT.cft" and 404 on every single bar."""
    from app.services.live.crypto_loop import LiveCryptoLoop

    loop = LiveCryptoLoop()
    assert loop._pair_for("BTCUSDT") == "BTC/USD"   # noqa: SLF001
    assert to_cft_symbol(loop._pair_for("BTCUSDT")) == "BTCUSDT.cft"  # noqa: SLF001


# ---------------------------------------------------------------------------
# Timestamps — a shift here would be a lookahead
# ---------------------------------------------------------------------------
def test_candle_time_is_the_bar_open_in_utc():
    """CFT stamps epoch MILLISECONDS at the bar's OPEN, matching the engine's
    convention. Any shift applied here would move a bar's label relative to its
    contents — the definition of a lookahead."""
    src = make_source(candles(3))
    df = src.fetch_ohlcv("BTC/USD", "1H", T0 - timedelta(hours=1), WIDE_END)

    assert list(df.index) == [
        pd.Timestamp(T0), pd.Timestamp(T0 + timedelta(hours=1)),
        pd.Timestamp(T0 + timedelta(hours=2)),
    ]
    assert str(df.index.tz) == "UTC"


def test_schema_matches_the_ohlcv_contract():
    df = make_source(candles(4)).fetch_ohlcv("BTC/USD", "1H", T0 - timedelta(hours=1), WIDE_END)
    assert list(df.columns) == list(OHLCV_COLUMNS)
    assert df.index.name == "time"
    assert df.index.is_monotonic_increasing and df.index.is_unique
    assert all(str(d) == "float64" for d in df.dtypes)
    assert (df["high"] >= df["low"]).all()


def test_range_is_half_open():
    src = make_source(candles(5))
    end = T0 + timedelta(hours=3)
    df = src.fetch_ohlcv("BTC/USD", "1H", T0, end)
    assert pd.Timestamp(T0) in df.index
    assert pd.Timestamp(end) not in df.index, "end must be exclusive"


def test_duplicate_timestamps_keep_the_last():
    payload = candles(2)
    payload["candles"].append({**payload["candles"][0], "close": 999.0})
    df = make_source(payload).fetch_ohlcv("BTC/USD", "1H", T0 - timedelta(hours=1), WIDE_END)
    assert len(df) == 2
    assert df.loc[pd.Timestamp(T0), "close"] == 999.0


# ---------------------------------------------------------------------------
# Abstain, never crash the live loop
# ---------------------------------------------------------------------------
def test_bridge_failure_returns_an_empty_frame():
    """A price source that raises would take the whole live loop down every
    time the bridge restarts. The engine's contract is to abstain."""
    src = CFTSource(bridge_url="http://bridge:8100", bridge_token="tok")

    def boom(path):
        raise ConnectionError("bridge is down")

    src._call = boom  # noqa: SLF001
    df = src.fetch_ohlcv("BTC/USD", "1H", T0, WIDE_END)
    assert df.empty and list(df.columns) == list(OHLCV_COLUMNS)


def test_non_200_from_cft_returns_empty():
    src = make_source("Validation failed for argument [0]", status=400)
    assert src.fetch_ohlcv("BTC/USD", "1H", T0, WIDE_END).empty


def test_unparseable_body_returns_empty():
    assert make_source("<html>not json</html>").fetch_ohlcv(
        "BTC/USD", "1H", T0, WIDE_END
    ).empty


def test_missing_columns_returns_empty_rather_than_a_broken_frame():
    """A frame missing 'low' would flow into structure detection and fail far
    from here, with a confusing error."""
    payload = {"candles": [{"time": int(T0.timestamp() * 1000), "open": 1, "high": 2, "close": 1.5}]}
    assert make_source(payload).fetch_ohlcv("BTC/USD", "1H", T0 - timedelta(hours=1), WIDE_END).empty


def test_no_bridge_token_abstains():
    src = CFTSource(bridge_url="http://bridge:8100", bridge_token="")
    assert src.fetch_ohlcv("BTC/USD", "1H", T0, WIDE_END).empty


def test_empty_candle_list_is_not_an_error():
    assert make_source({"candles": []}).fetch_ohlcv("BTC/USD", "1H", T0, WIDE_END).empty


# ---------------------------------------------------------------------------
# Timeframes / history limits
# ---------------------------------------------------------------------------
def test_unsupported_timeframe_raises():
    """A typo must fail loudly here, not become a silent 400 from CFT."""
    with pytest.raises(ValueError, match="unsupported timeframe"):
        make_source(candles()).fetch_ohlcv("BTC/USD", "7m", T0, WIDE_END)


def test_interval_tokens_are_cft_uppercase_forms():
    """CFT rejects lowercase forms outright ("Validation failed for argument
    [0]"), so this mapping is load-bearing, not cosmetic."""
    assert TF_TO_CFT["1H"] == "H1"
    assert TF_TO_CFT["15m"] == "M15"
    assert TF_TO_CFT["D"] == "D1"


def test_history_limits_are_recorded_for_every_supported_timeframe():
    """These decide where this source may be used at all: 1H offers ~125 days
    against the ~470 the corrected backtest needs, which is why backtests stay
    on Binance."""
    assert set(APPROX_HISTORY_DAYS) == set(TF_TO_CFT)
    assert APPROX_HISTORY_DAYS["1H"] < 200, "1H history is short — backtests cannot use it"
    assert APPROX_HISTORY_DAYS["D"] > 1000
    assert MAX_CANDLES == 3000


def test_requesting_more_history_than_cft_has_still_returns_what_exists(caplog):
    """Short data must not be mistaken for complete data — it warns, then
    returns what the venue actually has."""
    src = make_source(candles(3))
    df = src.fetch_ohlcv("BTC/USD", "1H", T0 - timedelta(days=400), WIDE_END)
    assert len(df) == 3
