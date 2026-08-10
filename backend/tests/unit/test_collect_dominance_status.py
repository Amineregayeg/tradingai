"""`collect_dominance.py --status` reports density against a real cadence.

THE BUG THIS PINS
`status()` used to compute `expected = int(span_min) + 1` — one sample per minute,
hardcoded. That was true for as long as the collector ran at `--loop 60` and became
false the moment it did not. At the deployed `--loop 10` the old denominator reports
~600% density: a health readout printing an impossible number at exactly the moment
the collector is finally correct, which is the failure mode this repo's register
calls "a 'not measured' state that renders as a plausible number" (KNOWN_ISSUES B13).

It is worth stating why this file exists at all: `collect_dominance.py` had NO test
of any kind before T-0001, despite being the sole producer of a series that cannot be
backfilled. These are the first.

The script is not importable as a package — `pyproject.toml` ships only `app*`, and
`scripts/` is repo tooling — so it is loaded by path.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "collect_dominance.py"


def _load():
    spec = importlib.util.spec_from_file_location("collect_dominance", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["collect_dominance"] = module
    spec.loader.exec_module(module)
    return module


collect_dominance = _load()

HEADER = "ts_utc,TOTAL,TOTAL2,TOTAL3,BTC_D,ETH_D,USDT_D,coverage_pct,supplies_age_h"
START = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)


def write_series(path: Path, *, every_seconds: int, count: int) -> Path:
    """A CSV shaped exactly like the live one, at a known, exact cadence."""
    lines = [HEADER]
    for i in range(count):
        ts = (START + timedelta(seconds=i * every_seconds)).isoformat()
        lines.append(
            f"{ts},2280735890273,977612483024,742336857122,57.1361,10.3158,8.0731,94.83,0.00"
        )
    path.write_text("\n".join(lines) + "\n")
    return path


def density_from(out: str) -> float:
    for line in out.splitlines():
        if line.startswith("density"):
            return float(line.split("%")[0].split()[-1])
    raise AssertionError(f"no density line in:\n{out}")


def cadence_from(out: str) -> str:
    for line in out.splitlines():
        if line.startswith("cadence"):
            return line
    raise AssertionError(f"no cadence line in:\n{out}")


# ---------------------------------------------------------------------------
# The denominator


def test_a_declared_cadence_is_what_density_is_measured_against(tmp_path, capsys):
    """THE MUTATION TARGET. A complete 10s series is 100% dense at 10s.

    Restore `expected = int(span_min) + 1` in `status()` and this reads ~600%,
    because it would be counting a 10-second series against a per-minute
    expectation. That is the whole defect, in one number.
    """
    csv = write_series(tmp_path / "raw.csv", every_seconds=10, count=61)  # 10 minutes

    assert collect_dominance.status(interval=10, path=csv) == 0

    out = capsys.readouterr().out
    assert density_from(out) == pytest.approx(100.0, abs=2.0)
    assert "one sample per 10s" in out
    assert "once-per-minute" not in out, "the per-minute denominator is the bug"


def test_the_cadence_is_inferred_from_the_series_when_none_is_declared(tmp_path, capsys):
    """Nobody running --status by hand knows the collector's --loop value.

    Inferring it is what makes the command useful without that knowledge, and the
    output must say the number was inferred rather than presenting it as configuration.
    """
    csv = write_series(tmp_path / "raw.csv", every_seconds=10, count=61)

    assert collect_dominance.status(path=csv) == 0

    out = capsys.readouterr().out
    assert "10s (inferred from the series)" in cadence_from(out)
    assert density_from(out) == pytest.approx(100.0, abs=2.0)


def test_a_declared_cadence_the_collector_is_missing_shows_as_a_density_shortfall(
    tmp_path, capsys
):
    """Density has to stay able to report BAD news, not just agree with itself.

    A series sampling every 20s while configured for 10s is half the data it should
    have, and saying so is the entire point of the figure. Inference alone could
    never report this — it would call 20s the cadence and 100% the density.
    """
    csv = write_series(tmp_path / "raw.csv", every_seconds=20, count=31)  # 10 minutes

    assert collect_dominance.status(interval=10, path=csv) == 0

    out = capsys.readouterr().out
    assert density_from(out) == pytest.approx(50.0, abs=2.0)
    assert "10s (declared)" in cadence_from(out)


def test_the_declared_cadence_wins_over_the_inferred_one(tmp_path, capsys):
    csv = write_series(tmp_path / "raw.csv", every_seconds=60, count=11)

    assert collect_dominance.status(interval=10, path=csv) == 0

    out = capsys.readouterr().out
    assert "10s (declared)" in cadence_from(out)
    assert density_from(out) == pytest.approx(100.0 / 6.0, abs=2.0)


# ---------------------------------------------------------------------------
# Inferring the cadence


def test_one_outage_does_not_drag_the_inferred_cadence(tmp_path, capsys):
    """The live series has a single 415s gap in fourteen days.

    A mean would let that one gap move the denominator and flatter every density
    figure computed from it; the median is the typical spacing, which is what the
    question actually asks. This is why `observed_interval_seconds` is not a mean.
    """
    lines = [HEADER]
    row = "2280735890273,977612483024,742336857122,57.1361,10.3158,8.0731,94.83,0.00"
    ts = START
    for i in range(60):
        lines.append(f"{ts.isoformat()},{row}")
        ts += timedelta(seconds=415 if i == 30 else 10)
    csv = tmp_path / "raw.csv"
    csv.write_text("\n".join(lines) + "\n")

    assert collect_dominance.observed_interval_seconds(
        [datetime.fromisoformat(line.split(",")[0]) for line in lines[1:]]
    ) == 10.0

    assert collect_dominance.status(path=csv) == 0
    assert "10s (inferred from the series)" in cadence_from(capsys.readouterr().out)


def test_a_single_sample_has_no_cadence_to_infer_and_says_so(tmp_path, capsys):
    """Silence is not a pass — an unmeasurable cadence is reported, never guessed.

    A default of 60 here is how the original defect would come back.
    """
    csv = write_series(tmp_path / "raw.csv", every_seconds=10, count=1)

    assert collect_dominance.status(path=csv) == 0

    out = capsys.readouterr().out
    assert "cadence   unknown" in out
    assert "density" not in out


def test_no_samples_at_all_is_an_error_not_a_zero(tmp_path, capsys):
    csv = tmp_path / "raw.csv"
    csv.write_text(HEADER + "\n")

    assert collect_dominance.status(path=csv) == 1
    assert "no rows" in capsys.readouterr().out


def test_a_missing_file_is_an_error_not_a_zero(tmp_path, capsys):
    assert collect_dominance.status(path=tmp_path / "absent.csv") == 1
    assert "no data yet" in capsys.readouterr().out
