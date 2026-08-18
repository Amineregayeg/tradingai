"""GRADE-032 — BULLET TRAIN: the doctrinal name for incoming momentum that must not be faded.

*"An uninterrupted chain of momentum candles making new momentum imbalances, fresh gaps punching
through the concerning area, no deceleration and no counter micro-breaks."*

## FOUR CONDITIONS, AND ONLY THREE ARE READABLE — WHICH IS RECORDED, NOT ROUNDED

    chain of new momentum imbalances   READ    unmitigated imbalances in leg direction
    no counter micro-breaks            READ    PRIM-005 scale MICRO against the leg
    no deceleration                    READ    ordinal over the leg's unmitigated widths
    fresh gaps punching THROUGH the
      CONCERNING AREA                  NOT_READ — nothing produces a concerning area

**The fourth names an object no producer emits.** It is reported `NOT_READ` with the missing
producer named, `GATE-041`'s pattern — **not folded into the other three, and not silently dropped
from the count.** A regime call over three of four conditions is a different claim from one over
four, and the difference is invisible in the verdict.

## THE CHECKLIST IS THE OTHER HALF OF THE RULE, AND IT IS MOSTLY NOT OURS TO ANSWER

*"Before fading, the engine must run and record the diagnostic checklist: is there a deeper
concerning area? deeper liquidity? an unchecked timeframe? a missed institutional level or
candlestick? an economic-data release? a global event?"* — *"Momentum does not appear randomly,
there is always something happening that you are missing."*

**Six questions. The engine can answer ONE of them today** (the economic-data release, from the
calendar `T-0035`/`T-0036` wired). **The other five name objects nothing produces**, and the rule
says to RECORD the checklist rather than to pass it — so each item carries its own state and the
unanswered ones say who would answer them. **A checklist rendered as all-clear because nothing
could be checked is `B157` exactly: the richer the format, the more convincing the empty case.**

## NO SCALE IS INVENTED

`GRADE-032` has `values: null`. Every test here is structural or ordinal — **"no deceleration" is
read as *not increasing in the other direction* over the leg's own sequence, never against a `K`** —
and `GATE-035` bans `candle_body_size_threshold` and `impulse_candle_count_threshold` by name, so
"an uninterrupted chain of momentum candles" is read as **an uninterrupted chain of unmitigated
imbalances**, which is `GRADE-037`'s declared discriminator.
"""
from __future__ import annotations

from typing import Any, Sequence

from app.services.rules.base import RuleImplementation
from app.services.rules.grade_027_momentum_signs import (
    MOMENTUM_CLASSIFICATION_NOTE,
    MomentumLeg,
    _is_decreasing,
)
from app.services.rules.prim_005_breaks import BreakEvent
from app.services.telemetry.records import derived, from_record

#: The six diagnostic questions, with the producer that would answer each. `None` means NO
#: producer exists — which is not the same as one that answered nothing.
DIAGNOSTIC_CHECKLIST: tuple[tuple[str, str | None], ...] = (
    ("deeper_concerning_area", None),
    ("deeper_liquidity", None),
    ("unchecked_timeframe", None),
    ("missed_institutional_level_or_candlestick", None),
    ("economic_data_release", "gate_015_calendar_scope"),
    ("global_event", None),
)


class BulletTrainRegime(RuleImplementation):
    """GRADE-032: is this leg a bullet train, and what does the checklist say?"""

    RULE_ID = "GRADE-032"

    COVERAGE_NOTE = (
        "PARTIAL, AND THE UNREADABLE PARTS ARE NAMED RATHER THAN DROPPED. Three of the four "
        "regime conditions are read structurally; the fourth needs a CONCERNING AREA and no "
        "producer emits one. Of the six checklist questions the engine can answer ONE -- the "
        "economic-data release, via GATE-015 -- and the other five name objects nothing "
        "produces. Both are reported NOT_READ with the producer named (GATE-041's pattern) so a "
        "regime call over three of four is not read as a call over four. No scale is invented: "
        "GRADE-032 has values null and GATE-035 bans candle_body_size_threshold and "
        "impulse_candle_count_threshold by name, so 'a chain of momentum candles' is read as a "
        "chain of UNMITIGATED imbalances -- GRADE-037's declared discriminator. NOT WIRED."
    )

    @classmethod
    def conditions(
        cls, leg: MomentumLeg, breaks: Sequence[BreakEvent] = ()
    ) -> dict[str, dict[str, Any]]:
        left_behind = sorted(leg.unmitigated, key=lambda i: i.formed_index or 0)
        counter_micro = [
            b for b in breaks
            if b.bar_index is not None and leg.start_index < b.bar_index <= leg.end_index
            and str(getattr(b, "scale", "")) == "MICRO"
            and leg.direction is not None and str(b.direction) != str(leg.direction)
        ]
        decreasing = _is_decreasing(leg.widths)
        return {
            "uninterrupted_chain_of_momentum_imbalances": {
                "state": bool(left_behind) if left_behind or leg.imbalances else None,
                "count": len(left_behind),
                "coordinates": [
                    {"imbalance_id": i.id, "bar_index": i.formed_index} for i in left_behind
                ],
            },
            "no_counter_micro_breaks": {
                "state": None if leg.direction is None else not counter_micro,
                "counter_micro_breaks": len(counter_micro),
                "coordinates": [
                    {"break_id": b.id, "bar_index": b.bar_index, "direction": b.direction}
                    for b in counter_micro
                ],
            },
            "no_deceleration": {
                # ORDINAL. `_is_decreasing` returns None on fewer than two widths -- nothing to
                # compare is not "no deceleration", and treating it as the latter would be the
                # absent/empty collapse this cluster keeps meeting.
                "state": None if decreasing is None else not decreasing,
                "widths": list(leg.widths),
            },
            "fresh_gaps_through_the_concerning_area": {
                "state": None,
                "not_read": "concerning_area",
                "producer": None,
                "note": "no producer emits a concerning area — this is NOT 'no fresh gaps'",
            },
        }

    @classmethod
    def checklist(cls, economic_release: bool | None = None) -> dict[str, dict[str, Any]]:
        """The six diagnostic questions, RECORDED — the rule asks for a record, not a pass.

        `economic_release` is the one answerable today. **`None` for it means NOT ASKED**, which
        is distinct from `False`; the caller supplies `False` only when a calendar was actually
        read and had nothing.
        """
        out: dict[str, dict[str, Any]] = {}
        for name, producer in DIAGNOSTIC_CHECKLIST:
            if name == "economic_data_release":
                out[name] = {
                    "answered": economic_release is not None,
                    "state": economic_release,
                    "producer": producer,
                }
            else:
                out[name] = {"answered": False, "state": None, "producer": producer,
                             "note": "no producer exists — recorded as unanswered, not as clear"}
        return out

    @classmethod
    def evaluate(
        cls,
        leg: MomentumLeg | None = None,
        breaks: Sequence[BreakEvent] = (),
        *,
        economic_release: bool | None = None,
    ) -> Any:
        """NOT_APPLICABLE without a leg; otherwise PASS when the readable conditions all hold.

        **PASS means "bullet train on the evidence available", and `conditions_not_read` is in
        the same record so that claim cannot be read as the full four.**
        """
        if leg is None:
            return cls.evaluation(
                "NOT_APPLICABLE",
                values={
                    "legs_examined": 0,
                    "reason": "no leg supplied — fewer than two breaks bound no span",
                    "checklist": cls.checklist(economic_release),
                    "momentum_classification": MOMENTUM_CLASSIFICATION_NOTE,
                },
                value_provenance={
                    "legs_examined": derived("count of legs this evaluation read"),
                    "reason": derived("why no verdict was reached"),
                    "checklist": derived("GRADE-032's six diagnostic questions, recorded"),
                    "momentum_classification": derived("GATE-035 conformance note"),
                },
            )

        conditions = cls.conditions(leg, breaks)
        readable = {n: c for n, c in conditions.items() if c["state"] is not None}
        not_read = [n for n, c in conditions.items() if c["state"] is None]
        checklist = cls.checklist(economic_release)
        return cls.evaluation(
            "PASS" if readable and all(c["state"] for c in readable.values()) else "FAIL",
            values={
                "legs_examined": 1,
                "leg": leg.as_dict(),
                "conditions": conditions,
                "conditions_read": len(readable),
                # PUBLISHED BESIDE THE VERDICT. A regime call over three of four conditions is
                # not the claim a call over four would be, and the verdict cannot say which.
                "conditions_total": len(conditions),
                "conditions_not_read": not_read,
                "checklist": checklist,
                "checklist_answered": sum(1 for c in checklist.values() if c["answered"]),
                "checklist_total": len(checklist),
                "momentum_classification": MOMENTUM_CLASSIFICATION_NOTE,
            },
            value_provenance={
                "leg": from_record("primitives.breaks"),
                "conditions": derived("GRADE-032's four regime conditions"),
                "conditions_read": derived("how many reached a state"),
                "conditions_total": derived("the statement's four"),
                "conditions_not_read": derived("conditions whose producer does not exist"),
                "checklist": derived("GRADE-032's six diagnostic questions, recorded"),
                "checklist_answered": derived("how many had a producer that answered"),
                "checklist_total": derived("the statement's six"),
                "legs_examined": derived("count of legs this evaluation read"),
                "momentum_classification": derived("GATE-035 conformance note"),
            },
        )
