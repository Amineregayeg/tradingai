"""Builders for the three engine-contract record types (M1).

The contract's instruction is blunt and correct: *implement the telemetry schema before
strategy logic — everything downstream reads from it, and retrofitting is expensive.* This
module is that layer. It knows how to produce records that validate; it knows nothing about
the strategy.

THE FOUR THINGS THAT MAKE A RECORD USEFUL RATHER THAN MERELY PRESENT

1. **It records rejections.** `setup_evaluation` is emitted for every setup considered —
   taken, skipped, or stood aside. An engine that takes three correct trades while silently
   skipping thirty valid ones is failing, and executed-trade logs cannot show that.
2. **Every verdict carries its inputs** (`values`) and where each came from
   (`value_provenance`). Without provenance a verdict re-derives only itself, and a banned
   input passes every name-based check under a new name.
3. **Every choice the engine made because the strategy declined to** is stamped on every
   record (`declared_parameters`), so a later trader ruling can be applied retroactively to
   stored history instead of invalidating it.
4. **`deciding_rule_id` is the FIRST rule that failed**, on a fixed evaluation order — not
   merely *a* rule that failed. Otherwise the attribution ledger accumulates against
   whichever gate the engine chose to blame.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal

from app.core.build_info import build_info
from app.services.telemetry import contract_loader as contract
from app.services.telemetry.ny_time import iso_ny

Verdict = Literal["PASS", "FAIL", "NOT_APPLICABLE", "FLAG", "UNIMPLEMENTABLE"]
Decision = Literal["TAKE", "SKIP", "STAND_ASIDE"]


def engine_identity() -> dict[str, str]:
    """Pins a record to a code build AND to both contract versions.

    `engine_version` is the running commit, which the platform already knows how to report
    (`/api/system/version`). That is what lets a record found in six months be replayed
    against the exact code and exact registry that produced it.
    """
    build = build_info()
    return {
        "engine_version": build.commit,
        "rule_registry_version": contract.registry_version(),
        "telemetry_schema_version": contract.schema_version(),
        "git_sha": build.commit,
    }


@dataclass(frozen=True)
class DeclaredParameters:
    """Every value the ENGINE chose because the strategy declined to fix it.

    These are OUR choices, never the trader's doctrine. The contract is explicit that a
    proxy must be labelled a proxy in both code and telemetry — presenting one as his method
    is the failure mode this whole field exists to prevent.

    Stamped on every record so that when he does rule, stored history can be re-partitioned
    by the value that was actually in force rather than thrown away.
    """

    # --- required by the schema -------------------------------------------------
    virtual_account_size: float
    evaluation_order_id: str
    emission_policy_id: str
    layout_size_frozen: bool
    main_asset_counts: bool
    box_scope: Literal["ENTRY_BOX_EXEC_TF", "DESTINATION_BOX"]
    #: GATE-028's resolved reading. "Largest" is dead text; the selector is
    #: argmin |RR - 3.0| over candidates clearing 2R, ties to the larger stop.
    stop_selection_reading: Literal["CLOSEST_TO_3R_TIES_TO_LARGER", "LARGEST_ABOVE_2R"]
    runner_management_policy: str
    reverse_quorum: int | None

    # --- optional -----------------------------------------------------------------
    upper_rr_cut: float | None = None
    d4_quorum: int | None = None
    d5_quorum: int | None = None
    amplifier_collision_basis: str | None = None
    execution_tf_set: tuple[str, ...] | None = None
    magic_zone_enforced_as: str | None = None
    altcoin_trading_enabled: bool = False

    #: Emitted even when the value is null. `reverse_quorum` is OPEN — the trader declined
    #: to fix it — and the schema types it ["integer","null"] precisely so the engine can
    #: say "no quorum in force" out loud. Dropping the key instead would make "we chose
    #: nothing" indistinguishable from "we forgot to declare it", which is the ambiguity
    #: declared_parameters exists to remove.
    _ALWAYS_EMIT = ("reverse_quorum",)

    def as_dict(self) -> dict[str, Any]:
        out = {
            k: v
            for k, v in asdict(self).items()
            if v is not None or k in self._ALWAYS_EMIT
        }
        if self.execution_tf_set is not None:
            out["execution_tf_set"] = list(self.execution_tf_set)
        return out


@dataclass
class RuleEvaluation:
    """One rule, evaluated. THE core fidelity object.

    Emitted for every rule considered on every setup — including rules that did not apply.
    Silence is not a pass (C-04): the difference between "evaluated and inapplicable" and
    "never implemented" is precisely what rule coverage measures.
    """

    rule_id: str
    verdict: Verdict
    #: The inputs that produced the verdict, sufficient for an auditor to re-derive it with
    #: no engine access. An empty `values` counts against the unexplained-decision rate.
    values: dict[str, Any] = field(default_factory=dict)
    #: Where each key in `values` came from — an object id in this same record, a
    #: declared_parameters key, a registry constant, or an expression over those.
    value_provenance: dict[str, str] = field(default_factory=dict)
    evidence: dict[str, Any] | None = None
    declared_parameter_used: str | None = None
    banned_input_check: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        # Fail at construction, not at validation: an unknown id here is either a typo or an
        # invented rule, and both are far cheaper to find at the call site.
        contract.rule(self.rule_id)

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "rule_id": self.rule_id,
            "verdict": self.verdict,
            "values": self.values,
            "value_provenance": self.value_provenance,
            # Taken from the registry rather than passed in, so a rule's enforceability can
            # never be misreported by the code that happens to evaluate it.
            "enforceability": contract.enforceability_of(self.rule_id),
        }
        for k, v in (
            ("evidence", self.evidence),
            ("declared_parameter_used", self.declared_parameter_used),
            ("banned_input_check", self.banned_input_check),
        ):
            if v is not None:
                out[k] = v
        return out


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


# ---------------------------------------------------------------------------
# value_provenance builders
#
# Every key in a rule's `values` must name where it came from. This is what turns `values`
# from a self-attestation into evidence: without it an engine can fabricate numbers that
# re-derive its own verdict, or launder a banned input under a new name — both of which pass
# every check that only inspects key names.
#
# These exist so the correct shape is the easy one to write. Hand-built dicts drift.
# ---------------------------------------------------------------------------
def from_primitive(object_id: str, field_name: str) -> dict[str, str]:
    """A value read off a primitive this record emitted. The id must resolve here (K-24)."""
    return {"source": "PRIMITIVE_FIELD", "object_id": object_id, "field": field_name}


def from_correlate(object_id: str, field_name: str) -> dict[str, str]:
    """A value read off one of the layout panels in this same record."""
    return {"source": "CORRELATE_FIELD", "object_id": object_id, "field": field_name}


def from_declared(key: str) -> dict[str, str]:
    """A value the ENGINE chose because the strategy declined to fix it."""
    return {"source": "DECLARED_PARAMETER", "field": key}


def from_registry(rule_id: str, field_name: str = "values") -> dict[str, str]:
    """A constant that comes from the rule registry itself, e.g. the 3x3 risk table."""
    contract.rule(rule_id)
    return {"source": "REGISTRY_CONSTANT", "object_id": rule_id, "field": field_name}


def from_record(field_path: str) -> dict[str, str]:
    """A value taken from elsewhere in this record, e.g. `session.minutes_from_nyo`."""
    return {"source": "RECORD_FIELD", "field": field_path}


def derived(expression: str) -> dict[str, str]:
    """Arithmetic over other bound keys. State the expression, not just the result."""
    return {"source": "DERIVED", "field": expression}


def setup_evaluation(
    *,
    timestamp: datetime,
    declared: DeclaredParameters,
    scan_context: dict[str, Any],
    instrument: dict[str, Any],
    mode: dict[str, Any],
    timeframes: dict[str, Any],
    session: dict[str, Any],
    primitives: dict[str, Any],
    correlates: dict[str, Any],
    rule_evaluations: list[RuleEvaluation],
    decision: Decision,
    deciding_rule_id: str,
    risk_assessment: dict[str, Any],
    decision_path: list[str] | None = None,
    evaluation_id: str | None = None,
    **optional: Any,
) -> dict[str, Any]:
    """Build a `setup_evaluation` — emitted for EVERY setup, including rejections.

    `decision_path` defaults to the order the rules were actually evaluated in, which is
    what makes `deciding_rule_id` checkable: the suite asserts the deciding rule is the
    FIRST failure along that path.
    """
    contract.rule(deciding_rule_id)
    path = decision_path if decision_path is not None else [r.rule_id for r in rule_evaluations]

    record: dict[str, Any] = {
        "record_type": "setup_evaluation",
        "evaluation_id": evaluation_id or _new_id("eval"),
        "timestamp_ny": iso_ny(timestamp),
        "engine": engine_identity(),
        "declared_parameters": declared.as_dict(),
        "scan_context": scan_context,
        "instrument": instrument,
        "mode": mode,
        "timeframes": timeframes,
        "session": session,
        "primitives": primitives,
        "correlates": correlates,
        "rule_evaluations": [r.as_dict() for r in rule_evaluations],
        "decision_path": path,
        "decision": decision,
        "deciding_rule_id": deciding_rule_id,
        "risk_assessment": risk_assessment,
    }
    record.update({k: v for k, v in optional.items() if v is not None})
    return record


def trade_execution(
    *,
    timestamp: datetime,
    setup_evaluation_id: str,
    instrument: dict[str, Any],
    side: str,
    entry: dict[str, Any],
    stop: dict[str, Any],
    target: dict[str, Any],
    stop_ladder: list[dict[str, Any]],
    sizing: dict[str, Any],
    exits: list[dict[str, Any]],
    outcome: dict[str, Any],
    trade_id: str | None = None,
    **optional: Any,
) -> dict[str, Any]:
    """Build a `trade_execution`. Joins to its `setup_evaluation` by id.

    The FULL stop ladder is carried, including the candidates that were rejected — the
    selection is only auditable against the alternatives it beat.
    """
    record: dict[str, Any] = {
        "record_type": "trade_execution",
        "trade_id": trade_id or _new_id("trade"),
        "setup_evaluation_id": setup_evaluation_id,
        "timestamp_ny": iso_ny(timestamp),
        "engine": engine_identity(),
        "instrument": instrument,
        "side": side,
        "entry": entry,
        "stop": stop,
        "target": target,
        "stop_ladder": stop_ladder,
        "sizing": sizing,
        "exits": exits,
        "outcome": outcome,
    }
    record.update({k: v for k, v in optional.items() if v is not None})
    return record


def scan_census(
    *,
    declared: DeclaredParameters,
    instrument: dict[str, Any],
    signal_tf: str,
    session_date: str,
    window_from: datetime,
    window_to: datetime,
    bars_observed: int,
    evaluations_emitted: int,
    unemitted_bars: list[dict[str, Any]] | None = None,
    scan_id: str | None = None,
    **optional: Any,
) -> dict[str, Any]:
    """Build a `scan_census` — THE POPULATION RECORD.

    This is the one that stops a filtered sample being reported as full coverage. Every
    unemitted bar must name the registry rule id that authorises the omission; any
    pre-filter citing no rule is undocumented logic by definition, and is the cheapest way
    to score 100% fidelity while running on something nobody has seen.

    Under our emission policy (`every-closed-bar-roster-v1`) `unemitted_bars` should always
    be empty. If it is ever not, that is the finding.
    """
    record: dict[str, Any] = {
        "record_type": "scan_census",
        "scan_id": scan_id or _new_id("scan"),
        "engine": engine_identity(),
        "declared_parameters": declared.as_dict(),
        "instrument": instrument,
        "signal_tf": signal_tf,
        "session_date": session_date,
        "window_from_ny": iso_ny(window_from),
        "window_to_ny": iso_ny(window_to),
        "bars_observed": bars_observed,
        "evaluations_emitted": evaluations_emitted,
        "unemitted_bars": unemitted_bars or [],
    }
    record.update({k: v for k, v in optional.items() if v is not None})
    return record
