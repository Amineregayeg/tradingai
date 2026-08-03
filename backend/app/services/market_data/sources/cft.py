"""Price bars from Crypto Fund Trader — the venue we would actually execute on.

WHY THIS EXISTS (KNOWN_ISSUES A3)
The strategy read Binance prices while orders would be placed at CFT. Those are
different venues with different books, so the engine could see a setup at a
structural level that never existed on the chart it actually trades. For a
method built on FVGs and breaks of structure — i.e. on exact highs and lows —
that is a silent source of error with nothing measuring it.

MEASURED DIVERGENCE (300 matched 1H bars, 2026-08-03)

    BTC close vs Binance:  mean -0.0485%,  stdev 0.0093%,  range -0.072..-0.017%
    ETH close vs Binance:  mean -0.0485%,  stdev 0.0090%,  range -0.076..-0.016%
    bar-range (high-low) difference: mean 0.013%, max 0.117% of price

The close offset is a near-constant BID-side spread, not noise, and a constant
multiplicative offset moves no structure — BOS/FVG/direction are scale-invariant.
The bar RANGES are the real difference: a high or low that differs by up to
0.12% can create or erase a gap. That is why analysis has to read the venue it
trades on rather than a correlated proxy.

HISTORY LIMITS (measured, and they decide where this can be used)

    interval   bars   span
    M1         3000   ~2 days
    M5         3000   ~10 days
    M15        3000   ~31 days
    M30        3000   ~62 days
    H1         3000   ~125 days
    H4         3000   ~499 days
    D1         2323   ~6.4 years

The corrected backtest covers ~470 days at 1H, and CFT offers 125. So this
source is for LIVE and FORWARD-SIM use; historical backtests keep using Binance
and accept the venue difference, which is now a measured number rather than an
unknown. See KNOWN_ISSUES.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pandas as pd

from app.core.logging import logger
from app.services.market_data.sources.base import (
    OHLCV_COLUMNS,
    MarketDataSource,
    empty_ohlcv,
)

#: Engine timeframe -> CFT's interval token. CFT rejects lowercase forms like
#: "1h" outright ("Validation failed for argument [0]"), so this mapping is not
#: cosmetic — getting it wrong is a hard 400.
TF_TO_CFT: dict[str, str] = {
    "1m": "M1",
    "5m": "M5",
    "15m": "M15",
    "30m": "M30",
    "1H": "H1",
    "4H": "H4",
    "D": "D1",
}

#: Roughly how much history CFT serves per interval, in days (measured).
#: Used to warn when a caller asks for a window the venue cannot cover, instead
#: of silently returning a shorter series that looks complete.
APPROX_HISTORY_DAYS: dict[str, int] = {
    "1m": 2, "5m": 10, "15m": 31, "30m": 62, "1H": 125, "4H": 499, "D": 2322,
}

#: CFT caps a candles response at 3000 regardless of what is requested.
MAX_CANDLES = 3000


def to_cft_symbol(pair: str) -> str:
    """``BTC/USD`` -> ``BTCUSDT.cft``.

    CFT quotes crypto against USDT with a ``.cft`` broker suffix. ``BTCUSD.cft``
    does not exist — it 404s at their candle service — so USD is normalised to
    USDT rather than passed through.
    """
    base = pair.replace("/", "").replace("_", "").upper()
    if base.endswith("USD") and not base.endswith("USDT"):
        base = base[:-3] + "USDT"
    return f"{base}.cft"


class CFTSource(MarketDataSource):
    """OHLCV from CFT, fetched through the browser bridge.

    Reads through the same bridge the broker adapter uses: CFT is behind
    Cloudflare bot protection that fingerprints the TLS handshake, so no plain
    HTTP client can reach it. See ``cft_bridge_transport`` for the measurements.
    """

    name = "cft"

    def __init__(self, bridge_url: str | None = None, bridge_token: str | None = None) -> None:
        self._bridge_url = (bridge_url or os.getenv("CFT_BRIDGE_URL", "http://cft-bridge:8100")).rstrip("/")
        self._bridge_token = bridge_token or os.getenv("CFT_BRIDGE_TOKEN", "")

    # ------------------------------------------------------------------
    def _call(self, path: str) -> dict:
        """One bridge call. Synchronous because ``MarketDataSource.fetch_ohlcv``
        is sync and its callers already run it via ``asyncio.to_thread``."""
        import urllib.request

        req = urllib.request.Request(
            f"{self._bridge_url}/call",
            data=json.dumps({"method": "GET", "path": path}).encode(),
            headers={"X-Bridge-Token": self._bridge_token, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())

    # ------------------------------------------------------------------
    def fetch_ohlcv(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> pd.DataFrame:
        """Bars for ``symbol`` in ``[start, end)``, indexed by UTC open time.

        Returns an EMPTY frame rather than raising when CFT is unreachable. The
        engine's contract is to abstain on a missing input, and a price source
        that throws would take the whole live loop down every time the bridge
        restarts.
        """
        interval = TF_TO_CFT.get(timeframe)
        if interval is None:
            raise ValueError(
                f"unsupported timeframe {timeframe!r}; CFT serves {sorted(TF_TO_CFT)}"
            )
        if not self._bridge_token:
            logger.warning("CFT price source has no bridge token configured")
            return empty_ohlcv()

        cft_symbol = to_cft_symbol(symbol)

        # Warn when the requested window exceeds what this venue can serve, so a
        # short series is never mistaken for a complete one.
        wanted_days = max(0, (end - start).days)
        available = APPROX_HISTORY_DAYS.get(timeframe, 0)
        if wanted_days > available:
            logger.warning(
                "CFT cannot cover the requested window — returning what it has",
                symbol=cft_symbol, timeframe=timeframe,
                requested_days=wanted_days, available_days=available,
            )

        try:
            # candleSide=BID: the side a long exits and a short enters at. CFT
            # has no combined feed; BID is the conservative choice for a
            # strategy whose stops are what get hit.
            resp = self._call(
                f"/candles?symbol={cft_symbol}&interval={interval}"
                f"&candleSide=BID&amount={MAX_CANDLES}"
            )
        except Exception as exc:  # noqa: BLE001 - abstain, never kill the loop
            logger.warning("CFT candle fetch failed", symbol=cft_symbol, error=str(exc))
            return empty_ohlcv()

        if resp.get("status") != 200:
            logger.warning(
                "CFT candle request rejected",
                symbol=cft_symbol, status=resp.get("status"),
                body=str(resp.get("body"))[:200],
            )
            return empty_ohlcv()

        try:
            candles = json.loads(resp["body"]).get("candles") or []
        except Exception as exc:  # noqa: BLE001
            logger.warning("CFT candle response unparseable", error=str(exc))
            return empty_ohlcv()

        if not candles:
            return empty_ohlcv()

        df = pd.DataFrame(candles)
        missing = {"time", *OHLCV_COLUMNS} - set(df.columns)
        if missing:
            logger.warning("CFT candles missing columns", missing=sorted(missing))
            return empty_ohlcv()

        # CFT stamps candles in epoch MILLISECONDS at the bar's OPEN time, which
        # matches the engine's convention (a bar labelled 12:00 covers
        # [12:00, 13:00) on H1). No shifting needed — and shifting would be a
        # lookahead.
        df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
        df = df.dropna(subset=["time"]).set_index("time").sort_index()
        df.index.name = "time"
        df = df[~df.index.duplicated(keep="last")]

        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)
        if start_ts.tzinfo is None:
            start_ts = start_ts.tz_localize(timezone.utc)
        if end_ts.tzinfo is None:
            end_ts = end_ts.tz_localize(timezone.utc)
        df = df[(df.index >= start_ts) & (df.index < end_ts)]

        if df.empty:
            return empty_ohlcv()

        return df[list(OHLCV_COLUMNS)].astype(float)
