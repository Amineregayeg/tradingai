"""ICT detection engine using the smartmoneyconcepts library."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.db.enums import ICTDir, ICTStatus, ICTType
from app.models.ict_detection import ICTDetection

# Dynamically import smartmoneyconcepts to surface a clear error if missing
try:
    from smartmoneyconcepts import smc  # type: ignore[import-untyped]

    _SMC_AVAILABLE = True
except ImportError:
    _SMC_AVAILABLE = False
    logger.warning("smartmoneyconcepts not installed; ICT detection will be limited.")

# How many candles before an ACTIVE detection is considered EXPIRED
_EXPIRY_CANDLES = 200

# Minimum number of candles required to run detections
_MIN_CANDLES = 20

# Swing lookback for smc.swing_highs_lows. The smc OB / BOS-CHoCH / liquidity
# detectors all require a precomputed swing-highs/lows Series as their second
# argument; omitting it raises TypeError (the original bug that made OB,
# BOS/CHoCH and the SMC liquidity path silently return nothing).
#
# CALIBRATION KNOB: empirically on BTC/ETH 1H–4H (500 bars), length 50 yields
# ~5 swings (almost no structure) while length ~5–10 yields rich, tradeable
# structure. 10 is a balanced default; tune per-timeframe during M6 calibration.
_SWING_LENGTH = 10


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Convert a potentially NaN / None value to float."""
    try:
        f = float(val)
        return default if np.isnan(f) else f
    except (TypeError, ValueError):
        return default


def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure the dataframe has the expected column dtypes for SMC library."""
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = df[col].astype(float)
    return df.reset_index(drop=True)


class ICTDetector:
    """Run ICT pattern detections on a sliding window of candles.

    Usage
    -----
    Register the detector's ``on_candle_close`` as a callback on
    ``CandlePipeline`` so it is called after every candle:

    .. code-block:: python

        candle_pipeline.on_candle_close(ict_detector.on_candle_close_callback)

    Internally the detector fetches the last ``_MIN_CANDLES`` (up to 500)
    bars from the DB and runs all detection algorithms on them.
    """

    def __init__(self) -> None:
        self._ws_callbacks: list[Callable] = []
        self._db_session_factory: Callable | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def register_ws_callback(self, callback: Callable) -> None:
        """Register a WebSocket push callback called with each new detection dict."""
        self._ws_callbacks.append(callback)

    async def detect_all(
        self,
        db: AsyncSession,
        user_id: str,
        pair: str,
        timeframe: str,
        candles_df: pd.DataFrame,
    ) -> list[dict]:
        """Run all ICT detections on *candles_df* and persist new findings.

        Args:
            db: Async SQLAlchemy session.
            user_id: Owner of the detections.
            pair: Instrument symbol (e.g. ``"EURUSD"``).
            timeframe: Bar timeframe (e.g. ``"1H"``).
            candles_df: DataFrame with columns [time, open, high, low, close, volume],
                        at most 500 bars, sorted ascending.

        Returns:
            List of newly created detection dicts.
        """
        if len(candles_df) < _MIN_CANDLES:
            logger.debug(
                f"Skipping ICT detection for {pair}/{timeframe}: "
                f"only {len(candles_df)} candles (need {_MIN_CANDLES})"
            )
            return []

        df = _normalize_df(candles_df.copy())
        current_price = _safe_float(df["close"].iloc[-1])
        current_index = len(df) - 1

        # Mark mitigated / expired before running new detections
        await self._mark_mitigated(db, user_id, pair, timeframe, current_price)
        await self._expire_old(db, user_id, pair, timeframe, current_index)

        all_detections: list[dict] = []

        # Precompute the swing-highs/lows Series once; the smc OB / BOS-CHoCH /
        # liquidity detectors all require it. If it cannot be computed, those
        # detectors degrade gracefully (OB/BOS -> [], liquidity -> manual).
        swing = self._compute_swing(df)

        # (fn, needs_swing)
        detection_fns = [
            (self.detect_order_blocks, True),
            (self.detect_fvg, False),
            (self.detect_bos_choch, True),
            (self.detect_liquidity, True),
            (self.detect_sd_zones, False),
        ]

        for fn, needs_swing in detection_fns:
            try:
                results = fn(df, swing) if needs_swing else fn(df)
                all_detections.extend(results)
            except Exception as exc:
                logger.warning(
                    f"Detection fn {fn.__name__} failed for {pair}/{timeframe}: {exc}"
                )

        # Deduplicate against existing ACTIVE detections before persisting
        new_detections: list[dict] = []
        for det in all_detections:
            if await self._is_duplicate(db, user_id, pair, timeframe, det):
                continue

            det_row = await self._persist_detection(db, user_id, pair, timeframe, det)
            if det_row is not None:
                new_detections.append(det_row)
                await self._push_ws(det_row)

        if new_detections:
            logger.info(
                f"ICT: {len(new_detections)} new detections for {pair}/{timeframe}"
            )

        return new_detections

    # ------------------------------------------------------------------
    # Detection algorithms
    # ------------------------------------------------------------------

    def _compute_swing(
        self, df: pd.DataFrame, swing_length: int = _SWING_LENGTH
    ) -> pd.DataFrame | None:
        """Compute the swing-highs/lows Series required by the smc detectors.

        ``swing_length`` MUST match the lag any caller applies for no-lookahead
        backtests (the swing at bar k is only confirmable ~swing_length bars
        later). Returns ``None`` if smc is unavailable or the computation fails.
        """
        if not _SMC_AVAILABLE:
            return None
        try:
            return smc.swing_highs_lows(df, swing_length=swing_length)
        except Exception as exc:
            logger.warning(f"smc.swing_highs_lows failed: {exc}")
            return None

    def detect_order_blocks(
        self, df: pd.DataFrame, swing: pd.DataFrame | None = None
    ) -> list[dict]:
        """Detect bullish and bearish order blocks using SMC library."""
        if not _SMC_AVAILABLE:
            return []
        if swing is None:
            swing = self._compute_swing(df)
        if swing is None:
            return []

        try:
            ob_df: pd.DataFrame = smc.ob(df, swing)
        except Exception as exc:
            logger.debug(f"smc.ob failed: {exc}")
            return []

        results = []
        for i, row in ob_df.iterrows():
            # SMC returns NaN rows for non-OB candles
            ob_val = row.get("OB", np.nan)
            if pd.isna(ob_val) or ob_val == 0:
                continue

            direction = ICTDir.BULL if ob_val > 0 else ICTDir.BEAR

            top = _safe_float(row.get("Top", df["high"].iloc[int(i)]))
            bottom = _safe_float(row.get("Bottom", df["low"].iloc[int(i)]))
            # Impulse strength → confidence (normalised 0–1)
            impulse = abs(_safe_float(row.get("OBVolume", 1.0)))
            max_impulse = df["volume"].max()
            confidence = min(impulse / max_impulse, 1.0) if max_impulse > 0 else 0.5

            # Strength: price range relative to ATR proxy
            price_range = top - bottom
            atr_proxy = (df["high"] - df["low"]).mean()
            strength = min(price_range / atr_proxy, 1.0) if atr_proxy > 0 else 0.5

            results.append(
                {
                    "detection_type": ICTType.OB,
                    "direction": direction,
                    "price_high": top,
                    "price_low": bottom,
                    "confidence": round(confidence, 3),
                    "strength": round(strength, 3),
                    "candle_index": int(i),
                }
            )

        return results

    def detect_fvg(self, df: pd.DataFrame) -> list[dict]:
        """Detect Fair Value Gaps (3-candle imbalance pattern)."""
        if not _SMC_AVAILABLE:
            return self._detect_fvg_manual(df)

        try:
            fvg_df: pd.DataFrame = smc.fvg(df)
        except Exception as exc:
            logger.debug(f"smc.fvg failed: {exc}, falling back to manual")
            return self._detect_fvg_manual(df)

        results = []
        for i, row in fvg_df.iterrows():
            fvg_val = row.get("FVG", np.nan)
            if pd.isna(fvg_val) or fvg_val == 0:
                continue

            direction = ICTDir.BULL if fvg_val > 0 else ICTDir.BEAR
            top = _safe_float(row.get("Top", np.nan))
            bottom = _safe_float(row.get("Bottom", np.nan))

            if top == 0.0 and bottom == 0.0:
                continue

            gap_size = top - bottom
            atr_proxy = (df["high"] - df["low"]).mean()
            confidence = min(gap_size / atr_proxy, 1.0) if atr_proxy > 0 else 0.5

            results.append(
                {
                    "detection_type": ICTType.FVG,
                    "direction": direction,
                    "price_high": top,
                    "price_low": bottom,
                    "confidence": round(confidence, 3),
                    "strength": round(min(gap_size / atr_proxy * 0.5, 1.0) if atr_proxy > 0 else 0.5, 3),
                    "candle_index": int(i),
                }
            )

        return results

    def _detect_fvg_manual(self, df: pd.DataFrame) -> list[dict]:
        """Manual 3-candle FVG detection fallback."""
        results = []
        for i in range(2, len(df)):
            c0_high = _safe_float(df["high"].iloc[i - 2])
            c0_low = _safe_float(df["low"].iloc[i - 2])
            c2_high = _safe_float(df["high"].iloc[i])
            c2_low = _safe_float(df["low"].iloc[i])

            atr_proxy = (df["high"] - df["low"]).mean()

            # Bullish FVG: candle[0].high < candle[2].low
            if c0_high < c2_low:
                gap = c2_low - c0_high
                confidence = min(gap / atr_proxy, 1.0) if atr_proxy > 0 else 0.5
                results.append(
                    {
                        "detection_type": ICTType.FVG,
                        "direction": ICTDir.BULL,
                        "price_high": c2_low,
                        "price_low": c0_high,
                        "confidence": round(confidence, 3),
                        "strength": round(min(gap / atr_proxy * 0.5, 1.0) if atr_proxy > 0 else 0.5, 3),
                        "candle_index": i,
                    }
                )

            # Bearish FVG: candle[0].low > candle[2].high
            elif c0_low > c2_high:
                gap = c0_low - c2_high
                confidence = min(gap / atr_proxy, 1.0) if atr_proxy > 0 else 0.5
                results.append(
                    {
                        "detection_type": ICTType.FVG,
                        "direction": ICTDir.BEAR,
                        "price_high": c0_low,
                        "price_low": c2_high,
                        "confidence": round(confidence, 3),
                        "strength": round(min(gap / atr_proxy * 0.5, 1.0) if atr_proxy > 0 else 0.5, 3),
                        "candle_index": i,
                    }
                )

        return results

    def detect_bos_choch(
        self, df: pd.DataFrame, swing: pd.DataFrame | None = None
    ) -> list[dict]:
        """Detect Break of Structure and Change of Character."""
        if not _SMC_AVAILABLE:
            return []
        if swing is None:
            swing = self._compute_swing(df)
        if swing is None:
            return []

        try:
            bos_df: pd.DataFrame = smc.bos_choch(df, swing)
        except Exception as exc:
            logger.debug(f"smc.bos_choch failed: {exc}")
            return []

        results = []
        for i, row in bos_df.iterrows():
            bos_val = row.get("BOS", np.nan)
            choch_val = row.get("CHOCH", np.nan)

            for signal_val, det_type in [(bos_val, ICTType.BOS), (choch_val, ICTType.CHOCH)]:
                if pd.isna(signal_val) or signal_val == 0:
                    continue

                direction = ICTDir.BULL if signal_val > 0 else ICTDir.BEAR
                level = _safe_float(row.get("Level", df["close"].iloc[int(i)]))

                # BOS/CHoCH are point signals; use a small band around the level
                atr_proxy = (df["high"] - df["low"]).mean()
                band = atr_proxy * 0.1

                # The break is only CONFIRMED at BrokenIndex (smc), which lands
                # 15-35 bars after formation — critical for no-lookahead backtests.
                bi_raw = row.get("BrokenIndex", np.nan)
                broken_index = int(bi_raw) if pd.notna(bi_raw) else None

                results.append(
                    {
                        "detection_type": det_type,
                        "direction": direction,
                        "price_high": level + band,
                        "price_low": level - band,
                        "confidence": 0.8,
                        "strength": 0.75,
                        "candle_index": int(i),
                        "broken_index": broken_index,
                    }
                )

        return results

    def detect_liquidity(
        self, df: pd.DataFrame, swing: pd.DataFrame | None = None
    ) -> list[dict]:
        """Detect liquidity pools and sweeps (equal highs/lows, wick grabs)."""
        if not _SMC_AVAILABLE:
            return self._detect_liquidity_manual(df)
        if swing is None:
            swing = self._compute_swing(df)
        if swing is None:
            return self._detect_liquidity_manual(df)

        try:
            liq_df: pd.DataFrame = smc.liquidity(df, swing)
        except Exception as exc:
            logger.debug(f"smc.liquidity failed: {exc}, falling back to manual")
            return self._detect_liquidity_manual(df)

        results = []
        for i, row in liq_df.iterrows():
            liq_val = row.get("Liquidity", np.nan)
            if pd.isna(liq_val) or liq_val == 0:
                continue

            direction = ICTDir.BULL if liq_val > 0 else ICTDir.BEAR
            level = _safe_float(row.get("Level", np.nan))
            if level == 0.0:
                continue

            atr_proxy = (df["high"] - df["low"]).mean()
            band = atr_proxy * 0.05

            swept = row.get("Swept", False)
            confidence = 0.9 if swept else 0.6

            results.append(
                {
                    "detection_type": ICTType.LIQ,
                    "direction": direction,
                    "price_high": level + band,
                    "price_low": level - band,
                    "confidence": round(confidence, 3),
                    "strength": round(min(atr_proxy / level * 10, 1.0) if level > 0 else 0.5, 3),
                    "candle_index": int(i),
                }
            )

        return results

    def _detect_liquidity_manual(self, df: pd.DataFrame) -> list[dict]:
        """Manual swing-high / swing-low liquidity pool detection."""
        results = []
        lookback = 5

        for i in range(lookback, len(df) - 1):
            high_i = _safe_float(df["high"].iloc[i])
            low_i = _safe_float(df["low"].iloc[i])
            atr_proxy = (df["high"] - df["low"]).mean()
            band = atr_proxy * 0.05

            # Swing high: higher than surroundings
            surrounding_highs = df["high"].iloc[i - lookback : i].tolist() + df["high"].iloc[i + 1 : i + lookback + 1].tolist()
            if surrounding_highs and high_i == max(surrounding_highs + [high_i]):
                results.append(
                    {
                        "detection_type": ICTType.LIQ,
                        "direction": ICTDir.BEAR,
                        "price_high": high_i + band,
                        "price_low": high_i - band,
                        "confidence": 0.6,
                        "strength": 0.5,
                        "candle_index": i,
                    }
                )

            # Swing low: lower than surroundings
            surrounding_lows = df["low"].iloc[i - lookback : i].tolist() + df["low"].iloc[i + 1 : i + lookback + 1].tolist()
            if surrounding_lows and low_i == min(surrounding_lows + [low_i]):
                results.append(
                    {
                        "detection_type": ICTType.LIQ,
                        "direction": ICTDir.BULL,
                        "price_high": low_i + band,
                        "price_low": low_i - band,
                        "confidence": 0.6,
                        "strength": 0.5,
                        "candle_index": i,
                    }
                )

        return results

    def detect_sd_zones(self, df: pd.DataFrame) -> list[dict]:
        """Detect Supply / Demand zones (consolidation before strong move)."""
        results = []

        # Simple volume-weighted approach:
        # Find clusters where volume is below the 30th percentile (consolidation),
        # then check if a strong impulse candle (body > 1.5× ATR) follows.
        if len(df) < 10:
            return []

        volume_series = df["volume"].astype(float)
        vol_30th = float(volume_series.quantile(0.30))
        atr = float((df["high"] - df["low"]).astype(float).mean())
        if atr == 0:
            return []

        i = 5
        while i < len(df) - 1:
            # Detect consolidation window (low volume)
            if float(volume_series.iloc[i]) <= vol_30th:
                j = i
                while j < len(df) - 1 and float(volume_series.iloc[j]) <= vol_30th:
                    j += 1

                if j >= len(df) - 1:
                    break

                # j is the impulse candle
                body = abs(float(df["close"].iloc[j]) - float(df["open"].iloc[j]))
                if body > atr * 1.5:
                    zone_high = float(df["high"].iloc[i:j].max())
                    zone_low = float(df["low"].iloc[i:j].min())

                    if float(df["close"].iloc[j]) > float(df["open"].iloc[j]):
                        direction = ICTDir.BULL  # Demand zone
                    else:
                        direction = ICTDir.BEAR  # Supply zone

                    impulse_strength = min(body / atr, 1.0)
                    results.append(
                        {
                            "detection_type": ICTType.SD_ZONE,
                            "direction": direction,
                            "price_high": zone_high,
                            "price_low": zone_low,
                            "confidence": round(impulse_strength * 0.85, 3),
                            "strength": round(impulse_strength, 3),
                            "candle_index": j,
                        }
                    )

                i = j + 1
            else:
                i += 1

        return results

    # ------------------------------------------------------------------
    # Lifecycle management
    # ------------------------------------------------------------------

    async def _mark_mitigated(
        self,
        db: AsyncSession,
        user_id: str,
        pair: str,
        timeframe: str,
        current_price: float,
    ) -> None:
        """Flip ACTIVE OB/FVG/LIQ/SD_ZONE detections to MITIGATED when price enters+exits zone."""
        now = datetime.now(tz=timezone.utc)

        stmt = select(ICTDetection).where(
            ICTDetection.user_id == user_id,
            ICTDetection.pair == pair,
            ICTDetection.timeframe == timeframe,
            ICTDetection.status == ICTStatus.ACTIVE,
        )
        result = await db.execute(stmt)
        active: list[ICTDetection] = list(result.scalars().all())

        for det in active:
            ph = float(det.price_high)
            pl = float(det.price_low)

            # Zone is considered mitigated when price closes through it
            if pl <= current_price <= ph:
                det.status = ICTStatus.MITIGATED
                det.mitigated_at = now
                db.add(det)

        if active:
            await db.commit()

    async def _expire_old(
        self,
        db: AsyncSession,
        user_id: str,
        pair: str,
        timeframe: str,
        current_candle_index: int,
    ) -> None:
        """Mark ACTIVE detections older than _EXPIRY_CANDLES as EXPIRED."""
        # We use candle_index stored at detection time; detections formed at
        # (current_candle_index - _EXPIRY_CANDLES) or earlier are expired.
        threshold_index = current_candle_index - _EXPIRY_CANDLES
        if threshold_index <= 0:
            return

        stmt = select(ICTDetection).where(
            ICTDetection.user_id == user_id,
            ICTDetection.pair == pair,
            ICTDetection.timeframe == timeframe,
            ICTDetection.status == ICTStatus.ACTIVE,
            ICTDetection.candle_index <= threshold_index,
        )
        result = await db.execute(stmt)
        old: list[ICTDetection] = list(result.scalars().all())

        for det in old:
            det.status = ICTStatus.EXPIRED
            db.add(det)

        if old:
            await db.commit()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    async def _is_duplicate(
        self,
        db: AsyncSession,
        user_id: str,
        pair: str,
        timeframe: str,
        det: dict,
    ) -> bool:
        """Return True if an equivalent ACTIVE detection already exists in the DB."""
        ph = Decimal(str(round(det["price_high"], 6)))
        pl = Decimal(str(round(det["price_low"], 6)))

        stmt = select(ICTDetection).where(
            ICTDetection.user_id == user_id,
            ICTDetection.pair == pair,
            ICTDetection.timeframe == timeframe,
            ICTDetection.detection_type == det["detection_type"],
            ICTDetection.direction == det["direction"],
            ICTDetection.price_high == ph,
            ICTDetection.price_low == pl,
            ICTDetection.status == ICTStatus.ACTIVE,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def _persist_detection(
        self,
        db: AsyncSession,
        user_id: str,
        pair: str,
        timeframe: str,
        det: dict,
    ) -> dict | None:
        """Insert a new ICTDetection row and return its dict representation."""
        now = datetime.now(tz=timezone.utc)
        try:
            row = ICTDetection(
                id=uuid.uuid4(),
                user_id=user_id,
                pair=pair,
                timeframe=timeframe,
                detection_type=det["detection_type"],
                direction=det["direction"],
                price_high=Decimal(str(round(det["price_high"], 6))),
                price_low=Decimal(str(round(det["price_low"], 6))),
                confidence=Decimal(str(round(det["confidence"], 3))),
                strength=Decimal(str(round(det["strength"], 3))),
                candle_index=det["candle_index"],
                status=ICTStatus.ACTIVE,
                detected_at=now,
                mitigated_at=None,
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
        except Exception as exc:
            await db.rollback()
            logger.error(f"Failed to persist ICT detection: {exc}")
            return None

        return {
            "id": str(row.id),
            "user_id": row.user_id,
            "pair": row.pair,
            "timeframe": row.timeframe,
            "detection_type": row.detection_type.value,
            "direction": row.direction.value,
            "price_high": float(row.price_high),
            "price_low": float(row.price_low),
            "confidence": float(row.confidence),
            "strength": float(row.strength),
            "candle_index": row.candle_index,
            "status": row.status.value,
            "detected_at": row.detected_at.isoformat(),
        }

    async def _push_ws(self, detection_dict: dict) -> None:
        """Push a new detection to all registered WebSocket callbacks."""
        import asyncio

        for cb in self._ws_callbacks:
            try:
                result = cb(detection_dict)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.error(f"WS push error for ICT detection: {exc}")

    # ------------------------------------------------------------------
    # Convenience callback for CandlePipeline integration
    # ------------------------------------------------------------------

    async def on_candle_close_callback(
        self,
        pair: str,
        timeframe: str,
        candle: dict,
    ) -> None:
        """Adapter matching the CandlePipeline.on_candle_close signature.

        Fetches the last 500 candles from the DB and runs detections.
        Must call ``set_db_session_factory`` first.
        """
        if self._db_session_factory is None:
            return

        from app.models.candle import Candle as CandleModel

        try:
            async with self._db_session_factory() as db:
                stmt = (
                    select(CandleModel)
                    .where(
                        CandleModel.pair == pair,
                        CandleModel.timeframe == timeframe,
                    )
                    .order_by(CandleModel.time.desc())
                    .limit(500)
                )
                result = await db.execute(stmt)
                rows = list(reversed(result.scalars().all()))

                if len(rows) < _MIN_CANDLES:
                    return

                df = pd.DataFrame(
                    {
                        "time": [r.time for r in rows],
                        "open": [float(r.open) for r in rows],
                        "high": [float(r.high) for r in rows],
                        "low": [float(r.low) for r in rows],
                        "close": [float(r.close) for r in rows],
                        "volume": [float(r.volume) for r in rows],
                    }
                )

                # Use first user_id found (single-user context)
                user_id = getattr(rows[0], "user_id", "system")
                await self.detect_all(db, user_id, pair, timeframe, df)
        except Exception as exc:
            logger.error(
                f"ICT on_candle_close_callback error [{pair}/{timeframe}]: {exc}"
            )

    def set_db_session_factory(self, factory: Callable) -> None:
        self._db_session_factory = factory


# Module-level singleton
ict_detector = ICTDetector()
