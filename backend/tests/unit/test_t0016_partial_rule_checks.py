"""T-0016 — the registry-wide partially-evaluable checks must BITE (criterion 4).

`scripts/check_partial_rules.py` returning 0 proves nothing on its own: a check that
examines zero rules passes, and so does one whose assertions cannot fail. The mutations in
the work report drove each check red against the REAL rules; this file is what keeps that
property alive after those mutations were reverted.

WHY A DOUBLE HERE WHEN THE REPORT USED REAL RULES. The report's mutations edited
`gate_041_reverse_switch.py` and could not be left in the tree. A permanent test needs a
violation that can live in the repo, so each test injects one rule-shaped double into the
population the script iterates and asserts the script goes red. The double is never
registered — it is a plain class handed to a patched `implementations()` — so nothing here
can leak a rule id into `_IMPLEMENTATIONS` for the rest of the suite.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.services import rules as rules_pkg
from app.services.rules import base as rules_base
from app.services.rules.base import ConditionReading
from app.services.telemetry.records import RuleEvaluation, derived

#: A real registry id with no implementation, so `RuleEvaluation.__post_init__` accepts it.
#: An invented id would raise at construction, which is the wrong failure.
DOUBLE_ID = "GATE-011"


def _script():
    """Load the check script as a module, the way T-0016's other tests load the resolver."""
    path = Path(__file__).resolve().parents[3] / "scripts" / "check_partial_rules.py"
    spec = importlib.util.spec_from_file_location("check_partial_rules", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script():
    mod = _script()
    # `failures` is module-level, so a second run in the same process would inherit the
    # first one's failures and every later assertion would be meaningless.
    mod.failures = []
    return mod


def _double(*, provenance: bool = True):
    """A rule that scores its quorum over the READABLE SUBSET — the defect itself.

    This is base.py's own documented failure: "a rule that counts its TRUE conditions and
    reaches quorum while one condition is NOT_EVALUABLE has claimed a quorum on incomplete
    evidence — the denominator silently shrinks to the readable subset."
    """

    class _ShrunkenDenominator:
        RULE_ID = DOUBLE_ID

        @classmethod
        def evaluate(
            cls, readings: list[ConditionReading] | None = None
        ) -> RuleEvaluation:
            rs = readings if readings is not None else [
                ConditionReading("alpha", "NOT_EVALUABLE", missing_producer="nothing"),
                ConditionReading("beta", "TRUE"),
                ConditionReading("gamma", "TRUE"),
            ]
            readable = [r for r in rs if r.state in ("TRUE", "FALSE")]
            satisfied = [r for r in readable if r.state == "TRUE"]
            values = {"conditions": {r.name: r.state for r in rs}}
            return RuleEvaluation(
                rule_id=cls.RULE_ID,
                verdict="PASS" if len(satisfied) >= 2 else "FAIL",
                values=values,
                value_provenance=(
                    {"conditions": derived("the double's conditions")}
                    if provenance
                    else {}
                ),
            )

    return _ShrunkenDenominator


def _with_double(monkeypatch, cls) -> None:
    population = dict(rules_pkg.implementations())
    population[cls.RULE_ID] = cls
    monkeypatch.setattr(rules_pkg, "implementations", lambda: population)


def test_the_check_is_green_on_the_real_registry(script, capsys):
    """The baseline. Without it, every red below could be red for an unrelated reason."""
    assert script.main() == 0
    out = capsys.readouterr().out
    assert "PASSED" in out
    # Criterion 6: a check that examines zero rules passes, so the count is the only thing
    # separating "all compliant" from "found nothing to look at".
    assert "probes run" in out
    assert "examined" in out


def test_a_quorum_scored_over_a_shrunken_denominator_is_caught(
    script, monkeypatch, capsys
):
    """CRITERION 2. The probe flips one condition to unreadable and the rule must decline."""
    _with_double(monkeypatch, _double())
    assert script.main() == 1
    out = capsys.readouterr().out
    assert "claims a verdict with an unreadable condition" in out
    assert DOUBLE_ID in out
    # Both absences must block, not only the permanent one: NOT_READ means a producer
    # exists and nothing called it, which is no more readable than one that does not exist.
    assert "NOT_EVALUABLE ->" in out
    assert "NOT_READ ->" in out


def test_a_rule_that_can_never_reach_a_verdict_is_a_failure_not_a_pass(
    script, monkeypatch, capsys
):
    """The CONTROL half, and it is what stops the probe passing vacuously.

    A rule returning NOT_APPLICABLE unconditionally satisfies every unreadable probe
    perfectly while being completely broken. "Blocked" and "always default" are
    indistinguishable without an all-TRUE control — this project's signature failure, so
    the script refuses to report a pass it cannot tell from a dead rule.
    """

    class _NeverDecides:
        RULE_ID = DOUBLE_ID

        @classmethod
        def evaluate(
            cls, readings: list[ConditionReading] | None = None
        ) -> RuleEvaluation:
            rs = readings or [ConditionReading("alpha", "TRUE")]
            return RuleEvaluation(
                rule_id=cls.RULE_ID,
                verdict="NOT_APPLICABLE",
                values={"conditions": {r.name: r.state for r in rs}},
                value_provenance={"conditions": derived("the double's conditions")},
            )

    _with_double(monkeypatch, _NeverDecides)
    assert script.main() == 1
    assert "all-TRUE control reaches no verdict" in capsys.readouterr().out


def test_a_rule_exposing_readings_that_cannot_be_probed_fails(
    script, monkeypatch, capsys
):
    """Silence is not a pass. A rule the check could not examine is a FAILURE, never a skip."""

    class _NeedsMoreArguments:
        RULE_ID = DOUBLE_ID

        @classmethod
        def evaluate(
            cls, bars, readings: list[ConditionReading] | None = None
        ) -> RuleEvaluation:  # pragma: no cover - never called
            raise AssertionError("unreachable")

    _with_double(monkeypatch, _NeedsMoreArguments)
    assert script.main() == 1
    out = capsys.readouterr().out
    assert "every rule exposing condition readings could be probed" in out
    assert "evaluate() also requires ['bars']" in out


def test_the_binding_check_is_IDENTITY_and_not_hasattr(script, monkeypatch, capsys):
    """CRITERION 3 / 3-iii, and the hole `hasattr` alone would leave wide open.

    An inline copy written as a module-level function NAMED `quorum_blocked` satisfies
    `hasattr` while being exactly the duplication this criterion exists to catch. Only the
    identity against `base.quorum_blocked` separates them.
    """
    import app.services.rules.gate_041_reverse_switch as gate_041

    def _lookalike(readings, *, default_outcome):  # pragma: no cover - never invoked
        raise AssertionError("unreachable")

    monkeypatch.setattr(gate_041, "quorum_blocked", _lookalike)
    assert hasattr(gate_041, "quorum_blocked"), "the hasattr check would have passed here"
    assert gate_041.quorum_blocked is not rules_base.quorum_blocked

    assert script.main() == 1
    out = capsys.readouterr().out
    assert "derives the blocked-state invariant inline" in out
    assert "gate_041_reverse_switch" in out


def test_a_new_emitted_field_without_provenance_fails(script, monkeypatch, capsys):
    """CRITERION 3a. Every top-level key of `values`, not a type predicate."""
    _with_double(monkeypatch, _double(provenance=False))
    assert script.main() == 1
    out = capsys.readouterr().out
    assert "every emitted values key has provenance" in out
    assert f"{DOUBLE_ID}.conditions" in out


def test_the_pre_existing_baseline_reports_without_failing(script, capsys):
    """CRITERION 3a's ratchet: eleven known gaps are printed on every run and do not fail.

    A check that landed red would be switched off within a day. The ratchet is the version
    that survives — and the entries are printed rather than merely tolerated, because an
    exemption nobody sees is how a check becomes decorative.
    """
    assert script.main() == 0
    out = capsys.readouterr().out
    assert "PRE-EXISTING, reported and not failing (11)" in out
    for field in ("GATE-041.conditions_total", "GATE-040.cool_off"):
        assert field in out


def test_a_baseline_entry_that_no_longer_describes_anything_fails(script, capsys):
    """Fixing a gap means DELETING its baseline line, in the same commit.

    Without this, the list outlives the thing it excused and quietly grows into a
    permanent allowance — which is what an exemption list becomes when nobody prunes it.
    """
    script.PROVENANCE_PRE_EXISTING = {
        **script.PROVENANCE_PRE_EXISTING,
        ("GATE-041", "a_field_that_was_never_emitted"): "invented by this test",
    }
    assert script.main() == 1
    out = capsys.readouterr().out
    assert "no exemption or baseline entry is stale" in out
    assert "a_field_that_was_never_emitted matched nothing" in out


def test_an_unlisted_grep_hit_fails_rather_than_being_skipped(script, capsys):
    """CRITERION 3-iv / 5: a grep false positive is resolved by NAMING it.

    Never by loosening the pattern — a looser pattern makes the next false NEGATIVE
    silent, and the grep's failure mode is already the silent one.
    """
    script.GREP_EXEMPT = {}
    assert script.main() == 1
    out = capsys.readouterr().out
    assert "every grep hit is either a real duplication or a NAMED exemption" in out


def test_the_run_states_what_it_did_not_verify(script, capsys):
    """CRITERION 6b. The limits must travel with the RESULT, not only with the plan.

    Otherwise a green run reads as all six standing requirements holding — the decorative
    check arriving through the tool built to police decorative checks.
    """
    assert script.main() == 0
    out = capsys.readouterr().out
    assert "WHAT THIS RUN DID NOT VERIFY" in out
    assert "ONLY REQUIREMENTS 1 AND 2" in out
    assert "THE DIRECTION IS NOT CHECKED" in out
    # Verbatim, per criterion 3-iv: a clean grep is never proof of absence.
    assert '"no instance of the KNOWN pattern"' in out
    assert 'NEVER "no duplication"' in out


def test_the_exemptions_in_force_are_printed_on_every_run(script, capsys):
    """CRITERION 5. An exemption nobody sees is how a check becomes decorative (B41)."""
    assert script.main() == 0
    out = capsys.readouterr().out
    assert "EXEMPTIONS IN FORCE" in out
    assert "GATE-041.outcome" in out
    assert "GATE-040.mode" in out


def test_the_check_names_no_rule_it_covers(script):
    """CRITERION 1, the load-bearing one: the check ITERATES, it does not enumerate.

    A test that names the rules it covers is true of the rules someone remembered to add —
    the failure mode of every hand-maintained list on this project. The only rule ids the
    script may carry are inside the exemption tables, where each one is a NAMED entry with
    a reason that gets printed.
    """
    source = Path(script.__file__).read_text(encoding="utf-8")
    import re

    exempt_ids = {
        *script.QUORUM_EXEMPT,
        *(rid for rid, _ in script.PROVENANCE_EXEMPT),
        *(rid for rid, _ in script.PROVENANCE_PRE_EXISTING),
    }
    # Only the executable half — the module docstring and comments argue about specific
    # rules on purpose, and prose cannot make the check cover the wrong set.
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    code = code.split('"""', 2)[-1]
    found = set(re.findall(r'"([A-Z]+-\d{3})"', code))
    assert found <= exempt_ids, (
        f"{sorted(found - exempt_ids)} are named in the check's own logic. Enumerate from "
        "implementations() instead — a rule added tomorrow must be covered without anyone "
        "remembering."
    )


def test_the_double_never_leaked_into_the_registry():
    """The doubles above are plain classes, so nothing can register DOUBLE_ID for real.

    Ordered last on purpose. If a future edit makes one of them subclass
    RuleImplementation, `_IMPLEMENTATIONS` gains a permanent entry and every coverage
    figure in the project goes up by one for no reason.
    """
    assert DOUBLE_ID not in rules_pkg.implemented_ids()
    assert rules_pkg.implementations() is not None, "implementations() was left patched"
