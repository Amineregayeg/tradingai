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


async def data_health() -> dict:
    """Everything that fails silently, in one place.

    Async because the shadow's evidence lives in the database rather than on a
    mount. The two file-backed checks stay synchronous.
    """
    dominance = dominance_health()
    backups = backup_health()
    shadow = await shadow_health()

    # A component we cannot see is NOT ok. Rolling "unavailable" into "ok" here
    # would defeat the entire module.
    components = {
        "dominance_collector": dominance,
        "backups": backups,
        "shadow": shadow,
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
        **components,
    }
