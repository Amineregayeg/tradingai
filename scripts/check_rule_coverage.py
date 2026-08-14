#!/usr/bin/env python3
"""Check engine code against the pinned rule registry (M2).

The contract asks for a static link between our source and its rule ids, so it can grep our
codebase for rules that are in the registry and unimplemented. This is that link, checked.

WHAT FAILS THE BUILD, AND WHY ONLY THESE

  * **An id in our source that is not in the registry.** Either a typo or an invented rule.
    Both produce telemetry that conformance C-3 rejects, discovered far later.
  * **Two classes claiming one id.** Outcomes would accumulate against a rule with two
    behaviours, and the attribution ledger becomes unreadable.
  * **A `RULE_ID` that never registers.** Writing `RULE_ID = "GATE-005"` without subclassing
    `RuleImplementation` looks exactly like an implementation and is invisible to the
    coverage report. That gap is worse than no constant at all, because it reads as covered.

WHAT DOES NOT FAIL THE BUILD

Incomplete coverage. 116 of 117 rules are unimplemented today and that is simply where M2
sits — failing on it would mean the check could not be added until the work it measures was
finished, which is backwards. Coverage is REPORTED, loudly, and readiness gate 5 is what
eventually requires every NEVER_EVALUATED hard gate to be explained or fixed.

Run:  python3 scripts/check_rule_coverage.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))

from app.services import rules as rules_pkg  # noqa: E402
from app.services.telemetry import contract_loader as contract  # noqa: E402

#: `RULE_ID = "GATE-032"` anywhere in the backend source.
RULE_ID_ASSIGNMENT = re.compile(r'^\s*RULE_ID\s*(?::\s*[^=]+)?=\s*["\']([A-Z]+-\d{3})["\']', re.M)

failures: list[str] = []


def fail(title: str, detail: str) -> None:
    failures.append(title)
    print(f"FAIL  {title}")
    for line in detail.strip().splitlines():
        print(f"      {line.strip()}")


def ok(title: str) -> None:
    print(f"ok    {title}")


def canonical(rule_id: str) -> str:
    """Follow `alias_of` to the id that owns the implementation.

    THIRTEEN OF THE 117 REGISTRY IDS ARE ALIASES, AND COUNTING THEM AS RULES INFLATED EVERY
    ABSOLUTE FIGURE THIS SCRIPT PRINTED (B54). `GRADE-029` is `alias_of GATE-041`;
    `GRADE-035` is `alias_of GATE-040`. `base.py` registers an alias automatically and
    RAISES if a class claims one directly, so **an alias can never have its own
    implementation** — yet this script counted `GRADE-029` and `GATE-041` as two implemented
    rules, and reported one blocked class twice, twice over.

    RATIOS SURVIVED AND ABSOLUTE COUNTS DID NOT, which is why it went unnoticed: aliases
    inflate numerator and denominator together. The programme is scoped on an absolute count.

    `rule_waves.py` was fixed to collapse on 2026-08-14 and this script was not, so for one
    evening the project had two authoritative-looking answers to "how many rules are
    implemented" — and the divergence was created by fixing one of them.
    """
    return contract.alias_target(rule_id) or rule_id


def collapse(ids) -> set[str]:
    """The distinct rules behind a set of registry ids."""
    return {canonical(i) for i in ids}


def _wrap(text: str, width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines



def resolve_block_chain(
    rule_id: str, impls: dict, registry_ids: set, _seen: tuple = ()
) -> list[str]:
    """Follow CANNOT_FIRE_WITHOUT through rules that name other rules.

    Returns the chain from `rule_id` to its ROOT cause, e.g.
    `["GATE-040", "GATE-041", "GRADE-028"]`. A single-element list means not blocked.

    WHY THE FLAT FORM IS NOT ENOUGH, and the case is live. GATE-040's inputs name "the
    seven confirmation conditions (GATE-041)", and GATE-041 cannot reach a verdict. So
    GATE-040 consumes the output of a blocked rule while NONE of its own inputs is
    individually missing — it could have registered with no CANNOT_FIRE_WITHOUT at all
    and landed in effective coverage as able to decide. That omission would have been
    invisible: the flat form only sees DIRECT missing producers, and the blockage is one
    hop away.

    WHICH FORM THIS CHECK PREFERS, AND WHY IT IS NOT A STYLE CHOICE.
    **PROXIMATE** — name the rule you actually consume (`GATE-041`), not the root cause
    (`GRADE-028`). A root-cause declaration is a claim about ANOTHER rule's dependency:
    correct today only because both happen to block on the same producer, and silently
    FALSE the day GATE-041 blocks on something else, while still looking maintained. No
    local check can catch that, because the referent lives in a different module. The
    proximate form is the checkable one precisely because this function computes the
    chain instead of trusting an assertion about a rule nobody re-read.
    """
    if rule_id in _seen:
        return [*_seen, f"{rule_id} (CYCLE)"]
    cls = impls.get(rule_id)
    blockers = tuple(getattr(cls, "CANNOT_FIRE_WITHOUT", ()) or ()) if cls else ()
    if not blockers:
        return [rule_id]
    # POSITIONAL-FIRST, and the choice is recorded because it is currently DORMANT: no
    # rule declares more than one blocker today (all four are single), so this branch is
    # untested and activates silently the first time someone declares two. Same shape as
    # GATE-041's hardcoded FALSE — correct-looking now, load-bearing later, nothing
    # announcing the transition.
    #
    # First rather than shortest, longest, or all: it is deterministic and needs no
    # ordering rule over incommensurable chains, and any other blocker that is itself a
    # rule still surfaces as its own chain in the report, so nothing is hidden — only the
    # ATTRIBUTION of this rule's chain is arbitrary. Reporting every chain for a
    # multi-blocker rule is defensible and probably better, and was not done because
    # there is no instance to test it against; build it when the first one appears.
    nxt = blockers[0]
    if nxt in impls and nxt in registry_ids:
        return resolve_block_chain(nxt, impls, registry_ids, (*_seen, rule_id))
    # A leaf: named but not implemented, so there is nothing further to follow.
    return [*_seen, rule_id, nxt]


def main() -> int:
    registry_ids = contract.known_rule_ids()
    implemented = rules_pkg.implemented_ids()

    print(f"Rule coverage against RULE_REGISTRY.json v{contract.registry_version()}")
    print("-" * 68)

    # -- 1. every id in source resolves -------------------------------------------------
    in_source: dict[str, list[Path]] = {}
    for path in sorted(BACKEND.glob("app/**/*.py")):
        for rule_id in RULE_ID_ASSIGNMENT.findall(path.read_text(encoding="utf-8")):
            in_source.setdefault(rule_id, []).append(path)

    unknown = {r: p for r, p in in_source.items() if r not in registry_ids}
    if unknown:
        fail(
            "every RULE_ID in the source exists in the registry",
            "\n".join(
                f"{rid} in {', '.join(str(x.relative_to(REPO)) for x in paths)}"
                for rid, paths in unknown.items()
            )
            + "\nA rule id is never invented locally — it is the contract's join key.",
        )
    else:
        ok(f"every RULE_ID in the source exists in the registry ({len(in_source)} found)")

    # -- 2. no id claimed twice ---------------------------------------------------------
    duplicated = {r: p for r, p in in_source.items() if len(p) > 1}
    if duplicated:
        fail(
            "no rule id is claimed by two implementations",
            "\n".join(
                f"{rid}: {', '.join(str(x.relative_to(REPO)) for x in paths)}"
                for rid, paths in duplicated.items()
            ),
        )
    else:
        ok("no rule id is claimed by two implementations")

    # -- 3. every constant actually registers -------------------------------------------
    # The gap this closes: `RULE_ID = "GATE-005"` written without subclassing
    # RuleImplementation reads as an implementation and is invisible to the report below.
    unregistered = sorted(set(in_source) - implemented)
    if unregistered:
        fail(
            "every RULE_ID constant registers an implementation",
            "\n".join(
                f"{rid} in {', '.join(str(x.relative_to(REPO)) for x in in_source[rid])}"
                for rid in unregistered
            )
            + "\nDeclared but not registered: subclass RuleImplementation, and make sure"
            "\napp/services/rules/__init__.py imports the module.",
        )
    else:
        ok("every RULE_ID constant registers an implementation")

    # -- 4. report coverage (never fails) -----------------------------------------------
    print("-" * 68)
    hard = contract.ids_with_enforceability("HARD_GATE")
    open_ids = contract.ids_with_status("OPEN")

    # BOTH SPACES, BOTH LABELLED. A bare number cannot say which set it counted, and both
    # sets are legitimate answers to different questions: `ids` is what the registry
    # contains, `distinct` is how much work there is. Reporting only the first overstates
    # the programme; reporting only the second hides that the registry has two faces for
    # some rules. Printing one unlabelled is what produced B54.
    alias_ids = {i for i in registry_ids if contract.alias_target(i)}
    d_registry = collapse(registry_ids)
    d_implemented = collapse(implemented)
    d_hard = collapse(hard)
    d_open = collapse(open_ids)
    print(
        f"  EVERY FIGURE CARRIES ITS SPACE. `ids` counts registry entries; `distinct`"
        f"\n  collapses the {len(alias_ids)} alias ids onto the rule each one restates."
    )
    print(
        f"  implemented          {len(implemented):>3} / {len(registry_ids)} ids"
        f"     {len(d_implemented):>3} / {len(d_registry)} distinct"
    )
    print(
        f"  HARD_GATE covered    {len(implemented & hard):>3} / {len(hard)} ids"
        f"      {len(d_implemented & d_hard):>3} / {len(d_hard)} distinct"
    )
    print(
        f"  OPEN implemented     {len(implemented & open_ids):>3} / {len(open_ids)} ids"
        f"      {len(d_implemented & d_open):>3} / {len(d_open)} distinct"
        "   (each needs a declared parameter)"
    )
    if implemented:
        # KEEP THIS LINE'S SHAPE. `agents/rule_waves.py` parses it with
        # `implemented ids:\s*(.+)` to build its own view, then collapses aliases itself.
        # It lives outside this repository, so nothing in CI can catch a change here that
        # breaks it — `tests/unit/test_rule_coverage_counting.py` pins the format instead.
        print("  implemented ids:     " + ", ".join(sorted(implemented)))
        print("  distinct implemented:" + " " + ", ".join(sorted(d_implemented)))

    # -- 4b. IMPLEMENTED IS NOT THE SAME AS CAPABLE OF FIRING ----------------------------
    # THE FAILURE THIS EXISTS TO PREVENT, stated plainly because the number above is how
    # the whole rules programme is tracked: a rule implemented while one of its inputs has
    # no producer returns its documented DEFAULT forever. It is registered, its tests pass,
    # the count rises — and the engine's decisions are unchanged. Without this second line
    # the coverage report climbs to 91 while nothing decides differently, which is A10's
    # "an implemented rule that decides nothing is furniture" in a form that looks strictly
    # better than furniture.
    #
    # GATE-041 is the first instance: three of its seven conditions need GRADE-028, which
    # is SOFT_PREFERENCE and outside the 57, so no wave will ever deliver it.
    #
    # Derived from each implementation's own declaration rather than from the registry
    # graph, because 82 of 117 rules write their `inputs` as DATA NAMES and a rule-id graph
    # cannot see those dependencies at all (B44). A rule that knows it cannot fire says so.
    blocked = sorted(
        rid
        for rid, cls in sorted(rules_pkg.implementations().items())
        if getattr(cls, "CANNOT_FIRE_WITHOUT", None)
    )
    # DISTINCT RULES, NAMED BY THEIR CANONICAL ID. GATE-040 and GATE-041 — not four
    # entries. `GRADE-029` and `GRADE-035` are the same two classes under a second number,
    # so the flat count reported ONE blocked class twice, twice over.
    d_blocked = sorted(collapse(blocked))
    print(
        f"  implemented but CANNOT FIRE  {len(d_blocked):>3} distinct"
        f"   ({len(blocked)} ids incl. aliases)"
        "\n                               (an input has no producer — default forever)"
    )
    impls = rules_pkg.implementations()
    for rid in d_blocked:
        chain = resolve_block_chain(rid, impls, registry_ids)
        # The chain shows the ROOT cause and the hop count. A rule blocked one hop away
        # is invisible in the flat form, which is what this resolves.
        faces = [a for a in sorted(contract.aliases_of(rid)) if a in blocked]
        alias_note = f"   (also registered as {', '.join(faces)})" if faces else ""
        print(f"      {rid}  blocked: " + " <- ".join(chain) + alias_note)
    # THE NUMERATOR AND THE SUBTRAHEND MUST LIVE IN THE SAME SET. This subtracted ALL
    # blocked rules from a HARD_GATE-only count, so a blocked SOFT_PREFERENCE would have
    # been deducted from a total it was never in — and with enough of them, effective
    # coverage goes NEGATIVE. Correct today only because both blocked rules happen to be
    # HARD_GATEs, which is exactly the kind of accident that stops being true silently.
    # Found by writing invariant 4c below and asking what could violate it.
    blocked_hard = set(blocked) & implemented & hard
    d_blocked_hard = collapse(blocked) & d_implemented & d_hard
    if blocked:
        print(
            f"  effective coverage   {len(implemented & hard) - len(blocked_hard):>3}"
            f" / {len(hard)} ids"
            f"      {len(d_implemented & d_hard) - len(d_blocked_hard):>3} / {len(d_hard)}"
            " distinct   (implemented AND able to reach a verdict)"
        )

    # -- 4c. THE TOOL MUST NOT BE ABLE TO PRINT AN IMPOSSIBLE SET ------------------------
    # These hold by construction in any correct counting, in EITHER space, WITHOUT knowing
    # which number is right — which is the property that made the manual version of this
    # check cheap and is why it belongs in the tool rather than in a discipline.
    #
    # The instance: `effective coverage 37 / 91` was quoted beside `33 of 79 distinct
    # implemented`. Effective coverage cannot exceed implemented, and 37 > 33 on its face.
    # Both figures came from tools, both looked authoritative, and neither seat noticed for
    # hours. B47 is the reason to prefer the assertion over the agreement: both seats
    # demonstrated the discipline failing on this very pair within an hour of adopting it.
    #
    # A CONTRADICTION IS VISIBLE WITHOUT KNOWING WHICH FIGURE IS WRONG, so this localises
    # the error to one of two places for free. It fails the build because a report that
    # cannot be true is worse than no report.
    invariants = [
        ("distinct <= ids (registry)", len(d_registry) <= len(registry_ids)),
        ("distinct <= ids (implemented)", len(d_implemented) <= len(implemented)),
        ("distinct <= ids (HARD_GATE)", len(d_hard) <= len(hard)),
        ("implemented <= total, ids", len(implemented) <= len(registry_ids)),
        ("implemented <= total, distinct", len(d_implemented) <= len(d_registry)),
        ("implemented_and_hard <= implemented, ids",
         len(implemented & hard) <= len(implemented)),
        ("implemented_and_hard <= implemented, distinct",
         len(d_implemented & d_hard) <= len(d_implemented)),
        ("blocked <= implemented, ids", len(blocked) <= len(implemented)),
        ("blocked <= implemented, distinct", len(d_blocked) <= len(d_implemented)),
        ("effective <= implemented_and_hard, ids",
         len(implemented & hard) - len(blocked_hard) <= len(implemented & hard)),
        ("effective <= implemented_and_hard, distinct",
         len(d_implemented & d_hard) - len(d_blocked_hard) <= len(d_implemented & d_hard)),
        ("effective >= 0, ids", len(implemented & hard) - len(blocked_hard) >= 0),
        ("effective >= 0, distinct",
         len(d_implemented & d_hard) - len(d_blocked_hard) >= 0),
    ]
    broken = [name for name, holds in invariants if not holds]
    if broken:
        fail(
            "the counts above are internally consistent",
            "\n".join(broken)
            + "\nThese hold by construction in any correct counting, in either space. A "
            "violation means this tool's own arithmetic is wrong — do not quote any figure "
            "from this run.",
        )
    else:
        ok(f"the counts above are internally consistent ({len(invariants)} invariants)")

    # -- 5. what "implemented" does NOT mean --------------------------------------------
    # A rule id is a binary tick and several contract rules are not. Printing the notes here
    # is what stops the line above from reading as "PRIM-003: done".
    noted = sorted(
        (rid, cls.COVERAGE_NOTE)
        for rid, cls in rules_pkg.implementations().items()
        if getattr(cls, "COVERAGE_NOTE", None)
    )
    if noted:
        print("\n  Coverage notes — an implemented id is not always a finished rule:")
        for rid, note in noted:
            print(f"    {rid}")
            for line in _wrap(note, 66):
                print(f"      {line}")

    print("\n  Coverage is reported, not enforced: readiness gate 5 is what eventually")
    print("  requires every NEVER_EVALUATED hard gate to be explained or fixed.")

    print("-" * 68)
    if failures:
        print(f"FAILED {len(failures)}: " + "; ".join(failures))
        return 1
    print("PASSED — every rule id in the source resolves, is unique, and is registered.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
