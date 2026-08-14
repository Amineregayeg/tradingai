"""GATE-038 — amplifiers never create a trade; they only raise confidence (T-0019).

The registry entry:

    Negative gate. "Amplifiers never create a trade by themselves. They only increase the
    confidence of an already valid setup. A valid trade is always based on market structure,
    liquidity, imbalance, momentum, and forward/reverse trading logic." Collision test, for
    confidence scoring only: within approximately 0.2% of the entry zone — "If the entry POI
    is at 100.00, any amplifier between 99.80 and 100.20 is considered to be colliding"
    (±0.2%, a 0.4%-wide corridor). "The 0.2% value is an engineering guideline, not a strict
    market rule." All amplifier types are weighted equally.
    output: amplifier_count and types (telemetry / confidence only) — MUST NOT flip an
    accept/reject decision.

HOW A RULE ENFORCES "MUST NOT INFLUENCE", which is not the same as computing a number
The dangerous implementation is the one that computes `amplifier_count` correctly and then
adds it to a score that gates entry. It passes every test about the count and violates the
rule. So the prohibition is enforced STRUCTURALLY: this rule's verdict is a function of the
setup's validity ALONE, and the amplifier evidence is carried beside it where a decision path
cannot reach it without saying so. `decides_entry` is emitted as a literal `False` on every
record — a claim the engine makes about itself, which a conformance test can read.

THE 0.2% IS OURS AND UNRATIFIED, AND THE STATEMENT SAYS SO ITSELF
"approximately 0.2%" plus a worked example, plus "an engineering guideline, not a strict
market rule" — the GRADE-035 shape exactly. So it is a declared parameter carrying its own
provenance and ratified=False, never a bare literal in a comparison, and the record says what
it assumed. A later ruling can then be applied to stored history instead of invalidating it.

WHY THE FIRING RATE IS REPORTED RATHER THAN ASSUMED (B46)
A collision window that catches every amplifier and one that catches none produce the same
shaped record, and only a measured rate separates them. `amplifier_rate` reports how many of
the supplied levels fell inside the corridor, with the denominator, so a window that has gone
vacuous is visible rather than inferred.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isclose
from typing import Any, Sequence

from app.services.rules.base import RuleImplementation
from app.services.telemetry.records import RuleEvaluation, derived, from_record


@dataclass(frozen=True)
class DeclaredWindow:
    """A collision half-width that carries its provenance and its unratified status.

    Its own type rather than GRADE-031's `DeclaredQuorum`: that carrier is GRADE-031's
    CONTENT — it is the declared-parameter rule — while this is a percentage belonging to
    GATE-038. Sharing the type would dissolve one rule's substance into another's, which is
    the mistake `PROGRAMME_TO_CUTOVER.md` 2b records.
    """

    name: str
    pct: float
    source: str
    ratified: bool = False

    def as_values(self) -> dict[str, Any]:
        return {
            self.name: self.pct,
            f"{self.name}_ratified": self.ratified,
            f"{self.name}_source": self.source,
        }


#: OURS. Quoted from the statement, stamped unratified because the statement stamps itself.
DECLARED_COLLISION_WINDOW = DeclaredWindow(
    name="amplifier_window_pct",
    pct=0.2,
    source=(
        "GATE-038 statement quotes 'within approximately 0.2%' with the worked example "
        "100.00 -> 99.80..100.20, and then says outright: 'The 0.2% value is an engineering "
        "guideline, not a strict market rule.' Approximate plus a worked example is not a "
        "ruling, so this is carried as ours and unratified."
    ),
)

#: The three classes the statement names, all weighted equally ("All amplifier types are
#: weighted equally"). Listed so the record can say WHICH vocabulary was checked — a rule
#: made of a category list is defeated by a category nobody enumerated.
AMPLIFIER_KINDS = (
    "INSTITUTIONAL_KEY_LEVEL",   # PDH, PDL, PWH, PWL, PMH, PML, DO, WO, EQ — PRIM-003
    "ROUND_NUMBER",
    "SR_FLIP",                   # PRIM-006
)


@dataclass(frozen=True)
class AmplifierLevel:
    kind: str
    price: float
    label: str | None = None


def colliding(
    levels: Sequence[AmplifierLevel],
    *,
    entry_price: float,
    window: DeclaredWindow = DECLARED_COLLISION_WINDOW,
) -> list[AmplifierLevel]:
    """Levels inside the declared corridor around `entry_price`.

    The corridor is +/- `window.pct` percent, i.e. twice that wide in total — the statement's
    own worked example (100.00 -> 99.80..100.20) is the arithmetic check on this line.

    THE BOUNDARY IS INCLUSIVE AND THE NAIVE COMPARISON REJECTS THE STATEMENT'S OWN EXAMPLE.
    Both edges land on `0.20000000000000284` in binary float against a `half` of exactly
    `0.2`, so a bare `<=` excludes BOTH 99.80 and 100.20 — the rule refusing the only
    concrete boundary the doctrine wrote down.

    AND THE CHOICE OF ARITHMETIC IS WHAT DECIDES IT, which is the part worth knowing (B59).
    Three forms that look equally reasonable in a diff disagree about the documented case:

        abs(p - e) <= e * pct / 100         EXCLUDES both edges
        abs(p - e) / e <= pct / 100         EXCLUDES both edges
        precompute the band 99.80..100.20   INCLUDES both edges

    THIS FUNCTION USES THE FIRST FORM and repairs the boundary with `isclose`, rather than
    switching to the third, because a precomputed band hides the same decision inside its
    own rounding — it happens to agree here and there is no reason it would in general. The
    interior comparison is untouched; only the edge is.
    """
    half = abs(entry_price) * window.pct / 100.0
    out = []
    for lv in levels:
        delta = abs(lv.price - entry_price)
        if delta <= half or isclose(delta, half, rel_tol=1e-9, abs_tol=0.0):
            out.append(lv)
    return out


class AmplifiersNeverCreateATrade(RuleImplementation):
    """GATE-038: amplifier evidence is confidence only, never a trigger."""

    RULE_ID = "GATE-038"

    COVERAGE_NOTE = (
        "The 0.2% collision window is OURS and UNRATIFIED — the statement calls it 'an "
        "engineering guideline, not a strict market rule' — so it is a declared parameter "
        "stamped on every record, and the firing rate is reported with its denominator "
        "because a window that catches everything and one that catches nothing emit the "
        "same shaped record. The prohibition is enforced STRUCTURALLY: the verdict is a "
        "function of setup validity alone and `decides_entry` is emitted False, because an "
        "implementation that computes the count correctly and then feeds it into an entry "
        "score passes every count test and violates the rule."
    )

    @classmethod
    def evaluate(
        cls,
        levels: Sequence[AmplifierLevel] = (),
        *,
        entry_price: float | None = None,
        setup_valid: bool = False,
        window: DeclaredWindow = DECLARED_COLLISION_WINDOW,
    ) -> RuleEvaluation:
        """PASS only when the setup is independently valid. Amplifiers never move this.

        `setup_valid` IS THE ONLY THING THE VERDICT READS. The amplifier evidence is computed
        and reported and is not an input to the branch below — that is the enforcement, and
        it is structural rather than tested-into-place.
        """
        hits = (
            colliding(levels, entry_price=entry_price, window=window)
            if entry_price is not None
            else []
        )
        counted = len(levels) if entry_price is not None else 0

        values: dict[str, Any] = {
            "amplifier_count": len(hits),
            "amplifier_types": sorted({lv.kind for lv in hits}),
            "amplifier_labels": [lv.label for lv in hits if lv.label],
            "amplifier_kinds_checked": list(AMPLIFIER_KINDS),
            # B46: the rate with its denominator. A corridor that catches all of them and one
            # that catches none are indistinguishable from the count alone.
            "amplifier_levels_examined": counted,
            "amplifier_rate": round(len(hits) / counted, 6) if counted else None,
            "entry_price": entry_price,
            "setup_valid": setup_valid,
            # THE RULE'S OWN CLAIM ABOUT ITSELF, emitted so a conformance test can read it
            # rather than infer it from the absence of an effect.
            "decides_entry": False,
            **window.as_values(),
        }
        provenance: dict[str, Any] = {
            "amplifier_count": derived(
                f"levels within +/-{window.pct}% of entry_price (a "
                f"{2 * window.pct}%-wide corridor)"
            ),
            "amplifier_types": derived("distinct kinds among the colliding levels"),
            "amplifier_labels": derived("labels of the colliding levels"),
            "amplifier_kinds_checked": derived(
                "GATE-038 statement — institutional key levels, round numbers, S/R flips"
            ),
            "amplifier_levels_examined": derived("count of levels supplied to this rule"),
            "amplifier_rate": derived("amplifier_count / amplifier_levels_examined"),
            "entry_price": from_record("entry_poi.price_band"),
            "setup_valid": from_record("the entry decision this rule may not influence"),
            "decides_entry": derived(
                "GATE-038 statement — 'amplifiers never create a trade by themselves'"
            ),
            **{
                k: derived("GATE-038 declared window — OURS, unratified")
                for k in window.as_values()
            },
        }

        # THE BRANCH READS `setup_valid` AND NOTHING ELSE. Adding `or hits` here is exactly
        # the violation this rule exists to prevent, and it is a one-token edit — which is
        # why criterion 7's mutation is worth more than reading this line.
        return cls.evaluation(
            "PASS" if setup_valid else "FAIL",
            values=values,
            value_provenance=provenance,
        )
