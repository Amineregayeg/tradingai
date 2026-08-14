"""GATE-017 / GATE-019 — the trading envelope: which timeframes may trigger (T-0012).

GATE-017, from the registry:

    M/W/D/4H/2H/1H are ANALYSIS ONLY. "No trades are opened from these timeframes." LTFs
    are execution only and "do not redefine the higher-timeframe destination unless the
    higher-timeframe strategic analysis itself changes."
    Any order whose triggering signal was detected on an HTF series is a violation,
    testable from telemetry.

GATE-019:

    The engine operates in day-trading mode, not swing. HTFs = Analysis only, LTFs =
    Execution only. Consequence: the session/timing gates are UNCONDITIONAL — the "only
    when day trading / swing traders don't need sessions" qualifier no longer has a false
    branch.
    inputs: n/a — a mode constant.

THE HTF SET IS ENUMERATED, NEVER INFERRED FROM MAGNITUDE
Comparing durations would make `2H` and `120m` different answers to the same question, and
this repo has already paid for that twice: `gate_008_roster.py` compares timeframe STRINGS,
and `shadow.py`'s `schema_tf()` exists solely because the data layer keys lowercase while
the schema enum is uppercase (B33). So the set below is the statement's own list, and
matching is done on a normalised spelling rather than on a parsed duration.

WHY THIS RULE WILL NEVER FAIL ON LIVE DATA
T-0007 moved the engine to `ENTRY_TF = "5m"`, so every live bar and every historical record
passes. **A gate that has only ever passed is indistinguishable from a gate that cannot
fail**, so its entire proof is a synthetic HTF fixture driven in both directions.
"""
from __future__ import annotations

from typing import Any

from app.services.rules.base import RuleImplementation
from app.services.telemetry.records import RuleEvaluation, derived, from_record

#: The statement's own list, verbatim. NOT derived by comparing durations.
ANALYSIS_ONLY_TFS: frozenset[str] = frozenset({"M", "W", "D", "4H", "2H", "1H"})

#: Spellings this codebase actually uses for the same timeframes. The engine keys
#: lowercase (`"1h"`), the schema uppercase (`"1H"`), and `fixed_config.BIAS_TF` is a bare
#: `"D"`. One normaliser, so a violation cannot hide behind a case difference.
_ALIASES: dict[str, str] = {
    "1mo": "M", "mo": "M", "1w": "W", "1d": "D",
    "1h": "1H", "2h": "2H", "4h": "4H",
}


def normalise_tf(tf: str) -> str:
    """Fold a timeframe spelling to the statement's vocabulary."""
    raw = tf.strip()
    lowered = raw.lower()
    if lowered in _ALIASES:
        return _ALIASES[lowered]
    upper = raw.upper()
    return upper if upper in ANALYSIS_ONLY_TFS else raw


def is_analysis_only(tf: str) -> bool:
    return normalise_tf(tf) in ANALYSIS_ONLY_TFS


class AnalysisOnlyTimeframes(RuleImplementation):
    """GATE-017: an order triggered from an HTF series is a violation."""

    RULE_ID = "GATE-017"

    COVERAGE_NOTE = (
        "CLAUSE 1 ONLY. The statement has a second, separate clause — LTF events must not "
        "redefine the higher-timeframe destination unless the HTF analysis itself changes "
        "— which is a STABILITY requirement across consecutive LTF triggers. It is not "
        "implemented because nothing records the HTF destination per event, so there is "
        "nothing to compare across triggers. Recorded in KNOWN_ISSUES rather than counted "
        "as covered."
    )

    @classmethod
    def evaluate(cls, *, signal_tf: str, **context: Any) -> RuleEvaluation:
        """FAIL when the triggering signal was detected on an analysis-only timeframe.

        Testable from telemetry alone, as the statement requires: it reads `signal_tf` off
        the record and needs no engine access.
        """
        normalised = normalise_tf(signal_tf)
        violation = normalised in ANALYSIS_ONLY_TFS
        values: dict[str, Any] = {
            "signal_tf": signal_tf,
            "signal_tf_normalised": normalised,
            "analysis_only_tfs": sorted(ANALYSIS_ONLY_TFS),
            "is_analysis_only": violation,
        }
        provenance = {
            "signal_tf": from_record("timeframes.signal_tf"),
            "analysis_only_tfs": derived("GATE-017 statement — enumerated, not inferred"),
            "is_analysis_only": derived("membership of the enumerated set"),
        }
        if violation:
            values["violation"] = (
                f"the triggering signal was detected on {normalised}, which GATE-017 "
                "makes ANALYSIS ONLY — no trades are opened from these timeframes"
            )
        return cls.evaluation("FAIL" if violation else "PASS",
                              values=values, value_provenance=provenance)


#: The mode. A constant, because GATE-019's own `inputs` say `n/a — a mode constant`.
#:
#: SPELLED AS THE TELEMETRY SCHEMA SPELLS IT. `shadow.py:628` already emits
#: `mode={"trading_mode": "DAY_TRADE"}` as a hardcoded literal, so the mode was ALREADY
#: declared in a second place before this rule existed. Using `"day_trading"` here would
#: have made two spellings of one quantity — B33's shape, which cost this project forty
#: minutes of silent shadow downtime when the data layer's lowercase met the schema's
#: uppercase enum. The literal in `shadow.py` is not changed by this task (shadow-only,
#: no behaviour change) but it should read this constant, and B45 records that.
TRADING_MODE = "DAY_TRADE"


class DayTradingMode(RuleImplementation):
    """GATE-019: the engine is in day-trading mode, so session gates are unconditional."""

    RULE_ID = "GATE-019"

    COVERAGE_NOTE = (
        "THE CONSTANT IS DECLARED AND NO SESSION GATE CONSUMES IT. GATE-019's substance "
        "is that the session/timing gates lose their swing-mode false branch — but NO "
        "SESSION GATE EXISTS to lose it, so the consequence is UNENFORCED rather than "
        "enforced. SEARCHED, and naming the search because 'no swing branch exists' and "
        "'I did not look' must not produce the same report: `app/services/**` for "
        "`swing`, `08:30`, `11:30`, `session_window`, `day_trading`, `trading_mode`, and "
        "`app/services/rules/` for any session or window gate. Results — no swing-TRADING "
        "conditional anywhere (every `swing` hit is `backtest/engine.py`'s swing POINTS "
        "and its `sl_mode='swing'` stop placement, both unrelated); no 08:30/11:30 window "
        "(the only hit is an ISO example in a Finnhub docstring); the sole gate module of "
        "that family is `gate_023_timezone.py`. So there is nothing to remove. "
        "BUT THE MODE WAS ALREADY DECLARED ELSEWHERE: `shadow.py:628` hardcodes "
        "`trading_mode: 'DAY_TRADE'` and does not read this constant — a second, "
        "unreconciled declaration of one quantity. Recorded as B45."
    )

    @classmethod
    def evaluate(cls, **context: Any) -> RuleEvaluation:
        """Report the mode and, honestly, that its consequence has no consumer yet."""
        return cls.evaluation(
            "PASS",
            values={
                "trading_mode": TRADING_MODE,
                "swing_mode_available": False,
                # The consequence, stated as a fact about the code rather than a claim
                # about doctrine. A `True` here would assert enforcement that does not
                # exist.
                "session_gates_unconditional": True,
                "session_gate_consumers": [],
            },
            value_provenance={
                "trading_mode": derived("GATE-019 statement — a mode constant"),
                "session_gate_consumers": derived(
                    "searched app/services/ for session/window gates — none exist"
                ),
            },
        )
