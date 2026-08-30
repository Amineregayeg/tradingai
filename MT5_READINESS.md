# MetaTrader 5 — what is ready, what is blocked, and what you must bring

**Updated 2026-08-30.** For the phase after this one: linking an MT5 demo account and running the
strategy against it.

**Short version: two things wait on you and neither can be worked around. Everything else is either
done or in progress.**

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

### 2. An MT5 demo account

**Nothing can connect without it, and it cannot be created on your behalf.** Required: a broker, a
server name, a login, and a password.

**And possibly a paid bridge.** MT5 has no native REST API. If the transport spike (below) concludes
a third-party bridge is the only workable route, **that is a cost decision for you** — the spike is
required to name the price and what a free tier does not cover.

---

## What is being established now, without waiting for you

| task | what it settles | state |
|---|---|---|
| **T-0096** | **Which transport can actually reach MT5 from this box** — the MetaTrader5 Python package needs a *Windows terminal process*, which on our Linux container is a new service rather than an import. This is the critical path and it does not depend on your decision. | planned, next up |
| **T-0097** | **Units-to-lots conversion** — the seam where a unit error is a money error. Buildable now, no broker needed. | planned |

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

## Honest risks

**The strategy is not what you might assume it is.** Of your sixteen rulings, **one reaches a live
trade** — see the ruling ledger. Four more discharge only when the risk matrix is wired, and that
component is itself waiting on a grader that runs nowhere. **Linking MT5 tests the plumbing, not the
strategy**, and it is worth being clear about that before the demo account is treated as a verdict
on the trading logic.

**News blocks nothing today** and the calendar key alone will not change that — it is step one of
three.

**The engine has been running one open run for six days.** Before MT5 work starts it should be
stopped cleanly so the run closes and its figures stop being provisional.
