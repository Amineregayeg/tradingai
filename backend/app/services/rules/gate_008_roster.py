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


#: Minimum raw observations behind a synthesised correlate bar before its high and low are
#: treated as price action rather than sampling luck.
#:
#: AN ENGINE CHOICE, NOT DOCTRINE — the corpus fixes no number, so it is stamped as a
#: declared parameter like any other. NOT a GATE-005 violation: that rule bans candle counts
#: and time delays as inputs to the DISTURBANCE decision, and this is a precondition on
#: whether a bar exists to read at all. The two are easy to confuse and worth separating
#: out loud.
#:
#: At the collector's present 60-second sampling this admits 30M (30 samples) and rejects
#: 5M (5). That is the intended behaviour and it is why the guard lands before the sampling
#: rate changes, not after (KNOWN_ISSUES B11).
MIN_SAMPLES_PER_SYNTHETIC_BAR = 20


class LayoutReadability:
    """Can this layout be read at all? Produces the evaluations GATE-036 folds.

    Deliberately NOT a `RuleImplementation`: it invents no rule of its own. Each problem it
    finds is reported as a failure of the rule that actually requires the thing — GATE-008
    when the roster cannot be resolved, GATE-007 when the alignment is not available at the
    execution timeframe — so `deciding_rule_id` always names a real registry rule rather than
    a local invention.
    """

    @staticmethod
    def evaluate(
        reads: Any,
        *,
        signal_tf: str,
        instrument: str = "BTC",
        min_samples: int = MIN_SAMPLES_PER_SYNTHETIC_BAR,
    ) -> tuple[list[Any], list[str]]:
        """Return (rule evaluations in order, human-readable causes)."""
        from app.services.telemetry.records import RuleEvaluation

        evaluations: list[Any] = []
        causes: list[str] = []

        # -- GATE-008: does the roster resolve, and is every panel present? --------------
        try:
            panels = LayoutRoster.for_instrument(instrument)
            present = {getattr(r, "asset", None) for r in reads}
            missing = [p.asset for p in panels if p.asset not in present]
            roster_ok = not missing
            if missing:
                causes.append(f"no read for {', '.join(missing)}")
        except ValueError as exc:
            panels, missing, roster_ok = (), [], False
            causes.append(str(exc).split(".")[0])

        evaluations.append(RuleEvaluation(
            rule_id="GATE-008",
            verdict="PASS" if roster_ok else "FAIL",
            values={"instrument": instrument, "panels_missing": list(missing),
                    "layout_size": len(panels)},
            value_provenance={
                "instrument": {"source": "RECORD_FIELD", "field": "instrument"},
                "panels_missing": {"source": "DERIVED", "expression": "roster - reads"},
                "layout_size": {"source": "REGISTRY_CONSTANT", "field": "GATE-008.values.panels"},
            },
        ))

        # -- GATE-007: one timeframe, and it is the execution one -----------------------
        tf_ok, tf_why = AlignmentTimeframe.check_all(reads, signal_tf)
        if not tf_ok:
            causes.append(tf_why)

        # -- GATE-007 again: are the synthesised panels thick enough to carry structure? -
        thin = [
            (getattr(r, "asset", "?"), r.bar_sample_count)
            for r in reads
            if getattr(r, "bar_sample_count", None) is not None
            and r.bar_sample_count < min_samples
        ]
        if thin:
            tf_ok = False
            causes.append(
                "correlate bars too thin at "
                f"{signal_tf}: " + ", ".join(f"{a} has {n} samples" for a, n in thin)
                + f" (minimum {min_samples})"
            )

        evaluations.append(RuleEvaluation(
            rule_id="GATE-007",
            verdict="PASS" if tf_ok else "FAIL",
            values={"alignment_tf": sorted({getattr(r, "tf", "?") for r in reads}),
                    "signal_tf": signal_tf,
                    "thin_panels": [a for a, _ in thin],
                    "min_samples_per_synthetic_bar": min_samples},
            value_provenance={
                "alignment_tf": {"source": "CORRELATE_FIELD", "field": "tf"},
                "signal_tf": {"source": "RECORD_FIELD", "field": "signal_tf"},
                "thin_panels": {"source": "CORRELATE_FIELD", "field": "bar_sample_count"},
                "min_samples_per_synthetic_bar": {
                    "source": "DECLARED_PARAMETER", "field": "min_samples_per_synthetic_bar",
                },
            },
            declared_parameter_used="min_samples_per_synthetic_bar",
        ))
        return evaluations, causes

    @staticmethod
    def readable(reads: Any, *, signal_tf: str, instrument: str = "BTC",
                 min_samples: int = MIN_SAMPLES_PER_SYNTHETIC_BAR) -> bool:
        evaluations, _ = LayoutReadability.evaluate(
            reads, signal_tf=signal_tf, instrument=instrument, min_samples=min_samples
        )
        return all(e.verdict == "PASS" for e in evaluations)
