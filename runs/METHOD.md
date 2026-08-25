# How this export was produced, and what it does not contain

**Exported 2026-08-25T18:12:36Z** from the production database on the VPS.

## What was done

One read-only extract, then a local script that wrote these files. No database write, no engine
interaction, nothing on the running system was changed.

```
select * from engine_runs                                    ->  24 rows
select * from decision_records                               ->  1342 rows
select * from trades                                         ->  283 rows
select run_id, record_type, count(*), min(created_at), max(created_at)
  from telemetry_records group by run_id, record_type        ->  per-run counts only
```

**The extract script is not committed, because it embeds a database connection.** Everything it read
is above; the transformation is described below and its output is in this folder.

## What is READ and what is DERIVED

**Read directly from columns, unmodified:** every field in the per-run tables and in
`data/*.jsonl` and `data/trades.csv`. Decimals are carried as strings so no precision is lost to
float conversion — this matters, and `B278` is why: that finding lived in the fourth decimal place.

**Derived by this export, and each is reproducible from the data beside it:**

* **Duration** — `ended_at - started_at`.
* **Positions** — trade rows grouped by `broker_id`. **Not a stored count.** See `B225`, and the
  Run 01 warning in [README.md](README.md): before that fix `broker_id` was a literal, so grouping
  collapses every pre-fix row into one.
* **Entry-rule comparison totals** — **parsed with a regular expression from the text of
  `decision_records.reasons`.** The structured values were never persisted (`B274`): only the
  rendered `detail` string reaches the database, so text is the only available source. Each run
  document states how many rows the parse matched against how many rows exist — **if those two
  numbers differ, the parse missed rows and the totals are incomplete.** At export they were equal
  on every run.
* **Gate verdict counts** — parsed the same way, from the leading `VERDICT gate_name:` of each
  reason line.
* **Realised P&L** — sum of `pnl_dollars`.

## What is NOT here

* **Telemetry payloads.** 5406 records exist; only per-run counts by `record_type` are exported.
  The payload JSON is bulk and no register claim rests on it.
* **Candles.** 8937 rows of market data, not a record of engine behaviour.
* **The dominance files** captured alongside the nightly backup.
* **Anything from before run tracking existed, as its own record.** It is all inside Run 01, mixed
  with backtest replays. This export cannot separate what happened when inside it, because the rows
  do not carry that distinction — only `setup_tag` hints at it.
* **Account equity at decision time.** No such column exists (`B279`), and
  `prop_firm_snapshots` — which has one — has **zero rows**. It is being added by `T-0084`;
  rows written after that lands will carry it, and none of these do.

## Bounds

* **Point-in-time, not live.** Run 24 had not ended when this was taken; its figures are in flight.
  Everything else is closed.
* **One venue.** Every run is the in-process paper broker in `PROP_FIRM_SIM` mode. Nothing here
  describes behaviour against a real broker.
* **Two symbols.** BTC/USD and ETH/USD throughout.
* **The engine keeps running.** Figures grew between two extracts taken minutes apart during this
  work, which is why the export is timestamped rather than described as current.

## Reproducing it

Every figure in a run document can be recomputed from `data/decisions-<run>.jsonl` and
`data/trades.csv` with no database access. **That is the point of the export** — the register cites
run figures, and until now a reader could see the conclusion and not the evidence.
