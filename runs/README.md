# Engine runs — full record

**Every simulated run the engine has performed, exported from the production database.** One
document per run, plus the underlying rows in machine-readable form.

**Exported 2026-08-25T18:11:09Z.** This is a point-in-time export, not a live view — see [METHOD.md](METHOD.md)
for how it was produced and what it does not contain.

## Why this exists

The register (`KNOWN_ISSUES.md`) cites figures from specific runs — `B268` quotes two runs by id,
`B277` and `B278` quote individual trades to six decimal places, `B215`'s closure quotes a live
position payload. **Until this export, none of that was reproducible without database access.**
These documents are what those claims rest on.

## Totals at export

| | |
|---|---|
| runs | **24** |
| decision records | **1342** |
| trade rows | **283** |
| telemetry records | 5406 |
| candles | 8937 |

**DO NOT read a single P&L figure off this table.** Of the 283 trade rows,
**249 belong to Run 01, and 245 of those are `setup_tag = "Backtest replay"`** — imported history,
not engine simulation. Separated:

| | rows | realised P&L |
|---|---|---|
| **Live engine simulation** (runs 02-24) | **34** | **807.96** |
| Run 01 — backtest replay + pre-run history | 249 | 21654.23 |

**The engine's own simulated trading has produced 807.96 across 34 trade rows.** The larger number
is replay data swept into a synthetic container run, and reporting the two together would overstate
live results by roughly twenty-seven times.

**Every decision record and every trade row maps to a real run** — measured: zero `NULL` run ids,
zero ids absent from `engine_runs`.

## The runs

Trades and positions differ: `EXIT-001` splits a position into a 70/30 pair, so one position can
produce two trade rows sharing a `broker_id` (`B225`).

| # | run | started | duration | decisions | abstained | signals | trades | positions | P&L |
|---|---|---|---|---|---|---|---|---|---|
| 01 | [`00000000`](RUN-01__2026-08-04__00000000.md) | `2026-08-04T00:43:12` | 42h 24m 15s | 108 | 102 | 6 | 249 | 1 | 21654.23 |
| 02 | [`7d788ad6`](RUN-02__2026-08-05__7d788ad6.md) | `2026-08-05T19:07:27` | 71h 25m 26s | 138 | 137 | 1 | 0 | 0 | 0 |
| 03 | [`1e2d1ec5`](RUN-03__2026-08-08__1e2d1ec5.md) | `2026-08-08T18:32:54` | 0h 23m 7s | 2 | 2 | 0 | 0 | 0 | 0 |
| 04 | [`c2b78a47`](RUN-04__2026-08-08__c2b78a47.md) | `2026-08-08T18:56:04` | 23h 48m 0s | 41 | 40 | 1 | 0 | 0 | 0 |
| 05 | [`3c975f5e`](RUN-05__2026-08-09__3c975f5e.md) | `2026-08-09T18:45:43` | 2h 34m 1s | 6 | 5 | 1 | 0 | 0 | 0 |
| 06 | [`cd0361e9`](RUN-06__2026-08-09__cd0361e9.md) | `2026-08-09T21:21:02` | 73h 46m 32s | 95 | 92 | 3 | 3 | 1 | -58.26 |
| 07 | [`d6340ff9`](RUN-07__2026-08-12__d6340ff9.md) | `2026-08-12T23:12:06` | 17h 41m 47s | 14 | 12 | 2 | 2 | 1 | 2.94 |
| 08 | [`f5aa9754`](RUN-08__2026-08-13__f5aa9754.md) | `2026-08-13T16:58:26` | 0h 3m 53s | 3 | 3 | 0 | 0 | 0 | 0 |
| 09 | [`e9d0a351`](RUN-09__2026-08-13__e9d0a351.md) | `2026-08-13T17:03:04` | 0h 1m 40s | 2 | 2 | 0 | 0 | 0 | 0 |
| 10 | [`6059a2ea`](RUN-10__2026-08-13__6059a2ea.md) | `2026-08-13T17:05:46` | 0h 30m 25s | 2 | 2 | 0 | 0 | 0 | 0 |
| 11 | [`080af8be`](RUN-11__2026-08-13__080af8be.md) | `2026-08-13T17:36:59` | 3h 10m 28s | 6 | 4 | 2 | 2 | 1 | -4.70 |
| 12 | [`ea32c11c`](RUN-12__2026-08-13__ea32c11c.md) | `2026-08-13T20:48:58` | 0h 32m 37s | 2 | 0 | 2 | 2 | 1 | 2.52 |
| 13 | [`a8b98943`](RUN-13__2026-08-13__a8b98943.md) | `2026-08-13T21:22:43` | 0h 15m 50s | 2 | 0 | 2 | 2 | 1 | 1.15 |
| 14 | [`d8280803`](RUN-14__2026-08-13__d8280803.md) | `2026-08-13T21:39:18` | 1h 24m 45s | 2 | 0 | 2 | 2 | 1 | -6.39 |
| 15 | [`2b3bc59e`](RUN-15__2026-08-13__2b3bc59e.md) | `2026-08-13T23:05:30` | 0h 10m 0s | 6 | 6 | 0 | 0 | 0 | 0 |
| 16 | [`ff33aa4e`](RUN-16__2026-08-13__ff33aa4e.md) | `2026-08-13T23:16:35` | 10h 14m 15s | 170 | 167 | 3 | 3 | 1 | 32.99 |
| 17 | [`8752c718`](RUN-17__2026-08-14__8752c718.md) | `2026-08-14T09:33:17` | 1h 12m 54s | 17 | 16 | 1 | 1 | 1 | -9.01 |
| 18 | [`f7872d8e`](RUN-18__2026-08-14__f7872d8e.md) | `2026-08-14T10:48:45` | 0h 12m 35s | 8 | 8 | 0 | 0 | 0 | 0 |
| 19 | [`b2c4bab3`](RUN-19__2026-08-14__b2c4bab3.md) | `2026-08-14T11:02:31` | 61h 32m 54s | 61 | 59 | 2 | 2 | 1 | -16.86 |
| 20 | [`be4ceda2`](RUN-20__2026-08-19__be4ceda2.md) | `2026-08-19T13:16:43` | 5h 33m 27s | 68 | 67 | 1 | 2 | 1 | 228.68 |
| 21 | [`a32c3b98`](RUN-21__2026-08-19__a32c3b98.md) | `2026-08-19T18:50:22` | 102h 50m 38s | 307 | 303 | 4 | 6 | 1 | 324.05 |
| 22 | [`c533c6ea`](RUN-22__2026-08-24__c533c6ea.md) | `2026-08-24T01:41:16` | 2h 2m 5s | 50 | 50 | 0 | 0 | 0 | 0 |
| 23 | [`f8b40671`](RUN-23__2026-08-24__f8b40671.md) | `2026-08-24T03:50:25` | 11h 46m 17s | 83 | 81 | 2 | 4 | 2 | 303.18 |
| 24 | [`fe837dd1`](RUN-24__2026-08-24__fe837dd1.md) | `2026-08-24T15:45:20` | — | 149 | 146 | 3 | 3 | 2 | 7.67 |

## Three things to read before using the table

**Run 01 is not a real run.** Its id is `00000000-0000-0000-0000-000000000001` and its own note
says so: *"Everything recorded before runs existed. Left ACTIVE so the engine adopts it on first
start and no history disappears."* It is a container for pre-run history, it has no configuration
recorded, and **245 of its 249 trades are tagged `Backtest replay`** — only 4 are live. Its figures
are neither one session nor one kind of activity.

**The `positions` column is meaningless for Run 01, and that is `B225`.** All 249 of its trade rows
carry the literal `broker_id = "paper"`, because `broker_id` was written as a constant before the
fix. Grouping by it therefore reports **one** position for 249 trades. Every other run has real
per-position ids (5 distinct across runs 02-24), so the column means what it says from Run 02
onward.

**The last run had not ended when this was exported.** Its `ended_at` is null and its figures are
in flight; every other run is closed.

## Configuration

Runs record a config snapshot at start, so a result can never be read against the wrong settings.
The common configuration across runs that have one:

```json
{
  "bias_tf": "D",
  "broker_mode": "sim",
  "engine_version": "ict-v2-lookahead-fixed",
  "entry_tf": "1H",
  "max_concurrent": 3,
  "mode": "PROP_FIRM_SIM",
  "price_source": "binance",
  "risk_pct": 0.01,
  "starting_balance": 5000.0,
  "symbols": [
    "BTC/USD",
    "ETH/USD"
  ]
}
```

Each run document names how its own configuration differs from that, or states that it is identical.

## Machine-readable

* `data/decisions-<run>.jsonl` — **every** decision row for that run, all 24 columns, one JSON
  object per line. Nothing is summarised away.
* `data/trades.csv` — all 283 trade rows across every run, all columns.

*Generated by a script over a single database extract; the script is not committed because it
embeds a connection. [METHOD.md](METHOD.md) states exactly what it did.*
