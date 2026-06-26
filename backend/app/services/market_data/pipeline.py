"""Core market-data pipeline: ticks → 1m candles → higher-TF candles → DB → ICT."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.models.candle import Candle
from app.services.market_data.aggregator import TIMEFRAMES, aggregate_candles, should_close

# Higher timeframes derived from 1m candles (1m is always stored directly)
_DERIVED_TIMEFRAMES = [tf for tf in TIMEFRAMES if tf != "1m"]


@dataclass
class TickData:
    """Normalised price tick."""

    pair: str
    bid: float
    ask: float
    timestamp: datetime


@dataclass
class _CandleState:
    """Mutable state for the current in-progress 1-minute candle."""

    pair: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    start_time: datetime  # truncated to the minute boundary

    def update(self, price: float, tick_volume: float = 1.0) -> None:
        self.high = max(self.high, price)
        self.low = min(self.low, price)
        self.close = price
        self.volume += tick_volume

    def to_dict(self) -> dict:
        return {
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "start_time": self.start_time,
        }


class CandlePipeline:
    """Converts a tick stream into OHLCV candles and persists them to the DB.

    Flow
    ----
    1. ``process_tick`` receives a bid/ask tick.
    2. Mid price = (bid + ask) / 2 is used for OHLCV.
    3. The current 1m candle is updated in-memory.
    4. When the minute rolls over the closed 1m bar is:
       - persisted to the ``candles`` table (upsert).
       - used to derive and persist any higher-TF bars that also closed.
       - broadcast to all registered ``on_candle_close`` callbacks.
    5. ICT detection is triggered via those callbacks.
    """

    def __init__(self) -> None:
        # key: "EURUSD_1m"  value: _CandleState
        self._current_candles: dict[str, _CandleState] = {}
        # Rolling buffer of recently closed 1m candles per pair for higher-TF aggregation
        # key: pair, value: list of candle dicts (open, high, low, close, volume, start_time)
        self._candle_history: dict[str, list[dict]] = {}
        self._on_candle_close_callbacks: list[Callable] = []
        self._db_session_factory: Callable | None = None
        # Lock per-pair to serialise tick processing
        self._locks: dict[str, asyncio.Lock] = {}

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def set_db_session_factory(self, factory: Callable) -> None:
        """Set the async session factory (e.g. ``async_session_maker``)."""
        self._db_session_factory = factory

    def on_candle_close(self, callback: Callable) -> None:
        """Register a callback invoked whenever a candle closes.

        The callback signature is: ``callback(pair: str, timeframe: str, candle: dict)``.
        The callback may be a coroutine function.
        """
        self._on_candle_close_callbacks.append(callback)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def process_tick(
        self,
        pair: str,
        bid: float,
        ask: float,
        timestamp: datetime,
    ) -> None:
        """Process a single price tick.

        Args:
            pair: Instrument symbol, e.g. ``"EURUSD"``.
            bid: Broker bid price.
            ask: Broker ask price.
            timestamp: Tick UTC datetime (timezone-aware).
        """
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        mid = (bid + ask) / 2.0
        # Truncate to the minute boundary
        bar_start = timestamp.replace(second=0, microsecond=0)
        key = f"{pair}_1m"

        if pair not in self._locks:
            self._locks[pair] = asyncio.Lock()

        async with self._locks[pair]:
            current = self._current_candles.get(key)

            if current is None:
                # First ever tick for this pair
                self._current_candles[key] = _CandleState(
                    pair=pair,
                    open=mid,
                    high=mid,
                    low=mid,
                    close=mid,
                    volume=1.0,
                    start_time=bar_start,
                )
                return

            if bar_start > current.start_time:
                # The minute has rolled over → close the current bar
                closed = current.to_dict()
                await self._on_bar_close(pair, closed)

                # Start a new 1m bar
                self._current_candles[key] = _CandleState(
                    pair=pair,
                    open=mid,
                    high=mid,
                    low=mid,
                    close=mid,
                    volume=1.0,
                    start_time=bar_start,
                )
            else:
                current.update(mid)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _on_bar_close(self, pair: str, candle: dict) -> None:
        """Handle a closed 1m bar: persist it and evaluate higher timeframes."""
        bar_time: datetime = candle["start_time"]

        # Persist the 1m candle
        await self._persist_candle(
            pair=pair,
            timeframe="1m",
            open_=candle["open"],
            high=candle["high"],
            low=candle["low"],
            close=candle["close"],
            volume=candle["volume"],
            bar_time=bar_time,
        )

        # Emit 1m close event
        await self._emit_candle_close(pair, "1m", candle)

        # Update in-memory history for higher-TF aggregation
        history = self._candle_history.setdefault(pair, [])
        history.append(candle)
        # Keep last 500 bars so aggregation always has enough data
        if len(history) > 500:
            self._candle_history[pair] = history[-500:]

        # Evaluate each higher timeframe
        for tf in _DERIVED_TIMEFRAMES:
            if should_close(tf, bar_time):
                await self._close_higher_tf(pair, tf)

    async def _close_higher_tf(self, pair: str, timeframe: str) -> None:
        """Aggregate 1m history and persist+emit the higher-TF closed bar."""
        history = self._candle_history.get(pair, [])
        if not history:
            return

        # Build a 1m DataFrame from the in-memory history
        df = pd.DataFrame(history)
        df["time"] = pd.to_datetime([c["start_time"] for c in history], utc=True)
        df = df.set_index("time")
        df = df[["open", "high", "low", "close", "volume"]]

        try:
            agg = aggregate_candles(df, timeframe)
        except Exception as exc:
            logger.warning(f"Aggregation failed for {pair}/{timeframe}: {exc}")
            return

        if agg.empty:
            return

        # The most recently closed bar is the last row
        last = agg.iloc[-1]
        bar_time = agg.index[-1].to_pydatetime()
        if bar_time.tzinfo is None:
            bar_time = bar_time.replace(tzinfo=timezone.utc)

        candle_dict = {
            "open": float(last["open"]),
            "high": float(last["high"]),
            "low": float(last["low"]),
            "close": float(last["close"]),
            "volume": float(last["volume"]),
            "start_time": bar_time,
        }

        await self._persist_candle(
            pair=pair,
            timeframe=timeframe,
            open_=candle_dict["open"],
            high=candle_dict["high"],
            low=candle_dict["low"],
            close=candle_dict["close"],
            volume=candle_dict["volume"],
            bar_time=bar_time,
        )
        await self._emit_candle_close(pair, timeframe, candle_dict)

    async def _persist_candle(
        self,
        pair: str,
        timeframe: str,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        bar_time: datetime,
        user_id: str = "system",
    ) -> None:
        """Upsert a single candle row into the DB.

        Uses PostgreSQL ``ON CONFLICT DO UPDATE`` so re-processing the same
        bar is idempotent (handles reconnect / replay scenarios).
        """
        if self._db_session_factory is None:
            logger.debug("No DB session factory; skipping candle persistence.")
            return

        try:
            async with self._db_session_factory() as session:
                stmt = pg_insert(Candle).values(
                    time=bar_time,
                    user_id=user_id,
                    pair=pair,
                    timeframe=timeframe,
                    open=Decimal(str(round(open_, 6))),
                    high=Decimal(str(round(high, 6))),
                    low=Decimal(str(round(low, 6))),
                    close=Decimal(str(round(close, 6))),
                    volume=Decimal(str(round(volume, 6))),
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["user_id", "pair", "timeframe", "time"],
                    set_={
                        "open": stmt.excluded.open,
                        "high": stmt.excluded.high,
                        "low": stmt.excluded.low,
                        "close": stmt.excluded.close,
                        "volume": stmt.excluded.volume,
                    },
                )
                await session.execute(stmt)
                await session.commit()
        except Exception as exc:
            logger.error(f"Failed to persist candle {pair}/{timeframe}@{bar_time}: {exc}")

    async def _emit_candle_close(
        self, pair: str, timeframe: str, candle: dict
    ) -> None:
        """Invoke all registered candle-close callbacks."""
        for cb in self._on_candle_close_callbacks:
            try:
                result = cb(pair, timeframe, candle)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.error(f"Candle-close callback error [{pair}/{timeframe}]: {exc}")

    # ------------------------------------------------------------------
    # Bulk load helper (used by backfill)
    # ------------------------------------------------------------------

    async def load_candles_to_history(
        self, pair: str, candles: list[dict]
    ) -> None:
        """Seed the in-memory 1m history from backfilled data.

        Each element must have keys: open, high, low, close, volume, start_time.
        """
        history = self._candle_history.setdefault(pair, [])
        history.extend(candles)
        if len(history) > 500:
            self._candle_history[pair] = history[-500:]
        logger.info(f"Loaded {len(candles)} historical bars for {pair}")


# Module-level singleton
candle_pipeline = CandlePipeline()
