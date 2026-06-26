from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, PrimaryKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Candle(Base):
    """OHLCV candle data. Composite primary key: (user_id, pair, timeframe, time)."""

    __tablename__ = "candles"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "pair", "timeframe", "time"),
    )

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False, default="system")
    pair: Mapped[str] = mapped_column(String, nullable=False)
    timeframe: Mapped[str] = mapped_column(String, nullable=False)
    open: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    volume: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), nullable=False, default=Decimal("0")
    )
