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


class _FakePerp:
    """Stands in for the network, not for the source's logic.

    `_evaluate_layout` still calls the real identity check, so a fake claiming SPOT is
    refused exactly as a misaimed real source would be. That is the difference between
    this and 4a's `extra_panels`: 4a bypassed the wiring, this exercises it.
    """

    def __init__(self, family="PERPETUAL", empty=False):
        self.family, self.empty = family, empty

    def fetch_with_identity(self, roster_name, timeframe, start, end):
        from app.services.market_data.sources.binance_perp import PanelIdentity
        ident = PanelIdentity(roster_name=roster_name,
                              venue="https://fapi.binance.com",
                              instrument_family=self.family,
                              symbol_requested=roster_name.removesuffix(".P"))
        if self.empty:
            return pd.DataFrame(), ident
        n = 60
        idx = pd.DatetimeIndex([T0 + timedelta(hours=i) for i in range(n)], tz="UTC")
        base = [100.0 + i for i in range(n)]
        return pd.DataFrame({"open": base, "high": [b + 1 for b in base],
                             "low": [b - 1 for b in base], "close": [b + 0.5 for b in base],
                             "volume": [0.0] * n}, index=idx), ident


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
    evaluations, _causes, _grade = shadow._evaluate_layout(
        _ramp(), signal_tf=TF, panel_source=_FakeDominance(), extra_panels=perps,
        perp_source=_FakePerp(empty=True),
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


def test_with_no_perpetual_feed_the_two_perpetual_panels_are_named():
    """Two of four. The verdict must name what is absent, not merely refuse.

    Until T-0008 this was production's steady state and the test relied on the default
    perpetual source being unavailable. It no longer is — `_read_panels` now builds a
    real `BinancePerpetualSource`, so leaving it to the default made this test reach
    `fapi.binance.com` and pass four panels. **A unit test that silently acquires a
    network dependency is a unit test that will fail on a plane**, so the unavailable
    feed is now injected explicitly rather than assumed.
    """
    evaluations, _, _grade = shadow._evaluate_layout(
        _ramp(), signal_tf=TF, panel_source=_FakeDominance(),
        perp_source=_FakePerp(empty=True),
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
    evaluations, _, _grade = shadow._evaluate_layout(
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
    evaluations, _, _grade = shadow._evaluate_layout(
        _ramp(), signal_tf="1m",
        panel_source=_FakeDominance(samples=6),  # 1m at 10s polling = 6 samples
        extra_panels=perps,
        perp_source=_FakePerp(empty=True),
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


# ---------------------------------------------------------------------------
# The coupling B27's fix depends on, pinned rather than described
# ---------------------------------------------------------------------------

class _RecordingDominance(_FakeDominance):
    """Remembers the kwargs it was called with."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.calls: list[dict] = []

    def fetch_ohlcv_with_samples(self, symbol, timeframe, start, end, **kw):
        self.calls.append({"symbol": symbol, "timeframe": timeframe, **kw})
        return super().fetch_ohlcv_with_samples(symbol, timeframe, start, end, **kw)


def test_panels_are_read_with_the_forming_bar_dropped():
    """`sample_counts` takes the LAST bar, which is only the decision bar while
    `drop_partial=True`.

    B27 replaced a window-minimum with `iloc[-1]`. That is correct exactly as long as
    the forming bar has already been removed — a caller passing `drop_partial=False`
    would make "the decision bar" a partial one, thin by construction, which is the
    bug B27 fixed arriving one caller away. The coupling is implicit in the code, so
    it is pinned here instead of described in a comment.
    """
    src = _RecordingDominance()
    shadow._evaluate_layout(_ramp(), signal_tf=TF, panel_source=src,
        perp_source=_FakePerp(empty=True),
    )

    assert src.calls, "no panel was read at all"
    for call in src.calls:
        assert call.get("drop_partial") is True, (
            f"{call['symbol']} was read with drop_partial={call.get('drop_partial')!r}; "
            "the last bar is then still forming and `iloc[-1]` is not the decision bar"
        )


# ---------------------------------------------------------------------------
# T-0008 — the four-panel read through the REAL wiring, not a fixture
# ---------------------------------------------------------------------------

def test_four_panels_through_the_real_wiring_pass_gate_008():
    """The criterion the whole programme has walked toward, via the wiring itself."""
    evaluations, _, _grade = shadow._evaluate_layout(
        _ramp(), signal_tf=TF,
        panel_source=_FakeDominance(), perp_source=_FakePerp(),
    )
    v = _verdicts(evaluations)
    assert v["GATE-008"] == "PASS", _values(evaluations, "GATE-008")
    assert _values(evaluations, "GATE-008")["panels_missing"] == []
    assert v["GATE-007"] == "PASS"
    assert v["GATE-002"] == "PASS"
    assert sorted(_values(evaluations, "GATE-002")["panels_read"]) == [
        "BTCUSDT.P", "ETHUSDT.P", "TOTAL", "USDT.D"]


def test_a_perpetual_source_serving_spot_is_refused_not_substituted():
    """RUNTIME half of the identity mutation. A wrong-market panel is absent, not used."""
    evaluations, causes, _grade = shadow._evaluate_layout(
        _ramp(), signal_tf=TF,
        panel_source=_FakeDominance(), perp_source=_FakePerp(family="SPOT"),
    )
    assert _verdicts(evaluations)["GATE-008"] == "FAIL"
    assert sorted(_values(evaluations, "GATE-008")["panels_missing"]) == [
        "BTCUSDT.P", "ETHUSDT.P"]
    assert any("not\nPERPETUAL" in c or "not PERPETUAL" in c for c in causes), causes


def test_unreachable_perpetual_host_fails_naming_the_panels():
    """Criterion 6: absent, not stale and not a spot fallback."""
    evaluations, _, _grade = shadow._evaluate_layout(
        _ramp(), signal_tf=TF,
        panel_source=_FakeDominance(), perp_source=_FakePerp(empty=True),
    )
    assert _verdicts(evaluations)["GATE-008"] == "FAIL"
    assert sorted(_values(evaluations, "GATE-008")["panels_missing"]) == [
        "BTCUSDT.P", "ETHUSDT.P"]


# ---------------------------------------------------------------------------
# The correlates BLOCK must report what was graded, not a literal
# ---------------------------------------------------------------------------

def test_the_correlates_block_reports_the_measured_grade_not_a_constant():
    """A hardcoded `NONE` beside a passing GATE-002 reads as measured.

    This block was the literal {0, 0, "NONE", []} while the layout could not be read,
    which was honest then: every neighbouring field said "not measured". Wiring the
    panels removed those safeguards without touching the literal, so a HEAVY layout —
    which GATE-001 turns into a hard skip — would have been recorded as NONE.

    `layout_size` is the discriminator: 0 means never graded, whatever the grade says.
    """
    shadow_grade = DisturbanceClassifier.classify(
        _reads_for_a_clean_btc_long(), direction="LONG",
        instrument="BTC", main_asset_counts=False,
    )
    graded = shadow._correlates_block(shadow_grade)
    assert graded["layout_size"] == 4, graded
    assert graded["disturbance_grade"] == shadow_grade.grade
    assert graded["states"], "a graded layout must carry its per-panel states"

    ungraded = shadow._correlates_block(None)
    assert ungraded["layout_size"] == 0
    assert ungraded["states"] == []


def test_the_four_panel_pass_can_be_made_to_fail_by_dropping_a_panel():
    """Review's rejection condition: a PASS that cannot be made to FAIL proves nothing.

    `test_dropping_usdt_d_is_noticed_and_named` drops a panel from the *fixture* path.
    This drops one from the SAME path that produces the PASS — real wiring, real perp
    source — so the two results differ by exactly one panel and nothing else.
    """
    passing, _, grade = shadow._evaluate_layout(
        _ramp(), signal_tf=TF, panel_source=_FakeDominance(), perp_source=_FakePerp())
    assert _verdicts(passing)["GATE-008"] == "PASS"
    assert grade is not None and grade.layout_size == 4

    # One panel withdrawn from the dominance side; everything else identical.
    failing, _, grade_none = shadow._evaluate_layout(
        _ramp(), signal_tf=TF,
        panel_source=_FakeDominance(available=("TOTAL",)), perp_source=_FakePerp())
    assert _verdicts(failing)["GATE-008"] == "FAIL"
    assert _values(failing, "GATE-008")["panels_missing"] == ["USDT.D"]
    assert grade_none is None, "a layout missing a panel must not produce a grade"


def test_the_grade_carries_its_denominator_not_just_its_label():
    """GATE-003 freezes the layout at four, so HEAVY means 2-of-3 correlates.

    A `LIGHT` computed over 2 correlates and one computed over 3 are different facts
    and only one is the rule. The block must therefore carry `disturbed_count` and
    `layout_size`, because the grade alone cannot show which denominator produced it —
    and that number keys the risk matrix.
    """
    grade = DisturbanceClassifier.classify(
        _reads_for_a_clean_btc_long(), direction="LONG",
        instrument="BTC", main_asset_counts=False)
    block = shadow._correlates_block(grade)
    assert block["layout_size"] == 4, "GATE-003 freezes the layout at four panels"
    assert "disturbed_count" in block
    # 4 panels, main excluded by the declared GATE-004 choice -> 3 correlates.
    correlates = [s for s in block["states"] if s["role"] != "MAIN"]
    assert len(correlates) == 3, f"denominator must be 3, got {len(correlates)}"


def test_the_shadow_record_validates_against_the_telemetry_contract(monkeypatch):
    """`assert_valid` on the record the shadow actually emits. Not a key list.

    THE VERSION THIS REPLACED CHECKED THE KEYS I EXPECTED. It imported
    `telemetry.validate` for a side effect, never called it, and asserted against a
    hardcoded set — under a docstring claiming it asserted against the schema. So the
    test written to fix *"I checked the keys I expected instead of the schema the
    record must satisfy"* did exactly that, with a better-chosen list.

    It failed in the hiding direction: add a required property to `correlate_state`
    tomorrow and the key-list version still passes while every record silently fails
    validation and `_shadow_evaluate` swallows it — which is how the shadow went dark
    for forty minutes.

    A key list is also strictly weaker than it looks here. `correlate_state.tf` is an
    enum of legal timeframes, so the schema rejects `""` and any malformed value; the
    truthiness assertion it replaced could not.

    One assertion, against the real record, through the real validator.
    """
    from app.services.telemetry import validate as tvalidate

    monkeypatch.setattr(
        shadow, "_read_panels",
        lambda signal_tf, **kw: (
            {"BTCUSDT.P": _ramp(), "ETHUSDT.P": _ramp(),
             "TOTAL": _ramp(), "USDT.D": _ramp(rising=False)},
            {"BTCUSDT.P": None, "ETHUSDT.P": None, "TOTAL": 360, "USDT.D": 360},
            [],
        ),
    )

    idx = pd.DatetimeIndex([T0 + timedelta(hours=k) for k in range(80)], tz="UTC")
    base = [100.0 + k for k in range(80)]
    df = pd.DataFrame({"open": base, "high": [b + 1 for b in base],
                       "low": [b - 1 for b in base], "close": [b + 0.5 for b in base],
                       "volume": [1.0] * 80}, index=idx)

    record = shadow.evaluate(
        "BTC/USD", df, signal_tf=TF,
        declared=shadow.declared_parameters(), sequence_no=1, scan_id="test-scan",
    )
    assert record is not None, "the shadow produced no record at all"
    assert record["correlates"]["layout_size"] == 4, record["correlates"]

    # The contract decides, not a list I wrote.
    tvalidate.assert_valid(record)


def test_a_neutral_panel_does_not_silently_drop_the_record(monkeypatch):
    """NEUTRAL is legal in `agreement_state` and illegal in `observed_order_flow`.

    The grader's Flow vocabulary is BULLISH/BEARISH/NEUTRAL; the schema's is
    BULLISH/BEARISH/UNCLEAR. A panel reads NEUTRAL whenever its structure shows no
    clear direction, and a MISSING panel is recorded NEUTRAL by construction — so this
    is a routine market state, and every record containing one failed validation and
    was dropped silently by `_shadow_evaluate`.

    The trap is that the same token is valid in the neighbouring field, so a blanket
    rename would fix one and corrupt the other. This pins both halves.
    """
    from app.services.telemetry import validate as tvalidate

    flat = [Bar(time=T0 + timedelta(hours=i), open=100.0, high=100.5,
                low=99.5, close=100.0) for i in range(60)]
    monkeypatch.setattr(
        shadow, "_read_panels",
        lambda signal_tf, **kw: (
            {"BTCUSDT.P": flat, "ETHUSDT.P": flat, "TOTAL": flat, "USDT.D": flat},
            {"BTCUSDT.P": None, "ETHUSDT.P": None, "TOTAL": 360, "USDT.D": 360},
            [],
        ),
    )
    idx = pd.DatetimeIndex([T0 + timedelta(hours=k) for k in range(80)], tz="UTC")
    base = [100.0 + k for k in range(80)]
    df = pd.DataFrame({"open": base, "high": [b + 1 for b in base],
                       "low": [b - 1 for b in base], "close": [b + 0.5 for b in base],
                       "volume": [1.0] * 80}, index=idx)

    record = shadow.evaluate("BTC/USD", df, signal_tf=TF,
                             declared=shadow.declared_parameters(),
                             sequence_no=1, scan_id="test-scan")
    assert record is not None
    flows = {s["observed_order_flow"] for s in record["correlates"]["states"]}
    assert "NEUTRAL" not in flows, f"grader vocabulary leaked into the record: {flows}"
    tvalidate.assert_valid(record)


# ---------------------------------------------------------------------------
# The validator over the STATE SPACE, not over one state
# ---------------------------------------------------------------------------

def _panels(btc="up", eth="up", total="up", usdtd="down", drop=()):
    """Four panels with per-panel direction, minus any dropped."""
    mk = lambda d: _ramp(rising=(d == "up"))  # noqa: E731
    all_p = {"BTCUSDT.P": mk(btc), "ETHUSDT.P": mk(eth),
             "TOTAL": mk(total), "USDT.D": mk(usdtd)}
    return {k: v for k, v in all_p.items() if k not in drop}


@pytest.mark.parametrize("label,panels", [
    ("clean-long-all-four",      _panels()),
    ("clean-short-all-four",     _panels(btc="down", eth="down", total="down", usdtd="up")),
    ("one-correlate-disturbed",  _panels(eth="down")),
    ("two-correlates-disturbed", _panels(eth="down", total="down")),
    ("usdtd-inverted",           _panels(usdtd="up")),
    ("one-panel-missing",        _panels(drop=("USDT.D",))),
    ("two-panels-missing",       _panels(drop=("BTCUSDT.P", "ETHUSDT.P"))),
    ("no-panels-at-all",         {}),
])
def test_every_reachable_layout_state_produces_a_valid_record(label, panels, monkeypatch):
    """A validator run over one state is a validator; over the state space it is a guard.

    `NEUTRAL` was caught because the fixture happened to produce it. The next
    out-of-enum value may only occur when a panel is missing, when the grade is HEAVY,
    or on a SHORT — and each would go dark silently, because `_shadow_evaluate`
    swallows a validation failure by design.

    These are the states the layout can actually be in: every grade, both directions,
    the inversion, and every degree of absence down to nothing at all.
    """
    from app.services.telemetry import validate as tvalidate

    counts = {k: (None if k.endswith(".P") else 360) for k in panels}
    monkeypatch.setattr(shadow, "_read_panels",
                        lambda signal_tf, **kw: (dict(panels), dict(counts), []))

    idx = pd.DatetimeIndex([T0 + timedelta(hours=k) for k in range(80)], tz="UTC")
    base = [100.0 + k for k in range(80)]
    df = pd.DataFrame({"open": base, "high": [b + 1 for b in base],
                       "low": [b - 1 for b in base], "close": [b + 0.5 for b in base],
                       "volume": [1.0] * 80}, index=idx)

    record = shadow.evaluate("BTC/USD", df, signal_tf=TF,
                             declared=shadow.declared_parameters(),
                             sequence_no=1, scan_id=f"state-{label}")
    assert record is not None, f"{label}: the shadow produced no record"
    tvalidate.assert_valid(record)
