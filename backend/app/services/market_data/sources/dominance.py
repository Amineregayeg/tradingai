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

#: Engine timeframe -> length in seconds. Used to say how many samples a bar on that
#: timeframe SHOULD hold at a given poll rate, which is what decides whether the timeframe
#: is usable at all (KNOWN_ISSUES B11).
_TF_SECONDS: dict[str, int] = {
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
    "1H": 3600, "4H": 14400, "D": 86400, "W": 604800,
}


def expected_samples_per_bar(timeframe: str, poll_seconds: float) -> int:
    """How many observations a complete bar on `timeframe` holds at `poll_seconds`.

    This is the whole of B11 in one line of arithmetic. These are not exchange bars: they
    are resampled point observations, so a bar's high and low are only price action if
    enough observations went into it. At 60 s polling a 5m bar holds five, and its extremes
    are sampling luck.
    """
    seconds = _TF_SECONDS.get(timeframe)
    if seconds is None:
        raise ValueError(
            f"unsupported timeframe {timeframe!r}; expected one of {sorted(_TF_SECONDS)}"
        )
    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive")
    return int(seconds // poll_seconds)


def viable_timeframes(poll_seconds: float, min_samples: int) -> list[str]:
    """Which timeframes can carry structure at this poll rate, shortest first.

    `min_samples` is the engine's declared minimum and is NOT defaulted here on purpose —
    the number belongs to the strategy layer (`gate_008_roster.MIN_SAMPLES_PER_SYNTHETIC_BAR`)
    and duplicating it in the data layer is how two thresholds drift apart.
    """
    return [
        tf for tf in sorted(_TF_SECONDS, key=lambda t: _TF_SECONDS[t])
        if expected_samples_per_bar(tf, poll_seconds) >= min_samples
    ]


#: Engine timeframe -> pandas offset alias.
_TF_TO_OFFSET: dict[str, str] = {
    "1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min",
    "1H": "1h", "4H": "4h", "D": "1D", "W": "1W",
}


def _empty_with_samples() -> pd.DataFrame:
    """An empty frame in the ``_bars_with_samples`` contract: OHLCV **plus** ``samples``.

    Deliberately local to this source rather than a change to
    :func:`~app.services.market_data.sources.base.empty_ohlcv`. That helper is shared
    with ``binance.py`` and ``cft.py``, and adding ``samples`` there would give every
    source a column it cannot populate — the "fake it" this module's docstrings
    already refuse.

    It exists because a no-data branch that silently drops the column is how "no
    data" becomes "zero samples, looks fine" at the call site: a reader doing
    ``bars["samples"]`` gets a KeyError on the empty path and a plausible 0 on the
    populated one, so the two failure modes do not even look alike (KNOWN_ISSUES A11).
    """
    df = empty_ohlcv()
    df["samples"] = pd.Series(dtype="int64")
    return df


class DominanceSource(MarketDataSource):
    """OHLCV bars for the dominance symbols, resampled from raw samples."""

    name = "dominance"

    def __init__(self, raw_csv: str | Path | None = None) -> None:
        # BOTH NAMES, AND THE SECOND ONE IS NOT REDUNDANT.
        #
        # The api's deployed compose sets `DOMINANCE_DATA_DIR: "/data/dominance"` and
        # mounts /opt/dominance there read-only — correct intent, correct mount, and a
        # variable name this code never read. So the api fell through to the
        # /opt/dominance default, which does not exist inside that container, and every
        # dominance read from the api returned nothing at all. The collector's compose
        # sets `DOMINANCE_DIR`, so the two services disagreed about the name of the same
        # thing and only one of them matched the code.
        #
        # Found by T-0006 criterion 4c, and only by it: the shadow reported all FOUR
        # roster panels missing where exactly two should have been, and GATE-007's
        # `alignment_tf` came back empty. "Read nothing" and "read the two we have" are
        # different verdicts and the criterion existed to tell them apart. Criterion 3
        # alone looked like success.
        #
        # DOMINANCE_DIR is preferred because it is what the collector and this source
        # already agreed on; DOMINANCE_DATA_DIR is accepted so the running api works
        # without a root-only edit to /docker/tradingai/docker-compose.yml, which no
        # agent can perform. The durable fix is to rename it there — see KNOWN_ISSUES.
        dominance_dir = (
            os.getenv("DOMINANCE_DIR")
            or os.getenv("DOMINANCE_DATA_DIR")
            or "/opt/dominance"
        )
        self.raw_csv = Path(
            raw_csv
            or os.getenv("DOMINANCE_RAW_CSV")
            or Path(dominance_dir) / "dominance_intraday_raw.csv"
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
    def _bars_with_samples(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        drop_partial: bool = True,
        min_samples: int | None = None,
    ) -> pd.DataFrame:
        """OHLCV plus a ``samples`` column. The single implementation; both public
        readers below are projections of it, so they cannot drift apart.

        ``min_samples`` drops bars assembled from fewer than that many raw observations.
        Left None by default so existing callers are unchanged; the strategy layer passes
        its declared minimum (``gate_008_roster.MIN_SAMPLES_PER_SYNTHETIC_BAR``).

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
            return _empty_with_samples()

        series = pd.to_numeric(raw[column], errors="coerce").dropna()
        if series.empty:
            return _empty_with_samples()

        # closed="left", label="left": a bar stamped 12:00 aggregates samples in
        # [12:00, 12:15) and carries that timestamp. Any other convention lets a
        # bar include a sample from after its own label — a lookahead, and the
        # exact class of bug this repo has three regression tests for.
        grouped = series.resample(offset, label="left", closed="left")
        bars = grouped.ohlc()
        # How many observations went into each bar. Carried because these are RESAMPLED
        # point samples, not exchange bars: a bar's high and low mean something only if
        # enough observations produced them, and a caller cannot tell a 60-sample bar from
        # a 5-sample one by looking at it (KNOWN_ISSUES B11).
        bars["samples"] = grouped.count().astype(int)

        # resample() emits a row for every period in the range, including ones
        # with no samples at all. Those are NOT bars — the collector was down, or
        # had not started. Dropping them keeps gaps as gaps.
        #
        # SUBSET IS LOAD-BEARING: only the price columns decide whether a period is
        # empty. An empty period gets NaN for open/high/low/close but `samples` = 0,
        # and 0 is not NaN — so a bare `how="all"` has to agree across a column that
        # is never NaN, matches no row, and drops nothing. That is not hypothetical:
        # assigning `samples` above silently disabled this line the day it was added,
        # and this comment went on describing behaviour the code had stopped having
        # (KNOWN_ISSUES A11 — bars were invented across every collector outage).
        # Any column added above must be excluded here for the same reason.
        price_cols = ["open", "high", "low", "close"]
        bars = bars.dropna(subset=price_cols, how="all")
        if bars.empty:
            return _empty_with_samples()

        # A bar assembled from too few observations is not a low-quality bar, it is not a
        # bar. Dropping it is the same judgement the line above makes about an empty period,
        # for the same reason: a gap is the truth, and a thin bar is a shape that structure
        # detection will read as order flow.
        if min_samples is not None:
            bars = bars[bars["samples"] >= int(min_samples)]
            if bars.empty:
                return _empty_with_samples()

        if drop_partial:
            last_sample = series.index[-1]
            period_end = bars.index[-1] + pd.tseries.frequencies.to_offset(offset)
            if last_sample < period_end:
                bars = bars.iloc[:-1]

        # Volume is structurally absent for dominance. Zero is the honest
        # placeholder; a fabricated number would be worse than none.
        bars["volume"] = 0.0
        bars = bars[[*OHLCV_COLUMNS, "samples"]]

        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)
        if start_ts.tzinfo is None:
            start_ts = start_ts.tz_localize(timezone.utc)
        if end_ts.tzinfo is None:
            end_ts = end_ts.tz_localize(timezone.utc)
        bars = bars[(bars.index >= start_ts) & (bars.index < end_ts)]

        if bars.empty:
            return _empty_with_samples()

        bars.index.name = "time"
        return bars.astype(float)

    # ------------------------------------------------------------------
    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        drop_partial: bool = True,
        min_samples: int | None = None,
    ) -> pd.DataFrame:
        """Bars for ``symbol`` in ``[start, end)``, in the public OHLCV contract.

        ``samples`` is deliberately absent here — every other source would have to fake
        it. Callers that need it use :meth:`fetch_ohlcv_with_samples`.

        ``drop_partial`` (default True) removes a trailing bar whose period has not
        finished yet. This matters for causality, not tidiness: a 15m bar stamped 12:00
        covers [12:00, 12:15) and is not knowable until 12:15. The live loop drops the
        still-forming price bar for the same reason (``crypto_loop._tick_symbol``); a
        strategy that reads a partial dominance bar is reading the present as if it were
        closed history.
        """
        bars = self._bars_with_samples(
            symbol, timeframe, start, end,
            drop_partial=drop_partial, min_samples=min_samples,
        )
        # PROJECT UNCONDITIONALLY. This used to short-circuit on an empty frame and
        # return it unprojected, which was invisible only because the empty frame had
        # no `samples` column to leak. Now that `_bars_with_samples` honours its own
        # contract on every path, that short-circuit would hand `samples` back out of
        # `fetch_ohlcv` — contradicting the docstring above on exactly the branch
        # nobody tests. Selecting columns from an empty frame is well-defined and
        # costs nothing, so there is no reason for the empty path to be special.
        return bars[list(OHLCV_COLUMNS)]

    def fetch_ohlcv_with_samples(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        drop_partial: bool = True,
        min_samples: int | None = None,
    ) -> pd.DataFrame:
        """``fetch_ohlcv`` plus a ``samples`` column: observations behind each bar.

        This is what lets a correlate read carry ``bar_sample_count`` so the layout can
        refuse to grade noise (GATE-036 / ``LayoutReadability``). Without it the guard has
        no data source and is decorative.
        """
        return self._bars_with_samples(
            symbol, timeframe, start, end,
            drop_partial=drop_partial, min_samples=min_samples,
        )

    def timeframe_viability(self, poll_seconds: float, min_samples: int) -> dict:
        """Which timeframes this collector's sampling rate can actually support.

        Reported rather than assumed: the answer decides whether the execution timeframe
        under discussion is measurable at all, and it changes the moment the collector's
        poll interval does.
        """
        return {
            "poll_seconds": poll_seconds,
            "min_samples": min_samples,
            "expected_samples": {
                tf: expected_samples_per_bar(tf, poll_seconds) for tf in _TF_SECONDS
            },
            "viable": viable_timeframes(poll_seconds, min_samples),
        }

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
