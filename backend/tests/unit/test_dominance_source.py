"""DominanceSource — schema, causality, and refusal-to-fabricate.

The causality tests here exist for the same reason
``tests/integration/test_lookahead_regression.py`` does. Magic Alignment runs
structure detection on these bars, so a bar that contains a sample from after
its own timestamp is a lookahead in the confirmation signal — harder to spot
than one in the entry logic, and just as capable of manufacturing an edge that
is not there.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.services.market_data.sources.base import OHLCV_COLUMNS
from app.services.market_data.sources.dominance import (
    DOMINANCE_SYMBOLS,
    DominanceSource,
    expected_samples_per_bar,
    viable_timeframes,
)
from app.services.rules.gate_008_roster import MIN_SAMPLES_PER_SYNTHETIC_BAR

T0 = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
WIDE_END = T0 + timedelta(days=1)

HEADER = "ts_utc,TOTAL,TOTAL2,TOTAL3,BTC_D,ETH_D,USDT_D,coverage_pct,supplies_age_h\n"


def write_raw(path, rows: list[tuple[datetime, float]]) -> None:
    """Write a raw sample file; `rows` is (timestamp, BTC_D value)."""
    lines = [HEADER]
    for ts, btcd in rows:
        lines.append(
            f"{ts.isoformat()},2000000000000,900000000000,700000000000,"
            f"{btcd:.4f},10.0000,8.0000,94.50,1.00\n"
        )
    path.write_text("".join(lines))


@pytest.fixture
def raw_csv(tmp_path):
    return tmp_path / "dominance_intraday_raw.csv"


# ---------------------------------------------------------------------------
# Causality — the tests that matter
# ---------------------------------------------------------------------------
def test_bar_excludes_samples_from_after_its_own_period(raw_csv):
    """A 15m bar stamped 12:00 must cover [12:00, 12:15) and nothing later.

    The probe: a huge spike at exactly 12:15:00. If the 12:00 bar's high picks it
    up, the bar is reporting a value that had not happened when it closed.
    """
    write_raw(raw_csv, [
        (T0 + timedelta(minutes=0), 50.0),
        (T0 + timedelta(minutes=7), 51.0),
        (T0 + timedelta(minutes=14, seconds=59), 52.0),
        (T0 + timedelta(minutes=15), 99.0),           # first sample of the NEXT bar
        (T0 + timedelta(minutes=29), 60.0),
        (T0 + timedelta(minutes=44), 61.0),           # closes the 12:30 bar
    ])
    bars = DominanceSource(raw_csv).fetch_ohlcv("BTC.D", "15m", T0, WIDE_END)

    first = bars.loc[pd.Timestamp(T0)]
    assert first["high"] == 52.0, "the 12:00 bar absorbed a sample from 12:15 or later"
    assert first["open"] == 50.0
    assert first["close"] == 52.0

    second = bars.loc[pd.Timestamp(T0 + timedelta(minutes=15))]
    assert second["open"] == 99.0, "the 12:15 sample must open the 12:15 bar"


def test_partial_trailing_bar_is_dropped(raw_csv):
    """A bar whose period has not elapsed is not knowable yet."""
    write_raw(raw_csv, [
        (T0 + timedelta(minutes=0), 50.0),
        (T0 + timedelta(minutes=14), 51.0),
        (T0 + timedelta(minutes=15), 52.0),   # opens 12:15; period ends 12:30
        (T0 + timedelta(minutes=20), 53.0),   # ...but the last sample is 12:20
    ])
    src = DominanceSource(raw_csv)

    bars = src.fetch_ohlcv("BTC.D", "15m", T0, WIDE_END)
    assert list(bars.index) == [pd.Timestamp(T0)], "the still-forming 12:15 bar was returned"

    kept = src.fetch_ohlcv("BTC.D", "15m", T0, WIDE_END, drop_partial=False)
    assert len(kept) == 2, "drop_partial=False should expose the forming bar"


def test_complete_trailing_bar_is_kept(raw_csv):
    """Guard against over-correction: a genuinely closed last bar must survive."""
    write_raw(raw_csv, [
        (T0 + timedelta(minutes=0), 50.0),
        (T0 + timedelta(minutes=15), 52.0),
        (T0 + timedelta(minutes=30), 53.0),   # 12:15 bar's period is over
    ])
    bars = DominanceSource(raw_csv).fetch_ohlcv("BTC.D", "15m", T0, WIDE_END)
    assert pd.Timestamp(T0 + timedelta(minutes=15)) in bars.index


# ---------------------------------------------------------------------------
# Refusal to fabricate
# ---------------------------------------------------------------------------
def test_gaps_produce_no_bars(raw_csv):
    """A collector outage must leave a hole, not flat synthetic candles."""
    write_raw(raw_csv, [
        (T0 + timedelta(minutes=0), 50.0),
        (T0 + timedelta(minutes=5), 51.0),
        # 12:10 - 13:00 missing: the collector was down
        (T0 + timedelta(minutes=60), 55.0),
        (T0 + timedelta(minutes=65), 56.0),
        (T0 + timedelta(minutes=70), 57.0),
    ])
    bars = DominanceSource(raw_csv).fetch_ohlcv("BTC.D", "5m", T0, WIDE_END)

    stamps = set(bars.index)
    for minutes in (10, 15, 20, 30, 45, 55):
        assert pd.Timestamp(T0 + timedelta(minutes=minutes)) not in stamps, (
            f"a bar was invented for {minutes}m into a known outage"
        )
    assert not bars.isna().any().any(), "gaps must be absent rows, not NaN rows"


def test_volume_is_zero_never_invented(raw_csv):
    write_raw(raw_csv, [(T0 + timedelta(minutes=i), 50.0 + i) for i in range(0, 40, 5)])
    bars = DominanceSource(raw_csv).fetch_ohlcv("TOTAL", "15m", T0, WIDE_END)
    assert (bars["volume"] == 0.0).all(), "dominance has no volume; it must not be fabricated"


def test_missing_file_abstains_rather_than_raising(tmp_path):
    src = DominanceSource(tmp_path / "does_not_exist.csv")
    bars = src.fetch_ohlcv("BTC.D", "15m", T0, WIDE_END)
    assert bars.empty
    assert list(bars.columns) == list(OHLCV_COLUMNS)
    assert src.coverage()["available"] is False


def test_corrupt_file_abstains(raw_csv):
    raw_csv.write_text("this is not,a valid\x00csv at all\n\x00\x01\x02")
    assert DominanceSource(raw_csv).fetch_ohlcv("BTC.D", "15m", T0, WIDE_END).empty


def test_unparseable_timestamps_are_dropped_not_guessed(raw_csv):
    raw_csv.write_text(
        HEADER
        + f"{(T0).isoformat()},2e12,9e11,7e11,50.0000,10.0,8.0,94.5,1.0\n"
        + "not-a-timestamp,2e12,9e11,7e11,51.0000,10.0,8.0,94.5,1.0\n"
        + f"{(T0 + timedelta(minutes=20)).isoformat()},2e12,9e11,7e11,52.0000,10.0,8.0,94.5,1.0\n"
    )
    raw = DominanceSource(raw_csv).load_raw()
    assert len(raw) == 2, "a row with an unreadable timestamp must be dropped, not placed"


# ---------------------------------------------------------------------------
# Schema / contract
# ---------------------------------------------------------------------------
def test_schema_matches_the_ohlcv_contract(raw_csv):
    write_raw(raw_csv, [(T0 + timedelta(minutes=i), 50.0 + i * 0.1) for i in range(0, 40, 2)])
    bars = DominanceSource(raw_csv).fetch_ohlcv("BTC.D", "15m", T0, WIDE_END)
    assert list(bars.columns) == list(OHLCV_COLUMNS)
    assert bars.index.tz is not None and str(bars.index.tz) == "UTC"
    assert bars.index.name == "time"
    assert bars.index.is_monotonic_increasing and bars.index.is_unique
    assert all(str(d) == "float64" for d in bars.dtypes)
    assert (bars["high"] >= bars["low"]).all()


@pytest.mark.parametrize("symbol", DOMINANCE_SYMBOLS)
def test_every_documented_symbol_resolves(raw_csv, symbol):
    write_raw(raw_csv, [(T0 + timedelta(minutes=i), 50.0 + i) for i in range(0, 40, 5)])
    bars = DominanceSource(raw_csv).fetch_ohlcv(symbol, "15m", T0, WIDE_END)
    assert not bars.empty, f"{symbol} is documented but produced no bars"


def test_unknown_symbol_and_timeframe_raise(raw_csv):
    write_raw(raw_csv, [(T0, 50.0)])
    src = DominanceSource(raw_csv)
    with pytest.raises(ValueError, match="unknown dominance symbol"):
        src.fetch_ohlcv("SOL.D", "15m", T0, WIDE_END)
    with pytest.raises(ValueError, match="unsupported timeframe"):
        src.fetch_ohlcv("BTC.D", "7m", T0, WIDE_END)


def test_range_is_half_open(raw_csv):
    write_raw(raw_csv, [(T0 + timedelta(minutes=i), 50.0 + i) for i in range(0, 90, 5)])
    src = DominanceSource(raw_csv)
    end = T0 + timedelta(minutes=30)
    bars = src.fetch_ohlcv("BTC.D", "15m", T0, end)
    assert pd.Timestamp(T0) in bars.index
    assert pd.Timestamp(end) not in bars.index, "end must be exclusive"


def test_duplicate_timestamps_do_not_double_count(raw_csv):
    ts = T0 + timedelta(minutes=1)
    raw_csv.write_text(
        HEADER
        + f"{ts.isoformat()},2e12,9e11,7e11,50.0000,10.0,8.0,94.5,1.0\n"
        + f"{ts.isoformat()},2e12,9e11,7e11,77.0000,10.0,8.0,94.5,1.0\n"
        + f"{(T0 + timedelta(minutes=20)).isoformat()},2e12,9e11,7e11,52.0000,10.0,8.0,94.5,1.0\n"
    )
    src = DominanceSource(raw_csv)
    assert len(src.load_raw()) == 2
    bars = src.fetch_ohlcv("BTC.D", "15m", T0, WIDE_END)
    assert bars.loc[pd.Timestamp(T0), "close"] == 77.0, "the later duplicate should win"


def test_coverage_reports_honestly(raw_csv):
    write_raw(raw_csv, [(T0 + timedelta(minutes=i), 50.0) for i in range(0, 60, 1)])
    cov = DominanceSource(raw_csv).coverage()
    assert cov["available"] is True
    assert cov["samples"] == 60
    assert cov["span_hours"] == pytest.approx(0.98, abs=0.02)
    assert cov["live_priced_pct_last"] == 94.5
    assert cov["supplies_age_h_last"] == 1.0


# ---------------------------------------------------------------------------
# Sample counts and timeframe viability (M4 / KNOWN_ISSUES B11)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "timeframe, poll, expected",
    [
        ("5m", 60, 5), ("5m", 15, 20),
        ("15m", 60, 15), ("15m", 15, 60),
        ("30m", 60, 30), ("1H", 60, 60),
    ],
)
def test_expected_samples_per_bar_is_the_whole_of_b11(timeframe, poll, expected):
    """These are resampled point observations, not exchange bars. A bar's high and low are
    price action only if enough observations produced them."""
    assert expected_samples_per_bar(timeframe, poll) == expected


def test_the_collectors_poll_rate_decides_which_execution_timeframes_exist():
    """GATE-007 wants the correlate panels at the EXECUTION timeframe and GATE-017 makes 1H
    analysis-only, so the ruled choices are 30M/15M/5M. At 60s only one of the three clears
    the engine's declared minimum; at 15s all three do."""
    at_60 = viable_timeframes(60, MIN_SAMPLES_PER_SYNTHETIC_BAR)
    at_15 = viable_timeframes(15, MIN_SAMPLES_PER_SYNTHETIC_BAR)

    assert "5m" not in at_60 and "15m" not in at_60
    assert "30m" in at_60
    assert {"5m", "15m", "30m"} <= set(at_15)


@pytest.mark.parametrize("bad", [("7m", 60), ("5m", 0), ("5m", -1)])
def test_viability_arithmetic_refuses_nonsense(bad):
    with pytest.raises(ValueError):
        expected_samples_per_bar(*bad)


def test_bars_carry_the_number_of_observations_behind_them(raw_csv):
    """Without this the layout guard has no data source and is decorative: a caller cannot
    tell a 60-sample bar from a 5-sample one by looking at it."""
    write_raw(raw_csv, [(T0 + timedelta(seconds=15 * i), 50.0 + i) for i in range(20)])
    bars = DominanceSource(raw_csv).fetch_ohlcv_with_samples(
        "BTC.D", "1m", T0, WIDE_END, drop_partial=False)

    assert "samples" in bars.columns
    assert int(bars["samples"].iloc[0]) == 4, "4 samples per 1m bar at 15s"


def test_the_public_ohlcv_contract_does_not_leak_the_samples_column(raw_csv):
    """Every other source would have to fake it. Callers that need it ask explicitly."""
    write_raw(raw_csv, [(T0 + timedelta(seconds=15 * i), 50.0 + i) for i in range(20)])
    bars = DominanceSource(raw_csv).fetch_ohlcv("BTC.D", "1m", T0, WIDE_END,
                                                drop_partial=False)
    assert list(bars.columns) == list(OHLCV_COLUMNS)


def test_a_bar_too_thin_to_carry_structure_is_dropped_not_returned_weak(raw_csv):
    """A thin bar is not a low-quality bar, it is not a bar — the same judgement the source
    already makes about an empty period, for the same reason. Returning it anyway is how five
    samples become a disturbance grade and then a position size."""
    src = DominanceSource(raw_csv)
    # Two 1m bars: the first holds 4 samples, the second only 1.
    rows = [(T0 + timedelta(seconds=15 * i), 50.0 + i) for i in range(4)]
    rows.append((T0 + timedelta(minutes=1), 60.0))
    write_raw(raw_csv, rows)

    unfiltered = src.fetch_ohlcv("BTC.D", "1m", T0, WIDE_END, drop_partial=False)
    filtered = src.fetch_ohlcv("BTC.D", "1m", T0, WIDE_END, drop_partial=False,
                               min_samples=4)

    assert len(unfiltered) == 2
    assert len(filtered) == 1, "the 1-sample bar survived"
    assert filtered.index[0] == unfiltered.index[0]


def test_an_empty_result_still_carries_the_samples_column(raw_csv):
    """A "no data" branch that drops the column is how it quietly becomes a "zero samples,
    looks fine" branch at the call site."""
    write_raw(raw_csv, [(T0, 50.0)])
    bars = DominanceSource(raw_csv).fetch_ohlcv_with_samples(
        "BTC.D", "1m", T0, WIDE_END, drop_partial=False, min_samples=99)
    assert bars.empty
    assert "samples" in bars.columns


def test_viability_is_reported_rather_than_assumed(raw_csv):
    report = DominanceSource(raw_csv).timeframe_viability(
        poll_seconds=60, min_samples=MIN_SAMPLES_PER_SYNTHETIC_BAR)
    assert report["expected_samples"]["5m"] == 5
    assert "5m" not in report["viable"]
    assert report["min_samples"] == MIN_SAMPLES_PER_SYNTHETIC_BAR
