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
    #: False for a gate that is RECORDED AND NOT ACTED ON (T-0036 Stage A).
    #:
    #: An unenforced gate never sets `blocked_by`, so it cannot claim to be the reason a
    #: bar was declined. **The distinction is on the record rather than in the reader's
    #: head**: `passed=False, enforced=False` means *this would have blocked the trade and
    #: did not*, which is precisely the quantity Stage B needs before it may enforce.
    enforced: bool = True
    #: False when the condition COULD NOT BE READ -- the input was unavailable, not
    #: unfavourable.
    #:
    #: **"Could not look" must not share a representation with "looked and found nothing."**
    #: A calendar fetch that failed is not a bar with no news, and collapsing the two is
    #: precisely the fail-open `T-0035` closed one layer upstream. `passed` is False for such
    #: a gate -- the safe direction -- but `would_block_by` excludes it, because it did not
    #: say block either. It said nothing.
    evaluated: bool = True

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
            "values": self.values,
            "enforced": self.enforced,
            "evaluated": self.evaluated,
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
    #: Set when an ENFORCED gate stops the evaluation. None while still running.
    #:
    #: An observation (`observe`) never writes here, and that is load-bearing rather than
    #: tidy: `reasons` guards its census line with `blocked_by is None`, so a recorded
    #: would-block that touched this field would emit a record with no
    #: `candidates: N considered` line -- `B157`'s `B10` HALF exactly, rebuilt by a change
    #: that suppresses nothing. (`B10` was deliberately closed; `B157` carries it, and the
    #: TWO HALVES POINT OPPOSITE WAYS -- this is the MUST-EMIT one, because the zero here is
    #: a fact the evaluation OBSERVED, not an absence it never looked at.)
    blocked_by: str | None = None

    #: Did this bar get PAST every gate that can stop it, and reach the entry decision?
    #: (`B217`.)
    #:
    #: **THE POLARITY IS THE DESIGN, NOT A PREFERENCE.** `LIVE_NOT_REACHED` used to be keyed
    #: on `blocked_by`, which `gate()` sets for the THREE in-trace gates only — the FOUR
    #: loop-level blocks (kill switch, paused, already-in-a-position, max-concurrent) never
    #: touch it. A trace from a loop-blocked bar fell through to `bool(took_trade)` and
    #: recorded *"the live heuristic DECLINED"* for a bar it never evaluated.
    #:
    #: A NEGATIVE field — *"record why we blocked"* — is `B217` rebuilt: a block source added
    #: later that forgets to write it falls through to "reached", silently, in the unsafe
    #: direction. **A positive flag is covered by construction, because a new block source
    #: does nothing at all.**
    #:
    #: Set at ONE place: past the last enforced gate, before the POI work. **Not where
    #: detection runs** — detection precedes two of the three gates, so a flag set there would
    #: read True on bars `daily_bias` or `ltf_bos` went on to block, which is `B217` rebuilt
    #: inside the fix for `B217`.
    reached_entry_decision: bool = False

    # -- building -----------------------------------------------------------
    def gate(self, name: str, passed: bool, detail: str, **values: Any) -> bool:
        """Record a gate and return whether it passed, so call sites read as
        ``if not trace.gate(...): return``."""
        self.gates.append(Gate(name=name, passed=passed, detail=detail, values=values))
        if not passed and self.blocked_by is None:
            self.blocked_by = name
        return passed

    def observe(self, name: str, would_block: bool | None, detail: str, **values: Any) -> None:
        """Record a gate's verdict WITHOUT acting on it (T-0036 Stage A).

        **A GATE THAT HAS NEVER BEEN OBSERVED TO BLOCK ANYTHING MUST NOT BE GIVEN THE POWER
        TO BLOCK.** So a newly wired rule is recorded first and enforced only once the count
        of trades it would have stopped is non-zero and has been read by a human.

        Deliberately NOT `gate(..)` with the return ignored. `gate` sets `blocked_by` on a
        failing verdict, and two things follow that a caller ignoring the return would not
        see: `summary` would name this gate as the reason a bar was declined when it was
        not, and `reasons` would drop its census line, which is `B157`'s `B10` half --
        the MUST-EMIT direction, an observed zero. **The blocking
        channel makes the record claim a block; that is what the channel is for.**

        Returns nothing ON PURPOSE. There is no value here a caller could act on without
        defeating the staging, and `if not trace.observe(...)` reads like `gate` while
        meaning the opposite.
        """
        self.gates.append(
            Gate(
                name=name,
                # `would_block is None` -> NOT EVALUABLE. `passed=False` is the safe
                # direction for anything reading this field naively; `evaluated=False` is
                # what stops it being counted as a would-block.
                passed=(would_block is False),
                detail=detail,
                values=values,
                enforced=False,
                evaluated=would_block is not None,
            )
        )

    @property
    def would_block_by(self) -> list[str]:
        """Unenforced gates on THIS trace whose verdict was to block. A list, not a count.

        **NOT "Stage B's numerator", which is what this docstring said until B157.** This is a
        `list[str]` about ONE bar; a numerator is a population statistic. The aggregate
        vocabulary was used throughout this docstring, so a reader auditing the same claim in
        `news_context.py` came here and met a consistent register — **and consistency reads as
        corroboration**, which turns a check into a confirmation.

        Two DIFFERENT derivations sit on top of this, and they must be published together
        because they differ by a large factor:

            bars_where_news_would_block      GATE_NAME in trace.would_block_by
            trades_news_would_have_stopped   ... and trace.took_trade

        Observations are recorded BEFORE the enforcing gates, deliberately, so the verdict is
        present on every bar rather than only on bars surviving three unrelated gates. **That
        is why the bar-level list is not the trade-level count.**

        **Derived from the record rather than tallied beside it**, so neither figure can
        disagree with the trace it describes -- and a STORED trace can be re-derived later
        against a question nobody has asked yet.
        """
        return [
            g.name for g in self.gates
            if not g.enforced and g.evaluated and not g.passed
        ]

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
            # `g.enforced` is NOT optional here, and the bug it prevents is subtle enough
            # to be worth naming. Without it this takes the first NOT-PASSED gate of any
            # kind -- so a news observation recorded as would-block BEFORE an enforced gate
            # failed would have its detail returned as the reason the bar was declined,
            # while `blocked_by` correctly named the other gate. The two fields would
            # disagree, and the human-readable one is the one that would be believed.
            failed = next((g for g in self.gates if g.enforced and not g.passed), None)
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
        out = []
        for g in self.gates:
            if not g.evaluated:
                # NEITHER "PASS" NOR "WOULD-BLOCK". The condition was not read, and a record
                # that says either would be answering a question nobody asked.
                verdict = "NOT-EVALUATED"
            elif g.enforced:
                verdict = "PASS" if g.passed else "FAIL"
            else:
                # NOT "FAIL". A reader scanning for FAIL is looking for the reason a trade
                # did not happen, and this gate did not stop anything. WOULD-BLOCK says the
                # verdict and the fact that it was not acted on in one token.
                verdict = "OBSERVED" if g.passed else "WOULD-BLOCK"
            out.append(f"{verdict} {g.name}: {g.detail}")

        # The census line is UNCONDITIONAL. It used to be written only when there
        # were candidates, so a bar that passed every gate and then found no
        # fair-value gap produced a record ending after the last PASS — it read as
        # truncated, and 5 of the 137 declines in run 7d788ad6 were exactly that
        # (KNOWN_ISSUES B157, its `B10` half). "0 considered" is a finding; silence is an
        # ambiguity, and it is the same "nothing found vs never checked"
        # distinction the gates above are listed pass-or-fail to preserve.
        #
        # Only emitted once the evaluation actually reached the candidate stage.
        # A run stopped by a gate never looked, and claiming it considered zero
        # would be a different falsehood.
        if self.blocked_by is None:
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
            "would_block_by": self.would_block_by,
            "summary": self.summary,
            "gates": [g.as_dict() for g in self.gates],
            "candidates": self.candidates,
        }
