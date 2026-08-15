"""T-0018 — pin the `smartmoneyconcepts` output semantics our lookahead fixes are written against.

`requirements-prod.txt` says a version bump here is a STRATEGY CHANGE. Both it and
`test_lookahead_regression.py` DOCUMENT the semantics the three fixes depend on; until this
file, **neither ASSERTED them**. A bump changes the library, our engine code is unchanged, no
probe fires, and the file whose own comment calls it a strategy change is unguarded and
untested. The prober cannot help: it verifies that existing tests are load-bearing, and there
was no test to be load-bearing.

WHAT IS ALREADY PROTECTED AND WHAT IS NOT — MEASURED, NOT ASSUMED (criterion 1c)

Each axis was probed by monkeypatching the library function at its boundary — a simulated
bump — and running the existing lookahead and bias-causality tests:

    axis                                simulated bump              existing tests
    smc.fvg stamping                    output shifted one bar      1 FAILED  -> caught
    smc.swing_highs_lows confirmation   output shifted one bar      1 FAILED  -> caught
    smc.bos_choch BrokenIndex           BrokenIndex - 1             7 passed  -> NOT CAUGHT

**So two of the three were already protected and the third was not.** That is the shrunk task
the criterion hoped for, and it makes this file two different things at once, which is stated
per test rather than left to the reader:

  * for FVG and swing, these assertions are **DOCUMENTATION** — they transcribe a semantic the
    engine tests already defend, and their value is that a bump now names WHAT changed instead
    of surfacing as an unrelated red;
  * for `BrokenIndex`, this is **PROTECTION** — it is the only thing in the suite that fails
    when that semantic moves.

**AND THE TWO "CAUGHT" RESULTS ARE WEAKER THAN THEY LOOK.** Both were caught by
`test_fixture_opens_trades_both_directions` — a canary that asserts the fixture still opens
trades in both directions. It fires because a shifted library changes behaviour enough to stop
trades, not because anything noticed the semantics moved. A reader seeing that red would go
looking at the engine. So "already caught" here means "something goes red", not "the right
thing goes red".

WHY THE MONKEYPATCH IS THE DISCRIMINATOR AND NOT A CONVENIENCE
A fixture that goes red only when OUR code changes has pinned nothing — it re-tests the
engine through the detector and passes on any library version. Each mutation below patches the
LIBRARY function, which is the only way to distinguish "pins the library" from "pins us".
"""
from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd
import pytest
from smartmoneyconcepts import smc

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "btcusdtp_5m_999.csv"
REQUIREMENTS = Path(__file__).resolve().parents[2] / "requirements-prod.txt"

#: The version these semantics were measured against. Not read from the installed package —
#: `smartmoneyconcepts` exposes no `__version__`, which is itself part of why a bump is silent.
PINNED_VERSION = "smartmoneyconcepts==0.0.27"

#: `detector.py` calls `smc.swing_highs_lows(df, swing_length=...)` with this.
SWING_LENGTH = 50


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    rows = list(csv.DictReader(FIXTURE.open()))
    return pd.DataFrame([{
        "open": float(r["open"]), "high": float(r["high"]),
        "low": float(r["low"]), "close": float(r["close"]), "volume": 1.0,
    } for r in rows])


def test_the_pinned_version_is_the_one_these_semantics_were_measured_against():
    """If the pin moves, every assertion in this file is about a library we no longer use.

    This is the assertion that makes the rest of the file mean something: a bump would
    otherwise leave these tests green about the wrong version, or red for a reason nobody
    connects to the bump.
    """
    assert PINNED_VERSION in REQUIREMENTS.read_text(), (
        f"{PINNED_VERSION} is no longer the pin. Every semantic asserted in this file was "
        "measured against it, so re-measure them against the new version and update the "
        "constants here — that is what 'treat any bump as a strategy change' means in "
        "practice."
    )


# ---------------------------------------------------------------------------
# Axis 1 — FVG middle-bar stamping. DOCUMENTATION: already caught elsewhere.
# ---------------------------------------------------------------------------
def test_smc_fvg_stamps_the_gap_at_its_middle_bar(frame):
    """The semantic `engine.py`'s born+2 rule is written against.

    `smc.fvg` indexes a gap at the MIDDLE bar of the three that form it, so the near edge at
    `born + 1` is that bar's own extreme and a retrace test against it is vacuously true.
    That is why entry is only admissible from `born + 2`.

    ONE PHRASING, NOT TWO (criterion 2a). `requirements-prod.txt` described this as
    `low.shift(-1)` and `engine.py` as `low[born+1]`. **Neither string is executed anywhere**
    — both were prose — and two vocabularies for one quantity is how they drift apart. The
    indexed form is the one the code reasons in, so it is the one asserted here and the one
    the requirements comment now uses.
    """
    fvg = smc.fvg(frame)
    gaps = fvg[fvg["FVG"].notna()]
    assert len(gaps) >= 20, f"only {len(gaps)} gaps — too few to be pinning anything"

    for born in gaps.index[:40]:
        if born == 0 or born + 1 >= len(frame):
            continue
        direction = fvg["FVG"][born]
        top, bottom = fvg["Top"][born], fvg["Bottom"][born]
        if direction < 0:      # BEARISH: the gap sits between low[born-1] and high[born+1]
            assert top == pytest.approx(frame["low"][born - 1]), born
            assert bottom == pytest.approx(frame["high"][born + 1]), born
        else:                  # BULLISH: between high[born-1] and low[born+1]
            assert bottom == pytest.approx(frame["high"][born - 1]), born
            assert top == pytest.approx(frame["low"][born + 1]), born


def test_a_shifted_fvg_stamp_breaks_the_pin(frame, monkeypatch):
    """MUTATION at the LIBRARY boundary. A bump that re-stamps the gap must be visible here.

    This axis is already caught by an engine test, so this assertion is documentation rather
    than protection — but a documented semantic that nothing checks is exactly what this task
    exists to end, and the mutation proves the transcription is faithful rather than merely
    plausible.
    """
    original = smc.fvg
    monkeypatch.setattr(smc, "fvg", lambda df, *a, **k: original(df, *a, **k).shift(1))

    with pytest.raises(AssertionError):
        test_smc_fvg_stamps_the_gap_at_its_middle_bar(frame)


# ---------------------------------------------------------------------------
# Axis 2 — swing confirmation lag. DOCUMENTATION: already caught elsewhere.
# ---------------------------------------------------------------------------
def test_smc_swings_are_stamped_at_the_bar_they_occurred_not_when_confirmed(frame):
    """The semantic `_daily_bias_events`' `idx + swing_length` correction is written against.

    A swing detected at bar `idx` cannot be CONFIRMED until roughly `swing_length` bars later,
    because confirming it requires seeing that nothing exceeded it. `smc.swing_highs_lows`
    stamps it at `idx` — the bar where it happened, not the bar where it became knowable — so
    reading the column directly is lookahead, and the engine adds the lag itself.

    THE WINDOW IS FORWARD, AND I MEASURED THAT RATHER THAN ASSUMING IT. My first version
    asserted a SYMMETRIC window either side of the swing, which is the intuitive reading and
    is wrong: it holds on 11 of 12 checkable swings, so it would have shipped as a test that
    fails on real data for a reason unrelated to any bump. Measured over the fixture:

        forward  [idx, idx+L]        13 / 13 hold   <- the library's actual rule
        symmetric [idx-L, idx+L]     11 / 12
        backward [idx-L, idx]        11 / 13

    The forward window IS the confirmation lag: a swing at `idx` is the extremum of the L
    bars that follow it, so it cannot be known until bar `idx + L` — which is exactly the
    correction `_daily_bias_events` applies, and reading the column without it is lookahead.
    """
    swings = smc.swing_highs_lows(frame, swing_length=SWING_LENGTH)
    marked = swings[swings["HighLow"].notna()]
    assert len(marked) >= 5, f"only {len(marked)} swings at swing_length={SWING_LENGTH}"

    checked = 0
    for idx in marked.index:
        if idx + SWING_LENGTH >= len(frame):
            continue
        window = slice(idx, idx + SWING_LENGTH + 1)
        if swings["HighLow"][idx] > 0:
            assert frame["high"][idx] == pytest.approx(frame["high"][window].max()), idx
        else:
            assert frame["low"][idx] == pytest.approx(frame["low"][window].min()), idx
        # And the reported Level is that bar's own extreme, not an interpolation.
        own = frame["high"][idx] if swings["HighLow"][idx] > 0 else frame["low"][idx]
        assert swings["Level"][idx] == pytest.approx(own), idx
        checked += 1
    assert checked >= 3, f"only {checked} swings had a full forward window"


def test_a_shifted_swing_stamp_breaks_the_pin(frame, monkeypatch):
    """MUTATION at the LIBRARY boundary."""
    original = smc.swing_highs_lows
    monkeypatch.setattr(
        smc, "swing_highs_lows", lambda df, *a, **k: original(df, *a, **k).shift(1)
    )
    with pytest.raises(AssertionError):
        test_smc_swings_are_stamped_at_the_bar_they_occurred_not_when_confirmed(frame)


# ---------------------------------------------------------------------------
# Axis 3 — BOS/CHoCH BrokenIndex. PROTECTION: NOTHING ELSE CATCHES THIS.
# ---------------------------------------------------------------------------
def test_smc_bos_choch_broken_index_is_strictly_AFTER_the_event(frame):
    """THE AXIS THIS TASK IS FOR. Measured: no existing test fails when this semantic moves.

    `BrokenIndex` is the bar at which a break is CONFIRMED, and it is always later than the
    bar the break is stamped at. That is precisely why the full-series bias is non-causal —
    whether a break at bar k is confirmed, and when, depends on bars after k — and why
    `_causal_daily_bias_events` reconstructs the bias from a trailing window instead of
    reading this column.

    If a bump made `BrokenIndex` point at or before the event, the trailing-window
    reconstruction would be correcting a lag that no longer exists, and the correction would
    itself become the distortion. Nothing else in the suite would notice: patching
    `BrokenIndex - 1` leaves all seven lookahead and bias-causality tests green.
    """
    swings = smc.swing_highs_lows(frame, swing_length=SWING_LENGTH)
    events = smc.bos_choch(frame, swings)
    broken = events[events["BrokenIndex"].notna()]
    assert len(broken) >= 2, f"only {len(broken)} confirmed breaks in the fixture"

    for idx in broken.index:
        confirmed_at = events["BrokenIndex"][idx]
        assert confirmed_at > idx, (
            f"a break stamped at bar {idx} reports BrokenIndex {confirmed_at}, which is not "
            "after it — confirmation cannot precede the event, and the engine's causal "
            "reconstruction assumes it does not"
        )


def test_a_shifted_broken_index_breaks_the_pin(frame, monkeypatch):
    """MUTATION at the LIBRARY boundary, on the axis where it has real force.

    This is the one mutation in the file whose discriminator is genuinely available: the
    existing tests stay GREEN under this bump, so a red here is this file and nothing else.
    """
    original = smc.bos_choch

    def _pulled_back(df, swings, *a, **k):
        out = original(df, swings, *a, **k).copy()
        # Confirmation reported at the event bar itself — the lag gone.
        out["BrokenIndex"] = out.index.to_series().where(out["BrokenIndex"].notna())
        return out

    monkeypatch.setattr(smc, "bos_choch", _pulled_back)
    with pytest.raises(AssertionError):
        test_smc_bos_choch_broken_index_is_strictly_AFTER_the_event(frame)
