# MetaTrader 5 — what is ready, what is blocked, and what you must bring

> **Record correction, 2026-08-30.** The commit that applied these fixes (`020c512`) states
> *"B288 IS ADDED and is REVIEW'S"*. **That is false. `B288` was bid but never written into the
> register**, and I asserted it was on the strength of a peer's report without running the one
> command that checks. The corrections to this document below are unaffected — each was verified
> independently — but the commit message claims something that is not true, and it is pushed and
> immutable. This note is the correction of record.


**Updated 2026-08-30.** For the phase after this one: linking an MT5 demo account and running the
strategy against it.

**Short version: THREE things wait on you. Everything else is either done or in progress.**

**The third is easy to miss and this document previously buried it** — the kill-switch behaviour
below. It is named in the body as a decision only you can make, and it was absent from this
summary. **A reader who acted on the short version would settle two and ship the third as a
default — the one outcome this document says nobody should choose.**

---

## What only you can supply

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
