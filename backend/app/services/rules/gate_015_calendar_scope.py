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

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Sequence

from app.services.rules.base import (
    ConditionReading, RuleImplementation, quorum_blocked,
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
    #: The category half of GATE-015's filter, when a ruling eventually supplies one.
    #: None means NOT CHECKED — never "checked and found none".
    category: str | None = None
    #: Set when the caller has classified this as one of GATE-014's exceptional classes.
    exceptional_class: str | None = None

    @property
    def blocks(self) -> bool:
        """Does this event participate in a blackout at all?

        UNKNOWN blocks under the declared policy. That is the whole reason the third state
        exists — a two-valued impact would have forced it into one of the other two, and the
        upstream code forces it into the tradeable one.
        """
        if self.impact_class == "RED_FOLDER":
            return True
        if self.impact_class == "UNKNOWN":
            return DECLARED_UNKNOWN_POLICY == "BLOCK_ON_UNKNOWN"
        return False

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
        if self.exceptional_class is not None:
            out["exceptional_class"] = self.exceptional_class
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
    def category_condition(cls) -> ConditionReading:
        """The half of the filter that does not run, reported as unreadable rather than passed.

        NOT_EVALUABLE and not FALSE: no producer maps a provider event onto his six
        categories, so "the category check ran and the event did not match" has never
        happened. Reporting it as FALSE would make an absent check read as a working one.
        """
        return ConditionReading(
            name="red_folder_category_matched",
            state="NOT_EVALUABLE",
            missing_producer=(
                "event_category — GATE-015 names six categories (growth, inflation, "
                "employment, central bank, business surveys, speeches) and no feed we hold "
                "maps onto them; deriving a mapping would install our taxonomy as his "
                "doctrine. Round-3 question 6j."
            ),
        )

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
            out.append(ScopedEvent(
                event_id=str(raw.get("id") or f"ev-{i}"),
                time_ny=to_ny(time_raw),
                name=str(raw.get("event") or raw.get("name") or ""),
                currency=currency,
                impact_raw="" if impact_raw is None else str(impact_raw),
                impact_class=DECLARED_IMPACT_MAPPING.classify(impact_raw),
            ))
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
        category = cls.category_condition()

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
            "category_filter_applied": False,
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

        # NEVER PASS, and routed through the SHARED invariant rather than asserted here.
        # The category half of a two-part filter is permanently unreadable, so a PASS would
        # claim conformance to a filter half of which has never run — the shrinking
        # denominator `base.quorum_blocked` exists to refuse.
        #
        # GATE-015's own default is IMPACT_HALF_ONLY, and it points differently from
        # GATE-013's BLOCK one file away: this rule PRODUCES a list rather than deciding a
        # trade, so its conservative outcome is to emit the list it can justify and say which
        # half produced it. Defaulting to "emit nothing" would blind GATE-012/013 entirely,
        # which is the opposite of conservative for a safety filter.
        blocked = quorum_blocked([category], default_outcome=SCOPE_BLOCKED_DEFAULT)
        assert blocked is not None, (
            "the category condition is permanently NOT_EVALUABLE, so this rule can never "
            "reach the unblocked path; if it does, the condition has been silently changed"
        )
        unreadable, default_scope = blocked
        values["scope_outcome"] = default_scope
        values["not_applicable_reason"] = (
            "GATE-015 is a TWO-PART filter and only the impact half is implemented. The "
            "category half is NOT_EVALUABLE — no feed we hold maps onto his six categories "
            "and deriving one would install our taxonomy as his doctrine (round-3 6j). The "
            "scoped list above is real and the gates consume it; this rule is not thereby "
            "satisfied."
        )
        provenance["scope_outcome"] = derived(
            f"GATE-015's own blocked-state default, {SCOPE_BLOCKED_DEFAULT}: a producer's "
            "conservative outcome is to emit the list it can justify and name the half that "
            "produced it, because emitting nothing would blind GATE-012/013 completely"
        )
        provenance["not_applicable_reason"] = derived(
            "base.quorum_blocked over GATE-015's category condition"
        )
        return cls.evaluation(
            "NOT_APPLICABLE", values=values, value_provenance=provenance
        )
