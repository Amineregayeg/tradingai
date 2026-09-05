"""The ENTRY seam — the rule modules evaluated ALONGSIDE the live decision, deciding nothing.

## WHAT THIS IS AND WHAT IT IS NOT

`live/strategy_step.py` decides the entry with the **backtest engine** and imports **zero** rule
modules, so `ENTRY-001` and its neighbours are implemented, tested, and have no path to execution.
This is the harness that gives them one — **parallel evaluation, both verdicts recorded, and no
influence on the decision.**

> **THE VALUE HERE IS THE SEAM, NOT THE RATE.** A disagreement rate over one rule is thin and must
> not be dressed as more. What a later cutover task needs is this harness — the triple, the
> `NOT_COMPARABLE` reasons, the failure isolation — and **the one-rule rate is its first tenant
> rather than its purpose.**

## IT RUNS AFTER THE DECISION HAS ALREADY RETURNED

`compare_entry` is called by `crypto_loop` on the trace `evaluate_latest_bar_traced` produced. **Not
a single line inside the decision function is touched**, so *"change no decision"* is structural
rather than tested-into-place: **this code cannot influence a decision that has already been made.**

## THE PUBLISHED FIGURE IS A TRIPLE. A SCALAR CANNOT CARRY THREE OUTCOMES.

    per bar, per rule:  AGREE | DISAGREE | NOT_COMPARABLE(reason)
    published:          disagree=N  agree=M  not_comparable=K     <- always all three
    rate := N / (M + N)                                           <- K is NEVER in the denominator
    if M + N == 0:      "undefined (0 comparable)"                <- NEVER 0%

**`K` is folded into neither side.** Folding it into the denominator makes silence look like
agreement; folding it into the numerator makes silence look like disagreement — **both lies pointing
opposite ways, which is how you know it does not belong in the fraction.** `B157` is the same rule
at the per-record layer: *a format that enumerates its inputs must refuse to render when it had
none.*

## SCOPE — ONE RULE IS IN THE DENOMINATOR, AND FOUR ARE NOT

Established by measuring each rule's SHAPE rather than reading its name:

    ENTRY-001   def evaluate -> PASS/FAIL on a real proposition        COMPARABLE
    GATE-038    `return cls.evaluation("PASS" if setup_valid else ...)`
                an IDENTITY on its own argument. Fed the live verdict it agrees BY
                CONSTRUCTION; fed ENTRY-001's it is a duplicate term. Either way it
                inflates the denominator with something that cannot disagree, which
                moves the published rate in the REASSURING direction.       CONFORMANCE
    GATE-037    a conformance check over a decision record's PATHS -- a property of
                the code, not of the bar, so per-bar it is a constant.       CONFORMANCE
    GRADE-001/002/008   producer / predicate / classifier, no `evaluate` at all. They
                emit objects and labels; the live path emits `Signal | None`. There is
                no live-side counterpart for a disagreement to be a disagreement WITH.
                                                                             COVERAGE

**So every figure this module produces says "1 of 6" beside it.** Anyone reading *"the entry seam"*
as covering all six is reading a claim the record must not make.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Sequence

from app.services.rules.entry_001_imbalance_poi import ImbalanceIsTheOnlyEntryPOI
from app.services.rules.grade_001_structure_box import StructureBoxes
from app.services.rules.prim_001_swings import Bar, SwingPoints
from app.services.rules.prim_002_imbalances import ImbalanceInventory
from app.services.rules.prim_005_breaks import BreakEvents
from app.services.live.shadow import schema_tf

#: The name the comparison is recorded under on `DecisionTrace`.
GATE_NAME = "entry_rule_comparison"

#: The one rule whose verdict is comparable with the live decision. See the module docstring.
COMPARABLE_RULE_IDS: tuple[str, ...] = ("ENTRY-001",)

#: The id a row is keyed by. See the alias note in `compare_entry`.
registered_id = "ENTRY-001"

#: Suffixes the rules already use for "how many inputs did I look at". Read rather than
#: enumerated per rule, so a rule nobody has wired yet is covered on the day it is.
#:
#: **THIS IS THE HARNESS'S GENERAL DEFENCE AND `at_price` WAS ONLY ONE INSTANCE OF IT.** Every
#: parameter of every bar-shaped `evaluate` is defaulted, so `evaluate()` with no arguments
#: compiles and returns a verdict for all of them — a property of the `RuleImplementation`
#: convention, not of any one rule. Measured across the 67 registered rules: 9 are callable with
#: zero arguments, of which 3 EXPOSE THEIR OWN EMPTINESS in `values` (`ENTRY-001`
#: `candidates_considered`, `GATE-037` `paths_examined`, `GATE-038`
#: `amplifier_levels_examined`), 4 decline with `NOT_APPLICABLE`, and 2 are constant by nature.
#:
#: **So the emptiness is DERIVED — the rule ran and its own values say it examined nothing —
#: rather than asserted at one call site.** `B157`'s `B10` half implemented inside the rules: *0
#: examined* recorded rather than left silent, and the harness consumes a discriminator the
#: rules already publish instead of inventing one.
#:
#: `_count` is deliberately NOT here: `amplifier_count` is an OUTPUT count, and a rule that
#: found nothing is not a rule that looked at nothing.
INPUT_COUNT_SUFFIXES: tuple[str, ...] = ("_examined", "_considered")

Outcome = Literal["AGREE", "DISAGREE", "NOT_COMPARABLE"]

#: WHICH SIDE could not answer. The fixes differ, so the reasons must not collapse.
NotComparable = Literal[
    "RULE_NOT_EVALUABLE",  # the rule could not reach a verdict
    "LIVE_NOT_REACHED",    # the live path returned before the comparison point
    "INPUT_ABSENT",        # neither side had what it needed
    "RULE_RAISED",         # the rule or the adapter threw -- see `compare_entry`
]


@dataclass(frozen=True)
class RuleComparison:
    """One rule's verdict set against the live decision on one bar."""

    rule_id: str
    outcome: Outcome
    live_verdict: bool | None
    rule_verdict: str | None
    reason: NotComparable | None = None
    detail: str = ""
    #: Set when the rule returned a DIFFERENT id than the one it is registered under.
    alias_of: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "rule_id": self.rule_id,
            "outcome": self.outcome,
            "live_verdict": self.live_verdict,
            "rule_verdict": self.rule_verdict,
            "detail": self.detail,
        }
        if self.reason is not None:
            out["not_comparable_reason"] = self.reason
        if self.alias_of is not None:
            out["returned_rule_id"] = self.alias_of
        return out


#: The two populations `disagree` merges, and they carry OPPOSITE risk (`B177`).
#:
#:     RULE_STRICTER   live entered, the rule would not   -> missed opportunity
#:     RULE_LOOSER     live declined, the rule would      -> NEW LIVE EXPOSURE
#:
#: `T-0040`'s criterion turns on exactly this split — *"rules stricter is not the same risk as
#: rules looser"* — and `disagree=3` cannot answer it, because three looser and three stricter
#: render identically.
Direction = Literal["RULE_STRICTER", "RULE_LOOSER"]


def disagreement_direction(c: "RuleComparison") -> Direction | None:
    """Which way a DISAGREE went. **The ONE site that decides this.**

    Keyed on BOTH members of the pair, deliberately. Direction is derivable from
    `live_verdict` alone today — a DISAGREE means `rule_says_entry != live_verdict`, so the
    rule's side is the negation — but keying it on one field would make the must-fail arm
    (swap the two and the buckets must move) pass for the wrong reason: swapping puts a
    *string* in `live_verdict`, and every non-empty string is truthy, so a one-field classifier
    would report every disagreement as one direction and never notice.

    **RECORDED AT EMISSION, never reconstructed after the fact.** `B213`: in the live corpus
    the single disagreement's direction IS recoverable by joining `signal_dir`/`outcome`/
    `sized_units` — but only because `disagree == 1` and `agree == 0`. That join breaks on
    `disagree > 1`, on rows where agree and disagree are both non-zero, and on any bar where
    live declined and there is no signal row to join against. **It works on exactly the rows
    nobody needs it for**, so a reconstruction would be validated against the one row that
    cannot falsify it and ship green while being silently wrong on the first interesting bar.

    `None` for anything that is not a DISAGREE, and — defensively — for a DISAGREE whose
    `live_verdict` is not a bool. That second case is unreachable today (a `None` verdict is
    `LIVE_NOT_REACHED` and short-circuits to `NOT_COMPARABLE` before this point), and it is
    still not folded into a bucket: an unknown direction counted as either one would be a
    wrong answer where `direction_unknown` is a visible one.
    """
    if c.outcome != "DISAGREE" or not isinstance(c.live_verdict, bool):
        return None
    rule_says_entry = c.rule_verdict == "PASS"
    if c.live_verdict and not rule_says_entry:
        return "RULE_STRICTER"
    if rule_says_entry and not c.live_verdict:
        return "RULE_LOOSER"
    return None


@dataclass(frozen=True)
class ProducerRecord:
    """A rule that emits objects rather than a verdict. COVERAGE, never the denominator."""

    rule_id: str
    produced: bool
    count: int | None = None
    missing_input: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"rule_id": self.rule_id, "produced": self.produced}
        if self.count is not None:
            out["count"] = self.count
        if self.missing_input is not None:
            # NAMED, not just absent. "Not produced" and "not produced BECAUSE X is not built
            # on this path" are different findings and only the second is actionable.
            out["missing_input"] = self.missing_input
        return out


@dataclass(frozen=True)
class EntryComparison:
    """One bar's parallel evaluation: the comparison column and the coverage column."""

    comparisons: tuple[RuleComparison, ...] = ()
    producers: tuple[ProducerRecord, ...] = ()
    inventory_size: int | None = None
    at_price: float | None = None

    @property
    def agree(self) -> int:
        return sum(1 for c in self.comparisons if c.outcome == "AGREE")

    @property
    def disagree(self) -> int:
        return sum(1 for c in self.comparisons if c.outcome == "DISAGREE")

    @property
    def not_comparable(self) -> int:
        return sum(1 for c in self.comparisons if c.outcome == "NOT_COMPARABLE")

    def _directions(self) -> list[Direction | None]:
        """Only DISAGREE rows have a direction. A `NOT_COMPARABLE` outcome has none, and an
        AGREE has nothing to point at — so the split is defined on the DISAGREEING population
        and `rule_stricter + rule_looser + direction_unknown == disagree` is total."""
        return [
            disagreement_direction(c) for c in self.comparisons if c.outcome == "DISAGREE"
        ]

    @property
    def rule_stricter(self) -> int:
        """Live entered, the rule would not. **Missed opportunity.**"""
        return sum(1 for d in self._directions() if d == "RULE_STRICTER")

    @property
    def rule_looser(self) -> int:
        """Live declined, the rule would have entered. **NEW LIVE EXPOSURE.**"""
        return sum(1 for d in self._directions() if d == "RULE_LOOSER")

    @property
    def direction_unknown(self) -> int:
        """A DISAGREE whose direction could not be read. Zero on every path that exists.

        It is here so the invariant is TOTAL rather than true-by-luck: without it a future
        DISAGREE with a non-bool verdict would silently make `stricter + looser < disagree`,
        and a count that quietly stops adding up is the failure this whole harness is about.
        """
        return sum(1 for d in self._directions() if d is None)

    @property
    def detail(self) -> str:
        """One line for `DecisionTrace.reasons`. Always all three terms, never a bare rate."""
        comparable = self.agree + self.disagree
        rate = (
            "undefined (0 comparable)"
            if comparable == 0
            else f"{self.disagree / comparable:.3f}"
        )
        # THE SPLIT RIDES ON `detail` BECAUSE `detail` IS THE ONLY THING THAT REACHES THE
        # DATABASE. `values()` was always right and has never been persisted: `Gate.values`
        # is read only by `Gate.as_dict()`, whose only caller is `DecisionTrace.as_dict()`,
        # which has ZERO callers in `app/`. `record_on` passes `self.detail` as the third
        # positional argument to `trace.observe` and the kwargs alongside it — the third
        # argument survives into `DecisionRecord.reasons`, the kwargs do not.
        unknown = (
            f" direction_unknown={self.direction_unknown}"
            if self.direction_unknown
            else ""
        )
        return (
            f"entry rules: disagree={self.disagree} "
            f"(rule_stricter={self.rule_stricter} rule_looser={self.rule_looser}{unknown}) "
            f"agree={self.agree} "
            f"not_comparable={self.not_comparable} rate={rate} "
            f"[{len(COMPARABLE_RULE_IDS)} of 6 rules comparable]"
        )

    def values(self) -> dict[str, Any]:
        comparable = self.agree + self.disagree
        return {
            "comparisons": [c.as_dict() for c in self.comparisons],
            "producers": [p.as_dict() for p in self.producers],
            "agree": self.agree,
            "disagree": self.disagree,
            # The same two integers the string carries, so the in-memory path and any future
            # `.gates` consumer cannot disagree with what reached the database.
            "rule_stricter": self.rule_stricter,
            "rule_looser": self.rule_looser,
            "direction_unknown": self.direction_unknown,
            "not_comparable": self.not_comparable,
            # THE DENOMINATOR IS PUBLISHED, ALWAYS. A rate whose denominator can be zero must
            # publish its denominator: a ratio hides exactly one number and it is always the
            # one that says whether the ratio means anything.
            "comparable": comparable,
            "disagreement_rate": (
                None if comparable == 0 else round(self.disagree / comparable, 6)
            ),
            "comparable_rule_ids": list(COMPARABLE_RULE_IDS),
            "rules_named_by_the_task": 6,
            "imbalance_inventory": self.inventory_size,
            "at_price": self.at_price,
        }

    def record_on(self, trace: Any) -> None:
        """UNENFORCED, via `trace.observe`. This decides nothing and stops nothing.

        `would_block=False` because a comparison is not a verdict about the trade — it never
        blocks, and recording it as a would-block would put it in `would_block_by`, which is
        a different rule's numerator.
        """
        trace.observe(GATE_NAME, False, self.detail, **self.values())


def examined_nothing(values: dict[str, Any]) -> bool:
    """Do the rule's OWN values say it looked at no inputs?

    Requires at least one input-count key: a rule that publishes no such count has not said it
    examined nothing, and treating silence as emptiness is the collapse this harness exists to
    avoid. **"Could not look" and "looked and found nothing" must not share a representation.**
    """
    counts = [
        v for k, v in values.items()
        if any(k.endswith(sfx) for sfx in INPUT_COUNT_SUFFIXES) and isinstance(v, (int, float))
    ]
    return bool(counts) and all(c == 0 for c in counts)


def _live_entry_verdict(trace: Any) -> tuple[bool | None, NotComparable | None]:
    """What the live path decided, or why there is nothing to compare against.

    A bar that never reached the candidate loop has no opinion about whether an entry POI
    existed. **That is `LIVE_NOT_REACHED`, and it is not agreement** — counting it as
    agreement is the failure this whole triple exists to prevent.

    **`B217`: THIS USED TO ASK `blocked_by`, WHICH COVERS THREE OF SEVEN BLOCK SOURCES.**
    `trace.gate()` sets it for the three IN-TRACE gates; the four LOOP-LEVEL blocks — kill
    switch, paused, already-in-a-position, max-concurrent — never touch it. A trace from a
    loop-blocked bar fell through to `bool(took_trade)` and recorded `live_verdict=False`,
    *"the live heuristic DECLINED"*, for a bar it never evaluated.

    **The error is ASYMMETRIC and both halves argue FOR the cutover:** a rules-FAIL on such a
    bar scores AGREE, a rules-PASS scores DISAGREE labelled RULES-LOOSER — the category
    `T-0040` treats as new live exposure.

    **`blocked_by` is SUBSUMED, not consulted alongside.** Every bar it would have caught sets
    the flag False by never reaching the landmark, so reading both would be two statements of
    one fact — `GATE-011` — and they could drift.

    **The `False` default is REQUIRED.** `trace` is typed `Any` here, so this is a `getattr`;
    a `True` default fails open, silently, forever, on every caller that passes an object
    without the field.
    """
    if not getattr(trace, "reached_entry_decision", False):
        return None, "LIVE_NOT_REACHED"
    return bool(getattr(trace, "took_trade", False)), None


def compare_entry(trace: Any, bars: Sequence[Bar], *, tf: str) -> EntryComparison:
    """Evaluate the entry rules against the live decision that has ALREADY been made.

    FAILURE ISOLATION IS THE CONTRACT, not a precaution. Everything below runs inside one
    `try` and any exception becomes `NOT_COMPARABLE(RULE_RAISED)` carrying the exception text.
    **A parallel observer that can crash the trading loop is worse than no observer** — a
    shadow that takes the live path down converts an observation task into an outage.
    """
    live_verdict, live_reason = _live_entry_verdict(trace)

    if not bars:
        return EntryComparison(
            comparisons=(
                RuleComparison(
                    registered_id, "NOT_COMPARABLE", live_verdict, None,
                    reason="INPUT_ABSENT", detail="no bars supplied",
                ),
            ),
        )

    try:
        inventory = ImbalanceInventory.detect(bars, tf=schema_tf(tf))
        # `at_price` IS PASSED EXPLICITLY AND MUST NEVER BE DEFAULTED.
        #
        # `select()` skips its price filter entirely when `at_price is None`, so the verdict
        # becomes "an admissible imbalance exists ANYWHERE in the inventory" -- and over a
        # 320-bar window the inventory is 183-334 objects and is never empty. MEASURED on
        # tests/fixtures/btcusdtp_5m_1500.csv across 21 windows:
        #
        #     at_price=None    PASS 21/21    a CONSTANT
        #     at_price=close   PASS 16/21    it moves
        #
        # And the constant is PASS while the live path declines on most bars, so dropping this
        # argument does not produce a reassuring 0% -- IT PRODUCES A LARGE DISAGREEMENT RATE
        # THAT IS ENTIRELY AN ARTEFACT OF THE MISSING ARGUMENT, which someone would then go
        # looking for in the engine. DO NOT "simplify" this call.
        #
        # `close` is not chosen because it varies. It is the price the live retrace test uses
        # -- `lo <= ph and cl > pl` -- so this asks ENTRY-001 the same question about the same
        # price. The variation is the evidence that it is the comparable proposition.
        at_price = float(bars[-1].close) if bars[-1].close is not None else None
        if at_price is None:
            raise ValueError("the latest bar has no close; ENTRY-001 has no location to read")

        # An empty inventory needs no special case: `select` returns None and the rule says
        # FAIL, which is its documented answer -- "no imbalance at the entry location is the
        # rule working and refusing, not the rule being unable to speak."
        evaluation = ImbalanceIsTheOnlyEntryPOI.evaluate(inventory, (), at_price=at_price)
        rule_verdict = evaluation.verdict

        # THE ROW KEYS ON THE REGISTERED ID, NOT ON THE RETURNED ONE. Measured:
        #   implementations()['GRADE-029'].evaluate() -> RuleEvaluation(rule_id='GATE-041')
        #   implementations()['GRADE-035'].evaluate() -> RuleEvaluation(rule_id='GATE-040')
        # The alias mechanism the coverage report counts 13 of, so presumably intended -- but a
        # harness keying rows by `evaluation.rule_id` would attribute one rule's verdict to
        # another and MERGE TWO RULES INTO ONE ROW. It cannot bite at a denominator of one; it
        # bites the instant the comparable set widens, which is what this harness is for.
        returned_id = getattr(evaluation, "rule_id", registered_id)
        alias_of = None if returned_id == registered_id else returned_id

        # INPUT_ABSENT, DERIVED from the rule's own values rather than from the call site.
        # ENTRY-001 with an empty inventory returns FAIL and `candidates_considered: 0` -- and
        # FAIL AGREES with a live path that declined, so the naive harness records a SPURIOUS
        # AGREEMENT and the rate falls. That is the mirror of the `at_price` artefact below,
        # which produces spurious disagreement. Same convention, opposite direction.
        if rule_verdict == "NOT_APPLICABLE" or examined_nothing(dict(evaluation.values)):
            return EntryComparison(
                comparisons=(
                    RuleComparison(
                        registered_id, "NOT_COMPARABLE", live_verdict, rule_verdict,
                        reason="INPUT_ABSENT", alias_of=alias_of,
                        detail="the rule ran and its own values say it examined nothing",
                    ),
                ),
                inventory_size=len(inventory),
                at_price=at_price,
            )

        producers = _producer_column(bars, tf=schema_tf(tf))
    except Exception as exc:  # noqa: BLE001 - the isolation IS the contract
        return EntryComparison(
            comparisons=(
                RuleComparison(
                    registered_id, "NOT_COMPARABLE", live_verdict, None,
                    reason="RULE_RAISED", detail=f"{type(exc).__name__}: {exc}",
                ),
            ),
        )

    if live_reason is not None:
        comparison = RuleComparison(
            registered_id, "NOT_COMPARABLE", live_verdict, rule_verdict,
            reason=live_reason, alias_of=alias_of,
            detail=f"live stopped at {trace.blocked_by!r}; rule said {rule_verdict}",
        )
    else:
        rule_says_entry = rule_verdict == "PASS"
        agreed = rule_says_entry == live_verdict
        comparison = RuleComparison(
            registered_id, "AGREE" if agreed else "DISAGREE", live_verdict, rule_verdict,
            alias_of=alias_of,
            detail=(
                f"live {'took' if live_verdict else 'declined'} the entry; "
                f"ENTRY-001 said {rule_verdict}"
            ),
        )

    return EntryComparison(
        comparisons=(comparison,),
        producers=producers,
        inventory_size=len(inventory),
        at_price=at_price,
    )


def _producer_column(bars: Sequence[Bar], *, tf: str) -> tuple[ProducerRecord, ...]:
    """The three rules that emit objects rather than verdicts. OUTSIDE the denominator.

    **The right question about these is whether the live path computes the same OBJECTS, which
    is COVERAGE and is answerable later without a rate.** Recording them as agreeing whenever
    they produce something would be a term that cannot move — the defect this task's criterion
    exists to prevent.

    `GRADE-002` and `GRADE-008` name the input they lack rather than reporting a bare
    `produced: False`: *not produced* and *not produced because X is not built on this path*
    are different findings and only the second can be acted on.
    """
    swings = SwingPoints.detect(bars, tf=tf)
    breaks = BreakEvents.detect(bars, swings, tf=tf)
    boxes = StructureBoxes.construct(bars, swings, breaks, tf=tf)
    return (
        ProducerRecord("GRADE-001", produced=True, count=len(boxes)),
        ProducerRecord(
            "GRADE-002", produced=False,
            missing_input="BoxEvidence — the fuel/confluence evidence a box is graded against",
        ),
        ProducerRecord(
            "GRADE-008", produced=False,
            missing_input="htf_target_cleared — an HTF judgement no live path computes",
        ),
    )
