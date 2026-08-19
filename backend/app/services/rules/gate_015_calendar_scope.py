"""GATE-015 — which calendar events the news gates are allowed to see.

    "The calendar filter is Forex Factory RED FOLDERS ONLY — 'the highest impactful data…
    growth, inflation, employment, central bank, business surveys and speeches for the
    currencies'. Currency selection: for FX, the traded pair's own currencies; for crypto,
    'USD is enough however for extra confluence i can use EUR, GBP and USD'. The calendar's
    timezone must be set to New York local so calendar timestamps and chart timestamps
    match."

    output: "The event list that GATE-012/013/014 consume."

## THIS IS THE PRODUCER, SO ITS FAILURES ARE THE OTHER THREE RULES' FAILURES

GATE-012, GATE-013 and GATE-014 all decide from the list this rule emits. An event this rule
drops cannot be blacked out by any of them, and the drop is silent — the downstream record
shows a clean scan of an empty window, which is this project's signature failure wearing a
calendar.

## THE FILTER IS TWO-PART AND ONLY ONE PART IS BUILDABLE TODAY

    what the rule asks    red-folder impact  AND  one of six NAMED CATEGORIES
                          (growth · inflation · employment · central bank ·
                           business surveys · speeches)
    what is buildable     the impact half only

**THE CATEGORY HALF IS UNIMPLEMENTED AND THAT IS A REFUSAL, NOT AN OMISSION.** Finnhub's
schema carries no category taxonomy that maps onto his six, and inventing one would install
our taxonomy as his doctrine. Measured before deciding, arm stated (`backend/`, `*.py` +
`*.json`): every one of the six category terms appears ONLY in `RULE_REGISTRY.json` — the
doctrine — and in zero code paths; `fomc` and `rate decision` are absent even from the
registry, so the doctrine names the categories generically and never names an instrument.
Filed for Salim as round-3 `6j`. **`COVERAGE_NOTE` says so, and this rule must NOT be read as
fully satisfied: half a two-part filter is not the filter.**

## THE DEFAULT USED TO FAIL OPEN, IN A SAFETY FILTER — AND THIS RULE DOES NOT INHERIT IT

`app/services/calendar/finnhub.py` normalises impact with a DOUBLE fall-through to `"low"`:
`:262` defaults a missing field, `:263` defaults an unrecognised value, and `:188` then skips
anything that is not `"high"`. **So an event the provider labelled in a way we do not
recognise is treated as harmless and the trade is TAKEN** — the round-2 package's hard rule 5
(*watch the direction a default fails in*) violated toward acting during news. `B126`.

**This rule therefore classifies from the RAW provider value rather than from that normalised
field**, so its verdict does not inherit a fail-open that happened upstream. Unrecognised
becomes `UNKNOWN` — never `NOT_RED_FOLDER` — and how `UNKNOWN` is handled is a DECLARED,
RECORDED choice rather than an implicit default argument.

**`finnhub.py` ITSELF IS NOT CHANGED HERE.** It is live code, served hourly and to
`GET /calendar/today`, and this task is shadow-only. The upstream fail-open is escalated
rather than patched in passing.

## THE CONSTANTS HERE ARE OURS. THE ONES IN GATE-012/013 ARE HIS.

This is the opposite of the usual instruction and the two live one file apart. `GATE-015`'s
currency sets are his (`values`, read from the registry). **The provider→red-folder MAPPING is
ours**: `[ENGINEERING]`, `ratified: False`, because Finnhub's editorial `"high"` is not Forex
Factory's red folder and no ruling has ever equated them.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Literal, Sequence

from app.services.rules.base import (
    ConditionReading, RuleImplementation, quorum_blocked,
)
from app.services.rules.gate_015_classifier import (
    DECLARED_CLASSIFIER,
    EXCEPTIONAL_CLASS_BY_NAME,
    _matches_by_name,
    TYPES_EXCLUDED,
    TYPES_INCLUDED,
    UNCLASSIFIED_RED_POLICY,
    UNMATCHED_VENDOR_HIGH_POLICY,
    blocks_under_ruling,
    classify,
    force_include,
)
from app.services.telemetry import contract_loader as contract
from app.services.telemetry.ny_time import iso_ny, to_ny
from app.services.telemetry.records import RuleEvaluation, derived, from_registry

#: How this rule classifies a provider's impact value. THREE states, not two: "we could not
#: classify it" is a different market fact from "we classified it as harmless", and collapsing
#: them is what made the upstream default fail open.
ImpactClass = Literal["RED_FOLDER", "NOT_RED_FOLDER", "UNKNOWN"]

#: What to do with an event we could not classify. STATED, not buried in a default argument.
UnknownPolicy = Literal["BLOCK_ON_UNKNOWN", "TRADE_ON_UNKNOWN"]

#: GATE-015's blocked-state default, and it points DIFFERENTLY from GATE-013's one file away
#: — which is exactly why `quorum_blocked` refuses to carry a default of its own.
#:
#: This rule PRODUCES the event list rather than deciding a trade, so its conservative outcome
#: is to emit the half it can justify and say which half that was. "Emit nothing until both
#: halves work" would blind GATE-012/013 completely and turn a partial filter into no filter,
#: which is the opposite of conservative for a safety rule.
SCOPE_BLOCKED_DEFAULT = "IMPACT_HALF_ONLY"

#: GATE-015 `values`, read from the registry rather than retyped.
_VALUES: dict[str, Any] = contract.rule("GATE-015")["values"]
CRYPTO_CURRENCY_SET: tuple[str, ...] = tuple(_VALUES["crypto_currency_set"])
CRYPTO_OPTIONAL_CONFLUENCE: tuple[str, ...] = tuple(_VALUES["crypto_optional_confluence"])

#: The six categories the rule names. Listed so a record can say WHICH vocabulary was checked
#: and report that the check did not run — a rule made of a category list is defeated by a
#: category nobody enumerated, and here it is defeated by nobody enumerating any of them.
RED_FOLDER_CATEGORIES: tuple[str, ...] = (
    "growth", "inflation", "employment", "central bank", "business surveys", "speeches",
)


@dataclass(frozen=True)
class DeclaredMapping:
    """A provider→doctrine mapping that carries its own authority and unratified status.

    Its own type rather than a shared carrier, matching `DeclaredWindow` (GATE-038),
    `DeclaredEngineering` (GATE-029) and `DeclaredPercentage` (TARGET-005): the reason is at
    `gate_029_stop_flags.py:120` — these belong to the rules that carry them.

    A MAPPING RATHER THAN A NUMBER, and that is why it needs a type of its own rather than
    reusing TARGET-005's percentage carrier: there is no value to pin and no denominator to
    declare. What is unratified is the CLAIM THAT TWO TAXONOMIES CORRESPOND.
    """

    name: str
    #: provider value (lowercased) -> our classification.
    mapping: dict[str, ImpactClass]
    provider: str
    authority: str
    source: str
    ratified: bool = False

    def classify(self, impact_raw: object) -> ImpactClass:
        """UNKNOWN for anything not explicitly mapped — including None and empty.

        `.get(key, "NOT_RED_FOLDER")` would be the upstream defect rebuilt here: an
        unrecognised value silently becoming a tradeable one.
        """
        if impact_raw is None:
            return "UNKNOWN"
        key = str(impact_raw).strip().lower()
        if not key:
            return "UNKNOWN"
        return self.mapping.get(key, "UNKNOWN")

    def as_values(self) -> dict[str, Any]:
        return {
            self.name: dict(self.mapping),
            f"{self.name}_ratified": self.ratified,
            f"{self.name}_authority": self.authority,
            f"{self.name}_provider": self.provider,
            f"{self.name}_source": self.source,
        }


#: OURS. Unratified. Finnhub's editorial "high" is not Forex Factory's red folder, and the
#: rule names Forex Factory. Every value the provider documents is mapped explicitly so that
#: an unmapped one is a real unknown rather than a gap in this table.
DECLARED_IMPACT_MAPPING = DeclaredMapping(
    name="provider_red_folder_mapping",
    mapping={
        "3": "RED_FOLDER",
        "high": "RED_FOLDER",
        "2": "NOT_RED_FOLDER",
        "medium": "NOT_RED_FOLDER",
        "1": "NOT_RED_FOLDER",
        "low": "NOT_RED_FOLDER",
    },
    provider="finnhub",
    authority="ENGINEERING",
    source=(
        "GATE-015 names FOREX FACTORY red folders. We read Finnhub, whose impact field is an "
        "editorial 1/2/3 or low/medium/high scale (app/services/calendar/finnhub.py:45). No "
        "ruling equates the two taxonomies, so treating Finnhub 'high' as a red folder is "
        "OUR claim and is carried unratified. The CATEGORY half of the filter is not mapped "
        "at all — see COVERAGE_NOTE and round-3 question 6j."
    ),
)

#: OURS, and the direction is the whole point. An event we could not classify is treated as
#: if it were a red folder, because GATE-012/013 exist to keep the engine out of exactly the
#: conditions an unclassifiable event might be. The upstream default chose the opposite and
#: that is `B126`.
DECLARED_UNKNOWN_POLICY: UnknownPolicy = "BLOCK_ON_UNKNOWN"

UNKNOWN_POLICY_SOURCE = (
    "OURS, [ENGINEERING], unratified. The doctrine never contemplates an unclassifiable "
    "event. BLOCK_ON_UNKNOWN is chosen because the round-2 package's hard rule 5 says to "
    "watch the direction a default fails in, and the news gates exist to stand aside: "
    "standing aside on an event we cannot read costs an entry, while trading through one "
    "costs the account the rule was written to protect. Recorded on every evaluation so a "
    "later ruling can reinterpret stored history rather than re-derive it."
)


@dataclass(frozen=True)
class ScopedEvent:
    """One calendar event, classified, with everything a later re-reading would need.

    `impact_raw` and `provider` are carried DELIBERATELY: the day the feed changes or the
    mapping is ratified, stored telemetry can be reinterpreted instead of re-fetched, and a
    calendar we no longer have access to cannot be re-fetched at all.
    """

    event_id: str
    time_ny: datetime
    name: str
    currency: str
    impact_raw: str
    impact_class: ImpactClass
    provider: str = DECLARED_IMPACT_MAPPING.provider
    #: The category half of GATE-015's filter. Salim RULED it in round 3 and `T-0047` built the
    #: classifier, so this is now populated on every scoped event.
    #: **`None` STILL MEANS NOT CHECKED — never "checked and found none".** That distinction has
    #: no token in the ruled `taxonomy_class` enum (`UNCLASSIFIED` means RAN AND MATCHED NOTHING),
    #: which is why this boolean-by-absence field survives the ruling rather than being folded
    #: into it. Question 13 to Salim.
    category: str | None = None
    #: Set when the caller has classified this as one of GATE-014's exceptional classes.
    exceptional_class: str | None = None
    #: [RULING] force-included BY NAME regardless of vendor impact, and which list matched.
    force_included: bool = False
    force_include_match: str | None = None
    #: [ENGINEERING, OURS] RED and in scope and the name table did not recognise it.
    classifier_miss: bool = False
    #: Which pattern recognised the type, so a wrong classification is attributable to a line.
    classifier_pattern: str | None = None

    @property
    def blocks(self) -> bool:
        """THE RULED DISJUNCTION, round 3:

            blocks = (impact == RED OR force_included) AND type IN his six AND currency IN scope

        **Before `T-0047` this was the impact half alone**, so it was wrong in BOTH directions: a
        vendor-high housing print blocked (his ruling says it must not) and a vendor-medium FOMC
        item did not (his ruling says it must). *A one-conjunct filter standing in for a
        three-conjunct one does not merely under-block; it blocks the wrong set.*

        The currency conjunct is satisfied by construction — `scope()` drops out-of-scope events
        before they become `ScopedEvent`s — and is passed explicitly anyway rather than assumed,
        because "true by construction" is a claim about a caller.
        """
        blocked, _reason, _miss = self.block_verdict
        return blocked

    @property
    def block_verdict(self) -> tuple[bool, str, bool]:
        """`(blocks, reason, classifier_miss)` — the reason is what makes a NON-block auditable.

        The two non-blocking exits fail in OPPOSITE directions and must never share a
        representation: `RULED_EXCLUDED_TYPE` is HIS ruling failing toward more exposure, and
        `CLASSIFIER_MISS_BLOCKED_ENGINEERING` is OURS failing toward fewer trades.
        """
        if self.category is None:
            # NOT CHECKED. The classifier did not run on this event, so the type conjunct cannot
            # be evaluated -- and `UNCLASSIFIED` would be a lie about it. Falls back to the
            # pre-ruling impact-only behaviour and SAYS SO in the reason.
            if self.impact_class == "RED_FOLDER":
                return True, "TYPE_NOT_CHECKED_IMPACT_ONLY", False
            if self.impact_class == "UNKNOWN":
                return (DECLARED_UNKNOWN_POLICY == "BLOCK_ON_UNKNOWN",
                        "TYPE_NOT_CHECKED_IMPACT_UNKNOWN", False)
            return False, "TYPE_NOT_CHECKED_NOT_RED", False
        return blocks_under_ruling(
            impact_class=self.impact_class,
            taxonomy=self.category,  # type: ignore[arg-type]
            in_currency_scope=True,
            forced=self.force_included,
        )

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "event_id": self.event_id,
            "event_time_ny": iso_ny(self.time_ny),
            "name": self.name,
            "currency": self.currency,
            "impact_raw": self.impact_raw,
            "impact_class": self.impact_class,
            "provider": self.provider,
            "category_checked": self.category is not None,
        }
        if self.category is not None:
            out["category"] = self.category
            out["taxonomy_class"] = self.category
        if self.exceptional_class is not None:
            out["exceptional_class"] = self.exceptional_class
            # [ENGINEERING] OURS, AND IT IS A CHOICE BETWEEN TWO UNSAFE BEHAVIOURS.
            #
            # Arming GATE-014 from the TWO-name list rather than the EIGHT-name force-include
            # list makes this gate LOOSER, not stricter: a rate decision and a Fed-Chair speech
            # no longer reach the indefinite disable. **That is the direction we chose, and we
            # chose it because the strict version fails a different way** — GATE-014 has NO
            # DEFINED RESUMPTION CONDITION, so an event reaching it stops trading with nothing
            # specified to restart it.
            #
            # The missing half is the RESUMPTION, not the list. Question 14 to Salim: does a
            # rate decision halt trading, and if so what resumes it? Until then this is INTERIM.
            out["exceptional_class_authority"] = (
                "[ENGINEERING] OURS, unratified, INTERIM. Armed from exceptional_class_by_name "
                "(2 names) and NOT from force_include_by_name (8). This makes GATE-014 LOOSER, "
                "deliberately: GATE-014 has no defined resumption, so a scheduled event reaching "
                "it stops trading with nothing specified to restart it. A trade between two "
                "unsafe behaviours, and not ours to settle — question 14, round 4."
            )
        blocked, reason, miss = self.block_verdict
        # WHAT C-14 NEEDS TO RECOMPUTE THE WINDOWS WITHOUT THE ENGINE, and to see WHY.
        out["vendor_impact_raw"] = self.impact_raw
        out["force_included"] = self.force_included
        out["blocks"] = blocked
        out["block_reason"] = reason
        out["classifier_miss"] = miss
        # THE ONE BRANCH THAT IS NOT HIS, LABELLED IN THE RECORD ITSELF rather than only in a
        # comment: T-0042's round-4 set must be able to quote what we did.
        if miss:
            out["classifier_miss_authority"] = (
                "[ENGINEERING] OURS, unratified. His ruling covers events KNOWN to be outside "
                "the six; a miss on a RED in-scope event is more likely one OF the six, so the "
                "default BLOCKS and fails toward fewer trades. Question to Salim, round 4."
            )
        if self.force_include_match is not None:
            out["force_include_match"] = self.force_include_match
        if self.classifier_pattern is not None:
            out["classifier_pattern"] = self.classifier_pattern
        return out


class CalendarScope(RuleImplementation):
    """GATE-015: the event list GATE-012/013/014 consume."""

    RULE_ID = "GATE-015"

    #: NOT DECLARED. The calendar producer EXISTS and is live — initialised at main.py:106,
    #: refreshed hourly by cron, served at GET /calendar/today (B125). These five news rules
    #: are the first cluster in this programme that are NOT blocked on a missing producer,
    #: and declaring one here would understate coverage in the opposite direction to the
    #: usual error.
    CANNOT_FIRE_WITHOUT = ()

    COVERAGE_NOTE = (
        "PARTIAL, AND THE UNBUILT HALF IS HALF THE RULE. GATE-015 is a TWO-PART filter — "
        "red-folder impact AND one of six named categories (growth, inflation, employment, "
        "central bank, business surveys, speeches). Only the IMPACT half is built. The "
        "CATEGORY half is unimplemented deliberately: Finnhub carries no taxonomy that maps "
        "onto his six, and guessing one would install our taxonomy as his doctrine. Measured "
        "— all six category terms appear only in RULE_REGISTRY.json and in zero code paths. "
        "Filed for Salim as round-3 6j. DO NOT read this rule as satisfied. Built and real: "
        "the currency set from the registry, NY-local timestamps via GATE-023, a declared "
        "provider mapping carried unratified, and a third impact state UNKNOWN that blocks "
        "rather than trades — which the upstream finnhub.py default does not do (B126). "
        "finnhub.py was NOT changed by T-0032 — that was shadow-only — and T-0035 has since "
        "closed the same fail-open AT THE SOURCE: an unrecognised or missing impact is "
        "recorded as UNKNOWN there too, with the provider's own string kept, which is what "
        "makes this rule's raw-payload input constructible at all. WIRED FOR RECORDING ONLY "
        "(T-0036 Stage A) via app/services/live/news_context.py; it enforces nothing."
    )

    @classmethod
    def currency_set(cls, *, confluence: bool = False) -> tuple[str, ...]:
        """The currencies whose events matter for our instruments.

        Our symbols are BTC/USD and ETH/USD, so the set is the crypto set. The EUR/GBP
        confluence is OPTIONAL BY HIS OWN WORDS — "USD is enough however for extra
        confluence i can use EUR, GBP and USD" — so it ships OFF and the record says which
        set was used, rather than the choice being invisible.
        """
        if confluence:
            return tuple(dict.fromkeys(CRYPTO_CURRENCY_SET + CRYPTO_OPTIONAL_CONFLUENCE))
        return CRYPTO_CURRENCY_SET

    @classmethod
    def category_condition(cls, events: Sequence[ScopedEvent] | None = None) -> ConditionReading:
        """**THE REFUSAL THIS CARRIED IS DISCHARGED, and by a ruling rather than by an edit.**

        Through `T-0046` this returned `NOT_EVALUABLE` with `missing_producer="event_category"`,
        because *"no feed we hold maps onto them; deriving a mapping would install our taxonomy
        as his doctrine"* — filed as round-3 question 6j. **He answered it:** six types included,
        four excluded and IGNORE-AND-LOG, FOMC-class force-included by name.

        So the TAXONOMY is his and only the RECOGNITION is ours, which is a different and much
        smaller claim than the one the refusal was protecting against. `T-0047` built the
        classifier and it is `DECLARED_CLASSIFIER` — versioned, unratified, stamped on every
        record.

        `events=None` is still `NOT_EVALUABLE`, and NOT because a producer is missing: it means
        nobody supplied events to check. *"No producer exists" and "you did not ask" are
        different absences and the second must not inherit the first's vocabulary.*
        """
        if events is None:
            # `unread_producer`, NOT `missing_producer`. The producer EXISTS as of T-0047; it
            # was not read because nobody supplied events. Filing "you did not ask" under
            # "no producer exists" would resurrect a refusal that a ruling discharged.
            return ConditionReading(
                name="red_folder_category_matched",
                state="NOT_READ",
                unread_producer=(
                    f"{DECLARED_CLASSIFIER.name} {DECLARED_CLASSIFIER.version} exists and was "
                    "not asked — no events were supplied to classify"
                ),
            )
        if not events:
            # ZERO EVENTS IS NOT "CLASSIFIED AND NONE MATCHED". The classifier ran on nothing, so
            # the condition did not read — reporting FALSE here would make an empty calendar
            # indistinguishable from a calendar of events none of which are his six, and those
            # are exactly the two facts GATE-012/013 need kept apart.
            # `NOT_READ`, NOT `NOT_EVALUABLE`, and the type enforces the difference: the
            # first names a producer that EXISTS and was not called, the second one that does
            # not exist. Using NOT_EVALUABLE here would re-file a discharged refusal under the
            # vocabulary of an open one — the classifier exists as of T-0047.
            return ConditionReading(
                name="red_folder_category_matched",
                state="NOT_READ",
                unread_producer=(
                    f"{DECLARED_CLASSIFIER.name} {DECLARED_CLASSIFIER.version} exists and ran on "
                    "zero events — nothing was in scope to classify"
                ),
            )
        matched = [e for e in events if e.category in TYPES_INCLUDED]
        return ConditionReading(
            name="red_folder_category_matched",
            state="TRUE" if matched else "FALSE",
        )

    @classmethod
    def is_red_folder_day(cls, events: Sequence[ScopedEvent]) -> bool:
        """`GATE-016`'s input: **∃ an event on the NY calendar day with `blocks == true`.**

        The existential is over the RULED disjunction, not over impact — which is the whole
        point of the round-3 item. **A vendor-MEDIUM FOMC item makes the day red; a vendor-HIGH
        housing print does not.** Those two rows are the entire ruling.

        The caller supplies one NY calendar day's events. This does not re-derive the day
        boundary: `GATE-016.values.day_boundary` is `America/New_York calendar day` and the
        events already carry `time_ny`, so grouping is the caller's and is asserted there.
        """
        return any(e.blocks for e in events)

    @classmethod
    def scope(
        cls,
        raw_events: Sequence[dict[str, Any]],
        *,
        confluence: bool = False,
    ) -> list[ScopedEvent]:
        """Classify and filter the provider's raw events down to the ones the gates see.

        RAW EVENTS, NOT `CalendarEvent`. The provider's own payload is taken so this rule's
        verdict does not inherit `finnhub.py`'s fail-open normalisation — an event whose
        impact that module already collapsed to "low" would arrive here indistinguishable
        from a genuine low-impact one.

        Events outside the currency set are dropped and events with no usable time are
        dropped; both are COUNTED by `evaluate` so a shrinking event list is visible rather
        than inferred.
        """
        wanted = set(cls.currency_set(confluence=confluence))
        out: list[ScopedEvent] = []
        for i, raw in enumerate(raw_events):
            time_raw = raw.get("time") or raw.get("datetime")
            if not isinstance(time_raw, datetime):
                continue
            currency = str(raw.get("currency") or "").upper()
            if currency not in wanted:
                continue
            # The RAW value, before any normalisation — `impact` first, then the
            # provider's alternate key, and NEITHER defaulted to a tradeable value.
            impact_raw = raw.get("impact")
            if impact_raw is None:
                impact_raw = raw.get("importance")
            name = str(raw.get("event") or raw.get("name") or "")
            # THE TYPE CONJUNCT, RUN HERE — so that a `ScopedEvent` built directly by any other
            # caller keeps `category is None` meaning NOT CHECKED. `UNCLASSIFIED` is a RESULT of
            # running the classifier and is never the state of not having run it.
            taxonomy, pattern = classify(name)
            forced, match, forced_as = force_include(name)
            if forced and forced_as is not None and taxonomy != forced_as:
                # [RULING] a force-included event is REASSIGNED to CENTRAL_BANK (SPEECHES for a
                # Fed-Chair speech) so it can satisfy the type conjunct. Without the
                # reassignment the force-include would be inert against its own filter.
                taxonomy = forced_as
            # GATE-014's ROUTING, and the list is deliberately NOT the force-include list.
            #
            # `exceptional_class_by_name` is TWO names (FOMC Statement / FOMC Press Conference,
            # answers Q12); `force_include_by_name` is EIGHT. Arming GATE-014 from the wider list
            # would route rate decisions and Fed-Chair speeches onto the INDEFINITE-DISABLE path
            # — and **GATE-014 has no defined resumption condition**, so a scheduled event
            # reaching it is a worse failure than a missed blackout window: one costs a trade,
            # the other stops trading with nothing specified to restart it.
            exceptional = _matches_by_name(name, EXCEPTIONAL_CLASS_BY_NAME)
            event = ScopedEvent(
                event_id=str(raw.get("id") or f"ev-{i}"),
                time_ny=to_ny(time_raw),
                name=name,
                currency=currency,
                impact_raw="" if impact_raw is None else str(impact_raw),
                impact_class=DECLARED_IMPACT_MAPPING.classify(impact_raw),
                category=taxonomy,
                classifier_pattern=pattern,
                force_included=forced,
                force_include_match=match,
                exceptional_class=exceptional,
            )
            # Computed from the finished event rather than passed in, so the flag cannot
            # disagree with the verdict it is supposed to describe.
            out.append(replace(event, classifier_miss=event.block_verdict[2]))
        return out

    @classmethod
    def declared_parameters(cls) -> dict[str, Any]:
        return {
            **DECLARED_IMPACT_MAPPING.as_values(),
            "unknown_impact_policy": DECLARED_UNKNOWN_POLICY,
            "unknown_impact_policy_ratified": False,
            "unknown_impact_policy_authority": "ENGINEERING",
            "unknown_impact_policy_source": UNKNOWN_POLICY_SOURCE,
        }

    @classmethod
    def evaluate(
        cls,
        raw_events: Sequence[dict[str, Any]],
        *,
        confluence: bool = False,
    ) -> RuleEvaluation:
        """GATE-015's telemetry: what was scoped in, what was dropped, and what was unreadable.

        ALWAYS reports the counts, including zero. A scan that scoped no events and a scan
        that had none to scope are different facts, and the downstream gates cannot tell
        them apart from an empty list.
        """
        scoped = cls.scope(raw_events, confluence=confluence)
        category = cls.category_condition(scoped)

        by_class = {k: 0 for k in ("RED_FOLDER", "NOT_RED_FOLDER", "UNKNOWN")}
        for e in scoped:
            by_class[e.impact_class] += 1

        values: dict[str, Any] = {
            "events_supplied": len(raw_events),
            "events_in_currency_set": len(scoped),
            "events_dropped_out_of_scope": len(raw_events) - len(scoped),
            "currency_set": list(cls.currency_set(confluence=confluence)),
            "confluence_enabled": confluence,
            "events_by_impact_class": by_class,
            "events_blocking": sum(1 for e in scoped if e.blocks),
            "calendar_timezone": "America/New_York",
            "red_folder_categories_declared": list(RED_FOLDER_CATEGORIES),
            # WAS `False` UNTIL T-0047, and it was the honest value then: half a two-part filter
            # is not the filter, and saying so is what kept this rule from reading as satisfied.
            "category_filter_applied": True,
            **DECLARED_CLASSIFIER.as_values(),
            "event_types_included": list(TYPES_INCLUDED),
            "event_types_excluded": list(TYPES_EXCLUDED),
            "taxonomy_counts": {
                t: sum(1 for e in scoped if e.category == t)
                for t in sorted({e.category for e in scoped if e.category is not None})
            },
            "classifier_misses": sum(1 for e in scoped if e.classifier_miss),
            "force_included_count": sum(1 for e in scoped if e.force_included),
            "is_red_folder_day": cls.is_red_folder_day(scoped),
            # THE ONE BRANCH THAT IS NOT HIS, named in the record and not only in a comment.
            "unclassified_red_policy": UNCLASSIFIED_RED_POLICY,
            "unclassified_red_policy_authority": (
                "[ENGINEERING] OURS, unratified — his ruling covers events KNOWN to be outside "
                "the six; a miss on a RED in-scope event fails toward fewer trades by our "
                "choice. Question to Salim, round 4."
            ),
            "unmatched_vendor_high_policy": UNMATCHED_VENDOR_HIGH_POLICY,
            "conditions": {category.name: category.state},
            "unreadable_conditions": {category.name: category.missing_producer},
            **cls.declared_parameters(),
        }

        provenance: dict[str, Any] = {
            "events_supplied": derived("len(raw provider payload)"),
            "events_in_currency_set": derived("events whose currency is in the declared set"),
            "events_dropped_out_of_scope": derived("events_supplied - events_in_currency_set"),
            "currency_set": from_registry("GATE-015", "values.crypto_currency_set"),
            "confluence_enabled": derived(
                "caller's choice; the optional EUR/GBP confluence ships OFF because his own "
                "words make it optional"
            ),
            "events_by_impact_class": derived(
                "provider_red_folder_mapping applied to each event's RAW impact value"
            ),
            "events_blocking": derived(
                "RED_FOLDER events, plus UNKNOWN events under unknown_impact_policy"
            ),
            "calendar_timezone": from_registry("GATE-015", "statement"),
            "red_folder_categories_declared": from_registry("GATE-015", "statement"),
            "category_filter_applied": derived(
                "structural: no producer maps provider events onto the six categories"
            ),
            "conditions": derived("GATE-015's category half, with its evaluability"),
            "unreadable_conditions": derived(
                "conditions whose state is NOT_EVALUABLE, with the missing producer named"
            ),
        }
        for key in cls.declared_parameters():
            provenance[key] = derived(f"GATE-015 declared parameter {key}")

        # T-0047's keys. Bound explicitly rather than swept in by a prefix loop: an unbound key
        # is what `test_every_value_names_where_it_came_from` exists to catch, and a loop that
        # binds "whatever I emitted" satisfies that test without anyone stating a provenance.
        provenance.update({
            "category_filter_applied": derived(
                "TRUE from T-0047 — the classifier discharges round-3 question 6j"
            ),
            "event_types_included": from_registry("GATE-015", "values.event_types_included"),
            "event_types_excluded": from_registry("GATE-015", "values.event_types_excluded"),
            "taxonomy_counts": derived(
                f"{DECLARED_CLASSIFIER.name} {DECLARED_CLASSIFIER.version} over the scoped events"
            ),
            "classifier_misses": derived(
                "RED and in scope and unrecognised — OURS, and the count is the denominator for "
                "how badly the pattern table is doing"
            ),
            "force_included_count": from_registry("GATE-015", "values.force_include_by_name"),
            "is_red_folder_day": derived(
                "GATE-016's input: EXISTS an event on the NY calendar day with blocks == true"
            ),
            "unclassified_red_policy": from_registry("GATE-015", "values.unclassified_red_policy"),
            "unclassified_red_policy_authority": derived(
                "[ENGINEERING] OURS — the one branch of the filter that is not his"
            ),
            "unmatched_vendor_high_policy": from_registry(
                "GATE-015", "values.unmatched_vendor_high_policy"
            ),
            DECLARED_CLASSIFIER.name: derived("OURS, versioned, unratified"),
            f"{DECLARED_CLASSIFIER.name}_ratified": derived(
                "the unratified claim is that THESE PATTERNS RECOGNISE HIS SIX TYPES"
            ),
            f"{DECLARED_CLASSIFIER.name}_authority": derived("ENGINEERING, ours"),
            f"{DECLARED_CLASSIFIER.name}_source": derived(
                "seeded from IM44 and extended; cross-validation against a Forex Factory export "
                "is the pack's instruction and is UNMET"
            ),
            f"{DECLARED_CLASSIFIER.name}_pattern_count": derived(
                "size of the pattern table — a denominator, published always"
            ),
        })

        # THIS ASSERTION FIRED AT T-0047, AND IT WAS RIGHT TO.
        #
        # It read: "the category condition is permanently NOT_EVALUABLE, so this rule can never
        # reach the unblocked path; if it does, the condition has been SILENTLY CHANGED." The
        # condition did change — not silently, and not by an edit: **Salim ruled question 6j in
        # round 3**, `T-0045` put the six types and the four exclusions in the registry, and
        # `T-0047` built the classifier. The guard demanded that someone look, and this is that.
        #
        # BOTH PATHS ARE NOW REACHABLE, so the assertion is replaced by handling rather than
        # deleted. `quorum_blocked` returning None means the condition READ — the rule reaches a
        # real verdict on a real two-part filter for the first time.
        blocked = quorum_blocked([category], default_outcome=SCOPE_BLOCKED_DEFAULT)
        if blocked is None:
            # The category half RAN. The filter is whole and the rule is genuinely satisfied.
            values["scope_outcome"] = "BOTH_HALVES_APPLIED"
            provenance["scope_outcome"] = derived(
                "the impact half and the category half both ran — GATE-015's two-part filter is "
                "whole as of T-0047, discharging round-3 question 6j"
            )
        else:
            unreadable, default_scope = blocked
            values["scope_outcome"] = default_scope
            values["not_applicable_reason"] = (
                "The category half did not read on this evaluation — no events were supplied to "
                "classify. THIS IS NO LONGER A PRODUCER GAP: the classifier exists as of "
                "T-0047 and is versioned and declared. The scoped list above is real and the "
                "gates consume it."
            )
        provenance["scope_outcome"] = derived(
            f"GATE-015's own blocked-state default, {SCOPE_BLOCKED_DEFAULT}: a producer's "
            "conservative outcome is to emit the list it can justify and name the half that "
            "produced it, because emitting nothing would blind GATE-012/013 completely"
        )
        provenance["not_applicable_reason"] = derived(
            "base.quorum_blocked over GATE-015's category condition"
        )
        # **GATE-015 CAN REACH A VERDICT FOR THE FIRST TIME.** It returned NOT_APPLICABLE
        # unconditionally while half its filter had no producer — the honest value then, because
        # a PASS would have claimed conformance to a filter half of which never ran.
        #
        # PASS means "the two-part filter ran and produced this list", not "the market is safe":
        # this rule PRODUCES the list GATE-012/013/014 decide from and decides nothing itself.
        # NOT_APPLICABLE survives for the case that is still real — nothing to classify.
        return cls.evaluation(
            "NOT_APPLICABLE" if blocked is not None else "PASS",
            values=values, value_provenance=provenance,
        )
