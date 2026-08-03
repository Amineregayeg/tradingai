# Known issues — open problems register

Problems found while building, **not yet fixed**. Solved issues are not listed
(they are in git history). Each entry says what it is, where it came from, and
what it could break.

Ordered by what would hurt most, not by how hard it is to fix.

Last updated: 2026-08-03 (after D1 — verified backups running)

---

## The rule for keeping this file honest

**At the end of every task, any problem found but not fixed gets written here
before moving on.** Not mentioned in passing, not left in a commit message —
written here, where it will actually be reviewed.

This exists because of a specific failure: a problem was described as "noted"
when it had only been said out loud and never recorded. A conversation scrolls
away. Claiming something is written down when it is not is worse than saying
nothing, because it stops anyone else from writing it down either.

Two things that make entries worth having:

* **Verify before you write.** Checking one such claim showed the claim itself
  was wrong *and* uncovered a more serious defect underneath (B4 — a startup
  race that silently disconnects the broker). A register full of guesses is a
  register nobody trusts.
* **Say what it could break, not just what it is.** "X is unset" is a note;
  "X is unset, so a reboot silently drops the broker and the dashboard shows
  nothing" is a decision someone can act on.

Fixed something? Delete its entry in the same commit as the fix. A register that
only grows becomes wallpaper.

---

## A. Wrong numbers — these can mislead a decision

### A2. Live and backtest engines decide direction differently
**Found in:** inherited (residual #2); still open, listed as task I8
**What it is:** `strategy_step.py` calls `_daily_bias_events` (non-causal,
whole-series) while `backtest/engine.py` calls `_causal_daily_bias_events`.
**Why it matters:** Tier 1.7 requires the forward run to agree with the
backtest. They are currently different decision rules, so that gate cannot be
evaluated at all — and a simulation cannot prove a live bot correct if they are
not the same program.
**Fix:** point the live path at the causal builder; add a regression test.

### A3. Backtests still measure a different venue than they trade
**Found in:** Phase 4 planning; **narrowed by 4.4**
**What it is:** the LIVE path can now read CFT's own candles
(`PRICE_SOURCE=cft`), so live analysis and execution finally agree. Historical
backtests cannot: CFT serves only ~125 days of 1H history against the ~470 the
corrected backtest window needs, so backtests stay on Binance.
**The divergence is now measured rather than unknown** (300 matched 1H bars):

| | BTC | ETH |
|---|---|---|
| close vs Binance | −0.0485% (stdev 0.0093) | −0.0485% (stdev 0.0090) |
| bar-range difference | mean 0.013%, max 0.060% | mean 0.014%, max 0.117% |

The close offset is a near-constant BID-side spread and moves no structure —
BOS/FVG/direction are scale-invariant. The **bar ranges** are the real risk: a
high or low differing by up to 0.117% can create or erase the FVG an entry
depends on.
**Why it still matters:** a backtest result on Binance bars is not strictly a
prediction of CFT behaviour, and the gap is largest exactly where the strategy
is most sensitive.
**Fix options:** accept and disclose it (the divergence is now quantified); or
start archiving CFT candles now so that in ~1 year a same-venue backtest becomes
possible. Archiving is cheap and the history is unrecoverable if not collected —
the same argument as the dominance collector.

### A6. The CFT order body has never been accepted by CFT
**Found in:** 4.5
**What it is:** the order path is built and tested, but only against a MOCK. Its
endpoint map was reverse-engineered from CFT's web terminal by network capture,
so the field names are inferred, not documented — `stopLoss` vs `sl`,
`volume` vs `lots`, whether `instrument` is required alongside `symbol`.
**Why it matters:** a mock accepts whatever it is given. The first real order is
therefore also the first test of the body shape, and the plausible failure modes
are not symmetric: a rejected order is harmless, but a *partially* accepted one —
filled with the stop-loss field silently ignored — is an unprotected live
position.
**Fix:** the first live order must be placed manually, at minimum size, with a
human watching, and the result compared against what the adapter expected. That
is precisely the Tier-3 decision `ALLOW_LIVE_TRADING` exists to force; do not let
the first real order be one the engine placed on its own.

### A7. Two flags must be set to trade, and nothing warns if only one is
**Found in:** 4.5
**What it is:** enabling live orders needs `ALLOW_LIVE_TRADING=true` on the api
AND `BRIDGE_ALLOW_TRADING=true` on the bridge. That is deliberate — one mistake
cannot arm a funded account. But the halfway state is silent.
**Why it matters:** with only the api flag set, the engine believes it can trade
and every order fails at the bridge with a 403. The reason is now clear in the
message (fixed in 4.5), but nothing surfaces the mismatch *before* an order is
attempted.
**Fix:** show both flags on the dashboard's broker panel — `trading_enabled` is
already reported by `/status` on the bridge and flows through
`/api/brokers/accounts`. Small piece of UI.

### A5. PRICE_SOURCE=cft is built but not switched on
**Found in:** 4.4
**What it is:** the live loop still defaults to Binance. Switching is a
deliberate env change, not automatic.
**Why it matters:** until it is switched, live analysis still reads a different
venue than it would trade on — the thing 4.4 exists to fix.
**Why it was left off:** CFT bars come through the browser bridge, so the engine
would gain a dependency on it; and CFT's short 1H history means a restart cannot
rebuild as much context as Binance provides. Worth switching once the bridge has
demonstrated a few days of uptime.
**Fix:** set `PRICE_SOURCE=cft` on the api service.

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
**Partly addressed (4.2 / 4.3):** session health is now visible on the dashboard
(`/api/brokers/accounts` reports transport state), and a supervisor reconnects a
dead session within ~1 min. What remains is **alerting** — nothing tells a human
unprompted; you still have to be looking at the page.

### B5. The balance-drift check is inactive — no snapshot history exists
**Found in:** 4.6 (verified against production)
**What it is:** reconciliation's balance check compares CFT's current balance
against the most recent `PropFirmSnapshot`. Production has **0 profiles and 0
snapshots**, because `observe_sync` only writes a snapshot for a configured
prop-firm profile and none has been created. Live proof: the endpoint returns
`checks_run: ["positions"]` — the drift check silently does not run.
**Why it matters:** of the four reconciliation checks, drift is the one that
catches a balance moving when nothing of ours explains it — i.e. manual trading
or a malfunction. Position checks only catch a position that is still OPEN; a
trade opened and closed between two runs is invisible without it.
**Not a silent failure by luck:** `checks_run` was built precisely so "no
findings" cannot be mistaken for "all clear". It is working as intended — the
gap is visible rather than hidden.
**Fix:** create a prop-firm profile for the CFT account (the Prop Firm page
does this), which starts `observe_sync` writing snapshots every 2 minutes and
activates the check. Alternatively, record balance history independently of
prop-firm profiles.

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

### D5. Backups are on the same host as the database
**Found in:** D1 (recorded when backups were built)
**What it is:** verified daily backups now run, but they live in
`~/tradingai-backups/` on the same VPS as the database they protect.
**Why it matters:** they cover database corruption, a dropped table, a bad
migration, a deleted Docker volume — not loss of the machine. If the VPS goes
away, the backups go with it, including the unrecoverable dominance history.
**Why it was left:** off-site copies need a destination and credentials for it,
which is a decision (and a cost) rather than a code change.
**Fix:** sync `~/tradingai-backups/` to object storage or another host. The
directory is small — ~2 MB per run, so a year is under 1 GB.

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

### F7. The CFT connection does not pin an account id
**Found in:** 4.2. `account_id` is empty on the stored connection, so the bridge
uses whichever account CFT currently has selected. Fine with one account;
ambiguous the moment there are several (the adapter's own docstring cites two —
`365105` for a 5k challenge, `373010` for a 2.5k instant). Balances would then
be read from whichever CFT last selected, with nothing in our UI showing which.
**Fix:** set `account_id` on the connection once the intended account is chosen.

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
