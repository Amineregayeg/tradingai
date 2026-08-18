"""GATE-039 — do not fade a bullet train. A documented preference with NO automatable trigger.

**The rule says so about itself**, in its first six words: *"Documented preference with no
automatable trigger."* So this does not compute one.

> **A rule that states it has no trigger and is given one is off-doctrine even if the trigger is
> sensible.** *Inventing it would install our threshold as Salim's, which is `T-0029`'s refusal and
> `GATE-014`'s.*

## WHAT IT DOES INSTEAD: it records whether the CHECKLIST WAS RUN

*"Before fading, run the diagnostic checklist: missed a deeper concerning area? deeper liquidity?
unchecked timeframes? missed institutional levels or candlesticks? an economic data release? a
global event (war etc.)? — 'Momentum does not appear randomly, there is always something happening
that you are missing.'"*

**So the enforceable half is procedural, not numeric:** the verdict is about **whether the six
questions were asked**, never about whether the momentum was strong enough to fade. `GRADE-032`
owns the same checklist because both statements carry it; **this rule reads that record rather than
building a second one** — a second construction of the same list is `GATE-011`'s shape.

## AND THE VERDICT IS `NOT_APPLICABLE` WHEN NOBODY IS FADING

**A rule about what to do BEFORE fading has nothing to say on a bar where no fade was proposed.**
`PASS`/`FAIL` there would be a verdict about a decision nobody took — the same collapse this
cluster refuses everywhere else. `fade_proposed=None` means *not asked*, and it is the default.
"""
from __future__ import annotations

from typing import Any

from app.services.rules.base import RuleImplementation
from app.services.rules.grade_032_bullet_train import DIAGNOSTIC_CHECKLIST, BulletTrainRegime
from app.services.telemetry.records import derived, from_record

#: The preference, recorded as a declared value so it is quotable rather than inferable from an
#: absence of behaviour. `GATE-039` has `values: null`, so this carries no number — it is the
#: rule's own words about what it is.
DECLARED_PREFERENCE = (
    "Do not fade a bullet train. A cooling/consolidation period and probably an HTF break "
    "(5Min or 15Min) are required to reverse it — an i-MSB or a 1-minute MSB cannot stop it. "
    "NO AUTOMATABLE TRIGGER: the rule states this about itself and none is invented here."
)


class DoNotFadeABulletTrain(RuleImplementation):
    """GATE-039: the checklist must have been RUN before a fade, and no trigger is computed."""

    RULE_ID = "GATE-039"

    COVERAGE_NOTE = (
        "NO TRIGGER IS COMPUTED, AND THAT IS THE RULE'S OWN STATEMENT ABOUT ITSELF -- "
        "'documented preference with no automatable trigger'. A rule that says it has no trigger "
        "and is given one is off-doctrine even if the trigger is sensible; inventing one would "
        "install our threshold as Salim's, which is T-0029's and GATE-014's refusal. What is "
        "enforced is PROCEDURAL: whether the six diagnostic questions were asked before a fade. "
        "The checklist is READ from GRADE-032 rather than rebuilt -- a second construction of "
        "the same list is GATE-011's shape. NOT_APPLICABLE when no fade was proposed, because a "
        "rule about what to do BEFORE fading has nothing to say when nobody is fading. "
        "NOT WIRED into the live path."
    )

    @classmethod
    def evaluate(
        cls,
        fade_proposed: bool | None = None,
        *,
        economic_release: bool | None = None,
    ) -> Any:
        """`NOT_APPLICABLE` unless a fade was proposed; then PASS only if the checklist was run.

        `fade_proposed=None` means NOT ASKED and is the default — distinct from `False`, which
        means a fade was considered and declined.
        """
        checklist = BulletTrainRegime.checklist(economic_release)
        answered = [n for n, c in checklist.items() if c["answered"]]
        unanswered = [n for n, c in checklist.items() if not c["answered"]]

        values: dict[str, Any] = {
            "declared_preference": DECLARED_PREFERENCE,
            "automatable_trigger": False,
            "fade_proposed": fade_proposed,
            "checklist": checklist,
            # BOTH HALVES, ALWAYS. "The checklist was run" over one answered question of six is
            # not the claim it looks like, and the verdict alone cannot say which.
            "checklist_answered": len(answered),
            "checklist_total": len(DIAGNOSTIC_CHECKLIST),
            "checklist_unanswered": unanswered,
        }
        provenance = {
            "declared_preference": derived("GATE-039 statement — its own words, no number"),
            "automatable_trigger": derived(
                "GATE-039 states it has none; this rule computes none"
            ),
            "fade_proposed": derived("caller-supplied; None means NOT ASKED"),
            "checklist": from_record("GRADE-032's diagnostic checklist, read not rebuilt"),
            "checklist_answered": derived("questions with a producer that answered"),
            "checklist_total": derived("the statement's six"),
            "checklist_unanswered": derived("questions no producer can answer today"),
        }

        if fade_proposed is None:
            return cls.evaluation("NOT_APPLICABLE", values=values, value_provenance=provenance)
        if not fade_proposed:
            values["reason"] = "no fade proposed on this bar — nothing to gate"
            provenance["reason"] = derived("why no verdict about a fade was reached")
            return cls.evaluation("NOT_APPLICABLE", values=values, value_provenance=provenance)

        # A fade WAS proposed. The only thing this rule can enforce is that the questions were
        # asked -- and today five of the six have no producer, so this is FAIL on every real
        # bar until something can answer them. That is the honest state, not a defect: the rule
        # asks for a record and the record cannot yet be made.
        return cls.evaluation(
            "PASS" if not unanswered else "FAIL",
            values=values,
            value_provenance=provenance,
        )
