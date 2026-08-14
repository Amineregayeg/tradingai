"""GRADE-031 — quorums are declared parameters, and a bare number is refused (T-0012).

The registry entry, which is a PROHIBITION rather than a computation:

    No source states how many of D4's three confirmation signs, how many of D5's four
    slowdown signs, or how many of Q6's seven transition conditions must be present, nor
    how much deterioration "justifies a reversal" — no level, no delta, no lookback. The
    trader declined to fix these. The engine must expose them as declared, versioned
    parameters, report the chosen values and the observed counts in telemetry, and MUST
    NOT hard-code an undeclared quorum as if it were doctrine.
    output: {d4_quorum, d5_quorum, q6_quorum, deterioration_delta, lookback}

WHY A TYPED CARRIER AND NOT A CONFIG LOOKUP
The obvious implementation — keep the quorums in a dict and validate them at load — reads
as compliant and cannot detect the prohibited act. `DeclaredParameters` carries bare
fields, so a quorum stored that way arrives at the decision path as an `int`, and **a `4`
from the declared set and a hard-coded `4` are the same object**. No check placed there can
tell them apart, because by then there is nothing to tell apart: a literal written inside a
decision function sails straight past a load-time validation.

So the quorum travels as a `DeclaredQuorum` that names its rule id and version, and the
decision path refuses anything else **on the type**. That makes the mutation real — bypass
the set, pass a literal, and it fails where the literal is used rather than at a lookup the
literal never reached.

This is the third instance of one pattern on this project and it is now the default answer
to "was this value legitimate": **make the value carry its own answer.**
`correlate_denominator` and `expected_poll_seconds` are the other two.

WHY ONLY `q6_quorum` EXISTS
The registry's output names five parameters and **only `q6_quorum` has a consumer**
(GATE-041). Building the other four now would be a mechanism with four members nothing
produces — B41's shape, which this project has spent a day documenting.

**The rule does not become partial as a result.** A prohibition is total over whatever
exists: enforced as *"any quorum reaching a decision path must arrive as a declared,
versioned carrier"*, its coverage of `d4_quorum` and `d5_quorum` is **vacuous, not
missing** — there are no such quorums to fail it. When they arrive they must route through
this same carrier, because the prohibition already refuses bare numbers. The set grows when
a consumer does.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.rules.base import RuleImplementation
from app.services.telemetry.records import RuleEvaluation, derived, from_record

#: Version of the parameter SET, not of any one value. Bump when a value changes, so a
#: record stamped `ours-v1` and one stamped `ours-v2` are distinguishable in the corpus —
#: the same reason T-0010 versioned the emission policy rather than silently correcting it.
PARAMETER_SET_VERSION = "ours-v1"


@dataclass(frozen=True)
class DeclaredQuorum:
    """A quorum that carries its own provenance to the point of use.

    THE FIELDS ARE THE POINT. `value` alone is an `int` and indistinguishable from a
    literal; `rule_id` and `version` are what make it auditable, and `ratified` is what
    stops a record implying Salim chose it.
    """

    name: str
    value: int
    of_total: int
    rule_id: str = "GRADE-031"
    version: str = PARAMETER_SET_VERSION
    #: FALSE, and it must stay false until the trader rules. "The trader declined to fix
    #: these" makes a declared parameter the RULED OUTCOME here rather than a workaround —
    #: so the record must not imply Salim chose the value, and must not imply it is
    #: arbitrary either. `ratified=False` says exactly that and nothing more.
    ratified: bool = False
    #: Why this value and not another. Prose on purpose: the reason does not reduce to a
    #: number, and the next person needs it to argue with.
    rationale: str = ""

    def __post_init__(self) -> None:
        if not 1 <= self.value <= self.of_total:
            raise ValueError(
                f"{self.name} = {self.value} is outside 1..{self.of_total}; a quorum that "
                "cannot be met or cannot fail is not a threshold"
            )

    def as_declared_parameter(self) -> str:
        """The `declared_parameter_used` string for a telemetry record."""
        return f"{self.rule_id}.{self.name}@{self.version}"

    def as_values(self) -> dict[str, Any]:
        return {
            f"{self.name}": self.value,
            f"{self.name}_of": self.of_total,
            f"{self.name}_version": self.version,
            f"{self.name}_ratified": self.ratified,
        }


#: THE DECLARED SET. Every quorum in the engine lives here and nowhere else.
DECLARED_QUORUMS: dict[str, DeclaredQuorum] = {
    "q6_quorum": DeclaredQuorum(
        name="q6_quorum",
        value=4,
        of_total=7,
        rationale=(
            "OURS, NOT SALIM'S. GATE-041 says 'multiple structural confirmations' and the "
            "registry states outright that how many of the seven, and whether any is "
            "mandatory, is never stated. 4-of-7 is a bare majority: it refuses a single "
            "coincidence and does not demand near-unanimity from a list whose members are "
            "correlated. It is a choice with a reason, not a reading of the doctrine, and "
            "it is unratified."
        ),
    ),
}


class QuorumNotDeclared(TypeError):
    """Raised when a bare number reaches a decision path that requires a declared quorum.

    A `TypeError` rather than a `ValueError`: the defect is that the caller supplied the
    WRONG KIND of thing, not a bad value, and naming it precisely is what stops it being
    reported as "the quorum was unreadable" the way B36 records.
    """


def require_declared(quorum: Any, *, expected: str) -> DeclaredQuorum:
    """Gate for every decision path that consumes a quorum. **This is the prohibition.**

    Refuses an `int` explicitly rather than by duck-typing, because an `int` is exactly
    what a hard-coded quorum looks like and the error message is the thing that teaches
    the next person why.
    """
    if not isinstance(quorum, DeclaredQuorum):
        raise QuorumNotDeclared(
            f"{expected} must arrive as a DeclaredQuorum from GRADE-031's declared set, "
            f"not as {type(quorum).__name__}. GRADE-031 forbids hard-coding an undeclared "
            "quorum as if it were doctrine — and a bare number cannot be distinguished "
            "from a declared one at the point of use, which is why the type is the check."
        )
    if quorum.name != expected:
        raise QuorumNotDeclared(
            f"expected {expected}, got {quorum.name} — a quorum declared for one rule was "
            "passed to another, which would attribute this decision to the wrong threshold"
        )
    return quorum


class QuorumsAreDeclaredParameters(RuleImplementation):
    """GRADE-031: report the declared quorums and the observed counts; refuse literals."""

    RULE_ID = "GRADE-031"

    COVERAGE_NOTE = (
        "Implements the PROHIBITION and the one quorum that has a consumer (`q6_quorum`, "
        "read by GATE-041). `d4_quorum`, `d5_quorum`, `deterioration_delta` and `lookback` "
        "are NOT declared, because nothing evaluates D4 or D5 yet — GRADE-027 and "
        "GRADE-028 are SOFT_PREFERENCE and unimplemented. Coverage of those is VACUOUS, "
        "not missing: no such quorum exists to escape the prohibition, and any that "
        "appears must route through `require_declared` because it refuses bare numbers."
    )

    @classmethod
    def evaluate(
        cls, *, observed_counts: dict[str, int] | None = None
    ) -> RuleEvaluation:
        """Report the declared set and, where a consumer supplied them, the observed counts.

        `observed_counts` is what makes the parameter REVIEWABLE, and the statement demands
        it: without "4 of 7 satisfied" beside "quorum is 4", nobody can later tell whether
        4-of-7 was generous or strict on real data, and the value becomes unfalsifiable.
        """
        values: dict[str, Any] = {"parameter_set_version": PARAMETER_SET_VERSION}
        provenance: dict[str, Any] = {
            "parameter_set_version": derived("GRADE-031 declared set")
        }
        for q in DECLARED_QUORUMS.values():
            values.update(q.as_values())
            for k in q.as_values():
                provenance[k] = derived(f"GRADE-031 declared set {q.version}")

        for name, count in (observed_counts or {}).items():
            values[f"observed_{name}"] = count
            provenance[f"observed_{name}"] = from_record("rule_evaluations")

        # PASS means "the declared set is present and every quorum in it is declared" —
        # not "the values are right". Nothing can verify the values; the trader declined
        # to fix them. Saying PASS here claims only that no undeclared quorum is in use.
        return cls.evaluation(
            "PASS",
            values=values,
            value_provenance=provenance,
            declared_parameter_used=", ".join(
                q.as_declared_parameter() for q in DECLARED_QUORUMS.values()
            ),
        )
