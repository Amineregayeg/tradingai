"""T-0015 — panel monitoring, both axes, never one verdict (B35, B40).

WHY THE BOUNDARY NUMBERS BELOW ARE WRITTEN OUT INSTEAD OF DERIVED

A freeze/fresh pair is a LARGE-SIGNAL test and the defect it has to catch is a
ONE-INTERVAL offset. If the test computed "fresh" and "frozen" through the same helper
the implementation uses, both sides would shift together when the reference point is
wrong and both directions would still pass — the test would share the implementation's
error and confirm it.

So every age here is stated as wall-clock arithmetic. At `ENTRY_TF = 5m`, measuring from
the bar's CLOSE, with a threshold of 2 intervals:

    newest complete bar closed  9.9 min ago  ->  SILENT
    newest complete bar closed 10.1 min ago  ->  ALARMS, naming the panel

**And that pair is what discriminates the two reference points.** Measured from the bar's
LABEL instead, the healthy 9.9-minute case has a label age of 14.9 minutes — 2.98
intervals — so it would ALARM, and `test_a_panel_just_inside_the_boundary_is_silent`
fails. That is the whole difference, and it is not academic: a label-referenced threshold
of 5 minutes alarms on essentially every cycle, because in healthy operation the label
age reaches 9.9 minutes before the next bar closes. An alarm that fires every cycle gets
muted, and a muted alarm is the silence this monitor exists to end.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.services.live.shadow import PanelFetch
from app.services.monitoring import data_health as dh

RESAMPLED = ("TOTAL", "USDT.D")      # carry a sample count
EXCHANGE = ("BTCUSDT.P", "ETHUSDT.P")  # do not — a candle is not a resampling
ROSTER = ("BTCUSDT.P", "ETHUSDT.P", "TOTAL", "USDT.D")


def _frame(closed_minutes_ago: float, *, bars: int = 40, samples: int | None = 30,
           tf_minutes: float = 5.0):
    """A panel frame whose newest bar CLOSED `closed_minutes_ago` minutes ago.

    The index is bar OPEN time, as every source in this system returns it, so the newest
    open is one interval before the close the caller asked for. Doing that conversion
    here — in the fixture, explicitly — is what keeps this test independent of the
    production helper's own idea of where a bar's age is measured from.

    `tf_minutes` must match the `ENTRY_TF` the monitor will read this frame at. It is a
    parameter rather than a constant because getting it wrong is not a small error: a 5m
    frame read at 1H puts the newest bar's CLOSE in the FUTURE, the age goes negative,
    and every implementation — correct or not — reports "fresh". That produced a
    mutation-proof test in the first version of this file.
    """
    now = datetime.now(tz=timezone.utc)
    newest_open = now - timedelta(minutes=closed_minutes_ago + tf_minutes)
    idx = pd.DatetimeIndex([newest_open - timedelta(minutes=tf_minutes * i)
                            for i in range(bars - 1, -1, -1)])
    data = {"open": [1.0] * bars, "high": [2.0] * bars,
            "low": [0.5] * bars, "close": [1.5] * bars}
    if samples is not None:
        data["samples"] = [samples] * bars
    return pd.DataFrame(data, index=idx)


def _panels(monkeypatch, per_asset: dict[str, PanelFetch]):
    """Pin what `panel_health` sees. Patched at the DEFINITION, not on `dh`.

    `panel_health` imports `fetch_roster_panels` inside the function body, so a patch on
    `dh` would silently do nothing and every test here would measure the live feed.
    """
    def _fake(signal_tf, *, source=None, perp_source=None):
        return list(per_asset.values())

    monkeypatch.setattr("app.services.live.shadow.fetch_roster_panels", _fake)


def _all_fresh(closed_minutes_ago: float = 1.0) -> dict[str, PanelFetch]:
    return {
        a: PanelFetch(a, _frame(closed_minutes_ago, samples=None if a in EXCHANGE else 30),
                      None if a in EXCHANGE else 30)
        for a in ROSTER
    }


# ---------------------------------------------------------------------------
# Criterion 3-i — the boundary, numerically, from both sides
# ---------------------------------------------------------------------------
async def test_a_panel_just_inside_the_boundary_is_silent(monkeypatch):
    """9.9 minutes since close = 1.98 intervals. Healthy, and it must say nothing.

    THIS IS THE ASSERTION THAT FAILS ON A LABEL-REFERENCED IMPLEMENTATION. The same bar's
    label is 14.9 minutes old — 2.98 intervals, over the threshold — so a monitor
    measuring from the label reports this perfectly healthy panel as stale.
    """
    _panels(monkeypatch, _all_fresh(9.9))
    r = await dh.panel_health()

    assert r["status"] == "healthy", r["stale_panels"]
    assert r["stale_panels"] == []
    for asset in ROSTER:
        rec = r["panels"][asset]["recency"]
        assert rec["status"] == "fresh"
        assert rec["age_bars"] == pytest.approx(1.98, abs=0.05)
        assert "warning" not in rec


async def test_a_panel_just_outside_the_boundary_alarms_and_names_itself(monkeypatch):
    """10.1 minutes since close = 2.02 intervals. Over, by one tenth of a minute."""
    panels = _all_fresh(1.0)
    panels["BTCUSDT.P"] = PanelFetch("BTCUSDT.P", _frame(10.1, samples=None), None)
    _panels(monkeypatch, panels)

    r = await dh.panel_health()

    assert r["stale_panels"] == ["BTCUSDT.P"], (
        "the panel one tenth of a minute past the threshold was not reported"
    )
    rec = r["panels"]["BTCUSDT.P"]["recency"]
    assert rec["status"] == "stale"
    assert rec["age_bars"] == pytest.approx(2.02, abs=0.05)
    assert "BTCUSDT.P" in rec["warning"]
    # CRITERION 4: named, not aggregated. The other three must be untouched.
    assert [a for a in ROSTER if r["panels"][a]["recency"]["status"] != "fresh"] == [
        "BTCUSDT.P"
    ]


async def test_the_two_reference_points_disagree_by_exactly_one_interval(monkeypatch):
    """The discrimination above, stated as its own fact so it cannot be lost.

    Written out because the ONLY thing separating a correct monitor from one that alarms
    on every cycle is which timestamp it subtracts from, and nothing else in the codebase
    records that the healthy label age exceeds the healthy close age by a full interval.
    """
    _panels(monkeypatch, _all_fresh(9.9))
    r = await dh.panel_health()

    close_age_bars = r["panels"]["TOTAL"]["recency"]["age_bars"]
    label_age_bars = close_age_bars + 1.0

    assert close_age_bars < dh.PANEL_STALE_BARS < label_age_bars, (
        f"close age {close_age_bars} and label age {label_age_bars} must straddle the "
        f"threshold {dh.PANEL_STALE_BARS} — if they do not, this fixture has stopped "
        "discriminating between the two reference points"
    )
    assert r["scope"]["reference_point"].startswith("bar CLOSE")


async def test_a_frozen_panel_is_detected_and_a_fresh_one_is_not(monkeypatch):
    """CRITERION 3, both directions. A staleness check that has only ever seen fresh
    data is indistinguishable from one that cannot fire."""
    _panels(monkeypatch, _all_fresh(1.0))
    assert (await dh.panel_health())["stale_panels"] == []

    frozen = _all_fresh(1.0)
    frozen["ETHUSDT.P"] = PanelFetch("ETHUSDT.P", _frame(6 * 60, samples=None), None)
    _panels(monkeypatch, frozen)

    r = await dh.panel_health()
    assert r["panels"]["ETHUSDT.P"]["recency"]["status"] == "down"
    assert r["stale_panels"] == ["ETHUSDT.P"]
    assert r["status"] == "down"


# ---------------------------------------------------------------------------
# Criterion 2 — derived from bar duration, not a copied minute count
# ---------------------------------------------------------------------------
async def test_the_threshold_tracks_entry_tf_rather_than_a_minute_count(monkeypatch):
    """The SAME wall-clock age is stale at 5m and fresh at 1H.

    A hardcoded minute count cannot do that, and `COLLECTOR_STALE_MIN = 5.0` — correct
    for a process polling every 10 s — is the value this criterion exists to keep out.
    """
    _panels(monkeypatch, _all_fresh(20.0))          # 20 minutes since close, 5m bars
    at_5m = await dh.panel_health()
    assert at_5m["stale_panels"] == list(ROSTER), "20 minutes is 4 bars at 5m"
    assert at_5m["panels"]["TOTAL"]["recency"]["age_bars"] == pytest.approx(4.0, abs=0.05)

    # The SAME wall-clock age, on an hourly frame. The frame is rebuilt at 1H spacing:
    # reading a 5m frame at 1H would put the newest close in the future and make every
    # implementation look fresh, which is a test that cannot fail rather than one that
    # passes.
    monkeypatch.setattr("app.services.live.fixed_config.ENTRY_TF", "1H")
    _panels(monkeypatch, {
        a: PanelFetch(a, _frame(20.0, tf_minutes=60.0,
                                samples=None if a in EXCHANGE else 30),
                      None if a in EXCHANGE else 30)
        for a in ROSTER
    })
    at_1h = await dh.panel_health()

    assert at_1h["stale_panels"] == [], "20 minutes is a third of a bar at 1H"
    # THE ASSERTION THAT KILLS A HARDCODED DENOMINATOR. A monitor dividing by a literal
    # 300 seconds reports 4.0 here too, and the `stale_panels` check above would not see
    # it if the fixture ever drifted back to a shared frame.
    assert at_1h["panels"]["TOTAL"]["recency"]["age_bars"] == pytest.approx(0.33, abs=0.05)
    assert at_1h["panels"]["TOTAL"]["recency"]["bar_seconds"] == 3600
    assert at_1h["scope"]["stale_after_bars"] == dh.PANEL_STALE_BARS
    assert "1H" in at_1h["scope"]["timeframe_coupling"]


async def test_an_unknown_entry_tf_is_unavailable_not_healthy(monkeypatch):
    monkeypatch.setattr("app.services.live.fixed_config.ENTRY_TF", "7s")
    r = await dh.panel_health()
    assert r["status"] == "unavailable"
    assert r["watching"] is False


# ---------------------------------------------------------------------------
# Criterion 6 / 6a — two axes, and neither may stand in for the other
# ---------------------------------------------------------------------------
async def test_a_thin_panel_is_fresh_and_a_stale_panel_is_thick(monkeypatch):
    """The orthogonality, asserted in both directions in one test.

    Either can manufacture the other — filtering thin bars out leaves the newest-bar
    pointer on an older thick bar (B27) — so a merged verdict could not distinguish the
    two failures it exists to name.
    """
    panels = _all_fresh(1.0)
    panels["TOTAL"] = PanelFetch("TOTAL", _frame(1.0, samples=3), 3)       # thin, fresh
    panels["USDT.D"] = PanelFetch("USDT.D", _frame(6 * 60, samples=300), 300)  # thick, stale
    _panels(monkeypatch, panels)

    r = await dh.panel_health()

    assert r["panels"]["TOTAL"]["recency"]["status"] == "fresh"
    assert r["panels"]["TOTAL"]["thickness"]["status"] == "thin"
    assert r["panels"]["USDT.D"]["recency"]["status"] == "down"
    assert r["panels"]["USDT.D"]["thickness"]["status"] == "ok"

    # The two lists are separate and each names only its own axis.
    assert r["thin_panels"] == ["TOTAL"]
    assert r["stale_panels"] == ["USDT.D"]


async def test_the_thickness_margin_is_reported_as_a_ratio(monkeypatch):
    """B40's finding is that the margin SHRANK from 18x at 1H to 1.5x at 5m and nothing
    failed when it did. A ratio trending toward 1.0 is the warning a boolean cannot give."""
    panels = _all_fresh(1.0)
    panels["TOTAL"] = PanelFetch("TOTAL", _frame(1.0, samples=30), 30)
    _panels(monkeypatch, panels)

    thickness = (await dh.panel_health())["panels"]["TOTAL"]["thickness"]
    assert thickness["status"] == "ok"
    assert thickness["samples"] == 30
    assert thickness["margin"] == pytest.approx(1.5, abs=0.01), (
        "the 5m operating margin is 30 against a minimum of 20"
    )


async def test_a_none_sample_count_is_answered_rather_than_absent(monkeypatch):
    """CRITERION 6a. The perpetual panels carry no count BY CONSTRUCTION.

    They are excluded from GATE-007's `thin` list by its `is not None` condition — not
    partially covered, structurally invisible — and silence there is indistinguishable
    from having passed. So this says so instead.
    """
    _panels(monkeypatch, _all_fresh(1.0))
    r = await dh.panel_health()

    for asset in EXCHANGE:
        t = r["panels"][asset]["thickness"]
        assert t["status"] == "not_applicable"
        assert t["samples"] is None
        assert "exchange bar" in t["reason"]
    assert r["thin_panels"] == []
    for asset in RESAMPLED:
        assert r["panels"][asset]["thickness"]["status"] == "ok"


# ---------------------------------------------------------------------------
# Absent is not stale, and the payload says what it does not cover
# ---------------------------------------------------------------------------
async def test_an_absent_panel_is_unavailable_not_stale(monkeypatch):
    """A panel nobody served has no age. Reporting it as infinitely old would put a
    missing feed and a frozen one under one word, and they need different responses."""
    panels = _all_fresh(1.0)
    panels["BTCUSDT.P"] = PanelFetch("BTCUSDT.P", None, None, "BTCUSDT.P: no bars from fapi")
    _panels(monkeypatch, panels)

    r = await dh.panel_health()
    assert r["panels"]["BTCUSDT.P"]["recency"]["status"] == "unavailable"
    assert r["absent_panels"] == ["BTCUSDT.P"]
    assert r["stale_panels"] == [], "an absent panel was counted as a stale one"
    assert r["status"] == "down"
    assert "no bars from fapi" in r["panels"]["BTCUSDT.P"]["recency"]["reason"]


async def test_a_panel_missing_from_the_fetch_entirely_is_still_reported(monkeypatch):
    """The roster is the denominator, never the fetch. A panel the source did not even
    mention must not vanish from the report — that is how half the roster went unwatched
    in the first place."""
    _panels(monkeypatch, {a: v for a, v in _all_fresh(1.0).items() if a != "USDT.D"})
    r = await dh.panel_health()
    assert set(r["panels"]) == set(ROSTER)
    assert r["absent_panels"] == ["USDT.D"]


async def test_the_payload_states_what_it_does_not_attest(monkeypatch):
    """CRITERION 5. A health field that implies more than it checks is worse than none."""
    _panels(monkeypatch, _all_fresh(1.0))
    scope = (await dh.panel_health())["scope"]

    assert scope["attests"] == "recency_and_thickness_only"
    joined = " ".join(scope["does_not_attest"]).lower()
    for claim in ("values are correct", "roster is complete", "grade", "nothing does"):
        assert claim in joined, f"the payload does not disclaim {claim!r}"
    # CRITERION 2-i: the coupling is recorded as a coupling, not as an identity.
    assert "plumbing" in scope["timeframe_coupling"]


async def test_an_unreadable_fetch_is_unavailable_not_healthy(monkeypatch):
    """A monitor that cannot look reports that it could not look."""
    def _boom(signal_tf, *, source=None, perp_source=None):
        raise RuntimeError("fapi is unreachable")

    monkeypatch.setattr("app.services.live.shadow.fetch_roster_panels", _boom)
    r = await dh.panel_health()
    assert r["status"] == "unavailable"
    assert r["watching"] is False
    assert "fapi is unreachable" in r["reason"]


async def test_panels_are_a_separate_component_from_the_shadow(monkeypatch):
    """Liveness and staleness must not share an output (T-0009's reasoning, held to).

    A shadow can be alive, writing every permitted cycle, and grading frozen bars —
    liveness green, grade garbage.
    """
    async def _shadow_ok():
        return {"status": "healthy", "watching": True}

    frozen = _all_fresh(1.0)
    frozen["BTCUSDT.P"] = PanelFetch("BTCUSDT.P", _frame(6 * 60, samples=None), None)
    _panels(monkeypatch, frozen)
    monkeypatch.setattr(dh, "shadow_health", _shadow_ok)
    monkeypatch.setattr(dh, "DOMINANCE_DIR", dh.DOMINANCE_DIR)

    r = await dh.data_health()
    assert "correlate_panels" in r
    assert r["shadow"]["status"] == "healthy"
    assert "correlate_panels" in r["problems"]
    assert r["ok"] is False


async def test_thin_recent_bars_do_not_manufacture_staleness(monkeypatch):
    """B27, as a property of this monitor. The recency read must be UNFILTERED.

    THE MIXED FRAME IS THE POINT AND A UNIFORMLY-THIN ONE IS NOT. If every bar is thin the
    thickness filter empties the frame and any sane implementation falls back to the
    unfiltered one — so a uniformly-thin fixture passes against a filtered implementation
    and proves nothing. It has to be thin at the tip and thick behind it, which is what
    a real slow minute looks like.

    Here the newest three bars are thin and closed 1 minute ago; the newest THICK bar
    closed 16 minutes ago. An implementation that filters before reading the newest bar
    reports 3.2 intervals — stale — for a panel that is arriving on time and merely thin.
    That would put a density problem and a currency problem under one word, and the
    operator would go looking at the wrong host.
    """
    now = datetime.now(tz=timezone.utc)
    bars = 40
    newest_open = now - timedelta(minutes=1.0 + 5)
    idx = pd.DatetimeIndex([newest_open - timedelta(minutes=5 * i)
                            for i in range(bars - 1, -1, -1)])
    samples = [30] * (bars - 3) + [3, 3, 3]        # thick history, thin tip
    frame = pd.DataFrame(
        {"open": [1.0] * bars, "high": [2.0] * bars, "low": [0.5] * bars,
         "close": [1.5] * bars, "samples": samples},
        index=idx,
    )

    panels = _all_fresh(1.0)
    panels["TOTAL"] = PanelFetch("TOTAL", frame, 3)
    _panels(monkeypatch, panels)

    r = await dh.panel_health()
    rec = r["panels"]["TOTAL"]["recency"]

    assert rec["status"] == "fresh", (
        f"a thin-but-punctual panel was reported as {rec['status']} at "
        f"{rec['age_bars']} bars — the recency read is filtering by thickness first, "
        "which leaves the newest-bar pointer on an older thick bar and turns a density "
        "problem into a currency one"
    )
    assert rec["age_bars"] == pytest.approx(0.2, abs=0.05)
    # ...and the thinness is still reported, on its own axis.
    assert r["panels"]["TOTAL"]["thickness"]["status"] == "thin"
    assert r["stale_panels"] == []
    assert r["thin_panels"] == ["TOTAL"]


async def test_a_bar_closing_in_the_future_is_unmeasurable_not_fresh(monkeypatch):
    """Review's finding against T-0015's own implementation, and it is the never-alarm end.

    The status chain is one-sided — `>= 4`, `>= 2`, else fresh — so a NEGATIVE age falls
    straight through to `fresh` and the monitor reports perfect health forever. It is
    reachable two ways, neither exotic: `bar_seconds` comes from `ENTRY_TF` while the
    panels are read at `signal_tf` (equal by plumbing, not by definition), so a divergence
    puts every close time an interval into the future; and a host clock behind the
    exchange's does the same for free.

    THIS IS THE STATE MY OWN BROKEN FIXTURE WAS IN. The first version of
    `test_the_threshold_tracks_entry_tf_rather_than_a_minute_count` read a 5m frame at 1H,
    which is exactly this condition — and I diagnosed it as a bad test and fixed the test,
    which removed the only thing reaching the hole. So it is asserted here on the
    condition itself rather than via a mislabelled fixture.

    Not `stale` and not `down`: both assert something about the FEED, and the feed can be
    perfectly healthy while the clock or the timeframe is wrong.
    """
    panels = _all_fresh(1.0)
    # A bar whose close is two intervals ahead of now.
    panels["TOTAL"] = PanelFetch("TOTAL", _frame(-15.0, samples=30), 30)
    _panels(monkeypatch, panels)

    r = await dh.panel_health()
    rec = r["panels"]["TOTAL"]["recency"]

    assert rec["status"] == "invalid", (
        f"a bar closing in the future reported {rec['status']!r} at {rec['age_bars']} "
        "bars — a negative age is an unusable measurement, not freshness, and reading it "
        "as fresh means this monitor never alarms again"
    )
    assert rec["age_bars"] < 0
    assert "FUTURE" in rec["warning"]
    assert "clock or the timeframe rather than the feed" in rec["warning"]

    # Its own list, and it must not be laundered through the other two.
    assert r["unmeasurable_panels"] == ["TOTAL"]
    assert r["stale_panels"] == [], "an unmeasurable panel was reported as a stale feed"
    assert r["absent_panels"] == [], "an unmeasurable panel was reported as unserved"
    assert r["status"] == "down", "the component must not read healthy"
