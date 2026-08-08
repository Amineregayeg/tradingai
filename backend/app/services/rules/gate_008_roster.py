"""GATE-008 — the four-panel layout, and GATE-007's same-timeframe requirement (M4).

    For BTC trading the layout is exactly four panels — main: BTC · positive: ETH and TOTAL ·
    negative: USDT.D. Expected order flow for a BTC long: BTC, ETH, TOTAL bullish and USDT.D
    bearish; for a BTC short, the mirror. There is no panel called "total dominance".

WHY THE ROSTER IS A RULE AND NOT CONFIGURATION
It supplies the `expected_sign` that GATE-048 multiplies against observed order flow, which
produces the per-panel agreement that GATE-002 counts, which produces the disturbance grade
that keys the risk matrix. Get the roster wrong — one asset in the wrong role, or a fifth
panel added — and every position size downstream is wrong. It is also what GATE-003 freezes
the layout size to: with exactly three correlates, "2 or more disturbed → HEAVY" means 2-of-3
and nothing else, which is the only reading the corpus supports.

USDT.D IS NEGATIVE AND THAT IS THE POINT
A falling USDT.D is what a BTC long *requires*. Any code that scores panels by raw direction
counts that as bearish and therefore as disagreement — the inversion GATE-048 exists to
prevent. The role signs live here so there is exactly one place that knows USDT.D is negative.

ALTCOINS ARE REFUSED, NOT APPROXIMATED
"we can not rely on any kind of magic alignments when we trade Altcoins" (066), and the
registry notes GATE-001/002 therefore have no defined behaviour for them. So `for_instrument`
raises rather than returning a best-effort roster: an altcoin layout would produce a
disturbance grade the doctrine does not define, and that grade would silently key a real
position size.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.services.rules.base import RuleImplementation

Role = Literal["MAIN", "POSITIVE", "NEGATIVE"]
Direction = Literal["LONG", "SHORT"]
Flow = Literal["BULLISH", "BEARISH", "NEUTRAL"]

#: GATE-008 `values`, verbatim. Canonical tickers — BTCUSDT.P and ETHUSDT.P are the Binance
#: PERPETUALS, not spot, and TOTAL / USDT.D are CryptoCap indices rather than instruments.
MAIN = "BTCUSDT.P"
POSITIVE = ("ETHUSDT.P", "TOTAL")
NEGATIVE = ("USDT.D",)
PANEL_COUNT = 4


@dataclass(frozen=True)
class Panel:
    """One panel of the layout, with the sign its role implies."""

    asset: str
    role: Role

    @property
    def role_sign(self) -> int:
        """+1 for the main asset and positive correlates, −1 for negative ones."""
        return -1 if self.role == "NEGATIVE" else 1

    def expected_flow(self, direction: Direction) -> Flow:
        """What this panel should be doing for a setup in `direction`."""
        setup_sign = 1 if direction == "LONG" else -1
        return "BULLISH" if self.role_sign * setup_sign > 0 else "BEARISH"


class LayoutRoster(RuleImplementation):
    """GATE-008: the roster, fixed by name. Also satisfies GRADE-012."""

    RULE_ID = "GATE-008"

    PANELS: tuple[Panel, ...] = (
        Panel(MAIN, "MAIN"),
        Panel(POSITIVE[0], "POSITIVE"),
        Panel(POSITIVE[1], "POSITIVE"),
        Panel(NEGATIVE[0], "NEGATIVE"),
    )

    #: Names the corpus explicitly denies exist. Caught by name so a typo cannot invent a
    #: panel: "There is no panel called 'total dominance'."
    NOT_A_PANEL = ("TOTAL DOMINANCE", "TOTAL.D", "BTC.D")

    @classmethod
    def for_instrument(cls, instrument: str) -> tuple[Panel, ...]:
        """The layout for `instrument`, or a refusal.

        Only BTC has a ruled roster. Everything else raises — see the module docstring.
        """
        normalised = instrument.upper().replace("/", "").replace("USD", "").strip()
        if normalised.startswith("BTC") or instrument.upper() in (MAIN, "BTC"):
            return cls.PANELS
        raise ValueError(
            f"{instrument!r} has no ruled layout. The roster is fixed for BTC only, and "
            "the corpus states altcoins cannot be magic-aligned at all — so GATE-001 and "
            "GATE-002 have no defined behaviour here and no risk cell may be looked up."
        )

    @classmethod
    def correlates(cls) -> tuple[Panel, ...]:
        """The three non-main panels — the denominator GATE-003 freezes."""
        return tuple(p for p in cls.PANELS if p.role != "MAIN")

    @classmethod
    def expected_signs(cls, direction: Direction) -> dict[str, Flow]:
        """asset -> the order flow the roster expects for a setup in `direction`."""
        return {p.asset: p.expected_flow(direction) for p in cls.PANELS}

    @classmethod
    def layout_size(cls) -> int:
        return len(cls.PANELS)


class AlignmentTimeframe(RuleImplementation):
    """GATE-007: the alignment TF must BE the execution TF.

        "All assets must be checked on the same timeframe when confirming the entry."

    The registry is careful about which part is hard: the particular member of the
    {30M, 15M, 5M} set is hedged three times in the source, but the SAME-timeframe
    requirement is not hedged at all. So this checks equality and says nothing about which
    timeframe was chosen — that is GATE-017/018's business.
    """

    RULE_ID = "GATE-007"

    @staticmethod
    def check(alignment_tf: str, signal_tf: str) -> tuple[bool, str]:
        if alignment_tf == signal_tf:
            return True, f"alignment and execution both on {signal_tf}"
        return False, (
            f"alignment was read on {alignment_tf} but the signal is on {signal_tf} — a "
            "confirmation assembled from mixed timeframes is a violation"
        )

    @staticmethod
    def check_all(reads: Any, signal_tf: str) -> tuple[bool, str]:
        """Every panel on one timeframe, and that timeframe the execution one."""
        tfs = sorted({r.tf for r in reads})
        if len(tfs) > 1:
            return False, (
                f"panels were read on {len(tfs)} different timeframes ({', '.join(tfs)}) — "
                "the layout must be confirmed on a single timeframe"
            )
        if not tfs:
            return False, "no panel reads supplied, so no alignment timeframe exists"
        return AlignmentTimeframe.check(tfs[0], signal_tf)
