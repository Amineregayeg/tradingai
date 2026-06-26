"""Binance public REST OHLCV source (no API key required).

Free, full crypto history at any timeframe. Used as the primary price feed for
both backtest and live. Paginates the 1000-bar/request klines cap.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pandas as pd

from app.core.logging import logger
from app.services.market_data.sources.base import (
    OHLCV_COLUMNS,
    MarketDataSource,
    empty_ohlcv,
)

# engine timeframe -> Binance interval
_INTERVAL: dict[str, str] = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1H": "1h", "4H": "4h", "D": "1d", "W": "1w",
}
# engine timeframe -> milliseconds per bar (for pagination cursor advance)
_INTERVAL_MS: dict[str, int] = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1H": 3_600_000, "4H": 14_400_000, "D": 86_400_000, "W": 604_800_000,
}
_MAX_LIMIT = 1000
# Mirror hosts tried in order (geo / outage resilience). data-api.binance.vision
# is the public market-data mirror and needs no key.
_BASES = (
    "https://api.binance.com",
    "https://data-api.binance.vision",
    "https://api-gcp.binance.com",
)


def _to_ms(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


class BinanceSource(MarketDataSource):
    name = "binance"

    def __init__(self, quote: str = "USDT", timeout: float = 20.0) -> None:
        self.quote = quote.upper()
        self._client = httpx.Client(
            timeout=timeout, headers={"User-Agent": "tradingai/1.0"}
        )

    #: recognised quote assets (longest first so 'FDUSD' wins over 'USD')
    _QUOTES = ("FDUSD", "USDT", "USDC", "BUSD", "TUSD", "BTC", "ETH", "BNB")

    def to_symbol(self, base: str) -> str:
        """'BTC' -> 'BTCUSDT'; pass-through if already a full pair (e.g. 'ETHBTC')."""
        b = base.upper().replace("/", "").replace("-", "").replace("_", "")
        for q in self._QUOTES:
            # full pair only if it ENDS WITH a quote and is strictly longer than it
            if b != q and len(b) > len(q) and b.endswith(q):
                return b
        return f"{b}{self.quote}"

    def fetch_ohlcv(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> pd.DataFrame:
        if timeframe not in _INTERVAL:
            raise ValueError(f"Unsupported timeframe {timeframe!r}")
        sym = self.to_symbol(symbol)
        interval = _INTERVAL[timeframe]
        step = _INTERVAL_MS[timeframe]
        start_ms, end_ms = _to_ms(start), _to_ms(end)

        rows: list[tuple] = []
        cursor = start_ms
        while cursor < end_ms:
            batch = self._get(
                "/api/v3/klines",
                {
                    "symbol": sym,
                    "interval": interval,
                    "startTime": cursor,
                    "endTime": end_ms,
                    "limit": _MAX_LIMIT,
                },
            )
            if not batch:
                break
            for k in batch:
                rows.append(
                    (int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]))
                )
            last_open = int(batch[-1][0])
            cursor = last_open + step
            if len(batch) < _MAX_LIMIT:
                break

        if not rows:
            return empty_ohlcv()

        df = pd.DataFrame(rows, columns=["time", *OHLCV_COLUMNS])
        df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
        df = (
            df.drop_duplicates("time")
            .set_index("time")
            .sort_index()
        )
        # [start, end) — drop a partial bar exactly at/after end
        df = df[df.index < pd.Timestamp(end_ms, unit="ms", tz="UTC")]
        return df

    def _get(self, path: str, params: dict) -> list:
        last_exc: Exception | None = None
        for base in _BASES:
            try:
                resp = self._client.get(base + path, params=params)
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:  # noqa: BLE001 - try next mirror
                last_exc = exc
                continue
        logger.warning(f"Binance klines fetch failed for {params.get('symbol')}: {last_exc}")
        return []

    def close(self) -> None:
        self._client.close()
