# Running the tests locally

This file covers one thing: how to verify a change without pushing it.

That was not possible for most of this project's life. The only test runner was
GitHub Actions, so checking any change meant commit, push, wait ~4 minutes. That
does not just cost time — it changes what gets verified. Bugs got caught with
throwaway shell probes because "write a test and run it" was not an available
move.

## Setup

```bash
./scripts/dev_env.sh
```

Idempotent — safe to re-run, and takes about 15 seconds once built. It creates a
Python virtualenv, installs both dependency sets, installs the frontend
packages, and checks that the strategy-critical versions match production.

```bash
./scripts/dev_env.sh --check    # report what is present, change nothing
```

## Running things

| What | Command | From |
|---|---|---|
| Backend suite (632 tests, ~2 min) | `~/.venvs/tradingai/bin/python -m pytest` | `backend/` |
| One file | `~/.venvs/tradingai/bin/python -m pytest tests/unit/test_build_info.py` | `backend/` |
| Frontend tests (153 tests, ~1 min) | `pnpm exec vitest run` | `frontend/` |
| Frontend typecheck | `pnpm tsc` | `frontend/` |
| Lookahead guards (Tier 0.2) | `./scripts/verify_guards.sh` | `backend/` |

**`pnpm test` is bare `vitest`, which watches forever.** Use `vitest run`.

`verify_guards.sh` refuses to run with uncommitted or untracked files in the
paths it mutates — it edits real source to prove the guards bite, and it must be
able to restore exactly what was there. Commit first.

## Two things this environment does not prove

**Node version.** CI and the `web` container use node 20. Your machine may have
something newer, which is normally fine for vitest but is not evidence that the
production build works. CI remains the authority on `pnpm build`.

**Nothing else about production.** The suite runs against in-memory SQLite,
while production is TimescaleDB. Tests passing locally means the logic is
right, not that a migration will apply cleanly.

## Why the setup is shaped the way it is

* **Installs with `pip install -e ".[dev]"`** — the same command CI runs.
  `pyproject.toml` sources its dependencies from `requirements-prod.txt` and
  `requirements-dev.txt` through setuptools dynamic metadata, so installing this
  way exercises that wiring. It has broken before (an unsatisfiable numpy pin)
  and was invisible until someone tried the documented command.
* **The venv lives in `$HOME`, not the repo.** On WSL the repo is on `/mnt/c`, a
  9p filesystem where a virtualenv's thousands of small files are painfully
  slow. Override with `TRADINGAI_VENV` if you want it elsewhere.
* **pip is bootstrapped with `get-pip.py`.** Debian's stock python has
  `ensurepip` stripped out, and the alternative is a sudo password to install
  `python3-venv`. This needs no root.
