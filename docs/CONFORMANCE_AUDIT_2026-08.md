# Conformance audit — 2026-08-13

**The platform does not trade the delivered strategy.** Of the 117 rules in
`RULE_REGISTRY.json` v1.2.0, **zero** decided any trade this platform has ever
taken. Every one of the 12 entries in its history was produced by the
pre-contract ICT engine, and the three taken since the contract engine began
running in shadow were each taken on a bar where the contract engine had, a
fraction of a second earlier, refused.

35 of 117 rules are implemented (`check_rule_coverage.py`: 35/117, HARD_GATE
34/91, OPEN 0/14, and it prints PASSED). That number does not appear in the
answer above and should not be used to soften it: **an implemented rule that
decides nothing is furniture.** The clearest case is GATE-001 and GATE-002 —
implemented, tested, counted in the 35, and violated by the live engine on every
bar, because nothing calls them. The gap is architectural, not volumetric;
building more graders does not move the count from zero.

Audited at `d49c11f` against production. Everything below is a command you can
re-run. Every figure was measured for this report; none is carried from a plan or
a register entry, because five figures written this week went stale without
anything noticing.

---

## Q1. Is the platform trading Salim's strategy?

### Evidence — from the records, not the roadmap

```bash
python3 scripts/audit_live_conformance.py            # TRADINGAI_TOKEN in env
```

```
registry            RULE_REGISTRY.json v1.2.0, 117 rules
decisions           392
  acted on          12
  abstained         380

RULES DECIDING A TAKEN TRADE:  0
    (none — no acted-on decision cites any registry rule id)

THE OTHER ENGINE, ON THE SAME BARS (M9 Stage A shadow):
    evaluations        98
    decisions          {'STAND_ASIDE': 98}
    rules evaluated    1  {'GATE-023': 98}
    deciding rules     1  {'GATE-036': 98}
    blocked            2  {'GATE-002': 98, 'GATE-008': 98}
```

**The zero is measured, not asserted.** Proven before it was trusted:

```bash
python3 scripts/audit_live_conformance.py --self-test
# RULES DECIDING A TAKEN TRADE:  1
#     GATE-023  cited on 1 acted-on decision(s)
```

Fed one synthetic acted-on decision citing a real registry id, the script prints
1. A script that printed 0 because it always prints 0 would be indistinguishable
from this one on today's data.

### Why the live path *cannot* cite a rule

`decision_records` has no column for a rule id — not an empty one, none:

```
id, created_at, symbol, timeframe, inputs_hash, code_path_hash, score, abstained,
reasons, signal_dir, signal_entry, signal_sl, signal_tp, sized_units, expected_r,
realized_r, gap_r, outcome, correction_json, cohort, fill_price, run_id
```

`telemetry_records` — the contract engine's store — has `deciding_rule_id` as a
first-class column. **Two decision paths: one where rule citation is a schema
feature, one with no way to express it at all.** The audit scans the free-text
`reasons` array as the only place an id could appear, and finds none on any
acted-on decision. The scan is deliberately generous (a substring match would
count a rule id in a comment); it still returns zero, which makes the zero
stronger rather than weaker.

From the source side, the same answer: the only registry id anywhere in
`live/strategy_step.py` is a **comment** at `:128` recording that GATE-037 was
removed.

### The two engines on identical bars

Every live entry since the shadow began, matched to the contract engine's verdict
on the same instrument within a second:

| ICT entered | dir | shadow ruled | decision | citing |
|---|---|---|---|---|
| ETH/USD 2026-08-09 21:21:04.609 | LONG | 21:21:04.531 | STAND_ASIDE | GATE-036 |
| BTC/USD 2026-08-11 05:00:06.388 | SHORT | 05:00:06.149 | STAND_ASIDE | GATE-036 |
| ETH/USD 2026-08-12 13:00:06.032 | LONG | 13:00:05.764 | STAND_ASIDE | GATE-036 |

**3 of 3 — and read the reason before quoting the number.** Each was declined
citing **GATE-036: the engine could not see.** Not a judgement on the setup. It
declined **98 of 98** bars on the same grounds, whether the ICT path entered or
not, so "3 of 3" is a subset of a 100% rate and discriminates nothing. The three
were not singled out.

**So the finding is not "Salim's strategy would have refused every trade the
platform took."** That would require the contract engine to have evaluated the
setups, and it never has. The finding is worse:

> **Nobody knows what Salim's strategy would have done on any bar this platform
> has ever traded, because the engine implementing it has never been able to
> see.** GATE-008 and GATE-002 were blocked on all 98 evaluations — the correlate
> panels are unwired (**B11**) — so the comparison the shadow exists to provide
> does not yet exist.

The shadow proves the contract engine *runs*. It does not yet produce a second
opinion, and no conformance number can be computed from it until the panels are
wired.

**The agreement rate is 94/97 (96.9%) and it means nothing.** Within the shadow
window the ICT path declined 94 times and the contract engine declined all 98 —
but they decline for unrelated reasons. GATE-008 and GATE-002 were blocked on all
98 evaluations because the correlate panels were unwired (**B11**), so a
conformance number computed from that agreement would be measuring one engine's
opinion against another engine's blindness.

> **CORRECTED 2026-08-13.** This paragraph originally said the contract engine
> *"is saying GATE-036: I cannot see."* **That attributed a meaning to GATE-036
> that it does not carry, and the error inverted within hours.**
>
> `shadow.py:486` is `deciding = decision.deciding_rule_id or "GATE-036"` —
> **GATE-036 is the fallback used when no rule decided**, not a rule that fired.
> `rule_id="GATE-036"` appears **zero** times as a rule evaluation, and no shipped
> record carries one. Its own docstring reads *"STAND_ASIDE means no setup was in
> play."*
>
> So the same label means opposite things either side of T-0006. **Before:** the
> engine was blind, and GATE-036 appeared because GATE-008/GATE-002 were hardcoded
> blocked. **After:** all four gates PASS on a real four-panel read and GATE-036
> appears because **no setup was in play** — the rule's actual meaning, and a market
> judgement rather than a data one. Nothing in the record distinguishes the two
> cases, which is filed as its own defect (**B31**).
>
> The blindness this paragraph describes was real at the time of the audit. What
> was wrong was reading it off the `deciding_rule_id`, which could not have told
> you either way.

### HARD_GATEs the running engine violates

Each verified at the file and line, `grep -n`:

| rule | status | evidence |
|---|---|---|
| **GATE-032 / GRADE-017** — risk from the 9-cell `box_grade × disturbance` lookup | **violated** | `live/fixed_config.py:70` `RISK_PCT: Final[float] = 0.01`, flat, deliberately not a knob. Neither grader exists, so the lookup has no inputs. |
| **GATE-017 / GATE-019** — ruled execution timeframes are 30M/15M/5M; 1H is analysis-only | **violated** | `live/fixed_config.py:48` `ENTRY_TF: Final[str] = "1H"`, and **12 of 12 entries were on 1H** (below) |
| **GATE-008** — roster `BTCUSDT.P · ETHUSDT.P · TOTAL · USDT.D` | **violated** | `live/fixed_config.py:45` `SYMBOLS = {"BTC/USD": "BTCUSDT", "ETH/USD": "ETHUSDT"}` — spot, two instruments, no correlate panel read at decision time |
| **GATE-001 / GATE-002** — heavy-disturbance skip and the disturbance classifier | **violated *and implemented*** | both appear in `check_rule_coverage.py`'s implemented list, and neither is referenced on the live path — `disturbance` occurs only in `live/shadow.py`, which nothing trades from. **This pair is the whole argument in one line:** the rules exist, they are tested, they are counted in 35/117, and the engine violates them on every bar because nothing calls them. |
| **EXIT-001 / GATE-022** — 70% at 2R, 30% runner, flat at 19:00 New York | **violated** | `live/strategy_step.py:179,199` emit a single TP at `rr_partial × risk`; no session-close handling exists anywhere in `live/` |
| **GATE-025 / 026 / 027** — five-anchor stop ladder, 2R floor, no-trade below it | **violated** | one anchor via `ict_detector._compute_swing` (`strategy_step.py:68`); no RR floor in `fixed_config.py` |
| **GATE-037** — premium/discount entry filter | **CLOSED 2026-08-09** | only a comment remains, `strategy_step.py:128`, recording the removal |

### GATE-017/019 as a number

```sql
SELECT timeframe, count(*) FROM decision_records WHERE NOT abstained GROUP BY timeframe;
--  1H | 12
```

**12 of 12 — 100% of entries this platform has ever taken were triggered from an
analysis-only timeframe.** Proven from what happened, not from the constant that
intends it. (The engine *can* evaluate 5m: six abstains carry it. Every entry was
1H.)

### Answer

**No.** Zero of 117 rules decide a live trade, and the engine actively
contradicts at least six HARD_GATEs. The contract layer runs beside the trading
path and is read by nothing.

---

## Q2. Were the trades it has taken executed correctly?

### The populations, separated first

Auditing 392 rows as if they were live trades would be wrong in the direction
that flatters us.

| population | n | how identified |
|---|---|---|
| `decision_records` total | 392 | all rows |
| — abstains | 380 | `abstained = true` |
| — **acted on** | **12** | `abstained = false` |
| `trades` total | 252 | all rows |
| — **F2 backtest replay** | **245** | `setup_tag = 'Backtest replay'`, avg **0.0807R** — matches F2's recorded +0.081R exactly |
| — **genuine live trades** | **7** | `setup_tag = 'ICT (live)'` |
| — of those, resolved | 7 | 3 SL, 2 TP, 2 operator |
| `decision_records` **ABANDONED** | **5** | B14's historical casualties, including the ETH position of 2026-08-08 |

12 acted-on decisions against 7 live trades: the difference is the 5 `ABANDONED`
rows — decisions that opened a position which was never resolved because a
restart abandoned it.

### What ended each position — reconstructed, with the evidence class named

There is **no recorded close reason.** `_persist_and_resolve` writes only
`realized_r`, `gap_r` and `outcome`, and `outcome` is pure pnl-sign. So the cause
was reconstructed by matching each exit against the stop and target recorded on
its own decision:

```sql
SELECT t.pair, t.exit_price, d.signal_sl, d.signal_tp,
  CASE WHEN abs(t.exit_price - d.signal_tp) < 0.01 THEN 'TAKE-PROFIT'
       WHEN abs(t.exit_price - d.signal_sl) < 0.01 THEN 'STOP-LOSS'
       ELSE 'NEITHER -> closed at mark' END
FROM trades t JOIN decision_records d
  ON d.symbol = t.pair AND abs(extract(epoch FROM (d.created_at - t.entry_time))) < 5
WHERE t.setup_tag = 'ICT (live)' AND NOT d.abstained ORDER BY t.entry_time;
```

| pair | exit | cause | evidence class |
|---|---|---|---|
| ETH/USD | 1912.098102 | **STOP-LOSS** — `exit == sl` | recorded fact, cross-referenced |
| ETH/USD | 1912.202940 | **STOP-LOSS** — `exit == sl` | recorded fact, cross-referenced |
| BTC/USD | 63957.522428 | **TAKE-PROFIT** — `exit == tp` | recorded fact, cross-referenced |
| ETH/USD | 1934.851573 | **TAKE-PROFIT** — `exit == tp` | recorded fact, cross-referenced |
| ETH/USD | 1911.320022 | **STOP-LOSS** — `exit == sl` | recorded fact, cross-referenced |
| BTC/USD | 63387.760000 | operator close | timestamp correlation — `23:07:34`, the T-0004 stop |
| ETH/USD | 1875.850000 | operator close | timestamp correlation — `23:07:34`, the T-0004 stop |

Every exit lands on a recorded boundary to the cent, or provably on neither.
Corroborated independently by a second signature: `gap_r ≈ 0` occurs on exactly
the two take-profits (`0.0000` and `-0.0838`) and nowhere else, because
`realized_r` can equal `expected_r` only when a trade reaches its target.

**The join is the weak part, so name it precisely.** The values are recorded
facts; the *linkage* is a five-second temporal join, because **there is no
foreign key between `decision_records` and `trades`** — the only FKs into
`trades` come from `screenshots`, `checklists` and `orders`. It resolved 1:1 on
this corpus (7 trades, 7 rows, no duplicates, no misses, verified), so the result
stands. The exact evidence class is **recorded values, joined by temporal
proximity, verified unique on this corpus** — not a recorded fact about the
close, and not inference either. This is what breaks first at higher trade
frequency, and this report is written to be re-run.

**A trap that will mislead the next auditor, because it misled one of us.**
The seven live trades carry **no `sl` and no `tp` on their `trades` rows at all**:

```sql
SELECT setup_tag, count(*), count(sl) AS with_sl, count(tp) AS with_tp FROM trades GROUP BY setup_tag;
--  ICT (live)       |   7 | 0 | 0
--  Backtest replay  | 245 | 245 | 0
```

So anyone reconstructing close-cause from `trades` alone finds nothing and
concludes the information does not exist. **It does — it is on
`decision_records`.** Note also that *no* row in `trades`, live or replay, has
ever carried a `tp`.

**The finding is the missing label, not missing information.** The data
determines what closed every position; **the schema declines to say so.** No
`close_reason` field exists, and every consumer — including the feedback loop
that reads `gap_r` — must reconstruct by price-matching or get it wrong. Nothing
documents that requirement.

**And the failure path is better instrumented than the success path.** A
take-profit, a stop-out and an operator close produce three identical records,
while `reconcile_abandoned_decisions` writes a sentence explaining an abandoned
one: *"the engine stopped while this position was open… Not a loss — an
absence."* The only close this platform explains is the one that should never
happen.

### Population per sub-check

Stating "seven trades audited, all clean" would be accurate and would be read as
seven trades' worth of evidence about exits.

| sub-check | n | why |
|---|---|---|
| entry geometry vs recorded | **12 of 12** | every acted-on decision carries entry, sl, tp, size |
| closed by the thing that should have closed it | **5 of 7** | two were closed by an operator deploying |
| stop breached without closing | 0 found in 7 | two lives truncated by the operator close, so "no breach" means "not yet" |
| never resolved at all | **5** | `ABANDONED` — B14 |

**Entry integrity n=12. Exit integrity n=5.** Within the audited run alone, exit
integrity is **n=1** — one stop-out and two operator closes.

### Execution integrity, per trade

No discrepancy was found between what was intended and what was recorded. Every
acted-on decision carries `signal_entry`, `signal_sl`, `signal_tp` and
`sized_units`; every resolved trade's exit matches a recorded boundary or the
operator stop. `fill_price` is **null on the first five entries** — the column
did not exist yet, which is why the feedback loop's adverse-slippage rule has
never fired (`_serialize_decision`'s own comment says so).

`gap_r` across the seven: `-3.0230, -2.7449, -0.0838, 0.0000, -3.3076, -1.5688,
-2.3176`. The two near-zero values are the two take-profits. **`expected_r` is met
precisely when a trade reaches its target** — there is no calibration defect here.
An earlier draft of this audit reported the three trades of the last run only
(all large-negative) and inferred that `expected_r` was systematically
optimistic. That inference was wrong, and it was wrong because n=3 was
generalised to a corpus of 7.

### Has any order reached a funded account?

```
orders table rows          0
broker_connections         1   cryptofundtrader, observe_only: true, trading_enabled: false
CFT account                balance 5090.95, open_trade_count 0, is_simulation false
platform run balance       4941.74 at stop (PROP_FIRM_SIM)
```

**No.** The `orders` table has never held a row. CFT is reachable and authorised
but `observe_only` with `trading_enabled: false`. The platform's balance and
CFT's do **not** agree and are not supposed to — they are different accounts:
the platform simulates against a 5000 starting balance while CFT reports its own
5090.95. Nothing reconciles them, and nothing should until trading is enabled.

### Answer

**For the seven trades that exist, yes — with one caveat that is not about
correctness.** Intended geometry matches recorded geometry, every close lands on
a recorded boundary or an explained operator action, no stop was breached without
closing, and no row is orphaned `OUTCOME_OPEN`. **But five further positions were
never resolved at all** (`ABANDONED`, B14), and the sample is seven. There is no
win rate here, no expectancy, and no equity curve — the 200-trade floor stands.

---

## What the guard harness can and cannot tell you

`verify_guards.sh` runs eight probes and exits 0 as of T-0003, so for the first
time since 2026-08-09 it is real evidence. **None of that evidence covers the
code that decides live trades.**

The eight probes cover the backtest engine's FVG admissibility and daily bias,
the dominance source (three), execution sizing (two), and resolve. **No probe
covers `live/strategy_step.py`** (register **E1**).

**Conclusions in this report that lean on Tier 0.2, and which probe:**

* *"the dominance source no longer invents bars across an outage"* — leans on
  probe 5, `dominance gaps stay gaps`.
* *"market orders are sized from the real fill price"* — leans on probe 6.
* **Nothing in Q1 or Q2 leans on Tier 0.2 at all.** The live entry path is
  outside its coverage, so a green Tier 0.2 is evidence about everything except
  the thing this audit asks about.

**Two corrections to the NOTE the script itself prints, which must not be
repeated in either direction:**

* Its claim that `strategy_step.py` *"still calls the non-causal
  `_daily_bias_events`"* is **false.** No such call exists — only a comment at
  `:81` describing what it used to do. It is fixed *and* regression-guarded:
  `test_bias_parity.py:170-172` reads the source via `inspect.getsource` and
  asserts `"causal_bias_now" in src` and `"_daily_bias_events(" not in src`.
* *"has no causality test"* **overstates it.** Bias causality is tested directly
  and thoroughly, over 710 days of real BTC and ETH. What is genuinely unguarded
  is **born+2 FVG entry admissibility** (`strategy_step.py:136-143`).

**State the property, not the file:** the live entry brain is exercised by three
test files, and none of them tests entry-admissibility causality. A reader who
greps *"is `strategy_step` tested?"* gets a reassuring yes; a reader who trusts
the NOTE gets an alarming and false no. Both are wrong in opposite directions.

Note also that the bias guarantee is **transitive** — a directly-tested helper,
plus a source-inspection assertion that the live path calls it. That is a real
guarantee and structurally weaker than executing `strategy_step` and checking
causality: the difference between *"the code is right"* and *"the code calls
something that is right."*

---

## What nothing was gating

`main` has **no branch protection** — `"protected": false`, protection endpoint
404, zero rulesets (**B20**). The `Tier 0.2` job carries no `continue-on-error`,
so it is *written* to block and has nothing to block on.

**Every merge in this platform's history reached `main` without a check being
consulted** — including the ones that shipped the lookahead bugs this contract
exists to prevent, and including the four consecutive red commits from
2026-08-09 to 2026-08-12, one of which was what production ran.

It cannot be fixed by any agent here: branch protection is admin-only and every
agent pushes as a non-admin collaborator. Only the repository owner can enable
it.

---

## Baseline for this audit

```
cd backend && ~/.venvs/tradingai/bin/python -m pytest -q   ->  858 passed, 0 failed
```

Green for the first time since 2026-08-08. Audited at `d49c11f`; production ran
`71feb556b3e` throughout, one docs-only commit behind.
