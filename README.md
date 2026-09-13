# Handoff — where to start

This branch holds **working notes only, no code.** The code is on `main`.

Two people work on TradingAI, each with their own Claude sessions:

| Folder | Written by | Read by |
|---|---|---|
| `malek/` | Malek's sessions (updated automatically about every 2 hours) | Amine |
| `amine/` | Amine's sessions | Malek |

## If you are starting a session — AND BEFORE EVERY NEW TASK

1. Read the **other** side's `CURRENT.md`: the goal, the state, what is in progress, and what must not be touched.
   **Do this again before starting each new task, not only at the start of a session.** If the task would change
   something the other side lists under "In progress" or "Do not touch", stop and ask before changing it.
2. Read that side's newest file in `log/` for what changed recently.
3. Then read your own `CURRENT.md` and carry on.

(On Malek's machine this is enforced: every new task runs `handoff_sync.py peek` against `amine/CURRENT.md`.)

## What each folder contains

```
<name>/CURRENT.md          overwritten: current goal, state, in progress, next tasks, open decisions, do-not-touch
<name>/log/YYYY-MM-DD.md   append-only: one dated entry per update — what was done, and what was learned
```

## Rules

- **Write only in your own folder.** Never edit the other side's files. If something there is wrong, say so in
  your own `CURRENT.md` under "For the other side".
- **Update `CURRENT.md` when the goal or next tasks change, and at the end of every working session.**
- **This repository is PUBLIC.** Never write keys, tokens, passwords, emails, IP addresses or server details. Malek's
  side refuses to publish a file that looks like any of these.
- **Before pushing to `main`, pull first**, and never force-push or rewrite `main`'s history. Both sides push there.
- **Do not deploy, start the trading engine, or change which venue it trades on without Malek's explicit go.** The
  engine is held on purpose (see `malek/CURRENT.md`).
- **Known issues are filed in `KNOWN_ISSUES.md` on `main` with IDs (B-numbers) handed out on Malek's machine.** To
  avoid two people taking the same ID, Amine's side lists new findings in `amine/CURRENT.md` under "For the
  register", and Malek's side files them and replies with the ID.
