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
#: The venue FILLED SOMETHING and we cannot say how much (`B413`/`T-0143`).
#:
#: A market order came back `PARTIALLY_FILLED` with no usable filled quantity, so a position exists
#: at the venue whose size we cannot establish. The run HALTS on this — trading around a position
#: of unknown size is worse than stopping — and this is the durable record of the decision that
#: produced it.
#:
#: **ITS OWN VALUE, on `ABANDONED`'s and `REJECTED`'s own argument, because all three nearest
#: neighbours are a DIFFERENT FACT:**
#:
#: * `REJECTED` says execution REFUSED the signal. Nothing was refused — the venue accepted the
#:   order and acted on it. Filing it here is a false statement about what happened, and it is
#:   what the loop did before this value existed: `outcome=REJECTED`, `code=UNCLASSIFIED`, for an
#:   order the venue had partly filled.
#: * `OPEN` says a position exists at a known size, and `sized_units` is what the partial-close
#:   accounting reads (`crypto_loop.py:1579`, `:1624`). We do not have that number — that is the
#:   whole condition.
#: * `ABANDONED` says a position died before it closed. This one may still be open; nobody knows.
#:
#: **Excluded from the realized-R population for `ABANDONED`'s reason** — there is no number anyone
#: observed, and a fabricated zero in the feedback loop is worse than an absent row.
OUTCOME_UNSIZED_FILL = "UNSIZED_FILL"
DECISION_OUTCOMES: tuple[str, ...] = (
    OUTCOME_WIN,
    OUTCOME_LOSS,
    OUTCOME_BREAKEVEN,
    OUTCOME_OPEN,
    OUTCOME_ABSTAINED,
    OUTCOME_ABANDONED,
    OUTCOME_REJECTED,
    OUTCOME_UNSIZED_FILL,
)

# rejection_code ----------------------------------------------------------
#
# **`B392`: "M SHORTS REFUSED BY VENUE" IS NOT COUNTABLE FROM PROSE.** `rejection_reason` is free
# `Text`, and a count that matched it would be keyed on a sentence the VENUE chose — returning a
# confident zero the day the wording changes rather than failing. This is the structured half;
# the prose stays, unaltered, for diagnosis.
#
# **ONE MEMBER PER DECISION, NOT PER SENTENCE, AND THE VOCABULARY WAS GREPPED FROM THE DECISION
# SITES RATHER THAN INVENTED.** Two facts from that grep shaped it:
#
#   * `service.py:130` and `:153` emit the BYTE-IDENTICAL string `"non-positive size / stop"` for
#     two different decisions — a degenerate stop (entry == sl, a strategy defect) and a size that
#     came out non-positive (equity against stop width). **Opposite remedies.** The prose cannot
#     separate them even in principle, so here the code is strictly MORE informative than the text
#     it sits beside.
#   * the prop-firm family splits SIX ways, not one. A single `PROP_FIRM_RULE` would be **lossier
#     than the string it replaces** — the one direction a structuring change must never go — and
#     `PROFIT_TARGET_REACHED` is the proof: a PASSED challenge refusing new orders, bucketed as a
#     rejection, is wrong in the flattering direction. *Already halted* and *would breach* also
#     carry opposite remedies (stop the engine vs size down), and daily loss resets where drawdown
#     does not.
#
# ⚠ **A DIFFERENT `rejection_reason` LIVES IN `gate_027_stop_ladder.py`** — `NONE`,
# `NOT_LOCATABLE`, `RR_BELOW_2R` — over RULE CANDIDATES, not orders. **Same field name, different
# axis.** It is NOT part of this vocabulary, and it is named here because the next person building
# this list will grep the name and find both.
REJECTION_NO_REFERENCE_PRICE = "NO_REFERENCE_PRICE"
REJECTION_DEGENERATE_STOP = "DEGENERATE_STOP"
REJECTION_ENTRY_DRIFT = "ENTRY_DRIFT"
REJECTION_THROUGH_STOP = "THROUGH_STOP"
REJECTION_NON_POSITIVE_SIZE = "NON_POSITIVE_SIZE"
REJECTION_VENUE_DIRECTION_UNSUPPORTED = "VENUE_DIRECTION_UNSUPPORTED"

#: The size was POSITIVE but below the venue's published minimum for that asset (`T-0140`).
#:
#: **DISTINCT FROM `NON_POSITIVE_SIZE`, and the two have different remedies.** `units <= 0` is
#: arithmetic on our side — equity against stop width, or a degenerate stop. This is the VENUE's
#: floor: the order is well-formed and simply too small to place. Collapsing them is part 3's
#: `M-8` reappearing one task later.
#:
#: **The floor is not a constant.** Measured (`T-0139`/`B409`): BTC `0.000012941`, ETH
#: `0.000397984` — both $1.00 of notional, so the minimum MOVES WITH PRICE while
#: `min_trade_increment` (`1e-9` on both) does not. The two fields have different natures.
REJECTION_MIN_SIZE = "MIN_SIZE"
#: **`B429`.** The venue took the order and did NOT report the stop, so the position was closed
#: again and the decision is correctly recorded as not taken.
#:
#: **ITS OWN CODE, for `MIN_SIZE`'s reason.** Filed as `VENUE_TRANSPORT` it would read as a
#: transient blip that clears on its own; filed as `VENUE_DIRECTION_UNSUPPORTED` it would name the
#: wrong capability. It is not transient: it recurs while the observed condition holds — the venue
#: created no working stop, OR parked one in a status `WORKING_STOP_LEG_STATUSES` does not yet admit
#: (that list is unmeasured, and then too narrow). Telling an operator which world they are in is the
#: whole value of the code — `B375`'s confusion is what sharing one would rebuild.
REJECTION_PROTECTION_NOT_ACCEPTED = "PROTECTION_NOT_ACCEPTED"
REJECTION_PROP_FIRM_TARGET_REACHED = "PROP_FIRM_TARGET_REACHED"
REJECTION_PROP_FIRM_HALTED_DAILY_LOSS = "PROP_FIRM_HALTED_DAILY_LOSS"
REJECTION_PROP_FIRM_HALTED_MAX_DRAWDOWN = "PROP_FIRM_HALTED_MAX_DRAWDOWN"
REJECTION_PROP_FIRM_HALTED = "PROP_FIRM_HALTED"
REJECTION_PROP_FIRM_WOULD_BREACH_DAILY_LOSS = "PROP_FIRM_WOULD_BREACH_DAILY_LOSS"
REJECTION_PROP_FIRM_WOULD_BREACH_MAX_DRAWDOWN = "PROP_FIRM_WOULD_BREACH_MAX_DRAWDOWN"

#: The engine held no broker when something asked it to trade. **A LEGITIMATE IDLE STATE, and it
#: must NOT alarm.** Enumerating it is the whole point: we hardened every fallback so that absence
#: alarms, and a real idle path left off the list would land in the alarming bucket — the
#: liveness-signal failure arriving through the ENUMERATION rather than through the default.
#: It also gives `LiveLoopBrokerProxy.unavailable_reason` its first reader (`B394`'s first
#: instance), closing that one rather than adding to it.
REJECTION_BROKER_UNAVAILABLE = "BROKER_UNAVAILABLE"

#: The venue was REACHED and failed — a connection error, an auth rejection, a rate limit, a 5xx
#: (`B403`'s transport half). **DISTINCT FROM `VENUE_DIRECTION_UNSUPPORTED` ON PURPOSE, and the
#: distinction is `B375` itself**: a permanent venue RULE and a temporary FAILURE demand opposite
#: responses — one will refuse the same order forever, the other clears on its own. Sharing a code
#: would rebuild that confusion *inside the field built to prevent it*.
REJECTION_VENUE_TRANSPORT = "VENUE_TRANSPORT"

#: `place_order` RAISED with something outside the venue's own error family — so it is not
#: classifiable as a rule or as transport. **The bar used to abort here and leave NO ROW AT ALL**
#: (`B403`) — not an
#: unclassified row, absent from the denominator entirely, so a surface reading *"100% of
#: rejections were direction refusals"* would be reporting the shape of a silence.
REJECTION_VENUE_RAISED = "VENUE_RAISED"

#: **THE TWO UNKNOWNS, AND THEY MUST NEVER SHARE A VALUE.**
#:
#: `UNCODED_LEGACY` predates the field: knowably unknowable, **finite and SHRINKING**, so it is a
#: migration marker that decays to zero on its own and is safe to show on every row.
#: `UNCLASSIFIED` is a NEW rejection nothing coded — **a defect, and it must ALARM.**
#:
#: Collapsing them is `B215`'s could-not-ask/did-not conflation on a new field: a new uncoded row
#: landing in the legacy bucket means the bucket never decays, the alarm never fires, and the
#: failure is invisible for exactly as long as the legacy rows exist.
#:
#: **AND THE LEGACY ROWS ARE NEVER BACKFILLED FROM THE PROSE.** That would be a count keyed on
#: vocabulary the venue chose, manufactured once and thereafter indistinguishable from a
#: measurement. If a backfill is ever done, the code must carry its own provenance —
#: `recorded` vs `inferred` — or a parsed count becomes unreadable as a measured one.
REJECTION_UNCODED_LEGACY = "UNCODED_LEGACY"
REJECTION_UNCLASSIFIED = "UNCLASSIFIED"

REJECTION_CODES: tuple[str, ...] = (
    REJECTION_NO_REFERENCE_PRICE,
    REJECTION_DEGENERATE_STOP,
    REJECTION_ENTRY_DRIFT,
    REJECTION_THROUGH_STOP,
    REJECTION_NON_POSITIVE_SIZE,
    REJECTION_VENUE_DIRECTION_UNSUPPORTED,
    REJECTION_MIN_SIZE,
    REJECTION_PROTECTION_NOT_ACCEPTED,
    REJECTION_PROP_FIRM_TARGET_REACHED,
    REJECTION_PROP_FIRM_HALTED_DAILY_LOSS,
    REJECTION_PROP_FIRM_HALTED_MAX_DRAWDOWN,
    REJECTION_PROP_FIRM_HALTED,
    REJECTION_PROP_FIRM_WOULD_BREACH_DAILY_LOSS,
    REJECTION_PROP_FIRM_WOULD_BREACH_MAX_DRAWDOWN,
    REJECTION_BROKER_UNAVAILABLE,
    REJECTION_VENUE_TRANSPORT,
    REJECTION_VENUE_RAISED,
    REJECTION_UNCODED_LEGACY,
    REJECTION_UNCLASSIFIED,
)

#: Codes that mean **nobody classified this**, as opposed to a coded decision. `UNCLASSIFIED`
#: alarms; `UNCODED_LEGACY` does not. A surface must be able to ask which it has.
REJECTION_CODES_UNKNOWN: tuple[str, ...] = (
    REJECTION_UNCODED_LEGACY,
    REJECTION_UNCLASSIFIED,
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
    #: **STORED RAW, AND NOW CLASSIFIED BESIDE RATHER THAN INSTEAD** (`B392`, `T-0138`).
    #:
    #: This used to say *"STORED RAW, NOT CLASSIFIED"*, and gave a reason that was correct at the
    #: time: *"a classification chosen now would fix that split before anyone has counted it."*
    #: **The counting is what forced it.** `GROUP BY signal_dir` over `REJECTED` cannot answer
    #: *M shorts refused by venue* without matching this text — a count keyed on a sentence the
    #: VENUE chose, which returns a confident zero the day the wording changes rather than
    #: failing.
    #:
    #: So `rejection_code` carries the classification and **this field is unchanged**: free text,
    #: the venue's own words, for diagnosis. The structured field is for counting; the prose is
    #: for reading. Neither is derived from the other — deriving the code from this text is
    #: exactly the defect the code exists to remove.
    #:
    #: **AND THE OLD COMMENT UNDERSTATED ITS OWN SPLIT.** It counted *"two PRODUCER DEFECTS
    #: (non-positive size or stop, twice)"* as one category seen twice. They are two DECISIONS
    #: with opposite remedies — a degenerate stop is a strategy defect, a non-positive size is
    #: equity against stop width — emitting a byte-identical string. `rejection_code` separates
    #: them; this field never could.
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: WHICH DECISION produced the rejection, assigned AT THE DECISION SITE (`B392`).
    #:
    #: Nullable ONLY because rows predating the field exist; the migration backfills those with
    #: `UNCODED_LEGACY` rather than with any live code, and that is a one-way door — once a
    #: pre-existing row carries a live code, nothing can tell it from one classified at the
    #: decision.
    #:
    #: **NEVER DERIVED FROM `rejection_reason`.** See the vocabulary above: two decision sites
    #: emit one identical string, so the prose cannot separate them even in principle.
    rejection_code: Mapped[str | None] = mapped_column(String, nullable=True)

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
        # The rejection vocabulary is CLOSED at the database, for the reason every other closed
        # column here is: a value the constant allows and the database refuses, or the reverse,
        # is a difference only a real insert can find (`T-0084`). A code outside this set is a
        # classifier that invented one, and it must not become a bucket nobody notices.
        CheckConstraint(
            f"rejection_code IS NULL OR {_sql_in('rejection_code', REJECTION_CODES)}",
            name="ck_decision_records_rejection_code",
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
