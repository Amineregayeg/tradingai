# Malek — current state

_Last updated: 2026-09-14 00:45 WAT, by Malek's manager session. Updated about every 2 hours._

## Goal right now

**Run the full paper-trading simulation on Alpaca, and be able to track it.** Malek decided on 2026-09-10 that the
venue is Alpaca (paper account), not MetaTrader 5. The platform trades **long only** because Alpaca does not allow
shorting crypto, and every report must say so: about half the strategy's historical trades were shorts.
The plan is `ALPACA_PROGRAMME.md` on `main`.

## State

- **The trading engine is held (stopped on purpose) and has been since 2026-09-01.** Do not start it.
- **Production runs commit `6ae6aca`** (deployed 2026-09-12, database migration 0013). `main` is ahead of it.
- **No order has ever been placed on Alpaca.** Every Alpaca test so far runs against fakes or a local HTTP server.
- **The engine cannot select Alpaca today.** A hard-coded setting (`BROKER_MODE = "sim"`, register `B430`) keeps it
  on the simulator. That is a safety lock, and it is switched last, deliberately.

## How the work is organised on Malek's side

Three Claude sessions work together: a **manager** (plans, rules, verifies, keeps the register), an **execute**
seat (builds) and a **review** seat (attacks each commit with mutation testing before it counts as done). Every
defect found goes into `KNOWN_ISSUES.md` with a B-number. A commit is only "done" after review passes it.

## Programme parts

| Part | Status |
|---|---|
| A — Alpaca adapter | done |
| B — long-only refusal | done |
| C — order path wiring | done |
| D — order sending, sizing, fills | done; safety fixes passed review up to `fb3dab6` (2026-09-13) |
| E — the feedback analysis must refuse to mix long-only runs with older two-direction runs | **not built** |

## In progress

- **`B442`: the kill switch does not stop an entry already under way.** Reproduced on the simulator: a position can
  open after the switch is pulled. Being built by the execute seat (uncommitted on Malek's machine). It adds
  migration 0016.

## Next tasks, in order

1. Test migrations 0014–0016 on a scratch copy of the production database, then deploy (Malek decides which build).
2. **The first real orders ("probes" 1–4)**, run by hand on the paper account, following Malek's runbook. They answer
   questions only Alpaca can: does it accept a stop-loss attached to a crypto order, does it acknowledge before
   filling, how it spells symbols, and whether an attached stop blocks a partial close.
3. `B445` + `B446`: the kill switch's report can lose rows (a confirmed close shown as a failure), and a cancelled
   kill switch is silently swallowed. Queued right after `B442`.
4. `B437`: Alpaca calls currently block the app while they wait — move them to one worker queue per account.
5. **`B428b`, the largest remaining piece: manage and record positions on Alpaca** (register `B444`). Today the 70%
   take-profit would silently never happen on Alpaca, and a stop or target filling at Alpaca would write no trade
   and leave the decision open.
6. Part E.
7. Switch the engine to Alpaca (`B430`), last.

## Open decisions (Malek's)

- Deploy `fb3dab6` now for the probes, or wait for `B442` and deploy once.
- The wait before an order counts as unresolved (default 5 seconds).
- Whether to cancel the unfilled rest of a partially filled order.
- `B435`: halt or only alert when saving a trade record fails.
- `B443`: the kill switch can outlast the web proxy's 120-second limit on a slow venue; how it should respond.

## Do not touch

- `backend/app/services/broker/`, `execution/service.py`, `compliance/kill_switch.py`, `models/decision_record.py`,
  and new migrations: `B442` is being edited there now.
- Production, the engine, and `BROKER_MODE`.

## For the other side

- Welcome. The newest entries at the bottom of `KNOWN_ISSUES.md` are the best map of where the risks are.
- New findings: list them under "For the register" in `amine/CURRENT.md` and this side will file them with an ID.
