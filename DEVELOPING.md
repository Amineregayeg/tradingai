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
| Backend suite (858 tests, ~2 min) | `~/.venvs/tradingai/bin/python -m pytest` | `backend/` |
| One file | `~/.venvs/tradingai/bin/python -m pytest tests/unit/test_build_info.py` | `backend/` |
| Frontend tests (171 tests, ~1 min) | `pnpm exec vitest run` | `frontend/` |
| Frontend typecheck | `pnpm tsc` | `frontend/` |
| Lookahead guards (Tier 0.2) | `PYTHON=~/.venvs/tradingai/bin/python ./scripts/verify_guards.sh` | `backend/` |
| Dependency single-source | `python3 scripts/check_dependency_sources.py` | repo root |
| Deploy drift (needs ssh) | `~/.venvs/tradingai/bin/python scripts/check_deploy_drift.py` | repo root |
| Deploy the dominance collector (needs ssh) | `./scripts/deploy_dominance.sh` (`--check` to report only) | repo root |

**`pnpm test` is bare `vitest`, which watches forever.** Use `vitest run`.

**The backend suite is GREEN as of 2026-08-12 (T-0003): 858 passed, 0 failed.**
**Any** failure is new and yours.

It was red from 2026-08-09 to 2026-08-12 with two known failures in
`tests/unit/test_dominance_source.py`, and this paragraph used to tell you to
expect them and treat a third as new. That tripwire is now retired — leaving it
would have been calibrated to a state that no longer exists, telling you to
ignore exactly two failures that can no longer occur. If you find yourself
editing a "known failures" note like this one, delete it rather than adjust it;
a stale allowance is worse than none, because it reads as permission.

### About `verify_guards.sh`

It refuses to run with uncommitted or untracked files in the paths it mutates —
it edits real source to prove the guards bite, and must be able to restore
exactly what was there. Commit first.

Until 2026-08-12 that refusal **destroyed the work it refused to overwrite**: the
EXIT trap was armed above the check, so the `exit 1` fired `git checkout` over
your uncommitted changes, with no dirty file, no stash and no reflog to recover
from. Fixed — `restore()` now no-ops until a mutation has actually been applied.
Commit first anyway; the refusal is still there and is still correct.

**Two things that survive the fix, and both bite in normal use:**

* `restore()` covers only the four source files the probes mutate. A test file
  you edited — including one you neutered deliberately to check a probe — is
  **not** restored. Check `git status --porcelain` after every run.
* Exit 0 with eight `ok` lines and exit 0 having silently restored nothing look
  identical from outside. An empty `git status --porcelain` afterwards is the
  only thing that distinguishes them.

It needs a python that has pytest. It looks for `python` then `python3`, so on a
machine where neither has pytest installed you must point it at the venv with
`PYTHON=`. It exits 2 rather than guessing.

That strictness is not fussiness. The script reads "the test run failed" as "the
guard bit" — and a missing command is also a failure. Before this was fixed, on
a box without `python` on PATH it reported every guard as load-bearing and
printed `TIER 0.2 PASSED` without running a single test. It now proves the
baseline is green before trusting any mutation result.

### About `check_deploy_drift.py`

Three compose files in `deploy/` each claim to be "the record of what runs" on
the VPS. Nothing verified that, and the claim was untrue three separate ways
before anyone looked — an inline pip list on the server, a lockfile flag, and
two missing CFT bridge variables that meant the committed record described an
api with no route to its broker. This makes checking it one command.

It needs ssh to `pfe-vps`, so it cannot run in CI as things stand. Run it after
any deploy, and after changing anything in `deploy/`.

**It currently exits 0** — all seven services across the three projects match
their committed description. Any drift it reports is therefore new, and worth
stopping for rather than explaining away.

That sentence was **false from 2026-08-09 to 2026-08-10** and nobody noticed, which
is worth more than the fix. `--loop 15` was committed for the collector (`56518f8`),
recorded in `KNOWN_ISSUES` B11 as done, and never copied to the server — so the check
exited 1 while this file told each new reader that any drift they saw was damage they
had just caused. A baseline that lies costs more than no baseline. If you find this
sentence disagreeing with the script again, the script is right.

The collector was drifting because it had no deploy path — see
`scripts/deploy_dominance.sh` in the table above, which now exists for exactly that
reason and re-runs this check itself.

It compares parsed YAML with shell comments stripped, because a raw diff of
these files is ~91 lines of comment noise. Secret **values** are never compared
or printed — only whether each side has the variable at all, which is the check
that would have caught the missing bridge wiring.

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
