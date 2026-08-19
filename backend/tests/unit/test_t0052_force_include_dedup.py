"""T-0052 — B184: the force-include list carried VERB forms only, and the fix is DEDUPLICATION.

    _matches_by_name('Fed Chair Powell Testimony')  -> None    on BOTH registry lists
    _PATTERNS                                        ('testimony', 'SPEECHES')   <- knows the noun
    force_include (before)                           ('speaks','testifies','testimony',...)
                                                     <- a SECOND literal copy of the same four

> **Two places in one function encoded "the Fed Chair is speaking" and only one of them knew the
> noun form.** *Appending the missing string would have fixed this instance and left the mechanism* —
> the next vendor rendering diverges again, with no reviewer reading both branches side by side.

**`SPEECH_TOKENS` is now DERIVED from `_PATTERNS`, so the two branches cannot disagree.**

## DERIVING ALONE OVER-MATCHES, AND THE OVER-MATCH IS THE CASE THE REGISTRY FORBIDS

`FOMC Member Bowman Speaks` carries a speech token. Force-including on the token alone would catch
it — several a week, orange on Forex Factory, outside his RED filter — and
`fomc_member_speeches_force_included` is declared `false`. **So the shape is a CONJUNCTION: a
Fed-Chair marker AND a derived speech token.**
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.rules.gate_015_calendar_scope import CalendarScope
from app.services.rules.gate_015_classifier import (
    FED_CHAIR_MARKERS, FOMC_MEMBER_SPEECHES_FORCE_INCLUDED, FORCE_INCLUDE_BY_NAME, SPEECH_TOKENS,
    classify, force_include,
)

NY = ZoneInfo("America/New_York")


def _raw(name: str, impact: str, currency: str = "USD") -> dict:
    return {"id": name[:8], "event": name, "impact": impact, "currency": currency,
            "time": datetime(2026, 8, 19, 14, 0, tzinfo=NY)}


def _scoped(name: str, impact: str):
    events = CalendarScope.scope([_raw(name, impact)])
    assert len(events) == 1, f"{name} was dropped before classification"
    return events[0]


# ---------------------------------------------------------------------------
# MUST-FIRE — the ruling's own sentence, and the arm that failed before T-0052
# ---------------------------------------------------------------------------
def test_the_NOUN_form_force_includes_AND_BLOCKS_at_vendor_MEDIUM():
    """*"FOMC / Fed-Chair / rate-decision events are force-included by name even when the vendor
    rates them 'medium'"* — his card rates them VERY HIGH and the vendor does not.

    **This is the arm that failed before T-0052**, and it failed on a word the classifier already
    knew: `_PATTERNS` mapped `testimony -> SPEECHES` while `force_include` could not see it.
    """
    event = _scoped("Fed Chair Powell Testimony", "medium")
    assert event.force_included is True
    assert event.category == "SPEECHES"
    assert event.blocks is True
    assert event.block_verdict[1] == "RED_OR_FORCED_IN_SCOPE_TYPE"
    assert CalendarScope.is_red_folder_day([event]) is True, (
        "a vendor-MEDIUM Fed-Chair testimony did not make the day red — that is the ruling"
    )


@pytest.mark.parametrize("name,expected_class", [
    ("Fed Chair Powell testifies", "SPEECHES"),
    ("Fed Chair Powell speaks", "SPEECHES"),
    ("Fed Chair Powell Press Conference", "SPEECHES"),
    ("FOMC Statement", "CENTRAL_BANK"),
    ("FOMC Press Conference", "SPEECHES"),
    ("Federal Funds Rate", "CENTRAL_BANK"),
    ("Fed Interest Rate Decision", "CENTRAL_BANK"),
])
def test_NO_REGRESSION_every_previously_forced_event_still_forces(name, expected_class):
    """The derived branch is ADDITIVE. If any of these stopped forcing, the dedup replaced the
    exact-name list rather than extending it."""
    forced, match, as_type = force_include(name)
    assert forced is True, f"{name} no longer force-includes"
    assert as_type == expected_class
    assert match, "a force-include with no recorded match cannot be audited"


# ---------------------------------------------------------------------------
# MUST-MISS — the over-match that derivation alone would have caused
# ---------------------------------------------------------------------------
def test_MUST_MISS_an_FOMC_MEMBER_speech_still_does_NOT_force_include():
    """**THE CASE THAT MAKES THE CONJUNCTION NECESSARY.**

    Deriving force-inclusion from `SPEECH_TOKENS` alone would catch this: it carries `speaks`.
    Several a week, orange on Forex Factory, outside his RED filter — and
    `fomc_member_speeches_force_included` is declared `false` and goes to round 4.
    """
    assert FOMC_MEMBER_SPEECHES_FORCE_INCLUDED is False
    assert any(t in "fomc member bowman speaks" for t in SPEECH_TOKENS), (
        "the fixture no longer carries a speech token, so this must-miss proves nothing"
    )
    forced, _m, _t = force_include("FOMC Member Bowman Speaks")
    assert forced is False, (
        "an FOMC MEMBER speech was force-included — the derived branch widened past the "
        "Fed-Chair conjunction and now reaches events the exact-name list exists to exclude"
    )
    assert _scoped("FOMC Member Bowman Speaks", "medium").blocks is False


def test_MUST_MISS_an_unrelated_Testimony_without_a_Fed_Chair_marker_does_not_force():
    """The noun alone is not the ruled event."""
    assert any(t in "congressional testimony on housing finance" for t in SPEECH_TOKENS)
    forced, _m, _t = force_include("Congressional Testimony on Housing Finance")
    assert forced is False


@pytest.mark.parametrize("name", [
    "ECB Interest Rate Decision",
    "BOE Interest Rate Decision",
    "ECB President Lagarde Speaks",
])
def test_MUST_MISS_PROTECTED_ECB_and_BOE_still_do_NOT_force_include(name):
    """**PROTECTED. Do not "fix" this — the scoping is faithful, not narrow.**

    The ruling is Fed-specific by its own wording: *"FOMC / Fed-Chair / rate-decision"*, and the
    registry's force-include list names Fed instruments only. A non-US central bank's rate
    decision is not a USD event by his currency conjunct either.

    > *Review nearly filed this as a defect and read the scoping docstring first.* **An arm that
    > looks like a gap and is a ruling is exactly the thing a later seat will "correct".**
    """
    forced, _m, _t = force_include(name)
    assert forced is False, (
        f"{name} was force-included. The ruling is FED-SPECIFIC by its own wording — widening it "
        "to other central banks installs our reading as his, which is GATE-014's shape."
    )


# ---------------------------------------------------------------------------
# The deduplication itself — one source, and it stays one
# ---------------------------------------------------------------------------
def test_SPEECH_TOKENS_is_DERIVED_from_the_taxonomy_table_and_not_a_second_literal():
    """`B184`'s mechanism, closed. **The fix is that there is one list, not that it is longer.**"""
    from app.services.rules import gate_015_classifier as module

    taxonomy_speech = tuple(p for p, t in module._PATTERNS if t == "SPEECHES")
    assert SPEECH_TOKENS == taxonomy_speech, (
        "SPEECH_TOKENS no longer equals the SPEECHES rows of _PATTERNS — the two encodings have "
        "diverged again, which is the whole of B184"
    )
    assert "testimony" in SPEECH_TOKENS

    # AND THE SECOND COPY IS GONE. Asserted on the AST so a re-introduced literal tuple is caught
    # even if it happens to hold the same four strings today.
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(module.force_include))
    literal_tuples = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Tuple)
        and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.elts)
        and len(node.elts) > 1
    ]
    assert not literal_tuples, (
        "force_include contains a literal string tuple again — that is the second copy B184 is "
        "about, and it will diverge from the taxonomy table the next time a vendor renders a "
        "form only one of them knows"
    )


def test_the_derived_branch_is_ATTRIBUTABLE_in_the_record():
    """A force-include must say WHICH mechanism matched: the ruled exact name, the doctrine
    extension, or our derived Fed-Chair conjunction. **Round 4 is argued from that field.**"""
    _f, ruled, _t = force_include("Fed Chair Powell testifies")
    _f2, derived, _t2 = force_include("Fed Chair Powell Testimony")
    assert "(ruling)" in ruled
    assert "(derived_fed_chair)" in derived, (
        "the derived match is indistinguishable from a ruled one in the record — ours and his "
        "must never share a representation"
    )
    assert "FED_CHAIR" in derived


def test_the_registry_list_is_UNCHANGED_by_this_task():
    """The fix is in OUR recognition, not in HIS list. Adding 'Fed Chair Powell Testimony' to the
    registry would have been editing the ruling to match our matcher."""
    from app.services.telemetry import contract_loader as contract

    assert list(FORCE_INCLUDE_BY_NAME) == contract.rule("GATE-015")["values"]["force_include_by_name"]
    assert not any("Testimony" in n for n in FORCE_INCLUDE_BY_NAME), (
        "the noun form was appended to the registry list — that fixes the instance and leaves "
        "the mechanism, which is what B184 says not to do"
    )
    assert FED_CHAIR_MARKERS == ("fed chair",)


def test_the_taxonomy_branch_still_classifies_the_noun_independently():
    """MUST-HIT on the source of the derivation: `_PATTERNS` knew `testimony` all along, and it
    still does. If this ever fails, `SPEECH_TOKENS` derives from an empty set and every arm above
    passes vacuously."""
    assert classify("Fed Chair Powell Testimony")[0] == "SPEECHES"
    assert classify("Some Random Testimony")[0] == "SPEECHES"
    assert len(SPEECH_TOKENS) >= 4
