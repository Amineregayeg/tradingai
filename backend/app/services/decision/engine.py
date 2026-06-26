"""Decision engine — orchestrates candle-close processing.

Gathers state → optionally calls AI → generates alerts → pushes via WebSocket.
"""
from __future__ import annotations

from typing import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.db.enums import AlertStatus, AlertType, ICTStatus
from app.models.alert import Alert
from app.models.ict_detection import ICTDetection
from app.models.scoring_profile import ScoringProfile
from app.models.settings import UserSettings
from app.services.decision.alerts import (
    expire_old_alerts,
    generate_entry_signal_alert,
    generate_exit_mgmt_alert,
    generate_risk_warning,
)
from app.services.decision.scoring import compute_score


class DecisionEngine:
    """Main pipeline controller, called once per candle close.

    Usage::

        decision_engine.register_alert_callback(ws_push_fn)
        await decision_engine.on_candle_close(pair, timeframe, candle, db, user_id)
    """

    def __init__(self) -> None:
        self._ws_alert_callback: Callable | None = None

    def register_alert_callback(self, callback: Callable) -> None:
        """Register a callable that receives new alert dicts for WebSocket push.

        Args:
            callback: ``async`` or sync callable accepting a single dict.
        """
        self._ws_alert_callback = callback

    # ------------------------------------------------------------------
    # Main pipeline
    # ------------------------------------------------------------------

    async def on_candle_close(
        self,
        pair: str,
        timeframe: str,
        candle: dict,
        db: AsyncSession,
        user_id: str = "system",
    ) -> None:
        """Process a candle-close event and generate alerts as required.

        Pipeline:
        1.  Expire stale PENDING alerts.
        2.  Load active ICT detections for *pair* + *timeframe* (last 10).
        3.  Extract indicators from *candle* (or a Redis cache in the future).
        4.  Load the active scoring profile.
        5.  Load UserSettings.
        6.  Compute trade score via :func:`~.scoring.compute_score`.
        7.  Check for active HALTED compliance state (skip entry signals).
        8.  Generate entry-signal alert when score ≥ threshold.
        9.  Check for blackout periods and generate risk-warning alerts.
        10. Check open positions for exit-management triggers (≥ 1.5 R).
        11. Push new alerts via the registered WebSocket callback.

        Args:
            pair: Instrument (e.g. ``"EUR_USD"``).
            timeframe: Candle timeframe (e.g. ``"1H"``).
            candle: Dict with OHLCV data and optional indicator values.
            db: SQLAlchemy async session.
            user_id: User to scope all DB operations.
        """
        new_alerts: list[dict] = []

        # 1. Expire old alerts -----------------------------------------------
        try:
            await expire_old_alerts(db, user_id)
        except Exception as exc:
            logger.warning("Failed to expire old alerts", error=str(exc))

        # 2. Load active ICT detections --------------------------------------
        ict_detections = await self._load_ict_detections(db, user_id, pair, timeframe, limit=10)

        # 3. Extract indicators from candle ----------------------------------
        indicators = self._extract_indicators(candle)

        # 4. Load active scoring profile ------------------------------------
        scoring_profile_dict = await self._load_scoring_profile(db, user_id)

        # 5. Load UserSettings -----------------------------------------------
        settings = await self._load_settings(db, user_id)

        # 6. Determine HTF direction (placeholder — Phase 2 from HTF candles) -
        htf_direction: str | None = candle.get("htf_direction")

        # Determine setup direction from candle or ICT consensus
        setup_direction = self._infer_setup_direction(ict_detections, candle)

        # 7. Compute score ---------------------------------------------------
        score = compute_score(
            ict_detections=ict_detections,
            indicators=indicators,
            scoring_profile=scoring_profile_dict,
            htf_direction=htf_direction,
            setup_direction=setup_direction,
        )

        logger.debug(
            "Score computed",
            user_id=user_id,
            pair=pair,
            timeframe=timeframe,
            score=round(score, 2),
            setup_direction=setup_direction,
        )

        # 8. Entry signal ----------------------------------------------------
        halted = candle.get("compliance_halted", False)
        if not halted:
            context = {
                "pair": pair,
                "timeframe": timeframe,
                "candle": {
                    "open": candle.get("open"),
                    "high": candle.get("high"),
                    "low": candle.get("low"),
                    "close": candle.get("close"),
                    "timestamp": candle.get("timestamp"),
                },
                "setup_direction": setup_direction,
                "htf_direction": htf_direction,
            }
            try:
                alert_dict = await generate_entry_signal_alert(
                    db=db,
                    user_id=user_id,
                    pair=pair,
                    score=score,
                    ict_detections=ict_detections,
                    indicators=indicators,
                    ai_confidence=candle.get("ai_confidence"),
                    context=context,
                )
                if alert_dict:
                    new_alerts.append(alert_dict)
            except Exception as exc:
                logger.error("Failed to generate entry signal alert", error=str(exc), pair=pair)

        # 9. Blackout / risk warnings ----------------------------------------
        if candle.get("news_blackout"):
            try:
                warning = await generate_risk_warning(
                    db=db,
                    user_id=user_id,
                    pair=pair,
                    reason="High-impact news event imminent — trading suspended",
                    context={"pair": pair, "timeframe": timeframe},
                )
                new_alerts.append(warning)
            except Exception as exc:
                logger.error("Failed to generate risk warning", error=str(exc))

        # 10. Exit management ------------------------------------------------
        open_positions = candle.get("open_positions", [])
        for position in open_positions:
            try:
                r_multiple = float(position.get("r_multiple", 0.0))
                if r_multiple >= 1.5:
                    exit_alert = await generate_exit_mgmt_alert(
                        db=db,
                        user_id=user_id,
                        pair=pair,
                        r_multiple=r_multiple,
                        suggested_action={
                            "action": "partial_close",
                            "r_multiple": r_multiple,
                            "position_id": position.get("id"),
                            "pair": pair,
                        },
                        context={"position": position, "pair": pair, "timeframe": timeframe},
                    )
                    new_alerts.append(exit_alert)
            except Exception as exc:
                logger.error("Failed to generate exit mgmt alert", error=str(exc))

        # 11. Push alerts via WebSocket ----------------------------------------
        if self._ws_alert_callback and new_alerts:
            for alert_dict in new_alerts:
                try:
                    result = self._ws_alert_callback(alert_dict)
                    # Support both sync and async callbacks
                    if hasattr(result, "__await__"):
                        import asyncio  # noqa: PLC0415
                        asyncio.create_task(result)
                except Exception as exc:
                    logger.warning("WebSocket alert push failed", error=str(exc))

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _load_ict_detections(
        self, db: AsyncSession, user_id: str, pair: str, timeframe: str, limit: int = 10
    ) -> list[dict]:
        """Load recent ACTIVE ICT detections and serialise to dicts."""
        stmt = (
            select(ICTDetection)
            .where(
                ICTDetection.user_id == user_id,
                ICTDetection.pair == pair,
                ICTDetection.timeframe == timeframe,
                ICTDetection.status == ICTStatus.ACTIVE,
            )
            .order_by(ICTDetection.detected_at.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()

        return [
            {
                "id": str(row.id),
                "detection_type": row.detection_type.value,
                "direction": row.direction.value,
                "confidence": float(row.confidence),
                "strength": float(row.strength),
                "candle_index": row.candle_index,
                "detected_at": row.detected_at.isoformat(),
                "price_high": float(row.price_high),
                "price_low": float(row.price_low),
            }
            for row in rows
        ]

    async def _load_scoring_profile(self, db: AsyncSession, user_id: str) -> dict:
        """Return the active scoring profile as a dict, or sensible defaults."""
        stmt = (
            select(ScoringProfile)
            .where(
                ScoringProfile.user_id == user_id,
                ScoringProfile.active.is_(True),
            )
            .limit(1)
        )
        result = await db.execute(stmt)
        profile = result.scalar_one_or_none()

        if profile is None:
            return {
                "ict_weight": 0.4,
                "ta_weight": 0.35,
                "price_action_weight": 0.25,
                "mtf_bonus": 0.1,
                "min_score_entry": 65.0,
            }

        return {
            "ict_weight": float(profile.ict_weight),
            "ta_weight": float(profile.ta_weight),
            "price_action_weight": float(profile.price_action_weight),
            "mtf_bonus": float(profile.mtf_bonus),
            "min_score_entry": float(profile.min_score_entry),
        }

    async def _load_settings(self, db: AsyncSession, user_id: str) -> UserSettings:
        """Load UserSettings, creating defaults if absent."""
        stmt = select(UserSettings).where(UserSettings.user_id == user_id)
        result = await db.execute(stmt)
        settings = result.scalar_one_or_none()
        if settings is None:
            settings = UserSettings(user_id=user_id)
            db.add(settings)
            await db.commit()
            await db.refresh(settings)
        return settings

    @staticmethod
    def _extract_indicators(candle: dict) -> dict:
        """Extract indicator values from the candle dict.

        Falls back to neutral values when a key is missing so that
        :func:`~.scoring.compute_score` always receives a complete dict.
        """
        return {
            "rsi_14": candle.get("rsi_14", 50.0),
            "ema_21": candle.get("ema_21"),
            "ema_50": candle.get("ema_50"),
            "ema_200": candle.get("ema_200"),
            "atr_14": candle.get("atr_14"),
            "macd_histogram": candle.get("macd_histogram", 0.0),
            "ema_stack": candle.get("ema_stack", ""),
        }

    @staticmethod
    def _infer_setup_direction(ict_detections: list[dict], candle: dict) -> str:
        """Infer trade direction from ICT detections, falling back to candle context.

        Priority:
        1. Explicit ``"setup_direction"`` key in *candle*.
        2. Majority direction among ICT detections.
        3. Default ``"LONG"``.
        """
        explicit = candle.get("setup_direction", "")
        if explicit.upper() in ("LONG", "SHORT"):
            return explicit.upper()

        if not ict_detections:
            return "LONG"

        bulls = sum(1 for d in ict_detections if d.get("direction", "").upper() == "BULL")
        bears = len(ict_detections) - bulls
        return "LONG" if bulls >= bears else "SHORT"


# Module-level singleton
decision_engine = DecisionEngine()
