# The first MT5 connection — a checklist, in order

**Everything here is a question nobody can answer without a real account.** They are scattered across
eight register entries and four task documents; **assembled here so the first connection settles them
deliberately instead of rediscovering them one at a time in production.**

**Ordered by what blocks what.** Each item names where it came from.

---

> **Why this exists.** Every question below is a real unknown, correctly marked as unknown in
> the register — and until now they were **scattered across eight entries and four task
> documents.** Nobody connecting for the first time would assemble them, so they would be
> rediscovered one at a time in production instead of settled in a sitting. **Each item names the
> register entry it comes from, so the reasoning behind it is one lookup away.**

## STAGE 0 — **BEFORE YOU HAVE A WORKING ACCOUNT AT ALL** *(free, 2 minutes)*

### 0.1 What a wrong server name looks like versus a wrong password `B291`

**Question:** are these two distinguishable, or do they arrive as one generic failure?

**Call:** `create_account(...)` **twice on purpose** — once with a deliberately misspelled `server`,
once with a correct server and a wrong `password`.

**Expect:** `E_SRV_NOT_FOUND` and `E_AUTH` respectively.

| answer | implication |
|---|---|
| two distinct codes | the adapter can tell the user *which* thing to fix |
| one generic error | **a day of debugging on every future credential change** — and the adapter must say "server name or password" rather than guessing |

**Unblocks:** the adapter's connection error handling. **Do this FIRST — it is the only item that
needs no working account, and it is free.**

---

## STAGE 1 — **ONE CONNECTION, NO TRADE** *(cheap, ~10 minutes)*

### 1.1 ⚠ Connection state — **this gates everything below it** `B292`

> ### ⚠ REWRITTEN 2026-09-04 — **THE MEMBERS THIS ITEM TOLD YOU TO PRINT DO NOT EXIST** `B341`
>
> **Anyone following the previous wording would have got an `AttributeError` and no answer.** The
> SDK is now installed and introspected, and there is no `terminalState` on the object our adapter
> reads: `get_rpc_connection()` returns nine of the ten members the adapter expects and **no
> connection state at all.**
>
> **The datum is on a different object, and the vendor's version is better than the one this item
> invented.** `MetatraderAccount.connection_status` is a **three-valued enum**:
>
> ```
> CONNECTED  |  DISCONNECTED  |  DISCONNECTED_FROM_BROKER
> ```
>
> **`DISCONNECTED_FROM_BROKER` is this item's whole question, named by MetaApi.** *Connected to the
> cloud but not to the broker* is not a state we have to infer from two booleans — it is one of
> three documented values. The two-boolean pair was ours, and `B335` is what believing in it cost.

**Question:** what does `connection_status` report at each step, and what does `get_positions()`
return while it reads `DISCONNECTED_FROM_BROKER`?

**Call:** `connect()`, then `wait_synchronized()`, printing `account.connection_status` at each
step.

**AND SETTLE THIS WHILE YOU ARE HERE, because it is new and unresolved:** we call `connect()` then
`wait_synchronized()`. The SDK also documents **`wait_connected()`**, described as waiting until the
API server has connected to the terminal **AND the terminal has connected to the broker**. **Whether
`wait_synchronized()` alone implies a broker link is unsettled** — if it does not, then every
adapter method can run against a synchronised connection with no broker behind it, which is the
state this item exists to catch. Print `connection_status` after each of the three calls and the
answer falls out.

**Why it is first:** **an empty position list from a broker we cannot see is `unavailable`, not
`flat`.** Every reading below is uninterpretable until this distinction is confirmed — **and the
kill-switch design depends on it**, because confirmation that reads an empty list and concludes the
book is flat would report success having closed nothing.

**Unblocks:** the kill-switch decision, and every `get_positions()` interpretation.

### 1.1b Does an unreachable broker make the position list silently SHORT? `B293`

**Do this while the broker link is still down from 1.1 — it needs the same induced state and costs
nothing extra.**

**Call `GET /api/positions` and look at what comes back.**

**What is predicted:** the adapter raises honestly, the layer above it catches the error, logs a
warning and **continues** — returning a *shorter list* — and the endpoint's own contract is
*"never an error"*. **So a broker you cannot reach produces a position list that is silently
missing its positions, with nothing at the API surface saying so.**

| what you see | what it means |
|---|---|
| a short list, no indication anything failed | **B293 confirmed on the real system** |
| an error, or a list carrying a per-adapter status | already fixed — check whether T-0111 landed |

**Why it is worth the two minutes:** this is the one prediction on this list that can be **confirmed
by observation rather than by reading the code**, and it is the defect that would let a kill-switch
confirmation step report a flat book it never actually saw.


### 1.2 The account type field — **the safety argument rests on this one** `B284` `T-0100`

**Question:** what does `type` contain, and what happens when the read fails or returns something
outside the three enums?

**Call:** `get_account_information()` → read `type`. **Then disconnect mid-session and call it
again.**

| answer | implication |
|---|---|
| `ACCOUNT_TRADE_MODE_DEMO` | expected for a demo |
| the call raises | *could not ask* — must fail closed |
| a value outside the three | *asked, got something new* — must fail closed **and say so differently** |
| **failure and unknown are indistinguishable** | **we cannot tell a broker outage from a new account type, and a new enum value reads as an outage forever** |

**Unblocks:** `T-0076` — the `is_simulation` decision already in front of you. **Nothing touching
that flag should be built before this is answered.**

### 1.3 Real instrument specifications `B287` `T-0097`

**Question:** what are the actual `volume_min` / `volume_step` / `volume_max` for the instruments we
would trade?

**Call:** `get_symbol_specification(symbol=...)` for each.

**Implication:** the units-to-lots conversion is built and tested **against values we chose**. This
replaces guesses with the venue's own numbers — **and tells us whether the metals case (`contract_size`
100) behaves as assumed.**

### 1.4 Does `disconnect` exist? `B285`

**Question:** the SDK documents `connect()` and `wait_synchronized()` and **no close or disconnect**.

**Call:** inspect the connection object, or ask support.

**Implication:** if none exists the adapter's `disconnect` becomes a documented no-op. **Not a
silent `pass`** — the difference matters when someone later debugs a connection that will not close.

### 1.5 What a `get_positions()` costs `B291`

**Question:** the quota is denominated in **CPU credits**, not requests — *"1000 cpu credits per 1s"*.
Nothing says what our calls cost.

**Call:** poll at our real cadence and watch for `TooManyRequests` / 429; **capture the full payload,
not the status** — it carries `recommendedRetryTime`.

**AND CAPTURE ITS TYPE, not just its presence `B342`.** The adapter's translator does `int()` on
that field, and `recommendedRetryTime` is an **absolute date** rather than a number of seconds — so
a real 429 raises `ValueError` **from inside the rate-limit handler**, which is the one place a
retry must not fail. Record the literal value and its format.

**Implication:** the adapter's backoff either uses the server's recommendation or invents one.
**Only the payload tells us which is possible.**

> ### ⚠ AMENDED 2026-09-04 — **also capture `type(exc).__name__`** `B334`
>
> **This item was cited by an arm it could not settle, and Review measured that.** The adapter
> deliberately does not import the SDK, so it recognises a rate limit by **matching the exception's
> CLASS NAME as a string**. The arm asserting that says it is *"settled by checklist item 1.5,
> which provokes a real 429 and captures the payload"* — and **this item asked for the payload and
> never asked for the name.** The one datum the dispatch depends on was not on the list, so running
> the checklist would have left that arm exactly as unsettled as it is today, **while the citation
> made it look settled.**
>
> **So: print `type(exc).__name__` and `type(exc).__mro__` alongside the payload.** It costs
> nothing extra — the exception is already in hand at the moment the payload is captured.
>
> **THE GENERAL BOUND THIS EXPOSES, and it applies to every `ASSUMES:` marker in the adapter's
> test file:** an arm names the checklist item that would falsify it, and **nothing checks that the
> item on the other end can actually falsify the assumption.** A marker pointing at an inadequate
> item is worse than a marker pointing at nothing, because it reads as discharged.
>
> **CORRECTED 2026-09-04, same day — I overstated the meta-arm in the sentence above `B344`.** This
> paragraph first said *"one arm checks that those references RESOLVE."* **It does not.** Measured
> at `test_t0106_mt5_adapter.py:200`:
>
> ```python
> names_item = "checklist" in marker.lower() or "nothing about the venue" in marker.lower()
> ```
>
> **It checks that the WORD "checklist" occurs in the marker text.** A marker citing
> *"checklist item 99.9"* passes. A marker saying *"settled by the checklist"* and naming no item at
> all passes. **So the join is weaker than the bound I was describing** — I wrote that an inadequate
> item reads as discharged while describing an inadequate arm as adequate, in the same breath, from
> reading it rather than running it. Review found three markers whose cited items cannot falsify
> them (`B343`), which is what an audit finds when the guard checks a word.
>
> **Item 1.1 is the counter-example and shows the machinery works when the item is right:** it
> prints `terminalState.connected`, so running it *would* expose the attribute-spelling question
> that `B335` is about. **The instrument is real; this is its bound.**

---

## STAGE 2 — **NEEDS AN OPEN POSITION** *(one trade required)*

### 2.1 Which optional fields a real broker actually omits `B291`

**Question:** `MetatraderPosition` is 21 required / 7 optional. **Which of the optional ones does
this broker actually send?**

**Call:** open one position, `get_positions()`, print the raw payload.

**Implication:** the mock is built from the required set — **the safest guess and still a guess.** A
field the mock always supplies is a `KeyError` waiting for production.

### 2.2 Are `swap` and `commission` present on an open position? `B291` `B261`

**Question:** both are **optional**. Present-and-zero and absent are different facts.

**Call:** the same payload as 2.1, held **overnight** so swap can actually accrue.

**Implication:** decides whether our `Position` needs them as `Decimal | None` — **and `None` must
mean "not reported", never zero.**

---

## STAGE 3 — **NEEDS A CLOSED TRADE** *(the expensive one, and the most important)*

### 3.1 ⚠ Does a closed deal's `profit` include `swap` and `commission`? `B288` `B291`

**Question:** **is `profit` gross or net?** The docs say only *"deal profit"*, *"deal swap"*, *"deal
commission"* and never say whether the first contains the other two.

**CORRECTED 2026-09-01 (`B331`), and the correction narrows the question.** This read *"and all
three are optional on a deal"* — **wrong, and it disagreed with `MT5_READINESS.md:425` which was
right.** MetaApi's `MetatraderDeal`, quoted in full in `agents/tasks/T-0104/attack-01.md`:

```
commission   number         "deal commission"
swap         number         "deal swap"
profit       number   Yes   "deal profit"      <- REQUIRED
```

**So `profit` is REQUIRED and only `swap` and `commission` are optional.** The question here is
**only ever gross-versus-net, never whether the number is there.**

**Call:** close one position, `get_deals_by_position(position_id=...)`, and **compare `profit`
against the position's realised total.**

| answer | implication |
|---|---|
| `profit` **includes** costs | `realized_r`'s numerator gains components its denominator lacks — **every R reads worse than the geometry** |
| `profit` **excludes** costs | `realized_r` stays geometry-comparable and **silently ignores real costs — R looks fine while the account pays** |
| **`swap`/`commission`** are **absent** | absent is not zero, and nothing downstream distinguishes them — **`B291` measured 6 of 22 optional.** This branch is about those two fields ONLY: **`profit` cannot be absent** |

**Unblocks:** whether `realized_r` — **the number every trade result is judged by** — still means what
it meant on the paper broker. **This is the single most consequential unknown on the list.**

---

## WHAT CANNOT BE ANSWERED ON A DEMO AT ALL

**Does a prop-firm MT5 account report `ACCOUNT_TRADE_MODE_CONTEST`?** `B284`

**Inferred, never observed** — and inferred across the Match-Trader / MetaTrader boundary `B259`,
since the prop firm we trade today does not use MT5's enum at all. **A retail demo will report
`DEMO`, so this stays open until a prop account exists.**

---

## What this list does not prove

**It was derived, and the derivation has a known hole.** The items were found by sweeping the
register for entries that explicitly mark something as unverified — **141 entries parsed, 30
carrying such a marker, 12 relevant here.**

**That finds unanswered QUESTIONS. It does not find PREDICTED BEHAVIOURS.** Item 1.1b above carries
no such marker — it is a prediction about what the system will do, and a prediction is confirmable on
a first connection exactly like a question is. **It was found by someone remembering it existed, not
by the sweep.**

**So: everything on this list is worth doing, and the list is not provably complete.** If something
surprises you that is not here, that is the gap rather than a failure of the individual items.

## THE SHORT VERSION

```
FREE, no account          0.1  error shapes -- deliberately get it wrong twice
CHEAP, one connection     1.1  connection state   <- do before anything reads positions
                          1.2  account type       <- do before anything reads is_simulation
                          1.3  instrument specs    1.4  disconnect    1.5  rate-limit payload
NEEDS A TRADE             2.1  optional fields     2.2  swap overnight
NEEDS A CLOSED TRADE      3.1  profit inclusivity  <- the one that matters most
NOT ANSWERABLE ON DEMO    CONTEST
```

**Stages 0 and 1 are one sitting.** Stage 3 needs a full trade cycle and is the one worth waiting for.
