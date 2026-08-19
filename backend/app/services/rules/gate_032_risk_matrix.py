"""GATE-032 / SIZE-004 / GRADE-019 — how much is risked on a trade (T-0024).

Entries decide whether we are in, exits decide what we keep, and this decides the size of
both. It is the first rule in the programme that produces a number money is measured in.

    GATE-032   risk_pct = LOOKUP(structure_box_grade, disturbance_grade). Nine cells.
    SIZE-004   conformance: risk_pct <= 0.015 AND risk_pct in the nine matrix values.
    GRADE-019  risk_pct for altcoins = UNDEFINED (refuse) until ruled.

WHY A LITERAL TABLE, AND WHY THAT IS NOT AN ARGUMENT FROM IMPOSSIBILITY
The obvious defence of a lookup is "no formula reproduces it". That defence is FALSE and the
registry says so in `GATE-032.values`:

    "exact_relation": "LIGHT = NONE - 0.0075 (0.75 percentage points), exact for all three
    grades"

A decomposition exists; it is additive and exact. The reason to ship a table is AUTHORITY:
the ruling declares the source database authoritative, and the additive relation DESCRIBES
that database rather than generating it. Deriving LIGHT from NONE at runtime would promote a
pattern somebody noticed into the source of truth. So the table is the implementation, and
the relation is an invariant asserted over the table in
`tests/unit/test_t0024_position_sizing.py`.

WHAT IS ACTUALLY FORBIDDEN IS THE *MULTIPLICATIVE* FORM, AND THE DATA HIDES IT ON ROW ONE
GATE-033 is a whole rule about this: the proposed `base_risk x disturbance_modifier` refactor
claims to reproduce the table and does not.

    grade         NONE     LIGHT     additive -0.0075    multiplicative x0.5
    MANIPULATED   0.0150   0.0075    correct             ALSO CORRECT   <-- the trap
    SUPER         0.0125   0.0050    correct             WRONG (0.00625)
    STANDARD      0.0100   0.0025    correct             WRONG (0.0050)

The per-row Light/No ratios are 0.500 / 0.400 / 0.250 — three different numbers, so no single
Light multiplier exists. But `MANIPULATED` is the row GATE-032's own statement leads with, and
on that row x0.5 agrees to the last bit. AN IMPLEMENTER WHO SPOT-CHECKS ONE ROW CONFIRMS THE
WRONG RULE. On a $100,000 account the Standard/Light error sizes at $500 instead of $250 —
exactly double, on the most common grade.

That is why the test checks all three rows and says so in its own docstring: an edit trimming
it to "one representative row" would look like a tidy-up and would restore the trap.

`sizer_implementation` IS STAMPED ON EVERY RECORD. The telemetry schema enumerates
`MULTIPLICATIVE_MODIFIER` not as an option but as a DETECTABLE DEFECT (GATE-033). This module
emits `LOOKUP_TABLE` and nothing else.

HEAVY IS A SKIP, AND A SKIP IS NOT A ZERO-SIZED FILL
All three Heavy cells are `0% (skip)`. A position of size zero is not a trade taken at zero
risk; it is a trade refused. `RiskSizing.is_tradeable` is False for it and no risk_pct flows
onward, so a zero cannot be carried into a quantity calculation and out the other side as a
position record. GATE-001 already blocks on HEAVY upstream; this is the sizing half of the
same fact, and the two are deliberately not merged — GATE-001 decides admission, GATE-032
decides size, and conformance needs to show the gate fired BEFORE sizing rather than after.

A SKIP AND A REFUSAL HAVE THE SAME NUMERIC SHAPE AND ARE NOT THE SAME OUTCOME
`0% (skip)` is a ruled zero — the strategy working. An altcoin is an unruled undefined — the
strategy absent. Both produce no trade. Collapsing them into one code path would make a gap
in the doctrine indistinguishable from the doctrine operating, which is this project's
signature failure. Hence four outcomes, not two: SIZED, SKIP, REFUSED, UNGRADED_BOX.

GRADE-019 — THE CORRECT IMPLEMENTATION IS A REFUSAL, AND THE RULE CONTRADICTS ITSELF ABOUT IT
The registry entry disagrees with itself in two of its own fields:

    output       "risk_pct for altcoins = UNDEFINED (refuse) until ruled."
    triage_note  "PARTIAL: ship risk_pct(altcoin) = f(box_grade) = {0.0075, 0.005, 0.0025}..."

The Manager ruled on 2026-08-16 that `output` governs: a triage_note is a disposition about
what COULD ship, the output is what a consumer reads. Refusing also fails toward smaller
positions. **This module does not re-adjudicate that and neither should its next reader.**

WHY `risk_altcoin_heavy_as_written` IS NEVER INDEXED
    slot   no       light    heavy_as_written   ratio to siblings
    0      0.0075   0.0075   0.0075             1.0x
    1      0.005    0.005    0.05               10.0x   <-- exactly ten
    2      0.0025   0.0025   0.0025             1.0x

Three signatures agree that the middle cell is a dropped decimal: an exact factor of ten, a
monotonic descent broken in the one place nothing else breaks it, and a value 3.33x over
SIZE-004's ceiling sitting in the column GATE-032 sets to zero. `_as_written` is the
registry's own warning — the vector is a QUOTATION recorded so the transcription can be
audited, not an input.

The instruction is NOT "read it and reject it". It is **do not index it**: a code path that
reads a corrupt cell is one edit away from using it. `test_t0024_position_sizing.py` enforces
this with an AST walk over this package, so the constraint survives a refactor rather than
resting on this paragraph. Correcting `0.05` to `0.005` is also refused — a plausible typo fix
is still an implementer editing the authoritative database.

WHAT THIS MODULE DOES NOT DO
* **It is not wired.** `crypto_loop` sizes from `fixed_config.RISK_PCT = 0.01`, a flat 1%, and
  nothing under `live/` imports this module. Replacing the live sizer changes how much real
  money is at risk per trade and is a separate task with its own deploy. A green suite here is
  not a live 9-cell sizer.
* **It produces `risk_pct` only, not position quantity.** GATE-032's output is "risk_pct; then
  position quantity via the RR tool's Qty against the virtual account size". Quantity needs
  the stop distance and the account size — SIZE-001 / SIZE-002, waves 2 and 4. GATE-032 is
  therefore PARTIALLY implemented and the COVERAGE_NOTE says which half.
* **The altcoin refusal cannot fire in production.** The roster is BTC/USD and ETH/USD, both
  majors; `instrument_class` is hardcoded `"ALIGNED_MAJOR"` at `shadow.py:746` and
  `crypto_loop.py:794`; nothing classifies an instrument; and GATE-008 raises on an altcoin
  roster. `CANNOT_FIRE_WITHOUT` declares it so registering the rule does not inflate effective
  coverage. Adding an `instrument_class` producer to make the branch reachable would be a
  roster change that GATE-008 refuses on doctrine — the unreachability is the finding, not a
  gap to close.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

from app.services.rules.base import RuleImplementation
from app.services.rules.gate_002_disturbance import DisturbanceGrade
from app.services.rules.grade_002_box_grade import BoxGrade
from app.services.telemetry import contract_loader as contract
from app.services.telemetry.records import RuleEvaluation, derived, from_record, from_registry

#: GRADE-019's declared input. `ALIGNED_MAJOR` is what both production paths hardcode.
InstrumentClass = Literal["ALIGNED_MAJOR", "ALTCOIN"]

#: What the sizer concluded. FOUR outcomes, because three distinct facts share the numeric
#: shape "no position" and one of them is the strategy working while the others are not.
#:
#:   SIZED         a matrix cell was read and it is non-zero
#:   SKIP          HEAVY disturbance — a RULED zero, GATE-032's own "0% (skip)"
#:   REFUSED       an altcoin — GRADE-019, UNDEFINED until Salim rules
#:   UNGRADED_BOX  the box has no grade, so there is no row to look up
SizingOutcome = Literal["SIZED", "SKIP", "REFUSED", "UNGRADED_BOX"]

#: Row order is GATE-032's own, best grade first.
BOX_GRADES: tuple[BoxGrade, ...] = ("MANIPULATED", "SUPER", "STANDARD")
DISTURBANCE_GRADES: tuple[DisturbanceGrade, ...] = ("NONE", "LIGHT", "HEAVY")

#: The schema's `sizer_implementation` enum also carries `MULTIPLICATIVE_MODIFIER` and
#: `SUBTRACTIVE`. The first is GATE-033's defect, enumerated only so it is detectable in
#: stored records; the second is the exact_relation used as an implementation, which the
#: ruling's authority argument excludes. This module can only ever emit the first value.
SIZER_IMPLEMENTATION = "LOOKUP_TABLE"

#: GRADE-019's refusal, as a stable machine-readable token. A refusal that carries no named
#: reason is indistinguishable from a rule nobody wrote — the fourth instance of that shape in
#: this programme, after GATE-041's DECLINED/ERRORED, GRADE-013's `invalid`, and T-0016.
ALTCOIN_REFUSAL_REASON = "ALTCOIN_RISK_UNDEFINED"

#: GATE-032's HEAVY column, as a token distinct from the refusal above. Same numeric shape,
#: opposite meaning.
HEAVY_SKIP_REASON = "HEAVY_DISTURBANCE_SKIP"
#: GATE-016 ruling (b): a red-folder day sizes one rung DOWN the disturbance axis.
ECO_DAY_SKIP_REASON = "ECO_DAY_RUNG_DOWN_TO_SKIP"
#: The policy name that ships on every sized evaluation, so a record says WHICH rule moved the cell.
ECO_DAY_RISK_POLICY = "ONE_RUNG_DOWN"


def next_rung(disturbance: DisturbanceGrade) -> DisturbanceGrade | None:
    """One step down the disturbance axis. `None` past the end.

    **THE RULING INTRODUCES NO NEW NUMBER.** Every red-folder cell Salim named is already in
    `RISK_MATRIX` one rung along — Manipulated/NONE 1.50% -> 0.75% IS Manipulated/LIGHT, and every
    LIGHT cell steps to HEAVY, which is already `0.0`. So "one rung down" is a LOOKUP into the
    table we hold, not arithmetic and not a second table.

    *A nine-cell literal would restate what the matrix already says and drift from it silently, in
    the direction of whichever copy someone edits next* — `B93`'s shape, and the reason this is a
    derivation. HEAVY has no next rung and is already `0.0`, so it stays SKIP **by the same rule
    rather than by an exception**, which is what keeps the rule uniform.
    """
    order = DISTURBANCE_GRADES
    i = order.index(disturbance)
    return order[i + 1] if i + 1 < len(order) else None

#: No box grade, so no row. GRADE-001/GRADE-006: a box with no imbalance tap has no grade at
#: all, "which is what stops the risk matrix from being looked up".
UNGRADED_REASON = "BOX_HAS_NO_GRADE"


def _load_matrix() -> dict[tuple[str, str], float]:
    """The nine cells, read from the pinned registry. No arithmetic anywhere in this function.

    Read rather than typed as literals for the same reason EXIT-001 reads its fractions:
    changing a cell then means changing the contract, which is a reviewed act, and no call
    site can pass a different table because no signature accepts one.
    """
    values = contract.rule("GATE-032")["values"]

    # A fourth box grade appearing in the registry must not be silently ignored — a row this
    # module cannot see would size at whatever the caller's fallback is. `exact_relation` is
    # prose describing the table and is deliberately not a row.
    rows = set(values) - {"exact_relation"}
    if rows != set(BOX_GRADES):
        raise ValueError(
            f"GATE-032.values carries rows {sorted(rows)}; this module knows "
            f"{sorted(BOX_GRADES)}. A row the sizer cannot see is a grade that would fall "
            "through to a caller's default rather than to a ruled cell."
        )

    cells: dict[tuple[str, str], float] = {}
    for box in BOX_GRADES:
        row = values[box]
        missing = set(DISTURBANCE_GRADES) - set(row)
        if missing:
            raise ValueError(
                f"GATE-032.values[{box}] is missing {sorted(missing)} — an absent cell is a "
                "lookup that raises at decision time rather than at import"
            )
        for disturbance in DISTURBANCE_GRADES:
            cells[(box, disturbance)] = float(row[disturbance])
    return cells


#: THE TABLE. Bound at import so a registry typo is an ImportError rather than a wrong number
#: in a stored record.
RISK_MATRIX: dict[tuple[str, str], float] = _load_matrix()

#: SIZE-004's second assertion reads against this. NOTE THE CARDINALITY: nine CELLS, seven
#: DISTINCT VALUES — the three HEAVY cells are all 0.0. "risk_pct in the nine matrix values"
#: is a membership test over the values, so seven is the right size for this set and a reader
#: expecting nine is reading the cell count. Stated because a "why isn't this 9?" edit is the
#: kind that quietly widens a conformance check.
LEGAL_RISK_PCTS: frozenset[float] = frozenset(RISK_MATRIX.values())

#: Tolerance for the membership test. NOT exact float equality, deliberately: `0.0125 * 0.4`
#: and `0.005` are the same real number and different doubles, so `==` would make SIZE-004
#: pass or fail on binary representation rather than on doctrine. 1e-12 is nine orders of
#: magnitude below 0.0025, the smallest gap between two distinct cells, so it cannot merge one
#: legal value into another.
RISK_PCT_TOLERANCE = 1e-12


def _matrix_cell_id(box_grade: str | None, disturbance_grade: str | None) -> str:
    """The schema's `matrix_cell` enum value. The CELL ID, not just the number.

    Recorded so a mis-sized trade is attributable to a mis-graded box versus a mis-graded
    disturbance — two different upstream defects that produce one wrong number.
    """
    if box_grade is None or disturbance_grade is None:
        return "NOT_APPLICABLE"
    return f"{box_grade}_{disturbance_grade}"


@dataclass(frozen=True)
class RiskSizing:
    """What GATE-032 concluded for one setup, and why.

    `risk_pct` IS `None` FOR EVERY NON-SIZED OUTCOME EXCEPT THE RULED ZERO. A HEAVY skip
    carries 0.0 because GATE-032 states that number; a refusal carries None because there is
    no number to state. `None` and `0.0` are therefore not interchangeable here — one says
    "the doctrine says zero", the other says "the doctrine says nothing".
    """

    outcome: SizingOutcome
    risk_pct: float | None
    matrix_cell: str
    box_grade: BoxGrade | None
    disturbance_grade: DisturbanceGrade
    instrument_class: InstrumentClass
    reason_code: str | None
    reason: str
    #: GATE-016. `matrix_risk_pct` is the GRADED cell (box x disturbance) BEFORE any eco-day
    #: step; `risk_pct` above is the APPLIED value. Equal on a normal day, and the pair is what
    #: lets a record show that a step happened rather than asserting it.
    matrix_risk_pct: float | None = None
    eco_day_step_applied: bool = False
    eco_day_risk_policy: str = ECO_DAY_RISK_POLICY
    is_red_folder_day: bool = False

    @property
    def is_tradeable(self) -> bool:
        """Whether anything downstream may build a position from this.

        The gate criterion 2 turns on: a HEAVY cell is `0% (skip)` and a skip must not become
        a fill of zero units. Only SIZED is tradeable, so a zero cannot flow into a quantity
        calculation and out the other side as a position record.
        """
        return self.outcome == "SIZED"

    def as_risk_assessment(self) -> dict[str, Any]:
        """The schema's `setup_evaluation.risk_assessment` block.

        `box_grade` renders as the schema's `"NONE"` when the box has no grade — that enum
        member exists for exactly this state and is NOT the disturbance grade of the same
        name, which is why the two are never compared.
        """
        out = {
            "box_grade": self.box_grade if self.box_grade is not None else "NONE",
            "matrix_cell": self.matrix_cell,
            "risk_pct": self.risk_pct if self.risk_pct is not None else 0.0,
            "sizer_implementation": SIZER_IMPLEMENTATION,
        }
        out.update(self.eco_day_values())
        return out

    def eco_day_values(self) -> dict[str, Any]:
        """GATE-016's trio, emitted on EVERY evaluation and on BOTH record types.

        **`matrix_risk_pct` and `risk_pct` are equal on a normal day and that is the point**: the
        pair is what lets a stored record show a step HAPPENED rather than leaving it to be
        inferred from two numbers that differ. `eco_day_step_applied` says which.
        """
        return {
            "eco_day_risk_policy": self.eco_day_risk_policy,
            "matrix_risk_pct": (
                self.matrix_risk_pct if self.matrix_risk_pct is not None else 0.0
            ),
            "eco_day_step_applied": self.eco_day_step_applied,
            "is_red_folder_day": self.is_red_folder_day,
        }


class RiskMatrix(RuleImplementation):
    """GATE-032: the authoritative 9-cell risk matrix, as a lookup.

    Also registers GRADE-017, which the registry marks `alias_of GATE-032` — it is the ruling
    that fixed the Risk Alignment column, so implementing one implements both.
    """

    RULE_ID = "GATE-032"

    COVERAGE_NOTE = (
        "PARTIALLY IMPLEMENTED, AND THE HALF THAT IS MISSING IS NAMED. GATE-032's output is "
        "'risk_pct; then position quantity via the RR tool's Qty against the virtual account "
        "size'. THIS IS THE risk_pct HALF ONLY. Quantity needs the stop distance and the "
        "virtual account size, which are SIZE-001/SIZE-002 (waves 2 and 4) and are not "
        "implemented — so nothing here can produce a position, only the fraction one would be "
        "sized to. Implemented as a LITERAL LOOKUP over the registry's nine cells: the "
        "matrix is additively decomposable (LIGHT = NONE - 0.0075, exact) but the ruling "
        "declares the DATABASE authoritative, so the relation is asserted as an invariant "
        "over the table and never used to generate it. The MULTIPLICATIVE form GATE-033 "
        "names as a defect is impossible here by construction — there is no arithmetic in "
        "the lookup — and `sizer_implementation` is stamped LOOKUP_TABLE on every record. "
        "NOT WIRED: crypto_loop still sizes from fixed_config.RISK_PCT = 0.01, which is "
        "exactly this matrix's STANDARD/NONE cell, so the live engine currently sizes every "
        "setup as the most conservative non-zero row."
    )

    @classmethod
    def size(
        cls,
        *,
        box_grade: BoxGrade | None,
        disturbance_grade: DisturbanceGrade,
        instrument_class: InstrumentClass = "ALIGNED_MAJOR",
        is_red_folder_day: bool = False,
    ) -> RiskSizing:
        """Look up one cell, or say why no cell applies.

        ORDER OF CHECKS, AND WHY THE INSTRUMENT CLASS COMES FIRST:

        1. **Altcoin -> REFUSED**, before the matrix is consulted at all. Checking it after
           the disturbance grade would let an altcoin with HEAVY disturbance report `SKIP`,
           which asserts the Heavy-override that GRADE-019 says is *only ASSUMED* to apply to
           the altcoin column. Refusing first means the engine never leans on that assumption
           and never reads the altcoin vectors — including the corrupt `0.05` cell.
        2. **No box grade -> UNGRADED_BOX.** GATE-032's inputs declare
           `structure_box_grade in {Standard, Super, Manipulated}`; `None` is outside that
           domain, and GRADE-001's last sentence makes an ungraded box precisely the thing
           that stops the matrix being looked up.
        3. **The lookup.** A zero cell is HEAVY's ruled skip; anything else is a size.

        There is no fallback branch and no default risk_pct. Every path returns a named
        outcome with a reason code, because a sizer that silently declines looks exactly like
        a sizer nobody wrote.
        """
        if instrument_class == "ALTCOIN":
            return RiskSizing(
                outcome="REFUSED",
                risk_pct=None,
                matrix_cell=_matrix_cell_id(None, None),
                box_grade=box_grade,
                disturbance_grade=disturbance_grade,
                instrument_class=instrument_class,
                reason_code=ALTCOIN_REFUSAL_REASON,
                reason=(
                    "GRADE-019: risk_pct for altcoins is UNDEFINED until ruled. The source "
                    "database has two risk columns and the ruling supplied numbers for only "
                    "one — 9 of 18 cells are unanswered and whether the engine trades "
                    "altcoins at all is unstated. The engine must refuse to size an altcoin "
                    "trade rather than interpolate, and treating it as an aligned major "
                    "would be that interpolation under another name."
                ),
            )

        if box_grade is None:
            return RiskSizing(
                outcome="UNGRADED_BOX",
                risk_pct=None,
                matrix_cell=_matrix_cell_id(None, disturbance_grade),
                box_grade=None,
                disturbance_grade=disturbance_grade,
                instrument_class=instrument_class,
                reason_code=UNGRADED_REASON,
                reason=(
                    "the box carries no grade, so GATE-032 has no row to look up. GRADE-006 "
                    "makes the imbalance tap mandatory in all three grades, and a box "
                    "without one has no grade at all rather than the lowest one — which is "
                    "what stops the matrix from being consulted."
                ),
            )

        matrix_risk_pct = RISK_MATRIX[(box_grade, disturbance_grade)]
        risk_pct = matrix_risk_pct
        cell = _matrix_cell_id(box_grade, disturbance_grade)
        stepped = False

        if is_red_folder_day:
            # GATE-016 RULING (b), and it is a CELL RE-SELECTION rather than arithmetic —
            # `sizer_implementation` stays LOOKUP_TABLE. The stepped cell is read from the SAME
            # matrix at the next rung, so no number enters here that Salim did not write.
            #
            # `matrix_cell` KEEPS NAMING THE GRADED CELL (box x disturbance). The eco-day step is
            # recorded ALONGSIDE it and never folded into the grade: a record whose cell id moved
            # would attribute a smaller position to a worse box, which is a different fact.
            stepped_grade = next_rung(disturbance_grade)
            risk_pct = 0.0 if stepped_grade is None else RISK_MATRIX[(box_grade, stepped_grade)]
            stepped = True

        eco = {
            "matrix_risk_pct": matrix_risk_pct,
            "eco_day_step_applied": stepped,
            "is_red_folder_day": is_red_folder_day,
        }

        if risk_pct == 0.0 and stepped and matrix_risk_pct != 0.0:
            # THE RUNG-DOWN LANDED ON SKIP. Distinct from a HEAVY skip: the box was tradeable
            # today and the calendar removed it, which is the fact GATE-016 exists to record.
            return RiskSizing(
                outcome="SKIP",
                risk_pct=risk_pct,
                matrix_cell=cell,
                box_grade=box_grade,
                disturbance_grade=disturbance_grade,
                instrument_class=instrument_class,
                reason_code=ECO_DAY_SKIP_REASON,
                reason=(
                    f"GATE-016: red-folder day steps {cell} one rung down the disturbance axis "
                    f"to 0% (skip). The graded cell was {matrix_risk_pct:.2%} — this trade is "
                    "refused by the CALENDAR, not by the layout."
                ),
                **eco,
            )

        if risk_pct == 0.0:
            return RiskSizing(
                outcome="SKIP",
                risk_pct=risk_pct,
                matrix_cell=cell,
                box_grade=box_grade,
                disturbance_grade=disturbance_grade,
                instrument_class=instrument_class,
                reason_code=HEAVY_SKIP_REASON,
                reason=(
                    f"GATE-032 cell {cell} is 0% (skip). A ruled zero is a trade REFUSED, "
                    "not a trade taken at zero risk — GATE-001 makes HEAVY a hard filter "
                    "with no override path, so nothing downstream may build a position from "
                    "this."
                ),
                **eco,
            )

        return RiskSizing(
            outcome="SIZED",
            risk_pct=risk_pct,
            matrix_cell=cell,
            box_grade=box_grade,
            disturbance_grade=disturbance_grade,
            instrument_class=instrument_class,
            reason_code=None,
            reason=(
                f"GATE-032 cell {cell} = {risk_pct}"
                + (f" (GATE-016: one rung down from {matrix_risk_pct} on a red-folder day)"
                   if stepped else "")
            ),
            **eco,
        )

    @classmethod
    def evaluate(cls, sizing: RiskSizing) -> RuleEvaluation:
        """GATE-032's telemetry for one sizing decision.

        PASS — a cell was read, including the ruled zero. HEAVY passing is the rule WORKING:
        the matrix states `0% (skip)` and the engine skipped.
        NOT_APPLICABLE — no cell applies, because the instrument is an altcoin (GRADE-019
        refuses) or the box has no grade. Silence is not a pass (C-04): there is no risk_pct
        to assert anything about, and reporting PASS would count an absent doctrine as a
        conforming size.
        """
        values: dict[str, Any] = {
            "risk_pct": sizing.risk_pct,
            "matrix_cell": sizing.matrix_cell,
            "box_grade": sizing.box_grade,
            "disturbance_grade": sizing.disturbance_grade,
            "instrument_class": sizing.instrument_class,
            "sizer_implementation": SIZER_IMPLEMENTATION,
            "outcome": sizing.outcome,
            "is_tradeable": sizing.is_tradeable,
            "reason": sizing.reason,
            "matrix_cell_count": len(RISK_MATRIX),
            **sizing.eco_day_values(),
        }
        if sizing.reason_code is not None:
            values["reason_code"] = sizing.reason_code

        provenance: dict[str, Any] = {
            "risk_pct": from_registry("GATE-032", "values"),
            "matrix_cell": derived("f'{box_grade}_{disturbance_grade}'"),
            "box_grade": derived("GRADE-002/003/004 via grade_box()"),
            "disturbance_grade": derived("GATE-002 via DisturbanceClassifier"),
            "instrument_class": derived(
                "SUPPLIED — no producer exists; both live paths hardcode ALIGNED_MAJOR "
                "(shadow.py:746, crypto_loop.py:794). See GRADE-019.CANNOT_FIRE_WITHOUT"
            ),
            "sizer_implementation": derived(
                "constant LOOKUP_TABLE — GATE-033 enumerates MULTIPLICATIVE_MODIFIER as a "
                "detectable defect, and this module contains no arithmetic to produce one"
            ),
            "outcome": derived("SIZED | SKIP | REFUSED | UNGRADED_BOX"),
            "is_tradeable": derived("outcome == SIZED"),
            "reason": derived("the outcome's stated reason"),
            "reason_code": derived("machine-readable token for the non-SIZED outcomes"),
            "matrix_cell_count": derived(
                "len(RISK_MATRIX) — the DENOMINATOR. Without it a record cannot show the "
                "lookup covered the whole table rather than the row it happened to hit"
            ),
            "eco_day_risk_policy": from_registry("GATE-016", "values.eco_day_risk_policy"),
            "matrix_risk_pct": derived(
                "the GRADED cell (box x disturbance) BEFORE any eco-day step — equal to "
                "risk_pct on a normal day, and the pair is what shows a step happened"
            ),
            "eco_day_step_applied": derived(
                "GATE-016 ruling (b): true when the red-folder day moved the cell one rung"
            ),
            "is_red_folder_day": from_record(
                "GATE-016 — EXISTS an event on the NY day with blocks == true (GATE-015)"
            ),
        }

        verdict = "PASS" if sizing.outcome in ("SIZED", "SKIP") else "NOT_APPLICABLE"
        if verdict == "NOT_APPLICABLE":
            values["not_applicable_reason"] = sizing.reason
            provenance["not_applicable_reason"] = derived(
                "no matrix cell applies — GRADE-019 refusal or an ungraded box"
            )

        return cls.evaluation(
            verdict,
            values=values,
            value_provenance={k: v for k, v in provenance.items() if k in values},
        )


class RiskCeilingConformance(RuleImplementation):
    """SIZE-004: the 2% tier is unreachable, and its retirement was by omission.

    TWO ASSERTIONS, AND ONLY ONE OF THEM CAN CURRENTLY FAIL — SAY SO RATHER THAN COUNT TWO
    GUARDS. The output is `risk_pct <= 0.015 AND risk_pct in the nine matrix values`. The
    largest matrix cell IS 0.015, so for eight of the nine cells membership already implies
    the ceiling and the ceiling assertion is unexercisable. On `MANIPULATED_NONE` it is
    exactly saturated, so there it is a real boundary guard. Against any value NOT drawn from
    the table the two assertions are genuinely independent — and that is the case that
    matters, because the failure this rule exists to catch is a sizer that INTERPOLATES.

    A single `<=` check passes every interpolation: 0.009 satisfies the ceiling and is not a
    cell. The membership half is the stronger one and is the reason `risk_altcoin_heavy`'s
    0.05 could never reach a position even if something read it.
    """

    RULE_ID = "SIZE-004"

    COVERAGE_NOTE = (
        "THE CONFORMANCE ASSERTION, CHECKED AGAINST A SUPPLIED risk_pct. Both halves of the "
        "output are implemented separately and reported separately — the ceiling (<= 0.015) "
        "and membership in the nine matrix values. The ceiling half is dormant for eight of "
        "the nine cells because the matrix's own maximum IS the ceiling; it bites on values "
        "that did not come from the table, which is exactly the interpolation case. The 2% "
        "tier's retirement BY OMISSION rather than by argument is recorded in "
        "KNOWN_ISSUES.md as the rule's own statement requires, and `retired_ceiling` is "
        "stamped on every evaluation so the omission stays visible in stored records too."
    )

    MAX_RISK_PCT: float = float(contract.rule("SIZE-004")["values"]["max_risk_pct"])
    RETIRED_CEILING: float = float(contract.rule("SIZE-004")["values"]["retired_ceiling"])

    @classmethod
    def check(cls, risk_pct: float) -> dict[str, Any]:
        """The two assertions, evaluated and reported SEPARATELY.

        Returned as named booleans rather than one verdict so a record shows WHICH half
        failed. A sizer that interpolates fails only the second; a sizer that reads a corrupt
        cell fails both, and the difference names the defect.
        """
        within_ceiling = risk_pct <= cls.MAX_RISK_PCT
        in_matrix = any(
            math.isclose(risk_pct, legal, rel_tol=0.0, abs_tol=RISK_PCT_TOLERANCE)
            for legal in LEGAL_RISK_PCTS
        )
        return {
            "risk_pct": risk_pct,
            "within_ceiling": within_ceiling,
            "in_matrix_values": in_matrix,
            "conforms": within_ceiling and in_matrix,
        }

    @classmethod
    def evaluate(cls, sizing: RiskSizing) -> RuleEvaluation:
        """SIZE-004's telemetry for one sizing decision.

        NOT_APPLICABLE when no risk_pct was emitted — a refusal has no number, so there is
        nothing to assert conformance about. That is not the same as conforming.
        """
        values: dict[str, Any] = {
            "max_risk_pct": cls.MAX_RISK_PCT,
            "retired_ceiling": cls.RETIRED_CEILING,
            "retirement_by_omission": True,
            "legal_risk_pct_count": len(LEGAL_RISK_PCTS),
            "matrix_cell_count": len(RISK_MATRIX),
        }
        provenance: dict[str, Any] = {
            "max_risk_pct": from_registry("SIZE-004", "values.max_risk_pct"),
            "retired_ceiling": from_registry("SIZE-004", "values.retired_ceiling"),
            "retirement_by_omission": from_registry("SIZE-004", "statement"),
            "legal_risk_pct_count": derived(
                "len(set(RISK_MATRIX.values())) — SEVEN distinct values across NINE cells, "
                "because all three HEAVY cells are 0.0"
            ),
            "matrix_cell_count": derived("len(RISK_MATRIX)"),
            "risk_pct": from_registry("GATE-032", "values"),
            "within_ceiling": derived("risk_pct <= max_risk_pct"),
            "in_matrix_values": derived(
                "risk_pct is within 1e-12 of one of the matrix's distinct values"
            ),
            "conforms": derived("within_ceiling and in_matrix_values"),
            "not_applicable_reason": derived("no risk_pct was emitted, so none to check"),
            "violations": derived("SIZE-004 conformance failures, named individually"),
        }

        if sizing.risk_pct is None:
            values["not_applicable_reason"] = (
                f"{sizing.outcome}: no risk_pct was emitted, so there is no value to check "
                "against the ceiling or against the matrix. A refusal is not a conforming "
                "size."
            )
            return cls.evaluation(
                "NOT_APPLICABLE",
                values=values,
                value_provenance={k: v for k, v in provenance.items() if k in values},
            )

        result = cls.check(sizing.risk_pct)
        values.update(result)

        if not result["conforms"]:
            violations = []
            if not result["within_ceiling"]:
                violations.append(
                    f"risk_pct {sizing.risk_pct} exceeds SIZE-004's ceiling "
                    f"{cls.MAX_RISK_PCT} — a HARD violation"
                )
            if not result["in_matrix_values"]:
                violations.append(
                    f"risk_pct {sizing.risk_pct} is not one of GATE-032's nine matrix "
                    "values — an interpolated cell satisfies the ceiling and still "
                    "violates the matrix"
                )
            values["violations"] = violations
            return cls.evaluation(
                "FAIL",
                values=values,
                value_provenance={k: v for k, v in provenance.items() if k in values},
            )

        return cls.evaluation(
            "PASS",
            values=values,
            value_provenance={k: v for k, v in provenance.items() if k in values},
        )


class AltcoinRiskUndefined(RuleImplementation):
    """GRADE-019: the Risk Altcoin column is unruled, so the engine refuses to size altcoins.

    THE CORRECT BEHAVIOUR IS A REFUSAL, WHICH LOOKS EXACTLY LIKE "NOT IMPLEMENTED" UNLESS THE
    REFUSAL IS RECORDED. That is why this is a rule class with its own telemetry rather than
    an early return inside GATE-032: coverage would otherwise count the rule as built while
    the engine did nothing, and no reader could tell a refusal from a gap.
    """

    RULE_ID = "GRADE-019"

    #: `instrument_class` is a DATA NAME, not a rule id — TARGET-001 declares its own absent
    #: producer the same way. 82 of 117 rules write their inputs as data names, so a rule-id
    #: graph cannot see this edge at all (B44); the rule knows and the graph does not.
    #:
    #: TARGET-001's producer is deliberately NOT named here in full. T-0023 guards it with a
    #: substring scan over all of `app/`, which cannot tell a producer from a mention, so
    #: spelling it in this comment turns that tripwire red. Filed as B112.
    CANNOT_FIRE_WITHOUT = ("instrument_class",)

    COVERAGE_NOTE = (
        "IMPLEMENTED AND UNABLE TO FIRE IN PRODUCTION, AND THE UNREACHABILITY IS THE FINDING. "
        "The refusal is real, tested against a synthetic altcoin input, and carries a named "
        "reason so it can never read as silence. It cannot execute on live data: the roster "
        "is {BTC/USD, ETH/USD}, both majors; `instrument_class` is HARDCODED "
        "\"ALIGNED_MAJOR\" at shadow.py:746 and crypto_loop.py:794; no producer classifies "
        "an instrument; and GATE-008 RAISES on an altcoin roster because the corpus states "
        "altcoins cannot be magic-aligned at all. Adding a classifier to make the branch "
        "reachable would be a roster change GATE-008 refuses on doctrine, so it is "
        "deliberately not done. THE RULE CONTRADICTS ITSELF and the Manager ruled on "
        "2026-08-16 that `output` governs: `output` says refuse, `triage_note` says ship the "
        "disturbance-invariant scale {0.0075, 0.005, 0.0025}. Refusing also fails toward "
        "SMALLER positions. The registry's altcoin Heavy vector — the one whose name ends "
        "`_as_written` — is NEVER INDEXED: its middle cell is 0.05, exactly ten times its "
        "siblings, 3.33x over SIZE-004's ceiling, in the column GATE-032 sets to zero. The "
        "`_as_written` suffix marks it a QUOTATION rather than a value, and it is left "
        "unreconciled rather than corrected. See this module's docstring for the arithmetic; "
        "the full name is deliberately absent from executable code, including from this "
        "note, and an AST check in test_t0024_position_sizing.py enforces that."
    )

    REFUSAL_REASON = ALTCOIN_REFUSAL_REASON

    @classmethod
    def refuses(cls, instrument_class: InstrumentClass) -> bool:
        """Whether GRADE-019 refuses to size this instrument class.

        Deliberately NOT conditioned on `declared_parameters.altcoin_trading_enabled`. That
        parameter records whether the engine would TRADE altcoins, which is a separate
        unstated question; even were it true, the risk column for them is UNDEFINED and
        sizing would still have to refuse. Wiring the flag in here would make an
        engine-side toggle able to unlock a number the doctrine never supplied.
        """
        return instrument_class == "ALTCOIN"

    @classmethod
    def evaluate(cls, sizing: RiskSizing) -> RuleEvaluation:
        """GRADE-019's telemetry.

        PASS — an altcoin was presented and the engine refused. The rule fired and did what
        its output states.
        NOT_APPLICABLE — the instrument is an aligned major, so there is nothing to refuse.
        Recorded with its reason rather than omitted, because a rule that is silently absent
        from a record is indistinguishable from one that was never implemented (C-04).
        """
        refuses = cls.refuses(sizing.instrument_class)
        values: dict[str, Any] = {
            "instrument_class": sizing.instrument_class,
            "refused": refuses,
            "unanswered_cells": int(contract.rule("GRADE-019")["values"]["unanswered_cells"]),
            "branch_reachable_in_production": False,
            "cannot_fire_without": list(cls.CANNOT_FIRE_WITHOUT),
        }
        provenance: dict[str, Any] = {
            "instrument_class": derived(
                "SUPPLIED — no producer exists; shadow.py:746 and crypto_loop.py:794 both "
                "hardcode ALIGNED_MAJOR"
            ),
            "refused": from_registry("GRADE-019", "output"),
            "unanswered_cells": from_registry("GRADE-019", "values.unanswered_cells"),
            "branch_reachable_in_production": derived(
                "roster is {BTC/USD, ETH/USD}; instrument_class is hardcoded ALIGNED_MAJOR; "
                "GATE-008 raises on an altcoin roster — so this branch is NOT_EXERCISED by "
                "any live path and is asserted against a synthetic input instead"
            ),
            "cannot_fire_without": derived("the class constant, so the record carries it too"),
            "refusal_reason": derived("GRADE-019's named refusal token"),
            "refusal_detail": from_registry("GRADE-019", "output"),
            "not_applicable_reason": derived("the instrument is an aligned major"),
        }

        if refuses:
            values["refusal_reason"] = cls.REFUSAL_REASON
            values["refusal_detail"] = sizing.reason
            return cls.evaluation(
                "PASS",
                values=values,
                value_provenance={k: v for k, v in provenance.items() if k in values},
            )

        values["not_applicable_reason"] = (
            "instrument_class is ALIGNED_MAJOR, so GRADE-019 has nothing to refuse. The "
            "Risk Alignment column is ruled (GRADE-017) and GATE-032 sizes from it."
        )
        return cls.evaluation(
            "NOT_APPLICABLE",
            values=values,
            value_provenance={k: v for k, v in provenance.items() if k in values},
        )
