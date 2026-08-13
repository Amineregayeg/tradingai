"""The correlate layout is read from real panels — and can tell when one is missing.

WHY THE FIRST TEST IS THE IMPORTANT ONE
In production this engine reads two of GATE-008's four panels: TOTAL and USDT.D come
from our own collector, and BTCUSDT.P / ETHUSDT.P are Binance PERPETUALS which nothing
in this repo can fetch. So `GATE-008 FAIL, panels_missing: [BTCUSDT.P, ETHUSDT.P]` is
the *steady state*.

    four panels present  -> PASS, and a real four-panel disturbance grade
    production reality   -> FAIL naming exactly the two that are absent

**What each of those does and does not prove — stated because an earlier draft of this
docstring overclaimed it.** The first test supplies `reads` from a fixture, and `reads`
is the very artifact the wiring produces. So it is evidence about the *evaluator* —
that four panels grade correctly — and it says nothing about whether a fetch works. No
fixture test can prove a real read succeeded, because the fixture exists to avoid
needing one. It is kept because it is the regression test that will matter when the
perpetual feeds land.

**What actually distinguishes working plumbing from none is the COUNT, and it is free.**
`gate_008_roster.py:189` derives `missing` by subtracting the reads from the roster:

    read nothing            -> panels_missing has ALL FOUR
    read the two we have    -> panels_missing has EXACTLY TWO

And what separates a real read from one returning empty or garbage series is GATE-007,
which already emits the evidence: a non-empty `alignment_tf`, and `thin_panels` empty
with sample counts at or above the minimum. A list of absences says nothing about the
presences; those two fields are the presences.

The fixture standing in for the perpetual series is legitimate *here* precisely because
it is a test and never reaches a record — which is the whole difference from
substituting spot for perpetual in production, which this task refused to do.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.services.live import shadow
from app.services.rules.gate_002_disturbance import CorrelateRead, DisturbanceClassifier
from app.services.rules.gate_008_roster import LayoutRoster, Panel
from app.services.rules.prim_001_swings import Bar

T0 = datetime(2026, 8, 1, tzinfo=timezone.utc)
TF = "1H"


def _ramp(n: int = 60, *, rising: bool = True) -> list[Bar]:
    """A clean trending series — enough structure for a swing/break read."""
    out = []
    for i in range(n):
        base = 100.0 + (i if rising else -i)
        out.append(Bar(time=T0 + timedelta(hours=i), open=base, high=base + 1.0,
                       low=base - 1.0, close=base + (0.5 if rising else -0.5)))
    return out


class _FakeDominance:
    """Serves the two panels our collector really provides."""

    def __init__(self, available=("TOTAL", "USDT.D"), samples: int = 360):
        self.available = set(available)
        self.samples = samples

    def fetch_ohlcv_with_samples(self, symbol, timeframe, start, end, **kw):
        if symbol not in self.available:
            return pd.DataFrame()
        n = 60
        idx = pd.DatetimeIndex([T0 + timedelta(hours=i) for i in range(n)], tz="UTC")
        base = [100.0 + i for i in range(n)]
        return pd.DataFrame(
            {"open": base, "high": [b + 1 for b in base], "low": [b - 1 for b in base],
             "close": [b + 0.5 for b in base], "volume": [0.0] * n,
             "samples": [self.samples] * n},
            index=idx,
        )


def _verdicts(evaluations) -> dict[str, str]:
    return {e.rule_id: e.verdict for e in evaluations}


def _values(evaluations, rule_id) -> dict:
    return next(e.values for e in evaluations if e.rule_id == rule_id)


# ---------------------------------------------------------------------------
# 4a — the discriminator. Without this, a dead wire looks exactly like production.
# ---------------------------------------------------------------------------

def test_all_four_panels_present_makes_gate_008_pass_and_grades_the_layout():
    """With the perpetual series supplied by a fixture, the wiring produces a real grade.

    This is the only test that can distinguish working plumbing from none. If it fails
    while the production test below still passes, the wiring is decoration.
    """
    perps = {"BTCUSDT.P": _ramp(), "ETHUSDT.P": _ramp()}
    evaluations, _causes = shadow._evaluate_layout(
        _ramp(), signal_tf=TF, panel_source=_FakeDominance(), extra_panels=perps
    )
    verdicts = _verdicts(evaluations)

    assert verdicts["GATE-008"] == "PASS", _values(evaluations, "GATE-008")
    assert verdicts["GATE-007"] == "PASS", _values(evaluations, "GATE-007")
    assert _values(evaluations, "GATE-008")["panels_missing"] == []
    assert _values(evaluations, "GATE-008")["layout_size"] == 4

    # GATE-002 produced an actual grade rather than a refusal.
    assert verdicts["GATE-002"] == "PASS"
    gate_002 = _values(evaluations, "GATE-002")
    assert "grade" in gate_002 and gate_002["grade"]
    assert sorted(gate_002["panels_read"]) == ["BTCUSDT.P", "ETHUSDT.P", "TOTAL", "USDT.D"]


def test_production_reality_fails_naming_exactly_the_two_perpetual_panels():
    """Two of four. The verdict must name what is absent, not merely refuse."""
    evaluations, _ = shadow._evaluate_layout(
        _ramp(), signal_tf=TF, panel_source=_FakeDominance()
    )
    verdicts = _verdicts(evaluations)

    assert verdicts["GATE-008"] == "FAIL"
    assert sorted(_values(evaluations, "GATE-008")["panels_missing"]) == [
        "BTCUSDT.P", "ETHUSDT.P"
    ]
    # GATE-002 declines for the TRUE reason, and never silently passes (C-04).
    assert verdicts["GATE-002"] == "NOT_APPLICABLE"
    why = _values(evaluations, "GATE-002")["not_evaluated_because"]
    assert "BTCUSDT.P" in why and "ETHUSDT.P" in why
    assert "CryptoCap" not in why, "the old reason was false and must not return"


# ---------------------------------------------------------------------------
# 4b — mutate a panel we DO have
# ---------------------------------------------------------------------------

def test_dropping_usdt_d_is_noticed_and_named():
    """A wiring that cannot notice a missing panel is decoration."""
    perps = {"BTCUSDT.P": _ramp(), "ETHUSDT.P": _ramp()}
    evaluations, _ = shadow._evaluate_layout(
        _ramp(), signal_tf=TF,
        panel_source=_FakeDominance(available=("TOTAL",)),  # USDT.D withdrawn
        extra_panels=perps,
    )
    assert _verdicts(evaluations)["GATE-008"] == "FAIL"
    assert _values(evaluations, "GATE-008")["panels_missing"] == ["USDT.D"]
    assert _verdicts(evaluations)["GATE-002"] == "NOT_APPLICABLE"


def test_a_thin_panel_is_refused_rather_than_graded():
    """B16 / GATE-007: below MIN_SAMPLES_PER_SYNTHETIC_BAR the bar is sampling luck."""
    perps = {"BTCUSDT.P": _ramp(), "ETHUSDT.P": _ramp()}
    evaluations, _ = shadow._evaluate_layout(
        _ramp(), signal_tf="1m",
        panel_source=_FakeDominance(samples=6),  # 1m at 10s polling = 6 samples
        extra_panels=perps,
    )
    assert _verdicts(evaluations)["GATE-007"] == "FAIL"
    assert _values(evaluations, "GATE-007")["thin_panels"]


# ---------------------------------------------------------------------------
# 5 — USDT.D's negative role sign, asserted at the GRADE
# ---------------------------------------------------------------------------

def _reads_for_a_clean_btc_long() -> list[CorrelateRead]:
    """BTC/ETH/TOTAL bullish, USDT.D falling — textbook agreement for a LONG."""
    return [
        CorrelateRead(asset="BTCUSDT.P", tf=TF, observed_order_flow="BULLISH"),
        CorrelateRead(asset="ETHUSDT.P", tf=TF, observed_order_flow="BULLISH"),
        CorrelateRead(asset="TOTAL", tf=TF, observed_order_flow="BULLISH"),
        CorrelateRead(asset="USDT.D", tf=TF, observed_order_flow="BEARISH"),
    ]


def test_falling_usdt_d_is_agreement_for_a_long_not_disturbance():
    """The grade, not the constant. A falling USDT.D is what a BTC long REQUIRES.

    Asserting `role_sign == -1` would also go red under an inversion and would prove
    only that a constant is a constant. This asserts the number that keys the risk
    matrix.
    """
    grade = DisturbanceClassifier.classify(
        _reads_for_a_clean_btc_long(), direction="LONG",
        instrument="BTC", main_asset_counts=False,
    )
    assert grade.grade == "NONE", (
        f"a falling USDT.D was counted as disagreement: {grade}"
    )


def test_scoring_usdt_d_by_raw_direction_corrupts_the_grade(monkeypatch):
    """THE MUTATION. Score USDT.D by raw direction and the grade must change.

    This is the inversion `gate_008_roster.py:15-18` warns about in capitals. With the
    sign flipped, the identical market — BTC/ETH/TOTAL bullish, USDT.D falling — grades
    as disturbed. One panel wrongly disturbed is LIGHT; add a genuinely disturbed second
    panel and the same inversion reaches HEAVY, which GATE-001 turns into a hard skip.
    So the inversion can both invent a blocked trade and, in mirror, permit one.
    """
    clean = DisturbanceClassifier.classify(
        _reads_for_a_clean_btc_long(), direction="LONG",
        instrument="BTC", main_asset_counts=False,
    )
    assert clean.grade == "NONE"

    # Flip USDT.D from NEGATIVE to POSITIVE — i.e. score it by raw direction.
    inverted = tuple(
        Panel(p.asset, "POSITIVE" if p.role == "NEGATIVE" else p.role)
        for p in LayoutRoster.PANELS
    )
    monkeypatch.setattr(LayoutRoster, "PANELS", inverted)

    corrupted = DisturbanceClassifier.classify(
        _reads_for_a_clean_btc_long(), direction="LONG",
        instrument="BTC", main_asset_counts=False,
    )
    assert corrupted.grade != "NONE", (
        "the inversion produced no change in the grade, so nothing defends against it"
    )
    assert corrupted.grade == "LIGHT", f"expected LIGHT under inversion, got {corrupted.grade}"
