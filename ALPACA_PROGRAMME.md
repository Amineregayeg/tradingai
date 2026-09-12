# Alpaca — what a full working simulation needs

**Malek ruled 2026-09-10: the venue is ALPACA, not MetaTrader 5, and the platform trades LONG ONLY
because that is Alpaca's constraint on crypto.** I raised that it removes half the strategy; he
decided with that in front of him. This document proceeds on the ruling and does not re-argue it.

**The ruling supersedes `B305` for the venue** — the asset class is unchanged (BTC and ETH), the
venue and the direction are not.

---

## Two things make this materially easier than MT5, and one makes it harder

### ✅ EASIER — `is_simulation = True` is now TRUE, so nothing has to be relaxed

**This was the hardest single problem in the MT5 programme and it dissolves.**

```python
TradingClient(key, secret, paper=True)      # paper is a CONSTRUCTOR FLAG we set
```

`ExecutionService` refuses any adapter reporting `is_simulation=False`, and `ExecMode` has no LIVE
member — **deliberately, both of them.** An MT5 broker demo could not honestly answer that flag
(`T-0076`, unruled since 2026-08-24, `CONTEST` never ruled at all). **An Alpaca paper account can:
no real money is at risk, and the flag is derived from a value we pass rather than a venue field we
interpret.**

> **So the safety model is satisfied truthfully rather than bypassed.** No new `ExecMode`, no
> weakened assertion, no ruling required from Malek. `T-0076` stops being a blocker.

*(The flag's second reader — the reconciler asking "are these records a third party's" — still says
yes, because Alpaca holds them. That tension is smaller than MT5's and it is not gone.)*

### ✅ EASIER — the sizing and financing problems do not exist here

```
size_position() returns   (equity * risk_pct) / risk_per_unit   -> a float of UNITS
Alpaca crypto accepts     fractional qty. **MEASURED 2026-09-12 (`T-0139`, `B409`), and the
                          numbers below are NOT what this document first claimed:**
                            min_order_size      BTC 0.000012941   ETH 0.000397984   = $1 NOTIONAL,
                                                so it MOVES WITH PRICE and must be read per order
                            min_trade_increment 1e-9 on both      = a constant, and may be held
                          This document previously said "min 0.0001 BTC, increment 0.0001" for both.
                          The minimum was ~8x too large and the increment 100,000x too coarse.
our canonical pair name   "BTC/USD"  ==  Alpaca's native symbol format
```

**Units map to `qty` directly.** `units_to_lots()` stays at zero callers — the whole `B302`/`T-0097`
lots problem was MT5/CFD-specific. **And spot crypto charges no swap**, so `B261` and the
R-multiple-shift question disappear rather than being answered.

### ⛔ HARDER — long-only is not a smaller strategy, it is a DIFFERENT one, and the run must say so

**Measured on real executed trades:**

```
TRADES by direction     SHORT 147     LONG 146
```

**Roughly half of every decision this engine has ever executed cannot be placed on Alpaca.**

> **THE CENTRAL RISK OF THIS WHOLE PROGRAMME:** a simulation that silently drops shorts reads as
> *"the strategy underperformed."* It is not. It is *"half the strategy never ran."* **Those two
> are indistinguishable in a P&L curve and this project has spent weeks on exactly that
> distinction** — `B215`, `B292`, `B372`, `B380`, all of them one shape: *could not* must never be
> recorded as *did not*.

---

# WHAT NEEDS TO BE DONE

## A — The adapter  ✅ **DONE** — `T-0136`, landed `54c3982`, 27 arms

**Goal: an `AlpacaAdapter` the platform can construct and read from.**

| | |
|---|---|
| **A1** | Pin `alpaca-py`. Measure the transitive set against a real install, as `T-0133` did — it should be far lighter than MetaApi's 19 packages and three HTTP stacks, and that claim needs measuring rather than assuming. |
| **A2** | `alpaca.py`, a **flat module** in `app/services/broker/` — `B267`: the contract arm's discovery walk is not recursive, and an adapter one directory deep is invisible to it while the suite stays green. |
| **A3** | The eleven `BrokerAdapter` members. `is_simulation` returns the `paper` flag we constructed with. |
| **A4** | Factory branch in `_make_adapter`, reaching the existing `ALLOW_LIVE_TRADING` guard rather than returning before it — `B352`, and the reason the OANDA branch was deleted. |
| **A5** | UI: a broker option and a form branch. **`api_key` and `api_secret` already exist on the connect request**, so unlike MT5 this needs no schema change. |

**What the MT5 work already bought us**, and it transfers wholly: the kill-switch disposition
vocabulary on `base.py` is Malek's ruled property and is venue-agnostic; `close_all_positions`'
shape — rows enumerated before the loop, report published before it runs, per-position failure
continuing — is proven twice; and the could-not-ask work at the aggregate layer (`B372`) is not
MT5's.

## B — The long-only refusal  ✅ **DONE** — `T-0137`, landed `df1ed4c`, passed review 2026-09-10T23:36:50Z

> **`B391` changed where this lives, and it is the finding of the programme so far.** The refusal
> could NOT have gone in `AlpacaAdapter.place_order`: the live loop has never executed against a
> venue adapter at all — it builds `PaperBroker`/`SimPropFirmBroker` and hands THOSE to
> `ExecutionService`. Written the obvious way, every unit arm would pass and **not one short would
> be refused in a paper run.** So `DirectionPolicy` lives on `base.py`, the venue owns the reason,
> and BOTH simulators enforce it — *a simulator that permits what the venue forbids is not a
> simulation of that venue.*
>
> **Delivered weaker than specified, on purpose (`B392`):** the split reads `M shorts rejected`
> with the mixture named, not `M shorts refused by venue`. `rejection_reason` is free text, so an
> exact venue count would key on the venue's own sentence — which returns a confident ZERO the day
> the wording changes rather than failing. The structured `rejection_code` is scoped into C.

**Goal: every SHORT the strategy produces is REFUSED, RECORDED, and COUNTED — never dropped.**

**The recording path already exists and does not need building:**

```
crypto_loop.py:1087   _record_rejected_signal(...)
db/enums.py           REJECTED
crypto_loop.py:646    "records_rejected_signals": True
```

**So the work is to route into it with a reason the venue owns**, and then to make the count
impossible to miss:

* **B1** — `place_order` refuses a SHORT with a reason naming the venue constraint, not a generic
  rejection. *"Alpaca crypto is non-marginable and not shortable"* is the sentence; *"order
  rejected"* is not.
* **B2** — the refusal is recorded through `_record_rejected_signal` with that reason, so a short
  appears in the record as **a decision the strategy made and the venue could not express.**
* **B3** — **the run summary states the direction split explicitly.** `N longs taken, M shorts
  refused by venue`. Without it the P&L is uninterpretable, and `B380` is the standing example of a
  surface rendering an absence as a healthy number.
* **B4** — the arm that matters: **feed the engine a SHORT signal and assert the refusal is
  recorded and counted, not that the order failed.** A test asserting "no order was placed" passes
  against a crash.

## C — The order path (BIND ONLY)  ✅ **DONE** — `T-0138`, passed review as one unit at `a66239d`

> **Landed across five commits:** `a212f5d` (safety flag must agree with the endpoint; a run that
> can't place orders refuses to start), `d7f5b15` (one venue selection, one binder), `fcabf6e`
> (structured rejection codes), `f81e222` (a failed rebuild no longer leaves the old broker deaf) and
> `34cb5a8` (the venue label, recording of venue errors, the response redactor, part 3's survivors).
> **Migrations 0010 and 0011 were run against a real server** (a scratch copy of production) before
> landing, and the committed bytes match the tested ones
> (`agents/tasks/T-0138/MIGRATION_TEST.md`). Review reproduced every suite itself and verified all
> four silent-failure rows by mutation. **Alpaca is now selectable but can't fill orders. That's
> D's job.** — `T-0138`, six kill-set rows registered before any arm

**Goal: the engine CAN be pointed at the Alpaca adapter instead of the in-process simulator.**

**Ruled Reading A on 2026-09-11: C BINDS, it does not build the order body.** `place_order` still
refuses, so **a run configured for Alpaca must FAIL TO START** — naming the missing member and the
task that owns it — rather than starting and failing 146 longs one at a time. **A wall of per-order
failures reads as a broken venue** (`B380`'s shape); one refusal at startup cannot be mistaken for a
market condition. *"The simulator stays the default"* is not sufficient, because one config change
defeats it.

This is the old Gate 4, and it is **binding, not building** (`B350`). Three named changes, measured:

```
crypto_loop.py:157/162, 786/790   self.paper constructed INLINE -- no injection point
crypto_loop.py:168, 794           ExecutionService(self.paper, ExecMode.PAPER) hardcoded
broker_mode                       selects between TWO SIMULATORS -- not a venue switch
```

**And the safety layer needs no change at all**, which is the part that was impossible for MT5:
`ExecMode.PAPER` remains correct because an Alpaca paper account **is** a simulation, and
`execute()`'s assertion passes on a true flag.

## D — First connection, AND the order body written against what it measures

**Goal: replace assumptions with observations — and THEN implement `place_order`, whose inputs are
exactly those observations.**

> **SCOPE CORRECTION 2026-09-11, and the gap was mine.** `A3` said *"the eleven `BrokerAdapter`
> members"*, and A shipped `place_order` REFUSING — correctly, because B's recording path did not
> exist yet. **So the body fell between A and D and nothing owned it.** Execute found it by asking
> whether C was *bind* or *bind and build*, which the plan did not answer.
>
> **It belongs here rather than in C because `D3`'s measurement IS its input:** the minimum size and
> increment are what `size_position`'s output must be rounded to, and a sub-minimum order must
> REFUSE rather than round to zero. **Writing the body before D means writing it on assumptions and
> rewriting it after** — the mechanism by which this project generates its own defects.
>
> **So after C, Alpaca is SELECTABLE and cannot fill. After D, it trades.**

**Free and needs nothing from us:** a paper account is created with an email, **globally**, and
carries free real-time data.

| | |
|---|---|
| **D1** | Wrong key vs wrong secret — are they distinguishable? The `0.1` question, and still worth two minutes. |
| **D2** | Symbol format confirmed live: `BTC/USD` and `ETH/USD`. The legacy `BTCUSD` form also resolves; **pick one and record which**. |
| **D3** | Minimum order size and increment for both pairs — documented as `0.0001` for BTC; confirm for ETH. **This is what `size_position`'s output must be rounded to, and a sub-minimum order must REFUSE rather than round to zero.** |
| **D4** | What a rejection looks like, and whether a refused short is distinguishable from a rejected long. |

**Gone entirely from MT5's list:** the account-type enum, the connection-state pair, the CPU-credit
quota, the swap-inclusivity question, and the lots conversion.

## E — The analysis layer must refuse a population it cannot characterise

**Goal: stop the feedback loop computing corrections across runs that are not comparable.**

**Found by Review while attacking my own ruling**, and it is a stronger gap than the one I had named.
I said `long_only: true` in `EngineRun.config` would make any statistic self-marking. **It marks the
run and nothing carries the mark to the consumer that matters:**

```
DecisionRecord.run_id                   EXISTS -- the join to EngineRun.config is AVAILABLE
GET /feedback   last 2000 decisions ACROSS RUNS, no run filter
                analyze(records, ...) -> result["corrections"]
grep run_id|config|long_only in services/evaluation/feedback.py   ->   NOTHING
```

**`analyze()` cannot tell which run a decision came from, and it emits CORRECTION PROPOSALS.** So a
population mixing long-only runs with both-direction runs produces expected-versus-actual statistics
that are not comparable — **and the loop does not display them, it acts on them.**

> **`B292` at the analysis layer:** a statistic over a population you cannot describe should say so
> rather than produce a number.

**The remedy is a refusal rather than a join** — no new field, and it fails closed.

**And the refusal must NAME what it could not do**, which is the half a bare refusal loses: not
*"cannot analyse"* but *"this population spans 2 configurations — 1,340 decisions with
`long_only=false`, 660 with `long_only=true`."* **A bare refusal is its own `B292`** — an operator
cannot tell *could not ask* from *nothing to say*, and the counts say exactly when it becomes
answerable.

**Scoped as its own part rather than folded into `T-0137`**, because it is about the analysis layer
rather than the venue and it would outlive another venue change.

---

---

## What gets deleted, and what is kept

```
DELETE   mt5.py + its arms                       3,370 lines
DELETE   the metaapi-cloud-sdk pin               19 packages, 3 HTTP stacks, 2 unused sibling SDKs
DELETE   token / mt5_account_id request fields   Alpaca uses api_key + api_secret, which exist
MOTHBALL MT5_FIRST_CONNECTION.md, MT5_PROGRAMME.md   kept as history, marked superseded

KEEP     the 11-member BrokerAdapter contract
KEEP     the ruled kill-switch vocabulary on base.py, and its consumer
KEEP     the factory's ALLOW_LIVE_TRADING guard and the credential-blob route
KEEP     B372's could-not-ask work at the aggregate layer
KEEP     the engine, the Binance feed, the candle history, the 44-file rule engine
```

**Do not delete the MT5 work in the same commit as the Alpaca work lands.** A revert of one should
not resurrect the other, and the register entries that came out of it — `B334` through `B386` —
describe defect *classes* that outlived their venue.

---

## The honest risks

**The simulation tests the plumbing, not the strategy — and now less of the strategy than before.**
Long-only removes 147 of 293 executed trades. **Whatever the equity curve shows, it is a curve for
half a strategy**, and every report must carry the refused count beside it or it will be read as a
verdict on the rules.

**The R-multiple and grade apparatus was built for both directions.** Nothing breaks, but any
statistic aggregated across a long-only run is not comparable to one from the paper broker, and
nothing in the tree currently marks the difference.

**And `B383`'s lesson applies to this document.** Every figure here is measured — the direction
split from `trades`, the line numbers from the tree, the Alpaca limits from its own docs — except
the claim that `alpaca-py` is lighter than MetaApi's dependency set, **which is an expectation and
is marked as one.**
