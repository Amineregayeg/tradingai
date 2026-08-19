"""GATE-015's name classifier — OURS, versioned, and stamped as ours on every record.

**`T-0029`-shaped refusal, discharged.** `gate_015_calendar_scope.py` reported the category half
of the filter as `NOT_EVALUABLE` because *"no feed we hold maps onto them; deriving a mapping would
install our taxonomy as his doctrine"* — round-3 question 6j. **Salim answered: six types included,
four excluded and IGNORE-AND-LOG, and FOMC-class events force-included by name.** So the taxonomy is
his; **only the recognition of it from a free-text event name is ours.**

    blocks = (impact == RED  OR  force_included)
             AND taxonomy_class IN his six
             AND currency IN scope

## WHAT IS HIS AND WHAT IS OURS, BECAUSE THEY SIT ONE FIELD APART

    HIS [RULING]     the six included types · the four excluded · IGNORE_AND_LOG for a
                     vendor-high event outside the six · force-include FOMC / Fed-Chair /
                     rate-decision BY NAME regardless of vendor impact
    OURS [ENGINEERING]  every PATTERN below · the classifier VERSION · the miss policy ·
                        `case_insensitive_substring` matching

**Finnhub's calendar event carries actual/country/estimate/event/impact/prev/time/unit and NO type
field.** There is no vendor taxonomy to read, so the six-type assignment is a name-pattern classifier
the engine owns. The pack's table is **a seed for a classifier we own, validated against the feed,
not against the pack's memory** — its own words — and where the pack asserts a Forex Factory colour
or placement, that is outside knowledge we cannot follow.

## THE SPLIT THAT `T-0035`'s SINGLE `UNKNOWN` COULD NOT CARRY

    KNOWN-OUTSIDE-THE-SIX   housing · bonds · consumer surveys · misc
                            DOES NOT BLOCK   [RULING]   -> fails toward MORE exposure, HIS call
    CLASSIFIER MISS         UNCLASSIFIED and RED and in-scope — a name the table did not
                            recognise
                            BLOCKS + classifier_miss   [ENGINEERING, OURS]
                            -> fails toward FEWER trades

> **One state cannot carry two treatments that fail in opposite directions.** *`T-0035` built a
> single `UNKNOWN` and left it non-blocking, which is right for the first case and would be a silent
> fail-open for the second* — and `T-0036` Stage B is what would enforce on it.

## `UNCLASSIFIED` IS NOT `NOT CHECKED`, AND THE ENUM HAS NO TOKEN FOR THE SECOND

`ScopedEvent` already carries `category_checked`, a boolean whose ONLY job is separating *the
classifier ran and matched nothing* from *the classifier never ran*. The ruled `taxonomy_class` enum
has `UNCLASSIFIED` and **nothing for NOT CHECKED**, so writing an unchecked event as `UNCLASSIFIED`
would delete that distinction by vocabulary while satisfying the schema.

**Adding a token to a closed enum the ruling specifies is inventing doctrine** — `GATE-014`'s shape,
and `T-0029`'s refusal. So the enum is left exactly as ruled, `taxonomy_class` is emitted **only for
events the classifier actually ran on**, and `category_checked` carries the other fact. **Question 13
to Salim.**
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from app.services.telemetry import contract_loader as contract

_VALUES: dict[str, Any] = contract.rule("GATE-015")["values"]

TaxonomyClass = Literal[
    "GROWTH", "INFLATION", "EMPLOYMENT", "CENTRAL_BANK", "BUSINESS_SURVEYS", "SPEECHES",
    "BONDS", "HOUSING", "CONSUMER_SURVEYS", "MISC", "UNCLASSIFIED",
]

#: HIS. Read from the registry, never retyped — `B167` is what a locally-typed predicate costs.
TYPES_INCLUDED: tuple[str, ...] = tuple(_VALUES["event_types_included"])
TYPES_EXCLUDED: tuple[str, ...] = tuple(_VALUES["event_types_excluded"])
FORCE_INCLUDE_BY_NAME: tuple[str, ...] = tuple(_VALUES["force_include_by_name"])
#: HIS CARD, not his ruling — the pack calls this a [DOCTRINE]-derived extension and says
#: "keep or drop". Kept, and separated so a reader can tell which list is which.
FORCE_INCLUDE_DOCTRINE_EXTENSION: tuple[str, ...] = tuple(_VALUES["force_include_doctrine_extension"])
EXCEPTIONAL_CLASS_BY_NAME: tuple[str, ...] = tuple(_VALUES["exceptional_class_by_name"])
UNCLASSIFIED_RED_POLICY: str = _VALUES["unclassified_red_policy"]
UNMATCHED_VENDOR_HIGH_POLICY: str = _VALUES["unmatched_vendor_high_policy"]
NAME_MATCH_SEMANTICS: str = _VALUES["name_match_semantics"]
FOMC_MEMBER_SPEECHES_FORCE_INCLUDED: bool = bool(_VALUES["fomc_member_speeches_force_included"])


@dataclass(frozen=True)
class DeclaredClassifier:
    """The pattern table and its version, carrying its own authority.

    Its own type rather than a shared carrier, for `gate_029_stop_flags.py:120`'s stated reason:
    these belong to the rules that carry them.

    **What is unratified is not a number — it is the CLAIM THAT THESE PATTERNS RECOGNISE HIS SIX
    TYPES.** A pattern table is a hypothesis about a vendor's free text, and it is wrong in two
    directions at once: a name it fails to match becomes a classifier miss, and a name it matches
    into the wrong type either blocks a trade it should not or clears one it should not.
    """

    name: str
    version: str
    patterns: tuple[tuple[str, str], ...]
    authority: str
    source: str
    ratified: bool = False

    def as_values(self) -> dict[str, Any]:
        return {
            self.name: self.version,
            f"{self.name}_ratified": self.ratified,
            f"{self.name}_authority": self.authority,
            f"{self.name}_source": self.source,
            f"{self.name}_pattern_count": len(self.patterns),
        }


#: OURS. Every line is engineering. Ordered — the FIRST match wins, so more specific patterns
#: precede more general ones, and that ordering is itself a choice we made rather than one he ruled.
#:
#: SEEDED from his indicator card (IM44) and EXTENDED, because the pack says the card is a seed and
#: not a closed whitelist: his own filtered result admits Retail Sales and Empire State, which the
#: card does not list. **A pattern that is on the card is not thereby ratified, and a pattern that is
#: absent from it is not thereby wrong.**
_PATTERNS: tuple[tuple[str, str], ...] = (
    # CENTRAL BANK — before SPEECHES, so a rate decision is not swallowed by "speaks".
    ("fomc", "CENTRAL_BANK"),
    ("federal funds rate", "CENTRAL_BANK"),
    ("interest rate decision", "CENTRAL_BANK"),
    ("monetary policy", "CENTRAL_BANK"),
    ("official bank rate", "CENTRAL_BANK"),
    ("main refinancing rate", "CENTRAL_BANK"),
    ("beige book", "CENTRAL_BANK"),
    # SPEECHES
    ("speaks", "SPEECHES"),
    ("testifies", "SPEECHES"),
    ("testimony", "SPEECHES"),
    ("press conference", "SPEECHES"),
    # INFLATION
    ("cpi", "INFLATION"), ("ppi", "INFLATION"),
    ("core pce", "INFLATION"), ("pce price", "INFLATION"),
    ("inflation", "INFLATION"), ("price index", "INFLATION"),
    # EMPLOYMENT
    ("non-farm", "EMPLOYMENT"), ("nonfarm", "EMPLOYMENT"),
    ("unemployment", "EMPLOYMENT"), ("jobless claims", "EMPLOYMENT"),
    ("job openings", "EMPLOYMENT"), ("employment change", "EMPLOYMENT"),
    ("payrolls", "EMPLOYMENT"), ("average hourly earnings", "EMPLOYMENT"),
    # GROWTH
    ("gdp", "GROWTH"), ("retail sales", "GROWTH"),
    ("industrial production", "GROWTH"), ("durable goods", "GROWTH"),
    ("factory orders", "GROWTH"), ("capacity utilization", "GROWTH"),
    ("trade balance", "GROWTH"),
    # BUSINESS SURVEYS
    ("pmi", "BUSINESS_SURVEYS"), ("ism ", "BUSINESS_SURVEYS"),
    ("empire state", "BUSINESS_SURVEYS"), ("philly fed", "BUSINESS_SURVEYS"),
    ("business confidence", "BUSINESS_SURVEYS"),
    # THE FOUR EXCLUDED. Classified DELIBERATELY rather than left to fall through:
    # "recognised and ruled not to block" and "unrecognised" are the two states this whole
    # module exists to keep apart, and only an explicit match can produce the first.
    ("housing", "HOUSING"), ("building permits", "HOUSING"),
    ("home sales", "HOUSING"), ("mortgage", "HOUSING"),
    ("consumer sentiment", "CONSUMER_SURVEYS"),
    ("consumer confidence", "CONSUMER_SURVEYS"),
    ("michigan", "CONSUMER_SURVEYS"),
    ("bond auction", "BONDS"), ("treasury", "BONDS"), ("bund", "BONDS"),
)

#: THE SPEECH TOKENS, DERIVED FROM THE TAXONOMY TABLE ABOVE — one source, not two.
#:
#: `B184`: these four were written TWICE — once in `_PATTERNS` as the SPEECHES rows, and once as a
#: literal tuple inside `force_include`. **Two places in one function encoded "the Fed Chair is
#: speaking" and only one of them knew the noun form**, so `FORCE_INCLUDE_BY_NAME`'s verb entries
#: ("Fed Chair Powell speaks" / "testifies") missed `Fed Chair Powell Testimony` while the taxonomy
#: branch classified it SPEECHES correctly, one function apart.
#:
#: *Appending the missing string would have fixed the instance and left the mechanism* — and the
#: next vendor rendering diverges again with no reviewer reading both branches side by side.
SPEECH_TOKENS: tuple[str, ...] = tuple(
    pattern for pattern, taxonomy in _PATTERNS if taxonomy == "SPEECHES"
)

#: [ENGINEERING] OURS. The Fed-Chair marker that NARROWS the derived force-include.
#:
#: **DERIVING FORCE-INCLUSION FROM `SPEECH_TOKENS` ALONE OVER-MATCHES, and the case is the one the
#: registry explicitly forbids:** `FOMC Member Bowman Speaks` carries a speech token and is NOT
#: force-included — several a week, orange on Forex Factory, outside his RED filter, and
#: `fomc_member_speeches_force_included` is declared `false` and goes to round 4.
#:
#: So the narrower shape is a CONJUNCTION: a Fed-Chair marker AND a speech token. That covers every
#: rendering of the ruled event (`speaks` / `testifies` / `testimony` / `press conference`) without
#: reaching a single event the exact-name list was written to exclude.
FED_CHAIR_MARKERS: tuple[str, ...] = ("fed chair",)


DECLARED_CLASSIFIER = DeclaredClassifier(
    name="calendar_classifier_version",
    version="t0047.1",
    patterns=_PATTERNS,
    authority=(
        "ENGINEERING, OURS. Salim ruled the SIX TYPES and the four exclusions; Finnhub carries no "
        "type field, so recognising a type from a free-text event name is entirely ours. The "
        "unratified claim is not a number — it is that THESE PATTERNS RECOGNISE HIS SIX TYPES."
    ),
    source=(
        "Seeded from his indicator card §9.H IM44 (image 0002) and EXTENDED, because the pack "
        "states the card is a seed and not a closed whitelist -- his own filtered result (0004) "
        "admits Retail Sales and Empire State, which the card does not list. Ordered, first match "
        "wins, CENTRAL_BANK before SPEECHES so a rate decision is not swallowed by 'speaks'. That "
        "ordering is our choice too. Cross-validation against a Forex Factory export for one month "
        "is the pack's instruction and has NOT been done -- no export is held here."
    ),
)


def _matches_by_name(name: str, patterns: tuple[str, ...]) -> str | None:
    """`case_insensitive_substring`, the declared semantics. Returns the pattern that matched.

    EXACT NAMES rather than a bare `FOMC` pattern, and the reason is in the ruling: a bare `FOMC`
    would also catch FOMC-MEMBER speeches — several a week, orange on Forex Factory, outside his
    RED filter — and would fail toward far fewer trades. `fomc_member_speeches_force_included` is
    declared `false` and goes to round 4.
    """
    lowered = name.lower()
    for pattern in patterns:
        if pattern.lower() in lowered:
            return pattern
    return None


def classify(event_name: str) -> tuple[TaxonomyClass, str | None]:
    """`(taxonomy_class, matched_pattern)`. `UNCLASSIFIED` means RAN AND MATCHED NOTHING.

    It never means "not checked" — that state has no token in the ruled enum and is carried by
    `ScopedEvent.category_checked` instead. See the module docstring.
    """
    lowered = (event_name or "").lower()
    for pattern, taxonomy in _PATTERNS:
        if pattern in lowered:
            return taxonomy, pattern  # type: ignore[return-value]
    return "UNCLASSIFIED", None


def force_include(event_name: str) -> tuple[bool, str | None, TaxonomyClass | None]:
    """Is this event force-included BY NAME, and as which type?

    **[RULING].** FOMC / Fed-Chair / rate-decision block even when the vendor rates them medium —
    his card rates FOMC talks/statements/conferences/projections VERY HIGH. A force-included event
    is REASSIGNED to `CENTRAL_BANK` (`SPEECHES` for a Fed-Chair speech) if the classifier returned
    anything else, **so that it can satisfy the type conjunct and actually block**; without the
    reassignment the force-include would be inert against its own filter.
    """
    lowered = (event_name or "").lower()
    speaks = any(token in lowered for token in SPEECH_TOKENS)

    matched = _matches_by_name(event_name, FORCE_INCLUDE_BY_NAME)
    origin = "ruling"
    if matched is None:
        matched = _matches_by_name(event_name, FORCE_INCLUDE_DOCTRINE_EXTENSION)
        origin = "doctrine_extension" if matched else origin
    if matched is None and speaks and any(m in lowered for m in FED_CHAIR_MARKERS):
        # B184. THE EXACT-NAME LIST CARRIES VERB FORMS ONLY, so a vendor rendering the same ruled
        # event as a NOUN — "Fed Chair Powell Testimony" — was not force-included, while the
        # taxonomy branch one function away classified it SPEECHES from the very same token.
        #
        # This is a CONJUNCTION and not a widening of the list: a Fed-Chair marker AND a speech
        # token drawn from `SPEECH_TOKENS`, which is now derived from the taxonomy table so the
        # two branches cannot diverge again. `FOMC Member Bowman Speaks` still does not match,
        # which is what the exact-name list exists to prevent.
        matched = f"FED_CHAIR + {next(t for t in SPEECH_TOKENS if t in lowered)}"
        origin = "derived_fed_chair"
    if matched is None:
        return False, None, None
    return True, f"{matched} ({origin})", ("SPEECHES" if speaks else "CENTRAL_BANK")


#: OURS, and it PREDATES the ruling and survives it. `T-0035` found that `finnhub.py` collapsed an
#: unreadable provider impact to "low" and the event became silently tradeable; `T-0036` made
#: UNKNOWN block. **Salim ruled about events whose impact we CAN read** — RED versus not-RED — and
#: said nothing about a vendor string we cannot parse. That case is still ours and still blocks.
#:
#: Kept as a named constant so the ruled disjunction below cannot quietly absorb it: writing
#: `impact_class == "RED_FOLDER"` alone reads as a faithful transcription of the ruling AND
#: reintroduces the fail-open, which is exactly what happened in the first draft of this module and
#: what `test_gate_015_an_unrecognised_impact_blocks_rather_than_trades` caught.
IMPACT_TREATED_AS_RED: tuple[str, ...] = ("RED_FOLDER", "UNKNOWN")


def blocks_under_ruling(
    *, impact_class: str, taxonomy: TaxonomyClass, in_currency_scope: bool, forced: bool,
) -> tuple[bool, str, bool]:
    """The ruled disjunction, and the ONE branch of it that is ours.

    Returns `(blocks, reason, classifier_miss)`.

        blocks = (impact == RED OR force_included) AND taxonomy IN his six AND currency IN scope

    **The two non-blocking exits fail in OPPOSITE directions and are reported as different
    reasons**, because a single "did not block" cannot be audited:

        RULED_EXCLUDED_TYPE   a vendor-HIGH housing print. HIS ruling. Fails toward MORE exposure.
        CLASSIFIER_MISS       RED, in scope, and the name table did not recognise it. OURS.
                              Fails toward FEWER trades, and it BLOCKS.
    """
    if not in_currency_scope:
        return False, "OUT_OF_CURRENCY_SCOPE", False

    if taxonomy == "UNCLASSIFIED":
        # [ENGINEERING] — OURS, and the pack says to put the exact question to him next round.
        # His ruling covers events KNOWN to be outside the six; a miss on a RED in-scope event is
        # more likely one OF the six than not, so the default fails toward fewer trades.
        red_or_forced = impact_class in IMPACT_TREATED_AS_RED or forced
        if red_or_forced and UNCLASSIFIED_RED_POLICY == "BLOCK_AND_LOG_CLASSIFIER_MISS":
            return True, "CLASSIFIER_MISS_BLOCKED_ENGINEERING", True
        return False, "UNCLASSIFIED_NOT_RED", red_or_forced

    if taxonomy in TYPES_EXCLUDED:
        # [RULING]. A vendor-HIGH event outside the six does NOT block — logged, never blocked.
        return False, "RULED_EXCLUDED_TYPE", False

    if taxonomy not in TYPES_INCLUDED:
        # Unreachable while the enum is the ruled eleven; kept so a future token added to the
        # taxonomy cannot silently acquire blocking behaviour by being neither in nor excluded.
        return False, "TYPE_NEITHER_INCLUDED_NOR_EXCLUDED", False

    if impact_class == "RED_FOLDER" or forced:
        return True, "RED_OR_FORCED_IN_SCOPE_TYPE", False
    if impact_class == "UNKNOWN":
        # OURS, and reported under its OWN reason rather than folded into the ruled one. An
        # unreadable vendor impact on an event that IS one of his six is not "red"; it is
        # "we cannot tell", and the declared policy blocks. Naming it separately is what lets a
        # reader count how often the mapping is failing rather than how often news is red.
        return True, "UNKNOWN_IMPACT_BLOCKED_DECLARED_POLICY", False
    return False, "NOT_RED_AND_NOT_FORCED", False
