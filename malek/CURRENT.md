# Malek — current state

_Last updated: 2026-09-14 04:50 WAT, by Malek's manager session. Updated about every 2 hours._

## Goal right now

**Run the full paper-trading simulation on Alpaca, and be able to track it.** Malek decided on 2026-09-10 that the
venue is Alpaca (paper account), not MetaTrader 5. The platform trades **long only** because Alpaca does not allow
shorting crypto, and every report must say so: about half the strategy's historical trades were shorts.
The plan is `ALPACA_PROGRAMME.md` on `main`.

## State

- **The trading engine is held (stopped on purpose) and has been since 2026-09-01.** Do not start it.
- **Production runs commit `fb3dab6`** (deployed 2026-09-14, database migration 0015). `main` is ahead of it. Production is
  pinned to a reviewed commit with a compose override file; never deploy with a plain `docker compose up`.
- **The first real orders were placed on the Alpaca PAPER account on 2026-09-14** (three probe rounds, about $15 each,
  ending flat). They showed the order path as built cannot trade Alpaca crypto yet: see `B447`–`B451` in `KNOWN_ISSUES.md`.
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

- **Item 3, the kill-switch safety release, is commit `ab64c03`.** It bundles `B442`, `B445`/`B446`, follow-up (2c) and
  (2d).
  - All have passed review except (2d), which is in review now. (2d) hides secrets at any depth in the kill switch's
    "already in progress" answer.
  - Migration 0016 already passed the scratch-copy test.
  - It deploys once (2d) passes and a full test run pinned to `ab64c03` is green.
- **Test-only fixes (2e)** for seven kill-switch tests with a timing race (`B452`) are being built. Review confirmed the
  checks those tests carried still hold.
- **Item 4, `B437`** (Alpaca calls blocking the app): built, and its test record is being redone on top of (2d) and (2e).

## Next tasks, in order (Malek's list, 2026-09-14)

1. ~~Deploy the current fixes~~ — done: `fb3dab6`.
2. ~~The first real orders~~ — done. Findings:
   - Alpaca refuses a stop-loss attached to a crypto order (`B448`).
   - A separate stop locks the position against every close (`B448`).
   - Positions are spelled `BTCUSD` while orders use `BTC/USD` (`B449`).
   - The fee is 0.25% per leg (`B450`).
   - The minimum is $10 to open (`B451`).
   - The order-confirmation fix works on the real venue (`B427`).
3. The kill-switch release `ab64c03` — waiting on (2d)'s review and a pinned full test run; then deploy.
4. `B437` — Alpaca calls stop blocking the app (one worker per account).
5. `B428b` — manage and record positions on Alpaca: stops enforced by the engine, prices from Alpaca's quote,
   one pair spelling, quantities from the venue position, trade rows from Alpaca's fill history, and start-up
   reconciliation.
6. `B430` — make the engine able to select Alpaca, deliberately, last.
7. Part E — the feedback analysis refuses to mix long-only runs with older two-direction runs.

## Open decisions (Malek's)

- Stops on Alpaca are enforced by the engine for now (no protection while it is down); a venue backup stop can be added later.
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
