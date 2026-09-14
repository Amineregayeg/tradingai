# Malek — current state

_Last updated: 2026-09-14 19:30 WAT, by Malek's manager session. Updated about every 2 hours._

## Goal right now

**Run the full paper-trading simulation on Alpaca, and be able to track it.** Malek decided on 2026-09-10 that the
venue is Alpaca (paper account), not MetaTrader 5. The platform trades **long only** because Alpaca does not allow
shorting crypto, and every report must say so: about half the strategy's historical trades were shorts.
The plan is `ALPACA_PROGRAMME.md` on `main`.

## State

- **The trading engine is held (stopped on purpose) and has been since 2026-09-01.** Do not start it.
- **Production runs commit `e7d7c81`** (`B437` + `B453`, deployed 2026-09-14 13:52 WAT, database still at migration 0016). `main` is ahead of it. Production is
  pinned to a reviewed commit with a compose override file; never deploy with a plain `docker compose up`.
- **Real orders have been placed only by probes, on the Alpaca PAPER account** (seven rounds on 2026-09-14, $10–30 each,
  every round ending flat). The engine itself has placed none. The probes showed the order path as built cannot trade
  Alpaca crypto yet: see `B447`–`B451` in `KNOWN_ISSUES.md`.
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

- **Items 3 and 4 are done.** `B437` (one worker thread per Alpaca account) passed review and was DEPLOYED with the `B453`
  fix as release `e7d7c81`, 13:52 WAT, checked by content. Two small follow-ups are filed (`B462`, `B463`) and go in
  commit `B437b`, right after `B428b` commit (i).
- **Item 5, `B428b`:** the DESIGN is approved (`agents/tasks/T-0144/DESIGN.md`), and building commit (i) has started:
  - position identity
  - pair spelling
  - prices
  - the minimum
  - quantities
  - migration 0017
  **Commit (i) is COMMITTED as `f3250ad`** (15:56 WAT). It passed its own mutation record (113 of 113) and the whole suite
  (3,069 tests). The manager verified it, and review's independent check (304 mutation rows) is running. It is not
  deployed. Migration 0017 already passed a run on a real Postgres copy of production (rows unchanged, and a refused
  downgrade rolls back completely), and its file is unchanged in the commit.
  Probe round 6 confirmed that a cancelled resting order frees the position at once. New issues folded in: `B457`–`B461`.
- **Commits (ii), (iii) and (iv) already have their mutation checks registered in advance** by review (in
  `agents/tasks/_runs/b428b_ii`, `_iii` and `_iv`), with review's design gaps ruled in `T-0144/PLAN.md` revisions 6 and 7.
  Two decisions taken there:
  - trade rows gain the closing order's id (migration 0018, in (ii)), so a partial close is known by identity
  - the engine never sells or counts units on a symbol that it did not open itself
- **Item 6, `B430`, is being prepared in parallel.** Review attacked its brief and found the switch as written would
  take the API down at boot, because production has no Alpaca credentials in its environment. It would also create a
  second credential source. Both are now ruled in `T-0145/PLAN.md` revisions 2 and 3: the engine uses the saved broker
  connection, building a broker never fails boot, and there is one list of reasons Start refuses. `B430` is amended in the
  register. Probe round 7 (14:44 WAT, paper, ended flat) measured three facts:
  - a reused order id is refused
  - 36- and 40-character ids work
  - fill-history pagination is complete, and its `after` filter is exclusive
- **Part E (item 7) is prepared too.** Review attacked its brief, and the rulings are `T-0146/PLAN.md` revisions 2–4:
  - production's whole run history has no recorded venue, so it is "configuration unknown" and is refused as a whole
    (one run can still be analysed on its own)
  - runs are grouped by venue, execution class and engine version
  - exits are labelled by how they were decided
  Review has pre-registered its mutation checks.
- **`B437b` is being built on top of `f3250ad`:** the `B462` and `B463` fixes, plus a guard that blocks the network in
  tests (`B432`). It found 27 tests that reach the internet; 16 of them FAIL offline and passed only because Binance
  answered. All are patched.
- **Interruption:** the machine was suspended from about 15:52 to 18:31 WAT. Both mutation runs resumed afterwards, and
  any row that straddled the gap is re-run before it counts.
- **Process change (Malek: "too slow"):** test runs are now parallel, re-runs are limited to what a change can affect,
  and only review re-runs earlier checks.

## Next tasks, in order (Malek's list, 2026-09-14)

1. ~~Deploy the current fixes~~ — done: `fb3dab6`.
2. ~~The first real orders~~ — done. Findings:
   - Alpaca refuses a stop-loss attached to a crypto order (`B448`).
   - A separate stop locks the position against every close (`B448`).
   - Positions are spelled `BTCUSD` while orders use `BTC/USD` (`B449`).
   - The fee is 0.25% per leg (`B450`).
   - The minimum is $10 to open (`B451`).
   - The order-confirmation fix works on the real venue (`B427`).
3. ~~The kill-switch release~~ — done: `ab64c03`.
4. ~~`B437`~~ — done: deployed `e7d7c81` with (2f). Follow-up `B437b` (`B462`, `B463`, the `B432` socket-blocking fixture) comes after (i).
5. `B428b` — manage and record positions on Alpaca: stops enforced by the engine, prices from Alpaca's quote,
   one pair spelling, quantities from the venue position, trade rows from Alpaca's fill history, and start-up
   reconciliation.
6. `B430` — make the engine able to select Alpaca, deliberately, last.
7. Part E — the feedback analysis refuses to mix long-only runs with older two-direction runs.

## Open decisions (Malek's)

- ~~What the engine may do by itself when the app restarts with Alpaca positions open~~ — **DECIDED by Malek,
  2026-09-14: stops only.** At boot the engine enforces stop-losses and the blind close only: no 70% partial, no
  take-profit, no new entries until someone presses Start.
- Stops on Alpaca are enforced by the engine for now (no protection while it is down); a venue backup stop can be added later.
- The wait before an order counts as unresolved (default 5 seconds).
- Whether to cancel the unfilled rest of a partially filled order.
- `B435`: halt or only alert when saving a trade record fails.
- `B443`: the kill switch can outlast the web proxy's 120-second limit on a slow venue; how it should respond.

## Do not touch

- `backend/app/services/broker/`, `execution/`, `live/crypto_loop.py`, `evaluation/feedback.py`,
  `monitoring/data_health.py`, `models/decision_record.py`, `models/trade.py`, and new migrations: `B428b` commit (i) is
  uncommitted in the shared tree (26 files), and `B437b` is being built on top of it.
- Production, the engine, and `BROKER_MODE`.

## For the other side

- Welcome. The newest entries at the bottom of `KNOWN_ISSUES.md` are the best map of where the risks are.
- New findings: list them under "For the register" in `amine/CURRENT.md` and this side will file them with an ID.
- Newly filed today:
  - `B462`, `B463` (B437 follow-ups)
  - `B464` (the broker manager defaults a blank connection environment two different ways)
  - `B465` (feedback corrections aimed at knobs the live engine does not read)
  - `B466` (dashboard polling queues behind orders)
  `B430` and `B457` were amended with measurements.
