"""Write and read engine-contract telemetry (M1).

This is the only door into `telemetry_records`, and it is narrow on purpose.

**Validation happens here, not at the caller.** If any code path could store a record
without checking it, the store would eventually contain records that do not satisfy the
contract — and every conformance number computed afterwards would be a measurement of a
population that does not match the schema, discovered weeks later as an unexplainable gap.
Making the writer the only entrance means "stored" and "valid" cannot come apart.

**Nothing here updates or deletes.** The conformance suite is a pure function of stored
records, and a record that can be rewritten is not evidence. `sequence_no` is strictly
increasing per (engine build, instrument, timeframe) so suppression shows up as a gap and
rewriting as a repeat.
"""
from __future__ import annotations

import json
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.telemetry_record import TelemetryRecord
from app.services.telemetry import validate as val

#: The contract's own id field, per record type.
_ID_FIELD = {
    "setup_evaluation": "evaluation_id",
    "trade_execution": "trade_id",
    "scan_census": "scan_id",
}


def _extract(record: dict[str, Any]) -> dict[str, Any]:
    """Pull the query columns out of a record.

    Every one of these is a DUPLICATE of something inside `payload`, which stays
    authoritative. They exist so the common questions — what did we decide on this
    instrument, which rule decided it — do not require scanning JSON.
    """
    rt = str(record.get("record_type", ""))
    engine = record.get("engine") or {}
    instrument = record.get("instrument") or {}
    scan = record.get("scan_context") or {}
    timeframes = record.get("timeframes") or {}

    return {
        "record_type": rt,
        "record_id": str(record.get(_ID_FIELD.get(rt, ""), "")),
        "instrument": instrument.get("symbol"),
        "signal_tf": timeframes.get("signal_tf") or record.get("signal_tf"),
        "timestamp_ny": record.get("timestamp_ny") or record.get("window_from_ny"),
        "sequence_no": scan.get("sequence_no"),
        "decision": record.get("decision"),
        "deciding_rule_id": record.get("deciding_rule_id"),
        "engine_version": engine.get("engine_version"),
        "rule_registry_version": engine.get("rule_registry_version"),
    }


async def store(
    db: AsyncSession,
    record: dict[str, Any],
    *,
    run_id: Any | None = None,
) -> TelemetryRecord:
    """Validate, then persist. Raises `TelemetryInvalid` and stores nothing if invalid."""
    val.assert_valid(record)

    cols = _extract(record)
    if not cols["record_id"]:
        raise val.TelemetryInvalid(
            f"{cols['record_type']} record carries no id — "
            "a record that cannot be referenced cannot be joined to, and the conformance "
            "suite joins trades to the evaluation that produced them."
        )

    row = TelemetryRecord(run_id=run_id, payload=record, **cols)
    db.add(row)
    await db.flush()
    return row


async def store_many(
    db: AsyncSession,
    records: Iterable[dict[str, Any]],
    *,
    run_id: Any | None = None,
) -> list[TelemetryRecord]:
    """All-or-nothing: every record is validated before any is added.

    A partial write would leave the census disagreeing with the evaluations it counts,
    which is precisely the population problem the census exists to detect.
    """
    batch = list(records)
    for r in batch:
        val.assert_valid(r)
    return [await store(db, r, run_id=run_id) for r in batch]


async def export_jsonl(
    db: AsyncSession,
    *,
    record_type: str | None = None,
    run_id: Any | None = None,
    limit: int | None = None,
) -> str:
    """Stored records as JSONL — the format the knowledge team's harness expects.

    We store in Postgres because that is where evidence already lives here, with verified
    backups. Their suite assumes append-only JSONL. Exporting rather than changing our sink
    keeps both true: the suite is a pure function of the records either way.

    Ordered by `created_at, id` so an export is reproducible and two exports of the same
    window are diffable.
    """
    stmt = select(TelemetryRecord).order_by(TelemetryRecord.created_at, TelemetryRecord.id)
    if record_type:
        stmt = stmt.where(TelemetryRecord.record_type == record_type)
    if run_id is not None:
        stmt = stmt.where(TelemetryRecord.run_id == run_id)
    if limit:
        stmt = stmt.limit(limit)

    rows = (await db.execute(stmt)).scalars().all()
    # separators: no spaces, so a line is byte-stable across exports.
    return "\n".join(json.dumps(r.payload, separators=(",", ":"), sort_keys=True) for r in rows)


async def count_by_type(db: AsyncSession, *, run_id: Any | None = None) -> dict[str, int]:
    """How many of each record type are stored.

    The first thing to look at when a fidelity number seems wrong: a corpus with no
    rejections cannot be scored at all, and a census that does not reconcile against the
    evaluations it counts means the population is not what it claims.
    """
    stmt = select(TelemetryRecord.record_type)
    if run_id is not None:
        stmt = stmt.where(TelemetryRecord.run_id == run_id)
    out: dict[str, int] = {}
    for (rt,) in (await db.execute(stmt)).all():
        out[rt] = out.get(rt, 0) + 1
    return out
