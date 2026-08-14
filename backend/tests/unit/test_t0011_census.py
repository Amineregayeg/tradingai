"""T-0011 — the census must be MEASURED every scan, not asserted once (B41).

WHAT THE EXISTING TEST COULD NOT DO, AND WHY IT WAS NOT A CARELESS TEST

`test_telemetry_contract.py` builds a census with `bars_observed=19,
evaluations_emitted=19` — equal, by hand — and asserts `unemitted_bars == []`. That is a
faithful description of the schema's own portrait of an honest engine, and it is correct.
It is also incapable of going red for the defect the census exists to detect, because it
constructs the honest case in order to check it:

    A test that can only construct honesty cannot detect its absence.

So every test here builds the DISHONEST case first and asserts the census reports it.

THE FOUR WAYS THIS TASK COULD HAVE PRODUCED A GREEN RESULT AND NO INFORMATION, each of
which has a test below that fails on it specifically:

  1. counts taken from a loop counter        -> `test_the_counts_survive_a_restart`
  2. the window filtered on WRITE time       -> `test_the_filter_is_on_bar_time_not_write_time`
  3. the window filtered on a NY-local STRING -> `test_the_dst_fall_back_inverts_a_string_sort`
  4. an empty array hiding missing bars      -> `test_a_silently_dropped_bar_is_reported`

Mutations 1 and 2 are each necessary and neither is sufficient: an implementation
filtering on `created_at` is externally derived and passes 1, and a string comparison
passes both 1 and 2 and fails only on 3.

AND A FIFTH, ADDED BY RULING ON 2026-08-15. `unemitted_bars.items` REQUIRES a `rule_id`
matching the registry's pattern, so an omission caused by a FAILURE — a dead database, a
thin layout — cannot be represented in that array at all without inventing a rule. It
therefore stays empty, and `bars_observed` legitimately exceeds `evaluations_emitted`.

    An empty array with a SILENT mismatch is exactly the honest-looking census this
    task exists to prevent.

So the tests below draw the line not at "does the array have entries" but at "is the
shortfall accounted for to the bar" — `test_a_silently_dropped_bar_is_reported` and
`test_a_silent_shortfall_is_the_worst_case` are the pair that separates them, and
`test_a_policy_authorised_skip_is_not_reported_as_a_gap` is the third case: a skip the
declared emission policy DOES authorise, which must not be reported at all.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from app.models.telemetry_record import TelemetryRecord
from app.services.live import shadow
from app.services.telemetry import census
from app.services.telemetry import contract_loader as contract
from app.services.telemetry import records as rec
from app.services.telemetry import validate as val
from app.services.telemetry.ny_time import iso_ny

SYMBOL = "BTC/USD"
TF = "5M"
PERIOD = timedelta(minutes=5)
INSTRUMENT = {"symbol": SYMBOL, "instrument_class": "ALIGNED_MAJOR", "venue": "BINANCE_SPOT"}


@pytest.fixture
def declared():
    return shadow.declared_parameters()


def _bar_opens(first_open: datetime, n: int) -> list[datetime]:
    return [first_open + i * PERIOD for i in range(n)]


async def _store_evaluation(db, *, bar_open: datetime, symbol: str = SYMBOL, tf: str = TF) -> None:
    """A minimal stored `setup_evaluation` row, carrying its bar OPEN time as the engine does.

    Written through the model rather than through `records.setup_evaluation` on purpose:
    what the census reads is the indexed `timestamp_ny` column, and building the row
    directly is the only way to control that value independently of `created_at` — which
    is exactly the pair mutation 2 has to separate.
    """
    db.add(TelemetryRecord(
        record_type="setup_evaluation",
        record_id=f"eval-{symbol}-{tf}-{bar_open.isoformat()}",
        instrument=symbol,
        signal_tf=tf,
        timestamp_ny=iso_ny(bar_open),
        payload={"record_type": "setup_evaluation"},
    ))
    await db.flush()


# ---------------------------------------------------------------------------
# Criterion 2 — both counts derived from outside the emitting loop
# ---------------------------------------------------------------------------
async def test_the_counts_survive_a_restart(db_session, declared):
    """MUTATION 1. Nothing in the derivation may be a number the loop was holding.

    The failure this catches is not the lost count — it is that the RECONCILIATION STILL
    HOLDS when it is lost. A counter-based census undercounts `bars_observed`,
    `evaluations_emitted` and `unemitted_bars` together, so half a day counted honestly
    satisfies criterion 6 exactly as well as a full one: internally consistent,
    externally false, and indistinguishable from correct.

    The restart is simulated the only way that matters here — by keeping the database and
    the bar series and destroying every scrap of in-process state.
    """
    day = "2026-08-14"
    frm, _to = census.session_window(day)
    opens = _bar_opens(frm, 12)
    for o in opens[:8]:
        await _store_evaluation(db_session, bar_open=o)

    before = await census.build_scan_census(
        db_session, declared=declared, instrument=INSTRUMENT, signal_tf=TF,
        session_date=day, bar_opens=opens,
        attributions={census.bar_close(o, PERIOD): (census.OMISSION_FAILURE, "thin frame")
                      for o in opens[8:]},
    )
    # THE RESTART: no attributions at all, which is what a fresh process has.
    after = await census.build_scan_census(
        db_session, declared=declared, instrument=INSTRUMENT, signal_tf=TF,
        session_date=day, bar_opens=opens, attributions={},
    )

    assert before["bars_observed"] == after["bars_observed"] == 12
    assert before["evaluations_emitted"] == after["evaluations_emitted"] == 8

    acc_before = census.parse_accounting(before["notes"])
    acc_after = census.parse_accounting(after["notes"])
    assert acc_before.total == acc_after.total == 4, (
        "a restart changed how many bars the census says went missing — the counts are "
        "being carried in the process, not derived"
    )
    # What a restart DOES cost is the reason, and the census says which four are which
    # rather than silently reporting four fewer missing bars.
    assert (acc_before.failures, acc_before.unattributed) == (4, 0)
    assert (acc_after.failures, acc_after.unattributed) == (0, 4)


async def test_the_filter_is_on_bar_time_not_write_time(db_session, declared):
    """MUTATION 2. The only thing that separates the two time columns.

    `created_at` is not merely a noisier bar time. Measured on production rows, a 5m bar
    stamped 20:35:00-04:00 is WRITTEN at 00:40:18Z — the bar opens at 00:35Z and closes
    at 00:40Z, so at 5m the write time lands a full bar period after the stamp. A
    `created_at` window filter is therefore a deterministic off-by-one at every boundary,
    and it would report a MAJOR at every single one, caused entirely by its own filter.

    Here the write times are moved a full day across the window boundary while the bar
    times stay put. If the count moves, the filter is on the wrong column.
    """
    day = "2026-08-14"
    frm, to = census.session_window(day)
    opens = _bar_opens(frm, 6)
    for o in opens:
        await _store_evaluation(db_session, bar_open=o)

    baseline = await census.emitted_closes(
        db_session, instrument=SYMBOL, signal_tf=TF, period=PERIOD,
        window_from=frm, window_to=to,
    )
    assert len(baseline) == 6

    await db_session.execute(
        update(TelemetryRecord).values(created_at=to + timedelta(days=1))
    )
    await db_session.flush()

    moved = await census.emitted_closes(
        db_session, instrument=SYMBOL, signal_tf=TF, period=PERIOD,
        window_from=frm, window_to=to,
    )
    assert moved == baseline, (
        "moving every row's WRITE time a day outside the window changed the count, so "
        "the window is being applied to created_at and the census counts by when rows "
        "were saved rather than by which bars they describe"
    )


async def test_the_dst_fall_back_inverts_a_string_sort(db_session, declared):
    """MUTATION 3. A string comparison passes mutations 1 and 2 and fails only this.

    On the autumn fall-back, NY local time repeats and its ISO strings stop ordering with
    the instants they name:

        01:59:00-04:00  is  05:59Z   but sorts AFTER
        01:00:00-05:00  is  06:00Z   which is one minute LATER

    One night a year, on a 24/7 market, and no comparison raises. The offsets are in the
    strings precisely so a parser can tell them apart, which is why the census parses.
    """
    # 2026-11-01 is the US fall-back. The window is 25 hours long.
    day = "2026-11-01"
    frm, to = census.session_window(day)
    assert to - frm == timedelta(hours=25), "the fall-back day must be 25 hours"

    # The fall-back is at 06:00Z: 01:59:59-04:00 is followed by 01:00:00-05:00.
    earlier = datetime(2026, 11, 1, 5, 55, tzinfo=timezone.utc)   # 01:55 -04:00
    later = datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc)      # 01:00 -05:00
    assert earlier < later
    assert iso_ny(earlier) > iso_ny(later), (
        "this fixture is only meaningful if the strings sort the wrong way round; "
        f"got {iso_ny(earlier)!r} vs {iso_ny(later)!r}"
    )
    for o in (earlier, later):
        await _store_evaluation(db_session, bar_open=o)

    # A window ending BETWEEN the two bar closes (06:00Z and 06:05Z). Parsed, it admits
    # the earlier bar and excludes the later. Compared as NY-local text against
    # `iso_ny(cut)` = 01:03:00-05:00, it does exactly the opposite on both: "01:55:00
    # -04:00" sorts after the cut and "01:00:00-05:00" sorts before it.
    cut = datetime(2026, 11, 1, 6, 3, tzinfo=timezone.utc)
    got = await census.emitted_closes(
        db_session, instrument=SYMBOL, signal_tf=TF, period=PERIOD,
        window_from=frm, window_to=cut,
    )
    assert got == [census.bar_close(earlier, PERIOD)], (
        "the fall-back window admitted the wrong bar — the comparison is lexicographic "
        f"on NY-local text rather than on parsed instants; got {got}"
    )


# ---------------------------------------------------------------------------
# Criterion 3 — the test must construct the DISHONEST case
# ---------------------------------------------------------------------------
async def test_a_silently_dropped_bar_is_reported(db_session, declared):
    """THE CRITERION. Bars observed and not emitted, and the census must say so.

    If no test in the suite fails when a bar is silently dropped, this task moved the
    defect one layer up rather than fixing it.

    Note what is asserted and what is not. `unemitted_bars` is EMPTY here and that is
    correct: the array requires a registry `rule_id`, and neither "the database was
    unreachable" nor "the frame was too thin" is a rule. What must not be empty is the
    ACCOUNTING — the census has to state the shortfall to the bar, and C-13 has to
    report it.
    """
    day = "2026-08-14"
    frm, _to = census.session_window(day)
    opens = _bar_opens(frm, 10)
    for o in opens[:7]:
        await _store_evaluation(db_session, bar_open=o)

    dropped = opens[7:]
    attributions = {
        census.bar_close(dropped[0], PERIOD): (census.OMISSION_POLICY, "fewer than 10 bars in the frame (n=4)"),
        census.bar_close(dropped[1], PERIOD): (census.OMISSION_FAILURE, "OperationalError: database is locked"),
        census.bar_close(dropped[2], PERIOD): (census.OMISSION_FAILURE, "ValueError: body-less bar"),
    }
    record = await census.build_scan_census(
        db_session, declared=declared, instrument=INSTRUMENT, signal_tf=TF,
        session_date=day, bar_opens=opens, attributions=attributions,
    )

    assert val.errors(record) == [], "the dishonest census must still satisfy the contract"
    assert record["bars_observed"] == 10
    assert record["evaluations_emitted"] == 7
    assert record["unemitted_bars"] == [], (
        "an omission caused by a failure cannot be put in this array without inventing a "
        "rule id, so the array stays empty and the shortfall is declared in notes"
    )

    acc = census.parse_accounting(record["notes"])
    assert (acc.policy_excluded, acc.failures, acc.unattributed) == (1, 2, 0)
    assert "OperationalError: database is locked" in record["notes"]

    # C-13 reports the failures. The policy-excluded bar is NOT reported: it is
    # authorised by the declared emission policy, and reporting it would make the alarm
    # fire on the mechanism working.
    report = census.reconcile([record])
    assert report.examined == 1
    assert {f.check for f in report.findings} == {"unrepresentable-omission"}
    assert "2 bar(s)" in report.findings[0].message


async def test_a_silent_shortfall_is_the_worst_case(db_session, declared):
    """THE MUTATION FOR CRITERION 3 — remove the ACCOUNTING and it must go red.

    Deliberately NOT "remove the rule id", and no longer "remove the omission_class":
    the ruling of 2026-08-15 established that none of the real omission population can
    carry either. What is removed is the only thing the contract lets us record — the
    declared shortfall — and the resulting record is byte-plausible: valid, empty array,
    three bars gone.
    """
    day = "2026-08-14"
    frm, _to = census.session_window(day)
    opens = _bar_opens(frm, 4)
    await _store_evaluation(db_session, bar_open=opens[0])

    declared_record = await census.build_scan_census(
        db_session, declared=declared, instrument=INSTRUMENT, signal_tf=TF,
        session_date=day, bar_opens=opens,
        attributions={census.bar_close(o, PERIOD): (census.OMISSION_FAILURE, "RuntimeError: x")
                      for o in opens[1:]},
    )
    assert [f.check for f in census.reconcile([declared_record]).findings] == [
        "unrepresentable-omission"
    ]

    # THE MUTATION: identical counts, identical empty array, accounting stripped out.
    silent = dict(declared_record)
    silent.pop("notes")
    assert silent["bars_observed"] == declared_record["bars_observed"]
    assert silent["evaluations_emitted"] == declared_record["evaluations_emitted"]
    assert silent["unemitted_bars"] == declared_record["unemitted_bars"] == []
    assert val.errors(silent) == [], "the silent census is a perfectly valid record"

    findings = [f for f in census.reconcile([silent]).findings if f.check == "reconciliation"]
    assert len(findings) == 1, (
        "three bars were observed, never evaluated, and nothing accounted for them, and "
        "C-13 said nothing — an empty array with a silent mismatch is exactly the "
        "honest-looking census this task exists to prevent"
    )


async def test_a_policy_authorised_skip_is_not_reported_as_a_gap(db_session, declared):
    """A bar skipped under the DECLARED emission policy is the mechanism working.

    `every-closed-bar-with-sufficient-history-v2` names insufficient history, so those
    bars are authorised once, centrally, and expect no per-bar record. Reporting them
    would make C-13 fire on every short frame — and an alarm that fires on correct
    behaviour is the muted alarm this task started from.
    """
    day = "2026-08-14"
    frm, _to = census.session_window(day)
    opens = _bar_opens(frm, 5)
    for o in opens[:3]:
        await _store_evaluation(db_session, bar_open=o)

    record = await census.build_scan_census(
        db_session, declared=declared, instrument=INSTRUMENT, signal_tf=TF,
        session_date=day, bar_opens=opens,
        attributions={census.bar_close(o, PERIOD): (census.OMISSION_POLICY, "n=4")
                      for o in opens[3:]},
    )
    assert census.reconcile([record]).findings == []
    assert census.reconcile([record]).outcome == "PASS"


# ---------------------------------------------------------------------------
# Criterion 4 / 4c — no fabricated authority
# ---------------------------------------------------------------------------
def test_no_rule_id_is_ever_fabricated(db_session):
    """The ruling's rule 4, asserted on the source rather than trusted.

    Fabricating a pattern-valid id — `GATE-000` is the obvious one, since every registry
    prefix numbers from 001 — would make `unemitted_bars` usable for failures and make
    the arithmetic reconcile. It would also state that a rule authorised something no
    rule has ever mentioned, and C-3 rejects the id downstream.
    """
    import re
    from pathlib import Path

    for path in (Path("app/services/telemetry/census.py"),
                 Path("app/services/live/crypto_loop.py")):
        src = path.read_text(encoding="utf-8")
        # Rule-shaped literals in a string context. The registry's own ids appear in
        # comments and docstrings all over the codebase, so this looks only for
        # ASSIGNMENT of one into a rule_id field.
        assert not re.search(r'["\']rule_id["\']\s*:\s*["\'](?:GATE|GRADE|TARGET|ENTRY|EXIT|SIZE|PRIM)-\d{3}', src), (
            f"{path} writes a literal rule id into a rule_id field"
        )


def test_the_omission_classes_are_internal_only(declared):
    """The two labels must never reach a stored record's `rule_id`.

    They are classification, used to count and to explain in `notes`. The schema pins
    `rule_id` to the registry pattern, so a record carrying one of these would raise at
    `store.py` before it was written — this asserts the validator would in fact reject
    it, rather than assuming so.
    """
    assert census.OMISSION_CLASSES == {"POLICY", "FAILURE"}
    for label in sorted(census.OMISSION_CLASSES):
        bad = {
            "record_type": "scan_census", "scan_id": "s",
            "engine": rec.engine_identity(), "declared_parameters": declared.as_dict(),
            "instrument": INSTRUMENT, "signal_tf": TF, "session_date": "2026-08-14",
            "window_from_ny": "2026-08-14T00:00:00-04:00",
            "window_to_ny": "2026-08-15T00:00:00-04:00",
            "bars_observed": 1, "evaluations_emitted": 0,
            "unemitted_bars": [{
                "bar_close_time_ny": "2026-08-14T10:05:00-04:00",
                "rule_id": label, "reason": "r",
            }],
        }
        assert val.errors(bad), f"{label} was accepted as a rule_id — the pattern is not holding"


def test_a_plausible_looking_rule_id_is_caught():
    """4c. A rule id absent from the registry is undocumented logic.

    The obvious way this record becomes decorative is an id that LOOKS right. `GATE-044`
    is a real registry id and passes; `GATE-471` is not and must not.
    """
    def _with(rule_id: str) -> dict:
        return {
            "record_type": "scan_census", "scan_id": "s",
            "bars_observed": 1, "evaluations_emitted": 0,
            "unemitted_bars": [{
                "bar_close_time_ny": "2026-08-14T10:05:00-04:00",
                "rule_id": rule_id, "reason": "r",
            }],
        }

    real = sorted(contract.known_rule_ids())[0]
    assert not [f for f in census.reconcile([_with(real)]).findings
                if f.check == "undocumented-logic"]
    assert [f for f in census.reconcile([_with("GATE-471")]).findings
            if f.check == "undocumented-logic"]


# ---------------------------------------------------------------------------
# Criterion 6 — reconciliation is arithmetic, and it is allowed to FAIL
# ---------------------------------------------------------------------------
def test_a_census_that_does_not_add_up_is_a_finding():
    short = {
        "record_type": "scan_census", "scan_id": "s",
        "bars_observed": 288, "evaluations_emitted": 200, "unemitted_bars": [],
    }
    findings = [f for f in census.reconcile([short]).findings if f.check == "reconciliation"]
    assert len(findings) == 1
    assert "288" in findings[0].message and "200" in findings[0].message


async def test_evaluations_without_bars_are_not_balanced_away(db_session, declared):
    """A stored evaluation whose bar the series does not contain must NOT be hidden.

    Forcing the arithmetic to balance would fabricate the denominator this record exists
    to make honest, so the census reports both numbers as measured, says so in `notes`,
    and lets C-13 report the imbalance.
    """
    day = "2026-08-14"
    frm, _to = census.session_window(day)
    opens = _bar_opens(frm, 3)
    for o in opens:
        await _store_evaluation(db_session, bar_open=o)
    await _store_evaluation(db_session, bar_open=frm + timedelta(minutes=137))  # off-grid

    record = await census.build_scan_census(
        db_session, declared=declared, instrument=INSTRUMENT, signal_tf=TF,
        session_date=day, bar_opens=opens, attributions={},
    )
    assert record["bars_observed"] == 3
    assert record["evaluations_emitted"] == 4
    assert record["unemitted_bars"] == []
    assert "no matching bar in the series" in record["notes"]
    # The declared accounting is zero and the arithmetic leaves -1, so the record
    # disagrees with its own explanation and C-13 says which way it went.
    assert census.parse_accounting(record["notes"]).total == 0
    assert [f.check for f in census.reconcile([record]).findings] == ["reconciliation"]


# ---------------------------------------------------------------------------
# Criterion 5 / 5-i — the check reports its own denominator
# ---------------------------------------------------------------------------
def test_examining_zero_censuses_is_not_a_pass():
    """5-i. This lands on DAY ONE: 156 telemetry records in production, zero censuses.

    A check reporting only pass/fail would have gone green from an empty set and stayed
    green until the first census existed — which is exactly the window in which someone
    reads the green and concludes the mechanism works.
    """
    empty = census.reconcile([])
    assert empty.examined == 0
    assert empty.outcome == "NOT_EXERCISED"
    assert empty.outcome != "PASS"
    # `ok` alone is True on an empty corpus, which is why no caller may use it as the
    # outcome. This asserts the trap is still there rather than pretending it is not.
    assert empty.ok is True


def test_non_census_records_are_ignored_and_not_counted():
    """The denominator is censuses, not records. Counting a setup_evaluation as examined
    would inflate the one number this check exists to state honestly."""
    report = census.reconcile([
        {"record_type": "setup_evaluation", "evaluation_id": "e"},
        {"record_type": "trade_execution", "trade_id": "t"},
    ])
    assert report.examined == 0
    assert report.outcome == "NOT_EXERCISED"


# ---------------------------------------------------------------------------
# The record the census counts — criterion 4a
# ---------------------------------------------------------------------------
def test_both_facts_are_recorded_on_every_evaluation(declared):
    """4a. `engine_policy` and `rule_verdict`, never one-of-two.

    "The rules were not consulted" and "the rules were consulted and permitted" are
    different facts. Post-T-0010 the first is empty — which is exactly when it is
    cheapest to record and easiest to omit. A one-of-two record changes meaning silently
    the day someone reorders those two calls back; a two-field record does not.
    """
    import pandas as pd

    idx = pd.date_range("2026-08-14 10:00", periods=40, freq="5min", tz="UTC")
    df = pd.DataFrame({
        "open": [100.0 + i * 0.1 for i in range(40)],
        "high": [100.5 + i * 0.1 for i in range(40)],
        "low": [99.5 + i * 0.1 for i in range(40)],
        "close": [100.2 + i * 0.1 for i in range(40)],
    }, index=idx)

    for policy in ("already in a position", None):
        record, decline = shadow.evaluate_detailed(
            SYMBOL, df, signal_tf="5m", declared=declared,
            sequence_no=1, scan_id="scan-x", engine_policy=policy,
        )
        assert record is not None, f"the fixture must grade; declined with {decline!r}"
        ctx = record["scan_context"]
        assert "engine_policy" in ctx and "rule_verdict" in ctx, (
            "both fields must be present on every record, including when one is null"
        )
        assert ctx["engine_policy"] == policy
        assert ctx["rule_verdict"] == record["decision"]
        assert val.errors(record) == []


def test_the_grader_returns_its_own_reason_when_it_declines(declared):
    """The census cannot attribute an omission the grader will not explain."""
    import pandas as pd

    idx = pd.date_range("2026-08-14 10:00", periods=4, freq="5min", tz="UTC")
    df = pd.DataFrame(
        {"open": [1.0] * 4, "high": [2.0] * 4, "low": [0.5] * 4, "close": [1.5] * 4},
        index=idx,
    )
    record, decline = shadow.evaluate_detailed(
        SYMBOL, df, signal_tf="5m", declared=declared, sequence_no=1, scan_id="s",
    )
    assert record is None
    cls, reason = decline
    # POLICY, not FAILURE: the declared emission policy is literally named for this
    # condition, so it is authorised and C-13 must not report it as a gap.
    assert cls == census.OMISSION_POLICY
    assert "fewer than 10 bars" in reason
    # And the legacy entry point is unchanged for the trading path, which must not care.
    assert shadow.evaluate(
        SYMBOL, df, signal_tf="5m", declared=declared, sequence_no=1, scan_id="s",
    ) is None


# ---------------------------------------------------------------------------
# Criterion 4b-i / 4b-ii — the reordering, and the two tests that can see it
# ---------------------------------------------------------------------------
def _frame(periods: int = 80, start: str = "2026-08-14 10:00"):
    import pandas as pd

    idx = pd.date_range(start, periods=periods, freq="5min", tz="UTC")
    return pd.DataFrame({
        "open": [100.0 + i * 0.1 for i in range(periods)],
        "high": [100.5 + i * 0.1 for i in range(periods)],
        "low": [99.5 + i * 0.1 for i in range(periods)],
        "close": [100.2 + i * 0.1 for i in range(periods)],
    }, index=idx)


async def test_the_gate_re_evaluates_rather_than_reusing_the_early_read(monkeypatch):
    """4b-ii. WHEN something happened, not WHAT it produced — so observe the CALL.

    WHAT THIS ASSERTION PROTECTS, because an ordering assertion pins the implementation
    rather than the property and will otherwise read as noise to whoever next restructures
    this loop:

        `_entry_block_reason` is called TWICE per bar on purpose. The first call is for
        the RECORD — it is what the shadow's `setup_evaluation` carries as
        `engine_policy`. The second is the GATE, and it must read the world again,
        because the shadow's `await` yields and the state it reads is mutable from
        outside the loop (a position can close, the kill switch can be armed).

        Reuse produces exactly ONE call. Re-evaluation produces TWO. No assertion about
        the VALUES can tell those apart, however many values it checks — which is why
        this one is about the call.

    If you are restructuring the loop and this fails, the question to answer is whether
    the gate still reads position state AFTER the shadow has yielded. If it does, update
    the expected sequence. If it does not, this test has just done its job.
    """
    from app.services.live.crypto_loop import LiveCryptoLoop

    loop = LiveCryptoLoop()
    calls: list[str] = []

    async def _fetch(*a, **k):
        return _frame()

    async def _block(pair):
        calls.append("block")
        return "already in a position"

    async def _shadow(pair, entry, engine_policy=None):
        calls.append("shadow")

    async def _census(*a, **k):
        calls.append("census")

    monkeypatch.setattr(loop, "_fetch_bars", _fetch)
    monkeypatch.setattr(loop, "_entry_block_reason", _block)
    monkeypatch.setattr(loop, "_shadow_evaluate", _shadow)
    monkeypatch.setattr(loop, "_maybe_emit_census", _census)
    monkeypatch.setattr(loop, "_act", lambda *a, **k: _noop())
    monkeypatch.setattr(loop.paper, "on_tick", lambda *a, **k: [])
    monkeypatch.setattr("app.services.live.crypto_loop._ticker_price", lambda s: 100.0)

    await loop._tick_symbol("BTC/USD", "BTCUSDT")

    assert calls.count("block") == 2, (
        f"the block reason was computed {calls.count('block')} time(s) for one bar. One "
        "means the early value was REUSED at the gate, which is a trading behaviour "
        f"change; got {calls}"
    )
    assert calls == ["block", "shadow", "census", "block"], calls


async def test_a_position_closing_during_the_shadow_is_seen_by_the_gate(monkeypatch):
    """THE VALUE the call-order test cannot check, driven directly.

    This is the defect 4b-i names, made to happen rather than waited for. Production has
    held both pairs for 25 hours with zero closes, so `_has_position` cannot change there
    and a reusing implementation would produce byte-identical output to a correct one.
    Here the position closes DURING the shadow's await, which is the only window in which
    the two implementations differ:

        reused    the gate sees "already in a position" and returns -> no evaluation
        correct   the gate re-reads, finds nothing held, and the bar is evaluated

    The record still carries the value that was true when the bar was graded, which is
    what `engine_policy` is for — it is a statement about that moment, not a prediction.
    """
    import asyncio

    from app.services.live.crypto_loop import LiveCryptoLoop

    loop = LiveCryptoLoop()
    held = {"value": True}
    recorded: list[str | None] = []
    evaluated: list[str] = []

    async def _fetch(*a, **k):
        return _frame()

    async def _has_position(pair):
        return held["value"]

    async def _shadow(pair, entry, engine_policy=None):
        recorded.append(engine_policy)
        await asyncio.sleep(0)        # the yield 4b-i is about
        held["value"] = False          # the position closes while the shadow runs

    def _evaluate(pair, entry, bias, risk_pct):
        evaluated.append(pair)
        raise AssertionError("unreachable — replaced below")

    class _Trace:
        reasons: list[str] = []
        summary = "no setup"

    def _evaluate_ok(pair, entry, bias, risk_pct):
        evaluated.append(pair)
        return None, _Trace()

    monkeypatch.setattr(loop, "_fetch_bars", _fetch)
    monkeypatch.setattr(loop, "_has_position", _has_position)
    monkeypatch.setattr(loop, "_open_count", lambda: _zero())
    monkeypatch.setattr(loop, "_shadow_evaluate", _shadow)
    monkeypatch.setattr(loop, "_maybe_emit_census", lambda *a, **k: _noop())
    monkeypatch.setattr(loop, "_record_abstention", lambda *a, **k: _noop())
    monkeypatch.setattr(loop, "_act", lambda *a, **k: _noop())
    monkeypatch.setattr(loop.paper, "on_tick", lambda *a, **k: [])
    monkeypatch.setattr("app.services.live.crypto_loop._ticker_price", lambda s: 100.0)
    monkeypatch.setattr(
        "app.services.live.crypto_loop.evaluate_latest_bar_traced", _evaluate_ok
    )

    await loop._tick_symbol("BTC/USD", "BTCUSDT")

    assert recorded == ["already in a position"], (
        "the record must carry the block reason as it was when the bar was graded"
    )
    assert evaluated == ["BTC/USD"], (
        "the position closed during the shadow's await and the engine still skipped the "
        "bar on 'already in a position' — the gate reused a value that had gone stale, "
        "which is a changed trading decision produced by a bookkeeping change"
    )


# ---------------------------------------------------------------------------
# Criterion 1 — the census is emitted, and only on a real session rollover
# ---------------------------------------------------------------------------
async def test_the_census_is_emitted_once_when_the_ny_date_rolls(monkeypatch):
    """A day's bars cannot be counted until the day is over.

    Emitting early would report a partial window as a whole one — the undercount this
    record exists to detect, produced by the record itself. Emitting more than once would
    put two censuses in the store for one `(instrument, signal_tf, session_date)`, and
    the conformance suite would count the window twice.
    """
    from app.services.live.crypto_loop import LiveCryptoLoop

    loop = LiveCryptoLoop()
    emitted: list[str] = []

    async def _emit(pair, bsym, session_date, tf):
        emitted.append(session_date)

    monkeypatch.setattr(loop, "_emit_census", _emit)

    # 23:50 and 23:55 NY on the 14th, then 00:00 NY on the 15th. Bar CLOSE times are
    # +5m, so the third bar closes at 00:05 on the 15th and is the first of the new day.
    for start in ("2026-08-15 03:45", "2026-08-15 03:50"):
        await loop._maybe_emit_census("BTC/USD", "BTCUSDT", _frame(1, start))
    assert emitted == [], "no rollover yet — the session date has not changed"

    await loop._maybe_emit_census("BTC/USD", "BTCUSDT", _frame(1, "2026-08-15 04:00"))
    assert emitted == ["2026-08-14"], "the census must cover the day that ENDED"

    await loop._maybe_emit_census("BTC/USD", "BTCUSDT", _frame(1, "2026-08-15 04:05"))
    assert emitted == ["2026-08-14"], "a second bar in the new day must not re-emit"


async def test_a_census_failure_cannot_stop_the_engine(monkeypatch):
    """A measurement of the engine may not be able to break it, exactly as the shadow."""
    from app.services.live.crypto_loop import LiveCryptoLoop

    loop = LiveCryptoLoop()

    async def _boom(*a, **k):
        raise RuntimeError("the store is on fire")

    monkeypatch.setattr(loop, "_emit_census", _boom)
    await loop._maybe_emit_census("BTC/USD", "BTCUSDT", _frame(1, "2026-08-15 03:50"))
    await loop._maybe_emit_census("BTC/USD", "BTCUSDT", _frame(1, "2026-08-15 04:00"))


async def _noop():
    return None


async def _zero():
    return 0
