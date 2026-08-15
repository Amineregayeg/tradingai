"""EXIT-002 — the 25% scale-out ladder is OFF for v1 (T-0022).

The registry entry:

    "The 25% scale-out ladder (25% -> 25% -> 25% -> 25%) is an alternative discretionary
    trade management technique that I use manually in certain situations. It is not the
    default behavior and introduces unnecessary complexity for the first version of the
    automated system. For v1, implement only the 70% at 2R + 30% runner model." This
    overrides the crypto-strand exits — 114's "sometimes 25%, sometimes 50%... i generally
    prefer to close half of it... leave the rest like 10%" and 034's "Closing 25% of your
    Position every time you hit the Target" — FOR THE ENGINE ONLY; both remain live as the
    trader's manual practice. A telemetry record showing more than two exit tranches
    (partial + runner) is a v1 violation.
    output: conformance assertion — exit_events contains at most one partial tranche plus
    one runner tranche.

WHY THIS RULE NEEDED A CHECK BUILT RATHER THAN A NOTE SAYING IT WAS ALREADY SATISFIED
Until T-0022 this constraint was true and unenforced, for the worst possible reason: the
platform could not produce tranches at all. `broker/paper.py` closes positions whole, so
"at most two tranches" held the way "at most two moons" holds over a codebase with no moons.
That is a vacuous truth, and a vacuous truth reads exactly like a working guard.

**EXIT-001 IS WHAT ENDS THAT.** The 70/30 split is a CONSTRUCTOR for multiple tranches — the
moment tranching exists, four tranches are constructible, and the thing that made the
constraint unbreakable is gone. So the answer to "unreachable by construction, or blocked by
a check?" is not a finding to report; it is decided by whether this file exists. It is
blocked by a check, and the check is below.

WHAT THIS CHECKS THAT THE MODEL CANNOT
`V1ExitModel.simulate` cannot emit two partials — a `partial_taken` flag makes it
unconstructible — and that is exactly why it is not sufficient. The constraint is on the
TELEMETRY RECORD, not on one producer: an exit sequence can be assembled by a replay tool, a
migration, a future live path, or a hand-written fixture, and the record is what conformance
reads. A guard that only covers the one code path already known to be correct is decoration.
So this takes a sequence of events from anywhere and rules on it.

WHICH OF THESE FINDINGS CAN FIRE TODAY, MEASURED RATHER THAN ASSUMED
Say it plainly, because the alternative is a check that looks broader than it is:
**`records.trade_execution()` has ZERO callers in this repository — not in `app/`, not in
`scripts/`, not in the suite.** Nothing writes a stored `exits` array at all. So today the
ONLY producer of exit events is `ExitEvent`, whose constructor refuses any reason outside
EXIT-001's four, and therefore:

* the TRANCHE-COUNT findings — `MULTIPLE_PARTIALS`, `MULTIPLE_TERMINALS`,
  `TOO_MANY_TRANCHES`, `OVERSIZED_EXIT`, `SCALE_OUT_LADDER` — are reachable from validly
  constructed `ExitEvent`s, because the constructor validates each event on its own and
  says nothing about the sequence. These guard a real hole.
* **`REASON_OUTSIDE_V1` CANNOT FIRE over anything this codebase currently produces.** Every
  route to an exit event goes through a constructor that has already refused the bad value.
  It is reachable only from a hand-built dict, which means the test that covers it is
  verified against its own fixture.

**So `REASON_OUTSIDE_V1` guards a FUTURE writer** — a live exit path, a replay of stored
history, an importer — and that is the honest description of it, not "it checks the
records". It is kept because the dict path is the one a future writer will use and the cost
of it existing early is a line of code; it is documented because a check whose only caller
is its own test, left undescribed, reads as coverage it has not got (register B52, filed
twice off exactly this mistake).

THE OVERRIDE IS SCOPED TO THE ENGINE AND THE SCOPING IS PART OF THE RULE
The statement says the crypto-strand exits are overridden "FOR THE ENGINE ONLY; both remain
live as the trader's manual practice". So this is not a finding that 114 and 034 were wrong;
it is a statement about which of two live practices the automated system implements. Nothing
here deprecates the manual method, and the violation message says so — a conformance failure
that reads as "your strategy is wrong" rather than "the engine did something it may not"
invites the wrong fix.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from app.services.rules.base import RuleImplementation
from app.services.rules.exit_001_v1_model import (
    EXIT_001_REASONS,
    PARTIAL_2R,
    SCHEMA_ONLY_REASONS,
    TERMINAL_REASONS,
    ExitEvent,
)
from app.services.telemetry.records import RuleEvaluation, derived, from_registry

#: v1's whole permitted vocabulary of tranches: one partial, one runner. Named as a number
#: because the statement is a count — "more than two exit tranches ... is a v1 violation".
MAX_TRANCHES = 2

#: The ladder the rule switches off, kept as data so the violation can NAME what it looks
#: like rather than only reporting a count. A conformance failure that says "4 tranches"
#: and one that says "this is the 25/25/25/25 ladder" send the reader to different places.
LADDER_SIGNATURE: tuple[float, ...] = (0.25, 0.25, 0.25, 0.25)


@dataclass(frozen=True)
class ConformanceFinding:
    """One way a sequence of exits violates v1. `code` is stable; `detail` is for humans."""

    code: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


def _fraction(ev: Any) -> float:
    return float(ev["fraction"] if isinstance(ev, dict) else ev.fraction)


def _reason(ev: Any) -> str:
    return str(ev["reason"] if isinstance(ev, dict) else ev.reason)


def ladder_violations(events: Sequence[Any]) -> list[ConformanceFinding]:
    """Every way `events` breaks the v1 exit shape. Empty means conformant.

    Accepts `ExitEvent` objects OR the raw dicts of a stored `trade_execution.exits` array,
    because the constraint is on the RECORD and a check that could only read live objects
    could not be run over history — which is where a violation would actually be found.
    """
    findings: list[ConformanceFinding] = []

    partials = [e for e in events if _reason(e) == PARTIAL_2R]
    terminals = [e for e in events if _reason(e) in TERMINAL_REASONS]
    unknown = [e for e in events if _reason(e) not in EXIT_001_REASONS]

    if len(partials) > 1:
        findings.append(
            ConformanceFinding(
                "MULTIPLE_PARTIALS",
                f"{len(partials)} partial tranches; v1 permits exactly one 70% partial at "
                f"2R. Fractions: {[_fraction(e) for e in partials]}",
            )
        )
    if len(terminals) > 1:
        findings.append(
            ConformanceFinding(
                "MULTIPLE_TERMINALS",
                f"{len(terminals)} terminal tranches ({[_reason(e) for e in terminals]}); "
                "the runner ends once, on one of the three conditions",
            )
        )
    if len(events) > MAX_TRANCHES:
        findings.append(
            ConformanceFinding(
                "TOO_MANY_TRANCHES",
                f"{len(events)} exit tranches; the statement makes more than "
                f"{MAX_TRANCHES} (partial + runner) a v1 violation",
            )
        )
    for e in unknown:
        extra = (
            " — permitted by the telemetry schema's wider enum but not by EXIT-001"
            if _reason(e) in SCHEMA_ONLY_REASONS
            else ""
        )
        findings.append(
            ConformanceFinding(
                "REASON_OUTSIDE_V1",
                f"exit reason {_reason(e)!r} is not one of EXIT-001's four{extra}",
            )
        )

    total = sum(_fraction(e) for e in events)
    if total > 1.0 + 1e-9:
        findings.append(
            ConformanceFinding(
                "OVERSIZED_EXIT",
                f"exit fractions sum to {total:.4f}; more than the whole position left it",
            )
        )

    # Reported IN ADDITION to the counts above, never instead of them. It is a label on a
    # shape already ruled a violation, so a ladder with three legs — which does not match
    # the signature — is still caught by MULTIPLE_PARTIALS and TOO_MANY_TRANCHES. A check
    # that recognised only the four-legged form would be defeated by using three.
    fractions = tuple(round(_fraction(e), 10) for e in events)
    if fractions == LADDER_SIGNATURE:
        findings.append(
            ConformanceFinding(
                "SCALE_OUT_LADDER",
                "this is the 25% -> 25% -> 25% -> 25% scale-out ladder, which EXIT-002 "
                "switches off FOR THE ENGINE in v1. It remains the trader's manual "
                "practice; this is a statement about the automated system only.",
            )
        )

    return findings


class LadderOffForV1(RuleImplementation):
    """EXIT-002: at most one partial tranche plus one runner tranche."""

    RULE_ID = "EXIT-002"

    COVERAGE_NOTE = (
        "A NEGATIVE CONSTRAINT, ENFORCED BY A CHECK RATHER THAN BY NOTHING BEING BUILDABLE. "
        "Before T-0022 this rule was satisfied vacuously — no code path could produce a "
        "tranche at all — and EXIT-001's 70/30 split is precisely the constructor that ends "
        "that, so the check was built in the same task. It reads `ExitEvent` objects or the "
        "raw dicts of a stored `trade_execution.exits` array, so it can be run over history "
        "as well as over live output. It does NOT deprecate the trader's manual 25%/50% "
        "practice: the statement scopes the override to the engine."
    )

    @classmethod
    def evaluate(cls, events: Sequence[Any]) -> RuleEvaluation:
        """PASS when the sequence is a conformant v1 exit, FAIL with every finding named.

        There is no NOT_APPLICABLE branch and that is deliberate: an EMPTY exit list is
        conformant, not unevaluable. A position that has not exited yet has zero tranches,
        which is at most one partial plus at most one runner, so the constraint holds and
        the rule can say so. Recording NOT_APPLICABLE there would make the commonest state
        in the record — an open position — indistinguishable from a rule that could not run.
        """
        findings = ladder_violations(events)
        values: dict[str, Any] = {
            "tranche_count": len(events),
            "max_tranches": MAX_TRANCHES,
            "partial_count": sum(1 for e in events if _reason(e) == PARTIAL_2R),
            "terminal_count": sum(1 for e in events if _reason(e) in TERMINAL_REASONS),
            "fractions": [_fraction(e) for e in events],
            "reasons": [_reason(e) for e in events],
            "ladder_signature": list(LADDER_SIGNATURE),
            "violations": [f.as_dict() for f in findings],
        }
        provenance: dict[str, Any] = {
            "tranche_count": derived("len(exit_events)"),
            "max_tranches": from_registry("EXIT-002", "output"),
            "partial_count": derived("count of exit_events with reason == PARTIAL_2R"),
            "terminal_count": derived(
                "count of exit_events with reason in (FINAL_TARGET, STOP_HIT, "
                "SESSION_CLOSE)"
            ),
            "fractions": derived("exit_events[].fraction"),
            "reasons": derived("exit_events[].reason"),
            "ladder_signature": from_registry("EXIT-002", "statement"),
            "violations": derived("EXIT-002 conformance check over exit_events"),
        }
        return cls.evaluation(
            "FAIL" if findings else "PASS", values=values, value_provenance=provenance
        )


def assert_v1_exit_shape(events: Sequence[Any]) -> None:
    """Raise if `events` is not a conformant v1 exit. For callers that want a hard stop.

    Separate from `evaluate` because the two have genuinely different jobs: telemetry
    records a violation and carries on, so the record of what the engine did survives; a
    caller about to ACT on a non-conformant exit wants to be stopped. Sharing
    `ladder_violations` means the two can never disagree about what a violation is.
    """
    findings = ladder_violations(events)
    if findings:
        raise ValueError(
            "EXIT-002 violation — v1 permits at most one partial plus one runner: "
            + "; ".join(f"[{f.code}] {f.detail}" for f in findings)
        )


__all__ = [
    "LADDER_SIGNATURE",
    "MAX_TRANCHES",
    "ConformanceFinding",
    "ExitEvent",
    "LadderOffForV1",
    "assert_v1_exit_shape",
    "ladder_violations",
]
