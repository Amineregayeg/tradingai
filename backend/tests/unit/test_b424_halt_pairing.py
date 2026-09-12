"""B424 — halting and arming the alarm are ONE act, and NOTHING may suspend between them.

**Two properties that look like one, and the obvious fix only covers the first.**

```
THE PAIRING   every halt site arms the alarm      -> _declare_halt, and nothing assigns
                                                     self.halt_reason outside it
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
"""
from __future__ import annotations

import ast
import inspect
import textwrap

import pytest

from app.services.live import crypto_loop as mod
from app.services.live.crypto_loop import HALT_PARTIAL_UNSIZED, LiveCryptoLoop

#: Where the two fields may legitimately be written.
#: `_record_unsized_fill` updates `halt_record_failed` ONLY — that is the clear-on-success and
#: set-on-failure path, and it is the field's whole job. It must never touch `halt_reason`.
_HALT_REASON_WRITERS = {"__init__", "_declare_halt"}


def _loop_tree() -> ast.Module:
    return ast.parse(inspect.getsource(mod))


def _enclosing_function(tree: ast.Module, target: ast.AST) -> str | None:
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if any(n is target for n in ast.walk(fn)):
                return fn.name
    return None


# =====================================================================================
# PROPERTY 1 — THE PAIRING
# =====================================================================================

def test_halt_reason_is_assigned_ONLY_inside_declare_halt():
    """**`M-2`'s shape applied to a field instead of an import.**

    A second halt site that sets `halt_reason` and forgets the alarm inherits "healthy" for free —
    and nothing would fail, because every existing arm asserts STATES rather than call sites.
    """
    tree = _loop_tree()
    offenders = []
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        for t in targets:
            if isinstance(t, ast.Attribute) and t.attr == "halt_reason":
                where = _enclosing_function(tree, node)
                if where not in _HALT_REASON_WRITERS:
                    offenders.append(f"{where}() line {node.lineno}")

    assert not offenders, (
        "self.halt_reason is assigned outside _declare_halt: " + ", ".join(offenders) +
        ". A halt site that does not arm halt_record_failed reports a healthy durable record, "
        "because None on that field asserts both rows exist."
    )


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
    assert "halt_reason" not in touched, (
        "the writer assigns halt_reason — a bookkeeping write must not be able to lift a halt"
    )


# =====================================================================================
# PROPERTY 2 — THE WINDOW
# =====================================================================================

def _window_verdict(source: str) -> tuple[str, object]:
    """Check EVERY site, not the first one.

    **Review's first version returned after the first block containing both assignments — so with
    a second halt site it checked one, reported SAFE, and never looked at the other: the silent
    pass it exists to prevent, in the exact case `B424` exists for.** The execute seat's
    verification script had the identical bug. The keying was structural in both; the TRAVERSAL was
    not, and those are different properties.
    """
    tree = ast.parse(source)
    sites, halt_only = [], []
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            continue
        halt_i = alarm_i = None
        for i, st in enumerate(body):
            if not isinstance(st, ast.Assign):
                continue
            for t in st.targets:
                if isinstance(t, ast.Attribute) and t.attr == "halt_reason":
                    halt_i = i
                if isinstance(t, ast.Attribute) and t.attr == "halt_record_failed":
                    alarm_i = i
        if halt_i is None:
            continue
        if alarm_i is None or alarm_i <= halt_i:
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
    if mutation == "await":
        src = src.replace("        self.halt_reason = reason\n",
                          "        self.halt_reason = reason\n        await self._act('x', 'y')\n", 1)
    elif mutation == "drop_alarm":
        src = src.replace(
            '        self.halt_record_failed = f"{reason} — durable record NOT YET WRITTEN"\n', "", 1)
    else:
        src = src.replace("        self.halt_reason = reason\n", "", 1).replace(
            '        self.halt_record_failed = f"{reason} — durable record NOT YET WRITTEN"\n', "", 1)
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
                self.halt_reason = "A"
                self.halt_record_failed = "armed"

            async def site_two(self):
                self.halt_reason = "B"
                await self.something()
                self.halt_record_failed = "armed"
    ''')
    verdict, detail = _window_verdict(two_sites)
    assert verdict == "REOPENED", (
        f"a two-site module with an open window in the SECOND site reported {verdict} — the check "
        f"returns after the first site instead of walking all of them"
    )
    assert any(lineno for _, _, between in detail for _, lineno in between)


def test_a_module_with_NO_halt_site_is_refused_not_passed():
    """`NO SITE FOUND` must never read as `SAFE`."""
    verdict, _ = _window_verdict("class L:\n    def f(self):\n        self.other = 1\n")
    assert verdict == "NO SITE FOUND"
