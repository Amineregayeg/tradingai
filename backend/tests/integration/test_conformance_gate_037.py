"""HG-16 · Premium/discount and OTE never gate. The first conformance assertion.

GATE-037 is a NEGATIVE hard gate — it does not require the engine to do something,
it forbids it:

    "The bot should not use a premium/discount (equilibrium or OTE) entry filter.
     Although I understand the concepts, they are not part of my entry criteria…
     it should not influence whether a trade is taken or rejected. It is neither a
     required confirmation nor a filtering criterion."

The registry calls this "the single biggest image-vs-trader override in the
corpus": his own charts teach premium/discount as live doctrine — entries sited by
half, an entry built on the 0.7–0.8 OTE strip — and he overrides all of it. A
vision layer will keep detecting the geometry. It must never reach the gate.

WHY THE ASSERTION IS ABOUT WORDS
The contract's own conformance test is a token check: "no accept/reject decision
record may cite premium, discount, equilibrium, or OTE". That looks crude next to
a behavioural assertion, and it is the right shape anyway — the geometry is
allowed to survive as READING VOCABULARY under `primitives.ranges`, so what
distinguishes a legal use from an illegal one is not whether equilibrium was
computed but whether it appears on a path that accepted or rejected a trade.

TWO CHECKS, BECAUSE ONE IS NOT ENOUGH
Run 24 seeds and no candidate may cite a banned token — that catches the filter
firing. But a filter that simply never fired on the sampled data would pass it, so
the source of the decision path is checked as well. Together they say: not in the
records, and not in the code that writes them.

Before this, 5 of the 137 declines in run `7d788ad6` read "entry is in premium —
longs only in discount".
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services.live.strategy_step import evaluate_latest_bar_traced
from tests.integration.test_decision_trace import bars, daily

#: The contract's enumerated tokens. A negative hard gate needs an explicit list
#: or its assertion has nothing to assert over (registry note on GATE-037).
BANNED = re.compile(r"premium|discount|equilibrium|\bote\b|\brote\b", re.I)

#: Every module that can accept or reject a trade. `primitives` and the telemetry
#: layer are deliberately absent: they are allowed to RECORD the geometry.
DECISION_PATH = (
    Path("app/services/live/strategy_step.py"),
    Path("app/services/backtest/engine.py"),
)


def test_no_decision_record_cites_a_banned_token():
    """The assertion as the contract words it, over records we actually emitted."""
    offenders: list[str] = []
    for seed in range(1, 25):
        _sig, trace = evaluate_latest_bar_traced("BTC/USD", bars(seed=seed), daily(seed=seed))
        for text in trace.reasons:
            if BANNED.search(text):
                offenders.append(f"seed {seed}: {text}")
        for c in trace.candidates:
            blob = f"{c.get('reason', '')} {sorted(c.keys())}"
            if BANNED.search(blob):
                offenders.append(f"seed {seed}: candidate {blob}")

    assert not offenders, (
        "GATE-037 violated — a decision cited premium/discount/equilibrium/OTE:\n  "
        + "\n  ".join(offenders[:8])
    )


def test_the_decision_path_does_not_mention_the_geometry_at_all():
    """The records are clean because the filter is gone, not because it was quiet.

    A gate that never fired on 24 sampled seeds would pass the test above while
    sitting in the code waiting for the market that trips it. GATE-037 was deleted
    rather than defaulted off for exactly this reason — the same treatment the
    contract demands for the x0.5 risk modifier, which must be "absent from the
    codebase entirely, not merely unused".
    """
    offenders: list[str] = []
    for path in DECISION_PATH:
        assert path.exists(), f"decision path moved: {path}"
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]          # comments may explain the removal
            if BANNED.search(code):
                offenders.append(f"{path}:{lineno}: {line.strip()}")

    assert not offenders, (
        "GATE-037 geometry is back on the decision path:\n  " + "\n  ".join(offenders)
    )


def test_it_cannot_come_back_as_a_tuned_parameter():
    """The feedback loop proposes changes to named knobs. A removed gate that is
    still a knob is one accepted correction away from returning."""
    from app.services.evaluation import feedback

    all_knobs = set(feedback.INDEPENDENT_KNOBS) | set(feedback._KNOB_DEFAULTS)
    assert not [k for k in all_knobs if BANNED.search(k)], (
        f"a banned-geometry knob is still tunable: {sorted(all_knobs)}"
    )


@pytest.mark.parametrize("token", ["premium", "discount", "equilibrium", "OTE"])
def test_the_regex_actually_matches_what_it_claims_to(token):
    """The whole assertion rests on this pattern. A regex that matched nothing
    would make every test above pass for the wrong reason."""
    assert BANNED.search(f"entry is in {token} — longs only in discount")
