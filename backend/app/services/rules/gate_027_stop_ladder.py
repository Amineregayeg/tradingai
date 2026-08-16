"""The stop pipeline, part one: the ladder, the floor, the terminal skip, the selector.

T-0025a. Four rules that together decide WHERE THE STOP GOES, and they are four rules
rather than one function because each owns a distinct artefact that conformance tests
separately:

    GATE-027   the ordered five-rung candidate ladder     -> `ladder`
    GATE-025   the full candidate table with rr/accepted  -> `[{anchor, stop_price, rr, accepted}]`
    GATE-026   the terminal skip and the best rr          -> `best_rr`, NO_CANDIDATE_REACHES_2R
    GATE-028   the selector                               -> `selected_stop`, `selection_rule_id`

`stop_evaluation.required` is `['entry_reference_price','target_price','ladder','best_rr']`,
and `best_rr`'s own description names GATE-026 while `selection_rule_id`'s names GATE-028.
So the four are not a convenience grouping — THEY ARE THE EXACT SET THAT PRODUCES ONE
SCHEMA OBJECT AND ALL OF ITS REQUIRED FIELDS. A task holding only GATE-027 and GATE-025
cannot emit a valid record at all.

WHY THE SELECTOR SHIPS UNDER GATE-028 AND NOT GATE-025
The selection rule is `argmin |RR - 3.0|` over candidates clearing 2R, ties to the larger
stop. GATE-025 owns the FLOOR ("if the RR is below 2R, reject that stop-loss"); GATE-028
owns the CHOICE among the survivors. Shipping the selector under GATE-025's id would leave
GATE-028 — a `blocker: True` rule — reading UNIMPLEMENTED in the coverage report while its
selector ran in the engine. That is a BEHAVIOUR WITH NO RULE ID, the mirror of the
implementation-with-no-producer shape this register has filed four times, and no count we
have would show it.

THE AUTHORITY FOR THE SELECTION RULE IS SALIM'S ROUND-2 RULING, NOT GATE-028
GATE-028 is a DEFECT row. Its title opens "DEFECT", its statement opens "BLOCKER", its
`values` carry BOTH `operative_reading` and `competing_reading`, and its operative clause
ends "pending a trader ruling". It recorded our reading PROVISIONALLY and flagged that it
needed him. It is cited here as EVIDENCE THE QUESTION WAS LIVE and as the source of the
worked table below — never as the authority. Before the round-2 ruling the reading was
ours; after it, his.

THE LADDER ORDER IS THE ENGINE ORDER AND THE WORKSPACE'S PRINTED ORDER IS SUPERSEDED
`GATE-027.values.ladder` is authoritative. The workspace (§2 H8, §3.5, §8) runs Order Block
THIRD and hunted-liquidity/QML fourth. A reader consulting the workspace gets the wrong
order, and the workspace is the more findable source — which is why this is stated at the
point the ladder is defined rather than in a design note.

RUNG 4 HAS NO CONTRACT-SIDE PRODUCER AND SAYS SO IN THE HOUSE'S OWN VOCABULARY
Six PRIM rules and none produces order blocks. `detect_order_blocks()` exists at
`ict/detector.py:192` — the PRE-CONTRACT ICT strategy — and no rule module imports
`services.ict`; reaching for it would adopt that detector's semantics as doctrine, which is
the move TARGET-001 refuses. So rung 4 reports `NOT_EVALUABLE` with the missing producer
named — `base.py:44`'s vocabulary, "NO PRODUCER EXISTS. Permanent until someone builds one",
though deliberately NOT its `ConditionReading` type; see `order_block_gap()`. That is
deliberately NOT the same fact as "the producer ran and found nothing", and is NOT one of
`unlocatable_reason`'s three values. Those are a "closed set of
REAL search failures" each requiring `search_evidence`, and a producer gap is not a search
failure: filing it as one rebuilds the fabricated-excuse shape the round-2 rulings deleted
from rung 3. The producer is T-0029.

WHAT THIS MODULE DOES NOT DO
GATE-029 (flag above 4R), GATE-030 (TIGHTER_THAN_NECESSARY), GATE-031 (degenerate runner),
the post-selection zone-coverage modifier, and both corpus measurements are T-0030. Every
one of them consumes `selected_stop.rr` or the candidate table, so none could be built
before this module existed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Sequence

from app.services.rules.base import RuleImplementation
from app.services.rules.prim_001_swings import Swing
from app.services.rules.prim_002_imbalances import Imbalance
from app.services.rules.prim_003_liquidity import LiquidityPool
from app.services.rules.prim_004_sweeps import SweepEvent
from app.services.rules.prim_005_breaks import BreakEvent
from app.services.telemetry import contract_loader as contract
from app.services.telemetry.ny_time import iso_ny
from app.services.telemetry.records import (
    RuleEvaluation, derived, from_declared, from_primitive, from_registry,
)

Direction = Literal["LONG", "SHORT"]

#: The five anchors IN ENGINE ORDER, read from the registry rather than retyped.
#:
#: Retyping it here would create a second source that can drift from the registry silently,
#: and the whole of criterion 1 is that one printed order in this project is already wrong.
#: Read once at import: a typo is an ImportError, which is the cheapest moment.
LADDER: tuple[str, ...] = tuple(contract.rule("GATE-027")["values"]["ladder"])

#: GATE-025's floor and GATE-028's preferred value, from the registry for the same reason.
RR_FLOOR: float = float(contract.rule("GATE-025")["values"]["rr_floor"])
RR_PREFERRED: float = float(contract.rule("GATE-025")["values"]["rr_preferred"])

#: GATE-028's two competing readings. The operative one is what shipped.
SELECTION_READING: str = str(contract.rule("GATE-028")["values"]["operative_reading"])
COMPETING_READING: str = str(contract.rule("GATE-028")["values"]["competing_reading"])

#: `unlocatable_reason`'s closed set — a REAL search failure, each requiring
#: `search_evidence`. Rung 4's producer gap is deliberately not among them.
UNLOCATABLE_REASONS = (
    "NO_SUCH_PRIMITIVE_IN_SEARCH_WINDOW",
    "PRIMITIVE_BEYOND_DECISION_BAR",
    "PRIMITIVE_ON_WRONG_SIDE_OF_ENTRY",
)

#: What rung 4 is missing. Named as the missing DATA rather than a rule id, because no
#: registry rule produces order blocks either — B44's case: the rule knows, the graph does
#: not. TARGET-001 and GRADE-019 use the same form.
ORDER_BLOCK_PRODUCER = "order_block_detector"


@dataclass(frozen=True)
class DeclaredPlacement:
    """Where on a swept liquidity level the stop actually sits. OURS, unratified.

    Its own type rather than a shared carrier: this is GATE-027's [ENGINEERING] residual and
    belongs to GATE-027, exactly as GATE-038's collision window belongs to GATE-038.
    """

    name: str
    value: str
    source: str
    ratified: bool = False

    def as_values(self) -> dict[str, Any]:
        return {
            self.name: self.value,
            f"{self.name}_ratified": self.ratified,
            f"{self.name}_source": self.source,
        }


#: OURS. Unratified. Criterion 2b — "any old liquidity sweep level" fixes the LEVEL and not
#: the PLACEMENT on it, and his material shows both readings.
DECLARED_SWEEP_PLACEMENT = DeclaredPlacement(
    name="stop_placement_on_swept_level",
    value="BEYOND_THE_SWEPT_EXTREME",
    source=(
        "GATE-027 note (a) rules rung 3 a swept liquidity level — 'it does not have to be "
        "QML, any old liquidity sweep level can act as SL level for me, i do not have "
        "perfect standards for this' (026_Stop_Loss_Decision.md:46) — and fixes the level "
        "without fixing where on it the stop sits. His material shows BOTH 'at the swept "
        "level' and 'beyond the swept wick'. Beyond the extreme is declared here because a "
        "stop AT the level sits exactly where price already proved it trades, which is the "
        "cushion argument of GATE-030 applied to the one rung whose defining event is a "
        "penetration. OURS, unratified, and the competing placement is recorded so a later "
        "ruling re-partitions stored history rather than invalidating it."
    ),
)

#: The placement NOT taken. Recorded for the same reason GATE-028 records its competing
#: reading: an engineering choice with only one option written down reads as a fact.
COMPETING_SWEEP_PLACEMENT = "AT_THE_SWEPT_LEVEL"

#: OURS. Unratified. THE SAME CLASS OF CHOICE AS RUNG 3's, AND IT WAS A BARE LITERAL UNTIL
#: Review pointed out the asymmetry.
#:
#: `GATE-027.inputs` says "the DEEPER open momentum imbalance" — which fixes WHICH imbalance
#: and says nothing about WHICH EDGE of it the stop sits on. That is structurally identical
#: to rung 3, where "any old liquidity sweep level" fixes the level and not the placement on
#: it. Both anchors are ZONES with two defensible edges.
#:
#: Declaring one and hardcoding the other is worse than either choice alone: a reader who
#: finds `DECLARED_SWEEP_PLACEMENT` reasonably infers that the undeclared placements are
#: doctrine, so one declaration makes the other look settled.
#:
#: Rungs 1 and 5 need no equivalent and deliberately do not have one — "deepest LL/HH" and
#: "inner MSB" name POINTS, not zones, so there is no edge to pick. The line is
#: anchor-is-a-zone, and it selects exactly rungs 2 and 3.
DECLARED_IMBALANCE_EDGE = DeclaredPlacement(
    name="stop_placement_on_momentum_imbalance",
    value="FAR_EDGE",
    source=(
        "GATE-027 inputs name 'the deeper open momentum imbalance' and stop there — WHICH "
        "imbalance is his, WHICH EDGE is not stated anywhere. The far edge is declared here "
        "because PRIM-006's printed rule is that these objects are ZONES and never lines, "
        "and a stop at the near edge sits INSIDE the object it is meant to clear. That is a "
        "real argument for the choice and it is still OUR choice, not his — which is exactly "
        "why it is declared rather than reasoned in a comment."
    ),
)

#: The edge NOT taken.
COMPETING_IMBALANCE_EDGE = "NEAR_EDGE"


class StopCandidateNotComparable(ValueError):
    """A candidate whose rr cannot be computed against the predefined target."""


@dataclass(frozen=True)
class SearchEvidence:
    """HG-28 — why a rung was not located, in a form an auditor can contradict.

    Required whenever `locatable` is false FOR A SEARCH FAILURE. Rung 4 carries none because
    no search occurred, which is the distinction `ConditionReading` exists to keep.
    """

    search_window_from: datetime
    search_window_to: datetime
    candidate_object_ids_considered: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "search_window_from": iso_ny(self.search_window_from),
            "search_window_to": iso_ny(self.search_window_to),
            "candidate_object_ids_considered": list(self.candidate_object_ids_considered),
        }


@dataclass(frozen=True)
class StopCandidate:
    """One rung of the ladder, in the schema's `stop_candidate` shape.

    A rung is ALWAYS emitted, locatable or not. A five-anchor ladder that silently returns
    four is the absence-versus-empty collapse, and "rung 3 was not locatable on this bar" is
    only checkable if something counts the slots (criterion 2c).
    """

    rung: int
    anchor: str
    locatable: bool
    stop_price: float | None = None
    anchor_object_id: str | None = None
    rr: float | None = None
    accepted: bool = False
    rejection_reason: str = "NONE"
    unlocatable_reason: str | None = None
    search_evidence: SearchEvidence | None = None
    #: Set ONLY on a producer gap. Never emitted as an `unlocatable_reason`, because that
    #: enum is a closed set of REAL search failures and this is not one.
    missing_producer: str | None = None

    def __post_init__(self) -> None:
        if self.locatable and self.stop_price is None:
            raise ValueError(
                f"rung {self.rung} ({self.anchor}) is locatable but carries no stop_price — "
                "a located anchor with no price is a truncated ladder wearing a tick"
            )
        if not self.locatable and self.stop_price is not None:
            raise ValueError(
                f"rung {self.rung} ({self.anchor}) is not locatable but carries a "
                f"stop_price {self.stop_price}"
            )
        if self.unlocatable_reason is not None:
            if self.unlocatable_reason not in UNLOCATABLE_REASONS:
                raise ValueError(
                    f"rung {self.rung}: {self.unlocatable_reason!r} is not one of "
                    f"{UNLOCATABLE_REASONS}. The enum is a closed set of REAL search "
                    "failures; a producer gap uses missing_producer instead."
                )
            if self.search_evidence is None:
                raise ValueError(
                    f"rung {self.rung} claims {self.unlocatable_reason} with no "
                    "search_evidence — HG-28 requires the reason to be contradictable from "
                    "the record alone, and a bare reason is an unfalsifiable excuse"
                )
        if self.missing_producer is not None and self.unlocatable_reason is not None:
            raise ValueError(
                f"rung {self.rung} names both a missing producer and a search-failure "
                "reason. 'Nobody built one' and 'I looked and found nothing' are different "
                "facts with different owners; a rung reporting both has decided neither."
            )

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "rung": self.rung,
            "anchor": self.anchor,
            "locatable": self.locatable,
            "accepted": self.accepted,
        }
        for key, value in (
            ("stop_price", self.stop_price),
            ("anchor_object_id", self.anchor_object_id),
            ("rr", self.rr),
            ("unlocatable_reason", self.unlocatable_reason),
            ("missing_producer", self.missing_producer),
        ):
            if value is not None:
                out[key] = value
        if self.rejection_reason != "NONE":
            out["rejection_reason"] = self.rejection_reason
        if self.search_evidence is not None:
            out["search_evidence"] = self.search_evidence.as_dict()
        return out

    @property
    def cushion(self) -> float | None:
        """Distance from entry — the quantity 'larger stop' actually means."""
        return None if self._entry is None or self.stop_price is None else abs(
            self._entry - self.stop_price
        )

    #: Set by the ladder builder so `cushion` is answerable without threading entry through
    #: every comparison. Not emitted.
    _entry: float | None = None


@dataclass(frozen=True)
class LadderInputs:
    """The chart objects at the entry location, plus the two prices rr is computed against.

    `target` is the PREDEFINED target and is FIXED BEFORE stop selection — GATE-025's own
    words. It is taken as an input here rather than derived, so that a stop can never be
    chosen by moving the target to make it clear 2R.
    """

    entry: float
    target: float
    direction: Direction
    search_window_from: datetime
    search_window_to: datetime
    swings: Sequence[Swing] = ()
    imbalances: Sequence[Imbalance] = ()
    sweeps: Sequence[SweepEvent] = ()
    pools: Sequence[LiquidityPool] = ()
    breaks: Sequence[BreakEvent] = ()
    #: The MSB that opened the trade. Rung 1 is the deepest swing AFTER it.
    msb: BreakEvent | None = None

    def __post_init__(self) -> None:
        if self.direction not in ("LONG", "SHORT"):
            raise ValueError(f"direction {self.direction!r} is neither LONG nor SHORT")
        if self.direction == "LONG" and self.target <= self.entry:
            raise ValueError(
                f"LONG with target {self.target} at or below entry {self.entry} — the "
                "reward is negative and every rr computed from it would be a sign error "
                "wearing a number"
            )
        if self.direction == "SHORT" and self.target >= self.entry:
            raise ValueError(
                f"SHORT with target {self.target} at or above entry {self.entry}"
            )

    @property
    def reward(self) -> float:
        return abs(self.target - self.entry)

    def is_on_stop_side(self, price: float) -> bool:
        """A stop sits BELOW entry on a long and ABOVE it on a short.

        A candidate on the wrong side is not a tight stop — it is an instant loss, and its
        rr would compute as a negative number that sorts perfectly well.
        """
        return price < self.entry if self.direction == "LONG" else price > self.entry


def risk_reward(inputs: LadderInputs, stop_price: float) -> float:
    """rr against the PREDEFINED target. Raises rather than returning a sentinel."""
    risk = abs(inputs.entry - stop_price)
    if risk <= 0:
        raise StopCandidateNotComparable(
            f"stop {stop_price} is at entry {inputs.entry} — risk is zero and rr is "
            "undefined; returning inf here would make a degenerate stop win every selector"
        )
    if not inputs.is_on_stop_side(stop_price):
        raise StopCandidateNotComparable(
            f"stop {stop_price} is on the wrong side of entry {inputs.entry} for a "
            f"{inputs.direction}"
        )
    return inputs.reward / risk


class StopCandidateLadder(RuleImplementation):
    """GATE-027: the five anchors in engine order, every rung emitted.

    ARTEFACT: the ordered candidate list feeding GATE-025.
    """

    RULE_ID = "GATE-027"

    COVERAGE_NOTE = (
        "IMPLEMENTED for four of five rungs. Rungs 1, 2, 3 and 5 are located from PRIM-001 "
        "swings, PRIM-002 imbalances, PRIM-004 sweeps against PRIM-003 pools, and PRIM-005 "
        "breaks respectively. RUNG 4 (ORDER_BLOCK) HAS NO CONTRACT-SIDE PRODUCER — measured, "
        "six PRIM rules and none produces order blocks — so it is emitted with "
        "ConditionReading(NOT_EVALUABLE, missing_producer) and never with an "
        "unlocatable_reason, which is a closed set of real search failures. The ladder is "
        "always five long. Exact placement on rung 3's level is declared as ours and "
        "unratified. The producer is T-0029."
    )

    #: Rung 4 cannot be located until something produces order blocks. Declared so the
    #: coverage report puts this rule in the implemented-but-CANNOT-FIRE bucket for that
    #: rung rather than counting a five-rung ladder the engine cannot build.
    CANNOT_FIRE_WITHOUT = (ORDER_BLOCK_PRODUCER,)

    # -- per-rung location ----------------------------------------------------------
    @staticmethod
    def _deepest_swing(inputs: LadderInputs) -> tuple[float, str] | tuple[None, list[str]]:
        """Rung 1 — the deepest LL/HH AFTER the MSB, on the stop side.

        "Deepest" is the extreme, not the nearest: this rung is the widest cushion by
        definition and that is the whole reason it sits first.
        """
        after = inputs.msb.bar_index if inputs.msb is not None else -1
        wanted = "LOW" if inputs.direction == "LONG" else "HIGH"
        considered = [s.id for s in inputs.swings]
        pool = [
            s for s in inputs.swings
            if s.kind == wanted and s.bar_index > after
            and inputs.is_on_stop_side(s.price)
        ]
        if not pool:
            return None, considered
        chosen = min(pool, key=lambda s: s.price) if inputs.direction == "LONG" else max(
            pool, key=lambda s: s.price
        )
        return chosen.price, chosen.id

    @staticmethod
    def _momentum_imbalance(
        inputs: LadderInputs,
    ) -> tuple[float, str] | tuple[None, list[str]]:
        """Rung 2 — the DEEPER open momentum imbalance, at the DECLARED edge.

        "The deeper open momentum imbalance" is GATE-027's own wording and is HIS: `deeper`
        selects the imbalance. WHICH EDGE of it the stop sits on is stated nowhere, so it is
        `DECLARED_IMBALANCE_EDGE` — ours, unratified, with the competing edge recorded.
        """
        considered = [i.id for i in inputs.imbalances]
        pool = [
            i for i in inputs.imbalances
            if i.is_momentum_imbalance is True and i.fill_state != "FILLED"
        ]
        far_edge = DECLARED_IMBALANCE_EDGE.value == "FAR_EDGE"
        edges: list[tuple[float, str]] = []
        for imb in pool:
            if inputs.direction == "LONG":
                edge = imb.price_low if far_edge else imb.price_high
            else:
                edge = imb.price_high if far_edge else imb.price_low
            if inputs.is_on_stop_side(edge):
                edges.append((edge, imb.id))
        if not edges:
            return None, considered
        # DEEPER = further from entry = the larger cushion.
        price, object_id = max(edges, key=lambda pair: abs(inputs.entry - pair[0]))
        return price, object_id

    @staticmethod
    def _swept_level(inputs: LadderInputs) -> tuple[float, str] | tuple[None, list[str]]:
        """Rung 3 — a swept prior liquidity level. NO QML GEOMETRY.

        The rung is the swept LEVEL; the declared placement decides where on it the stop
        sits. `penetration_abs` gives the extreme the run actually reached, so
        BEYOND_THE_SWEPT_EXTREME is a measured price and not an invented buffer.
        """
        considered = [s.id for s in inputs.sweeps]
        by_id = {p.id: p for p in inputs.pools}
        found: list[tuple[float, str]] = []
        for sweep in inputs.sweeps:
            pool = by_id.get(sweep.pool_id)
            if pool is None or pool.price is None:
                continue
            if DECLARED_SWEEP_PLACEMENT.value == "BEYOND_THE_SWEPT_EXTREME":
                # The extreme of the run: below the level on a long, above it on a short.
                price = (
                    pool.price - abs(sweep.penetration_abs)
                    if inputs.direction == "LONG"
                    else pool.price + abs(sweep.penetration_abs)
                )
            else:
                price = pool.price
            if inputs.is_on_stop_side(price):
                found.append((price, sweep.id))
        if not found:
            return None, considered
        # The deepest swept extreme — same cushion preference as rung 2.
        price, object_id = max(found, key=lambda pair: abs(inputs.entry - pair[0]))
        return price, object_id

    @staticmethod
    def _inner_msb(inputs: LadderInputs) -> tuple[float, str] | tuple[None, list[str]]:
        """Rung 5 — the INNERMOST break, i.e. the tightest. Innermost by definition."""
        considered = [b.id for b in inputs.breaks]
        pool = [b for b in inputs.breaks if inputs.is_on_stop_side(b.break_price)]
        if not pool:
            return None, considered
        chosen = min(pool, key=lambda b: abs(inputs.entry - b.break_price))
        return chosen.break_price, chosen.id

    # -- the ladder -----------------------------------------------------------------
    @classmethod
    def order_block_gap(cls) -> dict[str, str]:
        """Rung 4's state, in base.py:44's vocabulary but NOT in its type.

        `NOT_EVALUABLE` is not a third flavour of FALSE and it is not a search failure. It
        says NO PRODUCER EXISTS, names which, and stays permanent until T-0029 builds one.
        That is base.py:44's distinction exactly, and it is the one this rung needs.

        WHY THE VOCABULARY AND NOT THE `ConditionReading` TYPE, which was the first
        implementation here. `ConditionReading` is documented as "one named condition of a
        MULTI-CONDITION rule", and `check_partial_rules.py` enforces that any module binding
        it also binds the shared `quorum_blocked` — because two inline copies of the
        blocked-state default are supposed to differ in exactly the place a mistake would
        appear. GATE-027 has no quorum: rung 4's unreadability blocks nothing, the ladder
        still returns five rungs and the rule still reaches PASS.

        The script has an `INLINE_EXEMPT` list documenting "a single-condition rule is the
        legitimate case", and taking it would have been sanctioned. It was refused because
        of how the two layers interact: the grep layer only fails a module for which
        `binds_helper` is TRUE, so an exempt module is unreachable by BOTH checks, and one
        entry would retire the guard for this file permanently rather than narrowly.

        Nothing is lost by dropping the type. The distinction it carries is enforced here by
        `StopCandidate.__post_init__`, which refuses a rung claiming both a missing producer
        and a search-failure reason, and declared to the coverage report by
        `CANNOT_FIRE_WITHOUT`.
        """
        return {"state": "NOT_EVALUABLE", "missing_producer": ORDER_BLOCK_PRODUCER}

    @classmethod
    def build(cls, inputs: LadderInputs) -> list[StopCandidate]:
        """The five rungs in engine order. ALWAYS five, locatable or not."""
        evidence = SearchEvidence(
            search_window_from=inputs.search_window_from,
            search_window_to=inputs.search_window_to,
        )
        locators = {
            "DEEPEST_SWING": cls._deepest_swing,
            "MOMENTUM_IMBALANCE": cls._momentum_imbalance,
            "LIQUIDITY_SWEEP_QML": cls._swept_level,
            "INNER_MSB": cls._inner_msb,
        }
        out: list[StopCandidate] = []
        for index, anchor in enumerate(LADDER, start=1):
            if anchor == "ORDER_BLOCK":
                # THE PRODUCER GAP. No search ran, so no search_evidence is emitted and no
                # unlocatable_reason is claimed — see the module docstring.
                out.append(StopCandidate(
                    rung=index,
                    anchor=anchor,
                    locatable=False,
                    accepted=False,
                    rejection_reason="NOT_LOCATABLE",
                    missing_producer=cls.order_block_gap()["missing_producer"],
                    _entry=inputs.entry,
                ))
                continue
            price, found = locators[anchor](inputs)
            if price is None:
                out.append(StopCandidate(
                    rung=index,
                    anchor=anchor,
                    locatable=False,
                    accepted=False,
                    rejection_reason="NOT_LOCATABLE",
                    unlocatable_reason="NO_SUCH_PRIMITIVE_IN_SEARCH_WINDOW",
                    search_evidence=SearchEvidence(
                        search_window_from=evidence.search_window_from,
                        search_window_to=evidence.search_window_to,
                        candidate_object_ids_considered=list(found),
                    ),
                    _entry=inputs.entry,
                ))
                continue
            out.append(StopCandidate(
                rung=index,
                anchor=anchor,
                locatable=True,
                stop_price=float(price),
                anchor_object_id=str(found),
                _entry=inputs.entry,
            ))
        return out

    @classmethod
    def evaluate(cls, inputs: LadderInputs) -> RuleEvaluation:
        ladder = cls.build(inputs)
        values: dict[str, Any] = {
            "ladder_order": list(LADDER),
            "ladder_length": len(ladder),
            "locatable_rungs": sum(1 for c in ladder if c.locatable),
            "ladder": [c.as_dict() for c in ladder],
            "workspace_order_superseded": True,
            **DECLARED_SWEEP_PLACEMENT.as_values(),
            "competing_placement": COMPETING_SWEEP_PLACEMENT,
            **DECLARED_IMBALANCE_EDGE.as_values(),
            "competing_imbalance_edge": COMPETING_IMBALANCE_EDGE,
        }
        provenance: dict[str, Any] = {
            "ladder_order": from_registry("GATE-027", "values.ladder"),
            "ladder_length": derived("count of rungs emitted"),
            "locatable_rungs": derived("count of rungs with locatable=True"),
            "ladder": derived("GATE-027 anchor location over the supplied primitives"),
            "workspace_order_superseded": from_registry("GATE-027", "statement"),
            DECLARED_SWEEP_PLACEMENT.name: from_declared(DECLARED_SWEEP_PLACEMENT.name),
            f"{DECLARED_SWEEP_PLACEMENT.name}_ratified": derived("OURS, unratified"),
            f"{DECLARED_SWEEP_PLACEMENT.name}_source": derived("GATE-027 note (a)"),
            "competing_placement": derived("the placement not taken, recorded"),
            DECLARED_IMBALANCE_EDGE.name: from_declared(DECLARED_IMBALANCE_EDGE.name),
            f"{DECLARED_IMBALANCE_EDGE.name}_ratified": derived("OURS, unratified"),
            f"{DECLARED_IMBALANCE_EDGE.name}_source": derived("GATE-027 inputs name the imbalance, not the edge"),
            "competing_imbalance_edge": derived("the edge not taken, recorded"),
        }
        for candidate in ladder:
            if candidate.anchor_object_id:
                provenance[f"rung_{candidate.rung}_anchor"] = from_primitive(
                    candidate.anchor_object_id, "price"
                )
        gap = cls.order_block_gap()
        values["order_block_rung"] = {
            **gap,
            "why": (
                "no contract-side producer exists for order blocks; ict/detector.py is the "
                "pre-contract strategy and adopting it would make that detector's semantics "
                "doctrine. T-0029 owns the producer."
            ),
        }
        provenance["order_block_rung"] = derived(
            "NOT_EVALUABLE + missing_producer — base.py:44's distinction, carried without "
            "its multi-condition type; see order_block_gap()"
        )
        return cls.evaluation("PASS", values=values, value_provenance=provenance)


class RewardFloor(RuleImplementation):
    """GATE-025: compute rr for every rung and reject anything below 2R.

    ARTEFACT: the full candidate table `[{anchor, stop_price, rr, accepted}]` — required
    telemetry, since conformance is tested from it. REJECTED CANDIDATES APPEAR, with their
    rr and `accepted: false`. A table containing only the winner cannot support conformance
    and is the defect.
    """

    RULE_ID = "GATE-025"

    COVERAGE_NOTE = (
        "IMPLEMENTED. The floor is the registry's rr_floor and the table carries every rung "
        "including unlocatable and rejected ones. This rule owns ADMISSION only — the "
        "choice among survivors is GATE-028's, and the terminal skip when nothing survives "
        "is GATE-026's."
    )

    @classmethod
    def table(cls, inputs: LadderInputs, ladder: Sequence[StopCandidate]) -> list[StopCandidate]:
        """Price every locatable rung and mark it accepted or rejected."""
        priced: list[StopCandidate] = []
        for candidate in ladder:
            if not candidate.locatable:
                priced.append(candidate)
                continue
            assert candidate.stop_price is not None  # guaranteed by __post_init__
            try:
                rr = risk_reward(inputs, candidate.stop_price)
            except StopCandidateNotComparable:
                priced.append(StopCandidate(
                    rung=candidate.rung,
                    anchor=candidate.anchor,
                    locatable=False,
                    accepted=False,
                    rejection_reason="NOT_LOCATABLE",
                    unlocatable_reason="PRIMITIVE_ON_WRONG_SIDE_OF_ENTRY",
                    search_evidence=SearchEvidence(
                        search_window_from=inputs.search_window_from,
                        search_window_to=inputs.search_window_to,
                        candidate_object_ids_considered=(
                            [candidate.anchor_object_id] if candidate.anchor_object_id else []
                        ),
                    ),
                    _entry=inputs.entry,
                ))
                continue
            accepted = rr >= RR_FLOOR
            priced.append(StopCandidate(
                rung=candidate.rung,
                anchor=candidate.anchor,
                locatable=True,
                stop_price=candidate.stop_price,
                anchor_object_id=candidate.anchor_object_id,
                rr=rr,
                accepted=accepted,
                rejection_reason="NONE" if accepted else "RR_BELOW_2R",
                _entry=inputs.entry,
            ))
        return priced

    @classmethod
    def evaluate(cls, inputs: LadderInputs, ladder: Sequence[StopCandidate]) -> RuleEvaluation:
        priced = cls.table(inputs, ladder)
        survivors = [c for c in priced if c.accepted]
        values: dict[str, Any] = {
            "rr_floor": RR_FLOOR,
            "entry_reference_price": inputs.entry,
            "target_price": inputs.target,
            "candidate_table": [c.as_dict() for c in priced],
            "accepted_count": len(survivors),
            "rejected_below_floor": sum(
                1 for c in priced if c.rejection_reason == "RR_BELOW_2R"
            ),
        }
        provenance: dict[str, Any] = {
            "rr_floor": from_registry("GATE-025", "values.rr_floor"),
            "entry_reference_price": derived("the intended entry rr was computed against"),
            "target_price": derived("the PREDEFINED target, fixed before stop selection"),
            "candidate_table": derived("rr = |target - entry| / |entry - stop| per rung"),
            "accepted_count": derived("count of rungs with rr >= rr_floor"),
            "rejected_below_floor": derived("count of rungs rejected RR_BELOW_2R"),
        }
        verdict = "PASS" if survivors else "FAIL"
        return cls.evaluation(verdict, values=values, value_provenance=provenance)


class NoCandidateReaches2R(RuleImplementation):
    """GATE-026: if every rung is below 2R, no trade. Terminal skip.

    ARTEFACT: `best_rr`, and the BLOCK decision with `block_reason
    NO_CANDIDATE_REACHES_2R`. It is not licence to move the target, widen the reward, or
    re-anchor outside the five categories.
    """

    RULE_ID = "GATE-026"

    COVERAGE_NOTE = (
        "IMPLEMENTED. best_rr is the max over LOCATABLE rungs and is None when no rung was "
        "locatable at all — a maximum over an empty set is representable rather than forced "
        "to a fabricated number, and null is equally a skip."
    )

    @staticmethod
    def best_rr(table: Sequence[StopCandidate]) -> float | None:
        """Max rr over locatable rungs. None when none was locatable.

        None IS A REAL ANSWER. Returning 0.0 for "nothing was locatable" would collapse it
        into "everything was terrible", and those are different records: one is a market
        fact, the other is a ladder the engine could not build.
        """
        rrs = [c.rr for c in table if c.locatable and c.rr is not None]
        return max(rrs) if rrs else None

    @classmethod
    def evaluate(cls, table: Sequence[StopCandidate]) -> RuleEvaluation:
        best = cls.best_rr(table)
        blocked = best is None or best < RR_FLOOR
        values: dict[str, Any] = {
            "best_rr": best,
            "rr_floor": RR_FLOOR,
            "decision": "BLOCK" if blocked else "CONTINUE",
            "locatable_rungs": sum(1 for c in table if c.locatable),
        }
        if blocked:
            values["block_reason"] = "NO_CANDIDATE_REACHES_2R"
        provenance: dict[str, Any] = {
            "best_rr": derived("max rr over locatable rungs; None when none was locatable"),
            "rr_floor": from_registry("GATE-025", "values.rr_floor"),
            "decision": derived("BLOCK when best_rr is None or below the floor"),
            "locatable_rungs": derived("count of rungs with locatable=True"),
        }
        if blocked:
            provenance["block_reason"] = from_registry("GATE-026", "output")
        return cls.evaluation("FAIL" if blocked else "PASS",
                              values=values, value_provenance=provenance)


class ClosestTo3RSelector(RuleImplementation):
    """GATE-028: among candidates clearing 2R, the one whose rr is CLOSEST TO 3R.

    ARTEFACT: `selected_stop` and `selection_rule_id`.

    THE TIE-BREAK IS PART OF THE RULE AND ITS DIRECTION IS COUNTERINTUITIVE.
    "Ties toward the larger (more cushioned) stop." GATE-028's own statement establishes
    that rr falls MONOTONICALLY as the stop widens, so THE LARGER STOP HAS THE LOWER RR: a
    tie between 2R and 4R resolves to the 2R candidate. A reader's intuition says 4R.

    AND THE TIE-BREAK KEYS ON CUSHION, NEVER ON LIST POSITION. `min()` over absolute
    distance resolves ties by list order silently, and in a cushion-monotonic ladder the
    larger stop is always EARLIER — so the correct answer and the list-order accident
    coincide by construction, and a tie fixture built from a monotonic ladder passes for
    both implementations. Monotonicity is exactly the claim nobody has measured (GATE-027
    asserts it in prose; T-0030 measures it), so this keys on the measured cushion.
    """

    RULE_ID = "GATE-028"

    COVERAGE_NOTE = (
        "IMPLEMENTED as the operative reading, which is Salim's round-2 ruling. GATE-028 is "
        "a DEFECT row that recorded that reading PROVISIONALLY 'pending a trader ruling' and "
        "carries the competing reading alongside it; the ruling settled it and both are "
        "emitted so stored history can be re-partitioned if it moves. This rule owns the "
        "CHOICE among survivors only — the floor is GATE-025's."
    )

    @staticmethod
    def select(table: Sequence[StopCandidate]) -> StopCandidate | None:
        """argmin |rr - 3.0| over accepted candidates, ties to the LARGER stop.

        The sort key is `(distance_from_preferred, -cushion)`. The second element is the
        rule, not a tidy-up: without it the winner among equidistant candidates is whichever
        happened to be listed first.
        """
        survivors = [c for c in table if c.accepted and c.rr is not None]
        if not survivors:
            return None
        return min(
            survivors,
            key=lambda c: (abs(c.rr - RR_PREFERRED), -(c.cushion or 0.0)),
        )

    @classmethod
    def evaluate(cls, table: Sequence[StopCandidate]) -> RuleEvaluation:
        chosen = cls.select(table)
        values: dict[str, Any] = {
            "selection_rule_id": SELECTION_READING,
            "competing_reading": COMPETING_READING,
            "rr_preferred": RR_PREFERRED,
        }
        provenance: dict[str, Any] = {
            "selection_rule_id": from_registry("GATE-028", "values.operative_reading"),
            "competing_reading": from_registry("GATE-028", "values.competing_reading"),
            "rr_preferred": from_registry("GATE-025", "values.rr_preferred"),
        }
        if chosen is None:
            values["selected_stop"] = None
            values["selected_rung"] = None
            values["not_applicable_reason"] = (
                "no candidate cleared the 2R floor, so there is nothing to select among. "
                "The terminal skip is GATE-026's, not this rule's."
            )
            provenance["selected_stop"] = derived("no accepted candidate")
            provenance["selected_rung"] = derived("no accepted candidate")
            provenance["not_applicable_reason"] = derived("survivor set was empty")
            return cls.evaluation("NOT_APPLICABLE", values=values,
                                  value_provenance=provenance)

        # Recorded so GATE-030 (T-0030) can be evaluated without re-deriving the survivor
        # set, and so the report shows the choice was made among more than one option.
        wider = [
            c for c in table
            if c.accepted and c.cushion is not None and chosen.cushion is not None
            and c.cushion > chosen.cushion
        ]
        values["selected_stop"] = chosen.as_dict()
        values["selected_rung"] = chosen.rung
        values["wider_accepted_candidates"] = len(wider)
        provenance["selected_stop"] = derived(
            f"argmin |rr - {RR_PREFERRED}| over accepted candidates, ties to larger cushion"
        )
        provenance["selected_rung"] = from_primitive(
            chosen.anchor_object_id or chosen.anchor, "price"
        )
        provenance["wider_accepted_candidates"] = derived(
            "count of accepted candidates with a larger cushion than the selected stop"
        )
        return cls.evaluation("PASS", values=values, value_provenance=provenance)


def evaluate_stop_pipeline(inputs: LadderInputs) -> dict[str, Any]:
    """Run all four rules in order and return their artefacts, separately.

    THE FOUR RULES DO NOT COLLAPSE INTO ONE FUNCTION (criterion 7). This is a caller-side
    convenience that runs them in dependency order and keeps each rule's evaluation
    distinct; it invents no verdict of its own and every value below is its rule's.
    """
    ladder = StopCandidateLadder.build(inputs)
    table = RewardFloor.table(inputs, ladder)
    return {
        "GATE-027": StopCandidateLadder.evaluate(inputs),
        "GATE-025": RewardFloor.evaluate(inputs, ladder),
        "GATE-026": NoCandidateReaches2R.evaluate(table),
        "GATE-028": ClosestTo3RSelector.evaluate(table),
        "ladder": ladder,
        "table": table,
        "selected": ClosestTo3RSelector.select(table),
        "best_rr": NoCandidateReaches2R.best_rr(table),
    }
