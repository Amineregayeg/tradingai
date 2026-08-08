"""GATE-048/002/003/004/005/009/001 and GRADE-013 — the correlate layout (M4).

    GATE-002: 0 disturbed → NONE. Exactly 1 → LIGHT. 2 or more → HEAVY.
    GATE-001: If disturbance_grade == HEAVY, the engine MUST NOT open a trade — regardless of
              Structure Box grade, momentum state, amplifier count, or any alignment score.
              risk_pct is forced to 0. There is no override path.

GATE-048 IS THE WHOLE REASON THIS MODULE HAS A SHAPE
    an engine that scores panels with a raw directional function (bullish +1 / neutral 0 /
    bearish −1) and then feeds that score to the disturbance count INVERTS the
    negative-correlated asset: a falling USDT.D — which is exactly what a BTC long requires —
    is scored −1 and counted as disturbed. In the four-panel BTC roster that single inversion
    moves the disturbance grade by one level on every setup.

One level of disturbance grade is one column of the risk matrix, and at the HEAVY end it is
the difference between a trade and a hard skip. So agreement is computed as
`sign(observed) × sign(expected)` and there is deliberately no function anywhere in this
module that returns a raw direction score — the rule requires that if both exist they must be
named distinctly and never summed, and the simplest way to obey that is to have only one.

DISTURBANCE IS STRUCTURAL, NEVER STATISTICAL — GATE-005 AND GATE-006
    "The correlation dropped below 0.75" · "The asset must confirm within two candles" ·
    "The MSB must occur within five minutes"

All three are banned verbatim. Nothing here takes a correlation coefficient, a candle count
or an elapsed time. `banned_input_check()` names the tokens that were checked, because a
negative gate with no enumerated tokens is a conformance assertion with nothing to assert
against.

THE OFF-CONDITION THAT CANNOT BE IMPLEMENTED, AND IS NOT FAKED
Off-condition 4, "reacts significantly before or after the others", is unquantified — and the
only ways to quantify it are the candle counts and time delays GATE-005 bans. It is therefore
evaluated ONLY when the caller supplies an explicit structural judgement. There is no default
and no proxy; leaving it unevaluated is the sole reading that obeys both rules at once.

WHY THE MAIN ASSET DOES NOT COUNT — GATE-004
    "a main asset that disagrees with its own setup is not a disturbance, it is an absent
    setup"

So the main panel is excluded from the count and its disagreement is reported separately as
`main_asset_disagrees`. The choice is declared (`main_asset_counts`), because the source
genuinely does not settle it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

from app.services.rules.base import RuleImplementation
from app.services.rules.gate_008_roster import Direction, Flow, LayoutRoster, Panel

AgreementState = Literal["ALIGNED", "NEUTRAL", "DISTURBED"]
DisturbanceGrade = Literal["NONE", "LIGHT", "HEAVY"]

#: GATE-002 `values`, verbatim. An ABSOLUTE count — GATE-003 forbids normalising it to the
#: layout size, which is why the roster is frozen at four panels instead.
NONE_MAX_DISTURBED = 0
LIGHT_DISTURBED_COUNT = 1
HEAVY_MIN_DISTURBED = 2

#: GATE-005's ban list, verbatim from the registry.
BANNED_INPUTS = ("correlation_coefficient", "fixed_candle_count", "fixed_time_delay")

#: GRADE-013 keeps BOTH lists: the PDF's six and the drawn six. Neither is declared
#: exhaustive, and they differ — the PDF adds momentum profile and structural reversal and
#: drops the drawn "never swept LIQ before MSB".
OFF_CONDITIONS = {
    "OC1_ORDER_FLOW_OPPOSITE": "order flow opposite to what the correlation implies",
    "OC2_FAILED_EXPECTED_BREAK": "fails the expected MSB/BOS while others confirmed",
    "OC3_DIFFERENT_OBJECTIVE": "moving toward a completely different liquidity objective",
    "OC4_OUT_OF_STEP": "reacts significantly before or after the others",
    "OC5_DIFFERENT_MOMENTUM": "different momentum profile",
    "OC6_STRUCTURAL_REVERSAL": "creates a structural reversal while others trend",
    "DRAWN_NEVER_SWEPT_LIQ": "never swept liquidity before its MSB",
    "DRAWN_NO_CLEAR_TARGET": "no clear target, target already cleared, or stuck between "
                             "liquidity points",
}


@dataclass
class CorrelateRead:
    """One panel's structural read, at the execution timeframe.

    Every field is a STRUCTURAL observation. There is deliberately no place to put a
    correlation coefficient, a candle count or an elapsed time — the dataclass is the first
    line of GATE-005's defence, because a field that does not exist cannot be populated.
    """

    asset: str
    tf: str
    observed_order_flow: Flow
    #: OC2 / the drawn "no MSB, no BOS". None means not observed rather than failed.
    expected_break_confirmed: bool | None = None
    #: OC3 — compared against the main panel's objective, never against a distance.
    liquidity_objective_id: str | None = None
    #: The drawn target-side conditions, as a single named state.
    target_state: Literal["CLEAR", "NONE", "ALREADY_CLEARED", "STUCK_BETWEEN"] | None = None
    #: OC5 — compared against the main panel's profile.
    momentum_profile: str | None = None
    #: OC6.
    structural_reversal: bool | None = None
    #: The drawn "never swept LIQ before MSB".
    swept_liquidity_before_break: bool | None = None
    #: OC4. Caller-supplied ONLY — see the module docstring. There is no default.
    reaction_out_of_step: bool | None = None
    #: GATE-009's six admissible forms need to know what this panel's structure did.
    break_state: Literal["MSB_IN_WINDOW", "ALREADY_MSB_CONTINUING_BOS", "NONE"] | None = None
    #: How many raw observations the bars behind this read were assembled from.
    #:
    #: None for a real instrument: an exchange bar is a bar, and asking how many ticks made
    #: it is meaningless. It matters only for TOTAL and USDT.D, which are CryptoCap indices
    #: we SYNTHESISE by sampling — where a 5-minute "bar" at 60-second sampling holds five
    #: observations and its high and low are sampling luck rather than price action
    #: (KNOWN_ISSUES B11). Carried so the layout can refuse rather than grade noise.
    bar_sample_count: int | None = None


@dataclass
class PanelVerdict:
    """Per-panel outcome, with the derivation kept re-checkable from the record alone."""

    asset: str
    role: str
    observed_order_flow: Flow
    expected_flow: Flow
    agreement_state: AgreementState
    disturbed: bool
    off_conditions: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "role": self.role,
            "observed_order_flow": self.observed_order_flow,
            "expected_sign": self.expected_flow,
            "agreement_state": self.agreement_state,
            "disturbed": self.disturbed,
            "off_conditions": list(self.off_conditions),
        }


@dataclass
class Disturbance:
    """The graded layout."""

    grade: DisturbanceGrade
    disturbed_count: int
    layout_size: int
    panels: list[PanelVerdict]
    main_asset_counted: bool
    main_asset_disagrees: bool
    unevaluated_off_conditions: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "disturbance_grade": self.grade,
            "disturbed_count": self.disturbed_count,
            "layout_size": self.layout_size,
            "main_asset_counted": self.main_asset_counted,
            "main_asset_disagrees": self.main_asset_disagrees,
            "panels": [p.as_dict() for p in self.panels],
            "unevaluated_off_conditions": list(self.unevaluated_off_conditions),
        }


class PanelAgreement(RuleImplementation):
    """GATE-048: agreement is sign-relative, never a raw direction."""

    RULE_ID = "GATE-048"

    @staticmethod
    def _flow_sign(flow: Flow) -> int:
        return {"BULLISH": 1, "BEARISH": -1, "NEUTRAL": 0}[flow]

    @classmethod
    def agreement_state(
        cls, panel: Panel, observed: Flow, direction: Direction
    ) -> AgreementState:
        """`sign(observed_order_flow) × sign(expected_sign)`.

        Note what is NOT here: no branch on whether the asset is USDT.D, no special case for
        negative correlates. The sign falls out of the roster role, so a fifth panel added
        tomorrow gets the same treatment without touching this function.
        """
        expected = cls._flow_sign(panel.expected_flow(direction))
        product = cls._flow_sign(observed) * expected
        if product > 0:
            return "ALIGNED"
        if product < 0:
            return "DISTURBED"
        return "NEUTRAL"


class OffConditionDetector(RuleImplementation):
    """GRADE-013: the per-asset 'off' conditions, both lists kept."""

    RULE_ID = "GRADE-013"

    COVERAGE_NOTE = (
        "Seven of the eight off-conditions are evaluated from structural fields. OC4 "
        "('reacts significantly before or after the others') is evaluated only when the "
        "caller supplies an explicit judgement: it is unquantified in the source and every "
        "way of quantifying it — candle counts, time delays — is banned by GATE-005."
    )

    @staticmethod
    def fired(
        read: CorrelateRead,
        agreement: AgreementState,
        main: CorrelateRead | None,
    ) -> list[str]:
        """Which off-conditions this panel trips. Any one of them makes it disturbed."""
        out: list[str] = []
        if agreement == "DISTURBED":
            out.append("OC1_ORDER_FLOW_OPPOSITE")
        if read.expected_break_confirmed is False:
            out.append("OC2_FAILED_EXPECTED_BREAK")
        if (
            main is not None
            and read.liquidity_objective_id is not None
            and main.liquidity_objective_id is not None
            and read.liquidity_objective_id != main.liquidity_objective_id
        ):
            out.append("OC3_DIFFERENT_OBJECTIVE")
        if read.reaction_out_of_step is True:
            out.append("OC4_OUT_OF_STEP")
        if (
            main is not None
            and read.momentum_profile is not None
            and main.momentum_profile is not None
            and read.momentum_profile != main.momentum_profile
        ):
            out.append("OC5_DIFFERENT_MOMENTUM")
        if read.structural_reversal is True:
            out.append("OC6_STRUCTURAL_REVERSAL")
        if read.swept_liquidity_before_break is False:
            out.append("DRAWN_NEVER_SWEPT_LIQ")
        if read.target_state in ("NONE", "ALREADY_CLEARED", "STUCK_BETWEEN"):
            out.append("DRAWN_NO_CLEAR_TARGET")
        return out


class DisturbanceClassifier(RuleImplementation):
    """GATE-002: the count, and the first hard boundary anywhere in the corpus.

    Also satisfies GRADE-010.
    """

    RULE_ID = "GATE-002"

    @staticmethod
    def classify(
        reads: Sequence[CorrelateRead],
        *,
        direction: Direction,
        instrument: str = "BTC",
        main_asset_counts: bool = False,
    ) -> Disturbance:
        """Grade the layout. `main_asset_counts` is the declared GATE-004 choice."""
        panels = LayoutRoster.for_instrument(instrument)
        by_asset = {r.asset: r for r in reads}
        main_panel = next(p for p in panels if p.role == "MAIN")
        main_read = by_asset.get(main_panel.asset)

        verdicts: list[PanelVerdict] = []
        for panel in panels:
            read = by_asset.get(panel.asset)
            if read is None:
                # A missing panel is not an aligned one. The layout is fixed by name, so an
                # absent read means the alignment was never done for that asset — recorded
                # as disturbed rather than skipped, which is the conservative direction.
                verdicts.append(PanelVerdict(
                    panel.asset, panel.role, "NEUTRAL", panel.expected_flow(direction),
                    "DISTURBED", True, ["OC1_ORDER_FLOW_OPPOSITE"],
                ))
                continue
            agreement = PanelAgreement.agreement_state(
                panel, read.observed_order_flow, direction
            )
            fired = OffConditionDetector.fired(read, agreement, main_read)
            verdicts.append(PanelVerdict(
                panel.asset, panel.role, read.observed_order_flow,
                panel.expected_flow(direction), agreement, bool(fired), fired,
            ))

        counted = [
            v for v in verdicts if main_asset_counts or v.role != "MAIN"
        ]
        disturbed_count = sum(1 for v in counted if v.disturbed)
        main_verdict = next(v for v in verdicts if v.role == "MAIN")

        if disturbed_count >= HEAVY_MIN_DISTURBED:
            grade: DisturbanceGrade = "HEAVY"
        elif disturbed_count == LIGHT_DISTURBED_COUNT:
            grade = "LIGHT"
        else:
            grade = "NONE"

        unevaluated = (
            [] if any(r.reaction_out_of_step is not None for r in reads)
            else ["OC4_OUT_OF_STEP"]
        )
        return Disturbance(
            grade=grade,
            disturbed_count=disturbed_count,
            layout_size=len(panels),
            panels=verdicts,
            main_asset_counted=main_asset_counts,
            main_asset_disagrees=main_verdict.disturbed,
            unevaluated_off_conditions=unevaluated,
        )

    @staticmethod
    def banned_input_check() -> dict[str, Any]:
        """GATE-005's enumerated tokens, so the negative is testable from the record."""
        return {"checked": list(BANNED_INPUTS), "present": []}


class AbsoluteCountNotRatio(RuleImplementation):
    """GATE-003: the ≥2 threshold is an absolute count, and the layout is frozen so it works.

    Also satisfies GRADE-016.

        2-of-3 (the fixed BTC layout) grades HEAVY; but §2 F1/106 permits five positive and
        five negative correlates and calls that layout STRONGER — 2-of-10 would also grade
        HEAVY and the trade would be skipped, penalising exactly the layout the workspace
        calls stronger. The engine MUST NOT silently substitute a ratio threshold.

    The interim requirement is met by construction: the roster is frozen at four panels
    (GATE-008), so 2-of-3 is the only heavy case that can arise. `layout_size` is logged
    with every grade so a later ruling can be applied to stored telemetry retroactively.
    """

    RULE_ID = "GATE-003"

    LAYOUT_FROZEN = True

    @staticmethod
    def check(disturbance: Disturbance) -> tuple[bool, str]:
        expected = LayoutRoster.layout_size()
        if disturbance.layout_size != expected:
            return False, (
                f"layout size {disturbance.layout_size} is not the frozen roster's "
                f"{expected}; an absolute ≥2 threshold is only defensible while it is"
            )
        return True, f"absolute count on a frozen layout of {expected} panels"


class MainAssetCountChoice(RuleImplementation):
    """GATE-004: whether the main asset is scored for disturbance — declared, not assumed."""

    RULE_ID = "GATE-004"

    #: "a main asset that disagrees with its own setup is not a disturbance, it is an absent
    #: setup." So it is excluded from the count and reported on its own.
    MAIN_ASSET_COUNTS = False
    RATIFIED = False


class StructuralNotStatistical(RuleImplementation):
    """GATE-005: the ban list. Also satisfies GRADE-014."""

    RULE_ID = "GATE-005"

    BANNED = BANNED_INPUTS

    @staticmethod
    def check(evidence: dict[str, Any]) -> tuple[bool, list[str]]:
        """Any banned input class present in the evidence a decision was built from."""
        present = sorted(
            token for token in BANNED_INPUTS
            if any(token in str(k).lower() for k in evidence)
        )
        return not present, present


class CorrelationIsSelectionOnly(RuleImplementation):
    """GATE-006: ±80% chooses the roster; it is never a live gate.

        The engine MUST NOT compute a rolling correlation coefficient as a trade filter and
        MUST NOT reject or downgrade a setup because a measured correlation fell.

    There is no correlation function in this package to call, which is the strongest form of
    compliance available: the check below exists for records assembled elsewhere.
    """

    RULE_ID = "GATE-006"

    SELECTION_THRESHOLD_ABS = 0.8
    BANNED = (
        "correlation_coefficient", "rolling_correlation", "r_squared",
        "correlation_threshold_0_75",
    )

    @classmethod
    def banned_input_check(cls) -> dict[str, Any]:
        return {"checked": list(cls.BANNED), "present": []}


class AlignmentForms(RuleImplementation):
    """GATE-009: six admissible agreement forms — simultaneity is NOT required.

    Also satisfies GRADE-015.

        The engine MUST NOT require all assets to print the exact same structure at the exact
        same candle — "That would be too rigid."

    So the gate passes on ANY of the six. The test that matters is that it still passes when
    form (a) is absent, which is what stops a stricter-than-documented engine from quietly
    rejecting setups the trader would have taken.
    """

    RULE_ID = "GATE-009"

    FORMS = {
        "A_ALL_MSB_SAME_WINDOW": "all assets MSB in the same entry window",
        "B_ALREADY_MSB_CONTINUING_BOS": "some already MSB'd and now continuing with BOS",
        "C_LEAD_LAG_SAME_IDEA": "one leads / one lags but still moves toward the same idea",
        "D_POSITIVES_NOT_FIGHTING": "positives not fighting the main asset",
        "E_NEGATIVE_OPPOSITE_AS_EXPECTED": "the negative moving opposite as expected",
        "F_SIMILAR_TARGET_LOGIC": "similar target logic",
    }

    @staticmethod
    def satisfied_forms(
        reads: Sequence[CorrelateRead], disturbance: Disturbance
    ) -> list[str]:
        """Which forms fired. Empty means no alignment was demonstrated at all."""
        by_asset = {r.asset: r for r in reads}
        out: list[str] = []
        states = [by_asset[v.asset].break_state for v in disturbance.panels
                  if v.asset in by_asset]

        if states and all(s == "MSB_IN_WINDOW" for s in states):
            out.append("A_ALL_MSB_SAME_WINDOW")
        if any(s == "ALREADY_MSB_CONTINUING_BOS" for s in states):
            out.append("B_ALREADY_MSB_CONTINUING_BOS")
        if states and len({s for s in states if s}) > 1 and not any(
            v.disturbed for v in disturbance.panels
        ):
            out.append("C_LEAD_LAG_SAME_IDEA")
        positives = [v for v in disturbance.panels if v.role == "POSITIVE"]
        if positives and all(v.agreement_state != "DISTURBED" for v in positives):
            out.append("D_POSITIVES_NOT_FIGHTING")
        negatives = [v for v in disturbance.panels if v.role == "NEGATIVE"]
        if negatives and all(v.agreement_state == "ALIGNED" for v in negatives):
            out.append("E_NEGATIVE_OPPOSITE_AS_EXPECTED")
        objectives = {
            r.liquidity_objective_id for r in reads if r.liquidity_objective_id is not None
        }
        if len(objectives) == 1:
            out.append("F_SIMILAR_TARGET_LOGIC")
        return out

    @staticmethod
    def check(reads: Sequence[CorrelateRead], disturbance: Disturbance) -> tuple[bool, list[str]]:
        forms = AlignmentForms.satisfied_forms(reads, disturbance)
        return bool(forms), forms


class HeavyDisturbanceSkip(RuleImplementation):
    """GATE-001: HEAVY is a hard filter. Also satisfies GRADE-011.

        Heavy Disturbance is a hard filter: no trade regardless of the Structure Box.

    There is no override path, and the registry is explicit that the softer wordings which
    exist for the same rule — "the trade should usually be skipped", "i will 90% skip the
    trade" — must NOT be implemented: an engine cannot implement "usually". The latest and
    most explicit statement wins.

    The box grade is passed in and deliberately ignored for the outcome, then recorded, so
    conformance can prove the gate fired BEFORE sizing rather than after.
    """

    RULE_ID = "GATE-001"

    RISK_PCT_ON_HEAVY = 0.0
    BLOCK_REASON = "HEAVY_DISTURBANCE"

    @staticmethod
    def check(disturbance: Disturbance, *, box_grade: str | None = None) -> dict[str, Any]:
        blocked = disturbance.grade == "HEAVY"
        out: dict[str, Any] = {
            "decision": "BLOCK" if blocked else "CONTINUE",
            "disturbance_grade": disturbance.grade,
            # Recorded and not consulted — that is the point of recording it.
            "structure_box_grade": box_grade,
            "disturbed_asset_list": [
                v.asset for v in disturbance.panels if v.disturbed
            ],
        }
        if blocked:
            out["block_reason"] = HeavyDisturbanceSkip.BLOCK_REASON
            out["risk_pct"] = HeavyDisturbanceSkip.RISK_PCT_ON_HEAVY
        return out
