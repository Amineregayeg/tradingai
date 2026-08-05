# Manual acceptance test

A walkthrough you can run yourself, in a browser, in about 25 minutes. It is written
against the three things you asked for at the start:

1. the dashboard shows **real** data,
2. **simulations can be run** on it,
3. the platform is **connected** to the accounts and platforms we will trade on.

Each step says what to click, what you should see, and — where it matters — **why that
particular observation is the proof**. Several steps are deliberately negative tests: they
ask you to break something and check the platform *says so* instead of quietly showing a
zero. That is the difference between a dashboard that works and a dashboard you can trust.

> **Read the "Expected" line before deciding something is broken.** A few panels are
> legitimately empty today, and they are listed in the last section with the reason and the
> issue number. Anything empty that is *not* in that list is a real finding.

---

## 0. Before you start

| | |
|---|---|
| URL | http://31.97.183.142:8095 |
| Token | the value of `API_AUTH_TOKEN` in `/docker/tradingai/docker-compose.yml` on the VPS |
| Deployed commit | check it yourself — step 1.1 |

Use a normal browser window, not private mode: the token is kept in `localStorage` and you
will want it to survive a reload (step 4.2 depends on that).

---

## 1. Is it the software we think it is?

### 1.1 The running build identifies itself
Open http://31.97.183.142:8095/api/system/version in a tab.

**Expected:** JSON with a full 40-character `commit`, and `known: true`.

**Why it matters:** before this, every container reported version `0.1.0` forever. If
`known` were `false` you would be looking at a server that cannot tell you what code it is
running, and nothing below this line would be worth testing.

**Compare it** to the newest commit in the repo (`git log -1 --format=%H`). If they differ,
you are testing an older build — decide whether that is what you want before continuing.

### 1.2 The infrastructure is actually up
Open http://31.97.183.142:8095/api/system/health (no token needed).

**Expected:** `status: "ok"`, and `db`, `redis` both `"ok"`, and under `brokers`,
`cryptofundtrader: "connected"`.

**Why it matters:** this is one call that touches the database, the cache and the live
broker session. If it is green, every failure you find later is in the application, not in
the plumbing — which makes the rest of this document much faster to work through.

---

## 2. Does the dashboard show real data?

### 2.1 Log in
Go to http://31.97.183.142:8095, paste the token, press Enter.

**Expected:** the dashboard renders. No redirect loop, no flash of an error.

### 2.2 The price is a real, moving price
On the dashboard, find the BTC price and the chart.

**Expected:** a price close to what Binance/TradingView shows right now (within a few
dollars), and a chart with candles running up to the current hour.

**Do this:** leave the tab open for two or three minutes. The price should change.

**Why it matters:** a static number is the classic symptom of a dashboard rendering a
cached constant. If it moves, the WebSocket feed is live.

### 2.3 The account figures are the real account
Go to **Settings → Brokers** (or the account panel on the dashboard).

**Expected:** two accounts.
* **cryptofundtrader** — balance around **$5,090**, `reachable: true`.
* **paper** — balance $50,000, marked as a simulation.

**Now verify it against the source of truth:** open CryptoFundTrader's own dashboard in
another tab and compare the balance. They should match.

**Why it matters:** this is the single most important number on the platform, and it is the
one that was previously invented. If our figure and CFT's figure agree, the read path to
the prop firm is genuinely connected — not mocked.

### 2.4 The performance report does not lie about what it is
Go to **Report** (`/report`).

**Expected:** either real closed-trade statistics, or an explicit banner saying the rows are
**backtest replay** — never backtest rows presented as live performance. If there is
nothing to measure, it should say so rather than print `0.0%` win rate.

**Why it matters:** the report used to relabel replayed backtest rows as live results. A
performance page that flatters itself is worse than no performance page.

---

## 3. Can simulations be run?

### 3.1 The engine is running and thinking
Go to **Engine** (`/engine`).

**Expected:** status **running**, mode **PAPER**, symbols BTC/USD and ETH/USD, and an
activity feed with entries roughly on the hour, e.g.

> `ETH/USD 1H bar closed — 1 FVG candidate(s), none valid — mostly: wrong direction for the daily bias (1)`

**Why it matters:** most of the time a strategy engine correctly does *nothing*, and a
silent engine is indistinguishable from a dead one. Those lines are the engine explaining
its abstentions — they are the evidence it is awake.

### 3.2 A decision can be opened and read
Click into a decision record.

**Expected:** the reasons list, each gate marked PASS/FAIL with the actual values, plus an
`inputs_hash` and a `code_path_hash`.

**Why it matters:** the two hashes are what make a decision reproducible. Given the same
inputs and the same code, you can prove the same decision comes out — which is the only way
to tell a strategy bug from a data bug later.

### 3.3 Configure and start a fresh run
On the Engine page, stop the run, change something visible (risk %, or drop to one symbol),
and start a new run.

**Expected:** the new configuration is what the status shows afterwards — not the old one.

### 3.4 Reset is non-destructive
Reset to a clean run, then open the **run history** panel.

**Expected:** the previous run is still listed, with its trade count and P&L intact.

**Why it matters:** this is the property that makes experimentation safe. If reset deleted
history, every test you run would cost you the evidence from the last one.

### 3.5 Restart survival
Note the balance and closed-trade count. Then, on the VPS:

```
docker restart tradingai-api-1
```

Wait ~30 seconds and reload the Engine page.

**Expected:** the same balance, the same closed-trade count, the run still active.

**Why it matters:** figures held only in memory look perfect until the first restart. This
proves they are in the database.

---

## 4. Does it fail honestly?

These are the tests worth doing slowly. Everything above tells you the platform works when
the world cooperates; this section is about what you see when it doesn't.

### 4.1 A dead backend produces an error, not an empty dashboard
On the VPS: `docker stop tradingai-api-1`. Reload the dashboard.

**Expected:** a visible failure message with a retry — **not** panels showing "0 trades",
"$0.00", or an empty chart.

Then `docker start tradingai-api-1` and press retry. The page should recover without a
manual reload.

**Why it matters:** an outage that renders as zeroes is the most dangerous failure this
platform can have, because you would read those zeroes as facts about your account. *(This
behaviour ships in commit `1a2619a`; if the deployed build from step 1.1 is older, this test
will fail for that reason and not because the fix is wrong.)*

### 4.2 A bad token is rejected and asks again
Open the browser console and run `localStorage.setItem('token','nonsense')`, then reload.

**Expected:** you are returned to the login screen. Enter the real token and you are back in.

### 4.3 A failed action says so
Trigger an action that cannot succeed — e.g. start the engine while it is already running,
or save an invalid setting.

**Expected:** an inline error explaining the refusal. Nothing should appear to succeed
silently. *(Ships in `b95bcea` — same deployed-build caveat as 4.1.)*

### 4.4 The safety interlocks are still set
Check the broker panel: CryptoFundTrader should show **observe-only**, with trading
**disabled**.

**Expected:** exactly that. The platform can read the prop-firm account but cannot place an
order on it.

**Why it matters:** this is the deliberate state. Two independent flags have to be turned on
before real money can move, and neither is on. Nothing in this test document can cause a
trade on your funded account.

---

## 5. Legitimately empty today — do not report these

| What you'll see | Why | Issue |
|---|---|---|
| **Prop Firm** page has no rows | no prop-firm account is registered; the engine runs in `PAPER`, not prop-firm `sim` mode | F6 |
| Economic calendar / news panel empty | no `FINNHUB_API_KEY` is set, so the calendar has no source | E4 |
| Site is `http://`, browser shows "not secure" | HTTPS is blocked on a DNS A record only you can create | D2 |
| Chart prices differ slightly from CryptoFundTrader's | we price from Binance spot; the strategy is written for perpetuals — a known and measured gap | A3 |
| Some report rows tagged "backtest replay" | 245 pre-fix rows still in the database, deliberately labelled rather than deleted | F2 |

Everything else that is blank, zero, or stale is a finding. Write down **what you clicked**
and **what you saw** — that is enough for me to reproduce it.
