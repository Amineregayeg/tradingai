# Known issues — open problems register

Problems found while building, **not yet fixed**. Solved issues are not listed
(they are in git history). Each entry says what it is, where it came from, and
what it could break.

Ordered by what would hurt most, not by how hard it is to fix.

Last updated: 2026-08-04 (after E5 — controls report their own failures)

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

### A5. The engine still runs on Binance prices, not CFT's
**Found in:** 4.4; **made switchable by 2.2**
**What it is:** the live loop still reads Binance. CFT prices are now selectable
from the New-run form on the engine page — no env change or redeploy — but
nobody has selected them.
**Why it matters:** until it is switched, live analysis reads a different venue
than it would trade on. Measured: closes differ by a near-constant −0.0485%
(harmless — structure is scale-invariant) but individual bar RANGES differ by up
to 0.117%, which can create or erase the FVG an entry depends on.
**The trade-off to weigh first:** CFT bars arrive through the browser bridge, so
the engine gains a dependency on it, and CFT serves only ~125 days of 1H history
against Binance's years — a restart rebuilds less context.
**Fix:** choose "Crypto Fund Trader" as the price source when starting a run.

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

### B1. Failures are visible but nothing tells you unprompted
**Found in:** I4 / 4.1; **narrowed by B1's monitoring work**
**What is now done:** `/api/system/data-health` and a dashboard panel report the
dominance collector, backups, and the CFT bridge session. A component the
backend cannot read reports `unavailable`, never `healthy`, so silence is never
mistaken for health. The collector also self-reports density over the last hour
rather than lifetime, so a recent death cannot hide behind a good long-run
average.
**What remains:** all of it is PULL. You have to open the dashboard. If nobody
looks for three days and the collector died on day one, three days of
dominance history are still gone — and that data cannot be backfilled.
**Why it was not finished:** pushing a notification needs a destination —
email (SMTP is a dependency but unconfigured), Telegram, a webhook. That is a
choice about where you want to be interrupted, not a code decision.
**Fix:** pick a channel, then alert on `data-health.ok == false` and on repeated
bridge failures. The detection already exists; only delivery is missing.

### E4. The economic calendar is dead — no FINNHUB_API_KEY
**Found in:** Phase 1 audit
**What it is:** `/api/calendar/today` returns 503 with
"FINNHUB_API_KEY not configured". MorningBriefingPage handles it honestly and
shows the error rather than pretending, so nothing is misleading — the feature
simply does not work.
**Why it matters:** only that a page of the app is permanently non-functional.
**Fix:** set FINNHUB_API_KEY on the api service, or remove the calendar from the
Morning Briefing so the page stops advertising something unavailable.


### B3. Deploys are identifiable but not reproducible
**Found in:** I6. Narrowed after B3/I6 — the "nobody can tell" half is fixed and
deployed: both containers record the resolved SHA and `/api/system/version`
serves it. Verified in production on `9a383d907`, api and web matching.
**What remains:** `GIT_REF` defaults to `main`, so recreating a container
tomorrow gets a different commit. The deploy is now honest about this
(`pinned: false`) rather than silently floating, but honest is not the same as
reproducible.
**Why it matters:** a rollback still means finding the previous SHA by hand, and
recreating one container and not the other can still put the two halves on
different code — it is now *detectable* rather than prevented.
**Fix:** set `GIT_REF` to a full 40-char SHA in the VPS compose as part of
releasing, so a deploy is a deliberate act. Fetch-by-SHA and rollback to an
older SHA are both verified working against GitHub.

---

## C. Drift — the repo and the server disagree

*Empty as of 2026-08-04.* All four entries here (C1 the api's inline pip list,
C2 `--no-frozen-lockfile`, C3 the hand-copied collector, C4 no way to detect any
of it) are closed, and `scripts/check_deploy_drift.py` reports all seven
deployed services matching their committed description.

The category is kept rather than deleted because it will come back — every entry
above appeared the same way, by someone editing the server without the repo.
Run the check after a deploy; anything it reports belongs here.

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

### D2. The site is still plain HTTP — blocked on a DNS record
**Found in:** I10; **token half done 2026-08-04**
**Done:** both secrets rotated — the API token and the CFT bridge token, the
latter because it leaked into a chat transcript through an unredacted diff. The
old API token is confirmed revoked (401).
**Still open:** traffic is unencrypted, so the bearer token crosses the network
readable on every request.
**What blocks it:** a certificate needs a hostname. The app is reached at
`http://31.97.183.142:8095`, and Let's Encrypt will not issue for a bare IP.
Everything else is already in place — the host runs nginx with certbot and
serves ~8 domains this way (`aasp-mvp.aminereg.com`, `app.harbyx.com`,
`cal.evidenss.ai` …), so this is one vhost away once a name exists.
**What is needed from you:** point a hostname (e.g. `tradingai.aminereg.com`) at
`31.97.183.142` with an A record. Then it is one nginx site plus
`certbot --nginx -d <host>`, and the app moves to https with the token no longer
travelling in clear.
**Interim:** the token is fresh and single-use-by-you; the exposure is passive
network observation between you and the VPS.

### D7. One shared, non-expiring token is the entire auth model
**Found in:** D2 follow-up (asked whether the token ever changes — it does not)
**What it is:** `API_AUTH_TOKEN` is a static string in the VPS compose file,
read at container start. It has no expiry and no rotation schedule, and it
survives restarts, redeploys and recreates. It changes only when a human edits
that file.
**Why it matters:** three separate consequences, none urgent on a small trusted
team, all of which get worse the moment real money is involved.
  * A leak is permanent until someone notices and rotates by hand. There is no
    backstop — which is exactly why the D2 rotation had to be done manually.
  * It is one token for every person, not a login. There is no way to revoke one
    person's access; rotating locks everyone out and everyone must re-fetch.
  * Nothing is attributable. Every action through the dashboard is "whoever held
    the token", so the audit log cannot answer who placed an order.
**Why it is fine for now:** the platform places no real orders (the CFT bridge
still reports `trading_enabled: false`) and the team is three people.
**Fix when it stops being fine:** per-user credentials with an expiry, so the
audit log names a person and access can be withdrawn individually. Worth doing
before the bridge write-guard is ever unlocked, not after.


### D3. Nothing stops a broken merge — BLOCKED ON ADMIN ACCESS
**Found in:** I2 (CI)
**What it is:** CI runs on every push, but `main` has no branch protection.
**Why it matters:** a red build can be merged anyway; the robot reports and is
ignored.
**State:** the fix is written and tested as far as it can be —
`scripts/enable_branch_protection.sh`. It verifies the four required check names
against a real workflow run before applying, because a required check that no job
reports makes `main` permanently unmergeable with no visible cause.
**Blocked on:** the `Docz2868` token has `push`, not `admin`, and this endpoint
needs admin. GitHub reports that as `404 Not Found`, not `403`. Someone with the
Admin role on `Amineregayeg/tradingai` must run the script.
**Note before running it:** required checks apply to direct pushes too, so
`git push origin main` starts being rejected and all work moves to PRs. That is
intended, and it is the whole cost.

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

### F8. The local dev environment runs node 24, production runs node 20
**Found in:** B7
**What it is:** `scripts/dev_env.sh` uses whatever node is installed. This box
has v24.16.0; CI and the `web` container pin node 20.
**Why it matters:** vitest and `tsc` are unaffected in practice, but a local
`pnpm build` succeeding is NOT evidence the production build works — a
node-version-sensitive build failure would only appear in CI. DEVELOPING.md says
so explicitly, so the risk is someone trusting a local build anyway.
**Fix:** install node 20 (nvm/fnm) for parity, or leave it and keep treating CI
as the authority on `pnpm build`. Low impact either way.

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
