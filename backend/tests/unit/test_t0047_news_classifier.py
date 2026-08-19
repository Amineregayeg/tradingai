"""T-0047 — GATE-015's ruled filter, and the two rows that are the whole ruling.

    blocks = (impact == RED OR force_included) AND taxonomy IN his six AND currency IN scope

**Before this task the filter was the impact half alone, so it was wrong in BOTH directions:** a
vendor-HIGH housing print blocked (his ruling says it must not) and a vendor-MEDIUM FOMC item did
not (his ruling says it must). *A one-conjunct filter standing in for a three-conjunct one does not
under-block; it blocks the wrong set.*
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.rules.gate_015_calendar_scope import CalendarScope, ScopedEvent
from app.services.rules.gate_015_classifier import (
    DECLARED_CLASSIFIER, TYPES_EXCLUDED, TYPES_INCLUDED, UNCLASSIFIED_RED_POLICY, classify,
    force_include,
)

NY = ZoneInfo("America/New_York")


def _raw(name: str, impact: str, currency: str = "USD", hour: int = 9) -> dict:
    return {"id": name[:8], "event": name, "impact": impact, "currency": currency,
            "time": datetime(2026, 8, 18, hour, 30, tzinfo=NY)}


def _one(name: str, impact: str, currency: str = "USD") -> ScopedEvent:
    scoped = CalendarScope.scope([_raw(name, impact, currency)])
    assert len(scoped) == 1, f"{name} was dropped before classification"
    return scoped[0]


# ---------------------------------------------------------------------------
# THE TWO ROWS THAT ARE THE WHOLE RULING
# ---------------------------------------------------------------------------
def test_a_vendor_MEDIUM_fomc_item_makes_the_day_RED():
    """[RULING]. His card rates FOMC talks/statements/conferences VERY HIGH; the vendor does not.

    **This is the direction the old filter got wrong by OMISSION** — a medium-impact FOMC event
    was invisible to a filter keyed on impact alone, and it is the single event class most likely
    to move the market the engine trades.
    """
    day = CalendarScope.scope([_raw("FOMC Statement", "medium")])
    assert CalendarScope.is_red_folder_day(day) is True
    event = day[0]
    assert event.force_included is True
    assert event.category == "CENTRAL_BANK", (
        "a force-included event must be REASSIGNED into the six, or the force-include is inert "
        "against its own type conjunct"
    )
    assert event.blocks is True


def test_a_vendor_HIGH_housing_print_does_NOT_make_the_day_red():
    """[RULING]. IGNORE AND LOG — logged, never blocked.

    **This is the direction the old filter got wrong by COMMISSION**: it blocked on impact alone,
    so every vendor-high housing print stopped trading on a day he rules tradeable.
    """
    day = CalendarScope.scope([_raw("Existing Home Sales", "high")])
    assert CalendarScope.is_red_folder_day(day) is False
    event = day[0]
    assert event.category == "HOUSING" and event.category in TYPES_EXCLUDED
    assert event.blocks is False
    assert event.block_verdict[1] == "RULED_EXCLUDED_TYPE", (
        "the non-block must say it was HIS ruling — a bare False cannot be told from a miss"
    )
    assert event.classifier_miss is False


# ---------------------------------------------------------------------------
# One must-fire per branch, and the branches are NOT symmetric
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name,impact,currency,blocks,reason", [
    ("Core CPI m/m",               "high",   "USD", True,  "RED_OR_FORCED_IN_SCOPE_TYPE"),
    ("Non-Farm Employment Change", "high",   "USD", True,  "RED_OR_FORCED_IN_SCOPE_TYPE"),
    ("ISM Manufacturing PMI",      "high",   "USD", True,  "RED_OR_FORCED_IN_SCOPE_TYPE"),
    ("Existing Home Sales",        "high",   "USD", False, "RULED_EXCLUDED_TYPE"),
    ("Consumer Sentiment",         "high",   "USD", False, "RULED_EXCLUDED_TYPE"),
    ("10-y Bond Auction",          "high",   "USD", False, "RULED_EXCLUDED_TYPE"),
    ("FOMC Statement",             "medium", "USD", True,  "RED_OR_FORCED_IN_SCOPE_TYPE"),
    ("Core CPI m/m",               "low",    "USD", False, "NOT_RED_AND_NOT_FORCED"),
])
def test_each_branch_of_the_disjunction_fires_on_its_own_case(name, impact, currency, blocks, reason):
    event = _one(name, impact, currency)
    verdict, got_reason, _miss = event.block_verdict
    assert verdict is blocks, f"{name} @ {impact}: expected blocks={blocks}, got {verdict}"
    assert got_reason == reason


def test_a_non_USD_event_is_out_of_scope_REGARDLESS_of_type_or_impact():
    """The currency conjunct, and it is checked BEFORE the others by construction.

    A RED event in one of his six is still not his event if it is not his currency.
    """
    assert CalendarScope.scope([_raw("Core CPI m/m", "high", "EUR")]) == []
    # MUST-HIT on the same row: the ONLY difference is the currency.
    assert len(CalendarScope.scope([_raw("Core CPI m/m", "high", "USD")])) == 1


# ---------------------------------------------------------------------------
# The split T-0035's single UNKNOWN could not carry
# ---------------------------------------------------------------------------
def test_the_two_non_blocking_reasons_FAIL_IN_OPPOSITE_DIRECTIONS_and_are_not_one_state():
    """`T-0035` built ONE `UNKNOWN` and left it non-blocking — right for the ruled exclusion and a
    silent fail-open for the classifier miss.

        RULED_EXCLUDED_TYPE     HIS ruling.  Fails toward MORE exposure.  Does NOT block.
        CLASSIFIER_MISS         OURS.        Fails toward FEWER trades.   DOES block.

    **A single state cannot carry two treatments that point opposite ways**, and it is the state
    `T-0036` Stage B would enforce on.
    """
    excluded = _one("Existing Home Sales", "high")
    missed = _one("Zorb Activity Gauge", "high")

    assert excluded.blocks is False and missed.blocks is True
    assert excluded.category == "HOUSING" and missed.category == "UNCLASSIFIED"
    assert excluded.classifier_miss is False and missed.classifier_miss is True
    assert excluded.block_verdict[1] != missed.block_verdict[1], (
        "both non-his-six events produced the same reason — the split has collapsed"
    )


def test_the_classifier_miss_branch_is_labelled_ENGINEERING_IN_THE_RECORD():
    """Not only in a comment. **It is the one branch that is not his**, and `T-0042`'s round-4
    set must be able to quote what we did from stored telemetry alone."""
    record = _one("Zorb Activity Gauge", "high").as_dict()
    assert record["classifier_miss"] is True
    assert "[ENGINEERING]" in record["classifier_miss_authority"]
    assert "round 4" in record["classifier_miss_authority"]
    assert UNCLASSIFIED_RED_POLICY == "BLOCK_AND_LOG_CLASSIFIER_MISS"

    values = CalendarScope.evaluate([_raw("Zorb Activity Gauge", "high")]).values
    assert values["classifier_misses"] == 1
    assert "[ENGINEERING]" in values["unclassified_red_policy_authority"]


def test_an_unrecognised_event_that_is_NOT_red_does_not_block():
    """MUST-MISS on the miss branch: it is gated on RED-or-forced, not on being unrecognised.

    Without this, `UNCLASSIFIED` alone would block and every unknown low-impact event would stop
    trading — which is not the engineering default the pack states.
    """
    event = _one("Zorb Activity Gauge", "low")
    assert event.category == "UNCLASSIFIED"
    assert event.blocks is False
    assert event.block_verdict[1] == "UNCLASSIFIED_NOT_RED"


# ---------------------------------------------------------------------------
# UNCLASSIFIED is not NOT-CHECKED
# ---------------------------------------------------------------------------
def test_UNCLASSIFIED_means_RAN_AND_MATCHED_NOTHING_and_never_did_not_run():
    """The ruled enum has `UNCLASSIFIED` and **no token for NOT CHECKED**.

    `ScopedEvent.category is None` carries the second, and adding a token to a closed enum the
    ruling specifies would be inventing doctrine — `GATE-014`'s shape. **Question 13 to Salim.**
    """
    ran = _one("Zorb Activity Gauge", "high")
    assert ran.category == "UNCLASSIFIED"
    assert ran.as_dict()["category_checked"] is True

    # A ScopedEvent built directly, without the classifier: NOT CHECKED, and it must not be
    # reported as UNCLASSIFIED.
    unchecked = ScopedEvent(
        event_id="x", time_ny=datetime(2026, 8, 18, 9, 30, tzinfo=NY), name="Core CPI m/m",
        currency="USD", impact_raw="high", impact_class="RED_FOLDER",
    )
    assert unchecked.category is None
    assert unchecked.as_dict()["category_checked"] is False
    assert "taxonomy_class" not in unchecked.as_dict(), (
        "an event the classifier never ran on was given a taxonomy_class — that writes NOT "
        "CHECKED into the vocabulary of CHECKED-AND-MATCHED-NOTHING"
    )
    assert unchecked.block_verdict[1].startswith("TYPE_NOT_CHECKED"), (
        "an unchecked event silently took the ruled path — the type conjunct cannot be evaluated"
    )


def test_zero_events_is_NOT_READ_and_not_NOT_EVALUABLE():
    """The producer EXISTS as of T-0047. Filing "nothing to classify" as NOT_EVALUABLE would
    re-file a discharged refusal under the vocabulary of an open one."""
    empty = CalendarScope.evaluate([])
    assert empty.values["conditions"]["red_folder_category_matched"] == "NOT_READ"
    # MUST-HIT: with events it READS, and the rule reaches a real verdict for the first time.
    full = CalendarScope.evaluate([_raw("Core CPI m/m", "high")])
    assert full.values["conditions"]["red_folder_category_matched"] == "TRUE"
    assert full.verdict == "PASS" and full.values["scope_outcome"] == "BOTH_HALVES_APPLIED"


# ---------------------------------------------------------------------------
# The classifier is OURS and says so
# ---------------------------------------------------------------------------
def test_the_classifier_is_declared_unratified_and_versioned_on_every_record():
    """Salim ruled the six TYPES. Recognising one from a vendor's free text is entirely ours, and
    the unratified claim is not a number — it is that THESE PATTERNS RECOGNISE HIS SIX TYPES."""
    assert DECLARED_CLASSIFIER.ratified is False
    assert "ENGINEERING" in DECLARED_CLASSIFIER.authority
    assert "seed" in DECLARED_CLASSIFIER.source.lower()
    assert "NOT been done" in DECLARED_CLASSIFIER.source, (
        "the pack's cross-validation instruction is unmet and the record must say so"
    )
    values = CalendarScope.evaluate([_raw("Core CPI m/m", "high")]).values
    assert values["calendar_classifier_version"] == DECLARED_CLASSIFIER.version
    assert values["calendar_classifier_version_ratified"] is False


def test_the_six_and_the_four_are_READ_from_the_registry_not_retyped():
    """B167: a locally-typed predicate is correct until the ruling moves and then silently
    disagrees with it, and nothing fails."""
    from app.services.telemetry import contract_loader as contract

    values = contract.rule("GATE-015")["values"]
    assert list(TYPES_INCLUDED) == values["event_types_included"]
    assert list(TYPES_EXCLUDED) == values["event_types_excluded"]
    assert set(TYPES_INCLUDED) & set(TYPES_EXCLUDED) == set()


def test_CENTRAL_BANK_wins_over_SPEECHES_for_a_rate_decision():
    """Ordering is OURS and it is load-bearing: `speaks` would otherwise swallow a rate decision.

    Both land in his six so the BLOCK verdict is unchanged either way — which is exactly why this
    needs its own arm. *A misclassification inside the six is invisible in the verdict and visible
    only in the record*, and the record is what round 4 will be argued from.
    """
    assert classify("FOMC Statement")[0] == "CENTRAL_BANK"
    assert classify("Fed Interest Rate Decision")[0] == "CENTRAL_BANK"
    assert classify("Fed Chair Powell speaks")[0] == "SPEECHES"
    forced, _match, as_type = force_include("Fed Chair Powell speaks")
    assert forced and as_type == "SPEECHES"


def test_a_bare_FOMC_pattern_is_NOT_used_for_the_force_include_list():
    """[RULING] EXACT NAMES. A bare `FOMC` would catch FOMC-MEMBER speeches — several a week,
    outside his RED filter — and fail toward far fewer trades.

    `fomc_member_speeches_force_included` is declared `false` and goes to round 4.
    """
    from app.services.rules.gate_015_classifier import (
        FOMC_MEMBER_SPEECHES_FORCE_INCLUDED, FORCE_INCLUDE_BY_NAME,
    )

    assert FOMC_MEMBER_SPEECHES_FORCE_INCLUDED is False
    assert "FOMC" not in FORCE_INCLUDE_BY_NAME, "the bare pattern is in the force-include list"
    forced, _m, _t = force_include("FOMC Member Bowman Speaks")
    assert forced is False, (
        "an FOMC MEMBER speech was force-included — that is the over-match the exact-name list "
        "exists to avoid, and it fails toward far fewer trades"
    )
    # MUST-HIT: the real FOMC events ARE force-included, so the arm above is not vacuous.
    assert force_include("FOMC Statement")[0] is True
    assert force_include("Fed Chair Powell testifies")[0] is True


# ---------------------------------------------------------------------------
# GATE-014's routing — the narrow list, and why it is narrow
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name,exceptional", [
    ("FOMC Statement", True),
    ("FOMC Press Conference", True),
    ("Fed Interest Rate Decision", False),
    ("Fed Chair Powell speaks", False),
    ("Core CPI m/m", False),
    ("Non-Farm Employment Change", False),
])
def test_only_FOMC_class_scheduled_events_arm_the_INDEFINITE_disable(name, exceptional):
    """`exceptional_class_by_name` is TWO names; `force_include_by_name` is EIGHT, and they are
    kept apart on purpose.

    > **`GATE-014` has NO DEFINED RESUMPTION CONDITION.** So a scheduled event reaching it is a
    > worse failure than a missed blackout window: *one costs a trade, the other stops trading
    > with nothing specified to restart it.*

    `T-0045` P2 put the same distinction in the registry citation — *"Read literally, the former
    citation would arm an indefinite disable on every CPI — it must not."*
    """
    event = _one(name, "high")
    assert (event.exceptional_class is not None) is exceptional, (
        f"{name}: exceptional_class={event.exceptional_class!r}, expected exceptional={exceptional}"
    )


def test_the_exceptional_list_is_a_STRICT_SUBSET_of_the_force_include_list():
    """If they were ever the same list, every force-included event would arm the indefinite
    disable — and nothing in either name would say so."""
    from app.services.rules.gate_015_classifier import (
        EXCEPTIONAL_CLASS_BY_NAME, FORCE_INCLUDE_BY_NAME,
    )

    assert set(EXCEPTIONAL_CLASS_BY_NAME) < set(FORCE_INCLUDE_BY_NAME), (
        "THE EXCEPTIONAL LIST HAS WIDENED ONTO THE INDEFINITE-DISABLE PATH, AND HERE IS WHY "
        "THAT MATTERS RATHER THAN JUST THAT IT IS FORBIDDEN.\n\n"
        "GATE-014 HAS NO DEFINED RESUMPTION CONDITION. An event that arms it stops trading with "
        "nothing specified to restart it — so every name added here is a name that can halt the "
        "engine indefinitely. The two-name list is DELIBERATELY LOOSER than the eight-name "
        "force-include list: we chose the looser failure because the stricter one has no exit.\n\n"
        "If you are widening this because a rate decision ought to halt trading, you may well be "
        "right — that is question 14 to Salim, and the half he must answer is WHAT RESUMES IT, "
        "not which names are on the list. Widen it when there is a resumption, not before.\n\n"
        "An assertion that says only 'these lists must not merge' is satisfied by anyone with a "
        "reason to merge them, which is why this message is the reason and not the invariant."
    )
    assert len(EXCEPTIONAL_CLASS_BY_NAME) == 2


def test_the_gate_014_routing_choice_is_stamped_ENGINEERING_in_the_record():
    """It is OURS, it is INTERIM, and it made a gate LOOSER — all three in the telemetry.

    **A choice between two unsafe behaviours must not read as a safety improvement**, and the
    record is where round 4 will be argued from.
    """
    record = _one("FOMC Statement", "high").as_dict()
    authority = record["exceptional_class_authority"]
    assert "[ENGINEERING]" in authority and "INTERIM" in authority
    assert "LOOSER" in authority, (
        "the record does not say which DIRECTION this choice cuts — a narrowing that reads as a "
        "tightening is how a loosening gets ratified by silence"
    )
    assert "resumption" in authority and "question 14" in authority
