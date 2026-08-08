"""Rule implementations carry their contract id (M2).

THE PROBLEM THIS SOLVES
The contract calls this the load-bearing integration point: rule ids are the join key for
conformance *and* for the learning loop, so they must appear in our source, not only in our
logs. A gate whose id exists only at the point it emits telemetry can be renamed, copied or
quietly duplicated, and nothing notices until an audit cannot reconcile the ledger.

So every gate, grader, selector and sizer subclasses `RuleImplementation` and declares
`RULE_ID` as a class constant. Three things follow, none of which need discipline to hold:

1. **The id is checked when the class is defined**, not when it first runs. A typo is an
   ImportError at startup, which is the cheapest possible moment.
2. **The id cannot be claimed twice.** Two classes implementing `GATE-032` would make the
   attribution ledger ambiguous — outcomes would accumulate against a rule with two
   behaviours.
3. **The set of implemented rules is discoverable**, so `scripts/check_rule_coverage.py`
   can report which of the 91 HARD_GATE rules the engine has not implemented. That number
   is meant to be looked at; the contract's readiness gate 5 requires every
   NEVER_EVALUATED hard gate to be explained or fixed.

WHAT A RULE IMPLEMENTATION IS NOT ALLOWED TO DO
Invent a value for an `OPEN` rule. Fourteen rules are OPEN because the trader explicitly
declined to make them numeric. An implementation of one must read a declared parameter and
say so in its telemetry — `declared_parameter_used` — so a later ruling can be applied to
stored history rather than invalidating it. `open_rule_requires_declared_parameter` below is
the machine-checkable half of that.
"""
from __future__ import annotations

from typing import Any, ClassVar

from app.services.telemetry import contract_loader as contract
from app.services.telemetry.records import RuleEvaluation, Verdict

#: Every implementation, keyed by the rule id it claims.
_IMPLEMENTATIONS: dict[str, type["RuleImplementation"]] = {}


class DuplicateRuleImplementation(RuntimeError):
    """Two classes claim the same rule id."""


class RuleImplementation:
    """Base for anything that evaluates a contract rule.

    Subclasses set ``RULE_ID`` and implement whatever evaluation signature their family
    needs. The base deliberately does not fix that signature — a session gate and a position
    sizer take different inputs, and forcing one shape would push the difference into
    untyped kwargs, which is worse than having none.
    """

    RULE_ID: ClassVar[str]

    #: Set on a subclass only when a rule is legitimately implemented in more than one
    #: place. Nothing uses it yet; it exists so that need is a deliberate, visible act
    #: rather than a silent overwrite.
    ALLOW_SHARED_ID: ClassVar[bool] = False

    #: What this implementation does and does NOT cover, in the implementer's own words.
    #:
    #: A rule id is binary in the coverage report — implemented or not — and several contract
    #: rules are not. PRIM-003 names seven classes of liquidity pool and three of them rest on
    #: numbers the trader explicitly declined to fix; an implementation of the other four is
    #: real work and is also not PRIM-003. Without somewhere to say so, the honest choice is
    #: between claiming a tick the code has not earned and shipping nothing.
    #:
    #: `check_rule_coverage.py` prints these. They are prose on purpose: the thing that
    #: matters is why a gap exists, and that does not reduce to a percentage.
    COVERAGE_NOTE: ClassVar[str | None] = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        rule_id = getattr(cls, "RULE_ID", None)
        if not rule_id:
            raise TypeError(
                f"{cls.__name__} subclasses RuleImplementation but declares no RULE_ID. "
                "The id is the contract's join key; a rule implementation without one "
                "cannot be attributed to anything."
            )

        # Raises if the id is not in the pinned registry — a typo or an invented rule, both
        # caught at import rather than in an audit.
        contract.rule(rule_id)

        existing = _IMPLEMENTATIONS.get(rule_id)
        if existing is not None and existing.__qualname__ != cls.__qualname__:
            if not (cls.ALLOW_SHARED_ID and existing.ALLOW_SHARED_ID):
                raise DuplicateRuleImplementation(
                    f"{rule_id} is already implemented by {existing.__module__}."
                    f"{existing.__qualname__}; {cls.__module__}.{cls.__qualname__} claims it "
                    "too. Two behaviours behind one id makes the attribution ledger "
                    "ambiguous."
                )
        _IMPLEMENTATIONS[rule_id] = cls

    # -- helpers -------------------------------------------------------------------
    @classmethod
    def rule(cls) -> dict[str, Any]:
        """The registry entry this class implements."""
        return contract.rule(cls.RULE_ID)

    @classmethod
    def is_open(cls) -> bool:
        return contract.is_open(cls.RULE_ID)

    @classmethod
    def evaluation(
        cls,
        verdict: Verdict,
        *,
        values: dict[str, Any] | None = None,
        value_provenance: dict[str, Any] | None = None,
        **extra: Any,
    ) -> RuleEvaluation:
        """Build this rule's telemetry, with the id filled in from the class constant.

        Taking the id from the constant rather than a parameter is the point: the id in the
        code and the id in the record cannot drift apart, because there is only one.
        """
        return RuleEvaluation(
            rule_id=cls.RULE_ID,
            verdict=verdict,
            values=values or {},
            value_provenance=value_provenance or {},
            **extra,
        )


def implementations() -> dict[str, type[RuleImplementation]]:
    """Every rule id the engine implements, keyed to its class."""
    return dict(_IMPLEMENTATIONS)


def implemented_ids() -> frozenset[str]:
    return frozenset(_IMPLEMENTATIONS)


def open_rule_requires_declared_parameter(ev: RuleEvaluation) -> str | None:
    """Return why this evaluation is non-compliant, or None.

    An OPEN rule that reaches a verdict without naming the declared parameter it used has
    invented a value — which produces an engine that is off-doctrine by construction and
    cannot be validated against anything in the corpus. Conformance C-05 calls this a MAJOR
    failure; catching it at emit time is cheaper.
    """
    if not contract.is_open(ev.rule_id):
        return None
    if ev.verdict == "NOT_APPLICABLE":
        return None
    if not ev.declared_parameter_used:
        return (
            f"{ev.rule_id} is OPEN — the trader declined to fix a value — but this "
            "evaluation names no declared_parameter_used. Never invent a value for an "
            "OPEN rule (conformance C-05)."
        )
    return None
