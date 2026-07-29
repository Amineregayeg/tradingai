import uuid
from datetime import datetime
from decimal import Decimal

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
DECISION_OUTCOMES: tuple[str, ...] = (
    OUTCOME_WIN,
    OUTCOME_LOSS,
    OUTCOME_BREAKEVEN,
    OUTCOME_OPEN,
    OUTCOME_ABSTAINED,
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


def _sql_in(column: str, values: tuple[str, ...]) -> str:
    """Render ``column IN ('a', 'b', ...)`` for a CHECK constraint.

    Values are drawn from the module-level vocabularies above (never user
    input), so simple single-quote wrapping is safe here.
    """
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


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

    # Which population this decision belongs to ----------------------------
    cohort: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=COHORT_REPLAY,
        server_default=COHORT_REPLAY,
    )

    __table_args__ = (
        CheckConstraint(
            f"signal_dir IS NULL OR {_sql_in('signal_dir', SIGNAL_DIRECTIONS)}",
            name="ck_decision_records_signal_dir",
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
    )
