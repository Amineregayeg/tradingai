"""The rule engine: bars in, a decision that cites a rule out (M4 → M9 Stage A).

WHY THIS FILE EXISTS
Thirty-four registry rules are implemented and, until this module, **none of them had ever
been evaluated on anything**. Nothing outside `app/services/rules/` called `grade_box`,
`DisturbanceClassifier`, `StructureBoxes` or `LayoutReadability` — the graders were a library
with no caller, which is exactly what KNOWN_ISSUES A10 says: the gap is architectural, not
volumetric, and building more rules never closes it.

This is the composition. It produces the artefact the execution plan's §6 lists first and
calls impossible to produce today:

    A decision record whose `deciding_rule_id` is a real registry id.

WHAT IT DELIBERATELY DOES NOT DO
No entry price, no stop, no position size. Those are ENTRY/TARGET/EXIT/SIZE and the 9-cell
risk matrix — M6, which the plan puts last *on purpose*, "because M1–M5 make it auditable".
So this decides the alignment-and-grading layer only. A TAKE here means "the layout and the
box permit a trade", not "place this order", and nothing downstream of it exists yet.

It also does not touch the live loop. Wiring it into `crypto_loop` in shadow is M9 Stage A
and a separate, much smaller step.

EVALUATION ORDER IS PART OF THE CONTRACT
`deciding_rule_id` is the FIRST rule that failed, so the order rules are evaluated in is not
cosmetic — it decides which rule gets the blame. The order here runs cheapest-and-most-
fundamental first:

    GATE-008  is there a layout for this instrument at all?
    GATE-007  is it readable — one timeframe, panels thick enough to carry structure?
    GRADE-001 did a break print, so that a box exists?
    GRADE-006 does the box have the mandatory imbalance tap? (§8 key)
    GRADE-007 has all of its manipulation finished printing?
    GATE-048  per-panel agreement, sign-relative
    GATE-002  the disturbance count (a CLASSIFIER: it passes when it classifies)
    GATE-001  HEAVY is a hard filter, and it fires BEFORE anything sizes
    GATE-009  is any of the six admissible alignment forms satisfied?
    GATE-036  fold the above into TAKE / SKIP / STAND_ASIDE

Every rule reached is emitted whether it passed or failed. Conformance C-04: silence is not
a pass, and "evaluated and inapplicable" must stay distinguishable from "never implemented".

SKIP VERSUS STAND_ASIDE, DECIDED BY WHETHER A BOX EXISTED
A box is this layer's candidate setup. Before one exists there is nothing to reject, so a
failure is a STAND_ASIDE; once one exists, a failure is a SKIP. That is the schema's own
distinction and it is the difference between "the strategy looked and declined" and "the
strategy could not look".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from app.services.rules.base import RuleImplementation
from app.services.rules.gate_002_disturbance import (
    AlignmentForms,
    CorrelateRead,
    Disturbance,
    DisturbanceClassifier,
    HeavyDisturbanceSkip,
    MainAssetCountChoice,
)
from app.services.rules.gate_008_roster import (
    MIN_SAMPLES_PER_SYNTHETIC_BAR,
    LayoutReadability,
    LayoutRoster,
)
from app.services.rules.gate_036_stand_aside import Decision, StandAside
from app.services.rules.grade_001_structure_box import StructureBox, StructureBoxes
from app.services.rules.grade_002_box_grade import GradedBox, grade_box
from app.services.rules.grade_008_fake_msb import FakeMSBClassifier
from app.services.rules.prim_001_swings import DEFAULT_FRACTAL_WINDOW, Bar, SwingPoints
from app.services.rules.prim_002_imbalances import ImbalanceInventory
from app.services.rules.prim_003_liquidity import LiquidityPools
from app.services.rules.prim_004_sweeps import SweepEvents
from app.services.rules.prim_005_breaks import BreakEvents
from app.services.telemetry.records import RuleEvaluation


@dataclass
class LayoutEvaluation:
    """One pass of the rule engine over one decision bar."""

    decision: Decision
    evaluations: list[RuleEvaluation]
    instrument: str
    signal_tf: str
    as_of_index: int
    box: StructureBox | None = None
    graded: GradedBox | None = None
    disturbance: Disturbance | None = None
    correlate_reads: list[CorrelateRead] = field(default_factory=list)
    alignment_forms: list[str] = field(default_factory=list)

    @property
    def deciding_rule_id(self) -> str | None:
        return self.decision.deciding_rule_id

    def as_dict(self) -> dict[str, Any]:
        """The shape a `setup_evaluation` record is assembled from."""
        out: dict[str, Any] = {
            "instrument": self.instrument,
            "signal_tf": self.signal_tf,
            "alignment_tf": self.signal_tf,
            "rule_evaluations": [
                {
                    "rule_id": e.rule_id,
                    "verdict": e.verdict,
                    "values": e.values,
                    "value_provenance": e.value_provenance,
                }
                for e in self.evaluations
            ],
            **self.decision.as_dict(),
        }
        if self.graded is not None:
            out["structure_box"] = self.graded.as_dict()
        if self.disturbance is not None:
            out["correlates"] = self.disturbance.as_dict()
        if self.alignment_forms:
            out["alignment_form"] = list(self.alignment_forms)
        return out


def _prov(source: str, **kw: Any) -> dict[str, Any]:
    return {"source": source, **kw}


def order_flow_from_breaks(breaks: Sequence[Any], *, before: int) -> str:
    """A panel's order flow is the direction of its most recent confirmed break.

    Structural by construction, which is what GATE-005 requires: no candle count, no elapsed
    time, no correlation coefficient. A panel that has never broken is NEUTRAL — a real state,
    not a missing one, and deliberately not defaulted to agreement.
    """
    prior = [b for b in breaks if getattr(b, "bar_index", -1) < before]
    if not prior:
        return "NEUTRAL"
    last = max(prior, key=lambda b: b.bar_index)
    return "BULLISH" if getattr(last, "direction", None) == "UP" else "BEARISH"


def break_state_from_breaks(breaks: Sequence[Any], *, before: int) -> str:
    """Which of GATE-009's structural situations this panel is in.

    Derived from the break stream rather than from an "entry window", because the corpus
    never bounds that window numerically and any candle-count or minute bound would collide
    with GATE-005's ban list. An MSB most recently means the panel has just shifted; a BOS
    after an earlier MSB means it shifted before and is now continuing.
    """
    prior = sorted(
        (b for b in breaks if getattr(b, "bar_index", -1) < before),
        key=lambda b: b.bar_index,
    )
    if not prior:
        return "NONE"
    if getattr(prior[-1], "type", None) == "MSB":
        return "MSB_IN_WINDOW"
    if any(getattr(b, "type", None) == "MSB" for b in prior[:-1]):
        return "ALREADY_MSB_CONTINUING_BOS"
    return "NONE"


def build_correlate_reads(
    panel_bars: Mapping[str, Sequence[Bar]],
    *,
    signal_tf: str,
    as_of_index: int,
    sample_counts: Mapping[str, int | None] | None = None,
    swing_window: int = DEFAULT_FRACTAL_WINDOW,
) -> list[CorrelateRead]:
    """Turn each panel's bars into the structural read the disturbance grader consumes.

    Every field is derived from structure. `bar_sample_count` is passed through from the data
    layer (`DominanceSource.fetch_ohlcv_with_samples`) and is None for real instruments — an
    exchange bar is a bar; only the CryptoCap panels we synthesise can be too thin to read.
    """
    counts = dict(sample_counts or {})
    reads: list[CorrelateRead] = []
    for asset, bars in panel_bars.items():
        swings = SwingPoints.detect(bars, tf=signal_tf, window=swing_window)
        breaks = BreakEvents.detect(bars, swings, tf=signal_tf)
        limit = min(as_of_index, len(bars))
        reads.append(CorrelateRead(
            asset=asset,
            tf=signal_tf,
            observed_order_flow=order_flow_from_breaks(  # type: ignore[arg-type]
                breaks, before=limit),
            break_state=break_state_from_breaks(breaks, before=limit),  # type: ignore[arg-type]
            expected_break_confirmed=bool(
                [b for b in breaks if getattr(b, "bar_index", -1) < limit]
            ),
            bar_sample_count=counts.get(asset),
        ))
    return reads


class LayoutEvaluator(RuleImplementation):
    """GATE-010: a valid entry requires the five canonical criteria, alignment among them.

        An order opened with no alignment read recorded is a conformance failure regardless
        of outcome.

    That is why this composition carries a rule id at all: GATE-010 is the rule that makes an
    unrecorded alignment a failure, and this is the only place an alignment read is produced.
    """

    RULE_ID = "GATE-010"

    COVERAGE_NOTE = (
        "PARTIAL. Of the five canonical entry criteria this evaluates Market Structure "
        "(the box), Imbalances (as the box's mandatory tap) and Magic Alignment. Liquidity "
        "as a target and Forward/Reverse context are not evaluated — TARGET-* and the "
        "mode rules are unimplemented — so a TAKE here means the layout and box permit a "
        "trade, never that an order should be placed."
    )


def evaluate_layout(
    main_bars: Sequence[Bar],
    panel_bars: Mapping[str, Sequence[Bar]],
    *,
    instrument: str,
    signal_tf: str,
    as_of_index: int | None = None,
    sample_counts: Mapping[str, int | None] | None = None,
    min_samples: int = MIN_SAMPLES_PER_SYNTHETIC_BAR,
    swing_window: int = DEFAULT_FRACTAL_WINDOW,
    momentum_min_width: float | None = None,
    htf_target_cleared: bool = False,
) -> LayoutEvaluation:
    """Evaluate one decision bar and return a cited decision.

    `as_of_index` is the decision bar: evidence must lie strictly to its left. It defaults to
    `len(main_bars)`, i.e. "decide now, having seen every closed bar" — which is what the live
    loop does after dropping the still-forming bar.
    """
    as_of = len(main_bars) if as_of_index is None else as_of_index
    evaluations: list[RuleEvaluation] = []
    reads = build_correlate_reads(
        panel_bars, signal_tf=signal_tf, as_of_index=as_of,
        sample_counts=sample_counts, swing_window=swing_window,
    )

    # ---- GATE-008 / GATE-007: is there a readable layout at all? ----------------------
    readability, causes = LayoutReadability.evaluate(
        reads, signal_tf=signal_tf, instrument=instrument, min_samples=min_samples
    )
    evaluations += readability
    if any(e.verdict == "FAIL" for e in readability):
        # No box has been looked for yet, so nothing was in play to reject.
        return LayoutEvaluation(
            decision=StandAside.unreadable(causes, evaluations),
            evaluations=evaluations, instrument=instrument, signal_tf=signal_tf,
            as_of_index=as_of, correlate_reads=reads,
        )

    # ---- primitives on the traded asset ----------------------------------------------
    swings = SwingPoints.detect(main_bars, tf=signal_tf, window=swing_window)
    breaks = BreakEvents.detect(main_bars, swings, tf=signal_tf)
    SwingPoints.classify_strength(swings, breaks)
    imbalances = ImbalanceInventory.detect(
        main_bars, tf=signal_tf, momentum_min_width=momentum_min_width
    )
    pools = LiquidityPools.detect(main_bars, swings, tf=signal_tf)
    sweeps = SweepEvents.detect(pools, main_bars, breaks, tf=signal_tf)

    # ---- GRADE-001: no box, no grade, nothing may be sized ---------------------------
    boxes = StructureBoxes.construct(main_bars, swings, breaks, tf=signal_tf)
    box = StructureBoxes.latest(boxes, as_of_index=as_of)
    evaluations.append(RuleEvaluation(
        rule_id="GRADE-001",
        verdict="PASS" if box is not None else "FAIL",
        values={"box_id": box.id if box else None, "boxes_seen": len(boxes)},
        value_provenance={
            "box_id": _prov("PRIMITIVE_FIELD", object_id=box.id, field="id") if box
            else _prov("DERIVED", expression="no break printed left of the decision bar"),
            "boxes_seen": _prov("DERIVED", expression="count(structure_boxes)"),
        },
    ))
    if box is None:
        return LayoutEvaluation(
            decision=StandAside.decide(evaluations, setup_in_play=False),
            evaluations=evaluations, instrument=instrument, signal_tf=signal_tf,
            as_of_index=as_of, correlate_reads=reads,
        )

    # From here a candidate exists, so every later failure is a SKIP, not a stand-aside.
    direction = "LONG" if box.direction == "UP" else "SHORT"

    # ---- GRADE-006 / GRADE-007: the grade -------------------------------------------
    fake = FakeMSBClassifier.classify(
        box, main_bars, breaks, sweeps,
        htf_target_cleared=htf_target_cleared, as_of_index=as_of,
    )
    graded = grade_box(
        box, main_bars, swings, imbalances, as_of_index=as_of, fake_msb=fake
    )
    evaluations.append(RuleEvaluation(
        rule_id="GRADE-006",
        verdict="PASS" if graded.evidence.imbalance_tap else "FAIL",
        values={"imbalance_tap": graded.evidence.imbalance_tap,
                "definition_used": graded.definition_used,
                "imbalance_id": graded.evidence.imbalance_id},
        value_provenance={
            "imbalance_tap": _prov("DERIVED", expression="pullback intersects an imbalance"),
            "definition_used": _prov("DECLARED_PARAMETER", field="manipulated_definition"),
            "imbalance_id": _prov("PRIMITIVE_FIELD",
                                  object_id=graded.evidence.imbalance_id or "none",
                                  field="id"),
        },
    ))
    evaluations.append(RuleEvaluation(
        rule_id="GRADE-007",
        verdict="PASS" if graded.poi_qualified else "FAIL",
        values={"poi_qualified": graded.poi_qualified,
                "last_evidence_index": graded.evidence.last_evidence_index,
                "decision_bar": as_of},
        value_provenance={
            "poi_qualified": _prov("DERIVED", expression="last_evidence_index < decision_bar"),
            "last_evidence_index": _prov("DERIVED", expression="max(evidence bar indices)"),
            "decision_bar": _prov("RECORD_FIELD", field="as_of_index"),
        },
    ))
    # The grade itself, under the id of the tier it landed on. Emitted even on no-grade so
    # the record shows the ladder was walked rather than skipped.
    grade_rule = {"STANDARD": "GRADE-002", "SUPER": "GRADE-003",
                  "MANIPULATED": "GRADE-004"}.get(graded.grade or "", "GRADE-005")
    evaluations.append(RuleEvaluation(
        rule_id=grade_rule,
        verdict="PASS" if graded.grade else "NOT_APPLICABLE",
        values={"box_grade": graded.grade,
                "fuel_component_count": graded.evidence.fuel_component_count,
                "retest_expectation": graded.retest_expectation},
        value_provenance={
            "box_grade": _prov("DERIVED", expression="LADDER[fuel_component_count]"),
            "fuel_component_count": _prov("DERIVED", expression="imb + inner_sweep + fake_msb"),
            "retest_expectation": _prov("REGISTRY_CONSTANT", field="GRADE-005.ladder"),
        },
    ))
    if graded.grade is None:
        return LayoutEvaluation(
            decision=StandAside.decide(evaluations, setup_in_play=True),
            evaluations=evaluations, instrument=instrument, signal_tf=signal_tf,
            as_of_index=as_of, box=box, graded=graded, correlate_reads=reads,
        )

    # ---- GATE-048 / GATE-002: the correlate layout -----------------------------------
    disturbance = DisturbanceClassifier.classify(
        reads, direction=direction, instrument=instrument,  # type: ignore[arg-type]
        main_asset_counts=MainAssetCountChoice.MAIN_ASSET_COUNTS,
    )
    evaluations.append(RuleEvaluation(
        rule_id="GATE-048",
        # Agreement is a measurement, not a gate — it PASSES as long as it was derived
        # sign-relatively. GATE-002 is what turns it into an outcome.
        verdict="PASS",
        values={"panels": [p.as_dict() for p in disturbance.panels],
                "formula": "sign(observed_order_flow) * sign(expected_sign)"},
        value_provenance={
            "panels": _prov("CORRELATE_FIELD", field="agreement_state"),
            "formula": _prov("REGISTRY_CONSTANT", field="GATE-048.values.agreement_formula"),
        },
    ))
    evaluations.append(RuleEvaluation(
        rule_id="GATE-002",
        # A CLASSIFIER PASSES WHEN IT CLASSIFIES. Producing HEAVY is a successful
        # evaluation, not a failed one — GATE-002's registry `output` is a grade, not a
        # verdict. Marking it FAIL on HEAVY would steal the blame from GATE-001, which is
        # the actual hard filter and the rule conformance needs to see blocking. The first
        # FAIL is what `deciding_rule_id` cites, so this distinction is the difference
        # between a record that says "the count classifier broke" and one that says "heavy
        # disturbance refused the trade".
        verdict="PASS",
        values={"disturbance_grade": disturbance.grade,
                "disturbed_count": disturbance.disturbed_count,
                "layout_size": disturbance.layout_size,
                "main_asset_counted": disturbance.main_asset_counted},
        value_provenance={
            "disturbance_grade": _prov(
                "DERIVED", expression="count(disturbed) -> NONE/LIGHT/HEAVY"),
            "disturbed_count": _prov("DERIVED", expression="sum(panel.disturbed)"),
            "layout_size": _prov("REGISTRY_CONSTANT", field="GATE-008.values.panels"),
            "main_asset_counted": _prov("DECLARED_PARAMETER", field="main_asset_counts"),
        },
        banned_input_check=DisturbanceClassifier.banned_input_check(),
    ))

    # ---- GATE-001: HEAVY is a hard filter, and it fires before anything sizes ---------
    heavy = HeavyDisturbanceSkip.check(disturbance, box_grade=graded.grade)
    evaluations.append(RuleEvaluation(
        rule_id="GATE-001",
        verdict="FAIL" if heavy["decision"] == "BLOCK" else "PASS",
        values=heavy,
        value_provenance={
            "decision": _prov("DERIVED", expression="disturbance_grade == HEAVY"),
            "disturbance_grade": _prov("DERIVED", expression="GATE-002 output"),
            "structure_box_grade": _prov("DERIVED", expression="recorded, not consulted"),
            "disturbed_asset_list": _prov("CORRELATE_FIELD", field="disturbed"),
            **({"block_reason": _prov("REGISTRY_CONSTANT", field="GATE-001.output"),
                "risk_pct": _prov("REGISTRY_CONSTANT", field="GATE-001.values.risk_pct_on_heavy")}
               if heavy["decision"] == "BLOCK" else {}),
        },
    ))

    forms_ok, forms = AlignmentForms.check(reads, disturbance)
    evaluations.append(RuleEvaluation(
        rule_id="GATE-009",
        verdict="PASS" if forms_ok else "FAIL",
        values={"alignment_form": forms},
        value_provenance={
            "alignment_form": _prov("DERIVED", expression="six admissible forms, any of"),
        },
    ))

    return LayoutEvaluation(
        decision=StandAside.decide(evaluations, setup_in_play=True),
        evaluations=evaluations, instrument=instrument, signal_tf=signal_tf,
        as_of_index=as_of, box=box, graded=graded, disturbance=disturbance,
        correlate_reads=reads, alignment_forms=forms,
    )
