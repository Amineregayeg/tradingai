"""T-0021 — the coverage script must not count alias ids as rules (B54).

`GRADE-029` is `alias_of GATE-041` and `GRADE-035` is `alias_of GATE-040`. `base.py`
registers an alias automatically and RAISES if a class claims one directly, so **an alias
can never have its own implementation** — yet the script counted each pair as two rules and
reported one blocked class twice, twice over.

**Ratios survived and absolute counts did not**, which is why it went unnoticed for so long:
aliases inflate numerator and denominator together. The programme's remaining-work figure is
an absolute count.

WHAT THIS FILE CAN AND CANNOT ENFORCE, stated because the cross-tool half is the reason the
task exists. `agents/rule_waves.py` is the other tool that answers "how many rules are
implemented", and **it lives outside this repository** — CI never sees it. So:

  * The counting itself, the alias collapse and the internal invariants are enforced HERE,
    in CI, against a synthetic registry that can be made impossible on purpose.
  * The INTERFACE between the two tools — the `implemented ids:` line that `rule_waves.py`
    parses — is pinned here, so this script cannot silently change the shape the other tool
    reads.
  * The live cross-tool comparison runs only where both files exist. It is in the work
    report, not in CI, and saying so is the point: a skipped test that reads as coverage is
    the thing this project keeps rebuilding.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "check_rule_coverage.py"


def _script():
    spec = importlib.util.spec_from_file_location("check_rule_coverage", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.failures = []
    return module


@pytest.fixture
def crc():
    return _script()


# ---------------------------------------------------------------------------------------
# A synthetic registry, so the impossible cases can be constructed at all. The real one is
# pinned and correct; a check that can only be run against correct data is not a check.
# ---------------------------------------------------------------------------------------


class _Contract:
    def __init__(self, rules: dict[str, dict]):
        self._rules = rules

    def known_rule_ids(self):
        return frozenset(self._rules)

    def registry_version(self):
        return "TEST"

    def alias_target(self, rid):
        return self._rules[rid].get("alias_of")

    def aliases_of(self, rid):
        return tuple(k for k, v in self._rules.items() if v.get("alias_of") == rid)

    def ids_with_enforceability(self, level):
        return frozenset(
            k for k, v in self._rules.items() if v.get("enforceability") == level
        )

    def ids_with_status(self, status):
        return frozenset(k for k, v in self._rules.items() if v.get("status") == status)

    def rule(self, rid):
        return self._rules[rid]


class _Rules:
    def __init__(self, impls: dict[str, type]):
        self._impls = impls

    def implemented_ids(self):
        return frozenset(self._impls)

    def implementations(self):
        return dict(self._impls)


def _blocked_class(blockers: tuple[str, ...]):
    class _Blocked:
        CANNOT_FIRE_WITHOUT = blockers

    return _Blocked


class _Plain:
    CANNOT_FIRE_WITHOUT: tuple[str, ...] = ()


def figures(out: str, label: str) -> tuple[int, int, int, int]:
    """`(ids_num, ids_den, distinct_num, distinct_den)` off one reported row.

    Parsed rather than string-matched, because an assertion pinned to column positions
    fails on a cosmetic change and passes on a wrong number — the wrong way round.
    """
    import re

    row = next(r for r in out.splitlines() if r.strip().startswith(label))
    m = re.search(r"(\d+) / (\d+) ids\s+(\d+) / (\d+) distinct", row)
    assert m, f"{label!r} row is not in the both-spaces form: {row!r}"
    return tuple(int(g) for g in m.groups())  # type: ignore[return-value]


def _install(crc, monkeypatch, tmp_path, rules, impls):
    """Point the script at a synthetic registry and an empty source tree.

    The source scan is aimed at `tmp_path` so checks 1–3 (every RULE_ID resolves, is unique
    and registers) see nothing and pass trivially — this file is about the COUNTING, and
    leaving the real scan in place would fail check 1 against a synthetic registry for a
    reason that has nothing to do with what is under test.
    """
    monkeypatch.setattr(crc, "contract", _Contract(rules))
    monkeypatch.setattr(crc, "rules_pkg", _Rules(impls))
    monkeypatch.setattr(crc, "BACKEND", tmp_path)


def test_the_real_registry_still_passes(crc, capsys):
    """The baseline. Without it every red below could be red for an unrelated reason."""
    assert crc.main() == 0
    out = capsys.readouterr().out
    assert "PASSED" in out
    assert "internally consistent" in out


def test_both_spaces_are_printed_and_labelled(crc, capsys):
    """CRITERION 1 / 2b: a bare number cannot say which set it counted.

    `37 / 91 ids` and `31 / 79 distinct` can be checked against each other. `effective
    coverage` and `distinct implemented` cannot — the reader cannot tell whether a
    contradiction is real or a units mismatch, so a number quoted without its space cannot
    participate in the check that would catch it.
    """
    assert crc.main() == 0
    out = capsys.readouterr().out
    assert "EVERY FIGURE CARRIES ITS SPACE" in out
    for line in ("implemented ", "HARD_GATE covered", "effective coverage"):
        row = next(r for r in out.splitlines() if r.strip().startswith(line.strip()))
        assert " ids" in row and " distinct" in row, row


def test_the_reported_figures_match_an_INDEPENDENT_recomputation(crc, capsys):
    """The script's arithmetic, checked against the registry rather than against a memory.

    AN EARLIER VERSION OF THIS TEST PINNED THE ABSOLUTE NUMBERS (42/117, 34/104) and went
    red the moment T-0019 landed three rules — correctly reporting a change that was not a
    defect. A test that must be edited every time the programme progresses gets edited
    without being read, and then it is pinning whatever was there last rather than checking
    anything. So the expectation is DERIVED here, from the same registry, by a different
    route than the script takes: if the two ever disagree, one of them is wrong.
    """
    from app.services import rules as real_rules
    from app.services.telemetry import contract_loader as real_contract

    canon = lambda rid: real_contract.alias_target(rid) or rid  # noqa: E731
    ids = real_contract.known_rule_ids()
    impl = real_rules.implemented_ids()
    hard = real_contract.ids_with_enforceability("HARD_GATE")
    blocked = {
        rid for rid, cls in real_rules.implementations().items()
        if getattr(cls, "CANNOT_FIRE_WITHOUT", None)
    }

    assert crc.main() == 0
    out = capsys.readouterr().out

    assert figures(out, "implemented ") == (
        len(impl), len(ids), len({canon(i) for i in impl}), len({canon(i) for i in ids})
    )
    assert figures(out, "HARD_GATE covered") == (
        len(impl & hard), len(hard),
        len({canon(i) for i in impl} & {canon(i) for i in hard}),
        len({canon(i) for i in hard}),
    )
    # The alias population is the whole reason both spaces exist, so it is asserted too.
    assert len(ids) - len({canon(i) for i in ids}) == sum(
        1 for i in ids if real_contract.alias_target(i)
    )
    assert f"CANNOT FIRE  {len({canon(i) for i in blocked}):>3} distinct" in out
    assert f"({len(blocked)} ids incl. aliases)" in out


def test_an_added_alias_does_not_increase_the_distinct_count(crc, monkeypatch, tmp_path, capsys):
    """CRITERION 4, and it is the whole defect in one fixture.

    A registry entry whose only content is `alias_of` an implemented rule is not work. It
    must move the `ids` figures and leave the `distinct` figures exactly where they were.
    """
    rules = {
        "GATE-100": {"id": "GATE-100", "enforceability": "HARD_GATE"},
        "GATE-101": {"id": "GATE-101", "enforceability": "HARD_GATE"},
    }
    impls = {"GATE-100": _Plain}

    _install(crc, monkeypatch, tmp_path, rules, impls)
    assert crc.main() == 0
    before = figures(capsys.readouterr().out, "implemented ")
    assert before == (1, 2, 1, 2), before

    # The two-line fixture: one alias id, pointing at the implemented rule, and its
    # automatic registration — which is what base.py does for a real alias.
    rules["GRADE-900"] = {
        "id": "GRADE-900",
        "alias_of": "GATE-100",
        "enforceability": "HARD_GATE",
    }
    impls["GRADE-900"] = _Plain

    crc2 = _script()
    _install(crc2, monkeypatch, tmp_path, rules, impls)
    assert crc2.main() == 0
    after = figures(capsys.readouterr().out, "implemented ")

    # ids move — the registry really does contain one more entry, and hiding that would be
    # the opposite error.
    assert after[:2] == (2, 3), after
    # distinct does NOT move. This is the assertion the whole task exists for, and it is
    # what the script got wrong: an alias landed in `implemented` as a rule to be counted.
    assert after[2:] == (1, 2), after


def test_cannot_fire_reports_distinct_rules_and_names_the_alias_faces(crc, capsys):
    """CRITERION 3. GATE-040 and GATE-041 — not four entries."""
    assert crc.main() == 0
    out = capsys.readouterr().out
    assert "GATE-040  blocked:" in out and "GATE-041  blocked:" in out
    assert "GRADE-029  blocked:" not in out
    assert "GRADE-035  blocked:" not in out
    # The alias faces are NAMED rather than dropped: they exist in the registry and a reader
    # who greps for GRADE-035 must still find it here.
    assert "also registered as GRADE-035" in out
    assert "also registered as GRADE-029" in out


def test_the_tool_refuses_to_print_an_impossible_set(crc, monkeypatch, tmp_path, capsys):
    """CRITERION 2a, and the case is REACHABLE rather than theoretical.

    `effective` used to subtract ALL blocked rules from a HARD_GATE-only numerator, so a
    blocked SOFT_PREFERENCE was deducted from a total it was never in — and with enough of
    them the figure goes negative. Correct today only because both blocked rules happen to
    be HARD_GATEs. This drives the case the old arithmetic could not survive.
    """
    rules = {
        "GATE-100": {"id": "GATE-100", "enforceability": "HARD_GATE"},
        "GRADE-800": {"id": "GRADE-800", "enforceability": "SOFT_PREFERENCE"},
        "GRADE-801": {"id": "GRADE-801", "enforceability": "SOFT_PREFERENCE"},
    }
    impls = {
        "GATE-100": _Plain,
        "GRADE-800": _blocked_class(("GRADE-028",)),
        "GRADE-801": _blocked_class(("GRADE-028",)),
    }
    _install(crc, monkeypatch, tmp_path, rules, impls)

    assert crc.main() == 0, "two blocked SOFT_PREFERENCEs must not make coverage negative"
    out = capsys.readouterr().out
    assert "internally consistent" in out
    # 1 HARD_GATE implemented, 0 of the blocked rules are HARD_GATE, so effective is 1.
    # The OLD arithmetic computed 1 - 2 = -1 and would have printed it.
    assert figures(out, "effective coverage")[:2] == (1, 1), out


def test_the_invariant_check_bites(crc, monkeypatch, tmp_path, capsys):
    """The guard must be shown to fail, or it is decoration.

    Forcing `collapse` to be the identity makes distinct == ids everywhere, which is still
    consistent — so instead this breaks the one relationship the report is quoted on, by
    making a blocked rule that is not implemented at all.
    """
    rules = {"GATE-100": {"id": "GATE-100", "enforceability": "HARD_GATE"}}
    impls = {"GATE-100": _Plain}
    _install(crc, monkeypatch, tmp_path, rules, impls)
    monkeypatch.setattr(
        crc, "collapse", lambda ids: set(ids) | {"PHANTOM-999", "PHANTOM-998"}
    )

    assert crc.main() == 1
    out = capsys.readouterr().out
    assert "the counts above are internally consistent" in out
    assert "FAIL" in out
    assert "do not quote any figure from this run" in out


def test_the_implemented_ids_line_keeps_the_shape_rule_waves_parses(crc, capsys):
    """CRITERION 2's durable half, and the honest statement of its limit.

    `agents/rule_waves.py` reads this script's output with `implemented ids:\\s*(.+)` and
    collapses aliases itself. That file is OUTSIDE this repository, so nothing in CI can
    catch a change here that breaks it. Pinning the interface is the half that can be
    enforced: the two tools cannot diverge through THIS side changing shape unnoticed.

    The live comparison of the two tools' numbers is in T-0021's work report, run by hand
    where both files exist. It is not in CI and this docstring is where that is admitted.
    """
    import re

    assert crc.main() == 0
    out = capsys.readouterr().out
    m = re.search(r"implemented ids:\s*(.+)", out)
    assert m, "rule_waves.py parses exactly this and would fall back to a FATAL"
    from app.services import rules as real_rules

    ids = [i.strip() for i in m.group(1).split(",")]
    # Derived, not pinned — see the recomputation test above for why.
    assert len(ids) == len(real_rules.implemented_ids()), ids
    assert "GRADE-029" in ids and "GRADE-035" in ids, (
        "the ids line is ID space and must stay that way — rule_waves.py collapses it "
        "itself, so pre-collapsing here would make the other tool count 34 as 34 while "
        "believing it had collapsed 42"
    )
    # And the distinct set is published beside it, so a future consumer need not re-derive
    # the collapse and get it wrong a third time.
    d = re.search(r"distinct implemented:\s*(.+)", out)
    assert d, "the distinct set must be published, not left to be recomputed"
    from app.services.telemetry import contract_loader as real_contract

    expected = {real_contract.alias_target(i) or i for i in real_rules.implemented_ids()}
    assert len([i.strip() for i in d.group(1).split(",")]) == len(expected)
