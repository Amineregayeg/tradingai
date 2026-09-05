# The MT5 programme — everything between here and trading the demo

**Written 2026-09-05, at Malek's request:** *what tasks need to be done before we start fully
setting up MetaTrader 5 for the simulations, and what is each task's goal.*

**How to read this.** Work is grouped into four gates. **A gate is a state of the world, not a
sprint** — each one is a thing that must be TRUE before the next is worth starting, and each names
the tasks that make it true and what each task is FOR. Malek's own items are listed separately at
the end because they interleave rather than queue.

**The honest headline:** *linking* the demo is close — one task, in flight. *Trading* the demo is a
programme: three named changes in the live loop, plus one decision that is Malek's.

---

## Where the line actually falls

```
GATE 1   the adapter is CORRECT            in flight    3 tasks    T-0135 (5 findings), B340, B343
GATE 2   the adapter is REACHABLE          DONE         T-0134 b07a43f + deployed e897d903c
GATE 3   the demo is CONNECTED             blocked      1 task     needs the MetaApi token
GATE 4   the strategy TRADES the demo      SCOPED       3 tasks    needs the T-0076 ruling
```

> **STATUS 2026-09-05: GATE 2 IS DONE.** `T-0134` landed and the server now runs it — the MetaApi
> SDK imports in production and the broker factory answers to `mt5`. **Gate 3 is blocked on nothing
> but the token.**

**Gates 1–3 give you a linked MT5 demo the platform can read**: balance, equity, open positions,
prices, and the broker-reported account type. **That is real and it is the near thing.**

**Gate 4 is what "for the simulations" means** if it means the strategy placing orders on the demo.
It is not a wiring change — **but it is a smaller job than this document said an hour ago**, and the
correction is in Gate 4 below (`B350`).

---

# GATE 1 — The adapter is CORRECT

**The state to reach:** `mt5.py` does not lie about what it did, and no unreadable field can silence
a safety path. **Everything here was found by review or by installing the real SDK, and none of it
needs Malek.**

### `B349` — the unreadable-field regression  *(inside `T-0135`)*

> **NOT a `T-0106` cycle 2, and this document said it was.** `T-0106` is **DONE** — Review passed
> cycle 1 on 2026-09-05 with all four mutation predictions matched, and `B349` came *out* of that
> review rather than being left open by it. It is routed to `T-0135`, which already owns
> `close_all_positions`. **The heading here previously named a cycle that does not exist**, so a
> reader counting Gate 1's tasks counted this one twice.

**Goal: make sure a field we cannot parse cannot disable the kill switch.**

Cycle 1 fixed a real defect — an unparseable price silently became zero — by making `_dec` **raise**
instead of returning `None`. Correct in isolation. But `_to_position` calls it for `swap` and
`commission`, `get_positions()` builds every position through `_to_position`, and
`close_all_positions()` opens with:

```python
try:
    positions = await self.get_positions()
except Exception as exc:
    raise BrokerError("... could not enumerate the open positions ... Nothing was attempted.")
```

**So one unreadable `swap` on one position, and the kill switch closes nothing and says so.** The
enumeration is all-or-nothing and the raise is uniform, and the two compose into a denial of the
one operation that must never be unavailable.

**This is the most urgent item in the document** and it is a regression introduced yesterday, not an
inherited defect. **Do not fix it by reverting to the flooring** — that reintroduces the zero-price
defect. The shape wanted is a position that carries its own unreadable-field marker so the *book*
can still be enumerated while the *field* stays refused.

### T-0135 — the kill-switch accounting `B335` `B337` `B338` `B342` `B349`

**`B349` is routed here rather than to a cycle 2**, because this task already owns the member.

**Goal: make the kill switch's report true, because Malek's ruled property is satisfiable by a
false one.**

Four findings on one member, all measured:

| | what is wrong | why it matters |
|---|---|---|
| `B335` | `_require_broker_link` **fails open** when the guard attribute is absent — and the SDK object it reads has no such attribute at all, so **the guard never runs** | `close_all_positions` on a down link returns `[]`, which says *there was nothing to close* — the exact collapse its own docstring says it prevents |
| `B337` | the position whose close **was sent** is reported `NOT ATTEMPTED`, reason *"the close loop never reached this position"* | affirmatively false about our own action, at 3am. **Ruled: mark it FAILED with a reason saying the close was sent and the outcome never observed.** That uses Malek's vocabulary, not a fourth state |
| `B338` (2nd half) | the report is keyed on `position.id` and a missing id defaults to `""` | two positions collapse into one row — a position open when the switch was pulled is reported **nowhere** |
| `B342` | `_rate_limited` calls `int()` on `recommendedRetryTime`, which is an **absolute date** | a real 429 raises `ValueError` **inside the retry handler** — the one place a retry must not fail |

**Order matters and is counter-intuitive** (Review measured it): land the parametrized arm **first**
on unconsolidated code, then consolidate. And the variable that decides whether `B342` is visible is
the **fixture's value type** — integer `7` gives 6 passed, the venue's ISO instant gives 6 failed.

### B340 — the arms that cannot see their own subject

**Goal: stop a green suite from meaning "unverified".**

**Semantic mutations to `mt5.py` survive the arms at a rate Review has now measured twice**, and
the second number is the one to use:

```
first pass    33 of 67 survive   -> "a green suite is 50.7% of a verification"
CORRECTED                        -> 57.3%   (B354)
```

**The first figure came from a contaminated baseline and I had quoted it here.** Review's own
mutation harness leaves a surviving mutant on disk when a run is interrupted, and the next run
adopts it as its baseline — **and a surviving mutant passes every arm, so "the baseline is green"
cannot detect it.** The instrument was auditing itself and the audit is the finding. The survivors **cluster**: five of the seven rate-limit dispatch sites can be
*inverted* with the suite green. **One parametrized arm kills all five with the seven copies left
exactly where they are.**

### ~~B352~~ — the live-trading gate has no arm at all — **DONE inside `T-0134`**

**Goal: put a test behind the single centralised check that stands between a stored
`observe_only=False` and a live-write adapter.** **Already done** — `T-0134` fixed it in the same
commit that found it, and `test_t0134_mt5_construction.py` carries twelve arms including the
must-miss that fails if the gate is welded shut. **I queued this as open without reading Execute's
handoff; verified closed.**

> **One half of it is genuinely still open and it is smaller.** All four gate-effect arms pass
> `"cft"`, so **nothing drives the forcing on the mt5 path.** The structural arm asserts the guard
> is *positioned* before every return — and a guard correctly placed can still not run for a
> branch, which is exactly what "my branch is the second caller" makes non-theoretical. Folded into
> Execute's next commit touching that file.

**Found while `T-0134` was hoisting it** — the check had to move out of the CFT branch so a second
broker branch could not return before it, and moving a guard is the moment to ask what fails if it
stops working. **The answer was nothing.**

```
grep -rn ALLOW_LIVE_TRADING tests/   ->  two files, BOTH prose in docstrings
grep -rn "setenv|environ\[" tests/  |  ALLOW_LIVE   ->  no results
```

**Nothing in the suite sets the variable.** And the two files that mention it name it as the
upstream control they are defending *behind* — so a defence-in-depth argument is resting on a gate
that nothing checks. **`T-0134` just added a second caller to it**, which is the moment this stops
being theoretical.

### B343 — three assumption markers that cannot be discharged

**Goal: stop a citation from reading as a discharged assumption when the thing it cites cannot
settle it.**

Every arm names the checklist item that would falsify it. **Three of twenty-one cite items that
cannot** — and it is one mechanism rather than three accidents: the citations cross the
DEAL/POSITION axis. **And the arm policing this checks that the WORD `checklist` appears in the
marker** — `"checklist item 99.9"` passes, and so does `"settled by the checklist"` naming nothing.

---

# GATE 2 — The adapter is REACHABLE

**The state to reach:** something in the application can construct an MT5 connection, and the code
that does is running on the server.

### ~~T-0134~~ — make `mt5` constructible — **DONE 2026-09-05, `b07a43f`**

**Goal: turn a class that only its own test file can instantiate into something the platform can
connect with.** **Landed.** `_MT5_ALIASES = {"mt5", "metatrader5", "metatrader", "metaapi"}` and the
factory constructs `MetaTrader5Adapter` from an account factory. **The demo is now linkable as soon
as there is a token.**

Today `_make_adapter` branches on one alias set and ends `raise ValueError("Unsupported broker")`.
A `broker_connections` row naming `mt5` raises.

**Its shape changed under `B341` and it is no longer "add a branch":**

```
RpcMetaApiConnectionInstance        ALL the reads          no terminal_state
StreamingMetaApiConnectionInstance  terminal_state         NONE of the reads
```

**No single connection serves both the data and the guard.** The adapter holds the
`MetatraderAccount`: reads through `account.get_rpc_connection()`, reachability through
`await account.reload()` then `account.connection_status`, **failing closed on an unrecognised
value.**

**Decided, and the reasoning is recorded so it can be overruled:** `reload()` costs one REST call on
a connection we already hold; the streaming alternative costs a **second permanent websocket whose
only job is answering one boolean pair**, bought before an account exists to point it at.

**It must also decide and record where the MetaApi token comes from** — environment variable versus
the credential blob on the connection row — because that is a security property, not a style
choice. **And it must reach the existing `ALLOW_LIVE_TRADING` guard rather than returning before
it**; a branch that returns early would be a new unguarded real-money path, which is precisely why
the OANDA branch was deleted from that function.

**This task delivers READS and cannot deliver trading**, and its commit must say so.

### ~~The deploy~~ — **DONE 2026-09-05, verified in the running container**

**Goal: make the server run the code this document describes.**

```
api serving   e897d903c   ==   local HEAD e897d903c
in-container  import metaapi_cloud_sdk            -> OK
              MetaTrader5Adapter.broker_name      -> "mt5"
```

**Verified inside the container rather than inferred from the deploy command exiting.** The
preflight was clean before it went: schema matched at `0008` so no migration ran, engine down, zero
open positions — *"deploying now settles nothing and the ledger will not move."* `web-build` was
recreated alongside `api`, closing the web/api commit gap the preflight flagged.

**Gate 2 is complete. The only thing between you and a linked demo is the MetaApi token.**

#### Why it mattered, kept because the gap reopens on every commit

```
was   deployed 99849e972      main   25 commits ahead
```

Nothing from this week is on the server: not the adapter, not the SDK pin, not the kill-switch
work. **One command, and the order is the entrypoint's rather than yours:**

```
ssh pfe-vps 'cd /docker/tradingai && docker compose up -d --force-recreate api'
```

Run `agents/deploy_preflight.py` first. **Do not run `alembic upgrade head` separately** — the
migration lives in the image and running it first executes the OLD one.

---

# GATE 3 — The demo is CONNECTED

**The state to reach:** the platform is talking to Malek's demo account and we know what the venue
actually says, rather than what its documentation says.

### The first-connection checklist — `MT5_FIRST_CONNECTION.md`

**Goal: replace every assumption in the adapter with an observation, in the order that makes each
answer interpretable.**

**This needs the MetaApi token and nothing else from us.** The items, in dependency order:

1. **0.1 — get it wrong twice on purpose.** Misspelled server, then bad password. Free, needs no
   working account. **If they arrive as one generic error, every future credential change costs a
   day.**
2. **1.1 — connection state.** `await account.reload()` before each read, or the value is stale by
   construction. **An empty position list from a broker we cannot see is *cannot see*, not *flat*,**
   and the kill switch depends on the difference. Also settles whether `wait_synchronized()` alone
   implies a broker link or whether `wait_connected()` is required.
3. **1.2 — the account type.** `DEMO | CONTEST | REAL`, broker-reported, per call. **The safety
   argument rests on this one field.**
4. **1.3 — real instrument specifications.** Contract size, volume min/max/step. **`default_pairs`
   is deliberately empty** — the ruling settles the asset class, not whether this broker calls it
   `BTCUSD`, `BTCUSD.x` or `BTCUSDm`.
5. **1.5 — a real 429 payload, and the TYPE of `recommendedRetryTime`.**
6. **3.1 — does a closed deal's `profit` include swap and commission?** Needs a closed trade, so it
   cannot be day one. **It decides whether your R-multiples still mean what they meant on the paper
   broker.**

---

# GATE 4 — The strategy TRADES the demo

**The state to reach:** the engine places orders on the MT5 demo. **This is the gate that is not a
task list yet.**

### The order path — and it is BINDING, not BUILDING `B346` `B350`

**Goal: let the engine's existing order path terminate somewhere other than a simulator built inside
the process.**

> **CORRECTED 2026-09-05, hours after this document was first written.** `B346` — mine — said the
> order path *reaches no adapter*. **That is wrong and Review measured it.** `PaperBroker` and
> `SimPropFirmBroker` are both `BrokerAdapter` subclasses that define `place_order`, so **the path
> does not stop short of an adapter: it terminates in one, end to end, every time.** The one it
> terminates in is always simulated.
>
> **The two statements dispatch different work, which is why the correction is worth more than the
> conclusion:**
>
> ```
> "reaches no adapter"     -> the plumbing does not exist; this means BUILDING an order path
> "reaches a SIM adapter"  -> the plumbing exists end to end; this means BINDING into it
> ```
>
> **My conclusion survives and is firmer.** Linking MT5 gives reads and cannot give trading — **not
> because a path is missing but because the destination is hardcoded**, and a hardcoded destination
> is not fixed by adding an adapter.

**So the work is three named changes rather than an open question:**

```
crypto_loop.py:157/162   self.paper is constructed INLINE in __init__ -- no injection point at all
crypto_loop.py:168/794   ExecMode.PAPER is hardcoded at BOTH construction sites
broker_mode              selects between TWO SIMULATORS -- it is not a live/sim switch
```

**Three deliberate refusals stand behind that, and all three are safety features working:**

1. `ExecMode` has **no LIVE member** — the branch was removed, not disabled.
2. `execute()` **raises** on any adapter reporting `is_simulation=False`.
3. `MetaTrader5Adapter.is_simulation` **returns `False`**, pending `T-0076`.

**So this gate is a design decision before it is a task**, and the decision is whose refusal to
relax and how. **It must not be done by making the MT5 adapter claim `is_simulation=True`** — that
would satisfy the assertion by lying to it.

### The units→lots conversion — built, and wired to nothing

**Goal: stop a unit error from becoming a money error.**

`units_to_lots()` exists in `lots.py` (T-0097, DONE) and **has zero callers.** Meanwhile
`service.py` binds `lot_size=round(units, 8)` and the CFT adapter sends that raw as `volume`
(`B302`). **MT5 sizes in lots with broker-set minimums and step increments.** The conversion must
round to the broker's step, clamp to its limits, and **refuse rather than silently round to zero** —
a zero-lot order the venue rejects would be a success report over an action that never happened.

**It needs Gate 3 item 1.3 first**, because the step and the minimum are the broker's numbers and
we do not have them.

### The symbol map

**Goal: know what this broker calls Bitcoin.**

`default_pairs` is empty on purpose. **Filled in from the ruling rather than from the venue, it
would be inventing a vocabulary.** Gate 3 item 1.3 supplies it.

---

# What waits on Malek

**None of these blocks Gates 1 or 2.** They are listed in the order they become blocking.

### 1. The MetaApi token — **blocks Gate 3 entirely**

`app.metaapi.cloud/token`. **The demo account is already in hand; this is the other half.** It is
a paid service whose published pricing page 404s, so **signing up is also how we learn the price.**
Put it in a file rather than pasting it.

### 2. Authorising the deploy — **blocks Gate 2's second half**

25 commits, including the first run of code that has never executed in production.

### 3. Lifting the engine hold

Down since 2026-08-30 by his own decision. **Its stated condition — `T-0119` landed, someone
watching — has been met.** Not needed for linking; needed for any run.

### 4. The `T-0076` ruling — **blocks Gate 4 and nothing else**

`is_simulation` for an MT5 demo, and it has three states rather than two:

| venue says | means |
|---|---|
| `DEMO` | no real money, real broker connection |
| `REAL` | real money |
| **`CONTEST`** | **neither — and it has no ruling at all** |

`ExecutionService` asks *is real money at risk* — a demo says no. The reconciler asks *are these
records a third party's* — a demo says yes. **There is no value of the flag that is correct for
both**, which is why it is a decision and not a derivation.

### 5. Optional — a fourth kill-switch disposition `B337`

*Attempted, outcome unknown*, as its own state rather than living in a FAILED row's reason. **An
improvement, not a gap. Nothing waits on it.**

---

## What this document does not promise

**No date.** Gate 1 is four tasks of known shape. Gate 2 is one task in flight plus a command. Gate
3 is a checklist that cannot start without a token. **Gate 4 now has three named changes and an
unmade decision** — better than the unscoped piece it was this morning, and still not something to
put a date on while the decision is open.

**And the thing worth remembering when the demo does connect:** the adapter was written from
documentation, passed 130 tests against a mock, and the first time a real package was installed it
turned out to be reading the wrong object. **The demo account is the next instrument of that kind.**
Expect it to find things, and treat Gate 3 as measurement rather than as confirmation.
