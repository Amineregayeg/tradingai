"""The perpetual source cannot launder spot data under a `.P` label.

WHY THIS IS ABOUT IDENTITY AND NOT ABOUT A URL
The obvious test — "point the perpetual source at the spot host and assert the URL
changed" — asserts that a constant is a constant. It would pass against a source that
returns spot bars while every record still says PERPETUAL, which is exactly the failure
worth guarding: **a panel labelled `BTCUSDT.P` carrying spot data**. GATE-008 would
`PASS` that layout, GATE-002 would grade it, and the grade keys the risk matrix.

The trap is real rather than theoretical, because **Binance names the perpetual
`BTCUSDT` — the same string spot uses.** The market is identified by the HOST, not by
the symbol, so a symbol-derived identity is wrong by construction and a
suffix-derived one is wishful. `identity_for` reads the source's actual configuration,
so aiming it elsewhere makes it say so.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.services.market_data.sources.binance_perp import (
    BinancePerpetualSource,
    PanelIdentity,
)

T0 = datetime(2026, 8, 1, tzinfo=timezone.utc)
SPOT_HOST = "https://api.binance.com"
PERP_HOST = "https://fapi.binance.com"


def test_the_roster_suffix_is_ours_and_binance_does_not_use_it():
    """`BTCUSDT.P` is GATE-008's notation. The wire symbol is `BTCUSDT`."""
    assert BinancePerpetualSource.to_symbol("BTCUSDT.P") == "BTCUSDT"
    assert BinancePerpetualSource.to_symbol("ETHUSDT.P") == "ETHUSDT"
    # Idempotent, so a caller that already stripped it is not punished.
    assert BinancePerpetualSource.to_symbol("BTCUSDT") == "BTCUSDT"


def test_identity_names_the_perpetual_when_aimed_at_the_perpetual_host():
    src = BinancePerpetualSource()
    ident = src.identity_for("BTCUSDT.P")
    assert isinstance(ident, PanelIdentity)
    assert ident.instrument_family == "PERPETUAL"
    assert "fapi." in ident.venue
    assert ident.roster_name == "BTCUSDT.P"
    assert ident.symbol_requested == "BTCUSDT"


# ---------------------------------------------------------------------------
# Criterion 1's MUTATION — bites on identity, not on a host string
# ---------------------------------------------------------------------------

def test_aiming_the_perpetual_source_at_spot_stops_it_claiming_the_perpetual():
    """THE MUTATION. Substitute the market and the record must stop claiming otherwise.

    This is the failure a substitution actually looks like from the inside: the roster
    name is still `BTCUSDT.P`, the requested symbol is still `BTCUSDT` — because those
    are identical across the two markets — and the ONLY thing that can betray it is the
    recorded instrument family.

    Asserting `venue == SPOT_HOST` here would also go red and would prove only that the
    constructor stored its argument. The assertion that matters is
    `instrument_family != "PERPETUAL"`, because that is the field a downstream reader
    trusts when deciding whether GATE-008's roster was really satisfied.
    """
    aimed_at_spot = BinancePerpetualSource(bases=(SPOT_HOST,))
    ident = aimed_at_spot.identity_for("BTCUSDT.P")

    assert ident.instrument_family == "SPOT", (
        "a source serving spot bars still described them as PERPETUAL — this is exactly "
        "the substitution GATE-008 would PASS, with the grade keying the risk matrix"
    )
    assert ident.instrument_family != "PERPETUAL"
    # The two fields that CANNOT distinguish the markets, pinned so nobody later
    # decides one of them is sufficient.
    assert ident.roster_name == "BTCUSDT.P"
    assert ident.symbol_requested == "BTCUSDT"


def test_provenance_is_carried_not_inferred(monkeypatch):
    """Criterion 2: a record states which venue and family produced each panel."""
    src = BinancePerpetualSource()
    prov = src.identity_for("ETHUSDT.P").as_provenance()
    assert set(prov) == {"roster_name", "venue", "instrument_family", "symbol_requested"}
    assert prov["instrument_family"] == "PERPETUAL"
    assert prov["roster_name"] == "ETHUSDT.P"
    # Two characters separate the roster names of two different markets; the provenance
    # must not require anyone to notice them.
    assert prov["symbol_requested"] == "ETHUSDT"


def test_fetch_returns_bars_and_identity_together(monkeypatch):
    """The pair is the unit. A frame alone lets a caller label it whatever they expect."""
    src = BinancePerpetualSource()
    idx = pd.DatetimeIndex([T0 + timedelta(hours=i) for i in range(3)], tz="UTC")
    frame = pd.DataFrame(
        {"open": [1.0] * 3, "high": [2.0] * 3, "low": [0.5] * 3,
         "close": [1.5] * 3, "volume": [10.0] * 3}, index=idx)
    monkeypatch.setattr(src, "fetch_ohlcv", lambda *a, **k: frame)

    bars, ident = src.fetch_with_identity("BTCUSDT.P", "1H", T0, T0 + timedelta(days=1))
    assert len(bars) == 3
    assert ident.instrument_family == "PERPETUAL"


# ---------------------------------------------------------------------------
# Criterion 6 — failure behaviour
# ---------------------------------------------------------------------------

def test_an_unreachable_host_yields_no_bars_rather_than_stale_or_spot(monkeypatch):
    """GATE-008 FAIL naming the panel — not a stale bar, not a fallback, not a raise.

    A shadow that can break the engine is worse than no shadow (`shadow.py`), so this
    must not propagate. And a spot fallback would be the substitution the whole module
    exists to prevent, arriving as an availability convenience.
    """
    src = BinancePerpetualSource()

    def boom(*a, **k):
        raise ConnectionError("fapi unreachable")

    monkeypatch.setattr(src._client, "get", boom)

    out = src.fetch_ohlcv("BTCUSDT.P", "1H", T0, T0 + timedelta(days=1))
    assert out.empty, "an unreachable host must produce no bars at all"
    assert list(out.columns) == ["open", "high", "low", "close", "volume"]


def test_an_unsupported_timeframe_raises_rather_than_guessing():
    src = BinancePerpetualSource()
    with pytest.raises(ValueError):
        src.fetch_ohlcv("BTCUSDT.P", "7m", T0, T0 + timedelta(days=1))
