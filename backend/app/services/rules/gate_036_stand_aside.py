"""GATE-036 — STAND_ASIDE is a first-class outcome, not the absence of a signal (M4).

    Q1's three-step procedure ALWAYS yields "the next unresolved objective" and has no
    stand-aside output — "The engine as specified cannot output 'no trade'." A stand-aside
    output is mandatory; the condition that TRIGGERS it is deliberately unfixed, because the
    trader bans fixed % and ATR distance tests (GATE-035).

WHY THIS RULE IS THE ONE THAT MAKES THE OTHERS SAFE
Every grader in M4 returns an answer. `grade_box` returns a grade, `DisturbanceClassifier`
returns NONE/LIGHT/HEAVY. Neither has a way to say "I could not read this" — and a grader
with no refusal path will always produce something, which is exactly how five samples in a
5-minute bar become a disturbance grade and then a position size (KNOWN_ISSUES B11).

So the refusal has to exist as an OUTCOME, with a rule id attached, or it degrades into a
missing signal that nothing can audit. The schema is explicit about the distinction:

    STAND_ASIDE is distinct from SKIP: SKIP means a candidate setup failed a gate;
    STAND_ASIDE means no setup was in play.

THE TRIGGER THIS RULE NAMES IS NOT IMPLEMENTED, DELIBERATELY
GATE-036's documentary trigger is price sitting far from every concerning objective — "price
is right in the middle of PDH and PDL, then nothing is your concern at the moment". The
registry says the condition is *deliberately* unfixed because GATE-035 bans the fixed-% and
ATR distance tests that would operationalise it. Implementing a distance threshold here would
break the rule it claims to implement. What this module supplies is the OUTPUT — the machinery
for a refusal to be recorded and cited — and the causes it raises are structural ones supplied
by callers, never a distance.

DECIDING_RULE_ID IS DERIVED, NEVER CHOSEN
    `deciding_rule_id` MUST be the first entry whose verdict is FAIL … Without this, an
    engine that fails several gates may cite whichever one it prefers, and an engine that
    decides by undocumented logic may cite any gate.

So `decide()` takes the ordered evaluations and computes both `decision_path` and
`deciding_rule_id` from them. Nothing may pass a decider in by hand; that is the whole point
of K-25, and a hand-picked id is indistinguishable from a fabricated one after the fact.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

from app.services.rules.base import RuleImplementation
from app.services.telemetry.records import RuleEvaluation

DecisionType = Literal["TAKE", "SKIP", "STAND_ASIDE"]


@dataclass
class Decision:
    """One decision, with the path that produced it."""

    decision: DecisionType
    decision_path: list[str]
    deciding_rule_id: str | None
    reason: str
    stand_aside_causes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "decision": self.decision,
            "decision_path": list(self.decision_path),
            "reason": self.reason,
        }
        if self.deciding_rule_id is not None:
            out["deciding_rule_id"] = self.deciding_rule_id
        if self.stand_aside_causes:
            out["stand_aside_causes"] = list(self.stand_aside_causes)
        return out


class StandAside(RuleImplementation):
    """GATE-036: the engine can refuse, and the refusal carries a rule id."""

    RULE_ID = "GATE-036"

    COVERAGE_NOTE = (
        "The OUTPUT is implemented: STAND_ASIDE is a first-class decision and "
        "deciding_rule_id is derived as the first FAIL in the evaluation order (K-25). The "
        "documentary TRIGGER — price far from every concerning objective — is NOT "
        "implemented and must not be: the registry leaves the condition unfixed precisely "
        "because GATE-035 bans the fixed-% and ATR distance tests that would express it. "
        "Callers raise structural causes instead."
    )

    @staticmethod
    def decide(
        evaluations: Sequence[RuleEvaluation],
        *,
        setup_in_play: bool,
        stand_aside_causes: Sequence[str] = (),
    ) -> Decision:
        """Fold an ordered evaluation list into a decision.

        `setup_in_play` is what separates the two negative outcomes and it is a fact about
        the world, not a preference: SKIP means a candidate existed and a gate rejected it,
        STAND_ASIDE means there was never a candidate to reject. Collapsing them would make
        "the strategy looked and declined" indistinguishable from "the strategy could not
        look", which is the single most useful distinction in the whole decision record.
        """
        path = [e.rule_id for e in evaluations]
        first_fail = next((e for e in evaluations if e.verdict == "FAIL"), None)

        if first_fail is not None:
            decision: DecisionType = "SKIP" if setup_in_play else "STAND_ASIDE"
            return Decision(
                decision=decision,
                decision_path=path,
                deciding_rule_id=first_fail.rule_id,
                reason=(
                    f"{first_fail.rule_id} failed"
                    if setup_in_play
                    else f"no setup was in play — {first_fail.rule_id} failed"
                ),
                stand_aside_causes=list(stand_aside_causes),
            )

        if not setup_in_play:
            # Nothing failed and nothing was in play. Still a stand-aside, and still a
            # first-class outcome — but there is no failing rule to cite, so the record says
            # so rather than borrowing an id that passed.
            return Decision(
                decision="STAND_ASIDE",
                decision_path=path,
                deciding_rule_id=None,
                reason="no setup was in play and no rule refused one",
                stand_aside_causes=list(stand_aside_causes),
            )

        passed = [e for e in evaluations if e.verdict == "PASS"]
        return Decision(
            decision="TAKE",
            decision_path=path,
            # On TAKE the decider is the LAST gate that passed — the rule that authorised
            # the entry, per the schema.
            deciding_rule_id=passed[-1].rule_id if passed else None,
            reason="every evaluated rule passed",
        )

    @staticmethod
    def unreadable(causes: Sequence[str], evaluations: Sequence[RuleEvaluation]) -> Decision:
        """Stand aside because the layout could not be read at all.

        This is B11's safety property. A layout whose panels are missing, split across
        timeframes, or built from bars too thin to carry structure has not produced a weak
        alignment — it has produced no alignment, and grading it anyway manufactures the one
        input the risk matrix cannot check.
        """
        return StandAside.decide(
            evaluations, setup_in_play=False, stand_aside_causes=causes
        )
