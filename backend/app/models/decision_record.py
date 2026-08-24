import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    Index,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy import UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# ---------------------------------------------------------------------------
# Enum-like vocabularies.
#
# CONTRACT 4: enum-like columns are plain ``sa.String`` guarded by a CHECK
# constraint (NOT a Postgres ENUM type) so migrations never have to CREATE TYPE.
# The allowed values live here as module constants so the model, the CHECK
# constraints, and any calling code all share a single source of truth.
# ---------------------------------------------------------------------------

# signal_dir --------------------------------------------------------------
SIGNAL_DIR_LONG = "LONG"
SIGNAL_DIR_SHORT = "SHORT"
SIGNAL_DIRECTIONS: tuple[str, ...] = (SIGNAL_DIR_LONG, SIGNAL_DIR_SHORT)

# outcome (aligns with app.db.enums.OutcomeType, plus ABSTAINED for the
# no-trade decisions this table also records) -----------------------------
OUTCOME_WIN = "WIN"
OUTCOME_LOSS = "LOSS"
OUTCOME_BREAKEVEN = "BE"
OUTCOME_OPEN = "OPEN"
OUTCOME_ABSTAINED = "ABSTAINED"
#: The position existed and its result is unknowable — the process that held it
#: died before it closed. NOT a synonym for a loss, and not a fifth kind of
#: result: it is the absence of one, recorded so it stops being counted as still
#: in progress. Added for KNOWN_ISSUES A11, where an ETH long opened at 06:00 and
#: was annihilated by a container recreate twelve hours later, leaving a record
#: reading OPEN for good and a run reporting "0 trades" when it had taken one.
#:
#: It is deliberately its own value rather than BE. Folding it into breakeven
#: would put a fabricated zero into the feedback loop's realized-R population;
#: ABANDONED is excluded from that population instead, which is the honest
#: treatment of a number nobody ever observed.
OUTCOME_ABANDONED = "ABANDONED"
#: The strategy PRODUCED a signal and EXECUTION refused it (`B271`/`T-0084`).
#:
#: **DELIBERATELY NOT `ABSTAINED`, and this is the whole of the value.** `ABSTAINED` means
#: the detector never fired; this means it did and the order was declined. Folding them
#: makes a `took_trade=True` bar indistinguishable from one where nothing was found —
#: `B215`'s could-not-versus-did-not collapse, rebuilt **inside the one population that is
#: currently correct**, which is `B268`'s denominator.
#:
#: Same argument `ABANDONED` makes above: its own value rather than the nearest existing
#: one, because the nearest existing one is a different fact.
OUTCOME_REJECTED = "REJECTED"
DECISION_OUTCOMES: tuple[str, ...] = (
    OUTCOME_WIN,
    OUTCOME_LOSS,
    OUTCOME_BREAKEVEN,
    OUTCOME_OPEN,
    OUTCOME_ABSTAINED,
    OUTCOME_ABANDONED,
    OUTCOME_REJECTED,
)

# cohort ------------------------------------------------------------------
COHORT_REPLAY = "replay"
COHORT_BACKTEST = "backtest"
COHORT_PAPER = "paper"
COHORT_LIVE = "live"
DECISION_COHORTS: tuple[str, ...] = (
    COHORT_REPLAY,
    COHORT_BACKTEST,
    COHORT_PAPER,
    COHORT_LIVE,
)


# attribution -------------------------------------------------------------
# WHY TWO COLUMNS AND NOT ONE NULLABLE STRING
# A single nullable `deciding_rule_id` would make NULL mean three different
# things at once: the ICT path decided (no rule engine involved), the rule
# engine decided but the decider was lost on the way to the row, or the rule
# engine decided and legitimately had no rule to name. The middle one is a
# DEFECT and the other two are normal, so one value cannot carry all three
# without hiding the only case worth finding.
#
# That is B31 one layer down: `shadow.py:607` does `deciding_rule_id or
# "GATE-036"`, which collapses "nothing decided" into "GATE-036 decided" and
# makes "every abstention cites a rule id" satisfiable by a default. This pair
# of columns exists so the live table cannot repeat it.
#
#   decided_by     deciding_rule_id     meaning
#   UNSET          NULL                 NOBODY SAID. The write path omitted attribution.
#   ICT            NULL                 ICT path decided. Every row until the cutover.
#   RULE_ENGINE    NULL                 PLUMBING DEFECT — the decider was lost.
#   RULE_ENGINE    NO_RULE_DECIDED      Rule engine ran, no rule to name. Honest.
#   RULE_ENGINE    GATE-017             Attributed.
#
# The two defect rows are found by one query each and no normal state matches:
#
#   SELECT * FROM decision_records
#    WHERE decided_by = 'RULE_ENGINE' AND deciding_rule_id IS NULL;   -- decider lost
#   SELECT * FROM decision_records WHERE decided_by = 'UNSET';        -- nobody said
#
# WHY THE DEFAULT IS `UNSET` AND NOT `ICT`
# Defaulting to ICT would make "every decision names its decider" SATISFIABLE BY A
# DEFAULT — B31's exact shape, in the columns added to prevent B31. The failure it
# produces is not a missing row but a FALSE one: after the cutover, a write path
# that forgets the attribution would record a rule-engine decision as ICT-decided,
# in the evidence base, answering the very question this programme exists to
# answer — and the defect query above would never fire for it, because the row
# claims ICT.
#
# The fix is NOT to drop the default and let NOT NULL raise. Both write sites
# swallow bookkeeping exceptions, so the insert would be refused, the exception
# eaten, and the row LOST — trading a false row for no row, which is worse. UNSET
# is stored, detectable, and can never be read as a real attribution.
#
# CASE 2 IS DELIBERATELY STORABLE. A CHECK constraint forbidding it would make
# the insert raise, and both write sites swallow bookkeeping exceptions rather
# than kill the trading loop — so a plumbing defect would silently DROP the row
# and the corpus would lose precisely the evidence that the defect happened.
# Storing it and detecting it by query is strictly better than refusing it and
# losing it.
#
# WHERE THE LINE IS, AND WHY IT IS THERE — the rule for adding a new state.
# "Storing beats refusing" alone does not decide this; taken alone it would
# justify storing the contradictions too. The completing half:
#
#     REFUSE what the API cannot produce.  STORE what the runtime can.
#
# `Attribution` is frozen, `ict()` hard-codes a NULL rule id, and
# `from_rule_evaluation()` is the only rule-engine path and raises on a bare
# string — so `ICT + rule id` and `UNSET + rule id` are UNREACHABLE through the
# sanctioned API. Reaching them means bypassing the value object, which is a
# deterministic bug that recurs on every write, so refusing one row loses no
# unique evidence. `RULE_ENGINE + NULL` is a RUNTIME state and may be
# intermittent, so the row is the only evidence it ever happened.
#: Nobody set an attribution on this row. The DEFAULT, deliberately — see above.
#: It is a legal stored value rather than a rejected one so the omission survives
#: to be counted, and it is a distinct word rather than NULL so it cannot be
#: confused with either the ICT case or the lost-decider case.
DECIDED_BY_UNSET = "UNSET"
DECIDED_BY_ICT = "ICT"
DECIDED_BY_RULE_ENGINE = "RULE_ENGINE"
DECIDED_BY_VALUES: tuple[str, ...] = (
    DECIDED_BY_UNSET,
    DECIDED_BY_ICT,
    DECIDED_BY_RULE_ENGINE,
)

#: The two states that mean "this row cannot be trusted to name its decider".
#: Exposed as a vocabulary so an audit cannot hand-roll a narrower one and miss a
#: member the way a hand-written IN-list would.
DECIDED_BY_UNTRUSTWORTHY: tuple[str, ...] = (DECIDED_BY_UNSET,)

#: The rule engine reached a verdict and no single rule owns it. A SENTINEL, not
#: a rule: it must never collide with a registry id, and
#: `test_decision_attribution.py` asserts that against the real 117-entry
#: registry rather than trusting this comment. Registry ids are all `PREFIX-N`
#: (`GATE-036`, `GRADE-029`, `ENTRY-003`), so an underscored word cannot clash.
#:
#: It is a distinct value rather than NULL because NULL is how a LOST decider
#: presents, and "we looked and there was nothing to name" is a different claim
#: from "we do not know what happened here".
NO_RULE_DECIDED = "NO_RULE_DECIDED"


def _sql_in(column: str, values: tuple[str, ...]) -> str:
    """Render ``column IN ('a', 'b', ...)`` for a CHECK constraint.

    Values are drawn from the module-level vocabularies above (never user
    input), so simple single-quote wrapping is safe here.
    """
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


@dataclass(frozen=True)
class Attribution:
    """`decided_by` and `deciding_rule_id` as ONE value, so they cannot drift.

    WHY THE PAIR IS A SINGLE OBJECT
    The two columns are only meaningful together — `RULE_ENGINE` with no id is a
    defect, `ICT` with an id is a contradiction. Handing callers two independent
    keyword arguments invites exactly the combination that should be impossible,
    so the only sanctioned way to fill them is to build one of these.

    WHY THERE IS NO CONSTRUCTOR TAKING A RULE ID STRING
    `evaluator.py:25` states that `deciding_rule_id` is **the FIRST rule that
    failed**, which makes evaluation ORDER load-bearing — the value is a property
    of a completed evaluation and of nothing else. `gate_036_stand_aside.py:35` is
    explicit that nothing may pass a decider in by hand. A classmethod taking
    `str` would let a caller assert an attribution it did not compute, which is
    the same laundering B31 records, so `from_rule_evaluation` takes the
    EVALUATION and reads the accessor itself.
    """

    decided_by: str
    deciding_rule_id: str | None

    @classmethod
    def ict(cls) -> "Attribution":
        """The ICT path decided. No rule engine ran, so there is no rule to name."""
        return cls(decided_by=DECIDED_BY_ICT, deciding_rule_id=None)

    @classmethod
    def from_rule_evaluation(cls, evaluation: Any) -> "Attribution":
        """Read the decider off a completed evaluation. The ONLY rule-engine path.

        A missing decider becomes `NO_RULE_DECIDED` — an explicit "nothing owned
        this verdict" — never `None`, because `None` is reserved for the plumbing
        defect this pair exists to expose. That means a row written through here
        can never present as case 2: case 2 is only reachable by bypassing this
        method, which is precisely the failure the query is looking for.
        """
        if isinstance(evaluation, str) or not hasattr(evaluation, "deciding_rule_id"):
            raise TypeError(
                "Attribution.from_rule_evaluation needs the evaluation object, not a "
                "decider value — the decider is the first rule that FAILED and is a "
                "property of the evaluation's order, not something a caller may assert "
                f"(got {type(evaluation).__name__})"
            )
        decider = evaluation.deciding_rule_id
        return cls(
            decided_by=DECIDED_BY_RULE_ENGINE,
            deciding_rule_id=decider if decider else NO_RULE_DECIDED,
        )

    def as_columns(self) -> dict[str, Any]:
        """Keyword arguments for `DecisionRecord(...)`."""
        return {
            "decided_by": self.decided_by,
            "deciding_rule_id": self.deciding_rule_id,
        }


class DecisionRecord(Base):
    """Immutable audit row for EVERY engine decision — a trade or an abstain.

    One row is written whenever the decision engine evaluates a setup, whether
    it produced a signal or abstained. The row captures the inputs fingerprint,
    the code path fingerprint, the score, the proposed signal geometry, and —
    once the trade closes — the realized-vs-expected gap that CONTRACT 5's
    feedback engine consumes. Mirrors ``Trade`` for its ``Base`` import, its
    UUID ``id`` and ``created_at`` conventions, and its ``mapped_column`` style.
    """

    __tablename__ = "decision_records"

    id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # What was evaluated ---------------------------------------------------
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    timeframe: Mapped[str] = mapped_column(String, nullable=False)

    # Reproducibility fingerprints ----------------------------------------
    inputs_hash: Mapped[str] = mapped_column(String, nullable=False)
    code_path_hash: Mapped[str] = mapped_column(String, nullable=False)

    # Scoring outcome ------------------------------------------------------
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    abstained: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reasons: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    # Proposed signal geometry --------------------------------------------
    signal_dir: Mapped[str | None] = mapped_column(String, nullable=True)
    signal_entry: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    signal_sl: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    signal_tp: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    sized_units: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)

    #: Which engine run produced this decision. See models/engine_run.py — a
    #: reset starts a new run rather than deleting the evidence of the old one.
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        SAUUID(as_uuid=True), nullable=True, index=True
    )

    #: The price the order ACTUALLY filled at, as reported by the broker.
    #:
    #: `signal_entry` is what the strategy asked for; this is what it got. They
    #: differ on every market order, and the difference is the whole reason this
    #: column exists: R computed against `signal_entry` measures performance
    #: against a price that was never paid.
    #:
    #: It also un-blocks the feedback loop's Rule B, which targets adverse fill
    #: slippage and has been dormant since it was written — `_slippage_r()` looks
    #: for exactly this value and, finding nothing, returned None every time.
    #:
    #: Nullable: rows written before this column existed have no fill price, and
    #: readers fall back to `signal_entry` rather than discarding the row.
    fill_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)

    # Expected vs realized (feedback loop inputs) --------------------------
    expected_r: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    realized_r: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    gap_r: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)

    # Resolution -----------------------------------------------------------
    outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    correction_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: THE TWO INPUTS THE SIZE WAS COMPUTED FROM (`B279`/`T-0084`).
    #:
    #: `execution/service.py` sizes with
    #: `size_position(acct.equity, sig.risk_pct, sizing_price, sig.sl)` and **neither of the
    #: first two arguments was recorded anywhere**. `prop_firm_snapshots` has an equity column
    #: and **zero rows**, so the number a trade was sized against has never been persisted.
    #:
    #: **TWO COLUMNS, NOT ONE, BECAUSE ONE RE-BREAKS ON THE NEXT PLANNED CHANGE.**
    #: `risk_pct` is reconstructible today only because it is the constant 1%, and the top
    #: recommendation in front of Malek is to wire the risk matrix — which makes it per-trade
    #: variable. Recording equity alone would be correct until the day that lands.
    #:
    #: **PRECISION IS NOT NEGOTIABLE.** `Numeric(14, 2)` is not enough: the finding this
    #: preserves lived in the fourth decimal — `5000.9197` against `5000.00`.
    #: **AND THE THIRD INPUT, WHICH IS THE DIVISOR (`B280`).** `size_position` takes FOUR
    #: arguments and `sizing_price` is the one the stop distance is measured from —
    #: `service.py:149` sets it to `mark`, the reference price read BEFORE the order goes in,
    #: which is NOT the fill.
    #:
    #: **It is the input that degrades SILENTLY rather than failing.** A reconstruction using
    #: `fill` instead is exact only where both come from the same cached mark — true of
    #: `PaperBroker` today — and otherwise comes out wrong by exactly the slippage: measured,
    #: 50 ticks puts the recomputed size 4.76% out, and nothing in the row says so.
    #: *`fill_price` exists as a separate column precisely because they are not the same
    #: thing*, and MT5 is where slippage gives the fill a second author.
    sizing_equity: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    sizing_risk_pct: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    sizing_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)

    #: WHY execution refused this signal, RAW (`T-0084`).
    #:
    #: **A COLUMN, not `reasons`.** `reasons` is the field `_with_exit_plan`'s own docstring
    #: calls *"a JSON list nothing parses"*, and it is the field `B270` criticised `B268` for
    #: parsing — so putting the reason only there would recreate the problem in the commit
    #: that fixes it.
    #:
    #: **STORED RAW, NOT CLASSIFIED.** The five rejection sites in `execution/service.py`
    #: split three ordinary MARKET CONDITIONS (no reference price, drift beyond threshold,
    #: market already through the stop) against two PRODUCER DEFECTS (non-positive size or
    #: stop, twice). *A corpus that cannot tell a market condition from a fault rebuilds
    #: `B215` in a second place*, and a classification chosen now would fix that split
    #: before anyone has counted it.
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Which population this decision belongs to ----------------------------
    cohort: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=COHORT_REPLAY,
        server_default=COHORT_REPLAY,
    )

    #: WHICH ENGINE decided. Written independently of whether a rule id was
    #: captured — see the attribution block at the top of this module.
    #:
    #: DEFAULTS TO `UNSET`, NOT `ICT`. Defaulting to a real attribution would let
    #: a write path that forgets this column produce a row that CLAIMS to know
    #: who decided — and after the cutover that claim would be false and
    #: undetectable. The historical rows genuinely are ICT and the migration
    #: backfills them explicitly; that is a different question from what a future
    #: forgetful write should record, and one value must not answer both.
    decided_by: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=DECIDED_BY_UNSET,
        server_default=DECIDED_BY_UNSET,
    )

    #: The registry rule that decided, when the rule engine decided. Mirrors
    #: `telemetry_record.py:90` in type and index so the two tables can be joined
    #: and compared — the asymmetry this column closes is that the DISCARDED
    #: shadow verdict has carried an attribution since M9 Stage A while the
    #: acted-on decision has never carried one.
    deciding_rule_id: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            f"signal_dir IS NULL OR {_sql_in('signal_dir', SIGNAL_DIRECTIONS)}",
            name="ck_decision_records_signal_dir",
        ),
        CheckConstraint(
            _sql_in("decided_by", DECIDED_BY_VALUES),
            name="ck_decision_records_decided_by",
        ),
        # ONLY the rule engine may name a rule. The ICT path never consults the
        # registry, and an UNSET row by definition has nobody standing behind its
        # attribution — so a rule id on either is a value copied from somewhere it
        # does not belong, and it would corrupt a `GROUP BY deciding_rule_id`
        # audit with attributions no rule produced.
        #
        # NOTE the asymmetry with the two defect states, which are deliberately
        # NOT constrained: `RULE_ENGINE + NULL` and `UNSET` must be STORABLE so
        # they survive to be counted, while a rule id on a non-rule-engine row is
        # a contradiction that should never be written at all.
        CheckConstraint(
            f"decided_by = '{DECIDED_BY_RULE_ENGINE}' OR deciding_rule_id IS NULL",
            name="ck_decision_records_only_rule_engine_names_a_rule",
        ),
        CheckConstraint(
            f"outcome IS NULL OR {_sql_in('outcome', DECISION_OUTCOMES)}",
            name="ck_decision_records_outcome",
        ),
        CheckConstraint(
            _sql_in("cohort", DECISION_COHORTS),
            name="ck_decision_records_cohort",
        ),
        Index("ix_decision_records_created_at", "created_at"),
        Index("ix_decision_records_cohort", "cohort"),
        # The audit groups by this column and `decision_records` is the larger of
        # the two tables carrying it.
        Index("ix_decision_records_deciding_rule", "deciding_rule_id"),
        Index("ix_decision_records_decided_by", "decided_by"),
    )
