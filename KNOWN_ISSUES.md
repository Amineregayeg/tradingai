# Known issues — open problems register

Problems found while building, **not yet fixed**. Solved issues are not listed
(they are in git history). Each entry says what it is, where it came from, and
what it could break.

Ordered by what would hurt most, not by how hard it is to fix.

Last updated: 2026-08-12 (T-0003: A11 and B18 fixed and deleted; B21, B22, B23, B24 found; B20 made standalone; B15 annotated)

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

### A10. The engine does not trade the Magic Strategy — it trades the pre-contract ICT strategy, and one of its gates is explicitly forbidden
**Found in:** conformance audit of the live path against `RULE_REGISTRY.json` v1.2.0,
2026-08-08, asked as "is the platform trading the delivered strategies?"
**What it is:** the live loop's only entry decision is
`crypto_loop._tick_symbol` → `strategy_step.evaluate_latest_bar_traced`. That function
cites **zero** rule ids. It is the v1 ICT edge (daily-BOS bias → LTF BOS → FVG retrace),
written before the package arrived and unchanged since.

The contract work that exists is real but **not connected to anything that trades**:

| Built | Wired into the live path |
|---|---|
| `app/services/rules/` — 33 of 117 rules (GATE-023, PRIM-001…006, and M4's graders) | no — only tests and `check_rule_coverage.py` import it |
| `app/services/telemetry/` — contract records, validation, append-only store | no — the loop writes `decision_records`, not the contract's three record types |

So **33/117 rules implemented, 0/117 evaluated on any trade**, and 32/91 HARD_GATEs
implemented but 0 evaluated.

M3 and M4 both landed on 2026-08-08 — the primitive layer (PRIM-002/003/004/006) and then
the graders (GRADE-001…009, GATE-001/002/003/004/005/006/007/008/009/048). Coverage moved
3 → 7 → 33. **Neither narrows this entry**, and the gap between the two numbers above is now
the whole problem: a grader nothing calls changes no decision, and building more of them
does not close a gap that is architectural rather than volumetric. See
`MAGIC_STRATEGY_EXECUTION_PLAN.md` — no milestone in the original M0–M8 map ever switches
the live loop over.

**Where the running engine actively contradicts a HARD_GATE:**

* **GATE-037** — ~~the premium/discount entry filter~~ **CLOSED 2026-08-09.** The
  filter is deleted from `strategy_step.py` and `backtest/engine.py`, the equilibrium
  midpoint is no longer computed on the decision path, and `use_premium_discount` is gone
  from the feedback loop's tunable knobs. HG-16 now exists as
  `tests/integration/test_conformance_gate_037.py` — the first of the 78 conformance
  assertions to be a test. It checks the emitted records AND the source of the decision
  path, because a filter that simply never fired on the sampled data would pass the first
  check alone while waiting for the market that trips it.
* **GATE-032 / GRADE-017** — risk is the 9-cell `box_grade × disturbance` lookup
  (1.50/0.75/0 · 1.25/0.50/0 · 1.00/0.25/0). We size every trade at a flat 1% —
  `live/fixed_config.py` pre-registers `RISK_PCT` and deliberately makes it not a knob.
  Neither grader exists, so the lookup has no inputs even if it were wired.
* **GATE-001 / GATE-002** — heavy-disturbance hard skip and the disturbance classifier.
  Not implemented; nothing blocks a trade on correlate disagreement.
* **GATE-008** — roster is `BTCUSDT.P · ETHUSDT.P · TOTAL · USDT.D`. We trade `BTC/USD`
  and `ETH/USD` off Binance **spot**, and read no correlate panel at decision time (this is
  the A3 axis, restated as a rule violation).
* **GATE-017 / GATE-019** — 1H is **analysis only**; ruled execution timeframes are
  30M/15M/5M. The loop's default `entry_tf` is `1H`, so every entry it has ever taken was
  triggered from an analysis-only series.
* **EXIT-001 / GATE-022** — 70% at 2R, 30% runner, everything flat at 19:00 New York.
  The live signal carries a single TP at `rr_partial`-R and there is no session close;
  the 70/30 machinery exists only inside the backtester.
* **GATE-025 / 026 / 027** — five-anchor stop ladder, 2R floor, no-trade if nothing
  clears 2R. We use one anchor (swing or FVG edge, ATR-buffered) and never test an RR floor.

**Why it matters:** the platform is producing paper trades, a win rate and an equity
curve from a strategy that is not the one it was given, while the repo now contains a rule
registry, a telemetry store and a coverage script — the furniture of conformance. Anyone
reading the engine page, or `check_rule_coverage.py`'s "PASSED", can reasonably conclude
the delivered strategy is what is being measured. It is not, and no runtime signal says so:
the loop stamps `engine_version: "ict-v2-lookahead-fixed"` and nothing anywhere refuses to
trade for want of a rule.

**Also note:** `backtest/engine.py:378` applies a filter it names **"Magic Alignment
(first-order)"** — agreement with BTC's own daily bias. That is invented machinery under a
contract name; the real GATE-008/GATE-002 alignment is a four-panel roster with a
disturbance count. It is backtest-only and never reaches the live path, but the name will
be believed.

**Fix:** this is M3–M8 of `MAGIC_STRATEGY_INTEGRATION.md`, not a patch — 88 further hard
gates, and the graders in §2.4 that nothing can test automatically. Two things are worth
doing before any of it: ~~(1) drop the GATE-037 premium/discount filter~~ — done,
2026-08-09; (2) make the live path emit
contract telemetry with `deciding_rule_id`, so "which rule stopped this trade" has an
answer other than "none of them". Until the roster, the disturbance grader and the risk
matrix exist, the engine cannot cite a rule for its position size, which is readiness
gate 5's floor.

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
**SECOND AXIS, added by the Magic Strategy M0 work:** the strategy's roster names
`BTCUSDT.P`, the Binance PERPETUAL, and everything we have ever measured — the
corrected baseline, the CFT comparison above, every backtest — was computed on
Binance SPOT. Measured over 500 matched 1H bars, the perp extends beyond the spot
bar on **497 of 500 (99%)**, with a median bar-range difference of **2.89%** of
the bar's own range — two orders of magnitude larger than the CFT divergence in
the table above.
**Why it matters:** adopting the perpetual (see `MAGIC_STRATEGY_M0_CONTRACT.md`
§1.1) is correct for fidelity to the documented strategy, but it means the
existing baseline and `scripts/baseline/reference_trades.csv` describe a
different series from the one the engine will run on. They do not carry over.
**Fix:** re-run the corrected baseline on perpetual bars before comparing any new
result to it, and mark the spot-era baseline as belonging to a different venue
rather than deleting it.

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
**The engine page can no longer switch it.** With the settings frozen, the
price source is `fixed_config.PRICE_SOURCE` and changing it is a code change
plus a deploy. That is the deliberate cost of one configuration for every run.
**Sharpened now that the prop-firm simulator is the default:** the challenge
simulation runs its rules — $250 daily loss, $500 drawdown on a $5,000 account —
against decisions taken on BINANCE bars. A simulated breach is therefore a
statement about what would have happened on Binance prices, not certainly about
what CFT would have done. The gap is small and measured (table in A3) but it is
largest exactly where an entry is marginal.
**Fix:** set `PRICE_SOURCE = "cft"` in `backend/app/services/live/fixed_config.py`
and redeploy, once the browser-bridge dependency and the ~125-day history limit
are acceptable.

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

### B11. The disturbance grader cannot be run on real data — TOTAL and USDT.D have no credible execution-timeframe bars
**Found in:** M4 (implementing GATE-002/007/008/048), 2026-08-08
**What it is:** GATE-007 requires the layout to be confirmed at the **execution** timeframe,
and GATE-017 makes 1H analysis-only — so the four panels must be read on 30M, 15M or 5M. Two
of those four panels are CryptoCap indices we synthesise ourselves, and
`collect_dominance.py` samples at **60 s**:

| Execution TF | samples per bar | credible? |
|---|---|---|
| 30M | 30 | yes |
| 15M | 15 | marginal |
| 5M | 5 | no — see F1, the same defect one timeframe down |

So `DisturbanceClassifier` is implemented and tested, and on live data today it can only be
fed at 30M without inventing structure. Its inputs for TOTAL and USDT.D are `CorrelateRead`s
whose `observed_order_flow` and `expected_break_confirmed` come from structure detection on
those bars — and structure on a 5-observation bar is noise with an OHLC shape.
**Why it matters:** this is not a missing feature, it is the difference between a grader that
runs and one that produces a disturbance grade from fabricated geometry. The grade keys the
risk matrix, so a bad TOTAL read does not produce a slightly wrong alignment — it moves the
matrix cell and therefore the position size, or trips GATE-001's hard skip on a tradable
setup. History is *not* the constraint here: ~12 days at 15M is ~1,150 bars, plenty for LTF
structure. Sampling rate is.
**Verified, because the collector's own docstring reads the other way:** it warns that
CoinGecko `/global` refreshes only every ~602 s and that polling it per minute yields "nine
identical samples and then a jump — FABRICATED STRUCTURE". That is a warning about a
*different* construction. This collector does not take dominance from `/global`: it computes
market cap = price × supply, where **supplies** come from CoinGecko once a day (slow by
nature, fine) and **prices** come from Binance `/ticker/price`, real-time. So the intraday
resolution is bounded by our poll rate and nothing upstream — raising the rate buys genuine
structure, not duplicates. Anyone reading only the docstring would conclude the opposite.
**Both halves of the fix have landed IN PRODUCTION as of 2026-08-10; the entry stays open
because the DATA has not caught up.**
1. **Refuse rather than fabricate — done** (`ccdd4a4`). A bar assembled from too few samples
   is not a low-quality bar, it is not a bar. `CorrelateRead.bar_sample_count` carries the
   observation count, `LayoutReadability` fails GATE-007 when a panel is thinner than the
   declared minimum, and GATE-036 turns that into a STAND_ASIDE that cites a real rule. This
   half is what makes *any* execution-timeframe choice safe, and it is independent of which
   one is chosen.
2. **Raise the sampling rate — reached production 2026-08-10 at `--loop 10`, not 15** (T-0001).

   **This entry said "done" while it was not, and that is the more useful half of the
   story.** `--loop 15` was committed on 2026-08-09 (`56518f8`) and this text recorded the
   sampling-rate fix as complete the same day. The server was never updated: its own
   compose said `--loop 60`, and `tradingai-dominance-collector-1` ran six days on the old
   cadence — the container was created 2026-08-04, so it predates the commit by five days
   and outlived it by one. Those are two different clocks and conflating them is easy:
   the container's six days is not six days of a false register entry.
   `check_deploy_drift.py` reported it the whole time and exited 1, and nobody read the
   exit code. The cause was structural, not careless — the collector is compose project
   `tradingai-dominance` under `/home/deploy/`, outside every documented deploy path, and
   a grep for "dominance" or "collector" across the runbook and the agent prompts returned
   nothing. There was no step to skip. `scripts/deploy_dominance.sh` now exists so there is
   one, and it re-runs the drift check itself rather than announcing success.

   **The cadence is 10 s, not the 15 s this entry used to name.** 15 s was chosen when the
   question was which timeframes clear the minimum at all; it does not survive contact with
   jitter. `MIN_SAMPLES_PER_SYNTHETIC_BAR = 20` and 15 s gives a 5M bar **exactly 20** —
   one missed or late poll lands it on 19 and GATE-007 refuses the panel. There is a
   guaranteed overrun twice a day: `refresh_supplies()` runs inside a normal tick and holds
   a hard `time.sleep(6)` between its two CoinGecko calls, while the cadence controller
   sleeps `max(1.0, interval - elapsed)` and never makes up a deficit.

   | Execution TF | samples @60s | samples @15s | samples @10s |
   |---|---|---|---|
   | 5M | 5 | 20 — zero margin | **30** |
   | 15M | 15 | 60 | **90** |
   | 30M | 30 | 120 | **180** |
   | 1M | 1 | 1 | 6 — still fails, see B16 |

   Cost is 6 Binance requests/minute instead of 1, against limits the collector's own header
   calls generous; supplies are untouched. 10 s is also the floor `collect_dominance.py`
   enforces (`interval = max(10, int(args.loop))`).

**What is still true, and why this is not deleted:** every sample collected before
2026-08-10 18:23 UTC is 60 s apart, so **the existing ~14 days of history remain 30M-only
and always will** — it cannot be backfilled. Measured on the full pre-change series: 4,013
completed 5M bars, median 5 samples each, **0.0% clearing the 20-sample minimum** for TOTAL
and USDT.D alike. The engine refuses to grade those layouts rather than fabricating them,
which is correct and also means a 5M shadow window run over that history stands aside on
every bar. **Close this entry when the collector has run at 10 s for long enough to cover
the intended shadow window** — 20 trading days or 300 evaluations per symbol, whichever is
later (`MAGIC_STRATEGY_EXECUTION_PLAN.md` M9 Stage A) — not when the code merged, and not
now that the deploy has happened. The clock starts 2026-08-10, not 2026-08-09.
**Also note this task did not wire the correlate panels.** `/api/engine/shadow` still shows
every record blocked on GATE-008 with "roster panels TOTAL and USDT.D are unavailable". The
series is now capable of being read; nothing reads it yet.
**Also worth knowing:** the healthcheck's 600 s staleness threshold was left alone. It still
catches a dead collector at either rate, and tightening it to match a 10 s cadence would
trade a real signal for flapping. `COLLECTOR_STALE_MIN`/`COLLECTOR_DOWN_MIN` in
`data_health.py` were left alone for the same reason.

### B9. Four primitive sub-parts need numbers nobody has ruled on — BLOCKED ON THE TRADER
**Found in:** M3 (implementing PRIM-002/003/004/006), 2026-08-08
**What it is:** four documented objects rest on a threshold the corpus never states, so they
are **not detected at all** rather than detected with a guessed number:

| Object | The missing number | Rule |
|---|---|---|
| Parabolic / compressed liquidity | how tight is "very tight" | PRIM-003 class 3 |
| Institutional levels (deep-V extremes) | what makes a V a deep V | PRIM-003 class 4, **TARGET-007 is OPEN** |
| Diagonal / trendline pools | the staircase geometry, drawn by hand throughout | PRIM-003 |
| Liquidity sweep FAIL | how close is "extremely close" without crossing | PRIM-004 (a) |
| Engineered-liquidity build | cluster size, spacing, and candle shrinkage | PRIM-004 |
| Momentum imbalance | how large is "large" | PRIM-002 `is_momentum_imbalance` |

**Why it matters:** these are not cosmetic gaps, they are *destinations*. TARGET-001 picks
the trade's objective out of the pool inventory and GATE-025's 2R floor is measured to it, so
an invented threshold would not produce a slightly different target — it would produce
targets the trader never marked, and every reward-to-risk computed against one would be
fiction that validates perfectly. TARGET-007 says the quiet part outright: V-quality "should
be used as a weight, not as a filter", and the printed 5-tier list must not be transcribed as
an ordering because it contradicts itself at ranks 1–2.
**What we did instead:** PRIM-002's momentum flag and PRIM-004's failed sweep are emitted
only when the caller passes a declared parameter, and are left unset otherwise — the
`fake_msb` precedent from PRIM-005. The other three classes are simply not emitted, and each
implementation declares a `COVERAGE_NOTE` that `check_rule_coverage.py` now prints, so
"PRIM-003 implemented" cannot be read as "PRIM-003 finished".
**How it ends:** these belong on the same list as `OPEN_ITEMS/TRADER_QUESTIONS.md`. None of
them blocks M4 — the graders do not read these classes — so this is a question to batch, not
a gate to wait on.

### B12. Nothing says HOW the execution timeframe is chosen, and the trader varies it
**Found in:** answering "should the timeframe be set or can it vary?", 2026-08-08.
**What it is:** the contract fixes the legal *set* ({30M, 15M, 5M}, GATE-018) and
requires that within one decision every panel uses the SAME timeframe
(GATE-007, GRADE-010, HG-13: `alignment_tf` must equal `signal_tf`). It says
nothing about whether that timeframe may differ from one trade to the next — and
the telemetry schema stamps `signal_tf` on **every** `setup_evaluation`,
`trade_execution` and `scan_census` record, which is only worth doing if it moves.
The trader does move it: 6 bracketed trades on 1M, 2 on 3M.

A search of all 117 rules found no rule governing the choice. It is also **not
among the questions being put to him** — `TRADER_QUESTIONS.md` asks whether 1M/3M
are legal, and answers that from behaviour, but never asks how he picks.
**Why it matters:** if the engine varies the timeframe, the selection rule is ours
and invented, and it sits **upstream of every gate** — box grades, alignment,
stop ladder and therefore risk all read from whichever series we chose. That is
the worst possible place for an undeclared input: nothing downstream can be
audited past it, and a conformance score would be computed over a choice no rule
justifies.
**Fix, in order:** (1) keep it FIXED and declared for the first shadow window, so
the fidelity measurement has one fewer moving part; (2) add "how do you decide
which chart to drop to?" to the trader's question list — it is cheap and currently
missing; (3) only make it variable once there is a ruled or declared selection
rule, stamped on every record like any other declared parameter.

### B13. The telemetry schema cannot say "the layout was never read"
**Found in:** M9 Stage A, 2026-08-09.
**What it is:** `correlates.disturbance_grade` is an enum of `NONE | LIGHT |
HEAVY`. There is no value for *not evaluated*. The shadow engine has no correlate
panels at all (B11), so it must write one of the three, and `NONE` is the only
one that is not an outright claim — but read alone it says "checked, and nothing
was disturbed", which is the opposite of what happened.
**Why it matters:** C-04 is the contract's own principle that silence is not a
pass, and the schema enforces it everywhere else — `rule_evaluation.verdict` has
`NOT_APPLICABLE` and `UNIMPLEMENTABLE` precisely so an unaskable rule cannot be
recorded as a passing one. `disturbance_grade` is the one place that distinction
is unavailable, and it is a grade the risk matrix reads.
**How we handle it meanwhile:** every other field on the record contradicts the
optimistic reading — `layout_size` is 0, `states` is empty, GATE-008 and GATE-002
are `NOT_APPLICABLE` with their reasons, the decision is `STAND_ASIDE` and
`block_reason` is `NO_ALIGNMENT`. A reader who looks at only the one field can
still be misled.
**Fix:** ask Salim to add `NOT_EVALUATED` (or a sibling `layout_readable`
boolean) when he regenerates the schema against registry v1.2.0 — B8 is already
open for that regeneration, so this rides along with it.

### B14. Nothing enforces stopping the engine before a deploy — it is a documented habit, not a guard
**Found in:** setting up the three-agent working loop, 2026-08-10.
**What it is:** recreating the `api` container kills the live engine mid-run.
Positions opened by that run keep existing as rows, but no process will ever
check their stop-loss again — they are not "still open", they are abandoned.
`POST /api/engine/stop` closes them at the current price and ends the run
cleanly, so the correct sequence is stop → deploy → verify → start. That sequence
is written in `agents/PROMPT_EXECUTE.md` and in the deploy runbook. **Nothing in
the code refuses a deploy that skips it.**
**Why it matters now specifically:** Malek granted the Execute agent authority to
deploy unattended (2026-08-10). Until now every deploy had a human at the
keyboard who could notice an open position; from now on some will not. This is
exactly how the ETH LONG of 2026-08-08 06:00 was destroyed twelve hours in — the
only trade the platform had taken at the time.
**What it could break:** a silent loss of a real position, and a run whose
recorded result is wrong in a direction nobody can reconstruct afterwards,
because the trade shows as open forever rather than as closed at a price.
**Fix:** make it structural rather than procedural. Either the api refuses to
shut down cleanly with an open run without closing it (a shutdown hook already
calls `stop()` — verify it survives `--force-recreate`, which is a SIGKILL path,
because a hook that only runs on SIGTERM is not a guard here), or a preflight
script that a deploy must pass. Until then this is a habit, and habits are what
the register exists to distrust.

### B15. The agent message bus goes silently deaf when a session restarts
**Found in:** setting up the three-agent working loop, 2026-08-10.
**What it is:** the three agents wake each other with `SendMessage`, addressed by
the session name recorded in `agents/registry.json` during the HELLO handshake.
Those names (`tradingai-02`, …) are assigned per session and change when a
session is restarted or compacted into a new one. The message file is still
written to the right inbox — that half is durable — but the doorbell goes to a
name that no longer exists.
**What it could break:** the loop stalls with no error anywhere. Execute finishes,
sends WORK, and Review never wakes; Malek sees a task that has been "REVIEWING"
for hours and no indication that anything is wrong. Worse: if the stale name has
since been reassigned, the wake-up goes to an unrelated session working on
something else.
**How we handle it meanwhile:** `bus.py send` warns when the recipient role is
unregistered, and `bus.py tasks` shows each task's state and cycle, so a stalled
task is visible if you look. Re-running the handshake corrects the registry.
**Fix:** have each agent re-run `ListAgents` before sending and refuse to ring a
doorbell whose name is absent from the live peer list — that turns a silent stall
into a loud one, which is the whole difference.

**Note added 2026-08-12: the fix above is written down and we keep doing it by
hand instead.** Three sessions opened T-0003 by re-deriving the peer table
through set arithmetic across each other's `ListAgents` output — because no
session can see its own row, two peer lists are needed to identify either one.
That handshake is a manual substitute for the fix in the paragraph above, which
needs no coordination and cannot go stale. Same shape as B19 and B21: **a habit
that must be performed, standing in for a check that would fail on its own.**

Two corrections to how this entry has been *described* in passing, both wrong and
both tested rather than argued: **bare names DO resolve** — a message addressed to
`tradingai-4c` with no `[ref]` arrived — so "a bare name does not resolve" is not
the mechanism here and never was. The entry above is accurate: names change on
restart, and the doorbell goes to a name that no longer exists. The `[ref]` is
only needed to disambiguate.

### B16. The 1M second shadow run can never have readable correlate panels — a decision collides with a guard
**Found in:** T-0001, raising the collector to `--loop 10`, 2026-08-10.
**What it is:** `MAGIC_STRATEGY_EXECUTION_PLAN.md` §5.4 records Malek's decision of
**5M execution timeframe, with 1M as a second shadow run to compare against it**. At the
new 10 s cadence a 1M bar holds **6 samples** against `MIN_SAMPLES_PER_SYNTHETIC_BAR = 20`.
Clearing 20 on a 1M bar needs a poll every 3 s — and `collect_dominance.py` reads
`interval = max(10, int(args.loop))`, so **the script enforces a 10 s floor**. 3 s is not
merely undesirable, it is unreachable without changing that line, and changing it means 20
Binance requests a minute against a free endpoint.
**Why it matters:** the 1M run will `STAND_ASIDE` on GATE-007 for every single bar, citing
GATE-036, exactly as the 5M run does on the 60 s history today. So the 5M-vs-1M comparison
the decision exists to produce **cannot be produced as specified** — the 1M arm yields no
gradeable layouts at all, not merely worse ones. Reading its output as "1M performs poorly"
would be reading the guard, not the market.
**What it could break, concretely:** M9 Stage A's shadow window is the evidence base for
Stage B, the cutover. If half that window is an arm that structurally cannot grade anything,
the window is smaller than it appears and the comparison it was designed around is absent.
Worse, the 1M records will look like ordinary abstentions — the same `STAND_ASIDE` /
GATE-036 shape a genuine market refusal produces — so nothing in the telemetry distinguishes
"the layout was unreadable by construction" from "the layout was read and refused".
**Not fixed here:** T-0001 changed the collector's cadence, not the decision. This is for
Malek: either drop the 1M arm, or accept it as a null arm and say so in the record, or
re-open the 3 s question with its cost attached. **Settle it before Stage A's window is
treated as meaningful**, because afterwards it is 20 days of data with a hole in it.

### B17. Production's collector diagnostics are stale-by-design after T-0001, and one of them is now blind
**Found in:** T-0001, 2026-08-10.
**What it is:** two readouts keep a once-per-minute denominator in production even though
both are fixed in this repo, because neither ships with the collector's compose file:

* **`/api/system/data-health` → `recent_density_pct`.** The fix is in
  `data_health.py` (`EXPECTED_POLL_SECONDS`), but `data_health.py` runs in the **api**
  container and this task deliberately did not redeploy the api — recreating it kills the
  live engine mid-run and abandons open positions (B14). Production still computes
  `min(100.0, 100.0 * recent / 60.0)`.
* **`collect_dominance.py --status`.** The fix is **on `main` as of 2026-08-10**, but the
  collector container `git clone`s `backend/scripts/` from GitHub main **at startup** and
  is guarded by an `/app/.ready` flag, so the running container still holds the code it
  cloned when it was recreated at 18:23 UTC. The fix is armed, not applied: it lands at the
  collector's **next recreate** (`./scripts/deploy_dominance.sh --force`), and until then
  `--status` in production reports density against a per-minute expectation and prints
  ~600%. Nobody needs to recreate the collector for this alone — a needless recreate puts a
  real gap in a series that cannot be backfilled, and this is a CLI readout, not the health
  signal. It will correct itself the next time the collector is deployed for any reason.

**Why it matters — the density figure is not merely wrong, it is saturated.** At 10 s a
healthy hour is ~360 samples; against a 60-sample expectation that is 600%, clamped to
exactly **100.0**. A collector degrading all the way back to 60 samples/hour — a sixfold
loss on data that cannot be backfilled — still reads **100.0% healthy**. Measured either
side of the cadence change, nine minutes apart:

| | 18:26:13Z (60 s) | 18:35:21Z (10 s) |
|---|---|---|
| `recent_density_pct` | 100.0 | 100.0 |
| `samples_in_tail` | 971 | 971 |

Two identical readouts across a 6× change in the underlying rate.
**And there is no second field that would reveal it.** `samples_in_tail` looks like a raw
count and is not a signal: `_read_tail` seeks `size - TAIL_BYTES` and parses a fixed 96 KiB
window, so it returns ~970 rows at any cadence and any level of degradation. Do not record
this as a weak signal; the panel has **none**.
**What still works, so the blind band is bounded:** `status` is driven by `age_min` against
`COLLECTOR_STALE_MIN = 5.0` and `COLLECTOR_DOWN_MIN = 30.0`, not by density. A **dead**
collector is still caught within five minutes at either cadence. What is invisible is
**partial** degradation between 1× and 6× — which is precisely the range a struggling
Binance endpoint or a slow container would produce.
**The replacement check until it is fixed** — no ssh, no token, over the public CSV:

```
curl -s http://31.97.183.142:8097/dominance_intraday_raw.csv | tail -400 | \
  python3 -c "import sys,csv,datetime as dt,statistics; \
r=[dt.datetime.fromisoformat(l.split(',')[0]) for l in sys.stdin if l[:2]=='20']; \
print('median gap', statistics.median((b-a).total_seconds() for a,b in zip(r,r[1:])))"
```

**Fix:** an api deploy carries `data_health.py`; the merge to main is **done**, so the next
collector recreate carries `--status`. The api deploy is the one with a cost — it requires
stopping the live run first (B14), so it should ride along with the next api change rather
than being done for this alone. **Close this before M9 Stage A's shadow window is treated as
meaningful**, not merely "at the next api deploy": the window is exactly when a silently
degrading collector would do the most damage and be least visible.

### B19. Nothing checks a `file:line` citation, and this register is made of them
**Found in:** 2026-08-12. Two agents independently audited their own citations
after one off-by-one surfaced: **12 wrong out of ~40 checked** — 7 in the first
two commits of a register entry, 5 in T-0003's pre-review.
**What it is:** every entry here, and every work report and plan, points at code
by `file:line`. Nothing verifies those, and they rot or arrive wrong silently.
Four distinct mechanisms were observed in a single session:

| mechanism | example |
|---|---|
| wrong cwd | `scripts/verify_guards.sh` is `backend/scripts/…` from the root; the bare form is correct only inside `backend/`, and CI uses it because the job sets `working-directory: backend` |
| wrong referent | `:71` (array opens) vs `:75` (the line meant) — both defensible, neither stated |
| off-by-one from a range read | `sed -n '78,100p'` where **line 78 is blank**: the first *visible* line reads as 78, and every citation from that read shifts by one |
| inheritance through a message | a number republished by an agent that verified the surrounding code but not the number — it gains apparent confirmation from each repetition |

**The split is mechanical, not a matter of care** — but it runs in one direction
only, and an earlier draft of this entry overstated it. What both audits show is
that **every wrong citation came from a range read or from another agent's
message, and `grep -n` never produced a wrong one.** The converse does not hold:
a third audit, of two further entries' citations, found seven correct — four from
`grep -n`, and **three from range reads that happened to start on a non-blank
line**. So a range read is not reliably wrong; it is *unverifiable without
recounting*, which is worse, because it produces right answers often enough to
feel safe. "I checked them and they were fine" is not evidence the method works.
This is not fixable by looking harder. It is fixed by reading from output that
emits the line number instead of output that requires you to infer it.

**Why it matters:** a wrong citation does not fail, it misleads — and it misleads
the reader who is *acting* on the entry, six weeks later, with no cheap way to
tell. It also degrades the register's whole purpose: entries here exist to be
trusted without re-derivation. Worst is the confidence marker — both audits found
wrong numbers sitting under phrases like "checked, not reasoned" and "things I
verified, so nobody re-verifies them". **The signal of confidence and the act of
checking had become the same gesture**, so the sentence that should have carried
a check instead discouraged one.

**How we handle it meanwhile:** cite from `grep -n`, never from a counted range;
never republish a line number from another agent's message without re-deriving
it; say which referent a number means when a block has several.

**Fix:** a linter that resolves every `file:line` in `KNOWN_ISSUES.md`,
`agents/tasks/**` and the runbooks against the repo and fails when the target
does not exist or no longer contains what the entry claims. It would have caught
all 12 in about a second. Note the property that matters: it **fails**, rather
than being a review step someone performs — the same distinction as B15's
unrun fix. A sweep performed once by a diligent reader rots exactly like the
citations it audits. Pairs naturally with **B21**, which is the same disease in
the register's numbers rather than its line references.

### B20. CI on `main` is advisory — nothing blocks on a red check and nothing reports one
**Found in:** 2026-08-12, chasing why a job configured to block had not blocked.
**What it is:** `main` has **no branch protection and no rulesets**. Verified
against the GitHub API:

```
GET /repos/Amineregayeg/tradingai/branches/main/protection  -> 404 Not Found
GET /repos/Amineregayeg/tradingai/branches/main             -> "protected": false
GET /repos/Amineregayeg/tradingai/rulesets                  -> 0 rulesets
```

So every CI job on this repo is advisory. `Tier 0.2 - lookahead guards must bite`
carries no `continue-on-error` and fails the job on exit 2 — it is written to
block, and there is nothing for it to block. Nothing rejects a push to a red
`main`, and nothing requires a PR, a review or a green check to get there.

**Why it matters — and this is the part that already cost three days.** Nothing
*routes* a red `main` to a human, and nothing *stops* one either. CI is a machine
that observes correctly, reports honestly to a page nobody opens, and is wired to
no consequence.

That is not hypothetical. It has already happened, and the incident is recorded
here because the entry that used to hold it (A11) was deleted when its tests were
fixed on 2026-08-12:

```
2026-08-10T19:56Z  failure  946ca1c   <- was main, and what production ran
2026-08-10T17:23Z  failure  3402adb
2026-08-09T21:19Z  failure  b3264d6
2026-08-09T18:43Z  failure  7f51836
2026-08-08T21:55Z  success  8d30278   <- last green
```

Two checks were red across those four commits. One of them,
`Tier 0.2 - lookahead guards must bite`, meant **the project's mutation-testing
harness ran zero probes from 2026-08-09 to 2026-08-12** — all eight, including
five with no connection to the test that was failing. Nobody noticed for three
days, across a full task and a production deploy, and `946ca1c` reached
production by ordinary `git push`. **Nothing was overridden, because there was
nothing to override.**

The reason it went unnoticed is the reason to keep this entry: a script exiting
non-zero with a loud, accurate error reads as a broken environment rather than as
a disabled guard, and a red check that has been red for a while stops looking
like news. Compare the 2026-08-04 incident (`bd0e2a0`), where the same script
printed `TIER 0.2 PASSED` having run no tests: that failure was **invisible**, as
it never reached CI. This one was **visible and ignored**, which is worse.

**What it could break, concretely:** the guarantee everyone in this project has
been reasoning from — that `main` is releasable — is not enforced anywhere. A
lookahead regression reintroduced tomorrow would turn `Tier 0.2` red, and that
red would neither stop the merge nor reach anyone. Note also that runtime
containers `git clone` `main` at startup, so an unreleasable `main` is not a
staging concern: it is what the next container recreate ships.

**How we handle it meanwhile:** check CI by hand after every push to `main` —
`gh`-less, so via the API. This is a habit, and habits are what B15, B19 and this
entry all say do not hold.

**Fix:** require the four CI checks on `main` via a ruleset, and route a red
`main` somewhere a human reads. The first is **a decision, not a task** — it
changes how everyone lands code, and it is Malek's call, not an agent's.
**Recording this is not a recommendation to switch it on today.**

**One live precondition, stated as a check rather than a claim.** Turning
protection on while `main` is red would block every merge until it is green, so
the order matters. Do not take this paragraph's word for the current state —
**resolve it**:

```
gh-less:  curl -sH "Authorization: token $TOKEN" \
            .../repos/Amineregayeg/tradingai/commits/main/check-runs
```

All four checks must read `success`. Last measured 2026-08-12 at `a4f3b08`:
`Backend suite` **failure**, `Tier 0.2` **failure** — red, with the fix for both
sitting on an unmerged branch. An earlier draft of this entry asserted `main` was
already green; it was not, and that would have told Malek the blocker was gone
while it was still there. It would also have been the fifth stale figure of the
day, one paragraph above B21, which exists because of the other four.

**This entry outlives the incident that produced it, deliberately.** The red test
was incidental — the next one will be a different test, and the routing gap will
be identical. Do not close this because the four runs above went green.

### B21. The register quotes numbers the code owns, and nothing checks them
**Found in:** T-0003, 2026-08-12, after four stale figures surfaced from four
directions inside one hour.
**What it is:** entries here state figures that were true when written — suite
counts, poll cadences, thresholds, dates — and nothing re-reads them when a later
task makes them false. Four instances from one task:

* the A11 baseline `838 passed / 2 failed`, invalidated by T-0001 adding twelve
  tests (found by Review; the entry's own headline and its correction paragraph
  then disagreed with each other about the same number);
* **F1**'s "at 60 s polling a 1m bar holds one observation" and "drop `--loop` to
  ~15 s", both invalidated when the collector went to 10 s on 2026-08-10 — the
  advice became a *slowdown* while the entry's conclusion stayed correct;
* section **C**'s "Empty as of 2026-08-04", which reads as continuous drift-free
  state through a period when the drift check was in fact exiting 1;
* `DEVELOPING.md` was updated correctly for one of these and the register was
  not, so two documents disagreed about the same figure.

**Why it matters more here than in a doc:** `KNOWN_ISSUES.md` is where every
prompt's Step 4 sends an agent for its baseline. A stale figure here is
*load-bearing* — an agent that trusts `838` concludes that T-0001's twelve new
tests are twelve new failures, and spends its cycle chasing them. F1 shows the
worse shape: **right for the wrong reason**, so nobody rechecks it and every
detail a reader would act on is false.

**How we handle it meanwhile:** date-stamp a figure rather than overwriting it,
so a reader can order two numbers; and when a task invalidates an entry, correct
that entry in the same commit.

**Fix:** a check that reads both sides and fails when they disagree — the
register's quoted constants against the code that owns them
(`MIN_SAMPLES_PER_SYNTHETIC_BAR`, the collector cadence in
`deploy/compose.dominance.yaml`, suite counts, `TAIL_BYTES`). Same property as
B19's linter and B15's unrun fix: it **fails**, rather than being a sweep someone
performs. A sweep rots exactly like the figures it audits.

### B22. One red test disables all eight lookahead probes
**Found in:** T-0003, 2026-08-12 — the mechanism behind the three-day outage in
B20.
**What it is:** `backend/scripts/verify_guards.sh` checks `BASELINE_TESTS` as a
single block (`:148-156`) and refuses to mutate anything if any of them is red.
That refusal is correct and deliberate (`bd0e2a0`): a test that already fails
cannot demonstrate that removing a guard is what broke it. But the granularity is
wrong — the five baseline files back eight probes, so **one red file stops all
eight**, including the FVG probe, the daily-bias probe, both execution probes and
the resolve probe, none of which have anything to do with the file that is red.

That is exactly what happened: two failing dominance tests switched off lookahead
verification for the entire project for three days.

**What it could break:** the blast radius of any red test is the whole harness,
and the failure is silent in the way that matters — the script exits 2 with an
accurate, loud message, which reads as a broken environment rather than as
disabled guards.

**Fix:** baseline only the tests each probe actually uses, so a red dominance test
costs the three dominance probes and leaves the other five running. Deliberately
**not** done in T-0003: it changes the harness's design while that harness is the
instrument verifying the change, which is the wrong order.

### B23. A probe cannot tell that the line it mutates does nothing
**Found in:** T-0003, 2026-08-12. This is how A11 hid for as long as it did.
**What it is:** `probe()` guards two ways a probe can rot — a sed expression that
matches nothing (`:123-131`) and a test path missing from `BASELINE_TESTS`
(`:107-115`). Neither can see the third: **a sed that matches a line which has no
effect.** Probe 5 mutated `bars = bars.dropna(how="all")` for months while that
line dropped zero rows, so the probe guarding against fabricated bars across a
collector outage was pointed at dead code.

**Why it survives T-0003's fix:** the dominance line is live again, but nothing
was added that would detect the next occurrence. It applies to all eight probes.
A probe is only as good as the assumption that its target line does something,
and that assumption is currently unchecked.

**Fix:** no cheap one. The nearest thing is a coverage assertion — require each
mutated line to be executed by the probe's own test — which catches "dead line"
but not "live line with no effect". Worth a plan rather than a ride-along.

### B24. The dominance gap fix is merged but not deployed
**Found in:** T-0003, 2026-08-12.
**What it is:** the fix that stops `DominanceSource` inventing bars across a
collector outage is on `main` and **not on the api**. Runtime containers clone
`main` at startup, so it reaches production only on the next api recreate.

**Why it was not deployed with the fix:** an api recreate requires stopping the
live engine first (**B14** — `--force-recreate` abandons open positions), and
that is a live-run risk taken for a change that currently decides nothing.
Checked rather than assumed (T-0003 criterion 8): **`DominanceSource` has zero
consumers in `backend/app/` or `backend/scripts/`.** Its only non-test
instantiation is inside a docstring example, `fetch_ohlcv_with_samples` has no
call sites at all, `datasets.py` defaults to `BinanceSource`, and
`scripts/verify_baseline.py` reads Binance symbols. So no live decision has ever
consumed a dominance bar, phantom or otherwise — consistent with **B11**, where
the shadow engine `STAND_ASIDE`s on 100% of bars citing GATE-036.

**What it could break:** nothing today, and that is precisely the condition that
expires. The moment the correlate layer is wired (B11), production would be
reading the *old* fabricating code unless this has shipped first.

**Closing condition:** ships with the next api deploy, and should be **batched
with B17's api half**, which is waiting on the same stop → deploy → verify →
start. **Deploy this before wiring the correlate layer**, not merely "eventually".

Recorded rather than left implicit because T-0001's lesson was that undeployed
work goes invisible: a value committed, believed live, and running at its old
setting for days.

### B8. The delivered contract artefacts are mutually incompatible — BLOCKED ON SALIM
**Found in:** M1 (implementing the telemetry layer)
**What it is:** `TELEMETRY_SCHEMA.json` hard-pins `engine.rule_registry_version` with
`"const": "1.1.0"`, while the delivered `RULE_REGISTRY.json` ships as **1.2.0** — the
version the corpus triage produced when it cleared all 8 DEFECT rules and moved 20 rules
from OPEN to READY.
**Why it matters:** no record emitted against the real registry can ever validate against
the delivered schema. This is not the stale-prose problem in
`MAGIC_STRATEGY_INTEGRATION.md` §2.1 — that one misleads a reader; this one blocks emission.
**What we did instead of picking a side:** records keep stamping the TRUE versions. Writing
`1.1.0` while running 1.2.0 would make stored evidence claim a registry it was never
evaluated against, which defeats the only purpose of the field. The validator relaxes
exactly the two version `const`s and nothing else, and
`contract_loader.contract_version_skew()` reports the mismatch so it cannot pass silently.
**How it ends:** Salim ships a schema regenerated against registry 1.2.0.
`test_the_delivered_artefacts_are_mutually_incompatible_and_we_say_so` FAILS at that point
— deliberately — which is the prompt to delete the relaxation in `validate.py`.


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

### E4. The economic calendar is the wrong source, not merely unconfigured
**Restated 2026-08-08** after checking GATE-015 in registry v1.2.0. The entry used
to read "no FINNHUB_API_KEY". That understated it: a Finnhub key would produce a
working integration that still fails the gate.
**What it is:** GATE-015 (READY, HARD_GATE) names the source — **Forex Factory
RED FOLDERS ONLY**, currencies USD (optionally EUR/GBP for crypto), and the
calendar's timezone **set to New York local** so its timestamps and the chart's
agree. We implemented Finnhub, which is a different provider with different
impact classification and no red-folder concept.
**Why it matters:** three HARD_GATEs depend on it — GATE-012 (no new entry within
15 minutes BEFORE a red-folder event), GATE-013 (none for 30 minutes after, AND
then wait for the first complete M15 candle to close — both conditions, not
either), GATE-015 itself. Until the ruled source is wired, those three can only
ever be NEVER_EVALUATED, which is readiness gate 5's blocking condition.
**Worth carrying into the implementation:** GATE-012's note records that the
15 / 30 / M15 constants appear in no workspace page and in none of the 1,258
images — they are trader-authorised engine constants, not recovered doctrine, and
should be emitted as declared parameters even though the rule is READY.
**Fix:** a Forex Factory red-folder source with New York timestamps. Then delete
the Finnhub client rather than leaving it as a selectable fallback — a second
calendar is a second answer to "was there news", and the gates cannot cite two.

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

### F1. 1-minute dominance bars are degenerate — **see B16, which supersedes this**
**Found in:** I4. **Corrected 2026-08-12:** both of this entry's stated reasons
were still describing 60 s polling, which production left on 2026-08-10.

It read: "At 60s polling a 1m bar holds one observation, so O=H=L=C … Drop
`--loop` to ~15s if 1m bars are ever wanted." At the deployed `--loop 10`
(`deploy/compose.dominance.yaml`) a 1m bar holds **6** observations, not one, so
it is no longer O=H=L=C — and "drop to ~15s" is now a **slowdown** that would
make it 4. The remedy was also never sufficient: the binding threshold is
`MIN_SAMPLES_PER_SYNTHETIC_BAR = 20` (`gate_008_roster.py:158`), which 15 s never
reached either. Clearing 20 on a 1m bar needs 3 s polling, and
`collect_dominance.py:453` is `interval = max(10, int(args.loop))` — a hard 10 s
floor, so it is unreachable without changing that line.

**The conclusion still holds; every reason given for it was false.** That is the
worst state for a register entry — correct, so nobody rechecks it, and wrong in
each detail a reader would act on. Kept rather than deleted because the
degeneracy is real, but the live arithmetic and the decision it collides with
now live in **B16**, and only there. Do not restate them here; two copies of a
number is how these diverged.

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
