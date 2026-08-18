"""T-0036 Stage A — the news verdict reaches the order path, and enforces nothing.

`GATE-012/013/015/016` were built, tested and mutation-verified at `T-0032`, and the code
that places orders could not see any of them: the complete doctrine precondition set on
`crypto_loop -> strategy_step -> ExecutionService` was `history`, `daily_bias` and `ltf_bos`,
against **79 distinct `HARD_GATE` rules**.

**Every assertion here is about one of two properties**, and the second is the one a later
seat is most likely to erode:

    WIRED        the verdict is computed from the real calendar and lands on DecisionTrace
    UNENFORCED   it suppresses nothing, and "we could not look" never reads as "nothing on"

**A gate that has never been observed to block anything must not be given the power to
block.** Stage B enforces, once `trace.would_block_by` has produced a non-zero, human-read
count — so the tests that pin Stage A's *inaction* are protecting evidence, not caution.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.services.calendar.finnhub import CalendarEvent
from app.services.live.decision_trace import DecisionTrace
from app.services.live.news_context import (
    GATE_NAME,
    NewsContext,
    build_news_context,
    fetch_calendar_events,
    raw_from_calendar_events,
)

# 12:30 UTC == 08:30 NY. The pre-window is [event-15, event); the post-window runs to the
# first M15 close at or after event+30.
RELEASE = datetime(2026, 5, 29, 12, 30, tzinfo=timezone.utc)


def _ev(impact_raw: str | None, *, currency: str = "USD", at: datetime = RELEASE) -> CalendarEvent:
    """A parsed event carrying the PROVIDER'S OWN string, which is what T-0035 preserved."""
    return CalendarEvent(
        time=at, event="Some Release", currency=currency,
        impact="ignored-by-the-rule", impact_raw=impact_raw,
    )


def _ctx(events, *, now: datetime) -> NewsContext:
    return build_news_context(now, events)


# ---------------------------------------------------------------------------
# WIRED — a must-fire arm per rule. "The suite is green" carries no information
# about a rule that was just added unless something makes each one fail.
# ---------------------------------------------------------------------------


def test_gate_012_the_pre_event_window_blocks():
    ctx = _ctx([_ev("high")], now=RELEASE - timedelta(minutes=5))
    assert ctx.would_block is True
    assert ctx.block_reason == "NEWS_PRE_WINDOW"


def test_gate_012_must_fire_arm_outside_the_window_it_does_not():
    """MUST-MISS. Without this, `would_block is True` is equally consistent with a working
    rule and with one that blocks unconditionally."""
    ctx = _ctx([_ev("high")], now=RELEASE - timedelta(minutes=45))
    assert ctx.would_block is False
    assert ctx.block_reason is None


def test_gate_013_the_post_event_window_blocks_and_carries_its_three_terms():
    ctx = _ctx([_ev("high")], now=RELEASE + timedelta(minutes=5))
    assert ctx.would_block is True
    assert ctx.block_reason == "NEWS_POST_WINDOW"
    post = ctx.values()["post_window"]
    # All three terms, not just the answer: "the M15 close is an extra condition, not a
    # substitute for the 30 minutes" is only checkable if both are in the record.
    for key in ("first_permitted_entry_time", "cooldown_end", "m15_close"):
        assert key in post, f"{key} missing — GATE-013's formula is not reconstructible"


def test_gate_013_must_fire_arm_after_the_cooldown_it_does_not():
    ctx = _ctx([_ev("high")], now=RELEASE + timedelta(hours=3))
    assert ctx.would_block is False


def test_gate_015_an_unrecognised_impact_blocks_rather_than_trades():
    """The third state, end to end from the provider's string to the order path.

    `tier-1` is not in the declared mapping, so it classifies UNKNOWN, and UNKNOWN blocks
    under the declared policy. **Before `T-0035` the provider's string was destroyed and this
    event arrived as `low`** — the same event, silently tradeable.
    """
    ctx = _ctx([_ev("tier-1")], now=RELEASE - timedelta(minutes=5))
    assert ctx.would_block is True
    assert ctx.values()["unknown_impact_events"] == 1


def test_gate_015_must_fire_arm_a_recognised_low_does_not_block():
    ctx = _ctx([_ev("low")], now=RELEASE - timedelta(minutes=5))
    assert ctx.would_block is False
    assert ctx.values()["unknown_impact_events"] == 0


def test_gate_015_currency_scope_drops_events_outside_the_set():
    """MUST-MISS on the funnel: a JPY release is not scoped for a crypto/USD instrument."""
    ctx = _ctx([_ev("high", currency="JPY")], now=RELEASE - timedelta(minutes=5))
    assert ctx.would_block is False
    assert ctx.values()["raw_events"] == 1, "the provider did send it"
    assert ctx.values()["scoped_events"] == 0, "and scope dropped it"


def test_gate_016_the_red_folder_day_flag_is_recorded_and_gates_nothing():
    """GATE-016 is a DAY flag while 012/013 are MINUTES gates. Nothing reconciles them and
    the rule must not pick, so it is recorded and nothing branches on it — Salim round-3 6i.
    """
    ctx = _ctx([_ev("high")], now=RELEASE + timedelta(hours=6))
    assert ctx.is_red_folder_day is True
    assert ctx.would_block is False, (
        "the day flag must not become a blackout by the back door — that would be a MINUTES "
        "gate invented out of a DAY flag, which is the reconciliation nobody has ruled on"
    )
    assert ctx.values()["is_red_folder_day"] is True


def test_gate_016_must_fire_arm_a_quiet_day_is_not_a_red_folder_day():
    assert _ctx([_ev("low")], now=RELEASE).is_red_folder_day is False


# ---------------------------------------------------------------------------
# The bridge T-0035 made possible
# ---------------------------------------------------------------------------


def test_the_raw_payload_carries_the_PROVIDER_string_not_the_normalised_one():
    """THE CROSS PRODUCT `CalendarScope.scope()` NEEDS, AND WHY THIS WIRING NEEDED T-0035.

    `scope()` takes raw provider dicts so its verdict does not inherit `finnhub.py`'s
    normalisation, AND it requires a real `datetime`. The provider had the raw impact and a
    string time; `CalendarEvent` had the datetime and had already destroyed the raw impact.
    **Neither source could produce `scope()`'s input.**

    Handing `e.impact` here instead of `e.impact_raw` would not raise — it would classify
    `"low"` as `NOT_RED_FOLDER` and the gate would quietly stop blocking on unknowns.
    """
    raw = raw_from_calendar_events([_ev("tier-1")])
    assert raw[0]["impact"] == "tier-1", "the normalised value must not reach the rule"
    assert isinstance(raw[0]["time"], datetime), (
        "scope() drops a non-datetime time SILENTLY — every event would vanish and the gate "
        "would report 'no blackout' while seeing nothing"
    )


def test_an_absent_provider_impact_still_blocks():
    """`impact_raw is None` means the provider sent nothing to keep. `classify(None)` is
    UNKNOWN, which blocks — so an event we cannot read is not tradeable here either."""
    ctx = _ctx([_ev(None)], now=RELEASE - timedelta(minutes=5))
    assert ctx.would_block is True


# ---------------------------------------------------------------------------
# UNENFORCED — Stage A suppresses nothing, and the record says so
# ---------------------------------------------------------------------------


def test_a_would_block_verdict_does_not_set_blocked_by():
    """`trace.gate()` would set it. `trace.observe()` must not.

    If it did, `summary` would name the news gate as the reason a bar was declined when the
    bar was not declined at all — a lie in the field the trace exists to make honest.
    """
    trace = DecisionTrace(symbol="BTC/USD", timeframe="5m")
    _ctx([_ev("high")], now=RELEASE - timedelta(minutes=5)).record_on(trace)
    assert trace.blocked_by is None
    assert trace.would_block_by == [GATE_NAME]


def test_a_would_block_verdict_does_not_suppress_the_candidate_census():
    """B10, WHICH THIS CHANGE COULD HAVE REBUILT WITHOUT SUPPRESSING ANYTHING.

    `reasons` emits `candidates: N considered` only when `blocked_by is None` — because a run
    stopped by a gate never looked, and claiming it considered zero would be a different
    falsehood. A news verdict routed through the blocking channel would have dropped that
    line on exactly the bars a reader most wants it.
    """
    trace = DecisionTrace(symbol="BTC/USD", timeframe="5m")
    _ctx([_ev("high")], now=RELEASE - timedelta(minutes=5)).record_on(trace)
    trace.candidate(0, "LONG", False, "wrong direction for the daily bias")

    assert any(r.startswith("candidates:") for r in trace.reasons), (
        "the census line vanished — B10, rebuilt by a change that suppresses nothing"
    )
    assert any(r.startswith("WOULD-BLOCK") for r in trace.reasons)
    assert not any(r.startswith("FAIL " + GATE_NAME) for r in trace.reasons), (
        "an unenforced gate must not render as FAIL: a reader scanning for FAIL is looking "
        "for the reason a trade did not happen, and this gate stopped nothing"
    )


def test_the_summary_names_the_enforced_gate_not_the_observation():
    """A latent bug found while building this: `summary` took the first NOT-PASSED gate of
    any kind, so a would-block observation recorded BEFORE a failing gate would have supplied
    the human-readable reason while `blocked_by` correctly named the other one. **Two fields
    disagreeing, and the readable one is the one that gets believed.**"""
    trace = DecisionTrace(symbol="BTC/USD", timeframe="5m")
    _ctx([_ev("high")], now=RELEASE - timedelta(minutes=5)).record_on(trace)
    trace.gate("daily_bias", False, "no daily bias yet")

    assert trace.blocked_by == "daily_bias"
    assert trace.summary == "no daily bias yet"


def test_stage_a_never_removes_a_signal_the_engine_would_otherwise_have_taken():
    """THE STAGE A CONTRACT, asserted on the evaluator rather than described.

    Same bars, same everything, one call with a blocking news verdict and one without. The
    signals must be identical — **if this ever fails, Stage A has become Stage B by
    accident**, and the count Stage B is gated on would have been taken over a population
    the gate had already altered.
    """
    from tests.integration.test_decision_trace import bars, daily
    from app.services.live.strategy_step import evaluate_latest_bar_traced

    blocking = _ctx([_ev("high")], now=RELEASE - timedelta(minutes=5))
    assert blocking.would_block is True, "this fixture must actually block, or the test is vacuous"

    for seed in range(6):
        without, _ = evaluate_latest_bar_traced("BTC/USD", bars(seed=seed), daily(seed=seed))
        with_news, trace = evaluate_latest_bar_traced(
            "BTC/USD", bars(seed=seed), daily(seed=seed), news=blocking
        )
        assert (without is None) == (with_news is None), f"seed {seed}: the signal changed"
        if without is not None:
            # Every field, compared as a whole. Naming three by hand is a claim about which
            # ones Stage A could have altered, and that claim has no basis.
            assert without == with_news, f"seed {seed}: the signal's contents changed"
        assert GATE_NAME in trace.would_block_by


# ---------------------------------------------------------------------------
# "Could not look" must never read as "looked and found nothing"
# ---------------------------------------------------------------------------


def test_no_news_argument_records_NOT_EVALUATED_rather_than_staying_silent():
    from tests.integration.test_decision_trace import bars, daily
    from app.services.live.strategy_step import evaluate_latest_bar_traced

    _sig, trace = evaluate_latest_bar_traced("BTC/USD", bars(), daily())
    line = next(r for r in trace.reasons if GATE_NAME in r)
    assert line.startswith("NOT-EVALUATED"), line
    assert trace.would_block_by == [], "a verdict that was never taken is not a would-block"


def test_an_unavailable_calendar_is_not_an_empty_one():
    ctx = NewsContext.unavailable(RELEASE, "FINNHUB_API_KEY not configured")
    assert ctx.would_block is None, "None, not False — False is a verdict and none was taken"
    assert "NOT TAKEN" in ctx.detail and "not 'no blackout'" in ctx.detail.lower()
    assert ctx.values()["evaluated"] is False


def test_a_missing_api_key_yields_no_events_rather_than_an_empty_calendar():
    """MEASURED, AND IT IS THE LIVE STATE OF THIS REPOSITORY.

    `_fetch_from_finnhub` returns `[]` — with a warning nothing downstream can see — when no
    key is configured. Passed through, that scopes to zero events, decides ALLOW, and writes
    *"no news blackout"* on every bar the platform ever evaluates: **a calendar that was never
    consulted, indistinguishable from a quiet news week, in the exact field built to tell them
    apart.** The API router already refuses the same state with a 503.
    """
    events, reason = asyncio.run(fetch_calendar_events())
    assert events is None, "an unconfigured provider must not answer with an empty calendar"
    assert reason and "FINNHUB_API_KEY" in reason


def test_a_scope_that_saw_nothing_is_distinguishable_from_one_that_saw_events():
    """An INERT gate and a working one both say "no blackout". The funnel is what separates
    them, and it is why the counts are carried rather than just the verdict."""
    quiet = _ctx([_ev("low")], now=RELEASE).values()
    empty = _ctx([], now=RELEASE).values()

    assert quiet["scoped_events"] == 1 and quiet["blocking_events"] == 0
    assert empty["scoped_events"] == 0 and empty["raw_events"] == 0
    assert quiet != empty, "an inert gate must not be byte-identical to a working quiet one"


@pytest.mark.parametrize("term", ["atr", "stdev", "percentile", "sigma", "zscore"])
def test_the_seam_invents_no_numeric_volatility_test(term):
    """GATE-014 is OPEN and its resumption condition is undefined. `T-0032` refused to invent
    one; wiring the seam must not smuggle one in through the back door."""
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "app/services/live/news_context.py"
    names = set()
    for node in ast.walk(ast.parse(src.read_text(encoding="utf-8"))):
        for field in getattr(node, "_fields", ()):
            value = getattr(node, field, None)
            if isinstance(value, str):
                names.add(value)
    offenders = [n for n in names if term in n.lower() and not n.startswith(("#", " "))]
    assert not offenders, f"{term!r} appears as an identifier in the seam: {offenders}"
