"""T-0032 — the news subsystem: GATE-012, GATE-013, GATE-015, GATE-016.

GATE-014 IS DELIBERATELY NOT IMPLEMENTED and this file guards that decision rather than
covering for it. It is the only OPEN rule of the five, its own title is "resumption condition
UNDEFINED", and `base.open_rule_requires_declared_parameter` exempts only NOT_APPLICABLE — so
any verdict-bearing GATE-014 path would force us to name a resumption authority, which is a
governance choice for the platform's owner made inside the one rule that exists to record that
nobody has made it. `test_no_numeric_volatility_test_exists_in_the_news_modules` is the
deliverable in its place.

THE FIXTURE HAZARD THIS FILE EXISTS TO AVOID
The M15 condition is arithmetically inert for any release on the 15-minute grid, and every
realistic macro release is on it. The repository's only calendar data
(`test_calendar_service.py`) is 12:30 x4 / 10:00 x4 / 03:00 x1 — three distinct times, all
grid-aligned. So the natural fixture, and the one already in the tree, exercises the M15 term
ZERO times while every assertion passes. Every off-grid case here is CONSTRUCTED for that
reason, and both arms of the `max()` are shown to win.
"""
from __future__ import annotations

import ast
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from app.services.rules.base import open_rule_requires_declared_parameter
from app.services.rules.gate_012_news_blackout import (
    POST_EVENT_COOLDOWN_MINUTES, PRE_EVENT_BLACKOUT_MINUTES, THEN_WAIT_FOR,
    PostEventBlackout, PreEventBlackout, RedFolderDayFlag,
    first_m15_close_at_or_after, first_permitted_entry_time,
)
from app.services.rules.gate_015_calendar_scope import (
    DECLARED_IMPACT_MAPPING, DECLARED_UNKNOWN_POLICY, RED_FOLDER_CATEGORIES,
    CalendarScope, ScopedEvent,
)
from app.services.telemetry import contract_loader as contract
from app.services.telemetry.ny_time import NY

#: THE POPULATION THIS TASK'S GUARDS ARE MEASURED OVER, ENUMERATED BY PATH.
#:
#: Not a glob. A directory pattern that silently stops matching is how a must-not-exist
#: assertion goes vacuous in six months — and if a later seat adds `news_volatility.py`, this
#: list either covers it or VISIBLY does not, which is the whole point.
NEWS_MODULES: tuple[str, ...] = (
    "app/services/rules/gate_012_news_blackout.py",
    "app/services/rules/gate_015_calendar_scope.py",
)

#: Identifiers that would betray an invented numeric volatility test. GATE-014: "The engine
#: MUST NOT invent a numeric volatility test; it must expose the resumption decision as an
#: explicit, logged state transition."
VOLATILITY_TERMS: tuple[str, ...] = ("atr", "stdev", "percentile", "sigma", "zscore")

BACKEND = Path(__file__).resolve().parents[2]


def ev(
    minute_time: datetime, *, impact: str = "high", currency: str = "USD", eid: str = "e1"
) -> ScopedEvent:
    """A scoped event built through GATE-015's own classifier, never hand-labelled."""
    return ScopedEvent(
        event_id=eid, time_ny=minute_time, name="CPI", currency=currency,
        impact_raw=impact, impact_class=DECLARED_IMPACT_MAPPING.classify(impact),
    )


def at(h: int, m: int, d: int = 17) -> datetime:
    return datetime(2026, 8, d, h, m, tzinfo=NY)


# ===========================================================================
# GATE-014 — THE GUARD THAT REPLACES THE IMPLEMENTATION
# ===========================================================================
def _identifiers(source: str) -> list[str]:
    """Every NAME-LIKE POSITION an AST carries — not merely every identifier node.

    ONE walker, used by the guard AND by the falsifiability tests below, so the tests
    exercise the code path the guard uses rather than a reconstruction of it. A second copy
    here would be B140's middle layer — running your own rebuild and showing it as the code's.

    THE FIRST VERSION COVERED FOUR POSITIONS AND MISSED FOUR, AND THE INJECTION TESTS COULD
    NOT SEE THE GAP — found by Review, which planted a real threshold config in a news module
    and watched all 62 tests pass:

        _VOL = {"atr_period": 14, "sigma_mult": 2.0}          <- dict STRING keys, BLIND
        _measure(series, window=cfg["atr_period"])            <- keyword AT A CALL, BLIND

    **Those are how a threshold actually gets configured** — arguably likelier than a bare
    identifier. The must-fire control that proved the instrument itself worked was the same
    smuggle with one term rewritten as a plain `Name`, which DID go red.

    WHY THE PER-TERM FIX DID NOT REACH IT, which is the transferable half: every injection
    planted its term as a `FunctionDef` name, so five injections proved the walker sees ONE
    node type five times. **The per-TERM gap was closed and the per-POSITION gap was never
    opened.** That is Review's own T-0028 narrowing one level up — `BinOp` without `Compare`,
    where the control proved the walker saw arithmetic and nothing about whether arithmetic
    covered *derives*. **A control validates the INSTRUMENT, never the VOCABULARY; an
    injection validates the POSITION, never the positions.**

    STRING CONSTANTS ARE INCLUDED ONLY IN NAME-LIKE POSITIONS — dict keys and annotations —
    and never as bare values. Taking every string would fire on the docstrings these modules
    use to FORBID the thing, which is the failure the AST approach exists to avoid.
    """
    names: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name):
            names.append(node.id)
        elif isinstance(node, ast.Attribute):
            names.append(node.attr)
        elif isinstance(node, ast.arg):
            names.append(node.arg)
            if isinstance(node.annotation, ast.Constant) and isinstance(
                node.annotation.value, str
            ):
                names.append(node.annotation.value)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.append(node.name)
        elif isinstance(node, ast.keyword) and node.arg:
            # `f(atr_period=14)` and `@configure(atr_mult=2.0)` — a keyword at a CALL is an
            # `ast.keyword`, not an `ast.arg`, and the two are easy to conflate by name.
            names.append(node.arg)
        elif isinstance(node, ast.Dict):
            # `{"atr_period": 14}` — a dict key is a name-like position. Only KEYS, never
            # values, so a message string cannot trip the guard.
            for key in node.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    names.append(key.value)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.annotation, ast.Constant) and isinstance(
                node.annotation.value, str
            ):
                names.append(node.annotation.value)
    return names


#: The POSITIONS a forbidden term can occupy, as source templates taking one `{term}`.
#:
#: PARAMETRISED SO THE NEXT NARROWING CANNOT BE INVISIBLE. Injecting five terms into one
#: position proves one node type five times; the cross product proves the walker's DOMAIN.
#: Every entry below except the first four was BLIND before Review's finding.
INJECTION_POSITIONS: dict[str, str] = {
    "function_def_name": "def compute_{term}_threshold(series):\n    return series\n",
    "plain_name": "{term}_period = 14\n",
    "attribute": "cfg.{term}_period\n",
    "def_arg": "def f({term}_period=14):\n    return {term}_period\n",
    "keyword_at_call": "compute(series, {term}_period=14)\n",
    "dict_string_key": '_VOL = {{"{term}_period": 14}}\n',
    "decorator_keyword": "@configure({term}_mult=2.0)\ndef f():\n    pass\n",
    "string_annotation": 'def f(x: "{term}_series") -> None:\n    pass\n',
}

#: POSITIONS THIS GUARD DOES **NOT** COVER, named so the table above cannot read as exhaustive.
#:
#: A table of shapes implies completeness exactly the way five terms implied it — which is the
#: mistake that produced this whole finding. These are asserted as KNOWN-UNCOVERED below, so a
#: later seat that closes one moves it up rather than discovering the hole the way Review did.
#:
#: All four are dynamic or textual: the term never appears in a name-like AST position, so no
#: identifier walker can see it. Closing them needs a different instrument, not a wider walk.
UNCOVERED_POSITIONS: dict[str, str] = {
    "getattr_string": 'v = getattr(cfg, "{term}_period")\n',
    "subscript_string": 'v = cfg["{term}_period"]\n',
    "fstring_fragment": 'v = cfg[f"{{prefix}}_{term}"]\n',
    "assembled_at_runtime": 'v = cfg["{term}"[:3] + "_period"]\n',
}


@pytest.mark.parametrize("position", sorted(INJECTION_POSITIONS))
@pytest.mark.parametrize("term", VOLATILITY_TERMS)
def test_the_volatility_walker_can_see_each_term_in_each_position(term, position):
    """FALSIFIABILITY OVER THE CROSS PRODUCT — terms x POSITIONS, not terms alone.

    The first version parametrised over terms and planted every one of them as a
    `FunctionDef` name, so it proved the walker sees one node type five times while the
    guard's real exposure is WHERE a threshold gets written. Review demonstrated the gap by
    planting a working volatility config in a news module — `{"atr_period": 14}` plus
    `window=cfg["atr_period"]` — and watching all 62 tests pass.

    So the domain is asserted rather than assumed. If a later seat narrows `_identifiers`,
    this goes red in the specific position that was narrowed instead of silently covering
    four positions and calling it five terms.
    """
    planted = INJECTION_POSITIONS[position].format(term=term)

    assert any(term in n.lower() for n in _identifiers(planted)), (
        f"the walker cannot see {term!r} in position {position!r}, so a threshold written "
        "that way would pass the guard silently — which is how it passed before"
    )


@pytest.mark.parametrize("term", VOLATILITY_TERMS)
def test_the_walker_does_not_fire_on_prose(term):
    """The must-NOT-fire arm, and it is why the guard is an AST walk rather than a grep.

    These modules discuss volatility at length in order to forbid it. A text probe would
    fail on the prose that exists to prevent the thing — and a walker that took every string
    constant would do the same, which is why string constants are admitted only in
    NAME-LIKE positions (dict keys, annotations) and never as bare values.
    """
    prose_only = (
        f'"""This module must never compute {term}."""\n'
        f'MESSAGE = "do not use {term} here"\n'
    )
    assert not any(term in n.lower() for n in _identifiers(prose_only)), (
        f"the walker fires on {term!r} in a docstring or a message string, so the guard "
        "would fail on the prose that exists to forbid the thing"
    )


@pytest.mark.parametrize("position", sorted(UNCOVERED_POSITIONS))
def test_the_guard_does_NOT_cover_these_positions_and_says_so(position):
    """THE GUARD'S BOUNDARY, ASSERTED — because a shape table reads as exhaustive.

    That is precisely how this finding happened: five terms in one position read as five
    terms covered. So the positions the walker CANNOT see are named and pinned, and the
    assertion is deliberately inverted — it goes red the day one becomes covered, which
    forces the entry to move to `INJECTION_POSITIONS` rather than the coverage silently
    growing without anyone noticing which cells changed.

    ALL FOUR ARE DYNAMIC OR TEXTUAL. `cfg["atr_period"]` as a SUBSCRIPT is a bare string
    VALUE, not a dict key or a keyword, and admitting bare strings would fire on the
    docstrings these modules use to forbid the thing. **So this is a real limit of the
    approach and not an oversight in the walk:** closing it needs a different instrument.
    """
    planted = UNCOVERED_POSITIONS[position].format(term="atr")

    assert not any("atr" in n.lower() for n in _identifiers(planted)), (
        f"{position!r} is now COVERED by the walker — good. Move it from "
        "UNCOVERED_POSITIONS to INJECTION_POSITIONS so the guard's boundary stays stated "
        "rather than drifting"
    )


def test_the_guard_catches_a_realistic_smuggled_threshold():
    """THE MUST-FIRE ARM AT MODULE SCALE, and it is Review's fixture rather than mine.

    A per-position injection proves the walker sees each position in isolation. This proves
    the GUARD — the whole assemble-and-compare path — fires on a plausible violation written
    the way someone would actually write it. It is the exact code Review planted in
    `gate_012_news_blackout.py`, where 62 tests passed and none of the 8 volatility tests
    noticed.
    """
    smuggled = (
        '_VOL = {"atr_period": 14, "sigma_mult": 2.0, "percentile_cut": 95}\n'
        "\n"
        "def resume_when_calm(series, cfg=_VOL):\n"
        '    """Decides resumption from a numeric threshold. GATE-014 forbids this."""\n'
        '    return _measure(series, window=cfg["atr_period"], mult=cfg["sigma_mult"])\n'
    )
    names = _identifiers(smuggled)
    caught = sorted({t for t in VOLATILITY_TERMS if any(t in n.lower() for n in names)})

    assert caught == ["atr", "percentile", "sigma"], (
        f"the guard must catch every forbidden term in a realistic threshold config: {names}"
    )


def test_no_numeric_volatility_test_exists_in_the_news_modules():
    """GATE-014 forbids inventing a numeric volatility test, so this asserts none exists.

    AST IDENTIFIERS, NOT TEXT. The modules' own docstrings discuss volatility at length —
    explaining what must not be built — so a text grep would fail on the prose that exists to
    prevent the thing. What a numeric test cannot avoid is NAMING something, so this walks
    names: variables, attributes, arguments, functions and classes. T-0024's precedent, whose
    AST walk caught its own module on the first run.

    THE MUST-HIT ARM IS BELOW AND IT IS NOT OPTIONAL: a must-not-exist assertion with no
    control is indistinguishable from a broken probe, which is the instrument that produced
    B141, B143 and both of this seat's narrowed arms.
    """
    found: dict[str, list[str]] = {}
    for rel in NEWS_MODULES:
        path = BACKEND / rel
        assert path.exists(), f"{rel} is in the population list and not on disk"
        names = _identifiers(path.read_text(encoding="utf-8"))
        for term in VOLATILITY_TERMS:
            hits = [n for n in names if term in n.lower()]
            if hits:
                found.setdefault(term, []).extend(f"{rel}:{n}" for n in hits)

    assert not found, (
        "GATE-014 forbids an invented numeric volatility test and one of these modules "
        f"names one: {found}"
    )


def test_the_volatility_probe_finds_those_terms_where_they_legitimately_exist():
    """THE MUST-HIT ARM, per-term with counts, in the same suite as the must-miss.

    Without this, `test_no_numeric_volatility_test_exists_in_the_news_modules` passes
    identically whether the modules are clean or the walker is broken. The terms below DO
    occur elsewhere in the tree — that is what proves the instrument can see them.

    A UNION WOULD HIDE WHICH TERM FOUND WHAT, so the counts are per-term and asserted
    individually. "0 across five terms" and "0 for four terms and the fifth never probed"
    are different claims.
    """
    corpus = [p for p in (BACKEND / "app").rglob("*.py")]
    assert len(corpus) > 50, "the control corpus itself must be non-trivial"

    per_term: dict[str, int] = {}
    for term in VOLATILITY_TERMS:
        n = 0
        for path in corpus:
            if str(path.relative_to(BACKEND)).replace("\\", "/") in NEWS_MODULES:
                continue
            try:
                names = _identifiers(path.read_text(encoding="utf-8"))
            except SyntaxError:                      # pragma: no cover - defensive
                continue
            n += sum(1 for name in names if term in name.lower())
        per_term[term] = n

    # MEASURED, AND THE RESULT LIMITS THE GUARD ABOVE RATHER THAN ENDORSING IT.
    #
    # Only `atr` occurs as an IDENTIFIER anywhere else in the tree. A text grep finds
    # "percentile" in `ict/detector.py` and `consolidation.py`, but both occurrences are
    # PROSE — so as an AST identifier it is zero, and my first version of this arm asserted
    # it was positive and went red. That failure is the arm working.
    #
    # SO THE GUARD IS FALSIFIABLE FOR ONE TERM OF FIVE, AND THIS SAYS SO OUT LOUD rather
    # than letting "0 across five terms" imply five-term coverage. For the other four, the
    # must-miss assertion cannot currently distinguish "the modules are clean" from "the
    # walker cannot see this term" — nothing in the repo exercises them.
    assert per_term["atr"] > 0, (
        f"THE ONLY LIVE CONTROL ARM IS DEAD — the walker has stopped seeing identifiers and "
        f"the must-miss assertion above is now vacuous without changing colour: {per_term}"
    )
    uncontrolled = sorted(t for t in VOLATILITY_TERMS if per_term[t] == 0)
    assert uncontrolled == ["percentile", "sigma", "stdev", "zscore"], (
        "the set of forbidden terms with NO must-hit arm has changed. If a term gained one, "
        "the guard got stronger and this list should shrink. If a term LOST one, the guard "
        f"got weaker silently. Either way it is a deliberate update: {per_term}"
    )


def test_gate_014_is_open_and_unimplemented_and_that_is_the_reason():
    """The disposition, pinned so it is not quietly reversed by a later seat.

    C-05 IS THE MECHANISM, not a preference: `open_rule_requires_declared_parameter` exempts
    only NOT_APPLICABLE, so every verdict-bearing GATE-014 path must name a declared
    parameter — and the only candidate is the resumption AUTHORITY, a governance choice for
    the platform's owner, declared inside the rule that exists to record that nobody has made
    it.
    """
    from app.services.rules.base import implemented_ids

    assert contract.is_open("GATE-014")
    assert contract.rule("GATE-014").get("values") in (None, {})
    assert "GATE-014" not in implemented_ids(), (
        "GATE-014 is OPEN with no values and its resumption condition is undefined; "
        "implementing it would invent doctrine the registry says does not exist"
    )
    # The four that ARE built.
    for rule_id in ("GATE-012", "GATE-013", "GATE-015", "GATE-016"):
        assert rule_id in implemented_ids()


# ===========================================================================
# criterion 4 — the constants are HIS. Read, never retyped, never re-declared as ours.
# ===========================================================================
def test_the_constants_are_read_from_the_registry_and_not_retyped():
    """This inverts the habit T-0028 built, and this seat is the one likely to get it wrong.

    There every percentage was self-labelled provisional and had to be declared as OURS.
    Here GATE-012's notes record the constants as "trader-authorised engine constants",
    shipped with "For implementation purposes, use the following deterministic rule". So the
    tell is: a number with a registry `values` entry is HIS.
    """
    assert PRE_EVENT_BLACKOUT_MINUTES == (
        contract.rule("GATE-012")["values"]["pre_event_blackout_minutes"]
    )
    assert POST_EVENT_COOLDOWN_MINUTES == (
        contract.rule("GATE-013")["values"]["post_event_cooldown_minutes"]
    )
    assert THEN_WAIT_FOR == contract.rule("GATE-013")["values"]["then_wait_for"]


def test_his_constants_are_never_stamped_as_ours():
    """A `_ratified: False` on one of his numbers would misattribute his decision to us."""
    ev_pre = PreEventBlackout.evaluate(at(9, 0), [])
    ev_post = PostEventBlackout.evaluate(at(9, 0), [])
    for record in (ev_pre.values, ev_post.values):
        # `for key in record` passes trivially on an empty record. Review measured 8 and 12
        # keys, so the loop has a real denominator TODAY — this makes it true by
        # construction rather than by today's shape.
        assert record, "an empty record would satisfy the loop below vacuously"
        for key in record:
            assert not key.endswith("_ratified"), (
                f"{key} stamps a ratification flag on a news constant — these are HIS, "
                "authorised in writing, and re-declaring them as ours inverts criterion 4"
            )
    assert ev_pre.value_provenance["pre_event_blackout_minutes"]["source"] == (
        "REGISTRY_CONSTANT"
    )
    assert ev_post.value_provenance["post_event_cooldown_minutes"]["source"] == (
        "REGISTRY_CONSTANT"
    )


# ===========================================================================
# GATE-015 — the producer, its UNKNOWN state, and the half that is not built
# ===========================================================================
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("high", "RED_FOLDER"), ("3", "RED_FOLDER"),
        ("medium", "NOT_RED_FOLDER"), ("2", "NOT_RED_FOLDER"),
        ("low", "NOT_RED_FOLDER"), ("1", "NOT_RED_FOLDER"),
        ("tier-1", "UNKNOWN"), ("", "UNKNOWN"), (None, "UNKNOWN"),
    ],
)
def test_an_unrecognised_impact_is_unknown_and_never_tradeable(raw, expected):
    """B126's fix. `finnhub.py` defaults a missing field AND an unrecognised value to "low",
    and ":188" then skips anything that is not "high" — so an event we could not classify is
    treated as harmless and the trade is TAKEN. Three states, not two."""
    assert DECLARED_IMPACT_MAPPING.classify(raw) == expected


def test_an_unknown_event_blocks_rather_than_trades():
    """The direction the default fails in, which is the round-2 package's hard rule 5."""
    assert DECLARED_UNKNOWN_POLICY == "BLOCK_ON_UNKNOWN"
    unknown = ev(at(9, 0), impact="tier-1")
    assert unknown.impact_class == "UNKNOWN"
    assert unknown.blocks is True
    assert ev(at(9, 0), impact="low").blocks is False
    assert ev(at(9, 0), impact="high").blocks is True


def test_the_scope_reads_the_raw_value_and_not_the_normalised_one():
    """So this rule's verdict cannot inherit the upstream fail-open.

    An event whose impact `finnhub.py` had already collapsed to "low" would arrive
    indistinguishable from a genuine low-impact event; taking the provider payload keeps the
    two apart.
    """
    scoped = CalendarScope.scope([
        {"time": at(9, 0), "currency": "USD", "event": "CPI", "impact": "tier-1"},
    ])
    assert [e.impact_raw for e in scoped] == ["tier-1"]
    assert [e.impact_class for e in scoped] == ["UNKNOWN"]


def test_events_outside_the_currency_set_are_dropped_and_counted():
    scoped = CalendarScope.scope([
        {"time": at(9, 0), "currency": "USD", "event": "CPI", "impact": "high"},
        {"time": at(9, 0), "currency": "JPY", "event": "BoJ", "impact": "high"},
    ])
    assert [e.currency for e in scoped] == ["USD"]
    record = CalendarScope.evaluate([
        {"time": at(9, 0), "currency": "USD", "event": "CPI", "impact": "high"},
        {"time": at(9, 0), "currency": "JPY", "event": "BoJ", "impact": "high"},
    ])
    assert record.values["events_dropped_out_of_scope"] == 1
    assert record.values["currency_set"] == ["USD"]
    assert record.values["confluence_enabled"] is False


def test_the_optional_confluence_ships_off_and_is_recorded_either_way():
    """"USD is enough however for extra confluence i can use EUR, GBP and USD" — optional by
    his own words, so it ships off and the record says which set was used."""
    assert CalendarScope.currency_set() == ("USD",)
    assert set(CalendarScope.currency_set(confluence=True)) == {"USD", "EUR", "GBP"}


def test_gate_015_never_reports_pass_while_the_category_half_is_unbuilt():
    """Half a two-part filter is not the filter. A PASS would claim conformance to a filter
    half of which has never run."""
    record = CalendarScope.evaluate([
        {"time": at(9, 0), "currency": "USD", "event": "CPI", "impact": "high"},
    ])
    assert record.verdict == "NOT_APPLICABLE"
    assert record.values["category_filter_applied"] is False
    assert record.values["conditions"]["red_folder_category_matched"] == "NOT_EVALUABLE"
    assert "6j" in record.values["unreadable_conditions"]["red_folder_category_matched"]
    assert list(RED_FOLDER_CATEGORIES) == record.values["red_folder_categories_declared"]


def test_the_provider_and_raw_impact_are_on_every_scoped_event():
    """So a later switch of feed can be reinterpreted from stored telemetry rather than
    re-derived — and a calendar we no longer have access to cannot be re-fetched at all."""
    [e] = CalendarScope.scope([
        {"time": at(9, 0), "currency": "USD", "event": "CPI", "impact": "3"},
    ])
    d = e.as_dict()
    assert d["provider"] == "finnhub" and d["impact_raw"] == "3"
    assert d["category_checked"] is False


# ===========================================================================
# GATE-012 — 15 minutes before, NEW ENTRIES ONLY
# ===========================================================================
def test_a_new_entry_is_blocked_inside_the_fifteen_minutes_before_a_release():
    events = [ev(at(9, 0))]
    assert PreEventBlackout.decide(at(8, 45), events).decision == "BLOCK"
    assert PreEventBlackout.decide(at(8, 59), events).decision == "BLOCK"
    assert PreEventBlackout.decide(at(8, 44), events).decision == "ALLOW"


def test_the_pre_window_is_closed_at_the_start_and_open_at_the_release():
    """At the release instant GATE-013 takes over. A moment owned by both would be reported
    under whichever rule happened to be checked first."""
    events = [ev(at(9, 0))]
    assert PreEventBlackout.decide(at(8, 45), events).decision == "BLOCK"
    assert PreEventBlackout.decide(at(9, 0), events).decision == "ALLOW"
    assert PostEventBlackout.decide(at(9, 0), events).decision == "BLOCK"


def test_a_non_blocking_event_does_not_black_out_anything():
    assert PreEventBlackout.decide(at(8, 50), [ev(at(9, 0), impact="low")]).decision == (
        "ALLOW"
    )


def test_the_blackout_never_blocks_management_of_an_open_position():
    """GATE-012's final sentence, in the tail where `| head` cuts it: "The rule addresses new
    entries only; it says nothing about positions already open."

    A blackout that froze management would strand a live position through exactly the
    volatility the rule exists to avoid. Asserted on EVERY blocking path, not just one.
    """
    events = [ev(at(9, 0))]
    blocking = [
        PreEventBlackout.decide(at(8, 50), events),
        PostEventBlackout.decide(at(9, 10), events),
    ]
    assert all(d.decision == "BLOCK" for d in blocking), "vacuous otherwise"
    for d in blocking:
        assert d.blocks_new_entries is True
        assert d.blocks_management is False
        assert d.as_dict()["applies_to"] == "NEW_ENTRIES_ONLY"


# ===========================================================================
# GATE-013 — BOTH terms of the max(), and the off-grid case is CONSTRUCTED
# ===========================================================================
def test_the_m15_term_binds_on_an_off_grid_release():
    """THE CRITERION THIS TASK LIVES OR DIES ON.

    08:31 + 30 = 09:01, and the first M15 candle completing at or after 09:01 closes at
    09:15. The two terms differ by 14 minutes. CONSTRUCTED, because no fixture in this
    repository can supply one: the only calendar data present is 12:30 / 10:00 / 03:00, all
    on the grid.
    """
    permitted, cooldown_end, m15_close, _ = first_permitted_entry_time(at(8, 31))

    assert cooldown_end == at(9, 1)
    assert m15_close == at(9, 15)
    assert permitted == at(9, 15)
    assert permitted > cooldown_end, "the M15 term must be the one that bound"
    assert (permitted - cooldown_end) == timedelta(minutes=14)


def test_on_a_grid_release_the_two_terms_COINCIDE_rather_than_one_winning():
    """~~THE CONVERSE~~ — STRUCK. There is no converse, and claiming one was the defect.

    This test asserted `permitted == cooldown_end` and called it *"the 30 minutes must be
    the term that bound"*. On a grid release the two terms are EQUAL, so
    `permitted == m15_close` is equally true: **the assertion named a winner where there is
    no contest.** Found by Review, which deleted the `max()` entirely and watched all 44
    tests pass — including the one whose message read *"both arms must win somewhere or
    max() is untested"*.
    """
    permitted, cooldown_end, m15_close, _ = first_permitted_entry_time(at(8, 30))

    assert cooldown_end == m15_close == at(9, 0), "a grid release makes the terms COINCIDE"
    assert permitted == cooldown_end and permitted == m15_close, (
        "both equalities hold, which is why 'the 30 minutes bound' was never a finding"
    )


def test_the_permitted_time_IS_the_m15_close_and_the_cooldown_is_a_floor_it_cannot_undercut():
    """THE HONEST PROPERTY, replacing a `max()` whose first argument was unreachable.

    `first_m15_close_at_or_after(moment)` returns `>= moment` on ALL THREE of its paths and
    is called with `moment = cooldown_end`, so `m15_close >= cooldown_end` always. The
    `max()` the registry's prose implies could never select its first argument, and the
    Manager ruled it out: a `max()` over a comparison true by construction is noise, and its
    own criterion — *both arms must win once* — was unsatisfiable.

    MEASURED over 180 release times (60 minutes x 3 second-offsets): the M15 term strictly
    wins 176, the two COINCIDE 4, the cooldown term strictly wins ZERO. So `56 / 4` was the
    right pair of counts under the wrong label — strict wins and COINCIDENCES, not two arms
    winning.

    What replaces it is falsifiable: the permitted time IS the M15 close, and the cooldown is
    a floor the ratchet can never fall below.
    """
    for minute in range(60):
        for second in (0, 17, 59):
            moment = at(8, minute).replace(second=second)
            close, _ = first_m15_close_at_or_after(moment)
            assert close >= moment, (
                "the M15 lookup is no longer monotone in its argument, so max() has become "
                "load-bearing on a path nothing exercises — re-read this whole test"
            )

    strict_m15 = coincide = below_floor = 0
    for minute in range(60):
        permitted, cooldown_end, m15_close, _ = first_permitted_entry_time(at(8, minute))
        # THE PROPERTY, on every release minute: the answer IS the M15 close.
        assert permitted == m15_close
        if m15_close > cooldown_end:
            strict_m15 += 1
        elif m15_close == cooldown_end:
            coincide += 1
        else:                                        # pragma: no cover - unreachable today
            below_floor += 1

    assert (strict_m15, coincide, below_floor) == (56, 4, 0), (
        "56 STRICT WINS and 4 COINCIDENCES — not 'both arms winning'. A non-zero third "
        "count means the ratchet has fallen below its floor and the whole reading is wrong"
    )


def test_the_m15_close_is_measured_from_the_cooldown_end_not_from_the_release():
    """THE CHANGE THAT WOULD MAKE `max()` LOAD-BEARING, pinned before it happens.

    *"The first M15 close after the event"* is a plausible misreading of GATE-013, and under
    it the M15 close could land BEFORE `release + 30` — at which point `max()` starts
    deciding on a path nothing has ever exercised. Same shape as T-0025's 4R row going live
    the moment T-0029 landed.

    So the call site's argument is pinned. If a later task re-anchors it to the release, this
    goes red and the seat is sent to the test above rather than discovering it in production.
    """
    release = at(8, 31)
    _, cooldown_end, m15_close, _ = first_permitted_entry_time(release)

    from_cooldown, _ = first_m15_close_at_or_after(cooldown_end)
    from_release, _ = first_m15_close_at_or_after(release)

    assert m15_close == from_cooldown == at(9, 15)
    assert from_release == at(8, 45), "the misreading would permit entry 30 minutes early"
    assert from_release < cooldown_end, (
        "and it lands BEFORE the cooldown ends, which is exactly when max() would start to "
        "decide — the reason this rule keeps max() rather than returning m15_close"
    )


def test_a_new_entry_is_blocked_until_the_first_permitted_time():
    events = [ev(at(8, 31))]
    assert PostEventBlackout.decide(at(9, 5), events).decision == "BLOCK"
    assert PostEventBlackout.decide(at(9, 14), events).decision == "BLOCK", (
        "past release+30 but before the M15 close — this is the minute the M15 term earns"
    )
    assert PostEventBlackout.decide(at(9, 15), events).decision == "ALLOW"


def test_the_record_carries_both_terms_and_says_which_one_bound():
    """A record carrying the `max()` alone cannot show which term won, and the failure mode
    of this rule is one term silently never winning."""
    record = PostEventBlackout.evaluate(at(9, 5), [ev(at(8, 31))])

    assert record.values["cooldown_end"] and record.values["m15_close"]
    assert record.values["m15_term_bound"] is True

    # The grid case, evaluated INSIDE its window (release 08:30 permits at 09:00, so 09:05
    # is already allowed and an ALLOW record carries no timing fields — which is itself the
    # right shape, and my first version of this test asserted against an ALLOW by mistake).
    grid = PostEventBlackout.evaluate(at(8, 45), [ev(at(8, 30))])
    assert grid.values["decision"] == "BLOCK"
    assert grid.values["m15_term_bound"] is False


def test_an_observed_m15_series_beats_the_scheduled_grid_and_says_so():
    """A halt or a data gap means the grid says a candle closed and none did. The observed
    series is the only thing that knows, so its basis is recorded rather than assumed."""
    permitted, _, m15_close, basis = first_permitted_entry_time(
        at(8, 31), m15_closes=[at(9, 30), at(9, 45)]
    )
    assert basis == "OBSERVED_M15_SERIES"
    assert m15_close == at(9, 30) and permitted == at(9, 30)

    _, _, _, fallback = first_permitted_entry_time(at(8, 31))
    assert fallback == "SCHEDULED_M15_GRID"


def test_the_unread_m15_series_is_reported_as_not_read_never_not_evaluable():
    """`15m` is a real timeframe with a producer, so "nobody built this" would be false.
    NOT_READ names the producer that EXISTS and was not called."""
    record = PostEventBlackout.evaluate(at(9, 5), [ev(at(8, 31))])

    assert record.values["conditions"]["m15_series_read"] == "NOT_READ"
    assert "aggregator" in record.values["unreadable_conditions"]["m15_series_read"]

    read = PostEventBlackout.evaluate(
        at(9, 5), [ev(at(8, 31))], m15_closes=[at(9, 15)]
    )
    assert read.values["conditions"]["m15_series_read"] == "TRUE"


def test_the_not_applicable_verdict_OVERLOADS_no_news_with_blocking_news():
    """REVIEW'S FINDING 3, pinned as a property rather than left for whoever wires this up.

    Routing an unreadable condition through `quorum_blocked` is the house convention and six
    other rule modules do the same. **What is different here is that the exception has become
    the only state:** no production path supplies an M15 series, so `NOT_APPLICABLE` is the
    sole verdict `GATE-013` will ever emit in deployment.

    The consequence is a collision, and it is total:

        no events at all, no series          NOT_APPLICABLE   decision ALLOW
        inside the post-window, no series    NOT_APPLICABLE   decision BLOCK

    **Same verdict, opposite behaviour.** Anything reading verdicts cannot separate "no news"
    from "news, inside the window, blocking" — so the blocking outcome exists only in
    `decision` / `news_window_outcome`, and `news_window_outcome` has ZERO readers outside
    the emitting module. Harmless while nothing under `live/` imports this; a trap for the
    seat that wires it.

    THE STRICTNESS IS NOT THE DEFECT AND IS NOT CHANGED. The grid can only permit entry
    EARLIER than the truth, so BLOCK is the right default and refusing to assert an
    unverified window is right. What needed narrowing was the CLAIM, and this is it.
    """
    quiet = PostEventBlackout.evaluate(at(9, 0), [])
    blocking = PostEventBlackout.evaluate(at(9, 5), [ev(at(8, 31))])

    assert quiet.verdict == blocking.verdict == "NOT_APPLICABLE"
    assert quiet.values["decision"] == "ALLOW"
    assert blocking.values["decision"] == "BLOCK"
    assert blocking.values["news_window_outcome"] == "BLOCK"

    # And FAIL is reachable ONLY when an observed series is supplied — which production never
    # does. "Effective" and "effective in the fixtures" are different counts (B111's family).
    with_series = PostEventBlackout.evaluate(
        at(9, 5), [ev(at(8, 31))], m15_closes=[at(9, 15)]
    )
    assert with_series.verdict == "FAIL"


def test_first_m15_close_is_not_a_resampler():
    """It computes the SCHEDULE, which is what M15 denotes, and labels itself as such — it
    does not build an M15 candle out of smaller ones."""
    assert first_m15_close_at_or_after(at(9, 0)) == (at(9, 0), "SCHEDULED_M15_GRID")
    assert first_m15_close_at_or_after(at(9, 1)) == (at(9, 15), "SCHEDULED_M15_GRID")
    assert first_m15_close_at_or_after(at(9, 46)) == (at(10, 0), "SCHEDULED_M15_GRID")


# ===========================================================================
# GATE-016 — recorded, gating NOTHING
# ===========================================================================
def test_the_red_folder_day_flag_is_recorded():
    """CONSTRUCTION, not preservation: before this task `is_red_folder_day` had ZERO
    occurrences outside `telemetry/contract/`, as did the whole `news_context` block."""
    events = [ev(at(9, 0))]
    assert RedFolderDayFlag.is_red_folder_day(events, date(2026, 8, 17)) is True
    assert RedFolderDayFlag.is_red_folder_day(events, date(2026, 8, 18)) is False


def test_the_red_folder_day_flag_gates_nothing():
    """"Undefined until ruled." Deciding anything from it would be picking between the DAY
    and MINUTES readings, which is Salim's call (6i)."""
    record = RedFolderDayFlag.evaluate([ev(at(9, 0))], date(2026, 8, 17))

    assert record.verdict == "NOT_APPLICABLE"
    assert record.values["is_red_folder_day"] is True
    assert record.values["gates_anything"] is False

    # And the windows decide identically whether or not it is a red-folder day: the flag is
    # not an input to either gate. A shared verdict would be the collapse the rule forbids.
    events = [ev(at(9, 0))]
    assert PreEventBlackout.decide(at(8, 30), events).decision == "ALLOW"
    assert PreEventBlackout.decide(at(8, 50), events).decision == "BLOCK"


def test_risk_pct_is_recorded_beside_the_flag_when_supplied():
    """Per GATE-016's `inputs`, so a later ruling for reduced size on red-folder days can be
    applied to stored history rather than re-derived."""
    record = RedFolderDayFlag.evaluate(
        [ev(at(9, 0))], date(2026, 8, 17), risk_pct=0.0125
    )
    assert record.values["risk_pct"] == 0.0125


# ===========================================================================
# house invariants
# ===========================================================================
def test_every_value_names_where_it_came_from():
    records = [
        CalendarScope.evaluate([
            {"time": at(9, 0), "currency": "USD", "event": "CPI", "impact": "high"}
        ]),
        PreEventBlackout.evaluate(at(8, 50), [ev(at(9, 0))]),
        PostEventBlackout.evaluate(at(9, 5), [ev(at(8, 31))]),
        RedFolderDayFlag.evaluate([ev(at(9, 0))], date(2026, 8, 17)),
    ]
    for record in records:
        missing = set(record.values) - set(record.value_provenance)
        assert not missing, f"{record.rule_id} has unbound values keys: {missing}"


def test_no_open_rule_reaches_a_verdict_without_a_declared_parameter():
    """C-05, applied to every record this task emits. The four built rules are READY, so
    this returns None for all of them — and it is the same check that makes GATE-014
    unimplementable without inventing a governance decision."""
    for record in (
        CalendarScope.evaluate([]),
        PreEventBlackout.evaluate(at(9, 0), []),
        PostEventBlackout.evaluate(at(9, 0), []),
        RedFolderDayFlag.evaluate([], date(2026, 8, 17)),
    ):
        assert open_rule_requires_declared_parameter(record) is None


def test_nothing_under_live_imports_the_news_rules():
    """Criterion 12, stated NARROWLY per B142: the bare form of this claim has been true per
    task and false of the architecture, because `live/shadow.py` imports eleven rule modules.

    The must-hit arm is what makes the zeros meaningful — without it, a wrong path returns
    zero for everything and reads exactly like a clean result.
    """
    live = BACKEND / "app" / "services" / "live"
    assert live.is_dir(), "wrong path — the must-hit arm below would be meaningless"
    text = "\n".join(p.read_text(encoding="utf-8") for p in live.rglob("*.py"))

    for module in ("gate_012_news_blackout", "gate_015_calendar_scope"):
        assert module not in text
    # MUST-HIT: live/ genuinely does import rule modules, so a zero above is a fact about
    # these two rather than about the path.
    assert "prim_003_liquidity" in text
    assert "zzz_T0032_absent" not in text


def test_the_pre_contract_news_branch_is_characterised_and_not_adopted():
    """B125: `engine.py` carries a dead branch whose alert says "trading suspended" while
    nothing sets the key and nothing blocks. No rule authorises it, so adopting its semantics
    would install our blackout as Salim's — T-0029's refusal.

    Populate `news_blackout` and enforce the block in the SAME change, or neither. This task
    does neither, and the branch is left standing as the only evidence of what the
    pre-contract system intended.
    """
    engine = (BACKEND / "app" / "services" / "decision" / "engine.py")
    if not engine.exists():                          # pragma: no cover - path guard
        pytest.skip("decision/engine.py not present")
    text = engine.read_text(encoding="utf-8")
    assert "news_blackout" in text, "must-hit: the dead branch is still there"
    for module in ("gate_012_news_blackout", "gate_015_calendar_scope"):
        assert module not in text, "the news rules must not be wired into the live engine"
