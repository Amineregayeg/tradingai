"""Evaluation services — the output-understanding / feedback loop.

Exposes CONTRACT 5's pure feedback engine: given closed decision records and the
current knob values, it reports expected-vs-actual gaps and emits small, bounded,
evidence-backed corrections on the engine's INDEPENDENT knobs only (never risk_pct).
"""

from app.services.evaluation.feedback import (
    FIXED_KNOBS,
    INDEPENDENT_KNOBS,
    MAX_DELTA_FRAC,
    RISK_PCT_REFUSAL,
    Correction,
    RiskPctTuningRefused,
    analyze,
    propose_correction,
)

__all__ = [
    "analyze",
    "propose_correction",
    "Correction",
    "RiskPctTuningRefused",
    "INDEPENDENT_KNOBS",
    "FIXED_KNOBS",
    "MAX_DELTA_FRAC",
    "RISK_PCT_REFUSAL",
]
