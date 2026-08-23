"""T-0069 — no SECOND blackout implementation may grow on the calendar source layer.

**`T-0066` deleted `CalendarService.is_in_blackout`** because its window was SYMMETRIC —
`abs(now - event) <= n`, one number — against a ratified window that is asymmetric and carries
TWO. No value of `n` reconciles them, so the defect was the SHAPE and rewriting it would have
produced a third statement of the news doctrine.

**THIS ARM EXISTS BECAUSE THE NAME IS THE HAZARD SURFACE, AND THAT IS NOT `B191`'S DEFECT.**
Normally you do not test that a deleted function stays deleted. Here the failure mode is
specific and it has already happened once: a seat needing a blackout check greps, finds
nothing on the calendar layer, and writes one. That is how the first symmetric implementation
arrived. `B191` says do not enumerate TOKENS when the property is structural; here the
property genuinely *is* the identifier, because the identifier is what the next seat searches
for.

**AND `B245` IS WHY A GREP ARM ALONE IS NOT ENOUGH.** `T-0066`'s own acceptance was
`grep -rn is_in_blackout backend -> 0`. It passed — while a paragraph in `test_t0035` still
asserted the deleted helper's behaviour as current, because the rewrite had changed the
identifier to "the blackout helper" and *prose is not searchable by identifier*. The grep hit
was the thing that moved. So this file guards DEFINITIONS by AST, and says so.
"""
from __future__ import annotations

import ast
import pathlib

APP = pathlib.Path(__file__).resolve().parents[2] / "app"
CALENDAR = APP / "services" / "calendar"
RULES = APP / "services" / "rules"


def _definition_names(root: pathlib.Path) -> list[str]:
    """Every function, method and class DEFINED under `root`, by AST.

    Definitions, not text: a comment explaining why the helper was deleted must not trip a
    guard against the helper existing. *That distinction is the whole of `B245` read the
    other way round — prose and identifiers are different populations, and each needs the
    check the other cannot give.*
    """
    names = []
    for path in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.append(f"{path.relative_to(APP)}:{node.lineno}:{node.name}")
    return names


def _blackout_named(names: list[str]) -> list[str]:
    return [n for n in names if "blackout" in n.rsplit(":", 1)[1].lower()]


def test_the_calendar_source_layer_defines_NO_blackout_helper():
    """**The arm.** `GATE-012` is the ratified implementation and it lives in `rules/`. The
    calendar layer's job is to FETCH and CLASSIFY events, not to decide a window.

    A blackout helper here would be a second statement of the news doctrine at the source —
    which is exactly what was deleted, and exactly what a seat reaching for "the blackout
    function" would find first.
    """
    offenders = _blackout_named(_definition_names(CALENDAR))
    assert not offenders, (
        f"a blackout helper has reappeared on the calendar source layer: {offenders}. "
        "The ratified window is GATE-012's, it is ASYMMETRIC and carries two numbers, and it "
        "lives in app/services/rules/. A helper here cannot express it — that is why T-0066 "
        "deleted the last one rather than rewriting it."
    )


def test_the_scan_CAN_see_a_blackout_definition_when_one_exists():
    """**THE CONTROL PAIR.** An empty result and a broken scan are the same green.

    Run the identical predicate over `rules/`, where the ratified implementation lives. It
    finds `PreEventBlackout` and `PostEventBlackout` — **two classes, because the ratified
    window is asymmetric**, which is the very thing one symmetric helper could not express.
    """
    found = _blackout_named(_definition_names(RULES))
    assert len(found) >= 2, (
        f"the scan found {found} under rules/ — it can no longer see a blackout definition, "
        "so the green above says nothing about the calendar layer"
    )
    assert any("PreEventBlackout" in f for f in found)
    assert any("PostEventBlackout" in f for f in found)


def test_the_deleted_identifier_is_defined_NOWHERE_under_app():
    """The narrower, exact check: nothing named `is_in_blackout` is DEFINED anywhere."""
    offenders = [n for n in _definition_names(APP) if n.endswith(":is_in_blackout")]
    assert not offenders, f"is_in_blackout has been redefined at {offenders}"


def test_prose_about_the_deletion_does_NOT_trip_the_guard():
    """**The must-miss, and it is the `B245` lesson made mechanical.**

    `finnhub.py` still contains the word "blackout" — in the comment explaining why the helper
    was deleted and what decides now. An explanation of a removal must not read as the
    removal being undone, or the honest thing to write becomes the thing that turns a test
    red, and the next seat writes the dishonest one.
    """
    source = (CALENDAR / "finnhub.py").read_text(encoding="utf-8")
    assert "blackout" in source.lower(), (
        "the explanation of WHY the helper was deleted has itself been deleted — that is how "
        "the reason gets lost and the helper comes back"
    )
    assert not _blackout_named(_definition_names(CALENDAR)), (
        "prose mentioning the deletion must not count as a definition"
    )
