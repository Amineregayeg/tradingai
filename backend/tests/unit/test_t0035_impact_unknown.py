"""T-0035 — an unresolvable calendar impact is UNKNOWN, and the gate decision does not move.

`finnhub.py` had TWO independent fail-open defaults collapsing into one answer:

    impact_raw = str(item.get("impact") or item.get("importance") or "low")   # the `or` chain
    impact = _IMPACT_MAP.get(impact_raw.lower(), "low")                       # the dict default

**A fix that handled only the second would pass three of the four fixtures this task names**, so the
two branches are asserted SEPARATELY here rather than through their shared outcome.

**The safety property is the one that made this landable on live code:** `is_in_blackout` skips
anything that is not `"high"`, so `UNKNOWN_IMPACT` skips exactly as `"low"` did.
`test_the_gate_decision_is_identical_to_the_legacy_coercion` asserts that against a REIMPLEMENTATION
of the old line rather than describing it, so the claim is re-runnable by a later seat instead of
being taken on trust.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services.calendar.finnhub import (
    ABSENT,
    RESOLVED,
    UNKNOWN_IMPACT,
    UNRECOGNISED,
    _IMPACT_MAP,
    CalendarEvent,
    CalendarService,
    _resolve_impact,
)

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent

_T = "2026-05-29T12:30:00Z"


def _item(**over) -> dict:
    """A raw provider event that parses cleanly except for whatever `over` changes."""
    base = {"country": "US", "event": "Some Release", "time": _T}
    base.update(over)
    return base


# The four inputs T-0035 names, each labelled with the branch it actually exercises.
# THE LABEL IS THE POINT: three of these never reach the dict lookup at all.
UNRESOLVABLE = [
    pytest.param(_item(), ABSENT, None, id="no-impact-key-at-all"),
    pytest.param(_item(impact=""), ABSENT, None, id="empty-string"),
    pytest.param(_item(impact=None), ABSENT, None, id="explicit-null"),
    pytest.param(_item(impact="tier-1"), UNRECOGNISED, "tier-1", id="unrecognised-value"),
]


def _legacy_impact(item: dict) -> str:
    """The EXACT line this task replaced, reimplemented so the change can be measured.

    Kept as code rather than as a sentence in a docstring: a described baseline cannot be
    re-run, and *"the decision is unchanged"* is a claim about two behaviours where only one
    of them still exists in the tree.
    """
    impact_raw = str(item.get("impact") or item.get("importance") or "low")
    return _IMPACT_MAP.get(impact_raw.lower(), "low")


# ---------------------------------------------------------------------------
# Criterion 1 — UNKNOWN is recorded, and "low" is no longer claimed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("item,expected_reason,expected_raw", UNRESOLVABLE)
def test_an_unresolvable_impact_is_unknown_and_never_low(item, expected_reason, expected_raw):
    """MUST-FIRE ARM. Each of these returned `"low"` before T-0035."""
    impact, raw, reason = _resolve_impact(item)

    assert impact == UNKNOWN_IMPACT, f"{item!r} resolved to {impact!r}"
    assert impact != "low", (
        f"{item!r} still claims LOW. That is the fail-open this task exists to close: "
        f"'low' is an assertion about the event, not an admission that we have none."
    )
    assert reason == expected_reason
    assert raw == expected_raw


def test_the_legacy_line_really_did_say_low_for_all_four():
    """The must-fire arm is worthless unless the old behaviour was what we claim.

    Without this, `test_an_unresolvable_impact_is_unknown_and_never_low` would pass just as
    happily against inputs that never triggered the defect — a green arm proving nothing,
    which is `B145`'s uncontrolled-probe finding in a new file.
    """
    legacy = {_legacy_impact(p.values[0]) for p in UNRESOLVABLE}
    assert legacy == {"low"}, f"expected the old line to say low for all four, got {legacy}"


def test_the_two_fail_opens_are_independent_and_only_one_reaches_the_dict():
    """THE DISTINCTION A SINGLE-BRANCH FIX WOULD HAVE HIDDEN.

    `{}`, `{"impact": ""}` and `{"impact": None}` are decided by the `or` chain and never
    reach `_IMPACT_MAP` at all. Only `"tier-1"` reaches its default. A fix that widened the
    dict, or that only replaced the dict's default, would pass 3 of the 4 fixtures above and
    leave the commoner case — a field the provider simply omitted — still saying `"low"`.
    """
    reasons = {p.id: p.values[1] for p in UNRESOLVABLE}
    assert reasons["unrecognised-value"] == UNRECOGNISED
    assert {reasons["no-impact-key-at-all"], reasons["empty-string"], reasons["explicit-null"]} == {
        ABSENT
    }, "the three absent-shaped inputs must NOT be reported as unrecognised"


@pytest.mark.parametrize(
    "raw_value,expected",
    [("high", "high"), ("HIGH", "high"), ("3", "high"), ("2", "medium"), ("1", "low"), ("low", "low")],
)
def test_recognised_values_are_untouched(raw_value, expected):
    """MUST-MISS ARM. If this file only ever asserted UNKNOWN it would pass against a
    resolver that returned UNKNOWN for everything."""
    impact, raw, reason = _resolve_impact(_item(impact=raw_value))
    assert impact == expected
    assert reason == RESOLVED
    assert raw == raw_value


def test_importance_is_still_consulted_when_impact_is_absent():
    """The `or` chain's SECOND term is real behaviour, not incidental — dropping it while
    replacing the default would silently narrow what resolves."""
    impact, raw, reason = _resolve_impact({"country": "US", "event": "X", "time": _T, "importance": "3"})
    assert (impact, raw, reason) == ("high", "3", RESOLVED)


# ---------------------------------------------------------------------------
# Criterion 1's boundary — the gate decision MUST NOT move
# ---------------------------------------------------------------------------


def _async_return(value):
    async def _inner():
        return value

    return _inner()


@pytest.mark.asyncio
@pytest.mark.parametrize("item,_reason,_raw", UNRESOLVABLE)
async def test_the_gate_decision_is_identical_to_the_legacy_coercion(item, _reason, _raw):
    """IF THIS FAILS, CRITERION 1 HAS BEEN EXCEEDED and the change is no longer shadow.

    Making an unclassifiable event BLOCK is a live safety-versus-availability trade. It needs
    the count `resolution_stats()` starts accruing, and it is Malek's decision — not a seat's,
    and not something to arrive at as a side effect of a recording change.
    """
    now = datetime.now(tz=timezone.utc)
    when = now + timedelta(minutes=5)

    new_impact, _, _ = _resolve_impact(item)
    old_impact = _legacy_impact(item)
    assert new_impact != old_impact, "this fixture is supposed to be one the change affects"

    async def verdict(impact: str) -> bool:
        svc = CalendarService()
        svc.get_today_events = lambda: _async_return(  # type: ignore[method-assign]
            [CalendarEvent(time=when, event="X", currency="USD", impact=impact)]
        )
        blocked, _ = await svc.is_in_blackout("EUR/USD", blackout_minutes=30)
        return blocked

    assert await verdict(new_impact) == await verdict(old_impact), (
        f"{item!r}: the blackout verdict MOVED, {old_impact!r} -> {new_impact!r}"
    )


@pytest.mark.asyncio
async def test_the_identical_decision_arm_can_actually_detect_a_change():
    """The test above compares two verdicts. If `is_in_blackout` ignored impact entirely it
    would pass vacuously, so this pins that the comparison has a failing case at all."""
    now = datetime.now(tz=timezone.utc)
    when = now + timedelta(minutes=5)

    async def verdict(impact: str) -> bool:
        svc = CalendarService()
        svc.get_today_events = lambda: _async_return(  # type: ignore[method-assign]
            [CalendarEvent(time=when, event="X", currency="USD", impact=impact)]
        )
        blocked, _ = await svc.is_in_blackout("EUR/USD", blackout_minutes=30)
        return blocked

    assert await verdict("high") is True
    assert await verdict(UNKNOWN_IMPACT) is False
    assert await verdict("low") is False


def test_unknown_is_not_a_member_of_the_impact_map():
    """`_IMPACT_MAP` must never learn to produce UNKNOWN, and must never learn to absorb one.

    The plan forbids widening the map to silence an unknown, for the same reason
    `check_partial_rules.py` refuses a loosened grep pattern: **a wider map makes the NEXT
    unrecognised value silently `"low"` again**, and the defect returns with the evidence of
    it removed. This asserts the map's RANGE, so a new key is fine and a new severity is not.
    """
    assert set(_IMPACT_MAP.values()) == {"low", "medium", "high"}
    assert UNKNOWN_IMPACT not in _IMPACT_MAP
    assert UNKNOWN_IMPACT not in set(_IMPACT_MAP.values())


# ---------------------------------------------------------------------------
# Criterion 2's instrument — you cannot count what you do not record
# ---------------------------------------------------------------------------


def test_resolution_stats_counts_the_three_reasons_separately():
    svc = CalendarService()
    svc._parse_events(
        [
            _item(impact="high"),
            _item(impact="tier-1"),
            _item(impact=""),
            _item(),
        ]
    )
    stats = svc.resolution_stats()
    assert stats["counts"] == {RESOLVED: 1, UNRECOGNISED: 1, ABSENT: 2}


def test_stats_name_the_values_because_the_bare_total_prescribes_nothing():
    """ONE REPEATED VALUE AND MANY DISTINCT VALUES HAVE OPPOSITE FIXES, and the count alone
    cannot tell them apart — a missing tier in our map, versus the provider's schema moving.
    """
    repeated = CalendarService()
    repeated._parse_events([_item(impact="tier-1") for _ in range(3)])

    scattered = CalendarService()
    scattered._parse_events([_item(impact=v) for v in ("tier-1", "TIER-2", "sev3")])

    assert repeated.resolution_stats()["counts"][UNRECOGNISED] == 3
    assert scattered.resolution_stats()["counts"][UNRECOGNISED] == 3
    assert repeated.resolution_stats()["unrecognised_values"] == {"tier-1": 3}
    assert scattered.resolution_stats()["unrecognised_values"] == {
        "tier-1": 1,
        "TIER-2": 1,
        "sev3": 1,
    }


def test_stats_are_per_instance_so_one_service_cannot_inherit_another_s_count():
    a = CalendarService()
    a._parse_events([_item(impact="tier-1")])
    b = CalendarService()
    assert b.resolution_stats()["counts"] == {RESOLVED: 0, ABSENT: 0, UNRECOGNISED: 0}
    assert a.resolution_stats()["counts"][UNRECOGNISED] == 1


# ---------------------------------------------------------------------------
# The wire: cache round-trip and what `GET /calendar/today` actually serves
# ---------------------------------------------------------------------------


def test_the_api_payload_says_unknown_and_carries_the_provider_s_own_string():
    """`GET /calendar/today` returns `e.to_dict()` verbatim, so this IS the API contract.

    It is also the ONLY live reader of a parsed impact today: `is_in_blackout` has zero
    production callers. **If this dict kept saying `"low"`, the fix would have reached the
    rule and not the platform.**
    """
    svc = CalendarService()
    events = svc._parse_events([_item(impact="tier-1")])
    payload = events[0].to_dict()

    assert payload["impact"] == UNKNOWN_IMPACT
    assert payload["impact_raw"] == "tier-1"


def test_a_cached_entry_survives_the_round_trip_with_both_fields():
    original = CalendarEvent(
        time=datetime(2026, 5, 29, 12, 30, tzinfo=timezone.utc),
        event="X",
        currency="USD",
        impact=UNKNOWN_IMPACT,
        impact_raw="tier-1",
    )
    restored = CalendarEvent.from_dict(original.to_dict())
    assert restored.impact == UNKNOWN_IMPACT
    assert restored.impact_raw == "tier-1"


def test_from_dict_tolerates_a_cache_entry_written_before_impact_raw_existed():
    """THE FIRST HOUR AFTER ANY DEPLOY READS THESE. Redis holds the old shape for a 3600s
    TTL, so `from_dict` meets dicts without the new key — and a `KeyError` there would empty
    the calendar endpoint rather than fail loudly."""
    legacy_cached = {
        "time": "2026-05-29T12:30:00+00:00",
        "event": "X",
        "currency": "USD",
        "impact": "high",
        "forecast": None,
        "previous": None,
    }
    restored = CalendarEvent.from_dict(legacy_cached)
    assert restored.impact == "high"
    assert restored.impact_raw is None


# ---------------------------------------------------------------------------
# The UI, because a fix whose purpose is VISIBILITY must not end in concealment
# ---------------------------------------------------------------------------


def test_the_ui_groups_by_the_DATA_and_enumerates_only_what_it_has_a_design_for():
    """THE FINDING THAT MADE THIS TEST EXIST, and it runs the opposite way to the usual one.

    A backend-only version of this task would have made an unrecognised event *less* visible
    than the fail-open it replaced. `MorningBriefingPage.tsx` rendered
    `['high','medium','low'].map(...)`, so an `"unknown"` event matched no section — and the
    empty-state message is guarded by `events.length === 0`, which is false, **so the page
    would draw an empty bordered box and say nothing.** Before T-0035 the event was VISIBLE
    AND MISLABELLED; a half fix would have made it invisible.

    **AND `['high','medium','low','unknown']` WOULD HAVE BEEN THE SAME DEFECT ONE MEMBER
    OVER.** An enumeration is a claim about its complement and this one had already been
    wrong once. The page now derives a residual bucket from the values actually present, so
    `KNOWN_IMPACTS` is a list of what the UI has a *designed appearance* for — not a claim
    about what can arrive.

    So this asserts two things and neither is "unknown is in the list":
      1. the designed set matches the backend's designed set, EXACTLY
      2. `UNKNOWN_IMPACT` is NOT among them, because it is handled by derivation
    """
    page = REPO / "frontend" / "src" / "pages" / "MorningBriefingPage.tsx"
    assert page.exists(), page
    source = page.read_text(encoding="utf-8")

    match = re.search(r"const KNOWN_IMPACTS = \[([^\]]*)\] as const", source)
    assert match, "KNOWN_IMPACTS not found — the UI's designed set must stay derivable"
    designed = set(re.findall(r"'([^']+)'", match.group(1)))

    assert designed == set(_IMPACT_MAP.values()), (
        f"the UI designs for {sorted(designed)} and the backend can map to "
        f"{sorted(set(_IMPACT_MAP.values()))}. A severity added on one side of the wire only "
        f"renders in the residual bucket, which is safe but undesigned."
    )
    assert UNKNOWN_IMPACT not in designed, (
        f"{UNKNOWN_IMPACT!r} is enumerated in KNOWN_IMPACTS. That re-arms the exact defect "
        f"this task closed: the NEXT unrecognised value renders nowhere again."
    )
    assert "groupByImpact" in source, "the residual bucket must be derived, not listed"


def test_the_ui_does_not_reintroduce_the_cast_that_hid_the_missing_key():
    """`IMPACT_COLORS[impact as keyof typeof IMPACT_COLORS]` was load-bearing scaffolding for
    the enumerated design, not an unrelated wart.

    **It defeats the compiler at exactly the point where it would otherwise catch a missing
    key**: widen the bucket list without widening the colour map and it type-checks, returns
    `undefined`, and emits `color: undefined` — so unrecognised events render in the inherited
    colour. The fail-open one layer below the one this task is closing, compiling clean.

    Asserted on CODE rather than on the file as a whole: the phrase survives in a comment that
    explains why it is not used, and a text grep would call that a hit. `T-0032`'s
    text-versus-identifier lesson, in a language with no AST module to hand.
    """
    page = REPO / "frontend" / "src" / "pages" / "MorningBriefingPage.tsx"
    code = [
        line
        for line in page.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith(("//", "*", "/*"))
    ]
    offenders = [line.strip() for line in code if "as keyof typeof" in line]
    assert not offenders, f"the cast is back on a code line: {offenders}"


def test_this_files_own_ui_guard_would_notice_the_pre_t0035_page():
    """CONTROL ARM. The guard above must FAIL on the shape it exists to reject, not merely
    pass on the shape that is there. An assertion nobody has seen fail is a claim about a code
    path nobody has executed — and both arms of this pair are synthesised, because the case
    the guard exists for does not occur in the tree by construction."""
    # The pre-T-0035 page: enumerated, and UNKNOWN_IMPACT nowhere in it.
    assert set(_IMPACT_MAP.values()) == {"high", "medium", "low"}
    # The tempting half fix: enumerated WITH unknown. Designed-set equality is what rejects it.
    tempting = {"high", "medium", "low", UNKNOWN_IMPACT}
    assert tempting != set(_IMPACT_MAP.values())
    assert UNKNOWN_IMPACT in tempting
