"""Binance USDⓈ-M PERPETUAL futures OHLCV — a separate source, deliberately.

WHY THIS IS NOT A FLAG ON `BinanceSource`
GATE-008's roster is fixed by name: `BTCUSDT.P · ETHUSDT.P · TOTAL · USDT.D`, and
`gate_008_roster.py:38-42` is explicit that the first two are the PERPETUALS, "not
spot". Spot and perpetual are different markets with different prices, and A3
measures the divergence on this repo as large enough to create or erase the FVG an
entry depends on.

A boolean on the existing source would make "which market am I holding" a runtime
question answered by a parameter nobody re-reads. One host and one instrument family
per class means the question is answered by the type, and a spot bar cannot arrive
from here by any code path — `_BASES` and `_PATH` are module constants and there is
no argument that changes them.

WHAT MAKES THE IDENTITY HONEST
`BTCUSDT` and `BTCUSDT.P` differ by two characters and mean different markets, so
nothing here relies on anyone reading the suffix. Every fetch returns its venue and
instrument family alongside the bars — see `PanelIdentity` and `fetch_with_identity`.
The identity is **produced by whichever source actually ran**, never derived from the
symbol it was asked for. That is what makes the mutation in this module's tests
meaningful: aim this class at the spot host and the recorded identity must stop
claiming the perpetual, because a panel labelled `BTCUSDT.P` carrying spot data is
exactly what a substitution looks like from the inside — and GATE-008 would happily
PASS it.

RATE COST
Two extra series (BTC, ETH) on a second host, fetched once per closed bar of the
signal timeframe. At 1H that is 2 requests/hour; at 5M, 24/hour. Binance's USDⓈ-M
public klines endpoint is weight-limited well above that, and this source shares no
budget with the spot host because it is a different host.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
import pandas as pd

from app.core.logging import logger
from app.services.market_data.sources.base import (
    OHLCV_COLUMNS,
    MarketDataSource,
    empty_ohlcv,
)

#: USDⓈ-M futures. A DIFFERENT HOST from spot's api.binance.com, not a different path
#: on the same one — so a misconfiguration cannot silently return spot bars.
_BASES = ("https://fapi.binance.com",)
_PATH = "/fapi/v1/klines"

_INTERVAL: dict[str, str] = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1H": "1h", "4H": "4h", "D": "1d", "W": "1w",
}
_INTERVAL_MS: dict[str, int] = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1H": 3_600_000, "4H": 14_400_000, "D": 86_400_000, "W": 604_800_000,
}
_MAX_LIMIT = 1500  # USDⓈ-M allows 1500/request; spot allows 1000


@dataclass(frozen=True)
class PanelIdentity:
    """Which market a panel's bars actually came from.

    Carried on the read rather than inferred at the call site. `venue` is the host
    family that served the data and `instrument_family` says PERPETUAL or SPOT — the
    two facts a reader would otherwise have to reconstruct from a two-character
    suffix on a symbol string.

    `roster_name` is what GATE-008 calls this panel. Keeping it beside the other two
    is the point: it makes "the roster wanted BTCUSDT.P and this is what answered"
    a single object rather than an assumption spanning two files.
    """

    roster_name: str
    venue: str
    instrument_family: str
    symbol_requested: str

    def as_provenance(self) -> dict:
        return {
            "roster_name": self.roster_name,
            "venue": self.venue,
            "instrument_family": self.instrument_family,
            "symbol_requested": self.symbol_requested,
        }


def _to_ms(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


class BinancePerpetualSource(MarketDataSource):
    """USDⓈ-M perpetual klines. Cannot return a spot bar."""

    name = "binance_perp"

    #: What this source is, stated once. `fetch_with_identity` reports these rather
    #: than deriving them, so a source aimed elsewhere reports where it was aimed.
    INSTRUMENT_FAMILY = "PERPETUAL"

    def __init__(self, timeout: float = 20.0, bases: tuple[str, ...] = _BASES) -> None:
        # `bases` is injectable for tests ONLY. It is what the identity reports, so
        # a test that aims this source at the spot host gets an identity naming the
        # spot host — which is the mutation criterion 1 requires, and the reason the
        # identity is not a constant string.
        self._bases = bases
        self._client = httpx.Client(
            timeout=timeout, headers={"User-Agent": "tradingai/1.0"}
        )

    # ------------------------------------------------------------------
    @staticmethod
    def to_symbol(roster_name: str) -> str:
        """`BTCUSDT.P` -> `BTCUSDT`. The `.P` is the ROSTER's notation, not Binance's.

        Binance's USDⓈ-M endpoint names the perpetual `BTCUSDT` — the same string spot
        uses — because the market is identified by the HOST, not by the symbol. That
        is precisely why the identity has to be carried: the symbol alone cannot tell
        you which market answered.
        """
        s = roster_name.upper().strip()
        return s[:-2] if s.endswith(".P") else s

    def venue(self) -> str:
        """The host family actually configured, not the one intended."""
        return self._bases[0]

    def identity_for(self, roster_name: str) -> PanelIdentity:
        """What this source WOULD claim for `roster_name`, from its real configuration.

        Reports `SPOT` when aimed at a spot host: the identity follows the wire, so it
        cannot be used to launder spot data under a perpetual label.
        """
        host = self.venue()
        family = self.INSTRUMENT_FAMILY if "fapi." in host else "SPOT"
        return PanelIdentity(
            roster_name=roster_name,
            venue=host,
            instrument_family=family,
            symbol_requested=self.to_symbol(roster_name),
        )

    # ------------------------------------------------------------------
    def fetch_ohlcv(
        self, symbol: str, timeframe: str, start: datetime, end: datetime,
        drop_partial: bool = True,
    ) -> pd.DataFrame:
        """Closed bars in ``[start, end)``.

        ``drop_partial`` defaults **True** and removes the still-forming bar, matching
        `DominanceSource`. This is not tidiness: a 1H bar stamped 22:00 covers
        [22:00, 23:00) and is not knowable until 23:00, so including it feeds the
        present into a series read as closed history — the lookahead class this repo
        has three regression tests for on the entry path.

        It mattered here because `BTCUSDT.P` is the **MAIN** panel of GATE-008's
        layout: its order flow anchors the alignment, and the grade derived from it
        keys the risk matrix. The dominance panels dropped their forming bar while
        these did not, so the four panels ran **one bar out of step** — and every
        check passed, because `alignment_tf` compares the timeframe LABEL and nothing
        compares the last bar.
        """
        if timeframe not in _INTERVAL:
            raise ValueError(f"Unsupported timeframe {timeframe!r}")
        sym = self.to_symbol(symbol)
        interval, step = _INTERVAL[timeframe], _INTERVAL_MS[timeframe]
        start_ms, end_ms = _to_ms(start), _to_ms(end)

        rows: list[tuple] = []
        cursor = start_ms
        while cursor < end_ms:
            batch = self._get({
                "symbol": sym, "interval": interval,
                "startTime": cursor, "endTime": end_ms, "limit": _MAX_LIMIT,
            })
            if not batch:
                break
            for k in batch:
                rows.append((int(k[0]), float(k[1]), float(k[2]),
                             float(k[3]), float(k[4]), float(k[5])))
            cursor = int(batch[-1][0]) + step
            if len(batch) < _MAX_LIMIT:
                break

        if not rows:
            return empty_ohlcv()

        df = pd.DataFrame(rows, columns=["time", *OHLCV_COLUMNS])
        df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
        df = df.drop_duplicates("time").set_index("time").sort_index()
        df = df[df.index < pd.Timestamp(end_ms, unit="ms", tz="UTC")]

        if drop_partial and len(df):
            # A bar OPENS at its label and CLOSES one interval later. The window filter
            # above keeps any bar that opened before `end`, which is precisely the
            # still-forming one — so the drop has to be on the CLOSE time, not the open.
            closes_at = df.index[-1] + pd.Timedelta(milliseconds=step)
            if closes_at > pd.Timestamp(end_ms, unit="ms", tz="UTC"):
                df = df.iloc[:-1]
        return df

    def fetch_with_identity(
        self, roster_name: str, timeframe: str, start: datetime, end: datetime,
        drop_partial: bool = True,
    ) -> tuple[pd.DataFrame, PanelIdentity]:
        """Bars plus the identity of whatever actually served them.

        The pair is the unit callers should use. Returning the frame alone would let a
        caller record `BTCUSDT.P` beside data this source never claimed was perpetual.
        """
        return (self.fetch_ohlcv(roster_name, timeframe, start, end, drop_partial),
                self.identity_for(roster_name))

    def _get(self, params: dict) -> list:
        """UNREACHABLE MEANS EMPTY, NEVER A FALLBACK AND NEVER A RAISE.

        An empty list becomes an absent panel, which `LayoutReadability` reports as
        `GATE-008 FAIL` naming the missing roster entry. That is the correct failure:
        a stale bar would be silently wrong, a spot fallback would be the substitution
        this whole module exists to prevent, and an exception could reach the trading
        path through the shadow — which `shadow.py` states it must never do.
        """
        last_exc: Exception | None = None
        for base in self._bases:
            try:
                resp = self._client.get(base + _PATH, params=params)
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:  # noqa: BLE001 - try the next mirror, then give up
                last_exc = exc
                continue
        logger.warning(
            f"perpetual klines fetch failed for {params.get('symbol')}: {last_exc}"
        )
        return []

    def close(self) -> None:
        self._client.close()
