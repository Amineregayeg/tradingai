"""GATE-017/019 and the bias invariant, enforced rather than documented.

Both of these were commented and unguarded. `ENTRY_TF` sat at `1H` — an
analysis-only timeframe — for the platform's entire history, and 12 of 12 entries
were triggered from it. `BIAS_TF` carries a written invariant at
`fixed_config.py:50-52` that nothing checked.

A grep for GATE-017 in `tests/` returns a hit, and it is rationale rather than
coverage: `test_dominance_source.py` mentions the gate in a docstring while asserting
on `viable_timeframes`, never on `ENTRY_TF`. So "is GATE-017 tested?" answered
reassuringly yes while the gate was being violated on every trade. Third instance of
that shape this week.
"""
from __future__ import annotations

import pytest

from app.services.live import fixed_config as fixed
from app.services.market_data.sources.dominance import (
    _TF_SECONDS,
    expected_samples_per_bar,
)
from app.services.rules.gate_008_roster import MIN_SAMPLES_PER_SYNTHETIC_BAR

#: GATE-018's ruled execution set. Compared case-insensitively on purpose: the data
#: layer keys on "5m" and `shadow.RULED_EXECUTION_TFS` on "5M", and this test must not
#: silently depend on which spelling the constant happens to use today.
RULED_EXECUTION = {"30m", "15m", "5m"}
ANALYSIS_ONLY = {"1h", "2h", "4h", "d", "1d", "w", "1w", "1mo"}


def test_entry_tf_is_a_ruled_execution_timeframe_not_an_analysis_one():
    """GATE-017/019: 1H and above are analysis only. A HARD_GATE with no guard."""
    tf = fixed.ENTRY_TF.lower()
    assert tf not in ANALYSIS_ONLY, (
        f"ENTRY_TF={fixed.ENTRY_TF!r} is analysis-only — GATE-017/019 make it a "
        "CRITICAL violation, not a preference, and every entry taken on it is one"
    )
    assert tf in RULED_EXECUTION, (
        f"ENTRY_TF={fixed.ENTRY_TF!r} is outside the ruled set {sorted(RULED_EXECUTION)}"
    )


def test_entry_tf_spelling_is_one_the_data_layer_accepts():
    """`"5M"` raises in the data layer; `"5m"` does not. The codebase holds both forms."""
    assert fixed.ENTRY_TF in _TF_SECONDS, (
        f"ENTRY_TF={fixed.ENTRY_TF!r} is not a key of _TF_SECONDS — the data layer "
        f"uses lowercase minutes. Keys: {sorted(_TF_SECONDS)}"
    )


def test_bias_tf_is_strictly_higher_than_entry_tf():
    """`fixed_config.py:50-52` states the invariant; nothing enforced it.

    "A bias taken from the same series it trades tells you nothing the entry did not
    already say." The only existing reference asserts the loop READS the constant, not
    that the constant is sane.
    """
    assert fixed.BIAS_TF in _TF_SECONDS, f"BIAS_TF={fixed.BIAS_TF!r} unknown"
    assert _TF_SECONDS[fixed.BIAS_TF] > _TF_SECONDS[fixed.ENTRY_TF], (
        f"BIAS_TF={fixed.BIAS_TF!r} is not higher than ENTRY_TF={fixed.ENTRY_TF!r}"
    )


def test_entry_tf_correlate_panels_can_actually_be_graded():
    """The layout must be readable at the timeframe we trade, and the poll rate is DERIVED.

    `expected_samples_per_bar(ENTRY_TF, poll) >= MIN_SAMPLES_PER_SYNTHETIC_BAR`. This is
    what makes 1M impossible rather than discouraged: at 10 s a 1m bar holds 6 against a
    minimum of 20.

    THE POLL RATE IS READ FROM THE COLLECTOR'S OWN FLOOR, never written here. It is a
    production fact that already changed once this week — 60 s to 10 s in T-0001, which
    is the change that made 5m viable at all. Hardcoding it would make this guard a
    stale quoted constant, which is B21's class, in a guard written by the programme
    that catalogued B21.
    """
    poll = _collector_poll_floor_seconds()
    samples = expected_samples_per_bar(fixed.ENTRY_TF, poll)
    assert samples >= MIN_SAMPLES_PER_SYNTHETIC_BAR, (
        f"at {poll:g}s polling a {fixed.ENTRY_TF} bar holds {samples} samples against a "
        f"minimum of {MIN_SAMPLES_PER_SYNTHETIC_BAR} — the correlate layout cannot be "
        "graded at the timeframe the engine trades"
    )


def _collector_poll_floor_seconds() -> float:
    """The collector's enforced minimum poll interval, read from its source.

    `collect_dominance.py` is not importable as a module (`pyproject` ships only
    `app*`), so the floor is read out of `interval = max(10, int(args.loop))` rather
    than imported. Read rather than restated: a second copy of this number is exactly
    how the first one went stale.
    """
    import re
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / "scripts" / "collect_dominance.py").read_text()
    m = re.search(r"interval\s*=\s*max\(\s*(\d+)\s*,", src)
    assert m, "could not read the collector's poll floor from collect_dominance.py"
    return float(m.group(1))
