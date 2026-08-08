"""Load the pinned engine contract (M1).

The Magic Strategy contract is two machine-readable artefacts — a rule registry and a
telemetry schema — vendored under `contract/`. This module is the only place that reads
them.

WHY THEY ARE LOADED ONCE, AT IMPORT, FROM DISK
Rule ids are the join key for conformance and for the learning loop. A registry that could
change under a running engine would make stored telemetry un-auditable after the fact: a
record claiming `GATE-032` would mean whatever the registry happened to say when someone
later looked. Pinning the version into every record — and never fetching at runtime — is
what makes a stored record re-checkable years later.

WHAT THIS MODULE DELIBERATELY DOES NOT DO
It does not interpret rules. The registry says what a rule requires; implementing it is the
job of the gate that carries its id. Keeping the loader dumb means a rule cannot acquire
behaviour by being read.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

CONTRACT_DIR = Path(__file__).parent / "contract"
REGISTRY_PATH = CONTRACT_DIR / "RULE_REGISTRY.json"
SCHEMA_PATH = CONTRACT_DIR / "TELEMETRY_SCHEMA.json"

#: Rule families the contract defines. Anything else is not a rule id.
RULE_FAMILIES = ("GATE", "GRADE", "TARGET", "ENTRY", "EXIT", "SIZE", "PRIM")


@lru_cache(maxsize=1)
def registry() -> dict[str, Any]:
    """The full rule registry, as delivered."""
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def schema() -> dict[str, Any]:
    """The telemetry JSON Schema, as delivered."""
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def rules() -> dict[str, dict[str, Any]]:
    """Every rule, keyed by id."""
    return {r["id"]: r for r in registry()["rules"]}


def registry_version() -> str:
    return str(registry()["meta"]["version"])


def schema_version() -> str:
    """The schema's own version, taken from its ``$id``.

    Read from the artefact rather than hardcoded: a schema swapped without a version bump
    would otherwise be invisible in the telemetry it produced. The leading ``v`` of the
    ``$id`` path segment is stripped, because the schema's own ``const`` for this field
    spells it without one.
    """
    tail = str(schema().get("$id", "")).rsplit("/", 1)[-1]
    return tail[1:] if tail.startswith("v") else (tail or "unknown")


def contract_version_skew() -> str | None:
    """The delivered registry and schema disagree — return why, or None if they agree.

    THIS IS A DEFECT IN THE DELIVERED PACKAGE, NOT IN THIS ENGINE.

    `TELEMETRY_SCHEMA.json` pins `engine.rule_registry_version` with
    ``"const": "1.1.0"``, while `RULE_REGISTRY.json` ships as 1.2.0 — the version produced
    by the corpus triage that cleared all 8 DEFECT rules and moved 20 rules OPEN → READY.

    The consequence is concrete: **no record emitted against the real registry can ever
    validate against the delivered schema.** The two machine-readable artefacts are mutually
    incompatible, so this is not the stale-prose problem noted in
    MAGIC_STRATEGY_INTEGRATION.md §2.1 — it blocks emission itself.

    We report the true versions in every record regardless. The alternative is writing
    ``1.1.0`` into telemetry while running 1.2.0, which would make stored evidence claim a
    registry it was never evaluated against — defeating the one thing these fields exist for.
    """
    expected = (
        schema()
        .get("$defs", {})
        .get("engine_identity", {})
        .get("properties", {})
        .get("rule_registry_version", {})
        .get("const")
    )
    actual = registry_version()
    if expected is not None and expected != actual:
        return (
            f"telemetry schema {schema_version()} pins rule_registry_version=={expected!r}, "
            f"but the delivered RULE_REGISTRY.json is {actual!r}. The delivered artefacts "
            "are mutually incompatible; awaiting a schema regenerated against the registry."
        )
    return None


def rule(rule_id: str) -> dict[str, Any]:
    """One rule. Raises if the id is not in the registry.

    Raising is deliberate. A rule id that does not resolve is either a typo or a rule
    someone invented, and both must fail loudly at the point of use — an unknown id reaching
    telemetry is a conformance failure (C-3) discovered far later and much harder to trace.
    """
    try:
        return rules()[rule_id]
    except KeyError:
        raise KeyError(
            f"{rule_id!r} is not in RULE_REGISTRY.json v{registry_version()}. "
            "Rule ids are the contract's join key — they are never invented locally."
        ) from None


def known_rule_ids() -> frozenset[str]:
    return frozenset(rules())


def ids_with_status(status: str) -> frozenset[str]:
    """e.g. ``ids_with_status("OPEN")`` — the rules that must never be given a value."""
    return frozenset(k for k, v in rules().items() if v.get("status") == status)


def ids_with_enforceability(level: str) -> frozenset[str]:
    """e.g. ``ids_with_enforceability("HARD_GATE")`` — the 91 that must all be covered."""
    return frozenset(k for k, v in rules().items() if v.get("enforceability") == level)


def enforceability_of(rule_id: str) -> str:
    return str(rule(rule_id).get("enforceability", ""))


def is_open(rule_id: str) -> bool:
    """OPEN means the trader declined to fix a value. Never invent one; the engine must
    carry a declared parameter instead and stamp it on every record."""
    return rule(rule_id).get("status") == "OPEN"


@lru_cache(maxsize=1)
def _alias_index() -> dict[str, tuple[str, ...]]:
    """canonical rule id -> the ids that restate it.

    Thirteen GRADE ids carry `alias_of` because two extraction passes over the corpus
    produced the same rule twice under different numbers. They are not duplicates to be
    cleaned up — the id policy is STABLE and both ids may be cited by stored telemetry
    forever — so the engine has to treat one implementation as satisfying both.
    """
    out: dict[str, list[str]] = {}
    for rid, r in rules().items():
        target = r.get("alias_of")
        if isinstance(target, str) and target:
            out.setdefault(target, []).append(rid)
    return {k: tuple(sorted(v)) for k, v in out.items()}


def aliases_of(rule_id: str) -> tuple[str, ...]:
    """The alias ids that restate *rule_id*, or empty."""
    rule(rule_id)
    return _alias_index().get(rule_id, ())


def alias_target(rule_id: str) -> str | None:
    """The canonical id this one restates, or None if it is already canonical."""
    target = rule(rule_id).get("alias_of")
    return str(target) if isinstance(target, str) and target else None


def banned_inputs(rule_id: str) -> tuple[str, ...]:
    """Input classes the trader specifically prohibited for this rule.

    Named in the source *in order to be rejected* — correlation coefficients, ATR multiples,
    candle counts, fixed time delays, retracement percentages. The conformance suite asserts
    their absence, so a decision record has to show the check happened.
    """
    v = rule(rule_id).get("banned_inputs") or ()
    return tuple(v) if isinstance(v, (list, tuple)) else ()
