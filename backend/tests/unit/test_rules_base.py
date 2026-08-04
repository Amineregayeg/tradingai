"""Rule implementations carry their contract id (M2).

The contract calls this the load-bearing integration point: rule ids are the join key for
conformance *and* for the learning loop, so they must live in the source, not only in the
logs. These tests pin the properties that make that link trustworthy — an id cannot be
invented, cannot be claimed twice, and cannot drift between the code and the record it
emits.
"""
from __future__ import annotations

from datetime import datetime, timezone
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
    on_disk = {
        p.stem
        for p in pkg_dir.glob("*.py")
        if p.stem not in {"__init__", "base"}
    }
    imported = {
        cls.__module__.rsplit(".", 1)[-1] for cls in rules_pkg.implementations().values()
    }
    assert on_disk <= imported, f"not imported by rules/__init__.py: {sorted(on_disk - imported)}"


def test_the_registry_reports_what_is_actually_implemented():
    ids = rules_pkg.implemented_ids()
    assert "GATE-023" in ids
    assert ids <= contract.known_rule_ids(), "an implemented id is not in the registry"
