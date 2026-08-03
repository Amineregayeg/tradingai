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

#: The collector samples once a minute. A gap beyond this is not jitter.
COLLECTOR_STALE_MIN = 5.0
COLLECTOR_DOWN_MIN = 30.0

#: Matches the backup script's own staleness rule, so the two cannot disagree
#: about whether backups are healthy.
BACKUP_STALE_HOURS = 48.0

#: Only the tail of the CSV is read. At one sample a minute a year is ~525k rows
#: (~50 MB); parsing that on every dashboard poll would be pointless work for a
#: freshness check that only needs the recent past.
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
    recent_density = min(100.0, 100.0 * recent / 60.0)

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


def data_health() -> dict:
    """Everything that fails silently, in one place."""
    dominance = dominance_health()
    backups = backup_health()

    # A component we cannot see is NOT ok. Rolling "unavailable" into "ok" here
    # would defeat the entire module.
    components = {"dominance_collector": dominance, "backups": backups}
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
