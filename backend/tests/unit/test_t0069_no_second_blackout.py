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

#: **THE CARVE-OUT IS A REASON, NOT A LOCATION.** `GATE-012` is the ratified implementation
#: and these two classes ARE it. They are excluded BY NAME and the control below asserts what
#: they are — so the exclusion says *"the ratified pair, identified elsewhere in this file"*
#: rather than *"whatever happens to live in that directory"*.
#:
#: **There are TWO of them because the ratified window is ASYMMETRIC** — `[event-15, event)`
#: then `[event, event+30)`, two numbers — which is precisely what one symmetric helper could
#: not express and why `T-0066` deleted rather than rewrote it. *That arity is a good note and
#: would be a fragile guard: it is recorded here and not asserted as a rule.*
RATIFIED_BLACKOUT_PAIR = ("PreEventBlackout", "PostEventBlackout")


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


def _unratified(names: list[str]) -> list[str]:
    return [n for n in _blackout_named(names) if n.rsplit(":", 1)[1] not in RATIFIED_BLACKOUT_PAIR]


def test_NOTHING_under_app_defines_a_second_blackout_implementation():
    """**The arm, and `T-0070` widened it from `calendar/` to ALL of `app/`.**

    The first version walked only `app/services/calendar/`, where the deleted helper lived.
    Review mutated the case that scoping could not see:

        is_in_blackout reintroduced ON the calendar layer       caught
        a DIFFERENT name, blackout-shaped, ON the calendar layer  caught
        a DIFFERENT name, blackout-shaped, in `live/`           **INVISIBLE**

    **The third is not the edge case, it is the central one.** The seat `B232` describes is
    working in `live/` when they reach for a blackout check — so the narrow scope caught the
    two least likely places and missed the most likely. *A guard blind to the directory where
    the hazard would actually be written promises coverage it does not have.*

    **Widening cost nothing: the wider predicate was already true.** Every blackout-named
    definition under `app/` is the ratified pair, so `app/` minus those fires on NOTHING —
    measured before adopting it, the same shape as `B191`'s widening.

    **And the exclusion is by NAME, so a third statement inside `rules/` fires too.** A path
    exclusion would have made the ratified module the one place a second implementation could
    hide, which is the opposite of what `GATE-011` asks for.
    """
    offenders = _unratified(_definition_names(APP))
    assert not offenders, (
        f"a second blackout implementation has appeared: {offenders}. The ratified window is "
        f"{RATIFIED_BLACKOUT_PAIR} in GATE-012 — ASYMMETRIC, two numbers. T-0066 deleted the "
        "last one rather than rewriting it because no symmetric helper can express that, and "
        "a third statement of the news doctrine is GATE-011's defect."
    )


def test_the_scan_CAN_see_a_blackout_definition_and_it_IS_the_ratified_pair():
    """**THE CONTROL PAIR, and it is also what licenses the carve-out.**

    An empty result and a broken scan are the same green — so the identical predicate is run
    without the exclusion, and it must find the ratified pair and nothing else. That single
    assertion does two jobs: it proves the scan can see a blackout definition at all, and it
    establishes that what arm 1 excludes really is `GATE-012`'s implementation rather than
    whatever happened to be sitting in a directory.
    """
    found = _blackout_named(_definition_names(APP))
    assert sorted(n.rsplit(":", 1)[1] for n in found) == sorted(RATIFIED_BLACKOUT_PAIR), (
        f"the blackout population under app/ is now {found}. If the scan sees nothing, arm 1's "
        "green says nothing; if it sees something new, arm 1 should already have fired."
    )
    assert all(f.startswith("services/rules/gate_012") for f in found), (
        "the ratified pair must still live in GATE-012 — if it moved, the carve-out is "
        "excluding two names whose provenance is no longer established"
    )


def test_the_deleted_identifier_is_defined_NOWHERE_under_app():
    """The narrower, exact check: nothing named `is_in_blackout` is DEFINED anywhere."""
    offenders = [n for n in _definition_names(APP) if n.endswith(":is_in_blackout")]
    assert not offenders, f"is_in_blackout has been redefined at {offenders}"


def test_the_explanation_of_the_deletion_has_not_itself_been_deleted():
    """`finnhub.py` must still say WHY the helper is gone.

    *This is the assertion covered nowhere else in the file* — the guard above stops the
    helper returning, and this stops the REASON going missing, which is how it comes back.
    """
    source = (CALENDAR / "finnhub.py").read_text(encoding="utf-8")
    assert "blackout" in source.lower(), (
        "the explanation of WHY the helper was deleted has itself been deleted — that is how "
        "the reason gets lost and the helper comes back"
    )


def test_prose_is_not_a_definition_and_cannot_trip_the_guard():
    """**The must-miss, on a CONSTRUCTED source so it can fail for its OWN reason.**

    It used to re-assert arm 1 over the real tree, which meant a genuine offender made it
    report *"prose mentioning the deletion must not count as a definition"* when no prose was
    involved. **A must-miss that fails for the must-fire's reason cannot fail for its own** —
    Review's finding, and the fix is to give it an input only it can fail on.
    """
    prose_only = ast.parse(
        '"""The blackout helper was deleted by T-0066; is_in_blackout is gone."""\n'
        "# a comment about the blackout window and is_in_blackout\n"
        "BLACKOUT_NOTE = 'is_in_blackout was symmetric'\n"
        "def unrelated():\n"
        "    return 'blackout'\n"
    )
    names = [
        n.name for n in ast.walk(prose_only)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    assert names == ["unrelated"], names
    assert not [n for n in names if "blackout" in n.lower()], (
        "docstrings, comments and string CONSTANTS naming the deleted helper must not read "
        "as definitions — an explanation of a removal that turns a test red is how the "
        "honest thing to write becomes the thing nobody writes"
    )
