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
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

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


@pytest.fixture
def shadow_ok(monkeypatch):
    """Pin the shadow component healthy.

    The composition tests below are about whether an unavailable component
    poisons `ok` — not about the shadow, which reads the database and would
    report `unavailable` here for reasons that have nothing to do with what
    they assert. Its own behaviour is covered in `test_shadow_health.py`.
    """
    async def _healthy():
        return {"status": "healthy", "watching": True}

    monkeypatch.setattr(dh, "shadow_health", _healthy)


@pytest.fixture
def panels_ok(monkeypatch):
    """Pin the correlate-panel component healthy.

    Same reasoning as `shadow_ok`: `panel_health` reaches two live market-data hosts and
    would report `down` here for reasons that have nothing to do with what the
    composition tests assert. Its own behaviour is covered in `test_panel_health.py`.
    """
    async def _healthy():
        return {"status": "healthy", "watching": True}

    monkeypatch.setattr(dh, "panel_health", _healthy)


@pytest.mark.asyncio
async def test_unavailable_components_make_the_overall_result_not_ok(
    dirs, shadow_ok, panels_ok
):
    """Rolling 'cannot see it' into 'ok' would defeat the entire module."""
    r = await dh.data_health()
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


def test_partial_recent_coverage_is_reported(dirs, monkeypatch):
    """Half the expected samples reads as half.

    The declared cadence is pinned to 60s here rather than left at the default,
    because this test is about density reporting a SHORTFALL — not about what the
    collector happens to be configured for this month. Written when 60s was the
    only cadence and the denominator was hardcoded; making the assumption explicit
    is what lets the constant move without silently changing what this asserts.
    """
    monkeypatch.setattr(dh, "EXPECTED_POLL_SECONDS", 60.0)
    dom, _ = dirs
    write_samples(dom, list(range(0, 60, 2)))   # every other minute
    r = dh.dominance_health()
    assert 45 <= r["recent_density_pct"] <= 55


# ---------------------------------------------------------------------------
# Density measures against the CONFIGURED cadence (T-0001, criterion 11)
#
# The collector moved to --loop 10 on 2026-08-10. The denominator here was the
# literal 60 that had been correct for as long as the collector sampled once a
# minute, and these pin what goes wrong when it is left behind.


def test_density_is_measured_against_the_configured_cadence(dirs, monkeypatch):
    """THE MUTATION TARGET. A 10s-cadence hour holding 60 samples is not healthy.

    360 samples are expected; 60 arrived. That is a collector delivering one sixth
    of its data — the exact partial degradation this figure exists to catch.

    Restore `100.0 * recent / 60.0` and this reads 100.0: the old denominator says
    60 samples is a full hour, so a six-fold shortfall renders as perfect health,
    on the one dataset in this system that cannot be backfilled.
    """
    monkeypatch.setattr(dh, "EXPECTED_POLL_SECONDS", 10.0)
    dom, _ = dirs
    write_samples(dom, list(range(0, 60)))  # one a minute, for an hour

    r = dh.dominance_health()

    assert r["recent_density_pct"] == pytest.approx(16.7, abs=1.0)
    assert r["recent_density_pct"] < 100.0, "a 6x shortfall must not read as healthy"
    assert r["expected_poll_seconds"] == 10.0


def test_a_collector_keeping_up_reads_as_full_density(dirs, monkeypatch):
    """The other half of the mutation: the fix must not simply depress every number.

    360 samples in the hour at a declared 10s cadence is exactly what was asked
    for, and it has to read as 100% or the panel cries wolf permanently.
    """
    monkeypatch.setattr(dh, "EXPECTED_POLL_SECONDS", 10.0)
    dom, _ = dirs
    now = datetime.now(timezone.utc)
    lines = [HEADER]
    for i in range(359, -1, -1):  # 360 samples, 10s apart, newest ~0s old
        ts = (now - timedelta(seconds=i * 10)).replace(microsecond=0).isoformat()
        lines.append(f"{ts},2e12,9e11,7e11,56.5,10.1,8.0,94.50,1.00")
    (dom / "dominance_intraday_raw.csv").write_text("\n".join(lines) + "\n")

    r = dh.dominance_health()

    assert r["recent_density_pct"] == pytest.approx(100.0, abs=1.0)
    assert r["status"] == "healthy"


def test_the_expected_cadence_matches_the_deployed_compose_file():
    """The api's declared cadence and the collector's actual one cannot drift apart.

    `EXPECTED_POLL_SECONDS` is the SECOND declaration of the collector's poll rate;
    `deploy/compose.dominance.yaml`'s `--loop` is the first and it is the one that
    actually configures the container. Holding two copies of a number in step with a
    comment is precisely the habit that produced T-0001: `--loop 15` sat committed
    and undeployed for six days while `KNOWN_ISSUES` recorded it as done.

    `check_deploy_drift.py` cannot cover this. It compares a committed compose file
    against the server, and both sides of THIS disagreement are in the repo.

    This covers the whole space only because `EXPECTED_POLL_SECONDS` is a plain
    constant. An env override would be a third declaration this test cannot see, and
    it would go green through the one arrangement nothing else catches either — the
    variable set in both compose files with matching values while disagreeing with
    `--loop`. So: no knob, and this assertion means what it appears to mean.
    """
    compose = (
        Path(__file__).resolve().parents[3] / "deploy" / "compose.dominance.yaml"
    ).read_text()

    found = re.findall(r"collect_dominance\.py --loop (\d+)", compose)
    assert found, "no '--loop N' in deploy/compose.dominance.yaml — has it been restructured?"
    assert len(set(found)) == 1, f"the compose file declares more than one cadence: {found}"

    assert dh.EXPECTED_POLL_SECONDS == float(found[0]), (
        f"deploy/compose.dominance.yaml deploys the collector at --loop {found[0]}, but "
        f"data_health.EXPECTED_POLL_SECONDS is {dh.EXPECTED_POLL_SECONDS}. The density "
        "figure would then be measured against a cadence the collector is not running, "
        "which is the defect this constant exists to prevent."
    )


def test_the_denominator_is_declared_rather_than_read_from_the_data(dirs, monkeypatch):
    """Inferring the cadence from the samples would make degradation invisible.

    It is the obvious-looking fix and it is the wrong one: a yardstick derived from
    the thing being measured always reports 100%. This pins that the SAME data reads
    differently against different declared expectations — which is only possible if
    the expectation comes from configuration.
    """
    dom, _ = dirs
    write_samples(dom, list(range(0, 60)))  # one a minute for an hour, unchanged

    monkeypatch.setattr(dh, "EXPECTED_POLL_SECONDS", 60.0)
    at_60 = dh.dominance_health()["recent_density_pct"]
    monkeypatch.setattr(dh, "EXPECTED_POLL_SECONDS", 10.0)
    at_10 = dh.dominance_health()["recent_density_pct"]

    assert at_60 == pytest.approx(100.0, abs=1.0)
    assert at_10 == pytest.approx(16.7, abs=1.0)


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
@pytest.mark.asyncio
async def test_everything_healthy_reports_ok(dirs, shadow_ok, panels_ok):
    dom, bak = dirs
    write_samples(dom, list(range(0, 60)))
    _status(bak)
    r = await dh.data_health()
    assert r["ok"] is True
    assert r["problems"] == []


@pytest.mark.asyncio
async def test_one_sick_component_makes_the_whole_thing_not_ok(dirs, shadow_ok, panels_ok):
    dom, bak = dirs
    write_samples(dom, list(range(0, 60)))      # collector fine
    _status(bak, ok=False)                       # backups failing
    r = await dh.data_health()
    assert r["ok"] is False
    assert r["problems"] == ["backups"]
