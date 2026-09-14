"""**ONE canonical form for a trading pair** (`B449`, `B461`; T-0144 ruling R4).

Alpaca spells a crypto POSITION `BTCUSD` and its ORDERS, ASSETS and FILL activities `BTC/USD`; the engine's pair is
`BTC/USD` (`fixed_config.SYMBOLS`). Every comparison between the loop's pair and a venue's spelling of it goes through
here — an exact `==` between two spellings is how `_has_position` never saw an Alpaca position (`B449`) and how the
broker reconcilers would mark an OPEN trade CLOSED (`B461`).

**EQUALITY, NEVER SUBSTRING, AND THE QUOTE CURRENCY IS KEPT.** `BTCUSDT`, `BTCUSDC` and `BTCUSD` are three different
instruments. The venue converters elsewhere (`cryptofundtrader.to_mt_symbol`, `market_data.sources.cft.to_cft_symbol`)
collapse the quote currency on purpose for their venue and must not be reused for a comparison.

A position is still ADDRESSED at the venue by the venue's own spelling; this only decides whether two spellings name
the same pair.
"""
from __future__ import annotations


def canonical_pair(value: object) -> str:
    """`" btc/usd "` -> `"BTCUSD"`. Uppercase, surrounding whitespace and every `/` removed. Nothing else changes.

    Refuses anything that is not a non-empty string: a missing symbol is not a pair, and a `None` that became `""`
    would compare equal to another missing one (the old `_same_symbol` did exactly that)."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"not a pair: {value!r}")
    return value.strip().upper().replace("/", "")


def same_pair(a: object, b: object) -> bool:
    """Whether two spellings name the same pair. **A missing or empty side is never the same pair** — it answers
    `False` rather than raising, because the callers are filters over venue rows that may lack a symbol."""
    try:
        return canonical_pair(a) == canonical_pair(b)
    except ValueError:
        return False
