"""B424 — halting and arming the alarm are ONE act, and NOTHING may suspend between them.

**Two properties that look like one, and the obvious fix only covers the first.**

```
THE PAIRING   every halt site arms the alarm      -> _declare_halt, and nothing assigns
                                                     halt_reason outside it
THE WINDOW    nothing suspends between the two    -> its own arm, INSIDE _declare_halt too,
              assignments                            because collapsing them says nothing
                                                     about what sits between them
```

**Why the window matters.** `halt_record_failed is None` asserts *both durable rows are on disk*.
If a cancellation lands between declaring the halt and arming the alarm — or a concurrent
`status()` observes that instant — the engine is halted and reports a healthy record. An `await`
placed between the two statements reopens both routes **with `_declare_halt` fully in place**.

**The adjacency was undesigned.** It held because one author wrote two lines next to each other, and
nothing recorded it. A structural property nobody chose is the most fragile kind: no comment, no
arm, and no author who remembers deciding it.

#### THE TWO RESIDUALS, both review's, both fixed here rather than written down

**SCOPE.** The first version of this file scanned ONE MODULE, via `inspect.getsource(mod)`, while
`halt_reason` was a public attribute **assignable from any module**. Route 3 was closed against a
new halt site in `crypto_loop.py` and left wide open against the same site written one file over —
*"route 3 relocated from another function to another file."* Nothing outside that module assigned
it, so it was latent, which is the state every entry in this register was in the week before it
wasn't. Fixed **twice over**, because the two mechanisms fail differently:

```
halt_reason is now a read-only property    an external assignment RAISES     but only if it RUNS
the scan below walks the PACKAGE           a line that never runs is caught  but only where it LOOKS
```

**LAST-WINS.** `_window_verdict` kept one `halt_i`/`alarm_i` per body, overwriting them each
iteration, so **two pairs in one body left the earlier one unchecked** — driven and confirmed:
a two-pair body whose FIRST pair had an open window reported `SAFE`. That is the traversal defect
of `test_the_check_walks_EVERY_site_not_just_the_first` at one level down: fixed there *between*
bodies, still present *within* one. **The same last-wins shortcut in a third place**, which is why
it is a change and not the comment it was offered as.

**A STATED ASSUMPTION, since it bounds what every scan here can mean** (review's wording): a source
scan checks *the source someone will edit*, not the objects the interpreter has loaded. A
monkeypatched double is a test's own business and deliberately out of scope. The property is what
covers the loaded object; the scan is what covers the file.
"""
from __future__ import annotations

import ast
import inspect
import textwrap
from pathlib import Path

import pytest

from app.services.live import crypto_loop as mod
from app.services.live.crypto_loop import HALT_PARTIAL_UNSIZED, LiveCryptoLoop

#: Where the two fields may legitimately be written.
#: `_record_unsized_fill` updates `halt_record_failed` ONLY — that is the clear-on-success and
#: set-on-failure path, and it is the field's whole job. It must never touch the halt.
_HALT_REASON_WRITERS = {"__init__", "_declare_halt"}

#: **BOTH SPELLINGS, and the reason is this file's own near miss.** `halt_reason` became a
#: read-only property over `_halt_reason`; a scan updated to the new spelling alone would have gone
#: on passing while asserting nothing about the old one, and a scan left on the old spelling alone
#: would have matched zero assignments in production and passed *because the field was renamed*.
#: A rename is the cheapest way to turn a scan into a scan of nothing.
_HALT_FIELDS = ("halt_reason", "_halt_reason")

#: Product code and tests both. A fixture that fakes a halt by hand is the thing that was already
#: caught doing the production code's work once.
_PACKAGE_ROOTS = ("app", "tests")

#: **THE ONE EXEMPTION, named and bounded** — the arm that proves the property refuses an external
#: assignment has to contain an external assignment. `_IMPORT_EXEMPT`'s shape from the migration
#: freeze: an exemption nobody can see the size of is a hole, so its contents are pinned and an arm
#: below fails if it grows. This is the whole list; there is no wildcard.
_EXEMPT = {
    "tests/unit/test_b424_halt_pairing.py": {
        "test_halt_reason_is_READ_ONLY_so_an_external_assignment_cannot_be_written_at_all",
    },
}

_BACKEND = Path(mod.__file__).resolve().parents[3]


def _loop_tree() -> ast.Module:
    return ast.parse(inspect.getsource(mod))


def _enclosing_names(tree: ast.Module) -> dict[int, str]:
    """`id(node) -> enclosing function name`, built in one pass.

    The previous version re-walked the whole tree per match, which was affordable for one module
    and is not for 300-odd files. Innermost wins: functions are visited outermost-first, so a
    nested definition overwrites its parent's claim on the nodes it owns.
    """
    out: dict[int, str] = {}
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for n in ast.walk(fn):
                out[id(n)] = fn.name
    return out


def _assignment_sites(fields=_HALT_FIELDS, exempt=None) -> tuple[list[str], list[str]]:
    """Every `<expr>.<field> = ...` in the package, as `(offenders, legitimate_sites)`.

    **The sites are returned, not just the offenders, because a scan that matched nothing must not
    be able to pass.** An empty offender list means either "nobody assigns this" or "the field was
    renamed and this arm has been inert since"; only the denominator tells them apart.
    """
    exempt = _EXEMPT if exempt is None else exempt
    files = [f for r in _PACKAGE_ROOTS for f in sorted((_BACKEND / r).rglob("*.py"))]
    if not files:
        pytest.fail(
            f"REFUSING: scanned 0 files under {_BACKEND} — a zero from here would mean nothing"
        )

    offenders: list[str] = []
    sites: list[str] = []
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:                      # a file we cannot read is a LEAD, not a skip
            pytest.fail(f"REFUSING: {path} did not parse, so this scan cannot answer for it: {exc}")

        matches = []
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                targets = [node.target]
            for t in targets:
                if isinstance(t, ast.Attribute) and t.attr in fields:
                    matches.append(node)
        if not matches:
            continue

        where_of = _enclosing_names(tree)
        rel = path.relative_to(_BACKEND)
        for node in matches:
            where = where_of.get(id(node))
            at = f"{rel}:{node.lineno} in {where}()"
            key = rel.as_posix()
            if key == "app/services/live/crypto_loop.py" and where in _HALT_REASON_WRITERS:
                sites.append(at)
            elif where in exempt.get(key, ()):
                pass
            else:
                offenders.append(at)
    return offenders, sites


# =====================================================================================
# PROPERTY 1 — THE PAIRING
# =====================================================================================

def test_the_halt_is_assigned_ONLY_inside_declare_halt_ANYWHERE_IN_THE_PACKAGE():
    """**`M-2`'s shape applied to a field instead of an import, over the package rather than one
    module** — review's SCOPE residual.

    A second halt site that sets the halt and forgets the alarm inherits "healthy" for free, and
    nothing would fail, because every other arm asserts STATES rather than call sites. It does not
    become a different defect for being written in a different file.
    """
    offenders, sites = _assignment_sites()

    # **THE DENOMINATOR, and the first version of it was satisfied by something weaker.** It
    # asserted only that SOME site was found. A kill-set row renamed the field in `_declare_halt`
    # and this arm went on passing, because `__init__`'s assignment is also a legitimate site —
    # so the scan had gone blind to the declaration point and still reported a full denominator.
    # What has to be present is the site whose disappearance means the scan is measuring nothing.
    assert any("in _declare_halt()" in site for site in sites), (
        f"the scan found no assignment inside _declare_halt — it is no longer matching what the "
        f"declaration point writes, so its empty offender list is not evidence of anything. Check "
        f"{_HALT_FIELDS} against the field's current spelling. Sites seen: {sites}"
    )
    assert not offenders, (
        "the halt is assigned outside _declare_halt: " + ", ".join(offenders) +
        ". A halt site that does not arm halt_record_failed reports a healthy durable record, "
        "because None on that field asserts both rows exist."
    )


def test_the_SCAN_would_catch_an_assignment_in_ANOTHER_FILE():
    """**The control for the residual itself.** The old scan passed on exactly this input, and it
    passed for the reason that makes a scan dangerous: the offending line was outside the one file
    it was pointed at, so there was nothing to report and nothing to notice.

    Driven against this very module: an assignment lives here, in a file that is not
    `crypto_loop.py`, and the scan must name it.
    """
    offenders, _ = _assignment_sites(fields=("_b424_probe_field",))
    assert any("test_b424_halt_pairing.py" in o for o in offenders), (
        f"the scan did not see an assignment in a second file — it reported {offenders}"
    )


class _Probe:
    def arm(self):
        self._b424_probe_field = "the line the scan above must find"


def test_halt_reason_is_READ_ONLY_so_an_external_assignment_cannot_be_written_at_all():
    """**The other half of the SCOPE fix, and the half that does not depend on where anyone looked.**

    A scan answers for the files it was given. This answers for every file there will ever be,
    including one written after this arm stops being maintained.
    """
    loop = LiveCryptoLoop()
    with pytest.raises(AttributeError):
        loop.halt_reason = "declared from somewhere that is not _declare_halt"
    assert loop.halt_reason is None, "the refused assignment still landed"
    assert loop.halt_record_failed is None, "a refused halt armed the alarm anyway"


def test_declare_halt_sets_BOTH_fields():
    """The pairing, driven rather than read — a method could satisfy the arm above and set one."""
    loop = LiveCryptoLoop()
    assert loop.halt_reason is None and loop.halt_record_failed is None

    loop._declare_halt(HALT_PARTIAL_UNSIZED)

    assert loop.halt_reason == HALT_PARTIAL_UNSIZED
    assert loop.halt_record_failed and "NOT YET WRITTEN" in loop.halt_record_failed


def test_the_WRITER_may_update_the_alarm_but_never_the_HALT():
    """`_record_unsized_fill` clears the alarm on success — that is its job. It must not be able to
    clear the halt, which would let a successful bookkeeping write resume trading."""
    tree = _loop_tree()
    writer = next(fn for fn in ast.walk(tree)
                  if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and fn.name == "_record_unsized_fill")
    touched = {t.attr for n in ast.walk(writer)
               if isinstance(n, ast.Assign)
               for t in n.targets if isinstance(t, ast.Attribute)}
    assert "halt_record_failed" in touched, "the writer no longer reports its own outcome"
    assert not touched & set(_HALT_FIELDS), (
        "the writer assigns the halt — a bookkeeping write must not be able to lift a halt"
    )


# =====================================================================================
# PROPERTY 2 — THE WINDOW
# =====================================================================================

def _window_verdict(source: str) -> tuple[str, object]:
    """Check EVERY site, not the first one — and every PAIR, not the last one in each body.

    **Two traversal defects, found one after the other, in the same eight lines.**

    *Between bodies.* Review's first version returned after the first block containing both
    assignments, so with a second halt site it checked one, reported SAFE, and never looked at the
    other: the silent pass it exists to prevent, in the exact case `B424` exists for. The execute
    seat's verification script had the identical bug. The keying was structural in both; the
    TRAVERSAL was not, and those are different properties.

    *Within a body.* The fix for that kept a single `halt_i`/`alarm_i` per body and **overwrote
    them on each iteration**, so a body with two pairs was judged on its last one only — measured:
    two pairs in one body, open window on the FIRST, verdict `SAFE`. Each halt now pairs with the
    next alarm that follows it, and every halt is judged.
    """
    tree = ast.parse(source)
    sites, halt_only = [], []
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            continue
        halts, alarms = [], []
        for i, st in enumerate(body):
            if not isinstance(st, ast.Assign):
                continue
            for t in st.targets:
                if isinstance(t, ast.Attribute) and t.attr in _HALT_FIELDS:
                    halts.append(i)
                if isinstance(t, ast.Attribute) and t.attr == "halt_record_failed":
                    alarms.append(i)
        for halt_i in halts:
            alarm_i = next((a for a in alarms if a > halt_i), None)
            if alarm_i is None:
                halt_only.append(body[halt_i].lineno)
                continue
            between = [(type(n).__name__, n.lineno)
                       for st in body[halt_i:alarm_i] for n in ast.walk(st)
                       if isinstance(n, (ast.Await, ast.Yield, ast.YieldFrom))]
            sites.append((body[halt_i].lineno, body[alarm_i].lineno, between))

    if halt_only:
        # DISTINCT FROM "no site found". The halt exists and the alarm does not — a real defect
        # with a specific remedy, and the review seat declared this exact wart rather than
        # shipping the message that named the wrong cause.
        return "ALARM ABSENT", halt_only
    if not sites:
        # AND THIS MUST NEVER READ AS SAFE. A checker that matched nothing has not verified
        # anything — the empty-glob rule, in a third place.
        return "NO SITE FOUND", "the check is scanning nothing, which is not the same as SAFE"
    reopened = [s for s in sites if s[2]]
    return ("REOPENED", reopened) if reopened else ("SAFE", sites)


def test_nothing_suspends_between_the_halt_and_the_alarm():
    """**The window, on the real tree.**"""
    verdict, detail = _window_verdict(inspect.getsource(mod))
    assert verdict == "SAFE", f"{verdict}: {detail}"


@pytest.mark.parametrize("mutation,expected", [
    ("await", "REOPENED"),
    ("drop_alarm", "ALARM ABSENT"),
    ("drop_both", "NO SITE FOUND"),
])
def test_the_window_CHECK_discriminates(mutation, expected):
    """The checker's own control. Without it this file asserts that a checker which never matches
    anything is happy — which is what a `return`-on-first-site traversal quietly becomes."""
    src = inspect.getsource(mod)
    halt = "        self._halt_reason = reason\n"
    alarm = '        self.halt_record_failed = f"{reason} — durable record NOT YET WRITTEN"\n'
    assert src.count(halt) == 1 and src.count(alarm) == 1, (
        "the mutation anchors no longer match the source, so these mutations would be applied to "
        "nothing and every 'expected' below would be measuring the clean tree (B420)"
    )
    if mutation == "await":
        src = src.replace(halt, halt + "        await self._act('x', 'y')\n", 1)
    elif mutation == "drop_alarm":
        src = src.replace(alarm, "", 1)
    else:
        src = src.replace(halt, "", 1).replace(alarm, "", 1)
    verdict, _ = _window_verdict(src)
    assert verdict == expected, f"expected {expected}, got {verdict}"


def test_the_check_walks_EVERY_site_not_just_the_first():
    """**THE TRAVERSAL, and HEAD cannot test it** — HEAD has one halt site, so it cannot tell a
    correct traversal from one that returns after the first match. The fixture is synthetic on
    purpose: the tree we have is not a discriminating input, and using it would be measuring where
    the defect cannot appear."""
    two_sites = textwrap.dedent('''
        class L:
            def site_one(self):
                self._halt_reason = "A"
                self.halt_record_failed = "armed"

            async def site_two(self):
                self._halt_reason = "B"
                await self.something()
                self.halt_record_failed = "armed"
    ''')
    verdict, detail = _window_verdict(two_sites)
    assert verdict == "REOPENED", (
        f"a two-site module with an open window in the SECOND site reported {verdict} — the check "
        f"returns after the first site instead of walking all of them"
    )
    assert any(lineno for _, _, between in detail for _, lineno in between)


def test_the_check_walks_EVERY_PAIR_WITHIN_ONE_BODY():
    """**Review's LAST-WINS residual, and the fixture is the one that exposed it.**

    Two pairs in a single function body, open window on the **first**. Keeping one `halt_i` per
    body overwrites the first pair with the second and reports `SAFE` — measured before the fix.
    HEAD cannot discriminate this either: `_declare_halt` is one pair in one body, so the input
    that tells a correct walk from a last-wins one has to be built.
    """
    two_pairs = textwrap.dedent('''
        class L:
            async def both(self):
                self._halt_reason = "A"
                await self.something()
                self.halt_record_failed = "armed"
                self._halt_reason = "B"
                self.halt_record_failed = "armed"
    ''')
    verdict, detail = _window_verdict(two_pairs)
    assert verdict == "REOPENED", (
        f"two pairs in ONE body with an open window on the FIRST reported {verdict} — the walker "
        f"keeps the last pair in each body and never judges the earlier one"
    )
    assert len(detail) == 1 and detail[0][0] == 4, (
        f"the reopened pair should be the one starting at line 4, got {detail}"
    )


def test_a_module_with_NO_halt_site_is_refused_not_passed():
    """`NO SITE FOUND` must never read as `SAFE`."""
    verdict, _ = _window_verdict("class L:\n    def f(self):\n        self.other = 1\n")
    assert verdict == "NO SITE FOUND"


def test_the_EXEMPTION_is_bounded_and_is_still_LOAD_BEARING():
    """**`M-8`'s shape.** An exemption is a hole in the arm above, and one nobody can see the size
    of is an unbounded hole. Two things are checked, because pinning the list only covers the first:

    * it has not GROWN — the contents are pinned literally;
    * it still EXEMPTS something. An exemption whose line has since been deleted or renamed is a
      hole held open for free, and it reads exactly like a live one.
    """
    assert _EXEMPT == {
        "tests/unit/test_b424_halt_pairing.py": {
            "test_halt_reason_is_READ_ONLY_so_an_external_assignment_cannot_be_written_at_all",
        },
    }, f"the exemption list changed — every addition is a new hole in the scan: {_EXEMPT}"

    without, _ = _assignment_sites(exempt={})
    assert len(without) == 1 and "test_b424_halt_pairing.py" in without[0], (
        f"with the exemption removed the scan reports {without} — it should report exactly the one "
        f"line the exemption exists for. Anything else means the exemption is covering something "
        f"nobody chose, or nothing at all."
    )
