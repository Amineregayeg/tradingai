"""The population record — `scan_census` — derived from OUTSIDE the emitting loop (T-0011).

WHY THIS MODULE EXISTS AND WHY IT DOES NOT LIVE IN `crypto_loop`

The conformance suite is a pure function of stored telemetry, which means the engine
controls its own denominator. An engine that discards candidates before writing a
`setup_evaluation` emits a small, immaculate corpus and scores 100% fidelity while running
mostly on undocumented logic. `scan_census` makes the denominator explicit.

That only works if the census is not the emitting code's account of itself. A counter the
scan loop increments would be exactly that, with one extra step — and it fails in a way that
is invisible:

    the process restarts mid-session
    -> bars_observed, evaluations_emitted and unemitted_bars ALL undercount together
    -> the reconciliation holds perfectly
    -> a fraction of a day, counted honestly, is indistinguishable from a full one

So both counts are derived here, from sources the loop does not maintain:

    bars_observed        the bar series, re-fetched for the window
    evaluations_emitted  COUNT of stored setup_evaluation rows whose BAR time is in the window

and the bars that went missing are the SET DIFFERENCE of the two, never a counter. That is
what lets the census CONTRADICT the loop, which is the only thing a population record is for.
A restart now loses the *reason* a bar was omitted — never the fact that it was.

Where those missing bars are REPORTED is decided by the contract and not by us: see the
classification block below. `unemitted_bars` can only hold an omission a registry rule
authorises, ours are authorised by a policy or by nothing at all, so the array stays empty
and the counts go in `notes` with the resulting imbalance left standing.

THE TIME FIELD, AND WHY BOTH OBVIOUS CHOICES ARE WRONG

`telemetry_records` has two time columns and neither can be used as it stands:

    created_at    a real UTC datetime — but WRITE time, not bar time
    timestamp_ny  bar time — but a STRING, and New York LOCAL

* Filtering on `created_at` is not drift, it is a deterministic off-by-one. Measured on
  production rows: a 5m bar stamped `20:35:00-04:00` is written at `00:40:18Z` — the bar
  OPENS at 00:35Z and CLOSES at 00:40Z, so at 5m the write time is a full bar period after
  the stamp. `bars_observed` would exceed `evaluations_emitted` by exactly one at every
  window boundary, forever, and each of those would be reported as undocumented logic. An
  alarm that fires every cycle gets muted, and a muted alarm is the silence we started from.
* Comparing `timestamp_ny` as a string is off by 4-5 hours against a UTC window, and it is
  plausible because the format sorts. It is also not even self-consistent: across the autumn
  DST fall-back `01:59:00-04:00` sorts AFTER `01:00:00-05:00` while being 1 minute EARLIER
  (05:59Z against 06:00Z). One night a year, on a 24/7 market, and no comparison raises.

So `timestamp_ny` is the right field — it is bar time — and it is PARSED, never compared as
text. `datetime.fromisoformat` reads the embedded offset, which is the same evidence GATE-023
requires the offset to be there for, and the fall-back inversion disappears because the two
timestamps carry different offsets.

BAR OPEN VERSUS BAR CLOSE

`timestamp_ny` carries the bar's OPEN time (see the measurement above), and so does the
`scan_context.bar_close_time_ny` field, despite its name — recorded as B64. Everything here
therefore converts open -> close explicitly, on both sides of the comparison, so the two
sides cannot disagree about which convention they are using.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.telemetry_record import RECORD_SCAN_CENSUS, RECORD_SETUP_EVALUATION, TelemetryRecord
from app.services.telemetry import contract_loader as contract
from app.services.telemetry import records as rec
from app.services.telemetry.ny_time import NY, iso_ny

# --------------------------------------------------------------------------------------
# HOW AN OMISSION IS CLASSIFIED, and why none of these is ever written into a `rule_id`
# --------------------------------------------------------------------------------------
#
# The contract authorises a skipped bar in exactly two ways, and only one of them has a
# per-bar record:
#
#     POLICY-authorised   declared ONCE, in `emission_policy_id`. No per-bar record is
#                         expected, and `unemitted_bars` is the wrong place for it —
#                         putting it there would invent a rule that does not exist.
#     RULE-authorised     a per-bar entry in `unemitted_bars` naming a real GATE-nnn.
#     FAILURE             authorised by NEITHER, and the contract has no slot for it.
#
# `unemitted_bars.items` REQUIRES `rule_id` and pins it to the registry's id pattern, so a
# non-rule value cannot even be stored — `store.py` validates before it writes and raises.
# The schema's own prose meanwhile describes "an entry with no rule_id" as the case C-13
# must catch, which the `required` list makes unreachable (B65). Both facts point the same
# way: there is no honest way to put a failure in that array, so we do not.
#
# Our engine declares `every-closed-bar-with-sufficient-history-v2`, so a bar skipped for
# insufficient history IS policy-authorised. A bar skipped because something threw is not:
# a dead database is not a history condition, whatever the policy's name covers (B68).
#
# These two labels are therefore INTERNAL classification, used to count and to explain in
# `notes` — a field the contract accepts as free text. They are never a rule id, never an
# added schema property, and never presented as authorisation.

#: Skipped under the declared emission policy — insufficient history. Not an omission the
#: contract expects a per-bar record for.
OMISSION_POLICY = "POLICY"

#: Skipped because something FAILED — a dead database, a missing panel, a schema violation,
#: a thin layout. Authorised by no rule and no policy. This is the class the contract cannot
#: represent, and the reason the reconciliation below is allowed to come out unbalanced.
OMISSION_FAILURE = "FAILURE"

OMISSION_CLASSES = frozenset({OMISSION_POLICY, OMISSION_FAILURE})

#: The machine-readable head of `notes`. `notes` is the only field the contract offers for
#: this, and putting the numbers behind a fixed prefix is what stops C-13 having to read
#: prose to tell an EXPLAINED imbalance from a SILENT one — which is the whole difference
#: between an honest census and the honest-LOOKING one this task exists to prevent.
ACCOUNTING_PREFIX = "C13-ACCOUNTING"

#: Bar length per schema timeframe. `1MO` is absent on purpose — a month is not a fixed
#: period, so `open + period` would be a guess; asking for one raises rather than silently
#: using 30 days.
_TF_MINUTES: dict[str, int] = {
    "1M": 1, "3M": 3, "5M": 5, "15M": 15, "30M": 30,
    "1H": 60, "2H": 120, "4H": 240, "1D": 1440, "1W": 10080,
}


def period_for(signal_tf: str) -> timedelta:
    """The bar length for a schema timeframe. Raises on anything without a fixed one."""
    try:
        return timedelta(minutes=_TF_MINUTES[signal_tf])
    except KeyError:
        raise ValueError(
            f"no fixed bar period for signal_tf {signal_tf!r}. A census converts bar OPEN to "
            "bar CLOSE by adding the period, and a guessed period silently shifts every "
            "boundary in the window."
        ) from None


def session_window(session_date: str) -> tuple[datetime, datetime]:
    """`[from, to)` in UTC for one NY session date, DST-aware.

    Built from NY midnight to the NEXT NY midnight rather than by adding 24 hours, so the
    spring-forward day is 23 hours long and the fall-back day is 25 — which is what makes
    `bars_observed` independently checkable against the window length on those two days
    instead of off by one bar-hour (GATE-023).
    """
    day = date.fromisoformat(session_date)
    start = datetime.combine(day, time(0, 0), tzinfo=NY)
    end = datetime.combine(day + timedelta(days=1), time(0, 0), tzinfo=NY)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def session_date_of(moment: datetime) -> str:
    """The NY session date a UTC instant falls in."""
    return moment.astimezone(NY).date().isoformat()


def bar_close(bar_open: datetime, period: timedelta) -> datetime:
    """A bar's close time, in UTC, from its OPEN time. The one place this arithmetic lives."""
    if bar_open.tzinfo is None:
        raise ValueError(
            "naive bar timestamp. A bar time with no zone acquires the machine's, which is "
            "how a census is correct in CI and 4 hours wrong in production (GATE-023)."
        )
    return bar_open.astimezone(timezone.utc) + period


def observed_closes(
    bar_opens: Iterable[datetime], period: timedelta,
    window_from: datetime, window_to: datetime,
) -> list[datetime]:
    """Closed bars whose CLOSE falls in `[from, to)`, from the bar series. Sorted, unique."""
    seen = {
        c for o in bar_opens
        if window_from <= (c := bar_close(o, period)) < window_to
    }
    return sorted(seen)


async def emitted_closes(
    db: AsyncSession, *, instrument: str, signal_tf: str, period: timedelta,
    window_from: datetime, window_to: datetime,
) -> list[datetime]:
    """Bar CLOSE times of the stored `setup_evaluation` rows for this window.

    The window filter is applied in Python, after parsing, and NOT in SQL. That is
    deliberate: the only bar-time column is `timestamp_ny`, a New-York-local string, and
    every way of comparing it in SQL is either a string comparison (wrong across the DST
    fall-back, and silent) or a cast that assumes an offset (wrong for half the year). The
    SQL filter is therefore only on the indexed identity columns, which cannot be wrong, and
    the time comparison happens where the offset can actually be read.

    Cost: one row per bar per instrument per timeframe over the table's whole history —
    ~288/day/instrument at 5m. Fine at this size and recorded as B66 for when it is not.
    """
    stmt = select(TelemetryRecord.timestamp_ny).where(
        TelemetryRecord.record_type == RECORD_SETUP_EVALUATION,
        TelemetryRecord.instrument == instrument,
        TelemetryRecord.signal_tf == signal_tf,
        TelemetryRecord.timestamp_ny.is_not(None),
    )
    out: set[datetime] = set()
    for (stamp,) in (await db.execute(stmt)).all():
        try:
            opened = datetime.fromisoformat(stamp)
        except ValueError:
            # An unparseable stamp is not silently dropped from the denominator — it is
            # counted nowhere and shows up as a reconciliation gap, which is a finding.
            continue
        if opened.tzinfo is None:
            continue
        closed = bar_close(opened, period)
        if window_from <= closed < window_to:
            out.add(closed)
    return sorted(out)


@dataclass(frozen=True)
class Accounting:
    """Where the bars went, for the classes `unemitted_bars` cannot hold.

    `unattributed` is its own number rather than folded into `failures`: after a restart the
    process genuinely cannot say why a bar was dropped, and "3 bars failed" and "3 bars went
    missing and nobody knows why" are different claims. Guessing the first from the second
    is the fabrication this record exists to end.
    """
    policy_excluded: int = 0
    failures: int = 0
    unattributed: int = 0
    causes: tuple[str, ...] = ()

    @property
    def total(self) -> int:
        return self.policy_excluded + self.failures + self.unattributed


def format_accounting(acc: Accounting) -> str:
    """The `notes` string. One implementation, so the writer and C-13 cannot drift apart."""
    head = (
        f"{ACCOUNTING_PREFIX} policy_excluded={acc.policy_excluded} "
        f"failures={acc.failures} unattributed={acc.unattributed}"
    )
    if acc.total == 0 and not acc.causes:
        return head
    body = [head]
    if acc.total:
        body.append(
            "unemitted_bars is EMPTY and that is not a claim that nothing was skipped: the "
            "contract can only represent an omission that a registry rule authorises, and "
            "none of these is one."
        )
    if acc.policy_excluded:
        body.append(
            f"{acc.policy_excluded} bar(s) are authorised by the declared "
            "emission_policy_id (insufficient history) and are not expected to carry a "
            "per-bar record."
        )
    if acc.failures:
        body.append(
            f"{acc.failures} bar(s) were not evaluated because something FAILED, which is "
            "authorised by neither a rule nor the policy. The contract has no slot for it."
        )
    if acc.unattributed:
        body.append(
            f"{acc.unattributed} bar(s) are missing with no recorded cause (the engine "
            "restarted during the session, or the bar predates this run)."
        )
    if acc.causes:
        body.append("causes: " + "; ".join(acc.causes))
    return " ".join(body)


def parse_accounting(notes: str | None) -> Accounting | None:
    """Read back what `format_accounting` wrote. None if this census declares nothing."""
    if not notes or ACCOUNTING_PREFIX not in notes:
        return None
    head = notes.split(ACCOUNTING_PREFIX, 1)[1]
    values: dict[str, int] = {}
    for token in head.split():
        key, sep, raw = token.partition("=")
        if sep and key in ("policy_excluded", "failures", "unattributed"):
            try:
                values[key] = int(raw)
            except ValueError:
                return None
    if len(values) != 3:
        return None
    return Accounting(**values)


async def build_scan_census(
    db: AsyncSession,
    *,
    declared: rec.DeclaredParameters,
    instrument: dict[str, Any],
    signal_tf: str,
    session_date: str,
    bar_opens: Sequence[datetime],
    attributions: dict[datetime, tuple[str, str]] | None = None,
    scan_id: str | None = None,
    data_gaps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build one census for one `(instrument, signal_tf, session_date)`.

    `attributions` maps a bar CLOSE time to `(omission_class, reason)`. It is the only input
    the emitting loop supplies, and it supplies no COUNT — losing it degrades the census from
    "this bar was dropped, here is why" to "this bar was dropped", never to "no bar was
    dropped". That asymmetry is the whole point of deriving the counts here.
    """
    period = period_for(signal_tf)
    frm, to = session_window(session_date)
    symbol = str(instrument["symbol"])

    observed = observed_closes(bar_opens, period, frm, to)
    emitted = await emitted_closes(
        db, instrument=symbol, signal_tf=signal_tf, period=period,
        window_from=frm, window_to=to,
    )
    emitted_set = set(emitted)
    attributions = attributions or {}

    # `unemitted_bars` STAYS EMPTY, and the empty array is not the claim that nothing was
    # skipped. The array can only hold an omission a registry rule authorises; none of our
    # omissions is one, and a fabricated rule id would be C-3-detectable doctrine we
    # invented. The counts go in `notes`, which the contract accepts as free text, and the
    # imbalance they cause is left standing rather than absorbed — see `format_accounting`.
    policy = failures = unattributed = 0
    causes: list[str] = []
    for c in observed:
        if c in emitted_set:
            continue
        attribution = attributions.get(c)
        if attribution is None:
            unattributed += 1
            continue
        cls, reason = attribution
        if cls == OMISSION_POLICY:
            policy += 1
        else:
            failures += 1
        if reason and reason not in causes:
            causes.append(reason)

    stray = emitted_set - set(observed)
    if stray:
        # Evaluations for bars the series does not contain. NOT balanced away: forcing the
        # arithmetic would fabricate the denominator the record exists to make honest.
        causes.append(
            f"{len(stray)} stored evaluation(s) have no matching bar in the series "
            f"(earliest {iso_ny(min(stray))})"
        )

    accounting = Accounting(
        policy_excluded=policy, failures=failures, unattributed=unattributed,
        causes=tuple(causes[:12]),
    )

    return rec.scan_census(
        declared=declared,
        instrument=instrument,
        signal_tf=signal_tf,
        session_date=session_date,
        window_from=frm,
        window_to=to,
        bars_observed=len(observed),
        evaluations_emitted=len(emitted_set),
        unemitted_bars=[],
        scan_id=scan_id,
        data_gaps=data_gaps,
        notes=format_accounting(accounting),
    )


# --------------------------------------------------------------------------------------
# C-13 — the reconciliation. A census nobody reads is the third layer of the same failure.
# --------------------------------------------------------------------------------------
MAJOR = "MAJOR"


@dataclass(frozen=True)
class Finding:
    severity: str
    scan_id: str
    check: str
    message: str

    def __str__(self) -> str:  # pragma: no cover - formatting only
        return f"[{self.severity}] {self.scan_id} {self.check}: {self.message}"


@dataclass
class Report:
    """What C-13 found, and — separately — how much it looked at.

    `examined` is not decoration. On the day this shipped the production store held 156
    telemetry records and ZERO censuses, so a check that reported only pass/fail would have
    reported green from an empty set and stayed green until the first census existed —
    which is precisely the window in which someone concludes the mechanism works. Zero is
    reported as its own outcome by every caller (`outcome`), never folded into a pass.
    """
    examined: int = 0
    findings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings

    @property
    def outcome(self) -> str:
        """`NOT_EXERCISED` | `PASS` | `FAIL`. Three outcomes, because two would lie."""
        if self.examined == 0:
            return "NOT_EXERCISED"
        return "PASS" if self.ok else "FAIL"


def reconcile_one(census: dict[str, Any], *, known_rule_ids: frozenset[str]) -> list[Finding]:
    """C-13 over a single census record.

    THE RECONCILIATION IS DELIBERATELY ALLOWED TO COME OUT UNBALANCED, and the distinction
    this function turns on is between an imbalance that is DECLARED and one that is SILENT.

    The contract can represent an omission authorised by a rule and an omission authorised
    by the emission policy. It cannot represent one caused by a FAILURE — a dead database,
    a missing panel, a thin layout — and `unemitted_bars` therefore stays empty for that
    class rather than carrying a rule id we made up. So `bars_observed` legitimately
    exceeds `evaluations_emitted + len(unemitted_bars)`, and the excess must be accounted
    for in `notes` to the bar.

    An empty array with a silent mismatch is exactly the honest-LOOKING census this whole
    chain exists to prevent, so that case is the most severe thing here. An accounted
    mismatch is still reported — a failure class of any size is undocumented logic and the
    reader must see it — but it is reported as what it is.
    """
    scan_id = str(census.get("scan_id", "<no scan_id>"))
    out: list[Finding] = []

    observed = int(census.get("bars_observed", 0))
    emitted = int(census.get("evaluations_emitted", 0))
    unemitted = census.get("unemitted_bars") or []
    gap = observed - emitted - len(unemitted)
    acc = parse_accounting(census.get("notes"))

    if acc is None:
        if gap != 0:
            out.append(Finding(
                MAJOR, scan_id, "reconciliation",
                f"bars_observed {observed} != evaluations_emitted {emitted} + "
                f"unemitted_bars {len(unemitted)} (difference {gap}), and notes account "
                "for none of it. The population does not add up, so no fidelity number "
                "computed over this window is a measurement of a known denominator.",
            ))
    elif acc.total != gap:
        out.append(Finding(
            MAJOR, scan_id, "reconciliation",
            f"bars_observed {observed} - evaluations_emitted {emitted} - unemitted_bars "
            f"{len(unemitted)} leaves {gap} unaccounted, but notes declare {acc.total} "
            f"(policy {acc.policy_excluded}, failures {acc.failures}, unattributed "
            f"{acc.unattributed}). The census disagrees with its own explanation.",
        ))
    else:
        if acc.failures:
            out.append(Finding(
                MAJOR, scan_id, "unrepresentable-omission",
                f"{acc.failures} bar(s) were observed and never evaluated because "
                "something FAILED. Authorised by no rule and no policy, so the contract "
                "cannot represent them and unemitted_bars is empty by necessity rather "
                "than by absence of omissions. This is undocumented logic.",
            ))
        if acc.unattributed:
            out.append(Finding(
                MAJOR, scan_id, "unattributed-omission",
                f"{acc.unattributed} bar(s) were observed, never evaluated, and nothing "
                "records why. An omission that cannot be attributed is still a failure.",
            ))

    # `unemitted_bars` should be empty for us, but the check does not assume it: a future
    # rule-authorised omission is legitimate, and this is what keeps it honest.
    for i, entry in enumerate(unemitted):
        where = f"unemitted_bars[{i}] {entry.get('bar_close_time_ny', '<no bar time>')}"
        rule_id = entry.get("rule_id")

        if not rule_id or rule_id not in known_rule_ids:
            out.append(Finding(
                MAJOR, scan_id, "undocumented-logic",
                f"{where} cites rule_id {rule_id!r}, which is not in the registry. The "
                "schema's own words: an omission with no rule authorising it is "
                "undocumented logic.",
            ))

        if not str(entry.get("reason") or "").strip():
            out.append(Finding(
                MAJOR, scan_id, "empty-reason",
                f"{where} carries an empty reason. A cited rule with no reason names the "
                "authority and not the cause.",
            ))

    return out


def reconcile(records: Iterable[dict[str, Any]]) -> Report:
    """C-13 over a corpus. Non-census records are ignored, not counted."""
    known = contract.known_rule_ids()
    report = Report()
    for r in records:
        if r.get("record_type") != RECORD_SCAN_CENSUS:
            continue
        report.examined += 1
        report.findings.extend(reconcile_one(r, known_rule_ids=known))
    return report
