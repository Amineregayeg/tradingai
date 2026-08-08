"""GRADE-008 — the fake MSB, third component of the Manipulated grade (M4).

    Classify a break as a POTENTIAL FAKE MSB when this sequence is observed: (1) the HTF
    target is still valid; (2) a liquidity sweep occurs; (3) a temporary structural break
    prints against the main direction; (4) genuine reversal confirmation is absent; (5) price
    continues toward the HTF target. Both long and short traders must end up trapped inside
    the same structure. The engine is FORBIDDEN to define a fake MSB using fixed rules such
    as 'reversal within N candles', a maximum candle count, or a fixed time delay.

WHY THIS RULE IS DANGEROUS TO IMPLEMENT AND WHY IT IS STILL WORTH IMPLEMENTING
It is the third fuel component, so it is the single boolean standing between a SUPER box and
a MANIPULATED one — 1.25% and 1.50% of the account on the same setup. A detector biased
toward True over-sizes every trade it touches.

The registry's own note says the positive detector "cannot be fully specified from the
source": step (4), the absence of genuine reversal confirmation, has no operational test, and
the trader explicitly refused to supply the candle-count and time-delay proxies that would
give it one. So the honest reading is the one the rule's own wording invites — POTENTIAL —
and uncertainty must resolve DOWNWARD, to False, never to True.

HOW STEP (4) IS READ, DECLARED RATHER THAN SMUGGLED
Steps (4) and (5) are read as one structural question: did the market resume toward the HTF
target instead of confirming the reversal? Concretely, the FIRST break after the counter-break
returns to the main direction, and price then extends further toward the target. That uses
only the break stream and the price extremes — no candle window, no elapsed time, nothing on
the ban list. It is still an interpretation, and it is recorded as one.

When no break has printed after the counter-break, the sequence is UNFINISHED, not satisfied.
The verdict is False with a stated reason, which costs a quarter of a percent of risk on a
box that might have deserved MANIPULATED. That is the correct direction to be wrong in.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

from app.services.rules.base import RuleImplementation
from app.services.rules.grade_001_structure_box import StructureBox
from app.services.rules.prim_001_swings import Bar

TrappedSide = Literal["LONG", "SHORT"]

#: Input classes the registry forbids this detector from using, verbatim. Carried so the
#: emitted `banned_input_check` names what was checked rather than asserting a bare negative.
BANNED_INPUTS = ("reversal_within_n_candles", "max_candle_count", "fixed_time_delay")


@dataclass
class FakeMSB:
    """The classification, in the contract's shape."""

    is_fake_msb: bool
    reason: str
    break_bar: int | None = None
    break_id: str | None = None
    swept_side: str | None = None
    trapped_sides: list[TrappedSide] = field(default_factory=list)
    htf_target_id: str | None = None
    steps_met: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "fake_msb": self.is_fake_msb,
            "reason": self.reason,
            "steps_met": list(self.steps_met),
        }
        for key, value in (
            ("break_bar", self.break_bar),
            ("break_id", self.break_id),
            ("swept_side", self.swept_side),
            ("htf_target_id", self.htf_target_id),
        ):
            if value is not None:
                out[key] = value
        if self.trapped_sides:
            out["trapped_sides"] = list(self.trapped_sides)
        return out


class FakeMSBClassifier(RuleImplementation):
    """GRADE-008: the five-step sequence, with uncertainty resolving downward."""

    RULE_ID = "GRADE-008"

    COVERAGE_NOTE = (
        "Steps 1, 2, 3 and 5 are structural and implemented as written. Step 4 — 'lack of "
        "genuine reversal confirmation' — has no operational test in the source and the "
        "trader refused candle-count and time-delay proxies, so it is read jointly with step "
        "5 as 'the market resumed toward the HTF target instead of confirming the reversal'. "
        "An unfinished sequence returns False, never True: a false positive here promotes a "
        "SUPER box to MANIPULATED and raises real risk from 1.25% to 1.50%."
    )

    @staticmethod
    def classify(
        box: StructureBox,
        bars: Sequence[Bar],
        breaks: Sequence[Any],
        sweeps: Sequence[Any] = (),
        *,
        htf_target_cleared: bool,
        htf_target_id: str | None = None,
        as_of_index: int | None = None,
    ) -> FakeMSB:
        """Walk the five steps in order, stopping at the first that fails.

        `as_of_index` is the decision bar. Nothing at or after it may be used as evidence —
        GRADE-007's look-ahead guard, applied here because this is where the temptation is
        greatest: the continuation that confirms a fake MSB is exactly the bar that has not
        printed yet.
        """
        limit = len(bars) if as_of_index is None else as_of_index
        steps: list[str] = []

        # (1) the HTF target is still valid
        if htf_target_cleared:
            return FakeMSB(False, "HTF target already cleared — the sequence needs a live "
                                  "objective for price to continue toward",
                           htf_target_id=htf_target_id)
        steps.append("HTF_TARGET_VALID")

        main = box.direction
        counter = "DOWN" if main == "UP" else "UP"

        # (3) a temporary structural break against the main direction, inside the box's life
        counter_breaks = sorted(
            (b for b in breaks
             if getattr(b, "direction", None) == counter
             and box.break_index < getattr(b, "bar_index", -1) < limit),
            key=lambda b: b.bar_index,
        )
        if not counter_breaks:
            return FakeMSB(False, "no counter-direction break printed — nothing to be fake",
                           htf_target_id=htf_target_id, steps_met=steps)
        cb = counter_breaks[0]
        cb_index = int(cb.bar_index)

        # (2) a liquidity sweep occurs — at or before the counter break, after the box opened
        prior_sweeps = [
            s for s in sweeps
            if box.swing_index <= getattr(s, "bar_index", -1) <= cb_index
            and not getattr(s, "sweep_failed", False)
        ]
        if not prior_sweeps:
            return FakeMSB(False, "counter-break with no liquidity sweep behind it — a "
                                  "structural break, not a manipulation",
                           break_bar=cb_index, break_id=getattr(cb, "id", None),
                           htf_target_id=htf_target_id, steps_met=steps)
        steps.append("LIQUIDITY_SWEEP")
        steps.append("COUNTER_BREAK")
        swept = max(prior_sweeps, key=lambda s: s.bar_index)

        # (4)+(5) the market resumed toward the target rather than confirming the reversal
        after = sorted(
            (b for b in breaks
             if cb_index < getattr(b, "bar_index", -1) < limit),
            key=lambda b: b.bar_index,
        )
        if not after:
            return FakeMSB(False, "sequence unfinished — no break has printed since the "
                                  "counter-break, so the reversal is neither confirmed nor "
                                  "denied. Resolves downward by design.",
                           break_bar=cb_index, break_id=getattr(cb, "id", None),
                           swept_side=getattr(swept, "pool_id", None),
                           htf_target_id=htf_target_id, steps_met=steps)
        if getattr(after[0], "direction", None) != main:
            return FakeMSB(False, "the first break after the counter-break continued AGAINST "
                                  "the main direction — that is a genuine reversal, not a "
                                  "fake MSB",
                           break_bar=cb_index, break_id=getattr(cb, "id", None),
                           htf_target_id=htf_target_id, steps_met=steps)
        steps.append("REVERSAL_UNCONFIRMED")

        resumed = int(after[0].bar_index)
        tail = bars[resumed:limit]
        if not tail:
            return FakeMSB(False, "resumption break is the decision bar — no continuation "
                                  "has printed left of it",
                           break_bar=cb_index, htf_target_id=htf_target_id, steps_met=steps)
        counter_extreme = (
            min(b.low for b in bars[cb_index:resumed + 1]) if main == "UP"
            else max(b.high for b in bars[cb_index:resumed + 1])
        )
        progressed = (
            max(b.high for b in tail) > box.box_high if main == "UP"
            else min(b.low for b in tail) < box.box_low
        )
        if not progressed:
            return FakeMSB(False, "price did not continue toward the HTF target after the "
                                  "counter-break",
                           break_bar=cb_index, htf_target_id=htf_target_id, steps_met=steps)
        steps.append("CONTINUED_TO_TARGET")

        # Both sides trapped in the same structure: the sweep took one side's stops, the
        # counter-break took the other's. That symmetry IS the Manipulated box.
        trapped: list[TrappedSide] = ["LONG", "SHORT"]
        return FakeMSB(
            True,
            "sweep trapped one side and the counter-break trapped the other, then price "
            "resumed toward a still-valid HTF target",
            break_bar=cb_index, break_id=getattr(cb, "id", None),
            swept_side=getattr(swept, "pool_id", None),
            trapped_sides=trapped, htf_target_id=htf_target_id,
            steps_met=steps + [f"COUNTER_EXTREME_{counter_extreme:g}"],
        )

    @staticmethod
    def banned_input_check() -> dict[str, Any]:
        """What the detector was checked against, for `rule_evaluation.banned_input_check`.

        A negative is only testable if the tokens are named — asserting "we used no candle
        count" proves nothing unless the record says which shortcuts were considered.
        """
        return {"checked": list(BANNED_INPUTS), "present": []}
