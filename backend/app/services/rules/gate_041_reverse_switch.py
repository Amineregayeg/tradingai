"""GATE-041 — the switch to Reverse needs multiple structural confirmations (T-0012).

The registry entry:

    The switch to Reverse requires "multiple structural confirmations": price slows after
    reaching the destination · momentum begins deteriorating · momentum-imbalance failures
    appear · new opposite-direction momentum imbalances form · failed imbalances become
    S/R flips · those new imbalances successfully hold price · a valid micro MSB confirms
    the new direction. HOW MANY of the seven, and whether any is mandatory (e.g. the micro
    MSB), is never stated. Absent them the default is CONTINUE (GATE-040).
    inputs: the seven condition evaluations at the destination.

THE QUORUM IS OURS AND `status: READY` GAVE NO WARNING
"Multiple" is not a number. `>= 4 of 7` and "the micro MSB is mandatory" are **our
choices**, so they arrive from GRADE-031's declared set as a typed carrier and are stamped
on every record as unratified. **This is more dangerous than an OPEN rule**: nothing in the
registry flags GATE-041, so a coverage report would show a fully implemented HARD_GATE
whose central threshold we invented. B38 is the precedent for saying so on the record.

THREE OF THE SEVEN HAVE NO PRODUCER, AND THE HONEST ANSWER IS THE RULE'S OWN DEFAULT
Momentum deterioration, momentum-imbalance failures and "price slows after the
destination" all need `GRADE-028` (the last also `GRADE-035`, whose consolidation detector
does not exist either). `GRADE-028` is
`SOFT_PREFERENCE`, unimplemented, and **will never arrive from this programme** — no wave
delivers it. A proxy would be an invented threshold wearing a rule's id, so there is none.

Each condition is recorded individually as `TRUE` / `FALSE` / `NOT_EVALUABLE`, the last
naming its missing producer. **While any condition is NOT_EVALUABLE, no quorum is claimed
and the verdict is the documented default, CONTINUE.** That is faithful rather than
degraded: the statement says *"absent them the default is CONTINUE."*

**AND THAT CREATES THE FAMILIAR TRAP**: GATE-041 then returns CONTINUE on every live bar
forever, which is indistinguishable from a gate that is broken. Two things answer it —
`test_gate_041_reverse_switch.py` drives all seven TRUE on a fixture and gets a Reverse, and
the work report records the per-condition verdict distribution over the corpus, because five
conditions sitting at 100% FALSE is either a rare market or a dead check and nothing else
separates them.

THE DEFAULT IS A CONSTANT HERE, NOT A CALL
*"the default is CONTINUE (GATE-040)"* is emitted as a constant. GATE-040 is wave 2 and
unimplemented; calling it would give this rule a dependency that does not exist.
"""
from __future__ import annotations

from typing import Any

from app.services.rules.base import (
    ConditionReading,
    RuleImplementation,
    quorum_blocked,
)
from app.services.rules.grade_031_declared_quorums import (
    DECLARED_QUORUMS,
    DeclaredQuorum,
    require_declared,
)
from app.services.telemetry.records import RuleEvaluation, derived, from_record

#: The seven, in the registry's own order. Each carries the producer that evaluates it, so
#: a missing producer is nameable rather than an unexplained absence.
#:
#: `producer=None` means NO producer exists. That is not the same as a producer that
#: returned nothing, and conflating them is how a dead check reads as a quiet market.
CONDITIONS: tuple[tuple[str, str | None], ...] = (
    ("price_slows_after_destination", None),          # GRADE-028 / GRADE-035 — neither exists
    ("momentum_deteriorating", None),                 # GRADE-028 — SOFT_PREFERENCE, unimplemented
    ("momentum_imbalance_failures", None),            # GRADE-028 / GRADE-038 — unimplemented
    ("new_opposite_imbalances", "PRIM-002"),
    ("failed_imbalances_became_sr_flips", "PRIM-006"),
    ("new_imbalances_hold_price", "PRIM-002"),
    ("micro_msb_confirms", "PRIM-005"),
)

#: OURS, and unratified. The registry says whether ANY condition is mandatory is never
#: stated, so making the micro MSB mandatory is a second invented choice on top of the
#: quorum and is recorded as its own declared value rather than folded into the count.
MANDATORY_CONDITION = "micro_msb_confirms"

CONTINUE = "CONTINUE"
REVERSE = "REVERSE"


def _not_evaluable() -> list[ConditionReading]:
    """Live reading: the three momentum conditions have no producer at all."""
    out: list[ConditionReading] = []
    for name, producer in CONDITIONS:
        if producer is None:
            out.append(
                ConditionReading(
                    name,
                    "NOT_EVALUABLE",
                    missing_producer="GRADE-028 (SOFT_PREFERENCE, unimplemented)",
                )
            )
        else:
            out.append(ConditionReading(name, "FALSE"))
    return out


class ReverseSwitchConfirmations(RuleImplementation):
    """GATE-041: authorise Reverse only on a declared quorum of the seven."""

    RULE_ID = "GATE-041"

    #: Read by `check_rule_coverage.py`. This rule is registered and CANNOT FIRE.
    CANNOT_FIRE_WITHOUT = ("GRADE-028",)

    COVERAGE_NOTE = (
        "IMPLEMENTED BUT CANNOT FIRE ON LIVE DATA. Three of the seven conditions "
        "(price_slows_after_destination, momentum_deteriorating, "
        "momentum_imbalance_failures) have NO producer — they need GRADE-028, which is "
        "SOFT_PREFERENCE and outside this programme, so no wave will deliver it. While any "
        "condition is NOT_EVALUABLE the verdict is the rule's documented default, CONTINUE. "
        "The quorum (4 of 7) and the mandatory micro-MSB are OURS and unratified: the "
        "registry states the count and any mandatory member are never specified, and "
        "status READY gave no warning that a threshold was missing."
    )

    @classmethod
    def evaluate(
        cls,
        readings: list[ConditionReading] | None = None,
        *,
        quorum: DeclaredQuorum | int | None = None,
    ) -> RuleEvaluation:
        """Decide CONTINUE or REVERSE from the seven condition readings.

        `quorum` is typed `DeclaredQuorum | int | None` deliberately: the `int` is admitted
        by the SIGNATURE so that passing one is a runtime refusal with an explanatory
        message, rather than a static type error a caller can silence. GRADE-031's
        prohibition is the thing being enforced, and it must be enforced where the value is
        USED.
        """
        q = require_declared(
            quorum if quorum is not None else DECLARED_QUORUMS["q6_quorum"],
            expected="q6_quorum",
        )
        rs = readings if readings is not None else _not_evaluable()

        satisfied = [r.name for r in rs if r.state == "TRUE"]
        unevaluable = [r for r in rs if r.state == "NOT_EVALUABLE"]

        values: dict[str, Any] = {
            "conditions": {r.name: r.state for r in rs},
            "satisfied_count": len(satisfied),
            "conditions_total": len(rs),
            "not_evaluable_count": len(unevaluable),
            "mandatory_condition": MANDATORY_CONDITION,
            **q.as_values(),
        }
        provenance: dict[str, Any] = {
            "conditions": from_record("primitives"),
            "satisfied_count": derived("count of conditions with state TRUE"),
            "mandatory_condition": derived("GATE-041 declared choice — OURS, unratified"),
            **{k: derived(f"GRADE-031 declared set {q.version}") for k in q.as_values()},
        }

        blocked = quorum_blocked(rs, default_outcome=CONTINUE)
        if blocked is not None:
            unreadable, default_outcome = blocked
            # NO QUORUM IS CLAIMED. Scoring 4-of-7 while three cannot be read would report
            # a threshold decision that was never actually taken — the count would be
            # against a denominator of four.
            values["not_evaluable"] = unreadable
            provenance["not_evaluable"] = derived("no implementation produces this input")
            return cls.evaluation(
                "NOT_APPLICABLE",
                values={**values, "outcome": default_outcome},
                value_provenance=provenance,
                declared_parameter_used=q.as_declared_parameter(),
            )

        mandatory_ok = any(
            r.name == MANDATORY_CONDITION and r.state == "TRUE" for r in rs
        )
        authorised = len(satisfied) >= q.value and mandatory_ok
        values["outcome"] = REVERSE if authorised else CONTINUE
        values["mandatory_satisfied"] = mandatory_ok

        return cls.evaluation(
            "PASS" if authorised else "FAIL",
            values=values,
            value_provenance=provenance,
            declared_parameter_used=q.as_declared_parameter(),
        )
