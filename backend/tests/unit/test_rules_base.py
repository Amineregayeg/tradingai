"""Rule implementations carry their contract id (M2).

The contract calls this the load-bearing integration point: rule ids are the join key for
conformance *and* for the learning loop, so they must live in the source, not only in the
logs. These tests pin the properties that make that link trustworthy — an id cannot be
invented, cannot be claimed twice, and cannot drift between the code and the record it
emits.
"""
from __future__ import annotations

from datetime import datetime, timezone
import subprocess
import sys
from pathlib import Path

import pytest

from app.services import rules as rules_pkg
from app.services.rules.base import (
    DuplicateRuleImplementation,
    RuleImplementation,
    open_rule_requires_declared_parameter,
)
from app.services.rules.gate_023_timezone import NewYorkTimestamps
from app.services.telemetry import contract_loader as contract


@pytest.fixture(autouse=True)
def isolate_registry():
    """Restore the process-wide implementation registry around every test.

    Several tests below define RuleImplementation subclasses, which self-register. Without
    this they would leak into `implemented_ids()` and the coverage report would count test
    fixtures as engine capability — a coverage number that overstates itself is worse than
    none.
    """
    from app.services.rules import base

    saved = dict(base._IMPLEMENTATIONS)  # noqa: SLF001
    try:
        yield
    finally:
        base._IMPLEMENTATIONS.clear()  # noqa: SLF001
        base._IMPLEMENTATIONS.update(saved)  # noqa: SLF001


# ---------------------------------------------------------------------------
# The id cannot be wrong
# ---------------------------------------------------------------------------
def test_an_unknown_rule_id_fails_at_class_definition():
    """A typo becomes an ImportError at startup — the cheapest possible moment, rather
    than telemetry that conformance C-3 rejects weeks later."""
    with pytest.raises(KeyError, match="GATE-999"):

        class Bogus(RuleImplementation):
            RULE_ID = "GATE-999"


def test_an_implementation_without_an_id_is_refused():
    with pytest.raises(TypeError, match="RULE_ID"):

        class Anonymous(RuleImplementation):
            pass


def test_two_classes_cannot_claim_one_rule():
    """Two behaviours behind one id makes the attribution ledger ambiguous — outcomes
    would accumulate against a rule that means different things in different places."""

    class First(RuleImplementation):
        RULE_ID = "GATE-015"

    with pytest.raises(DuplicateRuleImplementation, match="GATE-015"):

        class Second(RuleImplementation):
            RULE_ID = "GATE-015"


def test_the_emitted_id_comes_from_the_constant():
    """There is only one id, so the code and the record cannot disagree."""
    ev = NewYorkTimestamps.evaluation("PASS")
    assert ev.rule_id == NewYorkTimestamps.RULE_ID == "GATE-023"
    assert ev.as_dict()["enforceability"] == contract.enforceability_of("GATE-023")


# ---------------------------------------------------------------------------
# OPEN rules
# ---------------------------------------------------------------------------
def test_an_open_rule_reaching_a_verdict_without_a_declared_parameter_is_flagged():
    """Fourteen rules are OPEN because the trader explicitly declined to fix a value.
    Inventing one produces an engine that is off-doctrine by construction and cannot be
    validated against anything in the corpus (conformance C-05)."""
    open_id = sorted(contract.ids_with_status("OPEN"))[0]

    class OpenRule(RuleImplementation):
        RULE_ID = open_id

    invented = OpenRule.evaluation("PASS", values={"threshold": 0.5})
    assert open_rule_requires_declared_parameter(invented) is not None

    declared = OpenRule.evaluation(
        "PASS", values={"threshold": 0.5}, declared_parameter_used="reverse_quorum"
    )
    assert open_rule_requires_declared_parameter(declared) is None


def test_a_ready_rule_needs_no_declared_parameter():
    ev = NewYorkTimestamps.evaluation("PASS")
    assert open_rule_requires_declared_parameter(ev) is None


# ---------------------------------------------------------------------------
# GATE-023 itself
# ---------------------------------------------------------------------------
def test_the_offset_follows_daylight_saving():
    """The evidence that a tz database was consulted rather than a constant applied.
    A fixed offset shifts the news blackout, magic zone, 19:00 close and every session
    range by an hour for half the year — silently, and in one direction."""
    summer = NewYorkTimestamps.evaluate(datetime(2026, 8, 4, 13, 0, tzinfo=timezone.utc))
    winter = NewYorkTimestamps.evaluate(datetime(2026, 1, 4, 13, 0, tzinfo=timezone.utc))

    assert summer.verdict == "PASS" and summer.values["tz_offset_used"] == "-04:00"
    assert winter.verdict == "PASS" and winter.values["tz_offset_used"] == "-05:00"
    assert summer.values["dst_in_effect"] is True
    assert winter.values["dst_in_effect"] is False


def test_a_naive_timestamp_fails_the_gate_rather_than_raising():
    """A hard gate that throws produces no record — losing exactly the evidence that
    something is misconfigured. The failure must be telemetry, not an exception."""
    ev = NewYorkTimestamps.evaluate(datetime(2026, 8, 4, 13, 0))
    assert ev.verdict == "FAIL"
    assert ev.values["tz_aware"] is False


def test_every_value_names_where_it_came_from():
    """Without provenance, `values` re-derives only itself — and a banned input passes
    every name-based check under a new name."""
    ev = NewYorkTimestamps.evaluate(datetime(2026, 8, 4, 13, 0, tzinfo=timezone.utc))
    assert set(ev.values) == set(ev.value_provenance)
    assert all("source" in p for p in ev.value_provenance.values())


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
def test_every_rule_module_on_disk_is_imported():
    """A rule implementation nothing imports is invisible to the coverage report — it
    counts as unimplemented while sitting in the tree, which is the one failure mode a
    coverage report must not have."""
    pkg_dir = Path(rules_pkg.__file__).parent
    # Modules in this package that deliberately register NO rule. An ALLOWLIST rather
    # than a predicate, so adding one stays a deliberate act: a new unregistered module
    # still fails this test until someone writes down why it is exempt.
    #
    # `consolidation` is a primitive the CONTRACT ASSUMES AND NEVER DEFINES — GRADE-035's
    # inputs name a consolidation/overlap detector that exists nowhere in the registry.
    # Giving it a RULE_ID would assert the registry defines a rule it does not.
    NOT_RULES = {"__init__", "base", "consolidation"}
    on_disk = {p.stem for p in pkg_dir.glob("*.py") if p.stem not in NOT_RULES}
    imported = {
        cls.__module__.rsplit(".", 1)[-1] for cls in rules_pkg.implementations().values()
    }
    # THE MESSAGE SAYS WHAT THE ASSERTION CAN SUPPORT, AND NO MORE (B93).
    # `implementations()` is a PROCESS-GLOBAL registry populated by any import, so this can
    # only ever say "was this registered in THIS interpreter" — and pytest imports every
    # collected test module before running any, so a test file that imports a rule module
    # directly satisfies it whether or not `rules/__init__.py` mentions the module. The old
    # message read "not imported by rules/__init__.py", a specific claim about a specific
    # file that this assertion never checks, and it is the sentence someone trusts while
    # debugging. `test_the_package_alone_registers_every_rule_module` below is the one that
    # can actually make that claim.
    assert on_disk <= imported, (
        f"not registered in this interpreter: {sorted(on_disk - imported)}. "
        "This does NOT establish that rules/__init__.py is missing them — this registry is "
        "process-global and any import populates it. See "
        "test_the_package_alone_registers_every_rule_module for the check that does."
    )


def test_the_package_alone_registers_every_rule_module():
    """THE GUARD ABOVE IS VACUOUS FOR MOST MODULES. This is the one that is not (B93).

    Measured, not asserted. Of the 26 modules in the guard's own domain (29 `.py` in
    `rules/` minus the three `NOT_RULES` exclusions at `test_rules_base.py:157`), **23 are
    imported directly by some test module**, and pytest imports every collected test module
    before running any test. So for those 23 the assertion above is satisfied by the test
    suite's own import side effects, and deleting them from `rules/__init__.py` leaves the
    whole suite green while `check_rule_coverage.py` correctly reports them unimplemented.

    That is not hypothetical: it happened to EXIT-004 / TARGET-001 / TARGET-003 during
    T-0023, when an `__init__.py` edit was reverted in the shared tree. Fifty tests stayed
    green, the guard above stayed green, and the coverage tool held at 39/104 — two
    instruments disagreeing silently, **with the suite being the wrong one.**

    So this spawns a clean interpreter that imports ONLY the package. No test file's imports
    can reach it.

    ITS OWN LIMIT, MEASURED THE SAME WAY RATHER THAN CAVEATED: rule modules import each
    other, so removing ONE module's import block from `rules/__init__.py` often leaves it
    registered anyway through a sibling. Removing each of the 26 in turn and re-importing
    the package in a clean interpreter: **15 of 26 stay registered via a sibling (this test
    is blind to those), 11 of 26 genuinely lose registration (this test catches those).**
    It reliably catches a GROUP going missing — which is the case that occurred — and not
    every single dropped line.
    """
    result = subprocess.run(
        [
            sys.executable, "-c",
            "from app.services.rules import implementations;"
            "print(','.join(sorted({c.__module__.rsplit('.',1)[-1] "
            "for c in implementations().values()})))",
        ],
        cwd=Path(rules_pkg.__file__).parents[3],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"importing the package alone failed:\n{result.stderr}"
    registered = set(result.stdout.strip().split(","))

    pkg_dir = Path(rules_pkg.__file__).parent
    NOT_RULES = {"__init__", "base", "consolidation"}
    on_disk = {p.stem for p in pkg_dir.glob("*.py") if p.stem not in NOT_RULES}

    assert on_disk, "no rule modules found on disk — the scan is not looking where it thinks"
    missing = sorted(on_disk - registered)
    assert not missing, (
        f"rules/__init__.py does not register: {missing}. These rule modules exist on disk "
        "and the suite may well be green — a test importing them directly is enough for "
        "that — but check_rule_coverage.py counts them as UNIMPLEMENTED, because a rule "
        "nothing imports is invisible to the coverage report."
    )


def test_the_registry_reports_what_is_actually_implemented():
    ids = rules_pkg.implemented_ids()
    assert "GATE-023" in ids
    assert ids <= contract.known_rule_ids(), "an implemented id is not in the registry"


# ---------------------------------------------------------------------------
# Alias ids (M4)
# ---------------------------------------------------------------------------
def test_implementing_a_rule_also_covers_the_ids_that_restate_it():
    """Thirteen GRADE ids carry `alias_of` because two extraction passes produced the same
    rule twice. They are not duplicates to clean up — the id policy is STABLE and stored
    telemetry may cite either forever — so one implementation must satisfy both."""
    from app.services.rules.gate_002_disturbance import (
        DisturbanceClassifier,
        HeavyDisturbanceSkip,
    )
    from app.services.rules.gate_008_roster import LayoutRoster

    impls = rules_pkg.implementations()
    assert impls["GRADE-010"] is DisturbanceClassifier, "GATE-002's alias"
    assert impls["GRADE-011"] is HeavyDisturbanceSkip, "GATE-001's alias"
    assert impls["GRADE-012"] is LayoutRoster, "GATE-008's alias"


def test_an_alias_is_registered_the_moment_its_canonical_is():
    """GATE-046 is not implemented, so this shows the registration itself rather than a
    coincidence of M4's import order."""
    assert "GRADE-023" not in rules_pkg.implemented_ids()

    class HouseRatio(RuleImplementation):
        RULE_ID = "GATE-046"

    assert rules_pkg.implementations()["GRADE-023"] is HouseRatio


def test_claiming_the_alias_instead_of_the_canonical_is_refused():
    """Claiming GRADE-023 would leave GATE-046 looking unimplemented while GRADE-023 looked
    covered — a coverage report wrong in both directions at once."""
    with pytest.raises(TypeError, match="alias_of GATE-046"):
        class Backwards(RuleImplementation):
            RULE_ID = "GRADE-023"


def test_a_second_class_cannot_claim_a_canonical_already_taken():
    class First(RuleImplementation):
        RULE_ID = "GATE-046"

    with pytest.raises(DuplicateRuleImplementation):
        class Second(RuleImplementation):
            RULE_ID = "GATE-046"


def test_every_alias_in_the_registry_points_at_a_real_rule():
    for rule_id in contract.known_rule_ids():
        target = contract.alias_target(rule_id)
        if target is None:
            continue
        assert target in contract.known_rule_ids()
        assert rule_id in contract.aliases_of(target)
        assert contract.alias_target(target) is None, "an alias may not point at an alias"
