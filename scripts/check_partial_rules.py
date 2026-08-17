#!/usr/bin/env python3
"""Enforce the partially-evaluable-rule requirements over the WHOLE registry (T-0016).

`PROGRAMME_TO_CUTOVER.md` carries six standing requirements for a rule implemented while
one of its inputs has no producer. Five of the six were enforced by review alone, and
Review's objection is that this makes them backwards:

    A structural requirement enforced only by review is enforced exactly where review is
    thorough — which is the rules nobody is worried about, not rule fifty. So these
    requirements are, as written, STRONGEST WHERE THEY ARE LEAST NEEDED.

The first rule of a new kind is written under maximum attention and will be correct.
GATE-041 is. Its correctness is the least informative evidence available about the
fiftieth, and 55 remain.

WHY THIS IS A SEPARATE SCRIPT FROM `check_rule_coverage.py`

They answer different questions and fail on different things. `check_rule_coverage.py`
answers *"does every rule id in the source resolve, uniquely, to a registered
implementation"* — a static link between our source and the contract. This answers
*"does every rule that cannot read all its inputs behave the way the standing pattern
requires"*. Folding the second into the first would make one `PASSED` line stand for two
unrelated properties, and a reader who knows what that line used to mean would not learn
that it now means less than they think. That is this project's default failure — an output
that does not discriminate — arriving through the tool built to police it.

WHAT FAILS THE BUILD

  * A rule that reaches a verdict while one of its condition readings is unreadable.
    The quorum was scored against a denominator that silently shrank to the readable
    subset. (Criterion 2 / standing requirement 2a.)
  * A rule module that uses `ConditionReading` without importing the SHARED
    `quorum_blocked`, i.e. one that derives the blocked-state invariant inline.
    (Criterion 3.)
  * A grep hit for the inline pattern in a module the import check calls clean, with no
    named exemption. (Criterion 3-iv: a false positive is resolved by naming it, never by
    loosening the pattern.)
  * A NEW emitted `values` key with no provenance entry, no named exemption, and no
    baseline entry. (Criterion 3a.)
  * A stale exemption or baseline entry — one that no longer describes anything. An
    exemption list nobody prunes is how a check becomes decorative.
  * A rule in a check's population that the check could not actually examine. Silence is
    not a pass: a rule that could not be probed is a FAILURE here, never a skip.

WHAT DOES NOT FAIL THE BUILD

The eleven provenance gaps that predate this script. They are listed by (rule, field) with
the date they were baselined, printed on every run, and a new one fails immediately. A
check that landed red would be turned off within a day; a ratchet is the version that
survives.

Run:  python3 scripts/check_partial_rules.py
"""
from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))

from app.services import rules as rules_pkg  # noqa: E402
from app.services.rules import base as rules_base  # noqa: E402
from app.services.rules.base import ConditionReading  # noqa: E402
from app.services.telemetry import contract_loader as contract  # noqa: E402

#: The two states that mean "this condition could not be read". They are DIFFERENT
#: absences — `NOT_EVALUABLE` means no producer exists, `NOT_READ` means one exists and
#: nothing wired it — and both must block a quorum, so both are probed.
UNREADABLE = ("NOT_EVALUABLE", "NOT_READ")
CONDITION_STATES = ("TRUE", "FALSE", *UNREADABLE)

# ---------------------------------------------------------------------------------------
# EXEMPTIONS. Criterion 5: the exemption path must be HARDER than compliance.
#
# Every entry carries the rule id (or module) it exempts and the reason, IN THE CHECK
# ITSELF, and every entry is printed on every run. An exemption nobody sees is how a check
# becomes decorative — B41 is four layers of exactly that. And an exemption that stops
# describing anything FAILS the build rather than lingering, so the list cannot outlive the
# thing it excuses.
# ---------------------------------------------------------------------------------------

#: Rules allowed to reach a verdict with an unreadable condition. EMPTY, and it should stay
#: that way: the invariant is rule-independent by construction. An entry here is a claim
#: that some rule's quorum is meaningful over a shrunken denominator.
#:
#: KEYED BY CANONICAL `RULE_ID`, like every list below. An alias id is the SAME class under
#: a second number, so keying by registered id would require every entry twice and let the
#: two copies drift — and a check whose exemption list can disagree with itself is worse
#: than no list.
QUORUM_EXEMPT: dict[str, str] = {}

#: Modules allowed to use `ConditionReading` without binding the shared `quorum_blocked`.
#: A single-condition rule is the legitimate case — there is no quorum to block.
INLINE_EXEMPT: dict[str, str] = {}

#: Modules the GREP flags while the import check calls them clean. Criterion 3-iv: this is
#: the resolution for a grep false positive, and it is deliberately a named entry rather
#: than a tighter regex — a tighter regex makes the NEXT false negative silent, and the
#: grep's failure mode is already silent.
GREP_EXEMPT: dict[str, str] = {
    "app.services.rules.gate_041_reverse_switch": (
        "Matches on `r.state == \"NOT_EVALUABLE\"` in two list/dict comprehensions that "
        "build the RECORD's `not_evaluable` map — reporting which conditions were "
        "unreadable, not deciding anything from it. The decision goes through the shared "
        "`quorum_blocked`, which the import check confirms is base's own object."
    ),
    "app.services.rules.gate_040_cool_off": (
        "Same shape as GATE-041: the matches build `values['not_evaluable']` and "
        "`values['not_read']` for the record. Keeping the two absences apart in the "
        "PAYLOAD is required — `quorum_blocked` merges them because for its purpose both "
        "mean no quorum, and the record must not — so this module is expected to name the "
        "states textually while still deciding through the shared helper."
    ),
    "app.services.rules.gate_012_news_blackout": (
        "Fourth instance of the GATE-041/GATE-040 shape, and a REPORTING match rather than a "
        "decision: the hit is `if condition.state == \"NOT_READ\"` guarding the construction "
        "of `values['unreadable_conditions']`, which names the producer that exists and was "
        "not called so the absence is attributable. The verdict is decided by "
        "`quorum_blocked` with GATE-013's own default BLOCK — the import check confirms the "
        "binding is base's own object. The state is named textually for GATE-040's reason: "
        "the PAYLOAD must keep NOT_READ and NOT_EVALUABLE apart even though quorum_blocked "
        "merges them, because for this rule the distinction is the whole finding — the M15 "
        "series EXISTS and was not wired, which has a different owner and a different fix "
        "from a producer nobody has built."
    ),
    "app.services.rules.target_006_equals_ranking": (
        "Third instance of the GATE-041/GATE-040 shape, and it is a REPORTING match rather "
        "than a decision: the hit is a dict comprehension building "
        "`values['unreadable_conditions']`, which names WHICH producer is missing or unread "
        "so the absence is attributable. The verdict is decided by `quorum_blocked` with "
        "TARGET-006's own default CLASSIFY_ONLY — the import check confirms the binding is "
        "base's own object. The two absences are deliberately named separately here for "
        "GATE-040's reason: this rule has one of EACH, a missing producer (v_shaped "
        "liquidity, TARGET-007 OPEN) and an unread one (boosters, emitted with zero read "
        "sites), and merging them would lose exactly the distinction that says which has an "
        "owner."
    ),
}

#: `values` keys that legitimately carry no provenance, keyed by (rule id, field).
#:
#: Criterion 3a-ii, and it is the reason a TYPE PREDICATE could not have been used: this is
#: a SEMANTIC judgement. No predicate over the value would surface it, and a predicate that
#: quietly dropped these would have hidden the one exemption that is actually correct.
PROVENANCE_EXEMPT: dict[tuple[str, str], str] = {
    ("GATE-041", "outcome"): (
        "THE VERDICT ITSELF. The rest of the payload IS its provenance — the conditions, "
        "their states, the quorum and its version are exactly what produced it. Requiring "
        "the outcome to explain its own origin is circular."
    ),
    ("GATE-040", "mode"): (
        "THE VERDICT ITSELF, under GATE-040's name for it — the registry's output field is "
        "`mode in {FORWARD, REVERSE}`. Same argument as GATE-041's `outcome`, applied to "
        "the second instance rather than left to be re-derived: the inputs map, the "
        "consolidation evidence and the elapsed duration are its provenance. THIS ENTRY IS "
        "MINE, not the plan's — 3a-ii named `outcome` as the one real exemption and this is "
        "the same field under a different name, so calling it a violation would have said "
        "'somebody should add provenance to the verdict', which 3a-ii calls circular."
    ),
}

#: Provenance gaps that PREDATE this check. Reported on every run, and they do NOT fail the
#: build — criterion 3a: "report them, do not fail the build until they are cleared, and say
#: which are pre-existing."
#:
#: THE RATCHET, AND WHY IT IS NOT AN EXEMPTION. An exemption says the field is fine as it
#: is; a baseline entry says the field is WRONG and nobody has fixed it yet. Conflating them
#: would put a permanent "this is correct" stamp on twelve fields that need work — the same
#: absent-versus-empty collapse this whole check exists to police. Clearing a gap means
#: deleting its line here, in the same commit, and the stale-entry check enforces that.
#: All eleven were measured on the first run of this script, on 2026-08-14, and are the
#: ENTIRE pre-existing population across every invokable rule — not a sample. KNOWN_ISSUES
#: B56 holds them and names who clears them.
PROVENANCE_PRE_EXISTING: dict[tuple[str, str], str] = {
    ("GATE-041", "conditions_total"): "predates T-0016 (2026-08-14) — B56",
    ("GATE-041", "not_evaluable_count"): "predates T-0016 (2026-08-14) — B56",
    ("GATE-041", "not_read"): "predates T-0016 (2026-08-14) — B56",
    ("GATE-041", "unread_count"): "predates T-0016 (2026-08-14) — B56",
    ("GATE-041", "mandatory_satisfied"): "predates T-0016 (2026-08-14) — B56",
    ("GATE-040", "cool_off"): "predates T-0016 (2026-08-14) — B56",
    ("GATE-040", "duration_enforced"): "predates T-0016 (2026-08-14) — B56",
    ("GATE-040", "not_evaluable"): "predates T-0016 (2026-08-14) — B56",
    ("GATE-040", "not_read"): "predates T-0016 (2026-08-14) — B56",
    ("GATE-019", "session_gates_unconditional"): "predates T-0016 (2026-08-14) — B56",
    ("GATE-019", "swing_mode_available"): "predates T-0016 (2026-08-14) — B56",
}

#: The inline-invariant grep. DELIBERATELY BROAD — it errs toward flagging, because a false
#: positive costs one named entry above and is visible, while a false negative is silent.
#: This is the WEAKEST of the three signals and is never treated as proof of absence.
INLINE_GREP = re.compile(
    r"""\.state\s*(?:==|!=|\s+in\s+)[^\n]*?["'](?:NOT_EVALUABLE|NOT_READ)["']"""
)

failures: list[str] = []


def fail(title: str, detail: str = "") -> None:
    failures.append(title)
    print(f"FAIL  {title}")
    for line in detail.strip().splitlines():
        if line.strip():
            print(f"      {line.strip()}")


def ok(title: str) -> None:
    print(f"ok    {title}")


def note(line: str) -> None:
    print(f"      {line}")


# ---------------------------------------------------------------------------------------
# Discovery. Criterion 1: ITERATE THE REGISTRY, never name the rules.
#
# 3-ii, Review's method and the reason it is not a grep: a grep answers "where does this
# text appear"; `implementations()` answers "which rules are there". The second question has
# a knowable denominator and the first does not — which is also what hands criterion 6a its
# ratio for free.
# ---------------------------------------------------------------------------------------


def readings_parameter(cls: type) -> str | None:
    """The name of `evaluate`'s condition-readings parameter, or None.

    Discovered from the ANNOTATION rather than from a parameter name, so a rule that calls
    it `conditions` or `inputs` is still found. This is criterion 2's population: "every
    registered implementation that exposes `list[ConditionReading]`".
    """
    fn = getattr(cls, "evaluate", None)
    if fn is None:
        return None
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return None
    for p in sig.parameters.values():
        if "ConditionReading" in str(p.annotation):
            return p.name
    return None


def required_parameters(cls: type, ignoring: str | None = None) -> list[str]:
    """Parameters of `evaluate` with no default, excluding `ignoring`."""
    fn = getattr(cls, "evaluate", None)
    if fn is None:
        return []
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return []
    return [
        p.name
        for p in sig.parameters.values()
        if p.default is inspect.Parameter.empty
        and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
        and p.name != ignoring
    ]


def condition_maps(values: dict[str, Any]) -> dict[str, list[str]]:
    """`values` fields that are a map of condition name -> condition state.

    STRUCTURAL, not by field name: GATE-041 calls it `conditions` and GATE-040 calls it
    `inputs`, and a check keyed to either name would silently stop covering the other one.
    A rule in criterion 2's population whose record exposes NO such map is a FAILURE below,
    not a skip — the probe needs the rule's own condition names to build a control that
    actually reaches a quorum.
    """
    out: dict[str, list[str]] = {}
    for key, value in values.items():
        if isinstance(value, dict) and value and all(
            isinstance(v, str) and v in CONDITION_STATES for v in value.values()
        ):
            out[key] = list(value)
    return out


def main() -> int:  # noqa: C901 - one report, read top to bottom
    impls = rules_pkg.implementations()
    registry_ids = contract.known_rule_ids()

    print("Partially-evaluable rule requirements, over every registered implementation")
    print(f"RULE_REGISTRY.json v{contract.registry_version()}")
    print("=" * 78)

    # Distinct CLASSES, because two registry ids can be one implementation: an alias is the
    # same rule under a second number. Probing GATE-040 twice under GATE-040 and GRADE-035
    # would double every count without examining anything twice.
    by_class: dict[type, list[str]] = {}
    for rid, cls in sorted(impls.items()):
        by_class.setdefault(cls, []).append(rid)

    modules: dict[str, list[str]] = {}
    for rid, cls in sorted(impls.items()):
        modules.setdefault(cls.__module__, []).append(rid)

    # -- criterion 2: no quorum while a condition is unreadable --------------------------
    print("\n-- 2. NO RULE REACHES A VERDICT WITH AN UNREADABLE CONDITION READING --------")

    quorum_population: list[tuple[type, list[str], str]] = []
    for cls, ids in by_class.items():
        param = readings_parameter(cls)
        if param is not None:
            quorum_population.append((cls, ids, param))

    probes_run = 0
    probed_classes = 0
    unprobeable: list[str] = []

    for cls, ids, param in sorted(quorum_population, key=lambda x: x[1][0]):
        label = "/".join(ids)
        if cls.RULE_ID in QUORUM_EXEMPT:
            continue
        blockers = required_parameters(cls, ignoring=param)
        if blockers:
            unprobeable.append(f"{label}: evaluate() also requires {blockers}")
            continue

        # The rule's own condition names, taken from its own default record. A probe built
        # from invented names would score no quorum on any rule and would pass vacuously.
        try:
            default_record = cls.evaluate()
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            unprobeable.append(f"{label}: evaluate() raised {type(exc).__name__}: {exc}")
            continue
        maps = condition_maps(default_record.values)
        if not maps:
            unprobeable.append(
                f"{label}: emits no condition map, so the probe has no names to use"
            )
            continue
        if len(maps) > 1:
            note(
                f"{label} emits {len(maps)} condition maps ({', '.join(sorted(maps))}); "
                f"probing the largest. The others are NOT probed."
            )
        names = max(maps.values(), key=len)

        # THE CONTROL COMES FIRST, AND IT IS THE HALF THAT MAKES THE PROBE MEAN ANYTHING.
        # A rule that returns NOT_APPLICABLE unconditionally passes the unreadable probe
        # perfectly while being completely broken — "blocked" and "always default" are
        # indistinguishable without it. This is the project's signature failure, so the
        # check refuses to report a pass it cannot tell from a dead rule.
        control = cls.evaluate(**{param: [ConditionReading(n, "TRUE") for n in names]})
        if control.verdict == "NOT_APPLICABLE":
            fail(
                f"{label}: all-TRUE control reaches no verdict",
                "Every condition readable and the rule still declines to decide, so the "
                "unreadable probes below would pass against a rule that can never reach a "
                "quorum at all. A vacuous pass, not a compliant rule.",
            )
            continue

        probed_classes += 1
        violations: list[str] = []
        for state in UNREADABLE:
            for i, name in enumerate(names):
                readings = [ConditionReading(n, "TRUE") for n in names]
                readings[i] = ConditionReading(
                    name,
                    state,
                    missing_producer="T-0016 probe" if state == "NOT_EVALUABLE" else None,
                    unread_producer="T-0016 probe" if state == "NOT_READ" else None,
                )
                probes_run += 1
                got = cls.evaluate(**{param: readings})
                if got.verdict != "NOT_APPLICABLE":
                    violations.append(
                        f"{name}={state} -> verdict {got.verdict} "
                        f"(a quorum scored over {len(names) - 1} of {len(names)})"
                    )
        if violations:
            fail(
                f"{label} claims a verdict with an unreadable condition",
                "\n".join(violations)
                + "\nThe denominator silently shrank to the readable subset. Route the "
                "decision through base.quorum_blocked with this rule's own documented "
                "default.",
            )
        else:
            ok(
                f"{label}: {len(names)} conditions x {len(UNREADABLE)} unreadable states, "
                f"control verdict {control.verdict}, every probe NOT_APPLICABLE"
            )

    if unprobeable:
        fail(
            "every rule exposing condition readings could be probed",
            "\n".join(unprobeable)
            + "\nA rule that could not be examined is not a rule that passed. Give it a "
            "no-argument path or a named QUORUM_EXEMPT entry.",
        )

    # -- criterion 3: nobody duplicates the invariant inline ------------------------------
    print("\n-- 3. NO RULE DUPLICATES THE `NOT_EVALUABLE` INVARIANT INLINE ---------------")
    print("      (import binding is the primary signal; the grep is the weakest)")

    inline_failures: list[str] = []
    grep_unlisted: list[str] = []
    grep_flagged: list[str] = []
    uses_conditions: list[str] = []

    for module_name, ids in sorted(modules.items()):
        module = sys.modules.get(module_name)
        if module is None:
            fail(f"{module_name} is registered but not importable")
            continue

        binds_reading = getattr(module, "ConditionReading", None) is ConditionReading
        condition_tables = [
            k
            for k, v in vars(module).items()
            if isinstance(v, (tuple, list)) and "CONDITIONS" in k
        ]
        # IDENTITY, NOT `hasattr`. 3-iii verified `gate_041.quorum_blocked is
        # base.quorum_blocked`, and the identity is what closes the obvious hole: an inline
        # copy written as a module-level function NAMED `quorum_blocked` would satisfy
        # hasattr while being the duplication this criterion exists to catch.
        binds_helper = (
            getattr(module, "quorum_blocked", None) is rules_base.quorum_blocked
        )

        if not (binds_reading or condition_tables):
            continue
        uses_conditions.append(module_name)

        if not binds_helper and module_name not in INLINE_EXEMPT:
            inline_failures.append(
                f"{module_name} ({', '.join(ids)}): uses ConditionReading"
                f"{' and declares ' + ', '.join(condition_tables) if condition_tables else ''}"
                " but does not import base.quorum_blocked"
            )

        source_file = inspect.getsourcefile(module)
        hits = []
        if source_file:
            for n, line in enumerate(
                Path(source_file).read_text(encoding="utf-8").splitlines(), 1
            ):
                if INLINE_GREP.search(line):
                    hits.append(f"{Path(source_file).name}:{n}")
        if hits:
            grep_flagged.append(f"{module_name} [{', '.join(hits)}]")
            if binds_helper and module_name not in GREP_EXEMPT:
                grep_unlisted.append(f"{module_name} [{', '.join(hits)}]")

    if inline_failures:
        fail(
            "no rule module derives the blocked-state invariant inline",
            "\n".join(inline_failures)
            + "\nThe blocked-state default points OPPOSITE ways between rules — CONTINUE "
            "for GATE-041, FORWARD for GATE-040, both conservative. Two inline copies are "
            "SUPPOSED to differ in exactly the place a mistake would appear, so a reviewer "
            "reading both cannot tell a correct opposite from a wrong one. Import "
            "base.quorum_blocked and pass this rule's own default.",
        )
    else:
        ok(
            f"every module using ConditionReading binds base.quorum_blocked itself "
            f"({len(uses_conditions)} of {len(modules)} modules use conditions)"
        )

    if grep_unlisted:
        fail(
            "every grep hit is either a real duplication or a NAMED exemption",
            "\n".join(grep_unlisted)
            + "\nThe import check calls these clean, so they are grep false positives — "
            "resolve by adding a GREP_EXEMPT entry with the reason, never by loosening the "
            "pattern. A looser pattern makes the next false NEGATIVE silent.",
        )
    else:
        ok(
            f"{len(grep_flagged)} grep hit(s), all resolved: real duplication is the "
            "import check's verdict, not the grep's"
        )

    # Verbatim, per criterion 3-iv. A clean grep is not evidence of absence and must never
    # be printed as though it were.
    print('      grep clean + import check passes -> "no instance of the KNOWN pattern".')
    print('                                          NEVER "no duplication".')

    # -- criterion 3a: no emitted field lacks provenance -----------------------------------
    print("\n-- 3a. NO EMITTED `values` KEY LACKS PROVENANCE ------------------------------")

    # EVERY TOP-LEVEL KEY, not a type predicate. A predicate makes the script CLASSIFY, and
    # a field that fails classification is silently not-checked — indistinguishable from a
    # field that passed. Absent-versus-empty, inside the check written against it.
    seen_keys: set[tuple[str, str]] = set()
    used_exemptions: set[tuple[str, str]] = set()
    new_gaps: list[str] = []
    pre_existing_seen: list[str] = []
    provenance_examined: list[str] = []
    provenance_unexamined: list[tuple[str, str]] = []
    keys_examined = 0

    for cls, ids in sorted(by_class.items(), key=lambda x: x[1][0]):
        param = readings_parameter(cls)
        blockers = required_parameters(cls, ignoring=param)
        if getattr(cls, "evaluate", None) is None:
            provenance_unexamined.append(("/".join(ids), "no evaluate() on the class"))
            continue
        if blockers:
            provenance_unexamined.append(
                ("/".join(ids), f"evaluate() requires {blockers}")
            )
            continue

        # BOTH BRANCHES. The blocked path and the decided path emit different key sets —
        # GATE-041's `mandatory_satisfied` exists only when it decides — so examining one
        # record per rule would leave the other branch's fields unchecked while the count
        # said the rule was covered.
        records = []
        try:
            records.append(("default", cls.evaluate()))
            if param is not None:
                maps = condition_maps(records[0][1].values)
                if maps:
                    names = max(maps.values(), key=len)
                    records.append(
                        (
                            "all-TRUE",
                            cls.evaluate(
                                **{param: [ConditionReading(n, "TRUE") for n in names]}
                            ),
                        )
                    )
        except Exception as exc:  # noqa: BLE001
            provenance_unexamined.append(
                ("/".join(ids), f"evaluate() raised {type(exc).__name__}: {exc}")
            )
            continue

        provenance_examined.append(
            f"{'/'.join(ids)} ({', '.join(name for name, _ in records)})"
        )
        # CANONICAL id, once. An alias is the same class, so iterating both registered ids
        # would examine the identical payload twice and demand every baseline line twice.
        rid = cls.RULE_ID
        for _, record in records:
            orphans = sorted(set(record.value_provenance) - set(record.values))
            if orphans:
                fail(
                    f"{rid} declares provenance for a field it does not emit",
                    ", ".join(orphans)
                    + "\nThe mirror of a missing entry, and it fails the same way: a "
                    "provenance line for a field nobody emits is a claim about nothing, "
                    "and it makes the coverage ratio read better than it is.",
                )
            for key in record.values:
                pair = (rid, key)
                if pair in seen_keys:
                    continue
                seen_keys.add(pair)
                keys_examined += 1
                if key in record.value_provenance:
                    continue
                if pair in PROVENANCE_EXEMPT:
                    used_exemptions.add(pair)
                    continue
                if pair in PROVENANCE_PRE_EXISTING:
                    pre_existing_seen.append(f"{rid}.{key}")
                    continue
                new_gaps.append(f"{rid}.{key}")

    if new_gaps:
        fail(
            "every emitted values key has provenance, an exemption, or a baseline entry",
            "\n".join(sorted(new_gaps))
            + "\nMake the value carry its own answer: derived(...) / from_record(...). If "
            "the field genuinely cannot have provenance, add a PROVENANCE_EXEMPT entry "
            "with the reason — the field most likely to be argued with is the one that "
            "cannot say where it came from.",
        )
    else:
        ok(
            f"{keys_examined} emitted keys across "
            f"{len(provenance_examined)} rule(s): no NEW gap"
        )
    if pre_existing_seen:
        note(
            f"PRE-EXISTING, reported and not failing ({len(pre_existing_seen)}): "
            + ", ".join(sorted(pre_existing_seen))
        )

    # -- exemption and baseline hygiene ----------------------------------------------------
    stale: list[str] = []
    for pair in PROVENANCE_EXEMPT:
        if pair not in used_exemptions:
            stale.append(f"PROVENANCE_EXEMPT {pair[0]}.{pair[1]} matched nothing")
    for pair in PROVENANCE_PRE_EXISTING:
        if f"{pair[0]}.{pair[1]}" not in pre_existing_seen:
            stale.append(f"PROVENANCE_PRE_EXISTING {pair[0]}.{pair[1]} matched nothing")
    for module_name in GREP_EXEMPT:
        if not any(f.startswith(module_name + " ") for f in grep_flagged):
            stale.append(f"GREP_EXEMPT {module_name} matched nothing")
    for module_name in INLINE_EXEMPT:
        if module_name not in modules:
            stale.append(f"INLINE_EXEMPT {module_name} is not a rule module")
    for rid in QUORUM_EXEMPT:
        if rid not in impls:
            stale.append(f"QUORUM_EXEMPT {rid} is not a registered rule")
    if stale:
        fail(
            "no exemption or baseline entry is stale",
            "\n".join(stale)
            + "\nAn entry that no longer describes anything is how a list stops being read. "
            "Delete it in the commit that fixed the thing it excused.",
        )
    else:
        ok(
            f"no stale entries ({len(PROVENANCE_EXEMPT)} exempt fields, "
            f"{len(PROVENANCE_PRE_EXISTING)} baselined, {len(GREP_EXEMPT)} grep, "
            f"{len(INLINE_EXEMPT)} inline, {len(QUORUM_EXEMPT)} quorum)"
        )

    # -- criteria 6 / 6a / 3-v: what was covered, with the excluded remainder named --------
    print("\n" + "=" * 78)
    print("WHAT THIS RUN EXAMINED — a check that examines zero rules passes\n")

    # EVERY LINE BELOW ADDS UP TO ITS OWN DENOMINATOR, deliberately. 6a's failure is a
    # numerator with no stated set: "examined 35" reads as thorough against a registry of
    # 117, and 35 is large enough to look like coverage. Review offered its own precedent
    # against itself — a grep-derived implemented set of 48 against the coverage script's
    # 35, used live to place a wave, wrong because neither number said what it had counted.
    implemented_ids = set(impls)
    unimplemented = len(registry_ids) - len(implemented_ids)
    quorum_ids = {i for _, ids, _ in quorum_population for i in ids}
    print(
        f"  registry            {len(registry_ids):>3} rule ids; {len(implemented_ids)} "
        f"implemented, {unimplemented} have no implementation"
    )
    print(
        f"                      those {len(implemented_ids)} ids are "
        f"{len(by_class)} distinct implementations behind "
        f"{len(modules)} modules — an alias id shares its canonical's class"
    )
    print(
        f"  inline duplication  examined {len(modules)} of {len(modules)} rule modules; "
        f"{len(uses_conditions)} use conditions; {len(INLINE_EXEMPT)} exempt"
    )
    print(
        f"  quorum invariant    examined {len(quorum_ids)} of {len(registry_ids)} "
        f"registered; {unimplemented} have no implementation; "
        f"{len(implemented_ids) - len(quorum_ids)} implemented ids expose no condition "
        f"readings; {len(QUORUM_EXEMPT)} exempt"
    )
    print(
        f"                      those {len(quorum_ids)} ids are {probed_classes} "
        f"implementation(s), {probes_run} probes run"
    )
    # 3-v, and it is why the ratio above is not enough on its own: the harness can only
    # invoke a rule whose `evaluate` takes no required arguments. "All rules pass" currently
    # means "the two rules I could call pass", and a check covering two rules produces output
    # IDENTICAL to one covering all of them.
    print(
        f"  rules DECLARING condition readings  {len(quorum_population)} "
        f"of {len(by_class)} implementations"
    )
    for _, ids, _ in sorted(quorum_population, key=lambda x: x[1][0]):
        print(f"                      {'/'.join(ids)}")
    print(
        f"  provenance          examined {len(provenance_examined)} of {len(by_class)} "
        f"implementations ({keys_examined} distinct keys); "
        f"{len(provenance_unexamined)} not invokable"
    )
    for label, reason in provenance_unexamined[:6]:
        print(f"                      excluded {label}: {reason}")
    if len(provenance_unexamined) > 6:
        print(
            f"                      ... and {len(provenance_unexamined) - 6} more, "
            "all excluded for the same two reasons"
        )

    print("\n  EXEMPTIONS IN FORCE — printed every run, because one nobody sees is how a")
    print("  check becomes decorative:")
    if not (QUORUM_EXEMPT or INLINE_EXEMPT or GREP_EXEMPT or PROVENANCE_EXEMPT):
        print("    (none)")
    for rid, reason in sorted(QUORUM_EXEMPT.items()):
        print(f"    quorum      {rid}: {reason}")
    for mod, reason in sorted(INLINE_EXEMPT.items()):
        print(f"    inline      {mod}: {reason}")
    for mod, reason in sorted(GREP_EXEMPT.items()):
        print(f"    grep        {mod.split('.')[-1]}")
        for line in _wrap(reason, 68):
            print(f"                {line}")
    for (rid, key), reason in sorted(PROVENANCE_EXEMPT.items()):
        print(f"    provenance  {rid}.{key}")
        for line in _wrap(reason, 68):
            print(f"                {line}")

    # -- criterion 6b: the limits travel with the result, not only with the plan -----------
    print("\n" + "-" * 78)
    print("WHAT THIS RUN DID NOT VERIFY — a green run is NOT all six standing")
    print("requirements holding:\n")
    print("  * ONLY REQUIREMENTS 1 AND 2 of the six are mechanically checkable. Requirement")
    print("    3 (count it as registered-and-blocked), 4 (report the verdict distribution)")
    print("    and 5 (prove the non-default verdict reachable on a fixture) are per-rule")
    print("    work and are NOT checked here.")
    print("  * THE DIRECTION IS NOT CHECKED. This script checks that a blocked-state default")
    print("    was passed explicitly. It can never check that it was the CORRECT one — that")
    print("    is read out of the rule's own statement, and the two live defaults point")
    print("    opposite ways (CONTINUE for GATE-041, FORWARD for GATE-040).")
    print("  * A CLEAN GREP MEANS \"no instance of the KNOWN pattern\", NEVER \"no")
    print("    duplication\". A rule phrasing the invariant differently escapes it; the")
    print("    import-binding check is the signal that does not depend on phrasing.")
    print("  * PROBES DRIVE `evaluate` DIRECTLY. Nothing here proves the live engine calls")
    print("    these rules at all — no rule has ever decided a live trade.")

    print("=" * 78)
    if failures:
        print(f"FAILED {len(failures)}: " + "; ".join(failures))
        return 1
    print(
        f"PASSED — {probed_classes} rule(s) probed with {probes_run} unreadable-condition "
        f"probes, {len(uses_conditions)} condition-using module(s) checked for inline "
        f"duplication, {keys_examined} emitted keys checked for provenance."
    )
    return 0


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


if __name__ == "__main__":
    raise SystemExit(main())
