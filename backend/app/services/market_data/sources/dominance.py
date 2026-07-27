"""Crypto-dominance bars — TOTAL, TOTAL2, TOTAL3, BTC.D, ETH.D, USDT.D.

Implements :class:`MarketDataSource`, so the dominance symbols are consumable by
exactly the same code that consumes BTC/ETH price bars. That is the whole point:
Magic Alignment needs to run structure detection (BOS / FVG / direction) on the
dominance series on the SAME intraday timeframe as the entry, and it should not
require a parallel code path to do it::

    src = DominanceSource()
    btcd = src.fetch_ohlcv("BTC.D", "15m", start, end)
    ict_detector.detect_fvg(_normalize_df(btcd.reset_index()))   # just works

The underlying samples are produced by ``backend/scripts/collect_dominance.py``
(live Binance prices x daily CoinGecko supplies — see that file for why polling
CoinGecko /global intraday does not work). This class only reads and reshapes;
it never fetches, so it stays deterministic and testable.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
* **It does not backfill.** History starts when collection started. Every bar is
  a real observation or it is absent. There is no free source of historical
  intraday dominance to interpolate from, and inventing one would fabricate the
  exact signal the strategy is being asked to evaluate.
* **It does not forward-fill gaps.** If the collector was down from 03:00-04:00,
  those bars do not exist. A flat synthetic candle is not missing data, it is
  wrong data, and a structure detector cannot tell the difference.
* **It does not report volume.** Dominance has no volume. The column exists
  because the OHLCV schema requires it and is always 0.0 — never a plausible
  invented number. Any indicator that needs real volume must not be used here.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from app.services.market_data.sources.base import (
    OHLCV_COLUMNS,
    MarketDataSource,
    empty_ohlcv,
)

#: The symbols Magic Alignment confirms against. CSV columns use ``_D`` because
#: the existing daily feed does; the public symbol names use ``.D`` because that
#: is what the trader's method and TradingView call them.
SYMBOL_TO_COLUMN: dict[str, str] = {
    "TOTAL": "TOTAL",
    "TOTAL2": "TOTAL2",
    "TOTAL3": "TOTAL3",
    "BTC.D": "BTC_D",
    "ETH.D": "ETH_D",
    "USDT.D": "USDT_D",
}

DOMINANCE_SYMBOLS: tuple[str, ...] = tuple(SYMBOL_TO_COLUMN)

#: Engine timeframe -> pandas offset alias.
_TF_TO_OFFSET: dict[str, str] = {
    "1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min",
    "1H": "1h", "4H": "4h", "D": "1D", "W": "1W",
}


class DominanceSource(MarketDataSource):
    """OHLCV bars for the dominance symbols, resampled from raw samples."""

    name = "dominance"

    def __init__(self, raw_csv: str | Path | None = None) -> None:
        self.raw_csv = Path(
            raw_csv
            or os.getenv("DOMINANCE_RAW_CSV")
            or Path(os.getenv("DOMINANCE_DIR", "/opt/dominance")) / "dominance_intraday_raw.csv"
        )

    # ------------------------------------------------------------------
    def load_raw(self) -> pd.DataFrame:
        """Raw samples indexed by UTC time. Empty frame if unavailable.

        A missing or unreadable file is not an error worth raising: the engine's
        contract is to ABSTAIN when an input is absent, not to crash the loop or
        guess. Callers see zero rows and decline to trade.
        """
        if not self.raw_csv.is_file():
            return pd.DataFrame()
        try:
            df = pd.read_csv(self.raw_csv)
        except Exception:  # noqa: BLE001 - a truncated/corrupt file abstains too
            return pd.DataFrame()
        if df.empty or "ts_utc" not in df.columns:
            return pd.DataFrame()

        df["ts_utc"] = pd.to_datetime(df["ts_utc"], utc=True, errors="coerce")
        df = df.dropna(subset=["ts_utc"]).set_index("ts_utc").sort_index()
        df.index.name = "time"
        # Duplicate timestamps would double-weight a sample in the OHLC; keep the
        # last observation for any instant.
        return df[~df.index.duplicated(keep="last")]

    # ------------------------------------------------------------------
    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        drop_partial: bool = True,
    ) -> pd.DataFrame:
        """Bars for ``symbol`` in ``[start, end)``.

        ``drop_partial`` (default True) removes a trailing bar whose period has
        not finished yet. This matters for causality, not tidiness: a 15m bar
        stamped 12:00 covers [12:00, 12:15) and is not knowable until 12:15. The
        live loop drops the still-forming price bar for the same reason
        (``crypto_loop._tick_symbol``); a strategy that reads a partial
        dominance bar is reading the present as if it were closed history.
        """
        if symbol not in SYMBOL_TO_COLUMN:
            raise ValueError(
                f"unknown dominance symbol {symbol!r}; expected one of {DOMINANCE_SYMBOLS}"
            )
        offset = _TF_TO_OFFSET.get(timeframe)
        if offset is None:
            raise ValueError(
                f"unsupported timeframe {timeframe!r}; expected one of {sorted(_TF_TO_OFFSET)}"
            )

        raw = self.load_raw()
        column = SYMBOL_TO_COLUMN[symbol]
        if raw.empty or column not in raw.columns:
            return empty_ohlcv()

        series = pd.to_numeric(raw[column], errors="coerce").dropna()
        if series.empty:
            return empty_ohlcv()

        # closed="left", label="left": a bar stamped 12:00 aggregates samples in
        # [12:00, 12:15) and carries that timestamp. Any other convention lets a
        # bar include a sample from after its own label — a lookahead, and the
        # exact class of bug this repo has three regression tests for.
        bars = series.resample(offset, label="left", closed="left").ohlc()

        # resample() emits a row for every period in the range, including ones
        # with no samples at all. Those are NOT bars — the collector was down, or
        # had not started. Dropping them keeps gaps as gaps.
        bars = bars.dropna(how="all")
        if bars.empty:
            return empty_ohlcv()

        if drop_partial:
            last_sample = series.index[-1]
            period_end = bars.index[-1] + pd.tseries.frequencies.to_offset(offset)
            if last_sample < period_end:
                bars = bars.iloc[:-1]

        # Volume is structurally absent for dominance. Zero is the honest
        # placeholder; a fabricated number would be worse than none.
        bars["volume"] = 0.0
        bars = bars[list(OHLCV_COLUMNS)]

        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)
        if start_ts.tzinfo is None:
            start_ts = start_ts.tz_localize(timezone.utc)
        if end_ts.tzinfo is None:
            end_ts = end_ts.tz_localize(timezone.utc)
        bars = bars[(bars.index >= start_ts) & (bars.index < end_ts)]

        if bars.empty:
            return empty_ohlcv()

        bars.index.name = "time"
        return bars.astype(float)

    # ------------------------------------------------------------------
    def coverage(self) -> dict:
        """What data actually exists — for the UI, and for deciding readiness.

        Magic Alignment cannot be evaluated until enough history accumulates.
        This reports the truth about that rather than letting someone assume it.
        """
        raw = self.load_raw()
        if raw.empty:
            return {"available": False, "samples": 0, "reason": f"no data at {self.raw_csv}"}

        first, last = raw.index[0], raw.index[-1]
        span_min = (last - first).total_seconds() / 60.0
        expected = span_min + 1
        out = {
            "available": True,
            "samples": int(len(raw)),
            "first": first.isoformat(),
            "last": last.isoformat(),
            "span_hours": round(span_min / 60.0, 2),
            "density_pct": round(100.0 * len(raw) / expected, 1) if expected > 0 else None,
            "stale_minutes": round(
                (datetime.now(tz=timezone.utc) - last.to_pydatetime()).total_seconds() / 60.0, 1
            ),
        }
        if "coverage_pct" in raw.columns:
            out["live_priced_pct_last"] = float(raw["coverage_pct"].iloc[-1])
        if "supplies_age_h" in raw.columns:
            out["supplies_age_h_last"] = float(raw["supplies_age_h"].iloc[-1])
        return out
