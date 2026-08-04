"""Validate telemetry against the vendored contract, before it is stored (M1).

WHY VALIDATION HAPPENS ON THE WAY IN, NOT ON THE WAY OUT
The conformance suite is a pure function of stored records. If an invalid record can reach
the store, every downstream number is computed over a population that does not match the
contract — and the failure surfaces weeks later, in an audit, as an unexplainable gap. The
cost of checking is nil at our emission rate, so the only question is whether a bad record
is discovered at its source or long after.

WHAT THIS DOES NOT CHECK, AND MUST NOT BE MISTAKEN FOR
Schema validity is a statement about shape, not about truth. A record can validate perfectly
and still describe a box the engine graded wrongly — and since the box grade keys the risk
matrix, that mis-sizes every trade while scoring 100% CONFORMANT. That gap is closable only
by a human replaying records against charts (readiness gate 7). Nothing here touches it.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from jsonschema import Draft202012Validator

from app.services.telemetry import contract_loader as contract

RECORD_TYPES = ("setup_evaluation", "trade_execution", "scan_census")


class TelemetryInvalid(ValueError):
    """A record does not satisfy the contract. Never stored."""


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    return Draft202012Validator(contract.schema())


@lru_cache(maxsize=None)
def _branch_validator(record_type: str) -> Draft202012Validator:
    """A validator for one record type.

    The schema is a `oneOf` over three record types, so a failure against the whole document
    reports three sets of errors — one per branch — and the useful one is buried. Selecting
    the branch by `record_type` first turns "does not match any of 3 schemas" into the actual
    missing field.

    THE ONE RELAXATION, AND WHY IT IS NARROW AND LOUD
    The delivered schema pins `engine.rule_registry_version` to the constant "1.1.0" while
    the delivered registry is 1.2.0 (see contract_loader.contract_version_skew). Left as-is,
    every record we emit fails on that field alone and the real errors are unreachable.

    So the two version `const`s — and ONLY those two — are dropped, and the skew is reported
    separately by `contract_version_skew()` so it can never pass silently. The fields
    themselves are still required and still type-checked; what is relaxed is which literal
    value they must equal.

    We do not solve this by writing "1.1.0" into the records. A record claiming a registry
    it was never evaluated against is worse than one that fails to validate, because it is
    wrong in a way nothing downstream can detect.
    """
    root = contract.schema()
    defs = root["$defs"]
    if record_type not in defs:
        raise KeyError(f"unknown record_type {record_type!r}")

    patched = dict(defs)
    ident = patched.get("engine_identity")
    if isinstance(ident, dict):
        ident = {**ident, "properties": dict(ident.get("properties", {}))}
        for fieldname in ("rule_registry_version", "telemetry_schema_version"):
            prop = ident["properties"].get(fieldname)
            if isinstance(prop, dict) and "const" in prop:
                ident["properties"][fieldname] = {
                    k: v for k, v in prop.items() if k != "const"
                }
        patched["engine_identity"] = ident

    sub = dict(patched[record_type])
    sub["$defs"] = patched  # keep internal $refs resolvable
    return Draft202012Validator(sub)


def errors(record: dict[str, Any]) -> list[str]:
    """Every reason this record is invalid. Empty means it validates."""
    rt = record.get("record_type")
    if rt not in RECORD_TYPES:
        return [f"record_type must be one of {RECORD_TYPES}, got {rt!r}"]

    out = [
        f"{'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}"
        for e in sorted(_branch_validator(rt).iter_errors(record), key=lambda e: list(e.absolute_path))
    ]

    # Beyond shape: every rule id emitted must exist in the pinned registry. The schema can
    # only check the id's PATTERN, so `GATE-999` satisfies it. Conformance C-3 asserts
    # existence, and finding out at emit time is far cheaper than in an audit.
    for rid in _rule_ids_in(record):
        if rid not in contract.known_rule_ids():
            out.append(
                f"rule id {rid!r} is not in RULE_REGISTRY.json "
                f"v{contract.registry_version()} (conformance C-3)"
            )
    return out


def _rule_ids_in(record: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for ev in record.get("rule_evaluations") or []:
        if isinstance(ev, dict) and isinstance(ev.get("rule_id"), str):
            ids.append(ev["rule_id"])
    if isinstance(record.get("deciding_rule_id"), str):
        ids.append(record["deciding_rule_id"])
    for step in record.get("decision_path") or []:
        if isinstance(step, str):
            ids.append(step)
    for bar in record.get("unemitted_bars") or []:
        if isinstance(bar, dict) and isinstance(bar.get("authorising_rule_id"), str):
            ids.append(bar["authorising_rule_id"])
    return ids


def is_valid(record: dict[str, Any]) -> bool:
    return not errors(record)


def assert_valid(record: dict[str, Any]) -> dict[str, Any]:
    """Return the record, or raise with every reason it failed.

    Raises rather than warning: a warning here would be a record that is invalid *and*
    stored, which is the worst of both — the store looks complete and is not.
    """
    problems = errors(record)
    if problems:
        rt = record.get("record_type", "?")
        raise TelemetryInvalid(
            f"{rt} record does not satisfy telemetry schema "
            f"{contract.schema_version()}:\n  - " + "\n  - ".join(problems)
        )
    return record
