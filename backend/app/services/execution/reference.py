"""**The entry's reference price** (T-0144 ruling R3', `B447`): what a market order is SIZED against and priced for the
venue minimum.

**THE BINANCE MARK FIRST, ALPACA'S QUOTE MID SECOND, NOTHING THIRD.**
  * The Binance mark is what the strategy computes its levels from, it is live, and it is what the simulators and the
    backtest use.
  * Alpaca's paper quote was measured stale for up to 29 s (BTC) and minutes (ETH) — probe round 4 — so it is only a
    fallback, and only while its OWN timestamp is younger than `ALPACA_QUOTE_MAX_AGE_S`. The age is measured from the
    quote's timestamp, never from when we read it: a read made now of a quote stamped two minutes ago is two minutes old.
  * The mid, `(bid + ask) / 2`: the reference is a price for the instrument, not for one side of a spread.
  * Neither usable -> `None`, which `ExecutionService` refuses as `NO_REFERENCE_PRICE`. Never `0.0`, never an older mark.

Every result names its SOURCE and the time the price describes, so a sized entry says what it was sized against.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

#: How old Alpaca's latest quote may be, by its own timestamp, and still stand in for the Binance mark (R3').
ALPACA_QUOTE_MAX_AGE_S: float = 120.0
#: How old the loop's Binance mark may be and still be "the live mark". The loop reads it on the same tick that
#: evaluates the bar, so a real mark is seconds old; one older than this is a mark from a tick that did not happen now.
BINANCE_MARK_MAX_AGE_S: float = 60.0

SOURCE_BINANCE = "binance_mark"
SOURCE_ALPACA_QUOTE_MID = "alpaca_quote_mid"


@dataclass(frozen=True)
class ReferencePrice:
    price: float
    source: str
    #: the time the price DESCRIBES (the mark's tick, or the quote's own timestamp), timezone-aware UTC
    at: datetime


@dataclass(frozen=True)
class VenueQuote:
    bid: float | None
    ask: float | None
    #: the quote's OWN timestamp, as the venue stamped it
    timestamp: datetime | None


def _usable(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) and value > 0 else None


def _aware(when: datetime | None) -> datetime | None:
    if not isinstance(when, datetime):
        return None
    return when if when.tzinfo is not None else when.replace(tzinfo=timezone.utc)


def choose_reference(binance: ReferencePrice | None, quote: VenueQuote | None, *,
                     now: datetime | None = None) -> ReferencePrice | None:
    """The reference price for an entry, or `None`. Pure: `now` is injectable for the arms."""
    now = _aware(now) or datetime.now(timezone.utc)
    if binance is not None:
        price, at = _usable(binance.price), _aware(binance.at)
        if price is not None and at is not None and (now - at).total_seconds() <= BINANCE_MARK_MAX_AGE_S:
            return ReferencePrice(price=price, source=SOURCE_BINANCE, at=at)
    if quote is not None:
        bid, ask, stamped = _usable(quote.bid), _usable(quote.ask), _aware(quote.timestamp)
        if bid is not None and ask is not None and stamped is not None:
            age = (now - stamped).total_seconds()
            if 0 <= age <= ALPACA_QUOTE_MAX_AGE_S:
                return ReferencePrice(price=(bid + ask) / 2, source=SOURCE_ALPACA_QUOTE_MID, at=stamped)
    return None
