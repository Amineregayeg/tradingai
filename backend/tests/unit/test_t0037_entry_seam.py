"""T-0037 — the entry rules evaluated alongside the live decision, deciding nothing.

**The value here is the SEAM, not the rate.** A disagreement rate over one rule is thin and is not
dressed as more; what a later cutover task needs is the harness — the triple, the `NOT_COMPARABLE`
reasons, failure isolation, and rows keyed on the registered id — and the one-rule rate is its first
tenant.

**Both arms are here and neither substitutes for the other:** an injected disagreement must move the
NUMERATOR, and **the DENOMINATOR must be observed non-zero from real bars in a pass with nothing
injected.** *An injected disagreement necessarily creates its own comparable pair, so the must-fire
arm proves the injection works and says nothing about whether the population exists.*
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from app.services.live.decision_trace import DecisionTrace
from app.services.live.entry_comparison import (
    COMPARABLE_RULE_IDS,
    GATE_NAME,
    INPUT_COUNT_SUFFIXES,
    EntryComparison,
    RuleComparison,
    compare_entry,
    examined_nothing,
)
from app.services.live.shadow import _bars_from_frame
from app.services.rules.base import implementations

BACKEND = Path(__file__).resolve().parents[2]
CORPUS = BACKEND / "tests" / "fixtures" / "btcusdtp_5m_1500.csv"


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    return pd.read_csv(CORPUS, parse_dates=["time"]).set_index("time").rename_axis("timestamp")


def _bars(frame: pd.DataFrame, end: int, n: int = 320):
    return _bars_from_frame(frame.iloc[end - n:end])


def _flat_bars(n: int = 20):
    """Identical candles — no gap can form between them, so the inventory is empty."""
    t0 = datetime(2026, 5, 1, tzinfo=timezone.utc)
    rows = [
        {"timestamp": t0 + timedelta(minutes=5 * i),
         "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0}
        for i in range(n)
    ]
    return _bars_from_frame(pd.DataFrame(rows).set_index("timestamp"))


def _trace(*, took: bool = False, blocked: str | None = None) -> DecisionTrace:
    """A trace as `evaluate_latest_bar_traced` would leave it.

    `reached_entry_decision` is set unless a gate blocked, because `T-0059`/`B217` made it the
    field `LIVE_NOT_REACHED` is keyed on — `blocked_by` covered three of seven block sources,
    so a loop-blocked bar used to read as *"the live heuristic DECLINED"* for a bar it never
    evaluated. **A hand-built trace is a trace PRODUCER**, and the flag is now the producer's
    obligation: without it every fixture here is NOT_COMPARABLE and both arms below pass
    vacuously, which is how this change announced itself.
    """
    t = DecisionTrace(symbol="BTC/USD", timeframe="5m")
    if blocked is not None:
        t.gate(blocked, False, "forced for the test")
    else:
        t.reached_entry_decision = True
    t.took_trade = took
    return t


# ---------------------------------------------------------------------------
# THE TWO ARMS
# ---------------------------------------------------------------------------


def test_arm_2_the_denominator_is_observed_non_zero_from_real_bars(frame):
    """THE ARM THAT THE MUST-FIRE ARM CANNOT SUBSTITUTE FOR.

    Nothing injected, nothing forced — real bars from the pinned corpus, and the comparable
    count must be non-zero. **Without this, `0 comparable` and `many comparable` both give a
    green must-fire arm and an `undefined` rate, and the harness would look correct over a
    population that does not exist.**
    """
    comparable = 0
    windows = 0
    for end in range(400, 1501, 110):
        c = compare_entry(_trace(), _bars(frame, end), tf="5m")
        comparable += c.agree + c.disagree
        windows += 1

    assert windows >= 10, "too few windows for this arm to mean anything"
    assert comparable > 0, (
        f"{windows} windows of real bars produced ZERO comparable decisions. The rate would be "
        f"'undefined' everywhere and the must-fire arm would still pass."
    )


def test_arm_1_an_injected_disagreement_moves_the_numerator(frame):
    """MUST-FIRE. The comparison must be able to register a difference at all."""
    bars = _bars(frame, 1500)

    # Same bars, two live verdicts. Exactly one of them must disagree with the rule, because
    # the rule's verdict does not depend on the live one.
    took = compare_entry(_trace(took=True), bars, tf="5m")
    declined = compare_entry(_trace(took=False), bars, tf="5m")

    assert took.disagree + declined.disagree == 1, (
        "flipping the live verdict against a fixed rule verdict must move the numerator by "
        f"exactly one, got took={took.disagree} declined={declined.disagree}"
    )
    assert took.agree + declined.agree == 1


# ---------------------------------------------------------------------------
# THE TRIPLE — a scalar cannot carry three outcomes
# ---------------------------------------------------------------------------


def test_a_bar_the_live_path_never_reached_is_NOT_agreement(frame):
    """`LIVE_NOT_REACHED`. Counting it as agreement is the failure the triple exists to stop."""
    c = compare_entry(_trace(blocked="daily_bias"), _bars(frame, 1500), tf="5m")

    assert c.comparisons[0].outcome == "NOT_COMPARABLE"
    assert c.comparisons[0].reason == "LIVE_NOT_REACHED"
    assert c.agree == 0 and c.disagree == 0
    assert c.not_comparable == 1


def test_an_empty_comparable_set_renders_UNDEFINED_and_never_zero_percent(frame):
    """`0%` over an empty denominator is maximally reassuring and completely empty — B157's
    rule at the aggregate layer: a format that enumerates its inputs must refuse to render
    when it had none."""
    c = compare_entry(_trace(blocked="history"), _bars(frame, 1500), tf="5m")

    assert "undefined (0 comparable)" in c.detail
    assert "0.000" not in c.detail
    assert c.values()["disagreement_rate"] is None
    assert c.values()["comparable"] == 0, "the denominator must be published even when zero"


def test_the_published_values_always_carry_all_three_terms_and_the_denominator(frame):
    c = compare_entry(_trace(took=True), _bars(frame, 1500), tf="5m")
    values = c.values()
    for key in ("agree", "disagree", "not_comparable", "comparable", "disagreement_rate"):
        assert key in values, f"{key} missing — a ratio hides exactly one number"
    assert values["comparable"] == values["agree"] + values["disagree"]


def test_every_figure_states_that_one_rule_of_six_is_comparable(frame):
    """Scope beside the figure, not near it. Anyone reading "the entry seam" as covering all
    six is reading a claim the record must not make."""
    c = compare_entry(_trace(took=True), _bars(frame, 1500), tf="5m")
    assert f"{len(COMPARABLE_RULE_IDS)} of 6 rules comparable" in c.detail
    assert c.values()["rules_named_by_the_task"] == 6
    assert c.values()["comparable_rule_ids"] == ["ENTRY-001"]


# ---------------------------------------------------------------------------
# INPUT_ABSENT, DERIVED — the harness's general defence, not a call-site check
# ---------------------------------------------------------------------------


def test_a_rule_that_examined_nothing_is_NOT_COMPARABLE_not_agreement(frame):
    """THE MIRROR OF THE `at_price` ARTEFACT, AND IT FAILS THE OTHER WAY.

    `ENTRY-001` on an empty inventory returns `FAIL` with `candidates_considered: 0` — and
    `FAIL` AGREES with a live path that declined. **So the naive harness records a SPURIOUS
    AGREEMENT and the rate falls**, where a dropped `at_price` produces spurious disagreement
    and the rate rises. Same convention, opposite directions, neither detectable from the
    verdict alone.
    """
    # FLAT bars, deliberately: a gap cannot form between identical candles, so the inventory
    # is EMPTY BY CONSTRUCTION. A small slice of real bars does NOT produce this -- `tail(3)`
    # of the corpus already yields 2 imbalances -- and a fixture that only happened to be
    # empty would stop testing this the day the corpus changed.
    c = compare_entry(_trace(took=False), _flat_bars(), tf="5m")

    assert c.comparisons[0].outcome == "NOT_COMPARABLE"
    assert c.comparisons[0].reason == "INPUT_ABSENT"
    assert c.agree == 0, "an empty inventory must not be recorded as agreement"

    # AND THE SPURIOUS AGREEMENT IS REAL, not hypothetical: the rule's own verdict on this
    # input is FAIL, which is what a declining live path would have agreed with.
    assert c.comparisons[0].rule_verdict == "FAIL"


def test_examined_nothing_requires_a_count_key_and_does_not_infer_from_silence():
    """CONTROL PAIR on the discriminator itself. A rule that publishes no input count has not
    said it examined nothing, and treating silence as emptiness is the collapse this harness
    exists to avoid."""
    assert examined_nothing({"candidates_considered": 0}) is True
    assert examined_nothing({"candidates_considered": 5}) is False
    assert examined_nothing({}) is False, "silence is not emptiness"
    assert examined_nothing({"verdict_only": "PASS"}) is False


def test_the_input_count_suffixes_match_what_the_rules_actually_publish():
    """DERIVED, not enumerated per rule — so a rule nobody has wired yet is covered.

    Measured across the registry: every parameter of every bar-shaped `evaluate` is defaulted,
    so `evaluate()` with no arguments compiles and returns a verdict. These three publish their
    own emptiness and are what the suffixes key on.
    """
    impl = implementations()
    published = {}
    for rid in ("ENTRY-001", "GATE-037", "GATE-038"):
        values = impl[rid].evaluate().values
        published[rid] = sorted(
            k for k in values if any(k.endswith(s) for s in INPUT_COUNT_SUFFIXES)
        )
        assert published[rid], (
            f"{rid} publishes no input count matching {INPUT_COUNT_SUFFIXES} — the harness's "
            f"emptiness discriminator does not reach it"
        )
        assert examined_nothing(dict(values)), f"{rid} on no input must read as examined-nothing"

    # `_count` is deliberately excluded: an OUTPUT count of zero means the rule found nothing,
    # which is a verdict, not an absence.
    assert "amplifier_count" not in published["GATE-038"]


# ---------------------------------------------------------------------------
# ROWS KEY ON THE REGISTERED ID
# ---------------------------------------------------------------------------


def test_the_row_is_keyed_by_the_registered_id(frame):
    c = compare_entry(_trace(took=True), _bars(frame, 1500), tf="5m")
    assert c.comparisons[0].rule_id == "ENTRY-001"
    assert c.comparisons[0].alias_of is None
    assert "returned_rule_id" not in c.comparisons[0].as_dict()


def test_the_alias_mismatch_this_guards_against_is_REAL_and_measured():
    """MUST-HIT for the guard above. It cannot bite at a denominator of one — it bites the
    instant the comparable set widens, which is what this harness exists to build for, so the
    arm is here rather than in a later debugging session."""
    impl = implementations()
    mismatched = {
        rid: impl[rid].evaluate().rule_id
        for rid in ("GRADE-029", "GRADE-035")
        if rid in impl and impl[rid].evaluate().rule_id != rid
    }
    assert mismatched == {"GRADE-029": "GATE-041", "GRADE-035": "GATE-040"}, (
        "the alias mechanism changed; a harness keying rows by the RETURNED id would merge "
        f"two rules into one row. Measured: {mismatched}"
    )


def test_an_alias_is_recorded_rather_than_silently_re_keyed():
    c = RuleComparison("GRADE-029", "AGREE", True, "PASS", alias_of="GATE-041")
    assert c.as_dict()["rule_id"] == "GRADE-029"
    assert c.as_dict()["returned_rule_id"] == "GATE-041"


# ---------------------------------------------------------------------------
# FAILURE ISOLATION — a parallel observer that can crash the loop is worse than none
# ---------------------------------------------------------------------------


def test_a_raising_rule_becomes_NOT_COMPARABLE_and_does_not_propagate():
    c = compare_entry(_trace(took=True), [object()], tf="5m")  # type: ignore[list-item]

    assert c.comparisons[0].outcome == "NOT_COMPARABLE"
    assert c.comparisons[0].reason == "RULE_RAISED"
    assert "AttributeError" in c.comparisons[0].detail, "the exception must be recorded, not swallowed"


def test_no_bars_is_INPUT_ABSENT_rather_than_a_crash():
    c = compare_entry(_trace(), [], tf="5m")
    assert c.comparisons[0].reason == "INPUT_ABSENT"


# ---------------------------------------------------------------------------
# RECORDED, NOT ENFORCED
# ---------------------------------------------------------------------------


def test_the_comparison_is_recorded_unenforced_and_is_not_a_would_block(frame):
    """It observes; it does not gate. And it must NOT land in `would_block_by`, which is a
    different rule's numerator."""
    trace = _trace(took=True)
    compare_entry(trace, _bars(frame, 1500), tf="5m").record_on(trace)

    assert trace.blocked_by is None
    assert GATE_NAME not in trace.would_block_by
    gate = next(g for g in trace.gates if g.name == GATE_NAME)
    assert gate.enforced is False


def test_the_seam_runs_after_the_decision_and_touches_no_line_inside_it():
    """"Change no decision" is STRUCTURAL here rather than tested-into-place.

    `compare_entry` is called by `crypto_loop` on the trace `evaluate_latest_bar_traced` has
    already returned, so it cannot influence a decision that has been made. This asserts the
    property that makes that true: the decision function does not import the comparison.
    """
    step = (BACKEND / "app/services/live/strategy_step.py").read_text(encoding="utf-8")
    assert "entry_comparison" not in step, (
        "the entry comparison must not be reachable from inside the decision function"
    )

    loop = (BACKEND / "app/services/live/crypto_loop.py").read_text(encoding="utf-8")
    assert "compare_entry(" in loop, "must-hit: the seam is wired somewhere"
    assert loop.index("evaluate_latest_bar_traced(") < loop.index("compare_entry("), (
        "the comparison must run AFTER the decision"
    )


def test_the_empty_comparison_publishes_zeros_without_a_rate():
    """The default `EntryComparison` is the no-rules-ran case and must not print `0%`."""
    c = EntryComparison()
    assert c.values()["comparable"] == 0
    assert c.values()["disagreement_rate"] is None
    assert "undefined (0 comparable)" in c.detail


# ---------------------------------------------------------------------------
# THE CONFORMANCE COLUMN — asserted ONCE PER RUN, never sampled per bar
# ---------------------------------------------------------------------------
#
# GATE-037 and GATE-038 are properties of the CODE, not of the bar. Sampling either per bar
# contributes a constant term to a disagreement rate, which is the defect this task's criterion
# exists to prevent, and GATE-038 is worse than a constant: its verdict is
# `"PASS" if setup_valid else "FAIL"` -- an IDENTITY on its own argument -- so in a denominator
# it can only ever AGREE, inflating the denominator and moving the published rate in the
# REASSURING direction. T-0028 established the once-per-run shape for TARGET-005/006.


def _entry_decision_source() -> str:
    return (BACKEND / "app/services/live/strategy_step.py").read_text(encoding="utf-8")


def _code_lines(source: str) -> list[str]:
    """Code only. The docstrings in this file DISCUSS the banned vocabulary in order to forbid
    it -- GATE-037's own instrument had to make this distinction and so does this one."""
    out, in_doc = [], False
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.count('"""') == 1:
            in_doc = not in_doc
            continue
        if in_doc or stripped.startswith("#") or stripped.startswith('"""'):
            continue
        out.append(line)
    return out


@pytest.mark.parametrize("token", ["premium", "discount", "equilibrium", "ote", "eq_level"])
def test_gate_037_the_live_entry_path_consults_no_premium_discount_vocabulary(token):
    """GATE-037, once per run. 'It should not influence whether a trade is taken or rejected.'"""
    from app.services.rules.gate_037_no_premium_discount import BANNED_TOKENS

    assert token in BANNED_TOKENS, "the vocabulary moved; this arm is asserting a stale token"
    offenders = [l.strip() for l in _code_lines(_entry_decision_source()) if token in l.lower()]
    assert not offenders, f"GATE-037: {token!r} appears on the live entry path: {offenders}"


def test_gate_037_the_instrument_can_see_a_token_when_one_is_there():
    """CONTROL. An all-clean sweep proves nothing unless the sweep can find something."""
    planted = 'if price > equilibrium:  # planted\n'
    assert [l for l in _code_lines(planted) if "equilibrium" in l.lower()]
    # MUST-MISS: the same token inside a docstring is prose, not a decision path.
    doc = '"""\nthis mentions equilibrium to forbid it\n"""\n'
    assert not [l for l in _code_lines(doc) if "equilibrium" in l.lower()]


def test_gate_038_amplifiers_do_not_reach_the_live_entry_decision():
    """GATE-038's doctrinal content, as a conformance assertion rather than a per-bar verdict.

    Its own values already carry `"decides_entry": False`, emitted "so a conformance test can
    read it rather than infer it from the absence of an effect" — this is that test.
    """
    from app.services.rules.gate_038_amplifiers import AMPLIFIER_KINDS

    source = "\n".join(_code_lines(_entry_decision_source())).lower()
    for kind in AMPLIFIER_KINDS:
        needle = kind.lower().replace("_", "")
        assert needle not in source.replace("_", ""), (
            f"GATE-038: {kind} appears on the live entry path — amplifiers may never create a trade"
        )

    assert implementations()["GATE-038"].evaluate().values["decides_entry"] is False
