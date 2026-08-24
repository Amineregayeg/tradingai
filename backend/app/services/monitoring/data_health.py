"""Health of the things that fail silently (task 4.6 follow-up / KNOWN_ISSUES B1).

WHY THIS EXISTS
Two systems here can die without anyone noticing, and both matter more than the
app itself:

  * The dominance collector. Its data is UNRECOVERABLE — no source sells
    intraday dominance history, so it exists only because something was
    recording at the time. Its container reports unhealthy roughly ten minutes
    after samples stop, but nothing read that healthcheck. A quiet death costs
    days that no later fix retrieves.
  * Backups. A backup job that stops is invisible by construction: everything
    looks fine right up until you need a restore.

THE RULE THAT SHAPES EVERY FUNCTION HERE
A check that cannot see its data reports ``unavailable``, never ``healthy``.
Silence and health look identical from the outside, and conflating them is how a
monitoring surface ends up reassuring people about a system it stopped watching
weeks ago. Every status below distinguishes "I looked and it is fine" from "I
could not look".
"""
from __future__ import annotations

import csv
import io
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.logging import logger


def with_summary(formatter):
    """Attach a one-line `summary` to EVERY dict a health function returns.

    **`B231`: the frontend's `DataHealth` type ENUMERATED its components**, so a renderer
    faithful to its type rendered two rows while `problems.length` counted five. The obvious
    repair — add three more fields — is the same defect, *and worse, because a type that
    enumerates looks like documentation.*

    The fix has to make the frontend able to render a component it has never heard of, and
    the thing that blocks that is not the nesting: **the five components share no vocabulary.**
    `age_minutes` / `age_bars` / `age_hours` / `withdrawn_symbols` / `absent_panels` — no field
    set a generic row can format. Derive the row and the hardcoded list merely MOVES into the
    formatter, harder to see.

    So each component emits its own summary, **computed where its fields are known**, and the
    frontend renders `{name, status, summary}` knowing nothing about any of them.

    **A DECORATOR RATHER THAN A LINE AT EACH RETURN.** These functions have 18 return sites
    between them; a summary added by hand at each is a summary that can be FORGOTTEN at one,
    and the one it is forgotten at is an error path — the exact case the panel most needs to
    show. Here no return site can miss it.
    """
    import functools
    import inspect as _inspect

    def decorate(fn):
        if _inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def awrapper(*a, **k):
                out = await fn(*a, **k)
                return {**out, "summary": formatter(out)} if isinstance(out, dict) else out
            return awrapper

        @functools.wraps(fn)
        def wrapper(*a, **k):
            out = fn(*a, **k)
            return {**out, "summary": formatter(out)} if isinstance(out, dict) else out
        return wrapper

    return decorate


def _fallback_summary(c: dict) -> str | None:
    """What every component says when it cannot say anything specific.

    `reason` first because an unavailable or idle component has already written the one
    sentence that matters, and re-deriving it would be a second statement of it.
    """
    reason = c.get("reason")
    if reason:
        return str(reason)
    if c.get("watching") is False:
        return "not being watched"
    return None


#: Read-only mounts into the api container. Defaults match compose.vps.yaml.
DOMINANCE_DIR = Path(os.getenv("DOMINANCE_DATA_DIR", "/data/dominance"))
BACKUP_DIR = Path(os.getenv("BACKUP_STATUS_DIR", "/data/backups"))

#: A gap beyond this is not jitter. Deliberately expressed in minutes and left
#: unchanged when the collector's cadence changed from 60s to 10s: these bound how
#: long the series may go SILENT, which is a question about acceptable data loss,
#: not about the poll rate. Tightening them to track the cadence would trade a real
#: signal for flapping — the same argument KNOWN_ISSUES B11 makes for the
#: container healthcheck's 600s threshold.
COLLECTOR_STALE_MIN = 5.0
COLLECTOR_DOWN_MIN = 30.0

#: What the collector is CONFIGURED to sample at, in seconds. Keep in step with
#: `--loop` in `deploy/compose.dominance.yaml` (10s since 2026-08-10; 60s before).
#:
#: DECLARED, NEVER INFERRED, and that distinction is the entire value of this
#: constant. Density is here to catch a collector that is degrading but not dead,
#: so it must be measured against what the collector is SUPPOSED to deliver. Derive
#: the denominator from the samples themselves — the obvious-looking fix — and a
#: collector limping along at one sample a minute reports a serene 100%, because
#: the yardstick degrades with the thing it is measuring.
#:
#: This is also why a literal `60` here was worse than wrong once the cadence moved.
#: A healthy hour at 10s is ~360 samples; against a 60-sample expectation that is
#: 600%, clamped to a permanent 100.0 — so a collector degrading all the way back
#: to 60 samples/hour would still have read exactly 100.0% healthy, on the one
#: dataset in this system that cannot be backfilled.
#: This is the SECOND place the cadence is declared — `deploy/compose.dominance.yaml`
#: is the first — and a comment asking the next person to keep them in step is exactly
#: the habit that produced this whole task. `check_deploy_drift.py` cannot catch the
#: disagreement either: it compares a compose file against the server, and both of
#: these live in the repo. So it is pinned by a test instead —
#: `test_the_expected_cadence_matches_the_deployed_compose_file` parses `--loop N` out
#: of that compose file and fails if this constant does not equal N.
#:
#: NOT an env var, deliberately. An override would be a THIRD declaration, and the
#: one place the test above goes blind: set in both compose files with the same value
#: while disagreeing with `--loop`, it would move the live denominator with nothing
#: turning red. `fixed_config.py` already made this call for the engine's settings and
#: wrote down why — "with exactly one configuration in the system, there is no second
#: value for a restart to disagree with", which is how A9 was closed by construction.
#: The cadence is not a secret, is not per-environment, and has exactly one correct
#: value at any instant. Changing it is a code change and a deploy, on purpose.
EXPECTED_POLL_SECONDS = 10.0

#: Matches the backup script's own staleness rule, so the two cannot disagree
#: about whether backups are healthy.
BACKUP_STALE_HOURS = 48.0

#: Only the tail of the CSV is read. At 10s a year is ~3.2M rows (~300 MB); parsing
#: that on every dashboard poll would be pointless work for a freshness check that
#: only needs the recent past.
#:
#: The size has to cover the density window with room to spare, so check it when the
#: cadence changes. Measured on the live file (2,047,434 bytes / 20,246 rows): rows are
#: **101 bytes**, so 96 KiB is ~970 samples — **2.7 hours** at 10s against a 1-hour
#: window. It was ~16 hours of headroom at 60s. Still ample, but no longer so large
#: that it can be assumed without arithmetic.
TAIL_BYTES = 96 * 1024


def _read_tail(path: Path, nbytes: int = TAIL_BYTES) -> list[str]:
    """Last complete lines of a file, cheaply."""
    size = path.stat().st_size
    with path.open("rb") as f:
        if size > nbytes:
            f.seek(size - nbytes)
            f.readline()  # discard the partial first line
        return f.read().decode("utf-8", errors="replace").splitlines()


def _dominance_summary(c: dict) -> str:
    """The collector's line. Its data is UNRECOVERABLE, so age leads."""
    if (fb := _fallback_summary(c)) is not None:
        return fb
    age = c.get("age_minutes")
    density = c.get("recent_density_pct")
    return (
        f"{age:.0f}m since the last sample · {density:.0f}% of the last hour"
        if age is not None and density is not None
        else "collector state unreadable"
    )


@with_summary(_dominance_summary)
def dominance_health() -> dict:
    """Freshness and continuity of the intraday dominance series."""
    path = DOMINANCE_DIR / "dominance_intraday_raw.csv"

    if not path.is_file():
        return {
            "status": "unavailable",
            "reason": f"{path} is not readable from this container",
            # Explicitly NOT "healthy". If the mount is missing we are not
            # watching the collector, and saying so is the whole point.
            "watching": False,
        }

    try:
        lines = _read_tail(path)
    except Exception as exc:  # noqa: BLE001
        return {"status": "unavailable", "reason": str(exc), "watching": False}

    header = "ts_utc,TOTAL,TOTAL2,TOTAL3,BTC_D,ETH_D,USDT_D,coverage_pct,supplies_age_h"
    rows = list(csv.DictReader(io.StringIO("\n".join([header] + [
        ln for ln in lines if ln and not ln.startswith("ts_utc")
    ]))))
    if not rows:
        return {"status": "unavailable", "reason": "no parseable rows", "watching": False}

    now = datetime.now(tz=timezone.utc)
    try:
        last_ts = datetime.fromisoformat(rows[-1]["ts_utc"])
    except Exception:  # noqa: BLE001
        return {"status": "unavailable", "reason": "unreadable timestamp", "watching": False}

    age_min = (now - last_ts).total_seconds() / 60.0

    # Density over the recent window, not lifetime. A collector that died an
    # hour ago still shows excellent lifetime density, which is exactly the
    # reassuring-but-wrong number to put on a dashboard.
    window_start = now - timedelta(hours=1)
    recent = 0
    for r in rows:
        try:
            if datetime.fromisoformat(r["ts_utc"]) >= window_start:
                recent += 1
        except Exception:  # noqa: BLE001
            continue
    expected_in_window = max(1.0, 3600.0 / EXPECTED_POLL_SECONDS)
    recent_density = min(100.0, 100.0 * recent / expected_in_window)

    if age_min > COLLECTOR_DOWN_MIN:
        status = "down"
    elif age_min > COLLECTOR_STALE_MIN:
        status = "stale"
    else:
        status = "healthy"

    out = {
        "status": status,
        "watching": True,
        "last_sample": last_ts.isoformat(),
        "age_minutes": round(age_min, 1),
        "recent_density_pct": round(recent_density, 1),
        # What that percentage is measured against. Without it the figure is
        # uninterpretable — "100%" means nothing unless the reader knows whether
        # the expectation was 60 samples an hour or 360.
        "expected_poll_seconds": EXPECTED_POLL_SECONDS,
        "samples_in_tail": len(rows),
    }
    if status != "healthy":
        out["warning"] = (
            f"no sample for {age_min:.0f} minutes — this data cannot be "
            "backfilled, so every minute the collector is down is lost permanently"
        )
    try:
        out["live_priced_pct"] = float(rows[-1].get("coverage_pct") or 0)
        out["supplies_age_h"] = float(rows[-1].get("supplies_age_h") or 0)
    except (TypeError, ValueError):
        pass
    return out


def _backup_summary(c: dict) -> str:
    if (fb := _fallback_summary(c)) is not None:
        return fb
    age = c.get("age_hours")
    kept = c.get("backup_count")
    return (
        f"{age:.0f}h since the last backup · {kept} kept"
        if age is not None
        else f"{kept} backup(s) kept, age unknown"
    )


@with_summary(_backup_summary)
def backup_health() -> dict:
    """Whether backups are running and verifying."""
    status_file = BACKUP_DIR / "status.json"

    if not status_file.is_file():
        return {
            "status": "unavailable",
            "reason": f"{status_file} is not readable from this container",
            "watching": False,
        }

    try:
        data = json.loads(status_file.read_text())
    except Exception as exc:  # noqa: BLE001
        return {"status": "unavailable", "reason": str(exc), "watching": False}

    try:
        last_run = datetime.fromisoformat(str(data.get("last_run", "")).replace("Z", "+00:00"))
        age_h = (datetime.now(tz=timezone.utc) - last_run).total_seconds() / 3600.0
    except Exception:  # noqa: BLE001
        return {"status": "unavailable", "reason": "unreadable last_run", "watching": False}

    ok = bool(data.get("ok"))
    if not ok:
        status = "failing"
    elif age_h > BACKUP_STALE_HOURS:
        # A status file saying "ok" from three weeks ago is worse than none.
        status = "stale"
    else:
        status = "healthy"

    out = {
        "status": status,
        "watching": True,
        "last_run": last_run.isoformat(),
        "age_hours": round(age_h, 1),
        "backup_count": data.get("backup_count"),
        "message": data.get("message"),
    }
    if status == "failing":
        out["warning"] = f"the last backup did not verify: {data.get('message')}"
    elif status == "stale":
        out["warning"] = f"no backup for {age_h:.0f} hours"
    return out


#: How many bar-periods of silence before a due evaluation is treated as missing.
#: Records are written a few seconds AFTER a bar closes (measured: `timestamp_ny`
#: is the bar's open and `created_at` lands ~20 s after its close), so one whole
#: period of slack absorbs the write lag plus a missed poll without crying wolf.
#: Expressed in bar-periods rather than minutes precisely so it tracks `ENTRY_TF`
#: instead of silently becoming wrong when it changes (B21).
def _as_utc(dt: datetime) -> datetime:
    """Naive timestamps out of SQLite are UTC; Postgres returns them aware."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


SHADOW_STALE_BARS = 2.0
SHADOW_DOWN_BARS = 4.0


def _shadow_summary(c: dict) -> str:
    """LIVENESS ONLY — the payload says so itself and this line must not overclaim."""
    if (fb := _fallback_summary(c)) is not None:
        return fb
    bars = c.get("age_bars")
    state = c.get("evaluation_state", "unknown")
    observed, expected = c.get("observed_in_window"), c.get("expected_in_window")
    head = f"{bars:.1f} bars since the last record ({state})" if bars is not None else state
    return (
        f"{head} · {observed} of ~{expected:.0f} expected in the window"
        if observed is not None and expected is not None
        else head
    )


@with_summary(_shadow_summary)
async def shadow_health() -> dict:
    """Is the contract engine's shadow still RECORDING? Not: is it right.

    WHY THIS EXISTS (B32)
    `shadow.py:20` — "every failure is swallowed and logged, and the return value is
    never read by the trading path" — and `:156` — "a shadow that can break the engine
    is worse than no shadow". Both are correct and neither may change. The consequence
    is that a broken shadow is **silent by construction**, and there was no second
    signal. On 2026-08-13 a vocabulary mismatch made every record fail schema
    validation; the engine traded normally and the evidence base went dark for forty
    minutes. Three agents independently explained the silence and all three were wrong
    — none considered that the shadow was crashing, because a legitimate wait looks
    identical from outside.

    WHAT COUNTS AS A LEGITIMATE SILENCE CHANGED WITH T-0010
    The shadow used to sit BELOW the entry gates, so `already in a position` suppressed
    it — and since the engine holds a position most of the time, long silences were
    normal and a naive signal would have screamed all day. `_shadow_evaluate` now runs
    ABOVE the gates (`crypto_loop`), and `shadow.py` says so outright: "engine paused,
    already in a position and max_concurrent no longer suppress a record". So `blocked`
    is no longer a state, and a due bar with no record now means broken, full stop.
    """
    from sqlalchemy import func, select

    from app.db.session import async_session_maker
    from app.models.engine_run import EngineRun
    from app.models.telemetry_record import TelemetryRecord
    from app.services.live.fixed_config import ENTRY_TF, SYMBOLS
    from app.services.market_data.sources.dominance import _TF_SECONDS

    # DERIVED, never written down. A hardcoded cadence is B21's class and would have
    # been wrong within a day: 1H -> 5m multiplied it by twelve.
    bar_seconds = _TF_SECONDS.get(ENTRY_TF)
    if bar_seconds is None:
        return {
            "status": "unavailable",
            "watching": False,
            "reason": f"ENTRY_TF {ENTRY_TF!r} has no known duration",
        }
    symbols = len(SYMBOLS)
    expected_per_hour = round(3600.0 / bar_seconds * symbols, 1)

    scope = {
        # CRITERION 9. This section attests LIVENESS ONLY. A shadow can be alive,
        # writing on every permitted cycle, and grading a still-forming bar — which
        # is a real defect this project shipped (the perpetual panels fed the forming
        # bar into GATE-008's MAIN panel). Every field below would read healthy
        # throughout. Without this said in the payload, the first green reading is
        # what someone cites when asked whether the correlate layer can be trusted.
        "attests": "liveness_only",
        "does_not_attest": [
            "correctness of the evaluation",
            "freshness of the correlate panels",
            "whether the grade reflects closed bars",
        ],
    }

    try:
        async with async_session_maker() as db:
            active = (
                await db.execute(
                    select(EngineRun)
                    .where(EngineRun.ended_at.is_(None))
                    .order_by(EngineRun.started_at.desc())
                    .limit(1)
                )
            ).scalars().first()

            if active is None:
                # Nothing is expected, so nothing is wrong. Reported as `idle` and
                # `watching: False` rather than `healthy`: the check is not looking at
                # a working shadow, it is looking at an engine that is not running,
                # and those must not read the same.
                return {
                    "status": "idle",
                    "watching": False,
                    "reason": "no active engine run — no evaluations are due",
                    "expected_per_hour": expected_per_hour,
                    **scope,
                }

            now = datetime.now(tz=timezone.utc)
            # SQLite hands back naive datetimes where Postgres returns aware ones, so
            # every timestamp out of the database is normalised before it is compared.
            # Skipping this passes in production and raises only under the test
            # backend — a difference that would be discovered by the suite, but as a
            # `status: unavailable` rather than as the type error it is.
            started = _as_utc(active.started_at)

            last = (
                await db.execute(
                    select(func.max(TelemetryRecord.created_at)).where(
                        TelemetryRecord.record_type == "setup_evaluation",
                        TelemetryRecord.created_at >= started,
                    )
                )
            ).scalar()

            window_start = max(now - timedelta(hours=1), started)
            recent = (
                await db.execute(
                    select(func.count()).select_from(TelemetryRecord).where(
                        TelemetryRecord.record_type == "setup_evaluation",
                        TelemetryRecord.created_at >= window_start,
                    )
                )
            ).scalar() or 0
    except Exception as exc:  # noqa: BLE001
        # Cannot see it is never "fine" — the rule this module is built on.
        return {"status": "unavailable", "watching": False, "reason": str(exc), **scope}

    run_age = (now - started).total_seconds()

    if last is None:
        # The run is young enough that the first bar has not closed yet. Genuinely
        # "not due", and distinguishing it from a dead shadow is the whole point.
        if run_age < bar_seconds * SHADOW_STALE_BARS:
            return {
                "status": "healthy",
                "watching": True,
                "evaluation_state": "not_due",
                "reason": (
                    f"run started {run_age / 60:.0f} min ago; first {ENTRY_TF} bar "
                    "has not closed yet"
                ),
                "expected_per_hour": expected_per_hour,
                "entry_tf": ENTRY_TF,
                **scope,
            }
        age_seconds = run_age
        last_iso = None
    else:
        last = _as_utc(last)
        age_seconds = (now - last).total_seconds()
        last_iso = last.isoformat()

    # The window is bounded below by the run's start, so a deploy gap is excluded
    # rather than counted as missing records — nothing was due while no run existed.
    window_minutes = max(0.0, (now - window_start).total_seconds() / 60.0)
    expected_in_window = expected_per_hour * (window_minutes / 60.0)
    density_pct = (
        min(100.0, 100.0 * recent / expected_in_window)
        if expected_in_window > 0
        else 100.0
    )

    age_bars = age_seconds / bar_seconds
    if age_bars > SHADOW_DOWN_BARS:
        status, state = "down", "due"
    elif age_bars > SHADOW_STALE_BARS:
        status, state = "stale", "due"
    else:
        status, state = "healthy", "not_due"

    out = {
        "status": status,
        "watching": True,
        "evaluation_state": state,
        "last_record": last_iso,
        "age_minutes": round(age_seconds / 60.0, 1),
        "age_bars": round(age_bars, 1),
        # What the age is measured against. `age_minutes` alone is uninterpretable —
        # eleven minutes is fine at 1H and two bars missed at 5m.
        "entry_tf": ENTRY_TF,
        "bar_seconds": bar_seconds,
        "symbols": symbols,
        "expected_per_hour": expected_per_hour,
        "observed_in_window": recent,
        # PRORATED TO THE WINDOW ACTUALLY MEASURED, not to a flat hour.
        #
        # The count already starts at the run's own start (a deploy gap is not a
        # shadow failure — during it, no run existed and nothing was due). But the
        # expectation beside it was a full-hour figure, so a seven-minute-old run
        # showing 6 records read as "6 against 24" — an apparent 4x shortfall that
        # was in fact AHEAD of rate.
        #
        # Misleading in the ALARMING direction is not the safe way round: a number
        # that cries shortfall on every restart is one a reader learns to skip, and
        # then it is not read on the day it is right. Same failure as a liveness
        # signal that fires on every blocked bar.
        "window_minutes": round(window_minutes, 1),
        "expected_in_window": round(expected_in_window, 1),
        # Clamped, and named as `dominance_health` names it — one word for one
        # concept, so nobody has to learn that two panels measure density
        # differently. Above 100 at startup is real and expected: both symbols
        # evaluate the newest closed bar the moment a run begins.
        "recent_density_pct": round(density_pct, 1),
        "stale_after_bars": SHADOW_STALE_BARS,
        **scope,
    }

    if status != "healthy":
        out["warning"] = (
            f"no shadow record for {age_bars:.1f} {ENTRY_TF} bars while the engine "
            f"run is active. The shadow swallows every exception by design, so this "
            f"field is the only thing that reports it."
        )
        # CRITERION: say what this CANNOT tell you, rather than implying it knows.
        # Two different failures present identically here and their remedies differ.
        out["ambiguous_between"] = [
            "the loop is turning and the shadow evaluation is raising (swallowed)",
            "the loop is not turning at all",
        ]
        # And the run row is not proof of life: A9/B14 — a process can die holding an
        # active run, which is exactly how a record was left reading OPEN for good.
        out["note"] = (
            "an active engine_run row means the run was never ENDED, not that the "
            "process is alive (B14)"
        )
    return out


#: How many bar-periods since a panel's newest complete bar CLOSED before it is stale.
#:
#: DERIVED FROM BAR DURATION, NEVER COPIED FROM THE COLLECTOR. `COLLECTOR_STALE_MIN = 5.0`
#: is right for a process polling every 10 s and catastrophically wrong here: measured
#: live at 10:59:53 with `ENTRY_TF = 5m`, the newest complete bar was LABELLED 10:50, so
#: its label age reaches 9.9 minutes in perfectly healthy operation. A 5-minute threshold
#: measured from the label would alarm on essentially every cycle, and an alarm that
#: fires every cycle gets muted — which is the silence this monitor exists to end.
#:
#: AND THE REFERENCE POINT IS THE BAR'S CLOSE, NOT ITS LABEL. The frames are fetched with
#: `drop_partial=True`, so the newest bar we see has already closed and the still-forming
#: one is correctly absent. Measured from the LABEL the healthy band is `[1, 2)` intervals
#: and any threshold has an offset nobody wrote down; measured from the CLOSE it is
#: `[0, 1)` and the threshold reads as "we have missed N bars". Either is defensible and
#: leaving it unstated is not: the same number against the wrong reference is off by one
#: interval, which at 5m is the difference between alarming always and never alarming.
PANEL_STALE_BARS = 2.0
PANEL_DOWN_BARS = 4.0


def _panel_summary(c: dict) -> str:
    """Three lists, and they stay THREE — an operator needs to know which axis failed."""
    if (fb := _fallback_summary(c)) is not None:
        return fb
    stale = len(c.get("stale_panels") or [])
    thin = len(c.get("thin_panels") or [])
    absent = len(c.get("absent_panels") or [])
    total = len(c.get("panels") or [])
    if not (stale or thin or absent):
        return f"{total} panel(s), none stale, thin or absent"
    return f"{total} panel(s) · {stale} stale · {thin} thin · {absent} absent"


@with_summary(_panel_summary)
async def panel_health() -> dict:
    """Are the GATE-008 roster panels RECENT, and are they THICK? Two answers, never one.

    WHY THIS EXISTS (B35, B40)
    `data_health` has carried panel recency for the dominance collector since it was
    written — `TOTAL` and `USDT.D` are watched. `BTCUSDT.P` and `ETHUSDT.P` arrive from a
    different host (`fapi.binance.com`) with a different failure mode and **nothing
    checked their age at all**. Half the roster was unmonitored.

    It is not cosmetic. GATE-008 grades a four-panel layout and GATE-002's 2-of-3
    disturbance count keys the risk matrix, so a FROZEN perpetual panel produces a
    confident disturbance grade computed from stale prices — present, well-formed, and
    wrong — while the roster check passes because the panel exists.

    WHY RECENCY AND THICKNESS ARE REPORTED SEPARATELY AND MUST STAY SEPARATE
    They measure different quantities: thickness is observations WITHIN a bar (density),
    recency is how long ago the newest bar closed (currency). A perfectly thick bar from
    six hours ago is fresh by one and stale by the other. And either can MANUFACTURE the
    other — filtering thin bars out leaves the newest-bar pointer on an older thick bar,
    which is B27 — so a merged verdict would answer two questions with one output and
    could not distinguish the two failures it exists to name.

    This is also why `GATE-007`'s existing `thin` list does not already cover this. It is
    built only `if bar_sample_count is not None`, and the perpetual panels never set it:
    an exchange bar is a candle, not a resampling of point observations. The two panels
    this monitor exists for are excluded from `thin` by the condition itself — not
    partially covered, structurally invisible.

    WHAT IT DOES NOT ATTEST — see `scope` in the payload.
    """
    import asyncio

    from app.services.live.fixed_config import ENTRY_TF
    from app.services.live.shadow import fetch_roster_panels
    from app.services.market_data.sources.dominance import _TF_SECONDS
    from app.services.rules.gate_008_roster import (
        MAIN, MIN_SAMPLES_PER_SYNTHETIC_BAR, NEGATIVE, POSITIVE,
    )

    roster = (MAIN, *POSITIVE, *NEGATIVE)

    bar_seconds = _TF_SECONDS.get(ENTRY_TF)
    if bar_seconds is None:
        return {
            "status": "unavailable",
            "watching": False,
            "reason": f"ENTRY_TF {ENTRY_TF!r} has no known duration",
        }

    scope = {
        # CRITERION 5. Recency and thickness ONLY. A panel can be seconds old, thick, and
        # carrying the wrong instrument's prices; it can be fresh and thick while a
        # different panel is missing entirely and the layout is ungradeable. Every field
        # below reads healthy in both cases. Without this said in the payload, the first
        # green reading is what someone cites when asked whether the correlate layer can
        # be trusted.
        "attests": "recency_and_thickness_only",
        "does_not_attest": [
            "that the values are correct, or that they came from the intended market",
            "that the roster is complete — a missing panel is absent here, not stale",
            "that the disturbance grade computed from these panels is sound",
            "that anything reads this field (nothing does — see B32's shape)",
        ],
        # CRITERION 2-i. The threshold tracks ENTRY_TF because that is the only timeframe
        # this module can see, and the panels are read at `signal_tf` — a PARAMETER that
        # `crypto_loop` happens to feed from `ENTRY_TF`. They coincide by PLUMBING, not by
        # definition. If `signal_tf` ever diverges, this monitor keeps measuring against
        # the wrong interval and goes silently wrong in the direction that alarms never.
        "timeframe_coupling": (
            f"thresholds derived from ENTRY_TF ({ENTRY_TF}); panels are read at "
            "signal_tf, which equals ENTRY_TF by plumbing rather than by definition"
        ),
        "reference_point": "bar CLOSE (label + one interval), not the bar's label",
        "stale_after_bars": PANEL_STALE_BARS,
        "down_after_bars": PANEL_DOWN_BARS,
        "min_samples_per_bar": MIN_SAMPLES_PER_SYNTHETIC_BAR,
    }

    try:
        # RAW `ENTRY_TF`, not its schema form. The sources take the timeframe the
        # engine uses ("5m"); `schema_tf` is for what goes INTO a telemetry record, and
        # handing "5M" to a fetch would ask for a timeframe no source knows. This is
        # B33's shape — two vocabularies for one quantity — and the reason it is worth a
        # comment is that both strings look equally plausible at the call site.
        fetched = await asyncio.to_thread(fetch_roster_panels, ENTRY_TF)
    except Exception as exc:  # noqa: BLE001 - a monitor may never break its host
        return {
            "status": "unavailable", "watching": False,
            "reason": f"panels unreadable ({type(exc).__name__}: {exc})",
            "scope": scope,
        }

    by_asset = {f.asset: f for f in fetched}
    now = datetime.now(tz=timezone.utc)
    panels: dict[str, dict] = {}

    for asset in roster:
        got = by_asset.get(asset)
        if got is None or got.frame is None or len(got.frame) == 0:
            # ABSENT is not STALE. A panel nobody served has no age, and reporting it as
            # infinitely old would put a missing feed and a frozen one under one word.
            panels[asset] = {
                "recency": {"status": "unavailable", "age_bars": None,
                            "reason": (got.note if got else None) or "panel not served"},
                "thickness": {"status": "unavailable", "samples": None,
                              "reason": "no bar to measure"},
            }
            continue

        # RECENCY, from the UNFILTERED frame. `fetch_roster_panels` deliberately does not
        # thin-filter, because filtering would leave this pointer on an older thick bar
        # and report a THIN panel as a STALE one.
        newest_open = got.frame.index[-1].to_pydatetime()
        newest_close = _as_utc(newest_open) + timedelta(seconds=bar_seconds)
        age_bars = (now - newest_close).total_seconds() / bar_seconds
        if age_bars < 0:
            # A BAR THAT CLOSES IN THE FUTURE IS NOT FRESH — IT IS UNMEASURABLE.
            #
            # The comparison chain below is one-sided, so without this a negative age
            # falls straight through to `fresh` and the monitor reports perfect health
            # forever. That is the catastrophic direction: not alarming every cycle,
            # which someone would notice and mute, but NEVER alarming, which nobody
            # notices at all.
            #
            # Two ways to get here and neither is exotic. `bar_seconds` comes from
            # `ENTRY_TF` while the panels are read at `signal_tf` — equal by PLUMBING,
            # not by definition (see `scope.timeframe_coupling`) — so a divergence makes
            # every close time land one wrong interval into the future. And a host clock
            # behind the exchange's timestamps does the same thing for free.
            #
            # Deliberately NOT `stale` or `down`: both assert something about the FEED,
            # and the feed may be perfectly healthy while the clock or the timeframe is
            # wrong. `unavailable` means nobody served this panel; this is its sibling —
            # served, and the arithmetic is impossible.
            recency_status = "invalid"
        elif age_bars >= PANEL_DOWN_BARS:
            recency_status = "down"
        elif age_bars >= PANEL_STALE_BARS:
            recency_status = "stale"
        else:
            recency_status = "fresh"

        recency = {
            "status": recency_status,
            "age_bars": round(age_bars, 2),
            "newest_bar_close": newest_close.isoformat(),
            "bar_seconds": bar_seconds,
        }
        if recency_status == "invalid":
            recency["warning"] = (
                f"{asset}: newest complete bar CLOSES {abs(age_bars):.1f} {ENTRY_TF} bars "
                "in the FUTURE — this panel's age cannot be measured, and the cause is "
                "the clock or the timeframe rather than the feed"
            )
        elif recency_status != "fresh":
            recency["warning"] = (
                f"{asset}: newest complete bar closed {age_bars:.1f} {ENTRY_TF} bars ago"
            )

        # THICKNESS, and a None count is ANSWERED rather than left absent.
        if got.sample_count is None:
            thickness = {
                "status": "not_applicable",
                "samples": None,
                # CRITERION 6a. Saying so beats falling out of the check the way these
                # panels already fall out of GATE-007's `thin` list, where the silence is
                # indistinguishable from having passed.
                "reason": (
                    "an exchange bar is a candle, not a resampling of point observations, "
                    "so there is no sample count to threshold"
                ),
            }
        else:
            margin = got.sample_count / MIN_SAMPLES_PER_SYNTHETIC_BAR
            thin = got.sample_count < MIN_SAMPLES_PER_SYNTHETIC_BAR
            thickness = {
                "status": "thin" if thin else "ok",
                "samples": got.sample_count,
                "minimum": MIN_SAMPLES_PER_SYNTHETIC_BAR,
                # The operating margin, printed because B40's finding is that it SHRANK
                # from 18x at 1H to 1.5x at 5m and nothing failed when it did. A ratio
                # trending toward 1.0 is the warning a boolean cannot give.
                "margin": round(margin, 2),
            }
            if thin:
                thickness["warning"] = (
                    f"{asset}: newest complete bar holds {got.sample_count} samples "
                    f"against a minimum of {MIN_SAMPLES_PER_SYNTHETIC_BAR}"
                )

        panels[asset] = {"recency": recency, "thickness": thickness}

    # NAMED, NOT AGGREGATED. A boolean would tell an operator something is wrong and not
    # which of two hosts to restart — the perpetual panels come from `fapi.binance.com`
    # and the others from our own collector, with independent failure modes.
    stale = [a for a, p in panels.items() if p["recency"]["status"] in ("stale", "down")]
    thin_panels = [a for a, p in panels.items() if p["thickness"]["status"] == "thin"]
    absent = [a for a, p in panels.items() if p["recency"]["status"] == "unavailable"]
    # Its own list. Folding it into `stale_panels` would send an operator to restart a
    # feed that is working, and folding it into `absent_panels` would say nobody served
    # a panel that was served.
    unmeasurable = [a for a, p in panels.items() if p["recency"]["status"] == "invalid"]

    if (absent or unmeasurable
            or any(p["recency"]["status"] == "down" for p in panels.values())):
        status = "down"
    elif stale or thin_panels:
        status = "failing"
    else:
        status = "healthy"

    return {
        "status": status,
        "watching": True,
        # The rollup exists so `data_health` can list a problem component. It is NOT the
        # answer — these three lists are, and they stay separate because an operator
        # needs to know which axis failed on which feed.
        "stale_panels": stale,
        "thin_panels": thin_panels,
        "absent_panels": absent,
        "unmeasurable_panels": unmeasurable,
        "panels": panels,
        "scope": scope,
    }


async def data_health(loop=None) -> dict:
    """Everything that fails silently, in one place.

    Async because the shadow's evidence lives in the database rather than on a
    mount. The two file-backed checks stay synchronous.

    `loop` is the live engine loop, needed by `order_path_health` so the ENTRY GATE can
    be asked rather than re-implemented. Optional, and its absence reports the order-path
    component as `unavailable` rather than dropping it — a check that silently disappears
    when its input is missing is the failure this whole module exists to prevent.
    """
    dominance = dominance_health()
    backups = backup_health()
    shadow = await shadow_health()
    panels = await panel_health()
    order_path = await order_path_health(loop)

    # A component we cannot see is NOT ok. Rolling "unavailable" into "ok" here
    # would defeat the entire module.
    components = {
        "dominance_collector": dominance,
        "backups": backups,
        "shadow": shadow,
        # T-0057/B199. BESIDE the shadow, never inside it. `shadow` answers "is the
        # contract engine still RECORDING", this answers "is the ORDER path still
        # TRADING", and on 2026-08-21 those two had opposite answers for 62-91 hours
        # while only the first was being watched.
        "order_path": order_path,
        # Separate from `shadow` on purpose. Liveness and staleness are orthogonal: the
        # shadow can be alive, writing on every permitted cycle, and grading frozen
        # panels — liveness green, grade garbage — and it can be correctly silent while
        # every panel is fresh. Merging them answers two questions with one output.
        "correlate_panels": panels,
    }
    problems = [
        name for name, c in components.items() if c.get("status") != "healthy"
    ]

    for name, c in components.items():
        if c.get("status") in ("down", "failing"):
            logger.warning("Data health problem", component=name, status=c["status"])

    return {
        "ok": not problems,
        "checked_at": datetime.now(tz=timezone.utc).isoformat(),
        "problems": problems,
        # NESTED, and it is not cosmetic. This used to end `**components`, so the top level
        # was `ok · checked_at · problems` PLUS the component keys — and a frontend deriving
        # its rows with `Object.entries` would render the first three AS COMPONENTS. Under
        # `components` the renderer can iterate everything it is given without a list of
        # names to keep in step, which is `B231`'s actual fix.
        "components": components,
        # KEPT AT THE TOP LEVEL FOR ONE RELEASE. Nesting alone would break any reader of
        # `health.shadow` the moment it deploys, and nothing here is deployed — so the
        # compatible order is: ship both, move the only reader, then drop these.
        **components,
    }


# ======================================================================================
# T-0057 / B199 — is the ORDER path still TRADING?
#
# BESIDE `shadow_health()`, never inside it. The two corpora have different
# legitimate-silence rules and one predicate cannot carry both — merging them is
# GATE-011's defect. `shadow_health` watches the SHADOW corpus, which T-0010 moved
# ABOVE the entry gates precisely so that `already in a position` would stop
# suppressing it. That was correct and it fixed B34. It also means the monitored
# artefact was engineered to be immune to the condition that stops the engine, and
# on 2026-08-21 the order path froze for 62-91 h with every signal green.
# ======================================================================================

#: The gate's own words for the state this signal exists to detect.
#:
#: **This is NOT a second statement of the gate.** `_entry_block_reason` is CALLED and
#: its answer is READ; this constant only names the answer being looked for. The two are
#: pinned together BEHAVIOURALLY by a test that drives a real loop into the state and
#: reads the string back — so a reworded gate turns a test red instead of silently making
#: this monitor unable to fire. A monitor keyed on a string nobody checks is B167's
#: vocabulary collision waiting to happen.
BLOCKED_BY_POSITION = "already in a position"

#: **[ENGINEERING] Calibrated against ONE observation, not invented — and no longer the term
#: carrying the separation.**
#:
#: `B216` measured that the first version of this signal put the label and the load in
#: different places: the doctrinal term was true of 5 of 5 blocks, so a constant advertised as
#: "arbitrary noise suppression" was silently doing all of the discriminating. It is not any
#: more. `remainder_outstanding` separates 2/2 structurally, and this floor's only remaining
#: job is to suppress a SHORT-LIVED legitimate remainder.
#:
#: There is exactly one observed: the ETH `2026-08-19 13:17:01` runner, outstanding about four
#: hours (14:55:19 to 18:50:11) before the engine stop closed it. So the number is answerable
#: to an observation rather than to taste.
#:
#: **Moving it CANNOT flip the control window**, which is the property that makes it safe: the
#: 2026-08-20 control contains no remainder at any floor value. A floor that could tune ARM 7
#: green would make ARM 7 unfalsifiable.
ORDER_PATH_BLOCKED_BARS_FLOOR = 3.0


#: How close a `trades.entry_time` must sit to a `decision_records.created_at` to be the
#: SAME entry. Measured, not guessed: the four entries of the current run match at 4-6 ms
#: (00:05:12.63111 vs 00:05:12.626072), and no unrelated trade lies within ten minutes of
#: any of them. One second is three orders of magnitude of slack over the observed skew.
ENTRY_TRADE_MATCH_SECONDS = 1.0


def entry_has_outstanding_remainder(sized_units, closed_lots) -> bool:
    """**The ONE site that decides whether an entry still has a remainder open.** (`ARM D`.)

    **This replaced a `tp is None` test, and the replacement is `B216`'s remedy.** The
    no-target term separated NOTHING: every position this engine has ever opened carries
    `tp = NULL`, so it was true of 5 of 5 blocks — three of which cleared on their own.

    The population is not homogeneous on the axis that matters:

        BTC 2026-08-20 03:20:12   closed 0.064343 of 0.064343   WHOLE     cleared (loss)
        BTC 2026-08-20 14:25:16   closed 0.103051 of 0.103051   WHOLE     cleared (loss)
        ETH 2026-08-19 19:20:31   closed 1.108751 of 1.583930   PARTIAL   still blocking
        BTC 2026-08-21 00:05:12   closed 0.056164 of 0.080234   PARTIAL   still blocking

    **2 of 2 both ways, structural, and no timer.** It is `EXIT-001`'s tranche model read
    directly: the 70% partial fires only on a WINNER reaching 2R, and what it leaves is a
    remainder whose stop is the original stop — now far below price — and whose target is
    `None`, so it can neither take profit nor realistically stop out. A LOSER closes WHOLE
    at its stop and frees the symbol. *That is why both entries that cleared are losses and
    both that block are wins.* The plan's sentence — "a position with no target can only
    stop out" — is true of a whole position and false of a winning remainder, which is the
    case it never considered.

    **SUM of closed lots, never "a partial row exists".** `ETH 2026-08-19 13:17:01` closed
    in TWO tranches, 2.298500 + 0.985072 = 3.283572, which is its `sized_units` exactly. A
    partial that is later completed is not a withdrawal, and an existence test would call
    it one.

    **AND `closed_lots > 0` IS PART OF THE DEFINITION, NOT A FILTER BOLTED ON.** A remainder
    only EXISTS if something was closed. Zero closes means either nothing ever traded
    (`B220`) or the whole position is still open and will stop out and clear — neither is a
    remainder, and both are ordinary. Over the full 33-entry corpus, measured:

        closed < sized          7 positives   <- includes 5 trade-less rows and open wholes
        0 < closed < sized      2 positives   <- EXACTLY the two blockers, with no scope term

    **PROVISIONAL PENDING `B218` — see `B227`.** This is a float comparison across three
    independent roundings that do not commute: the order carries `sized_units` at 8dp,
    `decision_records` stores it at 6dp, each settle lot is rounded to 8dp then written at
    6dp. **A fully SETTLED two-tranche trade can therefore read as a remainder**, in the
    direction that says the symbol is still blocked. It is NOT patched with an epsilon: a
    tolerance would have to exceed 1e-6 and would then be blind to a genuine remainder
    smaller than that, and choosing its size is `B93`'s tuned threshold. *The exact value
    already exists* — `paper.py:125` computes `remaining = round(pos.units - closed, 10)`
    and it dies in a log string. Once `B218` persists it, this becomes
    `remaining_units > 0` on the latest lot: one field, no arithmetic, no tolerance.

    *Why neither seat caught it first: the corpus holds 26 rows with `closed == sized` and
    25 are WHOLE closes — one lot, exact by construction. Exactly ONE completed two-tranche
    trade exists, and its arithmetic happens to land exact. The discriminator was validated
    against the only row that could have tested it.*
    """
    return 0 < closed_lots < sized_units


def outstanding_remainder_by_symbol(entries, trades, *, tolerance_seconds=None) -> dict:
    """Fold entries and their closed lots into `{symbol: bool | None}`. PURE.

    `entries` is `(symbol, opened_at, sized_units)`; `trades` is `(pair, entry_time,
    lot_size)`. Matching is by symbol and time because there is NO link column between
    `decision_records` and `trades` — stated here rather than implied, since a join keyed
    on a coincidence is a thing a reader must be told about.

    `None` for a symbol with no entries at all: nothing to judge. **NOT `False`** — absence
    of an entry is not evidence of no remainder, and treating it as such is `B161`'s class.

    **A KNOWN LIMIT, measured (`B220`).** An entry with ZERO matching trade rows folds to
    "the whole position is outstanding", because `closed_lots` is 0. Five such entries exist
    in history — 2026-07-27 through 2026-08-09 — and they are genuinely trade-less rather
    than join failures: no `trades` row lies within TEN MINUTES of any of them, and one of
    them is the ETH position the 2026-08-08 container recreate destroyed. Scoping every
    query to the ACTIVE RUN keeps them out; across runs they would read as a permanent
    remainder that no close can ever clear.
    """
    tol = ENTRY_TRADE_MATCH_SECONDS if tolerance_seconds is None else tolerance_seconds
    out: dict = {}
    for symbol, opened_at, sized_units in entries:
        closed = sum(
            float(lot)
            for pair, entry_time, lot in trades
            if pair == symbol and abs((entry_time - opened_at).total_seconds()) <= tol
        )
        outstanding = entry_has_outstanding_remainder(float(sized_units), closed)
        out[symbol] = out.get(symbol) or outstanding
    return out


def order_path_symbol_state(
    *,
    symbol: str,
    last_decision_at: datetime | None,
    now: datetime,
    bar_seconds: float,
    blocked_reason: str | None,
    remainder_outstanding: bool | None,
    since: datetime | None = None,
) -> dict:
    """The predicate, PURE — values in, values out, no database and no clock of its own.

    Pure so that the CONTROL PAIR is possible at all: the same predicate has to be
    runnable over a historical window in which the engine WAS trading normally, and a
    function that reads `now()` and the live broker cannot be. *"It fires on production
    right now" cannot distinguish a working detector from one that always fires.*

    **The discriminator is structural, not a timer.** An engine legitimately holding a
    position must not scream, and it holds one most of the time — so a staleness clock
    either screams all day or is set so loose it misses the incident. This fires only on

        blocked by `already in a position`  AND  a TRANCHE REMAINDER is still outstanding

    A whole position closes at its stop and frees the symbol; a 70% partial leaves a runner
    that can neither take profit nor realistically stop out. That is `EXIT-001`'s tranche
    model READ here, never restated — no rule is implemented in this function. **It is NOT
    keyed on the absence of a target: `B216` measured that every position this engine ever
    opened has `tp = NULL`, so that term was true of 5 of 5 blocks and separated nothing.**

    `remainder_outstanding` is TRI-STATE and the distinction is load-bearing: `True` a
    tranche remainder is still open, `False` every lot closed, `None` there was no entry to
    judge. Only an explicit `True` fires. *Absence of a value is never treated as the
    property* — that is the `B161` class, and it has already cost this project six
    instances.
    """
    age_seconds = (
        (now - last_decision_at).total_seconds()
        if last_decision_at is not None
        else (now - since).total_seconds() if since is not None else None
    )
    bars_blocked = age_seconds / bar_seconds if age_seconds is not None else None

    withdrawn = (
        blocked_reason == BLOCKED_BY_POSITION
        and remainder_outstanding is True
        and bars_blocked is not None
        and bars_blocked > ORDER_PATH_BLOCKED_BARS_FLOOR
    )

    return {
        "symbol": symbol,
        # THE VALUES, not a colour. A signal that returns only a verdict cannot be
        # argued with, and every one of these was needed by hand to find B198.
        "last_decision_at": last_decision_at.isoformat() if last_decision_at else None,
        "age_seconds": round(age_seconds, 1) if age_seconds is not None else None,
        "age_hours": round(age_seconds / 3600.0, 2) if age_seconds is not None else None,
        "bars_blocked": round(bars_blocked, 1) if bars_blocked is not None else None,
        "blocked_reason": blocked_reason,
        "remainder_outstanding": remainder_outstanding,
        "withdrawn_from_trading": withdrawn,
        # Why it did NOT fire, when it did not. A monitor that reports only its positives
        # is unfalsifiable from outside — B199 was found by hand precisely because the
        # green signals said nothing about what they had ruled out.
        "verdict_reason": (
            "blocked by an entry whose tranche remainder is still outstanding"
            if withdrawn
            else f"not blocked by a position (blocked_reason={blocked_reason!r})"
            if blocked_reason != BLOCKED_BY_POSITION
            else "every lot of the blocking entry is closed; nothing is outstanding"
            if remainder_outstanding is False
            else "no entry found to measure a remainder against"
            if remainder_outstanding is None
            else f"inside the {ORDER_PATH_BLOCKED_BARS_FLOOR}-bar floor "
            f"(bars_blocked={bars_blocked})"
        ),
    }


def _order_path_summary(c: dict) -> str:
    """`B234`/`B229`: `idle` and `withdrawn` MUST be distinguishable without opening the
    component. They are the two states the `ok` question is actually about, and the panel
    rendered them the same colour — so the sentence has to carry the difference."""
    if (fb := _fallback_summary(c)) is not None:
        return fb
    withdrawn = c.get("withdrawn_symbols") or []
    running = c.get("engine_running")
    if withdrawn:
        ages = {
            s["symbol"]: s.get("age_hours")
            for s in (c.get("symbols") or [])
            if s.get("withdrawn_from_trading")
        }
        detail = ", ".join(
            f"{sym} {age:.0f}h" if age is not None else sym for sym, age in ages.items()
        )
        return (
            f"WITHDRAWN FROM TRADING: {detail}"
            + ("" if running else " · and the engine is STOPPED")
        )
    if not running:
        return "the engine is not running — nothing is due, and nothing is withdrawn"
    return f"{len(c.get('symbols') or [])} symbol(s) still reaching decisions"


@with_summary(_order_path_summary)
async def order_path_health(loop=None) -> dict:
    """Is the ORDER path still TRADING? Not: is the engine RUNNING. Not: is the shadow RECORDING.

    WHY THIS EXISTS (`B199`)
    On 2026-08-21 the order path stopped and stayed stopped for 62-91 hours while
    `/api/engine/status` said `running: true`, equity rose, telemetry was 12 seconds old,
    `shadow_health()` was green and the activity buffer showed forty ordinary skips. The
    shadow corpus wrote 1,512 records in the window the decision corpus wrote 0. It was
    found by querying `max(created_at)` on `decision_records` PER SYMBOL by hand.

    THIS IS A FIFTH PREDICATE AND IT MUST STAY SEPARABLE FROM THE OTHER FOUR.
    `wired` / `executes` / `RETAINED` / `RUNNING` were each insufficient alone; this adds
    `TRADING`. An engine that is not running at all is `B178`'s signal and reports here as
    `idle` with `watching: False` — never as a problem, and never as healthy either.

    THE LOOP IS A PARAMETER, NOT A REACH-IN. Without it the gate cannot be ASKED, and this
    function refuses to guess: it reports `unavailable`, which is this module's rule —
    a component we cannot see is not `ok`.
    """
    from sqlalchemy import func, select

    from app.db.session import async_session_maker
    from app.models.decision_record import DecisionRecord
    from app.models.engine_run import EngineRun
    from app.models.trade import Trade
    from app.services.live.fixed_config import ENTRY_TF, SYMBOLS
    from app.services.market_data.sources.dominance import _TF_SECONDS

    scope = {
        # Same discipline as `shadow_health`'s CRITERION 9. This attests that the order
        # path is still REACHING decisions, and nothing whatever about their quality.
        "attests": "order_path_is_still_deciding",
        "does_not_attest": [
            "correctness of any entry decision",
            "whether the engine process is alive (that is /engine/status, B178)",
            "whether the shadow is recording (that is shadow_health, B32)",
            "whether an open position is profitable",
        ],
    }

    bar_seconds = _TF_SECONDS.get(ENTRY_TF)
    if bar_seconds is None:
        return {"status": "unavailable", "watching": False,
                "reason": f"ENTRY_TF {ENTRY_TF!r} has no known duration", **scope}

    if loop is None:
        # Cannot see is never "fine". Without the loop the GATE cannot be asked, and
        # inferring the block reason from positions would be a SECOND statement of
        # `_entry_block_reason` — GATE-011's defect, and the thing this task must not do.
        return {"status": "unavailable", "watching": False,
                "reason": "no live loop supplied; the entry gate cannot be asked", **scope}

    try:
        async with async_session_maker() as db:
            active = (
                await db.execute(
                    select(EngineRun)
                    .where(EngineRun.ended_at.is_(None))
                    .order_by(EngineRun.started_at.desc())
                    .limit(1)
                )
            ).scalars().first()

            # ARM E — SEPARABILITY FROM B178. The engine being stopped does NOT suppress the
            # per-symbol verdict, and this is deliberate: a signal that cannot fire while the
            # engine is stopped is not the fifth predicate TRADING, it is a sub-condition of
            # RUNNING. `stopped AND still blocked by a target-less runner` is a real and
            # reportable state, and the two facts are labelled separately below so a reader
            # is never asked to infer one from the other.
            if active is None:
                active = (
                    await db.execute(
                        select(EngineRun).order_by(EngineRun.started_at.desc()).limit(1)
                    )
                ).scalars().first()
                engine_running = False
            else:
                engine_running = True

            started = _as_utc(active.started_at) if active is not None else None
            symbols = list(getattr(loop, "symbols", None) or SYMBOLS)

            # The entries of THIS RUN and the lots closed against them.
            #
            # THE RUN SCOPE IS A SECOND, INDEPENDENT GUARD AND IT COVERS A DIFFERENT
            # FAILURE FROM THE `> 0` TERM. `0 < closed < sized` already excludes the five
            # trade-less rows (`B220`) and every fully-open position, with no scope at all.
            # What it does NOT exclude is a partial remainder STRANDED BY A KILLED RUN: it
            # would satisfy the term forever and fire on a symbol the current engine has
            # never touched. Not present in the corpus, structurally possible, cheap.
            # Keyed on `run_id` rather than a timestamp — a timestamp window is a second
            # way to say "this run" and the two can disagree.
            entries = [
                (r.symbol, _as_utc(r.created_at), r.sized_units)
                for r in (
                    await db.execute(
                        select(DecisionRecord).where(
                            DecisionRecord.sized_units.is_not(None),
                            *([DecisionRecord.run_id == active.id] if active else []),
                        )
                    )
                ).scalars().all()
            ]
            trade_rows = [
                (t.pair, _as_utc(t.entry_time), t.lot_size)
                for t in (
                    await db.execute(
                        select(Trade).where(
                            *([Trade.run_id == active.id] if active else []),
                        )
                    )
                ).scalars().all()
            ]

            last_by_symbol = {}
            for symbol in symbols:
                last = (
                    await db.execute(
                        select(func.max(DecisionRecord.created_at)).where(
                            DecisionRecord.symbol == symbol,
                            *( [DecisionRecord.created_at >= started] if started else [] ),
                        )
                    )
                ).scalar()
                last_by_symbol[symbol] = _as_utc(last) if last is not None else None

        remainders = outstanding_remainder_by_symbol(entries, trade_rows)
        # The gate is ASKED, once per symbol, and its answer is used verbatim. Reproducing
        # its four conditions here would put a second copy of the entry doctrine in a
        # monitoring module, and the copy would be the one that drifts.
        blocked = {s: await loop._entry_block_reason(s) for s in symbols}
    except Exception as exc:  # noqa: BLE001
        return {"status": "unavailable", "watching": False, "reason": str(exc), **scope}

    now = datetime.now(tz=timezone.utc)
    by_symbol = []
    for symbol in symbols:
        by_symbol.append(
            order_path_symbol_state(
                symbol=symbol,
                last_decision_at=last_by_symbol[symbol],
                now=now,
                bar_seconds=bar_seconds,
                blocked_reason=blocked[symbol],
                # READ from the stored position, never re-derived. A second site computing
                # "does this position have a target" would be a second doctrine.
                remainder_outstanding=remainders.get(symbol),
                since=started,
            )
        )

    withdrawn = [s["symbol"] for s in by_symbol if s["withdrawn_from_trading"]]
    if withdrawn:
        logger.warning("Order path withdrawn from trading", symbols=withdrawn)

    return {
        # Not "down": the engine is up and the shadow is fine. The order path specifically
        # has been withdrawn, and naming it anything vaguer sends the reader to the wrong
        # component — which is exactly how 91 hours passed.
        "status": "withdrawn" if withdrawn else "healthy" if engine_running else "idle",
        "watching": True,
        # TWO FACTS, LABELLED SEPARATELY. `engine_running` is B178's question and
        # `withdrawn_symbols` is this one; a reader must never have to infer either from
        # the other, and a stopped engine can still be withdrawn.
        "engine_running": engine_running,
        "withdrawn_symbols": withdrawn,
        "entry_tf": ENTRY_TF,
        "bar_seconds": bar_seconds,
        "blocked_bars_floor": ORDER_PATH_BLOCKED_BARS_FLOOR,
        "floor_provenance": "ENGINEERING, arbitrary noise suppression — not a ratified threshold",
        "run_started_at": started.isoformat() if started else None,
        "symbols": by_symbol,
        **scope,
    }
