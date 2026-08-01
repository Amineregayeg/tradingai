# Known issues — open problems register

Problems found while building, **not yet fixed**. Solved issues are not listed
(they are in git history). Each entry says what it is, where it came from, and
what it could break.

Ordered by what would hurt most, not by how hard it is to fix.

Last updated: 2026-08-01

---

## A. Wrong numbers — these can mislead a decision

### A1. The baseline edge measurement was never re-verified under production's libraries
**Found in:** I1 (test against production dependencies)
**What it is:** the headline result this whole project is judged against — *143
trades, −0.118R, −16.1%* — was only ever produced under numpy 1.x. Production
runs numpy 2.2.6. The test suite passes under both, but the backtest itself was
not re-run (deliberately deferred at the time).
**Why it matters:** that number is the yardstick for judging Magic Alignment. If
numpy 2's floating-point reductions shift it even slightly, every future
"better than baseline" comparison inherits the error.
**Fix:** re-run `code/run_corrected_backtest.py` under the production pins and
compare. Needs network access to Binance; about a minute.

### A2. Live and backtest engines decide direction differently
**Found in:** inherited (residual #2); still open, listed as task I8
**What it is:** `strategy_step.py` calls `_daily_bias_events` (non-causal,
whole-series) while `backtest/engine.py` calls `_causal_daily_bias_events`.
**Why it matters:** Tier 1.7 requires the forward run to agree with the
backtest. They are currently different decision rules, so that gate cannot be
evaluated at all — and a simulation cannot prove a live bot correct if they are
not the same program.
**Fix:** point the live path at the causal builder; add a regression test.

### A3. Price feed and execution venue disagree
**Found in:** Phase 4 planning
**What it is:** the strategy reads **Binance** prices but would execute on
**CFT**, which quotes its own symbols (`BTCUSDT.cft`) from its own feed.
**Why it matters:** for a strategy built on structural price levels, the engine
can see a setup that never existed on the chart it actually trades. Silent, and
nothing currently measures the divergence.
**Fix:** planned as task 4.4 — read prices from CFT. Note CFT history may be
shorter than Binance's, so backtests may need to keep using Binance.

### A4. LTF-BOS gate is mildly non-causal
**Found in:** inherited (residual #1)
**What it is:** `bos_dir_upto` uses full-series `smc` `broken_index`, which is
derived from swing detection that can see later bars. Measured impact: ~3% of
entry-eligible bars.
**Why it matters:** it is a filter, not a direction source, so the effect is
bounded — but it means fine-grained edge numbers are not fully trustworthy.
**Fix:** decide whether to make it causal *before* trusting detailed results;
doing so shifts the baseline you compare against.

---

## B. Silent failure — things that break without telling anyone

### B1. Nothing watches the dominance collector
**Found in:** I4 (dominance collector)
**What it is:** the container reports unhealthy ~10 minutes after samples stop,
but nothing reads that healthcheck. No alert, no UI indicator.
**Why it matters:** **this data cannot be recovered.** Intraday dominance
history exists only if something was recording at the time. A quiet death costs
days that no later fix can retrieve.
**Fix:** surface collector status in the UI (planned as 1.3 / 3.3), ideally with
an alert.

### B2. The CFT browser session is a single point of failure
**Found in:** 4.1 (browser bridge)
**What it is:** one Chromium session serves every CFT call. It self-heals on
401/403 and refreshes every 6h, but a crash mid-trade costs an ~11s re-login,
and repeated failures are only visible in container logs.
**Why it matters:** an order attempted during a dead session fails. Nothing
currently surfaces "the bridge is unhealthy" to a human.
**Fix:** connection health in the UI (task 4.3), plus alerting on repeated
bridge failures.

### B3. Nobody can tell which code version is running
**Found in:** I6 (never started)
**What it is:** containers `git clone --depth 1 main` at startup and record
nothing. No commit SHA anywhere.
**Why it matters:** you cannot debug or roll back what you cannot identify. Two
containers recreated at different times can silently run different code.
**Fix:** pin a commit/tag and expose the running SHA on an endpoint.

---

## C. Drift — the repo and the server disagree

### C1. The VPS compose still carries its own dependency list
**Found in:** I3 (dependency consolidation)
**What it is:** `/docker/tradingai/docker-compose.yml` still inline-pins ~20
packages instead of installing from `requirements-prod.txt`. Verified identical
*today*, but it is a second list.
**Why it matters:** this is exactly how production drifted onto numpy 2.2.6
while `pyproject.toml` demanded numpy<2.0.0. It will drift again.
**Fix:** update the VPS compose to `pip install -r /app/requirements-prod.txt`.
The repo copy (`deploy/compose.vps.yaml`) is already correct — the server is
what is stale.

### C2. Frontend installs with `--no-frozen-lockfile` in production
**Found in:** I3
**What it is:** the VPS web container ignores the committed lockfile and
re-resolves packages.
**Why it matters:** production can silently run frontend versions CI never
tested — the same class of drift as C1, on the other half of the app.
**Fix:** same edit as C1; the repo copy already says `--frozen-lockfile`.

### C3. The dominance collector runs from a hand-copied file
**Found in:** I4 deployment
**What it is:** it bind-mounts `/home/deploy/tradingai-dominance/app/`, a copy
made before the code reached GitHub, rather than cloning the repo.
**Why it matters:** application code on the server that the repo cannot see —
the same pattern as C1. Editing the repo does not change what runs.
**Fix:** now unblocked (the code is on `main`); switch to
`deploy/compose.dominance.yaml`. The CSV lives on the host, so no samples are
lost in the swap.

---

## D. Production hygiene

### D1. No database backup
**Found in:** I11 (never started)
**What it is:** TimescaleDB sits in a named Docker volume with no backup.
**Why it matters:** the `decision_records` table **is** the evidence that the
strategy does or does not work. Losing it loses the proof, not just data.

### D2. Plain HTTP, and the API token needs rotating
**Found in:** I10 (never started)
**What it is:** the site runs on `http://`, so the bearer token crosses the
network readable. It is also a single long-lived token, and it has appeared in
chat transcripts.
**Fix:** put it behind the Caddy already on the box, then rotate the token.

### D3. Nothing stops a broken merge
**Found in:** I2 (CI)
**What it is:** CI runs on every push, but `main` has no branch protection.
**Why it matters:** a red build can be merged anyway; the robot reports and is
ignored.

### D4. Production serves the frontend from the Vite dev server
**Found in:** I3 (reading the real compose)
**What it is:** the web container runs `pnpm dev` — unminified, source maps
exposed, HMR websocket open, slower.
**Fix:** `pnpm build` plus a static server. Needs testing, so it was not bundled
into a dependency change.

---

## E. Test coverage gaps

### E1. The live entry brain has no causality test
**Found in:** I2 (guard verification)
**What it is:** `strategy_step.py` carries the same born+2 lookahead guard as
the backtest, but no test exercises it, so `verify_guards.sh` cannot probe it.
**Why it matters:** **that is the code path that actually trades.** Its guard is
the only unverified one.
**Fix:** add `test_live_step_causality.py` asserting `evaluate_latest_bar` never
returns a Signal whose entry equals the deciding bar's own high/low, then add a
probe for it.

### E2. Seven pre-existing lint errors keep lint advisory
**Found in:** I2
**What it is:** 6 `no-explicit-any` plus one `react-hooks/exhaustive-deps`, so
the CI lint job runs with `continue-on-error: true`.
**Why it matters:** an advisory check is one people learn to ignore.
**Fix:** clear the seven, then flip `continue-on-error` to false.

---

## F. Known-minor (documented, low impact)

### F1. 1-minute dominance bars are degenerate
**Found in:** I4. At 60s polling a 1m bar holds one observation, so O=H=L=C. 5m
and above carry real structure. Drop `--loop` to ~15s if 1m bars are ever
wanted.

### F2. 245 pre-fix replay rows remain in the production database
**Found in:** I5. Now excluded from performance views and labelled in the
Journal, but they average +0.081R from the discredited lookahead engine. Leave,
regenerate, or delete — a data decision.

### F3. Decision-record commit-window race
**Found in:** inherited (residual #5). A manual/kill close during the ~ms commit
of a just-opened decision can orphan it as `OUTCOME_OPEN`. Audit data only.

### F4. `/positions/demo` pair collision
**Found in:** inherited (residual #6). The dev seed endpoint can resolve the
wrong decision if the loop holds the same pair. Authed dev endpoint.

### F5. `status()` DB-down fallback switches balance source
**Found in:** inherited (residual #4). Cosmetic; only on the DB-unreachable path.

### F6. Engine runs in `paper`, not prop-firm `sim`
**Found in:** platform audit. `ENGINE_BROKER` is unset, so the prop-firm
challenge simulator — the Tier 2 vehicle — is not the one running. Should only
be flipped after A2 and A3 are fixed, or it measures with a broken instrument.

---

## G. External / not ours to fix

### G1. The CFT integration is a workaround, not an integration
**Found in:** 4.1
**What it is:** CFT is behind Cloudflare bot protection that fingerprints the
TLS handshake, so no plain-HTTP client can reach it regardless of credentials.
We drive their web terminal with a real browser instead.
**Why it matters:** it breaks if CFT redesigns their login page or tightens
detection. It also means a permanent Chromium process beside the app.
**Fix:** ask CFT to allowlist the server IP (`31.97.183.142`) or expose a
documented API. Then the browser can be deleted entirely and the adapter becomes
ordinary HTTP. No longer urgent — but still the durable answer.

### G2. Docker-group access is root-equivalent
**Found in:** 4.1 deployment
**What it is:** the `deploy` user cannot write `/docker/tradingai` directly but
can mount it into a container running as root. This is inherent to Docker group
membership, not a misconfiguration.
**Why it matters:** it makes task I9 (root access) much less urgent, but that
login should be protected as if it were root — because it is.
