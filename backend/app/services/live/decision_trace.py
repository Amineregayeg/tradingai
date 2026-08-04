"""Why the engine did — or more often did not — take a trade (task 2.3).

THE PROBLEM THIS SOLVES
The engine reported WHAT it decided ("BTC/USD 1H bar closed — no valid setup")
and threw away WHY. To verify that a strategy is being executed correctly you
need the reasoning: which conditions held, which did not, and how close it came.

MOST OF WHAT AN HONEST STRATEGY DOES IS DECLINE. Over the corrected backtest
window the engine entered on 27% of days and passed on the rest, so the refusals
ARE the strategy — and they were the part with no record at all. "No valid
setup" is indistinguishable from "the detector is broken and never fires", which
is exactly the question a simulation is supposed to answer.

WHY THIS IS NOT JUST LOGGING
`DecisionRecord` has carried `abstained`, `reasons` and an `ABSTAINED` outcome
since it was written — its own docstring says a row is created "whether it
produced a signal or abstained". Nothing ever wrote one: rows appeared only when
an order filled. The schema for honest abstention existed and was unused, so
this fills it rather than inventing a parallel mechanism.

DESIGN RULE: a gate records the VALUES it compared, not just its verdict.
"premium/discount rejected it" is a fact; "entry 62150 was above equilibrium
61980, and longs are only taken below" is something you can check.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Gate:
    """One condition the engine evaluated, and the numbers behind its verdict."""

    name: str
    passed: bool
    detail: str
    values: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
            "values": self.values,
        }


@dataclass
class DecisionTrace:
    """The full reasoning behind one bar's decision."""

    symbol: str
    timeframe: str
    bar_time: str | None = None
    gates: list[Gate] = field(default_factory=list)

    #: Fair-value gaps present on this bar, and what happened to each. This is
    #: the detail that distinguishes "the strategy correctly saw nothing worth
    #: taking" from "the detector found nothing at all" — outcomes that look
    #: identical from the outside and mean opposite things.
    candidates: list[dict] = field(default_factory=list)

    took_trade: bool = False
    #: Set when a gate stops the evaluation. None while still running.
    blocked_by: str | None = None

    # -- building -----------------------------------------------------------
    def gate(self, name: str, passed: bool, detail: str, **values: Any) -> bool:
        """Record a gate and return whether it passed, so call sites read as
        ``if not trace.gate(...): return``."""
        self.gates.append(Gate(name=name, passed=passed, detail=detail, values=values))
        if not passed and self.blocked_by is None:
            self.blocked_by = name
        return passed

    def candidate(self, index: int, direction: str, accepted: bool, reason: str, **values: Any) -> None:
        self.candidates.append({
            "index": index, "direction": direction,
            "accepted": accepted, "reason": reason, "values": values,
        })

    # -- reading ------------------------------------------------------------
    @property
    def summary(self) -> str:
        """One line a human can read without expanding anything."""
        if self.took_trade:
            return "entry taken"
        if self.blocked_by:
            failed = next((g for g in self.gates if not g.passed), None)
            return failed.detail if failed else f"blocked at {self.blocked_by}"
        if self.candidates:
            rejected = [c for c in self.candidates if not c["accepted"]]
            if rejected:
                # Name the most common rejection rather than listing all of
                # them: the pattern is the useful signal.
                counts: dict[str, int] = {}
                for c in rejected:
                    counts[c["reason"]] = counts.get(c["reason"], 0) + 1
                top, n = max(counts.items(), key=lambda kv: kv[1])
                return f"{len(rejected)} FVG candidate(s), none valid — mostly: {top} ({n})"
        return "no FVG candidates in range"

    @property
    def reasons(self) -> list[str]:
        """Short strings for ``DecisionRecord.reasons``.

        Every gate is included, passed or failed. A record of only the failures
        cannot tell you whether the others were even evaluated — the same
        "no findings vs nothing checked" ambiguity the reconciliation and data
        health surfaces avoid.
        """
        out = [f"{'PASS' if g.passed else 'FAIL'} {g.name}: {g.detail}" for g in self.gates]
        if self.candidates:
            accepted = sum(1 for c in self.candidates if c["accepted"])
            out.append(
                f"candidates: {len(self.candidates)} considered, {accepted} accepted"
            )
            for c in self.candidates:
                if not c["accepted"]:
                    out.append(f"  rejected #{c['index']} ({c['direction']}): {c['reason']}")
        return out

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "bar_time": self.bar_time,
            "took_trade": self.took_trade,
            "blocked_by": self.blocked_by,
            "summary": self.summary,
            "gates": [g.as_dict() for g in self.gates],
            "candidates": self.candidates,
        }
