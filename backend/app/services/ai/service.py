"""Central AI service — all Claude API calls flow through here.

Responsibilities:
    * Budget capping (per-user monthly spend)
    * Model selection with automatic downgrade at 95 % spend
    * Circuit breaker integration
    * Image-hash-based caching (skip re-analysis of duplicate screenshots)
    * Persisting AIAnalysis records and updating spend tracking
"""
from __future__ import annotations

import base64
import hashlib
import json
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import anthropic
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AIBudgetExceeded,
    AICircuitOpen,
    AIUnavailable,
)
from app.core.logging import logger
from app.models.ai_analysis import AIAnalysis
from app.models.screenshot import Screenshot
from app.models.settings import UserSettings
from app.services.ai.circuit_breaker import ai_circuit_breaker
from app.services.ai.prompts import VISION_ANALYSIS_SYSTEM, build_vision_prompt

# ---------------------------------------------------------------------------
# Pricing constants (USD per million tokens)
# ---------------------------------------------------------------------------
_PRICING: dict[str, dict[str, float]] = {
    # claude-sonnet-4-6
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    # claude-haiku-4-5 (screening / downgrade model)
    "claude-haiku-4-5": {"input": 0.25, "output": 1.25},
}

# Fallback pricing for unknown models (conservative estimate)
_DEFAULT_PRICING = {"input": 3.0, "output": 15.0}


def _compute_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Return estimated cost in USD for a single Claude API call."""
    pricing = _PRICING.get(model, _DEFAULT_PRICING)
    return (
        prompt_tokens * pricing["input"] / 1_000_000
        + completion_tokens * pricing["output"] / 1_000_000
    )


class AIService:
    """Single entry point for all Claude AI calls.

    Must be initialised via :meth:`init` before use (called at app startup).
    """

    def __init__(self) -> None:
        self._client: anthropic.AsyncAnthropic | None = None
        self._db_factory: Any | None = None

    def init(self, api_key: str, db_factory: Any) -> None:
        """Wire up the Anthropic client and DB session factory.

        Args:
            api_key: Anthropic API key.
            db_factory: Callable that returns an async context-manager yielding
                an :class:`AsyncSession` (typically ``get_session``).
        """
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._db_factory = db_factory

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def analyze_screenshot(
        self,
        db: AsyncSession,
        user_id: str,
        screenshot_id: str,
        image_path: str,
        trade_context: dict,
    ) -> dict:
        """Run a vision analysis on a chart screenshot.

        Pipeline:
        1. Load :class:`UserSettings` — check ai_enabled + budget.
        2. Check circuit breaker.
        3. Select model (downgrade at ≥ 95 % budget spend).
        4. Load image from disk and base64-encode it.
        5. Check image-hash cache in ``ai_analyses``.
        6. Build prompt and call Claude.
        7. Persist :class:`AIAnalysis` and update spend.
        8. Return analysis dict.

        Raises:
            AIUnavailable: ai disabled, circuit open, or upstream error.
            AIBudgetExceeded: monthly budget exhausted.
        """
        # --- 1. Load settings -----------------------------------------------
        settings = await self._load_settings(db, user_id)

        if not settings.ai_enabled:
            raise AIUnavailable(
                "AI is disabled for this user",
                reason=AIUnavailable.REASON_AI_DISABLED,
            )

        # --- 3 & budget check are interleaved --------------------------------
        budget_status = await self.get_budget_status(db, user_id)
        if budget_status["tier"] == "block":
            raise AIBudgetExceeded(
                used_usd=float(budget_status["used_usd"]),
                budget_usd=float(budget_status["budget_usd"]),
            )

        # --- 4. Circuit breaker ---------------------------------------------
        if not ai_circuit_breaker.allow_request():
            raise AICircuitOpen()

        # --- 5. Model selection (auto-downgrade) ----------------------------
        downgraded = False
        if budget_status["tier"] == "downgrade":
            model = settings.ai_screening_model
            downgraded = True
        else:
            model = settings.ai_primary_model

        # --- 6. Load image from disk ----------------------------------------
        image_data, image_hash = self._load_and_hash_image(image_path)

        # --- 7. Cache check -------------------------------------------------
        cached = await self._find_cached_analysis(db, user_id, image_hash)
        if cached is not None:
            logger.info(
                "AI analysis cache hit — skipping API call",
                user_id=user_id,
                screenshot_id=screenshot_id,
                image_hash=image_hash,
            )
            return self._analysis_to_dict(cached)

        # --- 8. Build prompt ------------------------------------------------
        pair = trade_context.get("pair", "UNKNOWN")
        timeframe = trade_context.get("timeframe", "UNKNOWN")
        recent_ict = trade_context.get("recent_ict_detections", [])
        open_position = trade_context.get("open_position")
        setup_intent = trade_context.get("trade_setup_intent")

        user_prompt = build_vision_prompt(
            pair=pair,
            timeframe=timeframe,
            recent_ict_detections=recent_ict,
            open_position=open_position,
            trade_setup_intent=setup_intent,
        )

        # Vision user content block
        user_content: list[dict] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": image_data,
                },
            },
            {"type": "text", "text": user_prompt},
        ]

        # --- 9. Call Claude -------------------------------------------------
        try:
            raw_text, prompt_tokens, completion_tokens, cost_usd = await self._call_claude(
                model=model,
                system=VISION_ANALYSIS_SYSTEM,
                user_content=user_content,
            )
            ai_circuit_breaker.record_success()
        except Exception as exc:
            ai_circuit_breaker.record_failure()
            logger.error(
                "Claude API call failed",
                user_id=user_id,
                error=str(exc),
                model=model,
            )
            raise AIUnavailable(
                "Claude API call failed",
                reason=AIUnavailable.REASON_UPSTREAM_ERROR,
                detail=str(exc),
            ) from exc

        # --- 10. Parse JSON response ----------------------------------------
        analysis_json = self._parse_analysis_json(raw_text)

        # --- 11. Persist AIAnalysis -----------------------------------------
        screenshot_uuid = uuid.UUID(screenshot_id) if isinstance(screenshot_id, str) else screenshot_id
        analysis = AIAnalysis(
            user_id=user_id,
            screenshot_id=screenshot_uuid,
            model=model,
            analysis_json=analysis_json,
            trend_assessment=analysis_json.get("trend_assessment"),
            trade_bias=analysis_json.get("trade_bias"),
            confidence=Decimal(str(analysis_json.get("confidence", 0.0))),
            raw_text=raw_text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=Decimal(str(round(cost_usd, 5))),
            downgraded=downgraded,
        )
        db.add(analysis)

        # --- 12. Update spend -----------------------------------------------
        new_used = float(settings.ai_used_current_month_usd) + cost_usd
        await db.execute(
            update(UserSettings)
            .where(UserSettings.user_id == user_id)
            .values(ai_used_current_month_usd=Decimal(str(round(new_used, 5))))
        )

        await db.commit()
        await db.refresh(analysis)

        logger.info(
            "AI analysis completed",
            user_id=user_id,
            analysis_id=str(analysis.id),
            model=model,
            cost_usd=round(cost_usd, 5),
            downgraded=downgraded,
        )

        return self._analysis_to_dict(analysis)

    async def _call_claude(
        self,
        model: str,
        system: str,
        user_content: list,
        max_tokens: int = 1024,
    ) -> tuple[str, int, int, float]:
        """Execute a Claude API call and return (raw_text, prompt_tokens, completion_tokens, cost_usd).

        Args:
            model: The Claude model identifier.
            system: System prompt string.
            user_content: List of content blocks for the user turn.
            max_tokens: Maximum output tokens.

        Returns:
            Tuple of (raw_text, prompt_tokens, completion_tokens, cost_usd).
        """
        if self._client is None:
            raise RuntimeError("AIService.init() has not been called")

        response = await self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_content}],
        )

        raw_text = "".join(
            block.text for block in response.content if hasattr(block, "text")
        )
        prompt_tokens = response.usage.input_tokens
        completion_tokens = response.usage.output_tokens
        cost_usd = _compute_cost(model, prompt_tokens, completion_tokens)

        return raw_text, prompt_tokens, completion_tokens, cost_usd

    async def is_available(self, db: AsyncSession, user_id: str) -> tuple[bool, str]:
        """Check whether the AI subsystem is available for the given user.

        Returns:
            ``(True, "ok")`` when available, or
            ``(False, reason_string)`` when not.
        """
        try:
            settings = await self._load_settings(db, user_id)
        except Exception:
            return False, "settings_unavailable"

        if not settings.ai_enabled:
            return False, AIUnavailable.REASON_AI_DISABLED

        budget_status = await self.get_budget_status(db, user_id)
        if budget_status["tier"] == "block":
            return False, AIUnavailable.REASON_BUDGET_EXCEEDED

        if not ai_circuit_breaker.allow_request():
            # Restore the state — we were just peeking
            return False, AIUnavailable.REASON_CIRCUIT_OPEN

        return True, "ok"

    async def get_budget_status(self, db: AsyncSession, user_id: str) -> dict:
        """Return current budget status for the user.

        Returns:
            Dict with keys: ``used_usd``, ``budget_usd``, ``pct_used``, ``tier``.

        Budget tiers:
            * ``"ok"``        — < 80 % used
            * ``"warn"``      — 80–95 % used
            * ``"downgrade"`` — 95–99 % used (switch to screening model)
            * ``"block"``     — ≥ 100 % used (raise AIBudgetExceeded)
        """
        settings = await self._load_settings(db, user_id)
        used = float(settings.ai_used_current_month_usd)
        budget = float(settings.ai_monthly_budget_usd)

        if budget <= 0:
            pct = 100.0
        else:
            pct = used / budget * 100.0

        if pct >= 100.0:
            tier = "block"
        elif pct >= 95.0:
            tier = "downgrade"
        elif pct >= 80.0:
            tier = "warn"
        else:
            tier = "ok"

        return {
            "used_usd": round(used, 5),
            "budget_usd": round(budget, 2),
            "pct_used": round(pct, 2),
            "tier": tier,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _load_settings(self, db: AsyncSession, user_id: str) -> UserSettings:
        """Load UserSettings for *user_id*, creating defaults if absent."""
        stmt = select(UserSettings).where(UserSettings.user_id == user_id)
        result = await db.execute(stmt)
        settings = result.scalar_one_or_none()
        if settings is None:
            # Auto-provision default settings for this user
            settings = UserSettings(user_id=user_id)
            db.add(settings)
            await db.commit()
            await db.refresh(settings)
        return settings

    def _load_and_hash_image(self, image_path: str) -> tuple[str, str]:
        """Read an image from disk, base64-encode it, and compute its SHA-256 hash.

        Returns:
            Tuple of (base64_encoded_string, sha256_hex_digest).
        """
        path = Path(image_path)
        raw_bytes = path.read_bytes()
        image_hash = hashlib.sha256(raw_bytes).hexdigest()
        encoded = base64.standard_b64encode(raw_bytes).decode("ascii")
        return encoded, image_hash

    async def _find_cached_analysis(
        self, db: AsyncSession, user_id: str, image_hash: str
    ) -> AIAnalysis | None:
        """Return an existing AIAnalysis for the same image hash, or None."""
        stmt = (
            select(AIAnalysis)
            .join(Screenshot, AIAnalysis.screenshot_id == Screenshot.id)
            .where(
                AIAnalysis.user_id == user_id,
                Screenshot.image_hash == image_hash,
            )
            .order_by(AIAnalysis.created_at.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    def _parse_analysis_json(raw_text: str) -> dict:
        """Extract and parse the JSON object from the Claude response text.

        Handles cases where the model wraps JSON in a markdown code block.
        Falls back to an empty structure on parse failure.
        """
        text = raw_text.strip()

        # Strip markdown fences if present
        if text.startswith("```"):
            lines = text.splitlines()
            # Remove first and last fence lines
            inner_lines = lines[1:]
            if inner_lines and inner_lines[-1].strip().startswith("```"):
                inner_lines = inner_lines[:-1]
            text = "\n".join(inner_lines).strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Failed to parse AI response as JSON", raw_snippet=raw_text[:200])
            return {
                "trend_assessment": raw_text[:500],
                "trade_bias": "NEUTRAL",
                "key_levels": [],
                "ict_concepts_found": [],
                "risk_factors": ["Parse error — see raw_text"],
                "confidence": 0.0,
            }

    @staticmethod
    def _analysis_to_dict(analysis: AIAnalysis) -> dict:
        """Serialise an :class:`AIAnalysis` ORM object to a plain dict."""
        return {
            "id": str(analysis.id),
            "user_id": analysis.user_id,
            "screenshot_id": str(analysis.screenshot_id),
            "model": analysis.model,
            "analysis_json": analysis.analysis_json,
            "trend_assessment": analysis.trend_assessment,
            "trade_bias": analysis.trade_bias,
            "confidence": float(analysis.confidence) if analysis.confidence is not None else None,
            "raw_text": analysis.raw_text,
            "prompt_tokens": analysis.prompt_tokens,
            "completion_tokens": analysis.completion_tokens,
            "cost_usd": float(analysis.cost_usd),
            "downgraded": analysis.downgraded,
            "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
        }


# Module-level singleton — call ai_service.init(...) at startup
ai_service = AIService()
