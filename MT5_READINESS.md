# MetaTrader 5 — what is ready, what is blocked, and what you must bring

> **Record correction, 2026-08-30.** The commit that applied these fixes (`020c512`) states
> *"B288 IS ADDED and is REVIEW'S"*. **That is false. `B288` was bid but never written into the
> register**, and I asserted it was on the strength of a peer's report without running the one
> command that checks. The corrections to this document below are unaffected — each was verified
> independently — but the commit message claims something that is not true, and it is pushed and
> immutable. This note is the correction of record.


**Updated 2026-08-30.** For the phase after this one: linking an MT5 demo account and running the
strategy against it.

> ## CORRECTED 2026-09-04, the day you asked to start setting MT5 up — `B333`
>
> **This summary said THREE things wait on you, and had said it since two of the three were
> RULED in the body of this same document on 2026-08-31.** `84fe547` recorded the rulings and left
> the count. **TWO things wait on you, and only one of them blocks anything today:**
>
> | | what | blocks |
> |---|---|---|
> | **1** | **A MetaApi account and token** — `app.metaapi.cloud/token` | **everything.** Nothing can reach MT5 without it |
> | **2** | **An MT5 broker demo account whose demo lists BTC/ETH CFDs** | the first connection. See the constraint in item 0 |
>
> **And the `is_simulation` decision does NOT gate connecting** — the document listed it as
> though it did. `mt5.py:147` returns `False` explicitly and every write refuses, so **your ruling
> gates TRADING, not CONNECTING.** A reader of the old summary would have waited for a decision
> before creating an account, which is the wrong order.
>
> **What the summary did not say at all: two unbuilt pieces stand between the finished adapter and
> a connection**, and nothing tracked either until `T-0133` and `T-0134` were opened on 2026-09-04.
> See *"The adapter is not the last piece"* below. **Neither waits on you.**

---

## THE PLAN, IF YOU WANT THE WHOLE PICTURE FIRST

**[`MT5_PROGRAMME.md`](MT5_PROGRAMME.md)** — written 2026-09-05: every task between here and trading
the demo, what each one is FOR, and which of the four gates it belongs to. **It is the document that
answers "when can I start"**; this one answers "what do you need from me".

**Its headline, so it is not buried:** *linking* the demo is one task away and in flight. *Trading*
the demo is a programme, and one piece of it — the order path — has never been scoped by anyone.

---

## When you have credentials, start here

**[`MT5_FIRST_CONNECTION.md`](MT5_FIRST_CONNECTION.md)** — every open question turned into an ordered
test plan, each item naming the register entry behind it.

**One item needs no working account at all.** Telling a wrong server name from a wrong password is
settled by **deliberately getting it wrong twice** — misspell the server, then use a bad password.
Two minutes, free, and it can be done before anything connects. Those two failures are the ones a
first connection actually meets, and they have identical symptoms if nobody has checked.

**Two items gate everything after them**, and the order is not cosmetic:

1. **Connection state, before anything reads positions.** An empty list from a broker you cannot see
   is *cannot see*, not *nothing there* — every later reading is uninterpretable until that is
   confirmed, and the kill-switch design depends on it.
2. **Account type, before anything touches the safety flag** — with the disconnect-mid-session test
   attached, because if *failed* and *unrecognised* look the same, **a new account type would read as
   an outage forever.**

**The most important item needs a closed trade**, so it cannot be done on day one: whether the
venue's profit figure includes financing costs. **That single call decides whether your R-multiples
still mean what they meant on the paper broker.**

**And one question cannot be answered on a demo at all.** A retail demo reports `DEMO`, so the
`CONTEST` behaviour — the state a prop-firm challenge account would report — stays open until such an
account exists.

---

## What only you can supply

### 0. ✅ RULED 2026-08-31 — **MT5 TRADES CRYPTO CFDs (BTC/ETH)**

**You ruled this. Everything below in this item is kept as the reasoning behind the question, not
as an open question.** Under this answer the existing loop, the Binance feed and the candle history
drive MT5 unchanged and every queued MT5 task is correctly scoped already.

**One phrase here was wrong and is corrected rather than deleted (`B333`):** this item said
*"what changes is one adapter"*. **The adapter is written and green and nothing can connect** —
the MetaApi SDK is in no requirements file and `_make_adapter` raises for `mt5`. What changes is an
adapter, a pinned dependency, and a factory branch. The ruling itself is unaffected.

**It stays a CONSTRAINT after being closed as a question:** crypto CFDs, **not** whatever the broker
lists. An MT5 account offering forex does not widen it without a new decision.

**And the financing question survives:** MT5 crypto CFDs **charge swap** where spot does not, so
`B261` and §3.1 of the first-connection checklist are still the most important thing a closed trade
settles.

---

#### The question as it was put, kept for the reasoning

**Document:** `B305`, filed 2026-08-30. **This is not a code question and it cannot be derived.**

**Measured today:**

```
crypto_loop.py            the ONLY live loop
fixed_config.py:45        SYMBOLS: Final = {"BTC/USD": "BTCUSDT", "ETH/USD": "ETHUSDT"}
main.py:235               LiveCryptoLoop()  -- no arguments, so THAT dict is what production runs
market_data/sources/      binance, binance_perp, cft, dominance -- ALL FOUR ARE CRYPTO
```

**There is no forex or metals price source in this tree.** The first-connection checklist tells you
to capture the volume bounds *"for the instruments we would trade"* — **and never names one.**

**Two answers, and they are not the same size of work:**

* **Crypto CFDs on MT5** (most MT5 brokers list BTCUSD/ETHUSD) — the existing loop and feed drive it
  unchanged, **the adapter really is the last piece**, and everything queued below is correctly
  scoped.
* **Forex or metals** — **there is no feed, no candle history, no symbol map and no loop** for the
  instrument. **That is a programme, not an adapter**, and the six queued MT5 tasks are scoped for
  the other answer.

**This document has been implying the second one.** *"MT5 is the first venue that charges [overnight
financing]"* is true of forex and CFDs and not of spot crypto — **written without noticing it was an
answer to a question nobody had asked.**

**Every MT5 task so far has been about the TRANSPORT** — which SDK runs here, which members map, what
a mock must model. **None of them had to name an instrument, so none noticed that nothing does.**


### 1. A decision — `is_simulation` for an MT5 demo

**Document:** `agents/tasks/T-0076/decision-for-malek.md`, 227 lines, waiting since 2026-08-24.

**The problem in one line:** `is_simulation` is read by two places that mean different things by it.
`ExecutionService` asks *is real money at risk* — an MT5 demo says **no**. The reconciler asks *are
these records a third party's* — an MT5 demo says **yes**. **They have never disagreed before,
because every adapter so far was either our own paper broker or a real-money venue.**

So there is **no value of the existing flag that is correct for an MT5 demo**, and that is measured
rather than argued. The document names three options with their consequences and recommends a
sequence; it does not take the decision.

**Amendment 1 matters more than the options.** The safety claim everyone was leaning on —
*"a subclass that forgets `is_simulation` cannot be instantiated, so a new adapter can never
silently pass as safe"* — **is weaker than it reads.** Omitting the flag does raise, but
`is_simulation = True` as a bare class attribute instantiates fine. **The mechanism forces a
declaration and cannot force a true one**, and that declaration is the entire safety argument for
letting the engine trade.

**UPDATE 2026-08-30 — the decision has changed shape, and for the better.**

**The check the document said was missing turns out to EXIST.** MetaApi reports MT5's own native
account trade mode on the account-information response — **a required field, read from the broker,
not a value we supply:**

```
type  string  REQUIRED
  "account type. enum ACCOUNT_TRADE_MODE_DEMO, ACCOUNT_TRADE_MODE_CONTEST, ACCOUNT_TRADE_MODE_REAL"
```

**It arrives per call, so it is re-read on every reconnect** — which was the hard requirement. A
value obtainable only once at construction would have been a class constant with extra steps.

**That matters because demo and live are otherwise indistinguishable in code.** Account creation
takes **no demo/live field at all**; the only hint is a substring in a broker-chosen server name.
So without this read, the only thing standing between a demo and a live account is a config value
being right — **which is exactly what we have already ruled a safety property must never depend on.**

### ⚠ But it adds a state you have not been asked about

**The venue reports THREE states and the flag has TWO:**

| venue says | means |
|---|---|
| `DEMO` | no real money, real broker connection |
| `REAL` | real money |
| **`CONTEST`** | **neither** |

**`CONTEST` is not a hypothetical, and the reasoning behind that is INFERRED rather than observed.**
A prop-firm challenge account is exactly that shape, and this platform already operates in that
world: the engine's run config records `"mode": "PROP_FIRM_SIM"` and the one non-paper adapter is
Crypto Fund Trader, a prop firm. **It is the state this project is most likely to meet and least
likely to have planned for.**

> **Marked, because the inference crosses a platform boundary.** Crypto Fund Trader runs on
> **Match-Trader, not MetaTrader** — so the argument is *a prop firm on one platform implies a prop
> account on a different platform reports that platform's contest value.* Plausible, and inferred
> across exactly the line that has already caught us once. **No MT5 prop account has been
> observed.**

Failing closed puts `CONTEST` on the real-money side: no money at risk, but a **real broker
connection whose records belong to a third party** — which is the *other* question this one flag is
being asked. **That is a decision for you, not something to be derived.**

**One implementation trap, recorded so it is not walked into:** the field is called `type`, and the
same SDK uses `type` for something else entirely — `'cloud'`, the deployment kind, on the
account-creation call. **Same name, same vendor, unrelated meanings, and only one of them is a
safety property.**

### 2. An MT5 demo account

**Nothing can connect without it, and it cannot be created on your behalf.** Required: a broker, a
server name, a login, and a password.

**And a MetaApi account with a token — plus whatever tier it turns out to require.** The spike has
now concluded that a cloud bridge is **the only route that runs on our Linux container**, so this is
no longer conditional. **It is a paid service and its free tier is discretionary**, so the cost is a
decision only you can take. See *"The transport is settled"* below.


### 3. ✅ RULED 2026-08-31 — **the kill switch, as a PROPERTY**

> **Every position open when the switch was pulled must be CLOSED, FAILED WITH A REASON, or NOT
> ATTEMPTED. A position in none of those three states is a bug by construction.**

**You ruled the property rather than picking a design, which is what was recommended and why:** all
three designs can satisfy it, today's CFT code violates it, and it is the only formulation that does
not change when the transport does. **`NOT ATTEMPTED` is the state none of the four shapes in the
tree can express**, and it is the one that matters at 3am.

**Consequences, now in motion:** `T-0106`'s prohibition on `close_all_positions` is lifted with the
property as its specification; `B303`'s CFT defect is fixed under it; and an arm asserts it over
every implementation.

> ### An OPTIONAL refinement, offered rather than asked — and nothing waits on it `B337`
>
> **Your three states are being used as ruled and this is not a blocker.** Recorded here because it
> is your vocabulary and you should know the one place it strains.
>
> Review found that the position whose close **was actually sent** — and whose loop then died before
> the answer came back — was being reported `NOT ATTEMPTED`, with the reason *"the close loop never
> reached this position."* **That sentence is affirmatively false about our own action**, and it is
> the row the covering test did not look at.
>
> **I ruled the fix without you and here is the reasoning, so you can overrule it.** You ruled
> *"FAILED **WITH A REASON**"* — not *"FAILED"*. The reason clause is part of the state, and it is
> where *outcome unknown* belongs; that is what makes three states sufficient. So the in-flight row
> becomes **FAILED, reason: the close was sent and the outcome was never observed** — which uses
> your vocabulary rather than widening it. **The conservative action was the fix, not the wait:**
> waiting for a ruling would have kept a false sentence in front of an operator at 3am.
>
> **What is genuinely yours: whether you want a FOURTH state** — *attempted, outcome unknown* — as
> its own disposition rather than living in a FAILED row's reason. It would let an operator sort
> *"we tried and it failed"* from *"we tried and we do not know"* at a glance. **It changes the
> state set, which is why it is yours, and it is an improvement rather than a gap.** Say so
> whenever; the fix above holds either way.

---

#### The question as it was put, kept for the reasoning

**Document:** `agents/tasks/T-0125/decision-for-malek.md`, about two minutes. **New 2026-08-30.**

**Why it appears only now, which is the first thing worth saying:** it had existed for a week as a
single prohibition sentence inside `T-0106`'s body — *do not build `close_all_positions`, that is
Malek's decision.* **A decision recorded only inside another task's must-not-do clause is invisible**
— nothing lists it, nothing ages it, nothing surfaces it. **It is a tracked task now**, whichever way
you rule.

**The situation:** MetaApi has **no close-all call** (`B285`), so the MT5 kill switch must **loop**,
and a loop can **half-succeed**. Three closed, two not — what should it do and say?

**I almost did not ask, because the codebase looked like it had answered.** CFT already loops and
reports per position. **Measured today: it catches `BrokerError` only, and a network timeout is not
one** — the loop aborts, the remaining positions are never attempted, and the per-position record is
discarded with the frame. **Zero-closed and four-closed produce identical output** (`B303`, filed
today, on the venue you trade **now**).

**What I recommend is not one of the three designs — it is a property:** *the report must account for
every position that was open when the switch was pulled — CLOSED, FAILED WITH A REASON, or NOT
ATTEMPTED.* All three designs can satisfy it; today's CFT code violates it; and it is the only
formulation that does not change when the transport does.

### 4. Two live reads that need your say-so, not your judgement

**`T-0114`** — one live CFT API call to settle **which P&L key the broker actually sends**. It is
gated because it touches a live account, not because it is difficult. Everything about `B286`'s
family stays provisional until it runs.

**And `is_simulation` above is now a THREE-state question, not two** — MetaApi reports
`DEMO | CONTEST | REAL` (`B284`). `CONTEST` has no ruling anywhere.

---

## What is being established now, without waiting for you

| task | what it settles | state |
|---|---|---|
| **T-0096** | Which transport can reach MT5 from this box | **done** |
| **T-0099** | Demo vs live at the API level — found the broker-reported account type | **done** |
| **T-0100** | All twelve adapter members mapped onto MetaApi, as an ordered checklist | **done** |
| **T-0097** | Units-to-lots conversion — the seam where a unit error is a money error | **done** |
| **T-0103** | Its refusal vocabulary, and publishing what the tests do *not* cover | in progress |
| **T-0105** | `Position` schema for MT5 — three findings in one change, no migration | queued |
| **T-0106** | **The adapter itself — the eight members that map cleanly, against a mock** | queued |

## The adapter is not the last piece — two things stand behind it `B333`

**Measured 2026-09-04, and the only reason it was measured is that you asked.** `T-0106` is
written: 671 lines, 130 tests green. **Nothing in the application can connect with it.**

### 1. The MetaApi SDK is installed nowhere — and the suite cannot say so `T-0133`

```
grep -rn metaapi backend/requirements*.txt backend/pyproject.toml   ->  no hits
python -c "import metaapi_cloud_sdk"   ->  ModuleNotFoundError
```

**`mt5.py` deliberately does not import it.** The client is injected, and that is correct: `B267`
measured that an adapter module which cannot be imported is **skipped in silence** by the contract
arm that walks the broker package, so an SDK import at module scope would turn a missing dependency
from a loud failure into an invisible gap in the test suite.

> **The design choice that lets an adapter be written before its venue exists is the same choice
> that makes its missing dependency unobservable.** *"The adapter is done and green"* and
> *"nothing can connect"* are both true, and the suite reports only the first. **A green suite here
> is not readiness.**

**And the dependency has a price already measured but never confirmed against a real install:** 19
packages, including both `aiohttp` and `requests` on top of our `httpx` — **three HTTP stacks in
one image** — plus `python-socketio 4.6.1`, a pinned old major. Those figures come from a
`--dry-run`, which proves only that pip can compute a set. `T-0133` installs it for real and says
which of the three numbers was wrong.

### 2. Nothing can construct the adapter `T-0134`

`manager.py:25`, the only construction path:

```python
key = broker.lower()
if key in _CFT_ALIASES:
    ...
    return CryptoFundTraderAdapter(**common)
raise ValueError(f"Unsupported broker: {broker!r}")
```

**A `broker_connections` row naming `mt5` raises.** The adapter is reachable from its own test file
and nowhere else. **Not a missing line, either** — the factory passes `email / password /
base_url / account_id / environment / observe_only`; the adapter takes an **injected client** and a
keyword `account_id`. The shapes do not meet.

**The part of this that must not be got wrong:** the CFT branch forces `observe_only=True` unless
`ALLOW_LIVE_TRADING` is set server-side, and says on itself that this runs on **every** construction
path. An `mt5` branch returning before that guard would be a new unguarded real-money path —
**which is exactly why the OANDA branch was deleted from this function.**

### Why seven MT5 tasks did not find this

Every one of them was about the adapter's **inside** — which SDK runs here, demo versus live, the
twelve members mapped, units to lots, the refusal vocabulary, the schema, the adapter. **None had
to name its callers, so none noticed it has none.**

**That is `B305`'s shape one layer out.** There, six MT5 tasks were all about the transport, none
had to name an instrument, and none noticed nothing did. **A run of tasks that share a frame cannot
find what the frame excludes**, and the frame is invisible because every task in the run respects
it.

---

**`T-0106` is the one that decides what your first hour looks like.** It writes the adapter from
documentation that has already been read and quoted, so that **connecting becomes a test rather than
a build.**

**It deliberately stops short of three members**, and each for a reason that is yours rather than
ours:

* **`close_all_positions`** — the kill switch. Building it before you choose raise / report /
  confirm would be choosing for you.
* **`close_position`** — dispatches on size between two MetaApi calls, so it waits on the conversion
  work landing.
* **`disconnect`** — **not documented at all.** If none exists it becomes a no-op *with a docstring
  saying why*, never a silent one.

**And it reads the account-type field without acting on it.** The mapping from `DEMO` / `CONTEST` /
`REAL` onto our safety flag **is the decision waiting on you** — so the adapter will expose the
venue's answer and leave the wiring unbuilt, with a comment saying that is deliberate.

---

## The transport is CHOSEN, and it costs money

**Measured on this box — `Linux x86_64`, `python 3.12.3` — with nothing installed; every resolution
was a dry run.**

> **"Chosen", not "settled", and the distinction is not pedantry.** A `--dry-run` proves pip can
> compute a dependency set. **It proves nothing about authentication, websocket behaviour, rate
> limits, or whether the pinned old `socketio` major coexists at RUNTIME rather than merely
> resolving.** The candidate is picked; it has never connected to anything.

### The official MetaTrader 5 Python package cannot run here, and not for the usual reason

```
MetaTrader5  latest 5.0.6147   requires_python <4,>=3.6
9 files. EVERY ONE win_amd64. No manylinux wheel and NO SDIST.
```

**Two things follow that "it needs Windows" does not say.** `requires_python` **is satisfied** by our
3.12 — **the block is the platform, so pinning a different Python is a dead end.** And **no source
distribution means there is no compile-from-source escape hatch**: a package with a tarball could at
least be attempted on Linux; this cannot be attempted at all.

*(The naive check is ambiguous and was not trusted: `pip index versions` reports "No matching
distribution found" identically for "does not exist" and "no wheel for your platform". It was
disambiguated against PyPI directly.)*

### A cloud bridge is the only route that runs on this box

**MetaApi** installs as a pure-Python wheel and resolves cleanly on Linux/3.12. It speaks REST and
websockets and supports both MT4 and MT5. **A token is created at `app.metaapi.cloud/token`.**

**The dependency cost nobody had priced:** production today is 21 packages with **one** HTTP client
(`httpx`). MetaApi adds **19 packages, including both `aiohttp` and `requests`** — **three HTTP
stacks in one image** — plus `python-socketio 4.6.1`, a pinned old major. **No conflict today. A
plausible one later**, and worth knowing before it is a surprise during an incident.

### It is a paid service, and the free tier is discretionary

MetaApi's own SDK documentation: *"MetaApi is a paid service, however we may offer a free tier access
in some cases."*

**"In some cases" is not something a plan can be built on.** The published pricing page returns 404
and the pricing section on the site is JavaScript-rendered, so **exact figures are unverified** — the
per-account monthly model comes from a competitor's page and a `$10–$850` range from a third-party
aggregator, **neither of which a cost decision should rest on.**

**You do not need a separate investigation to settle it.** You need a MetaApi account and token
whichever tier applies, and **signing up surfaces the real pricing.** The account you must create
anyway is the instrument that answers this.

### A third route exists and is untested rather than ruled out

A broker-side MT-manager REST API would avoid the bridge entirely. **It requires a broker
relationship that does not exist**, so it was not tested — and that is recorded as untested, not as
unavailable.

---

## What is already settled, so it is not rediscovered

**Where the adapter file goes is a correctness question, not a style one.** The contract test that
would automatically cover a new adapter walks the broker package **non-recursively**. Measured: a
deliberately defective adapter placed one directory deep is **invisible, and the suite stays
green** — 16 tests pass. **The MT5 adapter must be a flat module in `app/services/broker/`.**

**Sizing is a producer and nothing covers it.** `size_position` returns **units**; MT5 sizes in
**lots** with broker-set minimums and step increments. The contract arms that auto-extend to a new
adapter cover *closing* positions, not sizing. The conversion must round to the broker's step, clamp
to its limits, and **refuse rather than silently round to zero** — a zero-lot order the venue
rejects would be a success report over an action that never happened, which has bitten us before.

**The position schema cannot carry an MT5 position as-is.** MT5 reports profit, swap and commission
as three quantities; our schema has one field. Both venues we have ever normalised from are
swap-free, so this has never been wrong before.

**An adapter that forgets `reference_price` silently rejects every market order** as *"no reference
price available"* — which reads like a market-data fault and sends the debugger to the wrong
subsystem. It is not enforced by the language; it goes on the checklist.

**Recording inputs is venue-independent; recording derivations is not.** All four inputs to the
sizing calculation are now persisted (`T-0084`), so position sizes stay reconstructible on any venue.
Before that fix they were recoverable only by arithmetic that **breaks on MT5**, where swap and
commission give account equity a second author — and nothing would have announced the break.

---

## One safety property changes on MT5, and it needs a decision

**Your kill switch is `close_all_positions`. On MT5 it can no longer be one call.**

**MetaApi has no close-all.** The only bulk close documented is *close positions for one symbol*. So
the kill switch **must iterate** — and a loop can **partially fail.**

> **"Closed everything" stops being a return value and becomes a claim the adapter has to earn.**

That is the exact shape that has already cost this project once: an operation that **reported success
over an action that did not happen**. On the paper broker the kill switch closes everything in one
call and cannot half-succeed. On MT5 it can.

**The decision to record — not to default:** when closing position 3 of 5 fails, what does the kill
switch do?

| option | what it does | what it trusts |
|---|---|---|
| **Raise** | stop at the first failure and surface it | the close calls' own answers |
| **Report per-symbol** | continue, return what closed and what did not | the close calls' own answers |
| **Confirm** | close, then **re-read positions and assert the book is flat** | nothing — it checks |

**The third option was missing from an earlier version of this document, and it is the one that
actually addresses the failure being guarded against.** Raise and report-per-symbol both believe
what the close calls told them. **Confirmation does not** — and "reported success, closed nothing"
is precisely a case where the calls' own answers were the thing that lied.

> ### ⚠ And confirmation has one precondition, or it becomes the *most* confident wrong answer
>
> **MetaApi reports two connection states, not one:** connected to *MetaApi*, and connected to the
> *broker*. **"Connected to the cloud but not to the broker" is a real state — and it is the state in
> which asking for your positions returns an empty list that means nothing.**
>
> **So confirmation would read that empty list and conclude the book is flat.** It reports the kill
> switch succeeded, having closed nothing and having been unable to see anything. **The option chosen
> because it verifies rather than trusts becomes the one that lies most confidently.**
>
> **This does not make confirmation the wrong choice** — the other two never look, so they cannot be
> misled; they simply never had the information. **It makes it incomplete.** The repair is one line
> of precondition: check the broker connection before treating an empty list as evidence. **An empty
> list from a broker you are not connected to is "cannot see", not "nothing there"** — a distinction
> this system already enforces elsewhere and would not have had here.
>
> **Inferred from the documented flag, not observed.** It is the first thing to test on your real
> connection, and it is cheap: connect, break the broker link, read positions.

**It costs an extra round trip and it is the only option that earns the claim.** Your own framing,
turned back on itself: *"closed everything" stops being a return value and becomes a claim the
adapter has to earn* — **earning it is what confirmation does.**

**Silently returning success is not on the list**, and it is what happens if nobody chooses.

**Worth knowing alongside it:** this member deliberately does *not* check `is_simulation` — that was
settled earlier and on purpose, because a kill switch that refuses to close a real position is worse
than the risk it avoids. **So this is the one path where an MT5 failure has no safety flag in front
of it.**

## A number on your dashboard will change on MT5, and nothing would announce it

**`realized_r` — the R-multiple every trade result is judged by — shifts on MT5 with no schema
change, no migration, and no error.**

```
realized_r  =  pnl at close  /  (|entry - stop| * units)
               ^^^^^^^^^^^^     ^^^^^^^^^^^^^^^^^^^^^^^
               the VENUE's      OUR stored geometry
```

**⚠ THE WARNING HOLDS. THE DIRECTION IS UNVERIFIED, and an earlier version of this document stated
one branch as though it were known.** Checked against MetaApi's deal model, quoted:

```
profit       number   REQUIRED   "deal profit"
commission   number              "deal commission"
swap         number              "deal swap"
```

**The documentation does not say whether `profit` already includes the other two.** And **three
separate fields argue that it does not** — reporting a component separately from a total containing
it would be double-counting.

**Both branches are a problem, and the unstated one is worse:**

| if the venue's `profit`… | then `realized_r`… |
|---|---|
| **includes** swap and commission | gains components the denominator lacks — **R gets worse than the geometry says** |
| **excludes** them | stays geometry-comparable and **silently ignores real costs — R looks FINE while the account pays** |

**A figure that quietly overstates performance on a live venue is worse than one that understates
it** — and it is the branch the field layout points at.

**The check is one closed deal:** read `profit` for it and compare against the position's realised
total. **It cannot be done before you have an account**, and it should be done on the first closed
trade rather than after a month of figures nobody can interpret.

**It is worth being precise about the blast radius, because the first guess was wrong.** The stored
result the exit rule was verified on is **safe**: it is computed from the decision's own geometry and
never touches the position P&L field. **That was checked, not assumed.** The exposure is the *other*
calculation, one layer up, which the schema work would never have touched.

### And the same ambiguity already exists on the venue you trade today

**Our position P&L field has no single definition right now:**

```
paper broker   sign * (price - entry) * units          GROSS price movement
CFT adapter    profit  OR  netProfit  OR  openNetProfit    whichever the venue sent
```

**`profit` and `netProfit` are not the same quantity** — one conventionally gross, the other net of
costs — and **the adapter takes whichever key arrives while recording nothing about which.** So the
field's meaning is decided per response, invisibly.

**This has never mattered because both venues we have ever used are swap-free** — the paper broker by
construction, crypto because it has no overnight financing. **MT5 is the first venue that charges,
and it is what forces the question.**

**One consequence already live:** the R-multiple shown for a CFT position is derived from that field,
while the paper broker's is a pure price ratio. **Same name on the same dashboard, two different
quantities**, depending which adapter produced the row.

**The fix does not need to wait for MT5 and does not depend on which key CFT sends today:** the
adapter must record which key it read, or read one and **fail loudly** rather than falling back
silently. **No definition survives an adapter that does not know which quantity it holds.**

## Honest risks

**The strategy is not what you might assume it is.** Of your sixteen rulings, **one reaches a live
trade** — see the ruling ledger. **Three** more discharge only when the risk matrix is wired, and that component is itself waiting on
a grader that runs nowhere. **Linking MT5 tests the plumbing, not the
strategy**, and it is worth being clear about that before the demo account is treated as a verdict
on the trading logic.

**News blocks nothing today** and the calendar key alone will not change that — it is step one of
three.

**The engine has been running one open run for six days.** Before MT5 work starts it should be
stopped cleanly so the run closes and its figures stop being provisional.
