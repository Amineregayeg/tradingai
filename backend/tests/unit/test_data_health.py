"""Health of the systems that fail silently (KNOWN_ISSUES B1).

THE PROPERTY WORTH MOST HERE IS THAT "I CANNOT SEE IT" NEVER READS AS "IT IS
FINE". Silence and health look identical from outside a monitoring surface, and
conflating them is how a dashboard ends up reassuring people about a system it
stopped watching weeks ago. Several tests below exist only to pin that.

The stakes are asymmetric for the collector specifically: its data cannot be
backfilled. Every minute it is down is lost permanently, which is not true of
anything else in this system.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.services.monitoring import data_health as dh

HEADER = "ts_utc,TOTAL,TOTAL2,TOTAL3,BTC_D,ETH_D,USDT_D,coverage_pct,supplies_age_h"


def write_samples(tmp_path, minutes_ago_list, coverage="94.50"):
    """Write a collector CSV whose newest sample is `min(minutes_ago_list)` old."""
    now = datetime.now(timezone.utc)
    lines = [HEADER]
    for m in sorted(minutes_ago_list, reverse=True):
        ts = (now - timedelta(minutes=m)).replace(microsecond=0).isoformat()
        lines.append(f"{ts},2e12,9e11,7e11,56.5,10.1,8.0,{coverage},1.00")
    p = tmp_path / "dominance_intraday_raw.csv"
    p.write_text("\n".join(lines) + "\n")
    return p


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    dom = tmp_path / "dominance"
    bak = tmp_path / "backups"
    dom.mkdir(); bak.mkdir()
    monkeypatch.setattr(dh, "DOMINANCE_DIR", dom)
    monkeypatch.setattr(dh, "BACKUP_DIR", bak)
    return dom, bak


# ---------------------------------------------------------------------------
# Unreadable must never read as healthy
# ---------------------------------------------------------------------------
def test_missing_collector_file_is_unavailable_not_healthy(dirs):
    r = dh.dominance_health()
    assert r["status"] == "unavailable"
    assert r["watching"] is False, "a check that cannot see its data claimed to be watching"


def test_missing_backup_status_is_unavailable_not_healthy(dirs):
    r = dh.backup_health()
    assert r["status"] == "unavailable"
    assert r["watching"] is False


def test_unavailable_components_make_the_overall_result_not_ok(dirs):
    """Rolling 'cannot see it' into 'ok' would defeat the entire module."""
    r = dh.data_health()
    assert r["ok"] is False
    assert set(r["problems"]) == {"dominance_collector", "backups"}


def test_a_corrupt_collector_file_is_unavailable(dirs):
    dom, _ = dirs
    (dom / "dominance_intraday_raw.csv").write_text("not a csv at all\n\x00\x01")
    assert dh.dominance_health()["status"] == "unavailable"


# ---------------------------------------------------------------------------
# Collector freshness
# ---------------------------------------------------------------------------
def test_fresh_samples_are_healthy(dirs):
    dom, _ = dirs
    write_samples(dom, list(range(0, 60)))
    r = dh.dominance_health()
    assert r["status"] == "healthy"
    assert r["watching"] is True
    assert r["age_minutes"] < dh.COLLECTOR_STALE_MIN
    assert "warning" not in r


def test_a_short_gap_is_stale(dirs):
    dom, _ = dirs
    write_samples(dom, [m + 10 for m in range(0, 50)])   # newest is 10 min old
    r = dh.dominance_health()
    assert r["status"] == "stale"
    assert "cannot be backfilled" in r["warning"], (
        "the warning must say why this is urgent, not just that it happened"
    )


def test_a_long_gap_is_down(dirs):
    dom, _ = dirs
    write_samples(dom, [m + 120 for m in range(0, 30)])  # newest is 2h old
    assert dh.dominance_health()["status"] == "down"


def test_density_is_measured_over_the_recent_window_not_lifetime(dirs):
    """A collector that died an hour ago still shows excellent LIFETIME density.

    That is exactly the reassuring-but-wrong number to put on a dashboard, so
    density is computed over the last hour only.
    """
    dom, _ = dirs
    # 500 perfect samples, but all of them older than an hour.
    write_samples(dom, [m + 70 for m in range(0, 500)])
    r = dh.dominance_health()
    assert r["recent_density_pct"] == 0.0, "lifetime density masked a dead collector"
    assert r["status"] == "down"


def test_partial_recent_coverage_is_reported(dirs):
    dom, _ = dirs
    write_samples(dom, list(range(0, 60, 2)))   # every other minute
    r = dh.dominance_health()
    assert 45 <= r["recent_density_pct"] <= 55


def test_collector_quality_fields_are_surfaced(dirs):
    dom, _ = dirs
    write_samples(dom, [0, 1, 2], coverage="88.25")
    r = dh.dominance_health()
    assert r["live_priced_pct"] == 88.25
    assert r["supplies_age_h"] == 1.0


# ---------------------------------------------------------------------------
# Backups
# ---------------------------------------------------------------------------
def _status(bak, ok=True, hours_ago=1.0, message="verified", count=3):
    ts = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).replace(microsecond=0)
    (bak / "status.json").write_text(json.dumps({
        "ok": ok, "last_run": ts.isoformat().replace("+00:00", "Z"),
        "message": message, "backup_count": count, "retention_days": 30,
    }))


def test_recent_verified_backup_is_healthy(dirs):
    _, bak = dirs
    _status(bak, ok=True, hours_ago=2)
    r = dh.backup_health()
    assert r["status"] == "healthy"
    assert r["backup_count"] == 3


def test_a_failed_backup_is_reported_as_failing(dirs):
    _, bak = dirs
    _status(bak, ok=False, message="restore verification failed")
    r = dh.backup_health()
    assert r["status"] == "failing"
    assert "restore verification failed" in r["warning"]


def test_an_old_ok_backup_is_stale(dirs):
    """A status file saying 'ok' from three weeks ago is worse than none."""
    _, bak = dirs
    _status(bak, ok=True, hours_ago=72)
    r = dh.backup_health()
    assert r["status"] == "stale"
    assert "72 hours" in r["warning"]


def test_backup_staleness_threshold_matches_the_backup_script(dirs):
    """The script's own --status uses 48h. If these disagree, the dashboard and
    the script would give different answers about the same backups."""
    assert dh.BACKUP_STALE_HOURS == 48.0


# ---------------------------------------------------------------------------
# Combined
# ---------------------------------------------------------------------------
def test_everything_healthy_reports_ok(dirs):
    dom, bak = dirs
    write_samples(dom, list(range(0, 60)))
    _status(bak)
    r = dh.data_health()
    assert r["ok"] is True
    assert r["problems"] == []


def test_one_sick_component_makes_the_whole_thing_not_ok(dirs):
    dom, bak = dirs
    write_samples(dom, list(range(0, 60)))      # collector fine
    _status(bak, ok=False)                       # backups failing
    r = dh.data_health()
    assert r["ok"] is False
    assert r["problems"] == ["backups"]
