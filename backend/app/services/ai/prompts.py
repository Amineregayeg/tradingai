"""Claude vision prompt templates for chart analysis."""
from __future__ import annotations

VISION_ANALYSIS_SYSTEM = """You are an expert ICT (Inner Circle Trader) and Smart Money Concepts analyst.
Analyze the provided chart screenshot and return a structured JSON analysis.
Focus on: market structure, order blocks, fair value gaps, liquidity sweeps, break of structure.
Always respond in valid JSON matching the specified schema."""


def build_vision_prompt(
    pair: str,
    timeframe: str,
    recent_ict_detections: list[dict],
    open_position: dict | None,
    trade_setup_intent: str | None,
) -> str:
    """Build the user-turn prompt for Claude vision analysis.

    Args:
        pair: Currency pair or instrument (e.g. ``"EUR_USD"``).
        timeframe: Chart timeframe (e.g. ``"1H"``, ``"4H"``).
        recent_ict_detections: List of recent ICT detection dicts (at most the
            first 5 are included to keep the prompt compact).
        open_position: Optional dict describing the currently open position.
        trade_setup_intent: Optional string describing the intended trade setup.

    Returns:
        Formatted prompt string ready to be sent as the user turn.
    """
    context_parts: list[str] = [f"Chart: {pair} {timeframe}"]

    if recent_ict_detections:
        context_parts.append(
            f"Recent ICT detections: {recent_ict_detections[:5]}"
        )
    if open_position:
        context_parts.append(f"Open position: {open_position}")
    if trade_setup_intent:
        context_parts.append(f"Setup intent: {trade_setup_intent}")

    return f"""{chr(10).join(context_parts)}

Analyze this chart and respond with JSON:
{{
  "trend_assessment": "...",
  "trade_bias": "LONG|SHORT|NEUTRAL",
  "key_levels": [{{"price": 0.0, "label": "...", "type": "support|resistance|target|pivot"}}],
  "ict_concepts_found": ["FVG", "OB", "..."],
  "risk_factors": ["..."],
  "confidence": 0.0
}}"""


SCREENING_SYSTEM = "You are a trading setup quality screener. Rate this setup briefly."
