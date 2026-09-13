"""LiveCryptoLoop — real-time crypto PAPER trading spine.

Polls Binance for BTC/ETH, marks the PaperBroker to the live price (firing
SL/TP), runs the validated strategy on each newly-closed entry-TF bar, executes
via the mode-gated ExecutionService (PAPER), and pushes ticks / positions /
account over the existing WebSocket. No real broker is touched — paper only.
"""
from __future__ import annotations

import asyncio
import json
import os
import urllib.request
import uuid
from collections import deque
from datetime import date, datetime, timedelta, timezone

from app.core.exceptions import BrokerError
from app.models.decision_record import REJECTION_VENUE_RAISED
from app.core.logging import logger, redact_for_storage
from app.services.broker.paper import PaperBroker

#: `broker_mode` values that select the ALPACA venue rather than an in-process simulator.
#: A set rather than a literal so the spelling lives in ONE place (`B184`); `manager.py`
#: keeps its own aliases for the CONNECT path, which is a different entry point.
_ALPACA_MODES = {"alpaca", "alpaca_paper", "alpaca-paper"}
from app.services.broker.alpaca import AlpacaUnprotectedPositionOpen
from app.services.broker.base import readable_quantity
from app.services.execution.service import ExecMode, ExecutionService
from app.services.live import fixed_config as fixed
from app.services.live import exit_shadow
from app.services.live.entry_comparison import compare_entry
from app.services.live.news_context import (
    NewsContext,
    build_news_context,
    fetch_calendar_events,
)
from app.services.live.shadow import _bars_from_frame
from app.services.telemetry.ny_time import to_ny
from app.services.live.strategy_step import evaluate_latest_bar_traced
from app.services.rules.exit_001_v1_model import (
    DECLARED_SESSION_CLOSE,
    DECLARED_SESSION_FLATTEN,
    SessionClose,
)
from app.services.market_data.sources.binance import BinanceSource
from app.services.ws.manager import ws_manager

_DEFAULT_SYMBOLS = {"BTC/USD": "BTCUSDT", "ETH/USD": "ETHUSDT"}

# Bumped whenever the decision code path changes materially — part of every
# DecisionRecord's code_path_hash so decisions are reproducible/auditable.
ENGINE_CODE_VERSION = "ict-v2-lookahead-fixed"


def _ticker_price(binance_symbol: str) -> float | None:
    for base in ("https://api.binance.com", "https://data-api.binance.vision"):
        try:
            url = f"{base}/api/v3/ticker/price?symbol={binance_symbol}"
            return float(json.loads(urllib.request.urlopen(url, timeout=8).read())["price"])
        except Exception:  # noqa: BLE001 - try next mirror
            continue
    return None


def _as_decision_id(dec_id):
    """Coerce a decision id to what the column's type expects.

    `_open_decision` stores `str(rec.id)` while `DecisionRecord.id` is a UUID column.
    Postgres accepts the string and SQLite does not — `'str' object has no attribute 'hex'`
    — so the comparison worked in production and raised under the test backend, where
    `_resolve_decision`'s own `except` would have swallowed it into a log line and returned.
    **A resolution path that silently does nothing under one backend is the shape this
    module's `_as_utc` comment already warns about**, one type over.
    """
    import uuid

    if isinstance(dec_id, uuid.UUID):
        return dec_id
    try:
        return uuid.UUID(str(dec_id))
    except (ValueError, AttributeError, TypeError):
        return dec_id


def _with_exit_plan(reasons: list[str] | None) -> list[str]:
    """Append `EXIT-001`'s two-leg plan to a decision's reasons. **`ARM 5`.**

    **A SINGLE `expected_r` FOR THIS PLAN WOULD BE A FABRICATION, NOT A SIMPLIFICATION.** The
    70% leg has a ratified target — `PARTIAL_AT_R` = 2.0R. The 30% runner has NONE: `EXIT-003`
    is OPEN in the registry and the runner is passive by contract until Salim rules. Any scalar
    blending them invents the number the registry deliberately leaves open, and it would arrive
    inside a column the feedback loop treats as ratified doctrine.

    So the PLAN is recorded and the scalar is not. It rides on `reasons`, which is the surface
    that actually reaches the database — a JSON list nothing parses, so this is additive and
    old rows keep loading. `expected_r` stays NULL, which is what `tp is None` already produced.

    **What this does NOT do, stated so it is not mistaken for done:** `gap_r` remains NULL, so
    the feedback loop still has no expected-versus-realized comparison to learn from. Giving it
    one means a PER-LEG gap — the 70% leg against 2.0R — which is a change to `feedback.py`'s
    consumers, not to what is recorded here.
    """
    from app.services.rules.exit_001_v1_model import (
        PARTIAL_AT_R, PARTIAL_FRACTION, RUNNER_FRACTION,
    )

    return [
        *(reasons or []),
        (
            f"exit plan: {PARTIAL_FRACTION:.2f} @ {PARTIAL_AT_R:.1f}R "
            f"+ {RUNNER_FRACTION:.2f} @ UNDEFINED (EXIT-003 OPEN); "
            "no scalar expected_r — a blended figure would invent the open leg"
        ),
    ]


#: **`B417`. `:.3f` PRINTS EVERY CRYPTO SIZE AS `0.000`.**
#:
#: Measured against the venue's own numbers (`T-0139`): BTC's minimum order is `0.000012941` and a
#: 1% risk entry on a five-figure account is `1e-4` to `1e-3`. So `f"{units:.3f}"` rendered
#: **every BTC entry the engine has ever logged** as `Entered BTC/USD LONG 0.000`, and every runner
#: remainder as `0.000 units run on`. The trade was real, the number in front of the operator was
#: zero, and a size that reads as zero is indistinguishable from the `NON_POSITIVE_SIZE` refusal
#: this codebase has a rejection code for.
#:
#: Nine decimal places because that is the venue's `min_trade_increment` (`1e-9`) — the grid sizes
#: are actually quantised to — with trailing zeros trimmed so a whole lot still reads as `0.5`
#: rather than `0.500000000`.
def _fmt_units(units: float | None) -> str:
    if units is None:
        return "unknown"
    return f"{units:.9f}".rstrip("0").rstrip(".") or "0"


#: **THE ACTIVITY KINDS A BLOCK CAN PRODUCE.** `halt` means nothing will trade until someone acts;
#: `skip` means this bar was not taken and the next one might be.
BLOCK_HALT = "halt"
BLOCK_SKIP = "skip"


class BlockReason(str):
    """A block reason that carries HOW SERIOUS it is, structurally rather than in its prose.

    **`B415`.** `_tick_symbol` decided halt-vs-skip with `block.startswith("KILL SWITCH")`. That is
    a **prose prefix**, so the classification depended on the first eleven characters of a sentence
    written for a human: reword the kill-switch reason and an armed kill switch is surfaced to the
    operator as a routine `skip`, and **any halt added later is a `skip` by default** — which is
    how `T-0141`'s named halt would have arrived, defeating the ruling through the back door.

    A `str` subclass rather than a pair or a dataclass, deliberately: `_entry_block_reason`'s answer
    is ALSO persisted as `engine_policy` prose on the shadow's `setup_evaluation` record, so the
    value has to stay a string for that contract to be unchanged. This keeps one object with one
    identity and puts the classification beside the text instead of deriving it from the text.
    """

    kind: str

    def __new__(cls, text: str, *, kind: str) -> "BlockReason":
        if kind not in (BLOCK_HALT, BLOCK_SKIP):
            raise ValueError(f"unknown block kind {kind!r}")
        obj = super().__new__(cls, text)
        obj.kind = kind
        return obj


#: The named halt for `B413`: the venue reported a partial fill and we could not establish the size
#: of the position it left. **A distinct value, per `M-7`** — sharing one with the operator pause or
#: the kill switch would make *halted because a partial could not be sized* and *someone pressed
#: stop* the same event to every count and every panel.
HALT_PARTIAL_UNSIZED = "a partial fill left a position we could not size"

#: **`B429`.** The venue would not accept the stop AND flat was not observed after cancelling
#: the entry and closing the position — a close still resting counts, so a
#: live position may exist with no stop at the venue and none in process. **Its own value,
#: per `M-7`** — sharing `HALT_PARTIAL_UNSIZED` would make *a partial we could not size* and
#: *a position we could not protect* the same event to every count and every panel, when the
#: operator action differs: one is reconcile the SIZE, this one is place a stop or flatten.
HALT_UNPROTECTED_POSITION = "a position may be open at the venue with no stop"

#: **`T-0130`. AN ORDER RESULT IS ONE OF THREE THINGS, AND ONLY TWO ARE ENUMERATED.**
#:
#: ```
#: FILL_BEARING_STATUSES   the venue acted on the order              -> track the position
#: REFUSAL_STATUSES        affirmatively NOT acted on                -> a rejection row
#: anything else           UNRESOLVED: absent, None, an acknowledgement ("NEW", "ACCEPTED"),
#:                         a terminal state that may carry a fill ("CANCELED")   -> halt
#: ```
#:
#: **The third class is the complement, never a list.** Enumerating the statuses that mean "not
#: yet known" would be a third encoding of order status beside `alpaca.py`'s venue sets, and it
#: would be wrong the day a venue sends one nobody listed — which then lands in whichever branch the
#: `else` is. Before `T-0130` the `else` was the REJECTION branch, so an acknowledged order the
#: venue may still fill was recorded as refused, and `service.py` defaulted absence to `FILLED`.
#:
#: **Both refusal spellings are listed because both are emitted**: `service.py` returns `"rejected"`
#: from its five pre-order refusals and `"REJECTED"` from the venue-error paths, and the adapters'
#: `place_order` returns `"REJECTED"`. No case-folding — it would accept spellings nobody emits.
#: The two sets are disjoint; an arm asserts it, because a name in both would be a fill AND a
#: refusal and the first branch tested would win silently.
#:
#: **TUPLES, NOT FROZENSETS, ON PURPOSE** (review's K-3). A forwarded venue reply can carry `{}` or
#: `[]` as its status, and `{} in frozenset(...)` RAISES TypeError — in the loop that escapes the tick
#: with no row and no halt. Tuple membership compares by equality and returns False. The classifier
#: also tests `isinstance(status, str)` before any membership test, which states the intent where it is
#: needed and protects any future set — and is the only thing that stops a status whose `__eq__` raises.
FILL_BEARING_STATUSES = ("FILLED", "PARTIALLY_FILLED")
REFUSAL_STATUSES = ("REJECTED", "rejected")
#: **NOT FROM THIS LOOP.** `service.py` returns `"observed"` only in `ExecMode.OBSERVE`, which sends
#: no order; this loop constructs its `ExecutionService` in `ExecMode.PAPER` and never reassigns it,
#: so the status cannot reach `_tick_symbol`. Listed so the producer-vocabulary arm has a home for it,
#: and NOT handled: were the loop ever built in OBSERVE, it would fall into UNRESOLVED and halt every
#: signal with "find the order at the venue" for an order never sent — so an arm pins the mode, and
#: that change fails a test before it fails an operator (manager; `B430`'s shape, safe by one
#: constructor argument rather than by design).
NOT_FROM_THIS_LOOP_STATUSES = ("observed",)

#: **`T-0130` / review's K-11. WHAT AN ORDER RESULT MEANS IS DECIDED IN EXACTLY ONE PLACE.** The loop
#: used to decide it at five sites — two literal comparisons in `_position_units`, three membership
#: tests in `_tick_symbol` — which is five guards to keep in step and `B184`'s divergence waiting to
#: happen. Every site now asks `classify_order_status`, and an arm asserts no status membership test
#: or status-literal comparison exists anywhere else in this module.
ORDER_FILLED = "filled"
ORDER_PARTIALLY_FILLED = "partially_filled"
ORDER_REFUSED = "refused"
ORDER_UNRESOLVED = "unresolved"
FILL_OUTCOMES = (ORDER_FILLED, ORDER_PARTIALLY_FILLED)


def classify_order_status(status: object) -> str:
    """The class of an order result's `status`: filled, partially filled, refused, or UNRESOLVED.

    **Pure, total, and never raises for any value a venue reply can carry.** Only a string is classified
    (review's K-3): `None`, a number, `{}`, `[]`, or a non-`str` object whose `__eq__` raises are
    UNRESOLVED before any comparison runs. A `str` SUBCLASS with a raising `__eq__` would pass the guard
    and reach the membership test — JSON cannot produce one, so it is stated rather than guarded. The
    third class is the COMPLEMENT — nothing enumerates "not yet known", so a status nobody listed
    lands here and halts rather than in whichever branch happens to be the `else`.
    """
    if not isinstance(status, str):
        return ORDER_UNRESOLVED
    if status in FILL_BEARING_STATUSES:
        return ORDER_PARTIALLY_FILLED if status == "PARTIALLY_FILLED" else ORDER_FILLED
    if status in REFUSAL_STATUSES:
        return ORDER_REFUSED
    return ORDER_UNRESOLVED


#: **`T-0130`.** `place_order` returned something that is neither a fill nor a refusal, so the
#: engine cannot say whether it holds a position. Its own value, per `M-7`: the operator action is
#: FIND THE ORDER AT THE VENUE, which neither reconciling a size (`HALT_PARTIAL_UNSIZED`) nor
#: placing a stop (`HALT_UNPROTECTED_POSITION`) is.
HALT_ORDER_UNRESOLVED = "an order's outcome is unresolved, so a position may exist that is not tracked"

#: **`B428a`. WHAT THIS LOOP NEEDS FROM ITS BROKER THAT THE CONTRACT DOES NOT PROMISE.**
#:
#: `BrokerAdapter` guarantees order placement — `place_order`, `close_position`, `get_positions`
#: and the rest. It says nothing about POSITION MANAGEMENT, and this loop requires three members
#: that only the in-process simulators have:
#:
#: ```
#: on_tick    EVERY tick, unguarded, on the path to the strategy evaluation   -> REQUIRED
#: _closed    warm-up replay ledger only                                      -> not required
#: balance    warm-up replay cash only                                        -> not required
#: ```
#:
#: **ONLY `on_tick` IS REQUIRED, and the two that are not were nearly required by mistake.**
#: Every `_closed`/`balance` use is inside `warmup()`, which returns at `if venue != "paper"`
#: before reaching any of them — and `status()`'s fallback reads `_closed` through a guarded
#: `getattr` **with a designed report for its absence**. Requiring them would have contradicted
#: that report and refused a venue adapter that implements `on_tick` perfectly well, replacing a
#: precise message with a blunt one. Caught by the review seat against the first version of this
#: list, whose own author had written the guarded fallback an hour earlier.
#:
#: **`AlpacaAdapter` has none of them**, so on that venue `_tick_symbol` raised `AttributeError`
#: at `:2051` — BEFORE the strategy evaluation at `:2062` — and `_loop`'s per-symbol handler
#: turned it into a `logger.warning`, every symbol, every poll, forever. The engine reported
#: `running=True`, `paused=False`, `halt_reason=None`. **Healthy, and unable to trade.** An
#: operator watching a running engine take no trades reads a quiet market (`B179`).
#:
#: THE LIST IS DERIVED, NOT REMEMBERED: `test_b428_broker_capabilities.py` walks this module for
#: every `self.paper.X` and fails if one is neither in the `BrokerAdapter` contract, nor declared
#: here, nor explicitly exempt. **A missing method is a category, not one incident** — nothing
#: required `on_tick` to be in the base class and nothing will require the next one either.
REQUIRED_BROKER_CAPABILITIES: tuple[str, ...] = ("on_tick",)

#: The block reason when they are absent. A named refusal, not a warning.
BLOCK_BROKER_INCAPABLE = "broker cannot manage positions"


class LiveCryptoLoop:
    def __init__(
        self,
        symbols: dict[str, str] | None = None,
        entry_tf: str = fixed.ENTRY_TF,
        bias_tf: str = fixed.BIAS_TF,
        starting_balance: float = fixed.STARTING_BALANCE,
        risk_pct: float = fixed.RISK_PCT,   # pre-registered FIXED (not a tunable knob)
        max_concurrent: int = fixed.MAX_CONCURRENT,
        poll_interval: float = fixed.POLL_INTERVAL,
        broker_mode: str | None = None,
    ) -> None:
        # The defaults ARE the configuration (services/live/fixed_config.py).
        # The arguments survive for tests, which need to build a loop with a
        # deliberately odd shape; nothing in the application passes any of them.
        self.symbols = symbols or dict(fixed.SYMBOLS)
        self.entry_tf = entry_tf
        self.bias_tf = bias_tf
        self.risk_pct = risk_pct
        self.max_concurrent = max_concurrent
        self.poll_interval = poll_interval
        # Broker: "paper" = plain simulation; "sim" = SimPropFirmBroker, which
        # enforces the prop-firm challenge rules (daily loss / drawdown / target).
        # Both are is_simulation=True; no real order is ever possible from this
        # loop. There is deliberately no ENGINE_BROKER environment override any
        # more: an env var is a second place the configuration can live, and the
        # whole point of fixed_config is that there is only one.
        self.broker_mode = (broker_mode or fixed.BROKER_MODE).lower()
        self._marks: dict[str, float] = {}
        #: EXIT-001's plan per OPEN position id: {"price", "fraction", "direction", "pair"}.
        #: Removed when the partial fires or the position closes.
        #:
        #: IN MEMORY ONLY, and the consequence is stated rather than left to be discovered: a
        #: restart between entry and the 2R touch loses the plan, and that position then rides
        #: to STOP_HIT or SESSION_CLOSE as a whole. It fails toward NOT taking a partial, which
        #: is a worse outcome and not an unsafe one — no order is placed that doctrine forbids.
        self._tranche_plans: dict[str, dict[str, Any]] = {}
        #: Position ids already partialled, kept so a price oscillating across the 2R level
        #: cannot bank 70% twice. Cleared with the plan.
        self._partialled: set[str] = set()
        #: NY date of the last session close performed, so 19:00 fires once a day.
        self._last_session_close: date | None = None
        self._bind_broker(starting_balance)

        # PRICE SOURCE — analyse the venue you execute on.
        #
        # With fixed_config.PRICE_SOURCE = "cft" the loop reads Crypto Fund
        # Trader's own candles instead of Binance's. That matters because the
        # strategy trades
        # structure: measured over 300 matched 1H bars, CFT closes sit a
        # near-constant -0.0485% below Binance (a BID-side spread, harmless to
        # scale-invariant structure) but individual bar RANGES differ by up to
        # 0.117% of price — and a high or low that moves by that much can create
        # or erase the very FVG the entry depends on.
        #
        # Binance stays the DEFAULT deliberately. CFT serves only ~125 days of
        # 1H history against the ~470 the corrected backtest needs, and the CFT
        # path requires the browser bridge to be up. Switching is an explicit
        # decision, not something that changes underneath anyone.
        source_name = fixed.PRICE_SOURCE
        if source_name == "cft":
            from app.services.market_data.sources.cft import CFTSource

            self.source = CFTSource()
            self.price_source_name = "cft"
            logger.info("Price source: Crypto Fund Trader (execution venue)")
        else:
            self.source = BinanceSource()
            self.price_source_name = "binance"
        self._last_eval: dict[str, datetime] = {}
        # pair -> id of the DecisionRecord opened for the currently-open position,
        # so a close can be resolved back to the decision that caused it.
        self._open_decision: dict[str, str] = {}
        self._running = False
        self.paused = False
        #: **NOT CLEARED BY `reset` OR `stop`, and that is the ruling's direction rather than an
        #: oversight.** `paused` is cleared by both, because an operator pause is resolved by the
        #: operator. This is not: it says a position of unknown size may exist AT THE VENUE, and
        #: restarting the engine does not make that position known. Clearing it silently on the
        #: next start would re-enter the hole it exists to stop us trading into. Reconciliation is
        #: what legitimately clears it, and reconciliation is the task after this one (`B413`).
        self._halt_reason: str | None = None
        #: **`B428a`.** Names from `REQUIRED_BROKER_CAPABILITIES` the bound broker does not have.
        #: Empty is the healthy state and it is EARNED — `_bind_broker` recomputes it on every
        #: bind, so it cannot be stale from a previous broker. Read by `status()`, by
        #: `_entry_block_reason` and by `start()`, which refuses rather than run blind.
        self.broker_missing: tuple[str, ...] = ()
        #: **`M-6`. WHY THE DURABLE RECORD OF A HALT IS MISSING, when it is.**
        #:
        #: The halt writes two records — a `DecisionRecord` for the corpus and an `Alert` for the
        #: operator — and neither may kill the loop (`M-5`). But *must not kill the loop* and
        #: *must not vanish silently* pull against each other, and the obvious reconciliation
        #: (`except Exception: logger.error(...)`) is **`B403` rebuilt inside the fix for
        #: `B413`** — we are adding the Alert precisely because a log line is not a record, so
        #: satisfying *must not vanish* with a log line satisfies it with the thing already known
        #: to be insufficient.
        #:
        #: So the failure goes where someone is already looking: `status()`, which is the surface
        #: the operator is on BECAUSE of the halt. The halt then reports both *a position of
        #: unknown size exists* and *its durable record could not be written*.
        self.halt_record_failed: str | None = None
        #: The scanning task, owned by start()/stop(). None when stopped.
        self._task: "asyncio.Task | None" = None
        #: Sequence number for shadow (M9 Stage A) telemetry within this scan.
        self._shadow_seq = 0
        #: pair -> {bar CLOSE time (UTC) -> (omission_class, reason)}.
        #:
        #: WHY THIS IS NOT A COUNTER, and the distinction is the whole of T-0011's
        #: criterion 2. `scan_census` derives BOTH of its counts from outside this loop —
        #: bars from the series, evaluations from the store — and computes the unemitted
        #: set by DIFFERENCE. This map supplies only the REASON a bar is missing.
        #:
        #: So losing it costs an attribution, never a count. A restart that wiped a
        #: counter would shrink bars_observed, evaluations_emitted and unemitted_bars
        #: together, the reconciliation would still hold, and half a day counted honestly
        #: would be indistinguishable from a whole one. A restart that wipes this map
        #: leaves the census reporting the same omissions and saying it cannot explain
        #: them — which C-13 reports as undocumented logic, correctly.
        self._omissions: dict[str, dict[datetime, tuple[str, str]]] = {}
        #: pair -> the NY session date of the last bar seen. The census for a date is
        #: emitted when a bar from the NEXT date arrives: a day's bars cannot be counted
        #: until the day is over, and guessing early is how a partial window gets reported
        #: as a full one.
        self._census_date: dict[str, str] = {}
        # The active run. Held in the DB rather than only in memory so
        # recreating the api container CONTINUES the same run instead of
        # silently resetting the dashboard's numbers on every deploy.
        self.run_id: "uuid.UUID | None" = None
        self.started_at: datetime | None = None
        self.starting_balance = starting_balance
        self.activity: deque[dict] = deque(maxlen=80)

    def _mark(self, pair: str) -> float:
        return self._marks.get(pair, 0.0)

    async def _act(self, kind: str, msg: str) -> None:
        """Record + broadcast an engine activity line (what the engine is doing)."""
        evt = {"time": datetime.now(tz=timezone.utc).isoformat(), "kind": kind, "msg": msg}
        self.activity.appendleft(evt)
        try:
            await ws_manager.broadcast(channel="system", event="activity", data=evt)
        except Exception:  # noqa: BLE001
            pass

    async def status(self) -> dict:
        """Engine status + metrics for the monitoring panel.

        SINGLE SOURCE OF TRUTH: realized figures (trade count, wins/losses,
        balance) are read from the DB `trades` table — the same source the Trade
        Journal uses — so every view agrees and the numbers survive an app
        restart. Open positions / unrealized P&L come from the live broker. Falls
        back to in-memory only if the DB is unreachable, so the panel never 500s.
        """
        acct = await self.paper.get_account()
        closed_n = wins = losses = 0
        #: Ledger-derived fields this call could NOT compute, by name. Empty is the
        #: measured state; a non-empty list is why every count below is `None`.
        counts_unavailable: list[str] = []
        try:
            from sqlalchemy import select

            from app.db.enums import OutcomeType, TradeStatus
            from app.db.session import async_session_maker
            from app.models.trade import SETUP_TAG_REPLAY, Trade

            async with async_session_maker() as db:
                # LIVE metrics only: exclude the injected backtest-replay rows.
                # Folding replay into the live panel is exactly the "presents
                # replay as live performance" defect the stress test flagged.
                # NULL/other tags count as live (see is_live_cohort).
                # Scoped to the CURRENT RUN. This is what makes a reset a real
                # reset: metrics start at zero because they only count this
                # run's trades, and nothing had to be deleted to achieve it.
                conditions = [
                    Trade.broker == "paper",
                    Trade.status == TradeStatus.CLOSED,
                    (Trade.setup_tag.is_distinct_from(SETUP_TAG_REPLAY)),
                ]
                if self.run_id is not None:
                    conditions.append(Trade.run_id == self.run_id)
                rows = (
                    await db.execute(
                        select(Trade.outcome, Trade.pnl_dollars).where(*conditions)
                    )
                ).all()
            closed_n = len(rows)
            realized = 0.0
            for outcome, pnl in rows:
                realized += float(pnl or 0)
                if outcome == OutcomeType.WIN:
                    wins += 1
                else:
                    losses += 1
        except Exception as exc:  # noqa: BLE001 - never let the panel 500
            logger.warning("status: DB read failed, using in-memory", error=str(exc))
            # Exclude warmup replay rows here too (reason='replay') so the DB-down
            # fallback matches the happy path — never fold replay into live counts,
            # and derive realized from the live closes only (not paper.balance,
            # which the warmup seeds with replay pnl).
            # **`B431`: THE REPORTING SURFACE MUST SURVIVE THE CONDITION IT REPORTS — AND MUST
            # NOT SUBSTITUTE ZEROS FOR THE FIGURES IT COULD NOT COMPUTE.**
            #
            # `_closed` is the simulator's realized-trade ledger. A venue adapter does not have
            # one, which `B428a` deliberately PERMITS — only `on_tick` is required. So this path
            # has two distinct outcomes and they must not look alike:
            #
            #     ledger present   -> the counts are MEASURED
            #     ledger absent    -> the counts are UNKNOWN, and every one of them is `None`
            #
            # **The first version of this guard returned 0 and justified it by saying
            # `broker_missing` names `_closed` and discriminates the two. It cannot.** Narrowing
            # `REQUIRED_BROKER_CAPABILITIES` to `("on_tick",)` — correctly — made `broker_missing`
            # unable to ever contain `_closed`, so the discriminator the comment pointed at
            # stopped existing while the comment went on claiming it. Driven on a broker with
            # `on_tick` and no `_closed`: `closed_trades 0, wins 0, losses 0, broker_missing []`,
            # a wholly reassuring payload with nothing behind it. `B179`, reached through a
            # correct narrowing of an unrelated list. **A comment asserting a property the code
            # does not have is `B238`.**
            ledger = getattr(self.paper, "_closed", None)
            if ledger is None:
                # NOT ZERO. `None` survives JSON as `null`, which every consumer already renders
                # as an em dash, and which no arithmetic silently absorbs.
                closed_n = wins = losses = None
                counts_unavailable = ["_closed"]
                realized = None
            else:
                closed = [c for c in ledger if c.get("reason") != "replay"]
                closed_n = len(closed)
                wins = sum(1 for c in closed if c["pnl"] > 0)
                losses = sum(1 for c in closed if c["pnl"] <= 0)
                realized = sum(float(c.get("pnl", 0) or 0) for c in closed)

        if realized is None:
            # **THE BROKER'S OWN FIGURES, which are authoritative for a real venue anyway.**
            # `starting_balance + realized` is a simulator idiom; with no ledger it would report
            # the STARTING balance as the current one — "no P&L" where the truth is "P&L unknown",
            # the same substitution one field along. `get_account()` is in the contract, so every
            # broker has it.
            balance = round(acct.balance, 2)
            equity = round(acct.equity, 2)
        else:
            balance = round(self.starting_balance + realized, 2)
            equity = round(balance + acct.unrealized_pl, 2)
        return {
            "running": self._running,
            "paused": self.paused,
            # **`M-6`'s READER.** A reason stored where `status()` cannot show it is `B394` — a
            # mechanism with no consumer. `paused` is a bare bool and carried no reason, so an
            # unnamed halt was indistinguishable from an operator pause, from the order-path gate
            # and from a prop-firm halt: three causes, one flag.
            "halt_reason": self.halt_reason,
            # **`B428a`. THE CONDITION THAT PREVIOUSLY HAD NO READER AT ALL.** An incapable
            # broker showed up nowhere on this payload — the engine read `running`, unpaused and
            # unhalted while it could not complete a single tick. An empty tuple here is a
            # positive statement that the bound broker has everything the loop needs.
            "broker_missing": list(self.broker_missing),
            # `M-6`'s consumer. `None` when nothing failed; the reason when the halt's durable
            # record could not be written. A key that is always populated cannot report health.
            "halt_record_failed": self.halt_record_failed,
            # B179's LESSON APPLIED BEFORE IT BITES. `0 flattens at 19:00` means "the flag is
            # off" and READS AS "the flatten works and there was nothing to close". Whoever
            # asks "did the daily flatten run?" must be able to tell SUPPRESSED from IDLE from
            # WORKING without reading the source, so the switch is on the status payload.
            **DECLARED_SESSION_FLATTEN.as_values(),
            "mode": self.mode,
            "symbols": list(self.symbols),
            "entry_tf": self.entry_tf,
            "risk_pct": self.risk_pct,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "starting_balance": self.starting_balance,
            "balance": balance,
            "equity": equity,
            "unrealized_pl": acct.unrealized_pl,
            "open_positions": acct.open_trade_count,
            "closed_trades": closed_n,
            "wins": wins,
            "losses": losses,
            # `None`, not 0.0, when the ledger could not be read — a 0% win rate is a
            # measurement and this is the absence of one.
            "win_rate": (None if closed_n is None
                         else round(100 * wins / closed_n, 1) if closed_n else 0.0),
            #: `B431`. Names what could not be counted, so a null above is explained on
            #: the same payload rather than by a key that cannot reach it.
            "counts_unavailable": counts_unavailable,
            "total_pnl": round(equity - self.starting_balance, 2),
            "total_pnl_pct": round(100 * (equity / self.starting_balance - 1), 2),
            "activity": list(self.activity)[:40],
            # The settings the engine is actually running, served from the same
            # module the engine reads. The page can then display them without a
            # second copy that can drift out of step with the first.
            "config": fixed.as_dict(),
        }

    def sim_state(self) -> dict | None:
        """Prop-firm rule state (balance, day pnl, drawdown, target, halted,
        pass/fail) when running the SimPropFirmBroker; None in plain paper mode.
        This is what the UI shows so Agent B sees the challenge status live."""
        rs = getattr(self.paper, "rule_state", None)
        return rs() if callable(rs) else None

    async def warmup(self, days: int = 14) -> dict:
        """Backfill the paper account with the strategy's REAL trades over the
        last `days` of Binance data, so the metrics panel shows genuine recent
        gains/losses (real strategy decisions on real prices)."""
        # Never inject replay trades into a prop-firm challenge account — that
        # would corrupt the very pass/fail signal Agent B is measuring.
        #
        # **AND THIS READ IS NOT THE SAME QUESTION AS THE OTHER TWO** (`T-0138`, `M-3`). It used
        # to be `broker_mode == "sim"`, which happened to be equivalent while `sim` and `paper`
        # were the only options. The real predicate is *can fabricated history be seeded into
        # this broker at all* — and for a REAL venue the answer is no, for a different reason
        # than the prop-firm one. Adding `alpaca` to the venue selection and leaving this read
        # spelled the old way is exactly the four-sites defect.
        #
        # ⚠ **AND MY FIRST STATEMENT OF THE CONSEQUENCE WAS FALSE.** I wrote that it *"would have
        # posted backtest trades at a live venue."* **It would not**, and the manager traced it
        # rather than accepting it: `warmup()` places no orders. It mutates simulator internals
        # directly — `self.paper.balance += pnl` and `self.paper._closed.append(...)` — and
        # `AlpacaAdapter` has neither member, so selecting Alpaca and warming up raises
        # `AttributeError`. **A loud crash at warm start, not orders at a venue.**
        #
        # The GUARD is still right: `broker_mode == "sim"` meant *"do not inject where injection
        # is harmful"*, and that meaning drifted the moment the vocabulary gained a third member.
        # **Recorded because the wrong reason was heading into a commit message**, and because it
        # is the third time in six hours one of us was right about the action and wrong about the
        # mechanism — each caught by re-deriving the mechanism instead of the conclusion.
        venue = self._select_venue()
        if venue != "paper":
            reason = ("prop-firm sim account stays clean" if venue == "sim"
                      else f"{venue} is a real venue — fabricated history is not postable to it")
            await self._act("engine", f"Warm start skipped — {reason}")
            return await self.status()
        from app.services.backtest.engine import Params, run_backtest

        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
        loaded: list = []
        for pair, bsym in self.symbols.items():
            try:
                entry = await self._fetch_bars(bsym, "1H", (days + 45) * 24)
                biasd = await self._fetch_bars(bsym, "D", days + 70)
                if entry.empty or biasd.empty:
                    continue
                trades, _ = run_backtest(entry, biasd, pair, Params(risk_pct=self.risk_pct))
                loaded += [t for t in trades if (t.exit_time or t.entry_time) >= cutoff]
            except Exception as exc:  # noqa: BLE001
                logger.warning("warmup failed", pair=pair, error=str(exc))
        loaded.sort(key=lambda t: (t.exit_time or t.entry_time))
        # also persist to the DB `trades` table so the Trade Journal matches
        from decimal import Decimal

        from app.db.enums import DirectionType, OutcomeType, TradeStatus
        from app.db.session import async_session_maker
        from app.models.trade import SETUP_TAG_REPLAY, Trade

        rows = []
        for t in loaded:
            pnl = round(t.pnl_pct * self.paper.balance, 2)
            self.paper.balance += pnl
            is_long = t.direction == "LONG"
            exit_px = t.entry + t.r_multiple * t.risk_per_unit * (1 if is_long else -1)
            self.paper._closed.append({
                "position_id": f"warmup-{len(self.paper._closed)}",
                "pair": t.symbol, "direction": t.direction,
                "entry": t.entry, "exit": exit_px, "units": 0.0, "pnl": pnl,
                # honest: replay exits are back-solved from a blended R, not a
                # single TP/SL touch — don't mislabel them as such.
                "reason": "replay",
                "open_time": t.entry_time, "close_time": t.exit_time or t.entry_time,
                "balance_after": round(self.paper.balance, 2),
            })
            rows.append(Trade(
                user_id="system", broker_id="paper", broker="paper", pair=t.symbol,
                direction=DirectionType.LONG if is_long else DirectionType.SHORT,
                entry_price=Decimal(str(round(t.entry, 6))),
                exit_price=Decimal(str(round(exit_px, 6))),
                sl=Decimal(str(round(t.sl, 6))), lot_size=Decimal("0"),
                entry_time=t.entry_time, exit_time=t.exit_time or t.entry_time,
                r_multiple=Decimal(str(round(t.r_multiple, 2))),
                outcome=OutcomeType.WIN if t.r_multiple > 0 else OutcomeType.LOSS,
                status=TradeStatus.CLOSED, pnl_dollars=Decimal(str(pnl)),
                setup_tag=SETUP_TAG_REPLAY,   # honest: injected backtest trades, not live
            ))
        try:
            async with async_session_maker() as db:
                # clear any prior warmup rows so re-running doesn't duplicate
                from sqlalchemy import delete
                # F3: only wipe replay rows on re-warmup — never the durable live trades
                await db.execute(
                    delete(Trade).where(Trade.broker == "paper", Trade.setup_tag == SETUP_TAG_REPLAY)
                )
                db.add_all(rows)
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("warmup DB persist failed", error=str(exc))
        await self._act(
            "engine",
            f"Warm start — loaded {len(loaded)} real trades from the last {days}d; "
            f"equity ${self.paper.balance:,.0f}",
        )
        return await self.status()

    async def _fetch_bars(self, binance_symbol: str, tf: str, count: int):
        """Fetch `count` bars of `tf`, from whichever price source is configured.

        Callers pass the BINANCE symbol ("BTCUSDT") because that is what
        self.symbols maps to. CFTSource expects the canonical pair ("BTC/USD")
        and appends its own USDT+.cft suffix, so handing it "BTCUSDT" directly
        would build "BTCUSDTUSDT.cft" and 404 on every bar. Translate here, at
        the one boundary, rather than teaching every call site about venues.
        """
        minutes = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1H": 60, "4H": 240, "D": 1440}.get(tf, 60)
        end = datetime.now(tz=timezone.utc)
        start = end - timedelta(minutes=minutes * (count + 5))

        symbol = binance_symbol
        if getattr(self, "price_source_name", "binance") == "cft":
            symbol = self._pair_for(binance_symbol)

        return await asyncio.to_thread(self.source.fetch_ohlcv, symbol, tf, start, end)

    def _pair_for(self, binance_symbol: str) -> str:
        """Reverse self.symbols: "BTCUSDT" -> "BTC/USD"."""
        for pair, bsym in self.symbols.items():
            if bsym == binance_symbol:
                return pair
        return binance_symbol

    async def _entry_block_reason(self, pair: str) -> str | None:
        """Return a human-readable reason if a new entry is blocked, else None.

        Pure gate logic (no network) so it is directly testable. The kill switch
        is authoritative: while ARMED, no new entry is allowed regardless of the
        loop's own pause state — this is what makes the kill switch actually stop
        trading rather than merely closing positions once.
        """
        from app.services.compliance.kill_switch import kill_switch

        # **THE HALT COMES FIRST, and it is checked before anything that can fail.** It means a
        # position of unknown size may exist at the venue, which outranks every other reason to
        # not enter — and, like the direction refusal in `alpaca.place_order`, it must not depend
        # on a position read or a venue call succeeding.
        if self.halt_reason:
            return BlockReason(f"HALTED ({self.halt_reason})", kind=BLOCK_HALT)
        # **`B428a`, AND A HALT RATHER THAN A SKIP.** A broker that cannot sweep SL/TP cannot
        # enforce a stop, and `AlpacaAdapter.place_order` sends none to the venue (`B429`) — so
        # entering here would open a position with no stop from either side. Checked with no I/O,
        # for the same reason the halt above is: a refusal this absolute must not depend on a
        # venue call succeeding. `start()` refuses too; this covers a REBIND mid-run, which
        # `start()` cannot see.
        if self.broker_missing:
            return BlockReason(
                f"{BLOCK_BROKER_INCAPABLE} (missing {', '.join(self.broker_missing)})",
                kind=BLOCK_HALT)
        if kill_switch.is_armed:
            return BlockReason(
                f"KILL SWITCH ARMED ({kill_switch.reason or 'no reason given'})", kind=BLOCK_HALT)
        # `skip`, not `halt`, and unchanged: an operator pause is resolved by the operator, and
        # this preserves exactly the classification the prose prefix produced.
        if self.paused:
            return BlockReason("engine paused", kind=BLOCK_SKIP)
        if await self._has_position(pair):
            return BlockReason("already in a position", kind=BLOCK_SKIP)
        if await self._open_count() >= self.max_concurrent:
            return BlockReason(f"max concurrent {self.max_concurrent} reached", kind=BLOCK_SKIP)
        return None

    async def _news_context(self) -> NewsContext:
        """T-0036 Stage A — the order path's news verdict, RECORDED and not enforced.

        Deliberately NOT part of `_entry_block_reason`. That function documents itself as
        *"pure gate logic (no network) so it is directly testable"*, and it is the ENFORCING
        path — a reason returned there skips the bar. Stage A must suppress nothing, and
        putting a calendar fetch there would break a property the function states about
        itself. **Stage B belongs there, and will need the events passed in rather than
        fetched, for that same reason.**

        ALWAYS RETURNS A CONTEXT. An unreadable calendar comes back as
        `NewsContext.unavailable(reason)`, never as `None` and never as an empty one: the
        evaluator records it as `NOT-EVALUATED` with the reason, so a provider outage is
        visible in the traces instead of being indistinguishable from a quiet news week. A
        `[]` here would make an unreachable calendar say *"no blackout"* — the fail-open
        `T-0035` closed at the source, rebuilt at the consumer.

        **The annotation said `-> NewsContext | None` until B157's sweep, and that was worse
        than stale.** `strategy_step`'s `news=None` ALSO means "not evaluated", so the type
        advertised two representations of one state — **describing this code as having the
        exact defect it was changed to remove.** A seat following that signature would
        reasonably add `if news is None: return` at the caller, or build a second unavailable
        path, and be following the type. **No test reads an annotation and a reader trusts it
        more than prose.**
        """
        now = datetime.now(tz=timezone.utc)
        events, reason = await fetch_calendar_events()
        if events is None:
            # NOT `return None` and NOT an empty calendar. The trace records
            # NOT-EVALUATED with the reason, so a silent stretch is attributable: quiet
            # news, a missing key and a provider outage look identical in a verdict and
            # need different responses.
            return NewsContext.unavailable(to_ny(now), reason or "unknown")
        return build_news_context(now, events)

    async def _open_count(self) -> int:
        return len((await self.paper.get_positions()))

    async def _has_position(self, pair: str) -> bool:
        return any(p.pair == pair for p in await self.paper.get_positions())

    async def _push_state(self) -> None:
        positions = await self.paper.get_positions()
        acct = await self.paper.get_account()
        # THROUGH THE ONE PRODUCER, so `positions.update` has one shape by construction
        # rather than by two call sites agreeing. AUTHORITATIVE: this reads the live broker's
        # own list, so an empty list here MEANS there are no positions — which is exactly the
        # case the client must act on and previously could not distinguish from a reconnect.
        await ws_manager.push_position_update(
            [p.model_dump(mode="json") for p in positions], authoritative=True
        )
        await ws_manager.broadcast(
            channel="positions", event="account",
            data={"balance": acct.balance, "equity": acct.equity,
                  "unrealized_pl": acct.unrealized_pl, "open_trade_count": acct.open_trade_count},
        )

    def _code_path_hash(self) -> str:
        """Fingerprint the decision code path + params so identical inputs under
        identical code are reproducible/auditable (the feedback loop's basis)."""
        import hashlib
        payload = f"{ENGINE_CODE_VERSION}|entry_tf={self.entry_tf}|bias_tf={self.bias_tf}|risk_pct={self.risk_pct}"
        return hashlib.sha1(payload.encode()).hexdigest()[:16]

    @staticmethod
    def _inputs_hash(entry_df) -> str:
        """Fingerprint the bars the decision saw (last ~10 closed bars)."""
        import hashlib
        try:
            tail = entry_df.tail(10)
            raw = "|".join(
                f"{ts.isoformat()}:{row.open:.2f}:{row.high:.2f}:{row.low:.2f}:{row.close:.2f}"
                for ts, row in tail.iterrows()
            )
        except Exception:  # noqa: BLE001
            raw = str(len(entry_df))
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

    async def _record_unprotected_position(self, pair: str, sig, exc) -> None:
        """Record a halt declared because a position may be open with no stop (`B429`).

        **AN ALERT ONLY, AND THE ABSENCE OF A `DecisionRecord` IS DELIBERATE.** Its sibling
        `_record_unsized_fill` writes one because `UNSIZED_FILL` says exactly what happened there.
        No value in the vocabulary says *the venue took the order, refused the stop, and the close
        failed*: `REJECTED` asserts no position (false), `OPEN` asserts one of known size that we
        are managing (false — nothing is managing it), `UNSIZED_FILL` asserts we could not size it
        (we could; we could not PROTECT it). **A row is worse than no row when every available
        value is affirmatively wrong** — `B399`, and the reason `UNSIZED_FILL` had to be added
        rather than borrowed. Neither `T-0130` nor `B427`, which own that vocabulary, added a ninth
        outcome — both ruled no row where every value is false — and this does not smuggle one in.

        **AND NO ROW EXISTS YET — "no NEW row" and "no row" are different states, and the argument
        above needs the second.** Traced and then DRIVEN (`test_the_unprotected_halt_leaves_NO_
        DECISION_ROW_AT_ALL`): `_record_signal_decision` has one call site, inside the fill branch,
        after `execution.execute()` returns, and this halt fires in the `except` around that call —
        so nothing has been written for this signal. Were a row already claiming `OUTCOME_OPEN`,
        declining to write would LEAVE it asserting a managed position of known size, which is the
        thing this docstring rejects and worse for being on disk already. The manager asked for the
        trace rather than accepting the claim, which is why it is stated here and not in a message.

        Mirrors the writer contract `_declare_halt` depends on: every failure is appended rather
        than raised, and the LAST statement clears the alarm unconditionally so a success cannot
        leave it standing.
        """
        failures: list[str] = []
        order_id = getattr(exc, "order_id", None)

        try:
            from datetime import timedelta

            from app.db.enums import AlertPriority, AlertStatus, AlertType
            from app.db.session import async_session_maker
            from app.models.alert import Alert

            async with async_session_maker() as db:
                db.add(Alert(
                    type=AlertType.RISK_WARNING,
                    priority=AlertPriority.CRITICAL,
                    pair=pair,
                    message=(
                        f"ENGINE HALTED — {HALT_UNPROTECTED_POSITION}. The venue accepted the "
                        f"order, refused the stop, and flat was NOT observed after cancel and close "
                        f"(a slow fill and a failed close both land here — see the detail). There is "
                        f"NO STOP at the venue and none in this process. No new entries."
                    ),
                    suggested_action={
                        "action": "flatten_or_place_stop_at_venue",
                        "pair": pair,
                        "order_id": order_id,
                    },
                    context_json={
                        "halt_reason": HALT_UNPROTECTED_POSITION,
                        "order_id": order_id,
                        "detail": getattr(exc, "detail", None),
                        "signal_sl": float(sig.sl) if sig.sl is not None else None,
                        "signal_tp": float(sig.tp) if sig.tp is not None else None,
                        "run_id": str(self.run_id) if self.run_id else None,
                    },
                    # `PENDING`, as its sibling `_record_unsized_fill` writes. The first version said
                    # `ACTIVE`, a member `AlertStatus` does not have: the AttributeError landed in the
                    # `except` below and became one log line, so the CRITICAL alert for an unprotected
                    # position would NEVER have been written. Found by the L-4 arm the kill set demanded.
                    status=AlertStatus.PENDING,
                    expires_at=datetime.now(timezone.utc) + timedelta(days=365),
                ))
                await db.commit()
        except Exception as exc2:  # noqa: BLE001 - a failed write must not un-halt the engine
            failures.append(f"alert: {type(exc2).__name__}")
            logger.error("live.unprotected_position.alert_failed", error=str(exc2), pair=pair)

        # UNCONDITIONAL, so a success CLEARS the alarm `_declare_halt` armed. A conditional
        # assignment here would leave "NOT YET WRITTEN" standing after a successful write, which
        # is the alarm that cries wolf and then gets ignored.
        self.halt_record_failed = (
            f"{HALT_UNPROTECTED_POSITION} — {', '.join(failures)}" if failures else None
        )

    async def _on_unresolved_order(self, pair: str, entry_df, sig, res: dict, trace=None) -> None:
        """`place_order` returned neither a fill nor a refusal, AFTER resolution. **The halt for exposure unknown.**

        **`T-0130`.** An absent or unrecognised status means the engine cannot say whether the venue
        acted. Recording a fill invents a position; recording a refusal denies one that may exist
        and that nothing would then manage (`B427`'s worst case). So this halts, as the other two
        *we cannot establish what we hold* states do, and records the halt — without a row.

        **`B427` RESOLVES ORDERS BEFORE THEY REACH HERE — IN THE ADAPTER, NOT IN THIS METHOD** (manager's
        ruling A). `AlpacaAdapter.place_order` re-reads the order until it is terminal or
        `ORDER_RESOLUTION_BUDGET_S` is spent, and maps the verdict: a `CANCELED` order with a known fill
        arrives as PARTIALLY_FILLED, one ended with a readable zero as REJECTED. **So what reaches this
        seam is what stayed unresolved when the budget expired** — an acknowledgement nothing confirmed, a
        terminal status with an unreadable quantity, a replaced order. Do NOT add resolution here: it
        would re-read orders the adapter already gave up on, and probe 3, which calls `place_order`
        directly, would never exercise it. What stays: anything still unresolved halts, because an order
        nobody can classify is not a refusal.

        **NO `DecisionRecord`, deliberately and PERMANENTLY for what reaches here** (manager's ruling,
        restated after `B427`). An order the adapter RESOLVED never reaches this seam: it goes through the
        FILL or REFUSAL branch and gets a true row there. What does reach it — the budget spent on a
        non-terminal order, or a terminal state whose quantity cannot be read — is exactly the case where
        exposure is unknown, and for it `REJECTED` denies a position, `OPEN` asserts one of known size and
        `UNSIZED_FILL` asserts the venue acted: none is true, and a row is worse than none when every
        available value is affirmatively wrong (`B399`). No later task writes it either — an outcome
        stored now to be rewritten later is `B423`'s silent rewrite. **The missing row is recoverable from
        the alert, which carries every input `_record_signal_decision` would have used**, once an operator
        has found the order at the venue.

        Same ordering as the other halt sites (`M-7`): the halt is in force before anything is
        written, so a failed write cannot un-halt.
        """
        status = res.get("status")
        self._declare_halt(HALT_ORDER_UNRESOLVED)
        logger.error(
            "live.order_unresolved — HALTING. place_order returned neither a fill nor a refusal, so "
            "a position may exist at the venue that this engine does not track",
            pair=pair, direction=sig.direction.value,
            status=redact_for_storage(repr(status)),
            status_key_present="status" in res,
            position_id=res.get("position_id"),
            client_order_id=res.get("client_order_id"),
        )
        await self._act(
            BLOCK_HALT,
            f"{pair} {sig.direction.value} — HALTED: {HALT_ORDER_UNRESOLVED} "
            f"(status {redact_for_storage(repr(status), limit=40)}, "
            f"order {res.get('position_id') or 'UNREPORTED'})",
        )
        await self._record_unresolved_order(pair, entry_df, sig, res, trace)

    async def _record_unresolved_order(self, pair: str, entry_df, sig, res: dict, trace=None) -> None:
        """The durable record of `HALT_ORDER_UNRESOLVED`: one CRITICAL alert, never a row.

        The writer contract `_declare_halt` depends on, as in `_record_unprotected_position`: every
        failure is appended rather than raised, and the LAST statement clears the alarm
        unconditionally so a success cannot leave it standing.

        **THE RESULT IS NOT STORED WHOLE.** A venue reply can carry text nobody vetted, and a
        `context_json` column never passes the log filter. What is kept is what finds the order and
        what shows why it was unclassifiable — the status as a bounded, redacted repr (so `None`,
        `""` and absent stay distinguishable), whether the key was present, the key NAMES, the sizes
        and the ids — plus `row_inputs`, the fields a truthful `DecisionRecord` needs.

        **`row_inputs` IS BUILT SEPARATELY FROM THE WRITE**, so a failure assembling it still writes
        the alert and is itself reported on `halt_record_failed`: an alert missing the inputs is an
        incomplete durable record, and saying "written" would hide that.
        """
        failures: list[str] = []

        def _plain(value):
            # JSON-safe and bounded: a string is redacted, a finite number kept, anything else
            # (NaN, a Decimal, an SDK object) becomes its bounded repr rather than failing the write.
            if value is None or isinstance(value, (bool, int)):
                return value
            if isinstance(value, float) and value == value and value not in (float("inf"), float("-inf")):
                return value
            return redact_for_storage(value if isinstance(value, str) else repr(value))

        try:
            row_inputs = {
                "symbol": pair,
                "timeframe": self.entry_tf,
                "inputs_hash": self._inputs_hash(entry_df),
                "code_path_hash": self._code_path_hash(),
                "reasons": [redact_for_storage(str(r)) for r in
                            _with_exit_plan(trace.reasons if trace is not None else None)][:50],
                "signal_dir": sig.direction.value,
                "signal_entry": _plain(float(sig.entry)),
                "signal_sl": _plain(float(sig.sl)),
                "signal_tp": _plain(float(sig.tp)) if sig.tp is not None else None,
                "sized_units": _plain(res.get("sized_units")),
                "sizing_equity": _plain(res.get("equity_at_entry")),
                "sizing_risk_pct": _plain(float(sig.risk_pct)),
                "sizing_price": _plain(res.get("sizing_price")),
                "fill_price": _plain(res.get("fill")),
                "run_id": str(self.run_id) if self.run_id else None,
            }
        except Exception as exc:  # noqa: BLE001 - reported, and the alert is still written
            failures.append(f"row_inputs: {type(exc).__name__}")
            row_inputs = {"error": f"{type(exc).__name__}: {redact_for_storage(str(exc))}"}

        try:
            from datetime import timedelta

            from app.db.enums import AlertPriority, AlertStatus, AlertType
            from app.db.session import async_session_maker
            from app.models.alert import Alert

            async with async_session_maker() as db:
                db.add(Alert(
                    type=AlertType.RISK_WARNING,
                    priority=AlertPriority.CRITICAL,
                    pair=pair,
                    message=(
                        f"ENGINE HALTED — {HALT_ORDER_UNRESOLVED}. The order result was neither a "
                        f"fill nor a refusal, so the venue may hold a position this engine is not "
                        f"managing. Find the order at the venue before restarting. No new entries."
                    ),
                    suggested_action={
                        "action": "find_order_at_venue",
                        "pair": pair,
                        "order_id": _plain(res.get("position_id")),
                        "client_order_id": _plain(res.get("client_order_id")),
                    },
                    context_json={
                        "halt_reason": HALT_ORDER_UNRESOLVED,
                        "status_repr": redact_for_storage(repr(res.get("status"))),
                        "status_key_present": "status" in res,
                        "result_keys": sorted(str(k) for k in res)[:40],
                        "units": _plain(res.get("units")),
                        "filled_units": _plain(res.get("filled_units")),
                        "position_id": _plain(res.get("position_id")),
                        "client_order_id": _plain(res.get("client_order_id")),
                        "row_inputs": row_inputs,
                    },
                    # `PENDING`, checked against the enum, as both sibling recorders write (`AS-1`).
                    status=AlertStatus.PENDING,
                    expires_at=datetime.now(timezone.utc) + timedelta(days=365),
                ))
                await db.commit()
        except Exception as exc:  # noqa: BLE001 - a failed write must not un-halt the engine
            failures.append(f"alert: {type(exc).__name__}")
            logger.error("live.order_unresolved.alert_failed", error=str(exc), pair=pair)

        self.halt_record_failed = (
            f"{HALT_ORDER_UNRESOLVED} — {', '.join(failures)}" if failures else None
        )

    async def _record_unsized_fill(self, pair: str, entry_df, sig, res: dict) -> None:
        """The two DURABLE records of a halt: one for the corpus, one for the operator.

        **`B413`/`T-0143`. THE HALT ITSELF IS ALREADY DONE BY THE TIME THIS RUNS** — `halt_reason`
        is set, the ERROR line is out, the activity line is out, and entry is blocked. This method
        only records it, and `M-7` is the reason that ordering is not incidental: **the alert is a
        durable record OF the halt, never the halt itself.** If everything here fails, the engine
        must still be stopped.

        **`M-5`: NEITHER WRITE MAY KILL THE LOOP.** This is a safety path, and the moment a
        database write is most likely to fail is exactly the moment it is most needed — a halt
        usually follows something already going wrong.

        **`M-6`: AND NEITHER MAY VANISH.** Those two requirements pull against each other, and the
        obvious reconciliation — catch, log, continue — is `B403` rebuilt inside the fix for
        `B413`: we are writing an `Alert` precisely because a log line is not a record. So a
        failure sets `halt_record_failed`, which `status()` exposes, which is the surface the
        operator is on BECAUSE of the halt.

        **The `DecisionRecord` carries `UNSIZED_FILL`** — its own outcome, because `REJECTED` says
        execution refused the signal (it did not — the venue acted), `OPEN` says a position of
        KNOWN size exists (that is the whole condition), and `ABANDONED` says one died (this may
        still be open). Before that value existed the loop wrote `REJECTED`/`UNCLASSIFIED` here,
        which was an affirmatively false row rather than a missing one.
        """
        from decimal import Decimal

        failures: list[str] = []

        try:
            from app.db.session import async_session_maker
            from app.models.decision_record import (
                COHORT_PAPER,
                Attribution,
                DecisionRecord,
                OUTCOME_UNSIZED_FILL,
            )

            entry = float(entry_df["close"].iloc[-1])
            async with async_session_maker() as db:
                db.add(DecisionRecord(
                    symbol=pair, timeframe=self.entry_tf,
                    inputs_hash=self._inputs_hash(entry_df), code_path_hash=self._code_path_hash(),
                    score=None, abstained=False,
                    signal_dir=sig.direction.value,
                    signal_entry=Decimal(str(round(entry, 6))),
                    signal_sl=Decimal(str(round(float(sig.sl), 6))),
                    signal_tp=None,
                    outcome=OUTCOME_UNSIZED_FILL,
                    # NOT `sized_units`: that column is read by the partial-close accounting as the
                    # size of the position, and not knowing it is the entire condition. Leaving it
                    # NULL says so; a number here would be invented.
                    rejection_reason=(
                        f"{HALT_PARTIAL_UNSIZED} — status {res.get('status')!r}, venue reported "
                        f"filled {res.get('filled_units')!r}, submitted {res.get('units')!r}, "
                        f"venue position {res.get('position_id') or 'UNREPORTED'}"
                    ),
                    cohort=COHORT_PAPER, run_id=self.run_id,
                    **Attribution.ict().as_columns(),
                ))
                await db.commit()
        except Exception as exc:  # noqa: BLE001 — recorded on status(), never raised
            failures.append(f"decision_record: {type(exc).__name__}")
            logger.error("live.unsized_fill.decision_record_failed", error=str(exc), pair=pair)

        try:
            from datetime import timedelta

            from app.db.enums import AlertPriority, AlertStatus, AlertType
            from app.db.session import async_session_maker
            from app.models.alert import Alert

            async with async_session_maker() as db:
                db.add(Alert(
                    # An EXISTING AlertType and priority on purpose. `type` is a Postgres ENUM
                    # (`alert_type_t`), so a new member would mean `ALTER TYPE` — which is what
                    # took production down in `0009`. RISK_WARNING/CRITICAL already say this.
                    type=AlertType.RISK_WARNING,
                    priority=AlertPriority.CRITICAL,
                    pair=pair,
                    message=(
                        f"ENGINE HALTED — {HALT_PARTIAL_UNSIZED}. A position may exist at the "
                        f"venue whose size we cannot establish. No new entries will be taken."
                    ),
                    suggested_action={
                        "action": "reconcile_position_at_venue",
                        "venue_position_id": res.get("position_id"),
                        "pair": pair,
                    },
                    context_json={
                        "halt_reason": HALT_PARTIAL_UNSIZED,
                        "status": res.get("status"),
                        "filled_units": res.get("filled_units"),
                        "submitted_units": res.get("units"),
                        "position_id": res.get("position_id"),
                        "client_order_id": res.get("client_order_id"),
                        "run_id": str(self.run_id) if self.run_id else None,
                    },
                    status=AlertStatus.PENDING,
                    # A halt does not resolve on its own, so this outlives an ordinary alert. It
                    # is NOT NULL on the model and has no default, so it must be supplied.
                    expires_at=datetime.now(tz=timezone.utc) + timedelta(days=365),
                ))
                await db.commit()
        except Exception as exc:  # noqa: BLE001 — recorded on status(), never raised
            failures.append(f"alert: {type(exc).__name__}")
            logger.error("live.unsized_fill.alert_failed", error=str(exc), pair=pair)

        # **UNCONDITIONAL, so that SUCCESS is what clears the alarm.** An `if failures:` here would
        # leave the "not yet written" string in place after a successful write — but worse, it was
        # what allowed `None` to survive from initialisation and mean two different things.
        self.halt_record_failed = (
            f"the halt is IN FORCE but its durable record could not be written "
            f"({', '.join(failures)}) — reconcile the position at the venue by hand"
            if failures else None
        )

    @property
    def halt_reason(self) -> str | None:
        """Why the engine is halted, or `None`. **READ-ONLY: the only writer is `_declare_halt`.**

        **`B424` residual, found by review.** The pairing arm scanned ONE MODULE while this was a
        public attribute assignable from ANY module — so route 3 was closed against a new halt site
        in this file and left open against the same site written one file over. A source scan can
        only ever answer for the files it was pointed at; the population question does not arise if
        the wrong state cannot be assigned in the first place.

        `loop.halt_reason = "..."` now raises `AttributeError` wherever it is written, including
        from a test — which is the point. A fixture that set both fields by hand was already caught
        once doing the production code\'s work, and this makes that fixture impossible rather than
        discouraged: `_declare_halt` is the only way to reach the halted state, so anything
        exercising a halt exercises the real pairing.
        """
        return self._halt_reason

    def _declare_halt(self, reason: str) -> None:
        """Stop the engine and arm the missing-record alarm. **THE ONLY PLACE EITHER IS SET.**

        **`B424`, and it is TWO properties that look like one.**

        *The pairing.* `halt_reason` and `halt_record_failed` must move together: a halt declared
        without arming the alarm reports a healthy record, because `None` on that field asserts
        *both durable rows are on disk*. Nothing required the pairing — it held because there was
        exactly one halt site and its author happened to write both lines. **The second halt site
        inherits "healthy" for free**, so the pairing is made unrepresentable here rather than
        remembered, and an arm asserts no assignment to either field outside this method. `halt_reason`
        is additionally a read-only property, so the scan's SCOPE stops mattering — see its
        docstring above; the scan still runs, PACKAGE-WIDE, because a line that never executes
        never raises.

        *The window.* **Collapsing the two assignments says nothing about what sits BETWEEN them.**
        The adjacency below is load-bearing and was undesigned: with no suspension point between
        the two statements, no cancellation can land in the gap and no concurrent `status()` can
        observe the reassuring middle — a halt in force with its alarm unset. An `await` inserted
        between these two lines reopens both routes **with this method fully in place**, which is
        why it has an arm of its own rather than a comment.

        **DO NOT PUT ANYTHING BETWEEN THE NEXT TWO STATEMENTS.** Not a log line, not an `await`,
        not a call that might one day become async.
        """
        self._halt_reason = reason
        self.halt_record_failed = f"{reason} — durable record NOT YET WRITTEN"

    @staticmethod
    def _position_units(res: dict) -> float | None:
        """The size of the position the venue ACTUALLY opened, or `None` when it cannot be read.

        **`B413`/`T-0141`. The ruling: a fill above zero is a real position, tracked at the FILLED
        size, never at the size we asked for.**

        ```
        FILLED            filled_units when the broker reports one, else `units`
        PARTIALLY_FILLED  filled_units ONLY. no fallback.
        anything else     None — not a fill
        ```

        **THE FALLBACK IS THE MUST-MISS AND IT IS WHY IT EXISTS ONLY ON `FILLED`.** `paper.py` and
        `cft_sim.py` return `units` and **no `filled_units` at all** — measured, not assumed — and
        those two are what the engine actually runs on today. Requiring `filled_units` for every
        fill would halt **every paper and sim entry** and destroy the order path, which is exactly
        the unconditional-halt failure the kill set names as `M-3`. A paper fill fills what was
        asked, so `units` is the filled size there.

        **AND THE FALLBACK MUST NOT REACH `PARTIALLY_FILLED`.** For Alpaca, `units` is what we
        SUBMITTED — so falling back to it on a partial would record the asked size and rebuild
        `B411`'s defect deliberately, which is `M-1`.

        A non-positive size is not a position (`M-5`). Recording one creates a phantom the engine
        would then try to exit, and `sized_units` is what the partial-close accounting reads
        (`:1579`, `:1624`).
        """
        def positive(value) -> float | None:
            """`value` as a positive float, or `None` when it is not one.

            **UNPARSEABLE IS UNSIZEABLE, and that is a deliberate fail-closed.** A broker handing
            back a non-numeric quantity is violating its contract, and letting `float()` raise
            would abort the bar into `_loop`'s blanket handler — leaving NO row, which is `B403`'s
            shape. *We cannot establish the size* is exactly what an unparseable quantity means,
            so it takes the same path as an absent one: the halt.
            """
            # **ONE PARSE (`B426`)**, the broker contract's: its own `float()` / `except (TypeError, ValueError)`
            # raised OverflowError on a 401-digit int — out of the function K-12 says must never raise,
            # which the runbook's probe step runs on a raw venue dict — and read `True` as a position of
            # one unit. `readable_quantity` rejects both; a SIZE must then also be above zero.
            number = readable_quantity(value)
            return number if number is not None and number > 0 else None

        # The kind of fill comes from the ONE classifier (`T-0130`, K-11); this method keeps its
        # signature — a plain dict — because the runbook's probe step calls it by name on a raw result.
        kind = classify_order_status(res.get("status"))
        # **`B419`. `.get()` CANNOT TELL "KEY ABSENT" FROM "KEY PRESENT AND `None`", and those are
        # the two cases this function exists to separate.** Membership can, so membership is what
        # is tested.
        #
        # Measured on the real return dicts: `paper.py` and `cft_sim.py` never emit `filled_units`
        # at all (0 occurrences), while `alpaca.py:889` ALWAYS emits it, with `None` meaning *the
        # venue did not say*. Read through `.get()` both arrive as `None`, so an Alpaca full fill
        # with no reported quantity took the paper fallback and recorded THE SUBMITTED SIZE.
        #
        # **And the adapter three lines above that key refuses exactly this** — *"never defaulted
        # to the submitted quantity, which would report a fill we have no evidence of"*. The loop
        # was doing it on the adapter's behalf: `B411` by another route, on the `FILLED` path.
        # I wrote both sides, and the second undid the first.
        reported = "filled_units" in res
        filled = positive(res.get("filled_units"))

        if kind == ORDER_PARTIALLY_FILLED:
            return filled

        if kind == ORDER_FILLED:
            # **ABSENT AND UNUSABLE ARE NOT THE SAME ANSWER, and collapsing them substitutes a
            # size for one we were given and could not read.** `paper.py` and `cft_sim.py` never
            # report a filled quantity, so absence is their normal and `units` is the fill. But a
            # broker that reported `NaN`, `inf` or a non-numeric SPOKE — and falling back to the
            # submitted quantity there would record a size the venue never confirmed, which is
            # `B411`'s defect reached through the fallback instead of the field.
            #
            # Caught by driving the resolver: with the two folded together, a `NaN` filled
            # quantity on a full fill returned the submitted size.
            if reported:
                return filled
            return positive(res.get("units"))

        return None

    async def _record_signal_decision(
        self, pair: str, entry_df, sig, sized_units: float, fill_price: float | None = None,
        trace=None, sizing_equity: float | None = None,
        sizing_risk_pct: float | None = None, sizing_price: float | None = None,
    ) -> None:
        """Persist a DecisionRecord for a taken signal (outcome OPEN), and remember
        its id so the eventual close can fill realized_r / gap_r / outcome.

        `fill_price` is what the broker actually paid. expected_r is computed from
        it rather than from `sig.entry`, because expected_r is the RR of the
        position that EXISTS, not of the one the strategy drew on the chart. With
        a market order those differ every time, and the gap between them used to
        be silently absorbed into the "expected" side of expected-vs-realized —
        the one measurement this whole feedback loop is built on."""
        try:
            from decimal import Decimal

            from app.db.session import async_session_maker
            from app.models.decision_record import (
                COHORT_PAPER, OUTCOME_OPEN, Attribution, DecisionRecord,
            )
            entry = float(sig.entry); sl = float(sig.sl)
            tp = float(sig.tp) if sig.tp is not None else None
            fill = float(fill_price) if fill_price is not None else None
            # Basis for the RR we actually committed to: the real fill when we
            # have one, the signal price only as a fallback.
            basis = fill if fill is not None else entry
            expected_r = abs(tp - basis) / abs(basis - sl) if (tp is not None and basis != sl) else None
            rec = DecisionRecord(
                symbol=pair, timeframe=self.entry_tf,
                inputs_hash=self._inputs_hash(entry_df), code_path_hash=self._code_path_hash(),
                score=None, abstained=False,
                # The reasoning behind a TAKEN trade matters as much as behind a
                # refusal: it is what lets you check the entry was justified
                # rather than merely profitable.
                reasons=_with_exit_plan(trace.reasons if trace is not None else None),
                signal_dir=sig.direction.value,
                signal_entry=Decimal(str(round(entry, 6))),
                signal_sl=Decimal(str(round(sl, 6))),
                signal_tp=Decimal(str(round(tp, 6))) if tp is not None else None,
                fill_price=Decimal(str(round(fill, 6))) if fill is not None else None,
                sized_units=Decimal(str(round(float(sized_units), 6))),
                # `B279`. SIX decimal places, not two: the finding this preserves lived in
                # the fourth — 5000.9197 against 5000.00.
                sizing_equity=(
                    Decimal(str(round(float(sizing_equity), 6)))
                    if sizing_equity is not None else None
                ),
                sizing_risk_pct=(
                    Decimal(str(round(float(sizing_risk_pct), 6)))
                    if sizing_risk_pct is not None else None
                ),
                sizing_price=(
                    Decimal(str(round(float(sizing_price), 6)))
                    if sizing_price is not None else None
                ),
                expected_r=Decimal(str(round(expected_r, 4))) if expected_r is not None else None,
                outcome=OUTCOME_OPEN, cohort=COHORT_PAPER,
                run_id=self.run_id,
                # This trade was decided by the ICT path — `_tick_symbol` reaches
                # here from the ICT setup, and the rule engine's verdict is
                # computed in the shadow and DISCARDED (Stage A). Stated rather
                # than left blank: it is knowable and true today, and a NULL here
                # would be indistinguishable from a rule decision whose decider
                # was lost. Changes at the cutover, not before.
                **Attribution.ict().as_columns(),
            )
            async with async_session_maker() as db:
                db.add(rec)
                await db.commit()
                self._open_decision[pair] = str(rec.id)
        except Exception as exc:  # noqa: BLE001 - never let bookkeeping kill the loop
            logger.warning("record decision failed", pair=pair, error=str(exc))

    # ------------------------------------------------------------------
    # Run lifecycle (task 2.1)
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # THE VENUE — one mapping, one binder, and both construction sites go through them
    # ------------------------------------------------------------------
    @staticmethod
    def _missing_capabilities(broker) -> tuple[str, ...]:
        """Which of `REQUIRED_BROKER_CAPABILITIES` this broker does not have.

        **Asked of the INSTANCE, not the class.** `balance` and `_closed` are assigned in the
        simulators' `__init__`, so a class-level `hasattr` reports both simulators missing both —
        a check that answers confidently and wrongly about the brokers we actually run. Measured:
        the class form called `PaperBroker` incapable.
        """
        return tuple(name for name in REQUIRED_BROKER_CAPABILITIES if not hasattr(broker, name))

    def _select_venue(self) -> str:
        """`broker_mode` normalised to the venue actually being built (`T-0138`).

        **ONE FACT IN ONE PLACE.** `broker_mode` was read at three sites and the switch is gaining
        a third option, so a literal per site is `B184` — and it fails by selecting the SIMULATOR
        somewhere nobody looks, which is the quiet direction.
        """
        mode = (self.broker_mode or "").strip().lower()
        if mode in _ALPACA_MODES:
            return "alpaca"
        if mode == "sim":
            return "sim"
        return "paper"

    def _bind_broker(self, starting_balance: float) -> None:
        """Build the broker for the selected venue and bind everything that must follow it.

        **THE INITIALISER AND THE RECONFIGURE PATH BOTH CALL THIS, AND THAT IS THE POINT.** The
        construction, the settle hook and the `ExecutionService` each existed at TWO sites, so a
        fix applied to one was invisible in the other while the suite stayed green — `B384` at
        this layer. Three duplicated facts become one call.

        **THE ATTRIBUTE NAME IS LOAD-BEARING AND MUST STAY `self.paper`.**
        `LiveLoopBrokerProxy._resolve()` does `getattr(self._loop, "paper", None)` at call time,
        and `main.py:242` registers that proxy as the manager's `paper` adapter. Renaming this
        attribute would orphan the kill switch, the aggregate position view and close-routing in
        silence — `B221`'s exact mechanism returning by a new route, and `B221` is the finding
        where the switch reported a clean trigger and closed nothing. An arm pins the name.
        """
        # ------------------------------------------------------------------
        # BUILD INTO A LOCAL AND SWAP ONLY ON SUCCESS (`B401`).
        #
        # **NOTHING IS MUTATED UNTIL THE NEW BROKER EXISTS.** `_build_broker` can raise — it
        # constructs a `TradingClient` and an `AlpacaAdapter` that refuses on an endpoint/flag
        # disagreement (`B389`) and refuses outright with no credentials — so a rebuild that
        # fails must leave the previous broker EXACTLY as it was, hook included.
        #
        # This replaced a version that cleared the old hook first and restored it in an
        # `except`. **That is the weaker shape: it repairs the damage rather than not doing
        # it**, and it only repairs the damage someone remembered to think of. Here the failure
        # window does not exist, at BOTH call sites, by construction.
        #
        # `B401` is what happens without it: `_reset_broker_state` cleared `_on_settle` for the
        # duration of a reset, the rebuild raised, and the OLD broker stayed in use **deaf** —
        # every later close on it silently dropped, kill switch included, because `paper.py`
        # guards the hook with a `None` check that SKIPS rather than raises. A suppression
        # scoped to a reset became permanent for the life of the process.
        # ------------------------------------------------------------------
        built = self._build_broker(starting_balance)

        previous = getattr(self, "paper", None)
        if previous is not None:
            # Suppress the OUTGOING broker's settles now that a replacement exists, so the
            # teardown cannot persist phantom closes into the run being started.
            previous._on_settle = None  # noqa: SLF001

        self.paper = built
        # Persist + resolve EVERY close (SL/TP tick, manual DELETE, kill switch) through one
        # hook — no close path can be silently lost from the DB or leave its DecisionRecord
        # stuck OPEN.
        self.paper._on_settle = self._on_settle_cb  # noqa: SLF001
        # **`B428a`, AND RECOMPUTED ON EVERY BIND.** A value carried over from the previous
        # broker would describe a broker that is no longer installed — which is the same class of
        # lie this entry exists to remove, one object along.
        self.broker_missing = self._missing_capabilities(self.paper)
        if self.broker_missing:
            logger.error(
                "broker.incapable — the bound broker cannot manage positions, so the engine "
                "cannot enforce a stop or sweep SL/TP. Entries are refused and start() will "
                "refuse. This is NOT a per-symbol tick error.",
                venue=self._select_venue(),
                broker=getattr(self.paper, "broker_name", type(self.paper).__name__),
                missing=list(self.broker_missing),
                required=list(REQUIRED_BROKER_CAPABILITIES),
            )
        self.execution = ExecutionService(self.paper, ExecMode.PAPER)

        # NAMED AT BIND TIME, and this is `B394`'s test applied to my own field rather than to
        # someone else's. `simulation_source` records WHETHER the simulation claim was checked
        # against the client's real endpoint or taken from the flag because the endpoint could
        # not be read — and until this line its only readers were its own arms, which is the
        # shape `B394` names: a remedy built for a real finding, with nobody asking it.
        #
        # An operator reading boot logs is a consumer that changes behaviour, in the same way
        # `start()` already announces the GATE-022 suppression: *a suppression that announces
        # itself once, at boot, is the difference between "nothing happened because the flag is
        # off" and "nothing happened".*
        logger.info(
            "Broker bound", venue=self._select_venue(), mode=self.mode,
            broker=getattr(self.paper, "broker_name", "?"),
            is_simulation=getattr(self.paper, "is_simulation", None),
            simulation_source=self.paper.simulation_source,
            endpoint=getattr(self.paper, "endpoint", None),
        )

    def _build_broker(self, starting_balance: float):
        """**THE ONE PLACE A VENUE BECOMES AN ADAPTER.**

        Alpaca is a real venue reached over the network; the other two are in-process simulators.
        The `direction_policy` is passed to the simulators because they must be wrong the same way
        the venue is (`B391`); `AlpacaAdapter` carries its own, because it IS the venue.
        """
        venue = self._select_venue()

        if venue == "alpaca":
            # SDK imported inside, `B328`: this module must stay importable without `alpaca-py`.
            from app.services.broker.alpaca import AlpacaAdapter

            api_key = (os.getenv("ALPACA_API_KEY") or "").strip()
            api_secret = (os.getenv("ALPACA_API_SECRET") or "").strip()
            if not api_key or not api_secret:
                # REFUSE, do not fall back to a simulator. A silent downgrade would run the
                # engine on a different venue than the one the operator selected and record a
                # config saying so — which is the class `B393` was filed for.
                raise BrokerError(
                    "broker_mode selects Alpaca but ALPACA_API_KEY / ALPACA_API_SECRET are not "
                    "set. Refusing to fall back to a simulator: a run that silently swapped its "
                    "venue would record results against settings it did not use.",
                    broker="alpaca",
                )

            from alpaca.trading.client import TradingClient

            # `raw_data=False` PINNED — it switches every return between a pydantic model and a
            # dict, and `paper=True` because `ExecMode` has no LIVE member. The adapter checks
            # that flag against the client's ACTUAL endpoint and refuses on a disagreement
            # (`B389`), so this is asserted rather than trusted.
            client = TradingClient(api_key, api_secret, paper=True, raw_data=False)
            # CONSTRUCT FIRST, LABEL SECOND (`B407`). This is exactly where `B389` refuses, so
            # assigning `self.mode` on the line above — as it was — flipped the label to
            # `ALPACA_PAPER` over a broker that was never built.
            adapter = AlpacaAdapter(client, paper=True)
            self.mode = "ALPACA_PAPER"
            return adapter

        if venue == "sim":
            from app.services.broker.cft_sim import PropFirmRules, SimPropFirmBroker

            async def _price_source(pair: str) -> float:
                return self._marks.get(pair, 0.0)

            sim = SimPropFirmBroker(
                PropFirmRules(starting_balance=starting_balance), _price_source,
                direction_policy=fixed.VENUE_DIRECTION_POLICY,
            )
            self.mode = "PROP_FIRM_SIM"   # only once the constructor has returned (`B407`)
            return sim

        paper = PaperBroker(
            starting_balance=starting_balance, price_fn=self._mark,
            direction_policy=fixed.VENUE_DIRECTION_POLICY,
        )
        self.mode = "PAPER"               # only once the constructor has returned (`B407`)
        return paper

    def _config_snapshot(self) -> dict:
        """What the engine was configured to do. Stored with the run so a result
        can never be read against the wrong settings later."""
        return {
            "broker_mode": self.broker_mode,
            "mode": self.mode,
            "symbols": list(self.symbols),
            "entry_tf": self.entry_tf,
            "bias_tf": self.bias_tf,
            "risk_pct": self.risk_pct,
            "starting_balance": self.starting_balance,
            "max_concurrent": self.max_concurrent,
            "price_source": getattr(self, "price_source_name", "binance"),
            "engine_version": ENGINE_CODE_VERSION,
            # `T-0084`. THE RUN BOUNDARY IS THE SEPARATOR AND THIS IS THE HALF THAT SAYS SO.
            #
            # `cohort` would be a trap: it names the VENUE (replay|backtest|paper|live) and a
            # policy value inside it makes one token mean two things. A row flag is not enough
            # either — it labels ROWS while the thing that changed is the POPULATION, so every
            # rate already published over a mixed run stays wrong with nothing saying so,
            # which is `B268`'s defect one level up.
            #
            # Without this entry, run N and run N+1 are two denominators with nothing
            # recording that they differ. `EngineRun.config`'s own docstring is the argument:
            # *"Snapshotted at start so a result can never be read against the wrong settings
            # later."*
            "records_rejected_signals": True,
            # ----------------------------------------------------------------
            # `T-0137`. THE MARK THAT KEEPS A LONG-ONLY RESULT FROM BEING READ AS A NORMAL ONE.
            #
            # Measured on real executed trades: 147 shorts against 146 longs. **Roughly half of
            # every decision this engine has ever made cannot be placed on Alpaca**, so a
            # long-only run is not a smaller sample of the same strategy — it is a different
            # strategy, and its P&L, win rate and R-multiples are not comparable with anything
            # recorded before the ruling.
            #
            # `EngineRun.config`'s own argument is why it belongs here and not in a new column:
            # *"Snapshotted at start so a result can never be read against the wrong settings
            # later."* Every surface that already renders a run's config is then self-marking
            # for free — which is the whole of `B380`'s lesson: a row written correctly and a
            # consumer that turns it back into an unmarked number is the same defect twice.
            #
            # **DERIVED FROM THE POLICY THE BROKER WAS ACTUALLY BUILT WITH, NOT ASSERTED.** A
            # literal `True` here would keep claiming long-only after someone changed
            # `fixed.VENUE_DIRECTION_POLICY`, and a config that describes a run it did not
            # govern is worse than one that says nothing — `B238`'s class, and this file has
            # already shipped it once.
            # `B395` — WAS THE SAFETY FLAG CHECKED, OR ONLY BELIEVED?
            #
            # `is_simulation` gates every execution. For a REMOTE venue the adapter verifies it
            # against the client's real endpoint and refuses on a disagreement (`B389`) — but
            # when the endpoint cannot be READ, construction succeeds and nothing has verified
            # anything. **That case is the only informative one**, and until now it lived in the
            # adapter's memory and died with the process: a run whose flag was confirmed and a
            # run where it was assumed left identical records.
            #
            # THREE STATES, AND THE THIRD IS WHY THIS IS NOT A BOOLEAN. An in-process simulator
            # has no endpoint to check, so marking it unverified would fire on the engine's
            # normal path — a marker that fires on every run is the liveness-signal failure:
            # routinely wrong, therefore ignored, therefore useless when it matters.
            #
            # **NO DEFAULT, DELIBERATELY.** This read was first written as
            # `getattr(self.paper, "simulation_source", "in-process ...")`, which meant an
            # adapter that failed to set it resolved to the CALMEST available sentence — absence
            # reading as safety, on the provenance of the flag that gates execution. Every
            # adapter declares it; a missing one must raise here rather than answer benignly.
            "simulation_source": self.paper.simulation_source,
            "long_only": self._long_only(),
            # `B402` — **THE VENUE THAT RAN, NOT THE POLICY'S LABEL.**
            #
            # This read `direction_policy.venue`, and there is ONE `DirectionPolicy` in the tree
            # shared by all four construction sites — so it recorded `"alpaca"` on a
            # `SimPropFirmBroker` run and on a `PaperBroker` run alike: **the name of a venue
            # those runs never touched.** `_select_venue()` knew the answer and nothing recorded
            # it.
            #
            # It lands on the analysis layer: grouping on `venue` would conclude ONE homogeneous
            # population across simulator, paper and live — the precise failure that grouping
            # exists to prevent, keyed on the field whose NAME promises the answer.
            #
            # **Contrast `long_only` directly above, which is invariant and TRUE.** Both are the
            # same value on every run today; the difference is that `B391` made both simulators
            # genuinely enforce the policy, so the invariant claim is a fact. **Invariant-and-true
            # is not a defect; invariant-and-false is.** Recorded because the two look identical
            # from the outside and the next reader will check them together.
            "venue": self._select_venue(),
            # The policy's OWN label, under a name that says what it is. A simulator standing in
            # for Alpaca is a real thing to record — it just is not the venue that ran.
            "direction_policy_venue": (
                None if getattr(self.paper, "direction_policy", None) is None
                else self.paper.direction_policy.venue
            ),
        }

    def _long_only(self) -> bool:
        """Whether the broker THIS RUN EXECUTES AGAINST can take a SHORT.

        Read off `self.paper`, which is the object `ExecutionService` was handed, so the answer
        cannot disagree with what the run will actually do.
        """
        from app.db.enums import DirectionType

        policy = getattr(self.paper, "direction_policy", None)
        return policy is not None and DirectionType.SHORT not in policy.supported

    async def ensure_run(self) -> "uuid.UUID | None":
        """Adopt the active run, or open one if there is none.

        ADOPTING matters more than creating: a restart must continue the same
        run. If this created a run every boot, every deploy would silently zero
        the dashboard and no run would ever be long enough to judge.
        """
        if self.run_id is not None:
            return self.run_id
        try:
            from sqlalchemy import select

            from app.db.session import async_session_maker
            from app.models.engine_run import EngineRun

            async with async_session_maker() as db:
                active = (
                    await db.execute(
                        select(EngineRun)
                        .where(EngineRun.ended_at.is_(None))
                        .order_by(EngineRun.started_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if active is None:
                    active = EngineRun(
                        config=self._config_snapshot(),
                        note="opened automatically on engine start",
                    )
                    db.add(active)
                    await db.commit()
                    await db.refresh(active)
                self.run_id = active.id
                logger.info("Engine run active", run_id=str(self.run_id))
        except Exception as exc:  # noqa: BLE001 - the engine must still trade
            logger.warning("Could not establish an engine run", error=str(exc))
        return self.run_id

    def apply_config(self, cfg) -> None:
        """Adopt a validated RunConfig. Only ever called as part of starting a
        new run — changing timeframe or symbols mid-run would make the result
        uninterpretable, which is why config belongs to a run."""
        self.symbols = dict(cfg.symbols)
        self.entry_tf = cfg.entry_tf
        self.bias_tf = cfg.bias_tf
        self.starting_balance = cfg.starting_balance
        self.broker_mode = cfg.broker_mode
        self.max_concurrent = cfg.max_concurrent

        # risk_pct is NOT settable — see services/live/run_config.py. It is
        # pre-registered at 1% and validate() refuses any request naming it.

        if cfg.price_source != getattr(self, "price_source_name", "binance"):
            if cfg.price_source == "cft":
                from app.services.market_data.sources.cft import CFTSource

                self.source = CFTSource()
            else:
                self.source = BinanceSource()
            self.price_source_name = cfg.price_source

    async def reset_run(self, note: str | None = None, label: str | None = None,
                        config=None) -> dict:
        """End the current run and start a clean one.

        NOTHING IS DELETED. The previous run's trades and decision records stay
        exactly where they are, still queryable by their run_id — they are the
        evidence of what the strategy did, and a reset button that destroyed
        them would undo the reason backups exist. The slate is clean because
        metrics are scoped to the new run, not because history was removed.
        """
        from datetime import datetime as _dt

        from sqlalchemy import select

        from app.db.session import async_session_maker
        from app.models.engine_run import EngineRun

        # Apply BEFORE snapshotting, so the run records what it will actually
        # run under rather than what it replaced.
        if config is not None:
            self.apply_config(config)
            note = note or config.note
            label = label or config.label

        # ------------------------------------------------------------------
        # REBUILD THE BROKER **BEFORE** SNAPSHOTTING THE CONFIG (`B393`).
        #
        # Without this the broker would carry the previous run's balance and open positions into
        # a run whose metrics start at zero. **But the ORDER is the fix, not the call.** The
        # comment above says *"Apply BEFORE snapshotting, so the run records what it will
        # actually run under rather than what it replaced"* — true of `apply_config`, and FALSE
        # of every key derived from `self.paper` while the rebuild happened afterwards. Driven:
        #
        #     snapshot taken before the rebuild -> {'long_only': False, 'venue': None}
        #     the broker the run ACTUALLY uses  -> {'long_only': True,  'venue': 'alpaca'}
        #
        # `RunHistoryPanel` renders that as a badge, so the panel would have stated the opposite
        # of the truth. **Latent until now only because all four construction sites passed the
        # same policy constant** — old and new answers coincided and the ordering error produced
        # a correct value by accident. `T-0138` is what arms it, because its whole subject is
        # making `self.paper` a different object with a different policy.
        #
        # NOT fixed by deriving those keys at read time: that turns `config` from a SNAPSHOT into
        # a live view and contradicts the sentence the field exists on — *"snapshotted at start
        # so a result can never be read against the wrong settings later."* A config that changes
        # under a later reader is a worse failure than the one being fixed.
        #
        # AND IT IS CORRECT ON THE FAILURE PATH TOO — but the reason changed, and the first
        # version of this sentence was the defect. It read: *"`_reset_broker_state` swallows its
        # exceptions and leaves `self.paper` as the old object, so snapshotting after it still
        # describes the broker actually in use."* **Right about the snapshot, silent about what
        # the swallow left behind** — a previous broker whose settle hook had been cleared for a
        # rebuild that never happened (`B401`). Worse than missing it: it promoted the swallow to
        # a documented invariant the next reader would have preserved.
        #
        # `_reset_broker_state` now RESTORES the previous broker and RE-RAISES, so this line is
        # never reached on a failed rebuild — the reset refuses instead of opening a run against
        # a venue that could not be built.
        # ------------------------------------------------------------------
        await self._reset_broker_state()

        async with async_session_maker() as db:
            for row in (
                await db.execute(select(EngineRun).where(EngineRun.ended_at.is_(None)))
            ).scalars().all():
                row.ended_at = _dt.now(tz=timezone.utc)
                db.add(row)
            fresh = EngineRun(
                config=self._config_snapshot(),
                note=note or "reset from the engine page",
                label=label,
            )
            db.add(fresh)
            await db.commit()
            await db.refresh(fresh)
            self.run_id = fresh.id

        self.started_at = datetime.now(tz=timezone.utc)
        self._last_eval.clear()
        self._open_decision.clear()
        self.activity.clear()
        # A new run is a new scan. Attributions belong to the run that observed them, and
        # the census for a date is scoped to a run's scan_id — carrying either across a
        # reset would let one run's omissions be reported inside another run's census.
        self._omissions.clear()
        self._census_date.clear()
        self.paused = False

        await self._act("engine", f"Run reset — new run started, balance back to "
                                  f"${self.starting_balance:,.0f}")
        logger.info("Engine run reset", run_id=str(self.run_id))
        return await self.status()

    async def _reset_broker_state(self) -> None:
        """Rebuild the simulation broker at its starting balance.

        Closing positions is deliberately NOT done through the normal close path:
        that fires the settle hook, which would persist phantom closes into the
        NEW run. A reset must leave no trace in the run it is starting.
        """
        # THE HOOK IS NO LONGER CLEARED HERE. `_bind_broker` suppresses the OUTGOING broker only
        # after the replacement has been built, so a failed rebuild cannot leave this one deaf.
        # The comment that used to sit on this line — *"suppress settle during reset"* — was true
        # only if the reset COMPLETED, and part 2 created a path where it does not (`B401`).
        try:
            self._bind_broker(self.starting_balance)
        except Exception as exc:
            # ------------------------------------------------------------------
            # `B401` — THE PREVIOUS BROKER WAS NEVER TOUCHED, SO THERE IS NOTHING TO RESTORE.
            # REFUSE LOUDLY.
            #
                # **WHAT IS TRUE HERE NOW:** `_bind_broker` builds the replacement into a LOCAL and
            # mutates nothing until that build succeeds — including `self.mode`, which
            # `_build_broker` now assigns only after its constructor returns (`B407`: it used to
            # assign it one line BEFORE, which made this sentence false for the label). So when it raises, `self.paper` is still
            # the previous broker **with its settle hook wired** — not repaired, never cleared.
            # This handler has no state to fix; its only job is to refuse.
            #
            # ⚠ **DO NOT CLEAR THE HOOK BEFORE `_bind_broker`.** That was the first shape of this
            # method, and it is the defect: clear-then-rebuild leaves the OLD broker in use with
            # `_on_settle = None` whenever the rebuild raises, and every later close on it —
            # SL/TP tick, manual DELETE, **and the kill switch** — is silently lost (`B221`'s
            # outcome by a new route: *the switch reports a clean trigger and closes nothing*).
            # The first fix then restored the hook in this `except`, which passes every arm
            # checking the END state and still leaves a window.
            # `..NEVER_TOUCHES_the_previous_broker_at_all` records every assignment to
            # `_on_settle` and requires ZERO during a failed rebuild — so reintroducing either
            # earlier shape turns it red. **This comment used to describe the cleared hook as the
            # current premise of this block**, which is the kind of sentence that invites the
            # next reader to put the line back; review caught it after the fix had landed.
            #
            # **PART 2 ARMED THIS AND MY OWN COMMENT DOCUMENTED THE SWALLOW AS CORRECT.** Before
            # the collapse this path built the simulators inline — no credentials, no network,
            # effectively unable to raise. `_build_broker` can: it constructs a `TradingClient`
            # and an `AlpacaAdapter` that refuses on an endpoint/flag disagreement (`B389`) and
            # raises with no credentials. **So the refusal built so a misconfigured venue cannot
            # trade was being caught and discarded.**
            #
            # RE-RAISED RATHER THAN LOGGED, because swallowing here reintroduces one level up the
            # exact defect `_build_broker` refuses internally: a run that silently swapped its
            # venue. An endpoint/flag disagreement is a DECISION, not a failure, and `B375` is
            # what a swallowed decision becomes — a permanent rule made indistinguishable from a
            # transient one. `order_path_status()`'s gate sits BEFORE `reset_run` on the same
            # principle: **do not destroy the thing you are refusing to replace.**
            # ------------------------------------------------------------------
            logger.error(
                "Broker rebuild FAILED — the previous broker is untouched, and the reset is "
                "refused rather than opening a run against a venue we could not build",
                error=str(exc), broker_mode=self.broker_mode,
            )
            raise

    async def _shadow_evaluate(self, pair: str, entry_df, engine_policy: str | None = None) -> None:
        """Emit one contract `setup_evaluation` for this bar. Never raises.

        THE SHADOW MAY NOT AFFECT THE TRADE, EVER. That is the whole safety
        property of Stage A, and it is why the body is one try/except with no
        return value the caller can act on: there is no code path by which a bad
        record, a broken rule or a dead database changes what the engine does.

        The counter is per-process and resets on restart. `sequence_no` is
        scoped to a scan, and the scan id is the run — so a restart legitimately
        begins a new scan rather than continuing one with a hole in it.

        EVERY PATH OUT OF HERE THAT WRITES NO RECORD NOW ATTRIBUTES ITSELF, and says
        which KIND of omission it is. The grader classifies its own declines; anything
        swallowed by the `except` below is a FAILURE, because a raised exception is not
        a condition the declared emission policy covers.

        None of this is written into a `rule_id`. "The layout was too thin" and "the
        database was unreachable" are engine failures, not clauses of Salim's strategy,
        and the contract's `unemitted_bars` can only hold an omission a registry rule
        authorises — so the census reports these in `notes` and leaves the resulting
        imbalance standing rather than inventing a rule that would read as permission.

        `engine_policy` is passed through to the record, not acted on. See the caller.
        """
        from app.services.telemetry import census

        bar_close_utc: datetime | None = None
        try:
            from app.db.session import async_session_maker
            from app.services.live import shadow
            from app.services.telemetry import store as telemetry_store

            bar_close_utc = self._bar_close_utc(entry_df)
            self._shadow_seq += 1
            record, decline = shadow.evaluate_detailed(
                pair,
                entry_df,
                signal_tf=self.entry_tf,
                declared=shadow.declared_parameters(),
                sequence_no=self._shadow_seq,
                scan_id=f"scan-{self.run_id}",
                engine_policy=engine_policy,
            )
            if record is None:
                cls, reason = decline or (
                    census.OMISSION_FAILURE, "the grader returned no record and no reason",
                )
                self._note_omission(pair, bar_close_utc, cls, reason)
                return
            async with async_session_maker() as db:
                await telemetry_store.store(db, record, run_id=self.run_id)
                await db.commit()
        except Exception as exc:  # noqa: BLE001 - a shadow may never reach the trader
            logger.warning("Shadow evaluation not recorded", pair=pair, error=str(exc))
            self._note_omission(
                pair, bar_close_utc, census.OMISSION_FAILURE, f"{type(exc).__name__}: {exc}",
            )

    def _bar_close_utc(self, entry_df) -> datetime:
        """The CLOSE time, in UTC, of the last bar in `entry_df`.

        The frame is indexed by bar OPEN time, so the period is added here rather than
        assumed anywhere else. Both sides of the census's set difference go through this
        same conversion, which is what stops one side counting opens and the other closes.
        """
        from app.services.live.shadow import schema_tf
        from app.services.telemetry import census

        moment = entry_df.index[-1].to_pydatetime()
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return census.bar_close(moment, census.period_for(schema_tf(self.entry_tf)))

    def _note_omission(
        self, pair: str, bar_close_utc: "datetime | None", cls: str, reason: str,
    ) -> None:
        """Remember WHY a bar produced no record. Never raises, never counts.

        A bar whose close time could not even be read is deliberately not recorded under
        a guessed key: the census would then attribute the omission to the wrong bar,
        which is worse than reporting it unattributed. It is still COUNTED either way —
        the set difference finds it without this map — and lands in the census's
        `unattributed` bucket, which C-13 reports.
        """
        if bar_close_utc is None:
            return
        self._omissions.setdefault(pair, {})[bar_close_utc] = (cls, reason)

    def _bar_opens(self, df) -> list[datetime]:
        """Every bar OPEN time in a frame, as aware UTC. Naive index -> UTC, as elsewhere."""
        out: list[datetime] = []
        for ts in df.index:
            moment = ts.to_pydatetime()
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            out.append(moment.astimezone(timezone.utc))
        return out

    async def _maybe_emit_census(self, pair: str, bsym: str, entry_df) -> None:
        """Emit the population record for the NY session date that just ended.

        Never raises: a census is a measurement of the engine and must not be able to
        stop it, exactly as the shadow cannot.

        The trigger is a bar whose NY date differs from the last one seen for this pair.
        A session's bars cannot be counted while the session is still running, and a
        census emitted early would report a partial window as a whole one — which is the
        undercount this record exists to detect, produced by the record itself.
        """
        from app.services.live.shadow import schema_tf
        from app.services.telemetry import census

        try:
            closed = self._bar_close_utc(entry_df)
            today = census.session_date_of(closed)
            previous = self._census_date.get(pair)
            self._census_date[pair] = today
            if previous is None or previous == today:
                return
            await self._emit_census(pair, bsym, previous, schema_tf(self.entry_tf))
        except Exception as exc:  # noqa: BLE001 - a census may never reach the trader
            logger.warning("Census not emitted", pair=pair, error=str(exc))

    async def _emit_census(self, pair: str, bsym: str, session_date: str, tf: str) -> None:
        """Build and store one `scan_census`, with both counts derived externally."""
        from app.db.session import async_session_maker
        from app.services.live import shadow
        from app.services.telemetry import census
        from app.services.telemetry import store as telemetry_store

        period = census.period_for(tf)
        frm, to = census.session_window(session_date)
        # Enough bars to span the window with room to spare. `_fetch_bars` always ends at
        # NOW, and this runs one bar into the new session, so the window is the most
        # recent full day plus a little — the slack covers the bar we are standing on, a
        # 25-hour fall-back day, and a feed that returns short.
        want = int((to - frm) / period) + 30
        frame = await self._fetch_bars(bsym, self.entry_tf, want)

        async with async_session_maker() as db:
            record = await census.build_scan_census(
                db,
                declared=shadow.declared_parameters(),
                instrument={
                    "symbol": pair,
                    "instrument_class": "ALIGNED_MAJOR",
                    # The same claim the setup_evaluations for this window carry, so the
                    # census and the records it counts describe one instrument rather
                    # than two that must be reconciled by a reader.
                    "venue": "BINANCE_SPOT",
                },
                signal_tf=tf,
                session_date=session_date,
                bar_opens=self._bar_opens(frame),
                attributions=self._omissions.get(pair, {}),
                # Unique per (run, pair, timeframe, session date). `record_id` is unique
                # in the store, so a second attempt at the same census raises rather than
                # quietly writing a duplicate the conformance suite would count twice.
                scan_id=f"census-{self.run_id}-{pair}-{tf}-{session_date}",
            )
            await telemetry_store.store(db, record, run_id=self.run_id)
            await db.commit()

        kept = {k: v for k, v in self._omissions.get(pair, {}).items() if k >= to}
        self._omissions[pair] = kept
        logger.info(
            "Census emitted", pair=pair, session_date=session_date,
            bars_observed=record["bars_observed"],
            evaluations_emitted=record["evaluations_emitted"],
            unemitted=len(record["unemitted_bars"]),
        )

    async def _take_partials(self, pair: str, price: float) -> None:
        """Bank EXIT-001's 70% when price reaches the 2R level. The runner keeps its stop.

        > **THE RUNNER'S STOP IS NOT TOUCHED HERE AND MUST NEVER BE.** `EXIT-001`: *"the runner
        > is PASSIVE — it does not trail, scale or move its stop"*, because `EXIT-003` is OPEN
        > and Salim re-confirmed passivity in round 3.

        The backtest does move it — `runner_trail_atr = 2.5`, *"never below break-even"* — and
        that policy is OFF-DOCTRINE. It is the most likely thing to leak into this method,
        because it is more sophisticated and it is thirty lines away in another file. **A
        break-even shift is a stop movement**, so "only to break-even" is not a lesser version
        of trailing; it is the same violation.
        """
        for pid, plan in list(self._tranche_plans.items()):
            if plan["pair"] != pair or pid in self._partialled:
                continue
            reached = (
                price >= plan["price"] if plan["direction"] == "LONG"
                else price <= plan["price"]
            )
            if not reached:
                continue
            position = next(
                (p for p in await self.paper.get_positions() if str(p.id) == pid), None
            )
            if position is None:
                self._tranche_plans.pop(pid, None)
                continue
            units = float(position.lot_size)
            lot = round(units * plan["fraction"], 8)
            if lot <= 0 or lot >= units:
                # Nothing to split. Refuse rather than close the whole position under a name
                # that says "partial" — T-0038's own defect, in the caller this time.
                self._tranche_plans.pop(pid, None)
                continue
            event = await self.paper.close_position(pid, lot_size=lot)
            if event.get("status") == "refused":
                logger.warning("EXIT-001 partial refused", pair=pair, pid=pid, lot=lot)
                continue
            self._partialled.add(pid)
            self._tranche_plans.pop(pid, None)
            await ws_manager.push_position_close(event)
            await self._act(
                "exit",
                f"EXIT-001 partial: banked {plan['fraction']:.0%} of {pair} at "
                f"{plan['price']:.0f} ({event.get('pnl', 0):+.0f} USDT) — "
                f"{_fmt_units(event.get('remaining_units', 0))} units run on, stop UNCHANGED",
            )

    async def _close_at_session_end(self, now_ny: datetime) -> None:
        """EXIT-001's third terminal reason: the 19:00 New York session close.

        **Built here because without it the runner has NO termination but the stop.** Before
        this cutover every position carried a 2R take-profit and ended there; after it the 30%
        remainder has no target at all (TARGET-001 cannot select one), so an unimplemented
        session close would leave it riding indefinitely — which is not EXIT-001's model, it is
        the absence of one.

        The time is `DECLARED_SESSION_CLOSE`: **OURS, UNRATIFIED, and stamped as such.** 19:00
        enters the codex only through the EURUSD / algo HT v2.0 strand while our instrument
        trades 24/7, and question 4 to Salim is unanswered. It is implemented as stated so the
        record shows how often a runner is cut and what R it was carrying — which is the
        evidence the ruling should rest on.
        """
        if self._last_session_close is not None and self._last_session_close >= now_ny.date():
            return
        if now_ny.time() < DECLARED_SESSION_CLOSE.local_time:
            return
        self._last_session_close = now_ny.date()
        positions = await self.paper.get_positions()

        # GATE-022 IS EVALUATED AND RECORDED WHETHER OR NOT IT MAY ACT.
        #
        # T-0051 gates the ORDER, never the rule. Suppressing the RECORD too would destroy the
        # evidence Salim's question 4 will be answered against — how often a runner WOULD have
        # been cut, and what R it was carrying. That evidence is the entire reason the flatten
        # was implemented as stated in T-0050.
        verdict = SessionClose.evaluate(now_ny)
        would_flatten = len(positions)

        if not DECLARED_SESSION_FLATTEN.enabled:
            # SUPPRESSED, AND SAID SO. `0 flattens` must never read as "it ran and found
            # nothing" — B179's trap, built here deliberately and therefore labelled here
            # deliberately. The count of what WOULD have closed is the load-bearing half.
            logger.info(
                "GATE-022 session flatten SUPPRESSED",
                flag=DECLARED_SESSION_FLATTEN.name,
                enabled=False,
                verdict=verdict.verdict,
                would_have_closed=would_flatten,
                reason="Salim question 4 unanswered; Malek operating decision 2026-08-19",
            )
            if would_flatten:
                await self._act(
                    "exit",
                    f"GATE-022 {DECLARED_SESSION_CLOSE.local_time:%H:%M} NY reached — "
                    f"{would_flatten} position(s) WOULD have been flattened. SUPPRESSED by "
                    f"{DECLARED_SESSION_FLATTEN.name}=false ([ENGINEERING], ours): question 4 "
                    "is unanswered. The runner now terminates on STOP_HIT only.",
                )
            return

        if not positions:
            return
        for position in positions:
            pid = str(position.id)
            event = await self.paper.close_position(pid)
            self._tranche_plans.pop(pid, None)
            self._partialled.discard(pid)
            await ws_manager.push_position_close(event)
        await self._act(
            "exit",
            f"EXIT-001 SESSION_CLOSE {DECLARED_SESSION_CLOSE.local_time:%H:%M} NY — closed "
            f"{len(positions)} position(s). DECLARED and UNRATIFIED (question 4, unanswered).",
        )

    async def _record_rejected_signal(
        self, pair: str, entry_df, sig, reason: str, trace,
        rejection_code: str | None = None,
    ) -> None:
        """Persist a signal the strategy PRODUCED and execution REFUSED (`B271`).

        **PERSISTENCE ONLY. Nothing re-runs.** `compare_entry(...).record_on(trace)` already
        ran at `:1409`, ABOVE both the abstention fork and this rejection — so every bar
        carries its comparison on the trace before execution can refuse it, and this writes
        what is already there. *`T-0037`'s structural property survives for free*: its comment
        says the seam runs AFTER the decision has returned, so "changes no decision" is
        structural rather than tested-into-place, and persisting an existing trace cannot
        weaken it. **Any fix that moved or re-ran the comparison would.**

        NEITHER EXISTING WRITER COULD TAKE THIS ROW. `_record_signal_decision` asserts `OPEN`
        with `sized_units`, `fill_price` and `expected_r` from a fill this bar does not have;
        `_record_abstention` asserts `abstained=True, outcome=ABSTAINED` and the strategy DID
        produce a signal.

        `abstained` is FALSE here, and that is the field that keeps the two apart even for a
        reader who does not know `REJECTED` exists.

        Never raises: bookkeeping must not be able to stop the engine trading.
        """
        try:
            from decimal import Decimal

            from app.db.session import async_session_maker
            from app.models.decision_record import (
                COHORT_PAPER, OUTCOME_REJECTED, REJECTION_UNCLASSIFIED, Attribution,
                DecisionRecord,
            )

            entry = float(sig.entry)
            rec = DecisionRecord(
                symbol=pair, timeframe=self.entry_tf,
                inputs_hash=self._inputs_hash(entry_df),
                code_path_hash=self._code_path_hash(),
                score=None,
                # NOT an abstention. The detector fired.
                abstained=False,
                reasons=_with_exit_plan(trace.reasons if trace is not None else None),
                signal_dir=sig.direction.value,
                signal_entry=Decimal(str(round(entry, 6))),
                signal_sl=Decimal(str(round(float(sig.sl), 6))),
                signal_tp=(
                    Decimal(str(round(float(sig.tp), 6))) if sig.tp is not None else None
                ),
                # NO sized_units and NO fill_price: there was no fill, and inventing either
                # would put a number nobody observed into the feedback loop's population.
                outcome=OUTCOME_REJECTED,
                rejection_reason=str(reason),
                # **ABSENT MEANS NOBODY CLASSIFIED IT, AND THAT ALARMS** (`B392`). The default is
                # the alarming state, never the benign one: a rejection arriving with no code is
                # a decision site that did not set one, which is a defect — and it must not be
                # confused with `UNCODED_LEGACY`, which means *predates the field*, is finite,
                # and decays to zero on its own.
                rejection_code=rejection_code or REJECTION_UNCLASSIFIED,
                cohort=COHORT_PAPER,
                run_id=self.run_id,
                **Attribution.ict().as_columns(),
            )
            async with async_session_maker() as db:
                db.add(rec)
                await db.commit()
        except Exception as exc:  # noqa: BLE001 - never let bookkeeping kill the loop
            logger.warning("record rejection failed", pair=pair, error=str(exc))

    async def _record_abstention(self, pair: str, entry_df, trace) -> None:
        """Persist WHY no trade was taken.

        Volume is modest — one row per symbol per closed bar, so ~48/day at 1H
        on two symbols — and it is the only record that the strategy was
        evaluated at all. Without it a quiet detector and a correctly selective
        one look identical.

        Never raises: bookkeeping must not be able to stop the engine trading.
        """
        try:
            from app.db.session import async_session_maker
            from app.models.decision_record import (
                COHORT_PAPER, OUTCOME_ABSTAINED, Attribution, DecisionRecord,
            )
            rec = DecisionRecord(
                symbol=pair, timeframe=self.entry_tf,
                inputs_hash=self._inputs_hash(entry_df),
                code_path_hash=self._code_path_hash(),
                score=None, abstained=True,
                reasons=trace.reasons,
                outcome=OUTCOME_ABSTAINED, cohort=COHORT_PAPER,
                run_id=self.run_id,
                # An ICT abstention. The shadow's rule-engine verdict for this
                # same bar is recorded separately in `telemetry_records` and is
                # not what stood this trade aside.
                **Attribution.ict().as_columns(),
            )
            async with async_session_maker() as db:
                db.add(rec)
                await db.commit()
        except Exception as exc:  # noqa: BLE001 - never let bookkeeping kill the loop
            logger.warning("record abstention failed", pair=pair, error=str(exc))

    async def _open_decision_id_from_db(self, pair: str) -> str | None:
        """The still-OPEN decision for `pair`, read from the database rather than memory.

        **`ARM 1`.** `_open_decision` is a dict on this object; a restart between the 70%
        partial and the 30% runner empties it, and the runner's close — the one carrying the
        larger half of the P&L — would resolve nothing. The decision rows themselves are the
        durable index: `outcome` is written `OPEN` at creation and only ever leaves that state
        here, so *"the open decision for this symbol"* is a query, not a cache.

        At most one can match: `_entry_block_reason` refuses a second entry while the symbol
        holds a position, so a pair has one open decision at a time. `LIMIT 1` on the newest
        is belt-and-braces rather than a tie-break that could go either way.
        """
        try:
            from sqlalchemy import select

            from app.db.session import async_session_maker
            from app.models.decision_record import OUTCOME_OPEN, DecisionRecord

            async with async_session_maker() as db:
                row = (await db.execute(
                    select(DecisionRecord)
                    .where(
                        DecisionRecord.symbol == pair,
                        DecisionRecord.outcome == OUTCOME_OPEN,
                        DecisionRecord.sized_units.is_not(None),
                    )
                    .order_by(DecisionRecord.created_at.desc())
                    .limit(1)
                )).scalars().first()
            return str(row.id) if row is not None else None
        except Exception as exc:  # noqa: BLE001 - never let bookkeeping kill the loop
            logger.warning("open decision lookup failed", pair=pair, error=str(exc))
            return None

    async def _realised_pnl_for_position(self, ev: dict) -> float:
        """Every tranche's P&L for this position, summed from the DURABLE rows.

        `_persist_live_close` writes each tranche BEFORE `_resolve_decision` runs, and after
        `B225` they share `broker_id` — the broker's position id — so the sum is a query over
        rows that survive a restart rather than a number accumulated in memory.

        **Falls back to this event's own P&L** when the position id is missing or no rows
        match, which is the pre-`B225` shape and every row written before this change. That
        fallback is the OLD behaviour, so a failure here degrades to what the system already
        did rather than to zero — *a bookkeeping path that can report 0.0 profit is worse than
        one that reports too little.*
        """
        own = float(ev.get("pnl", 0) or 0)
        position_id = ev.get("position_id")
        if not position_id:
            return own
        try:
            from sqlalchemy import func, select

            from app.db.session import async_session_maker
            from app.models.trade import Trade

            async with async_session_maker() as db:
                total = (await db.execute(
                    select(func.sum(Trade.pnl_dollars)).where(
                        Trade.broker_id == str(position_id)
                    )
                )).scalar()
            return own if total is None else float(total)
        except Exception as exc:  # noqa: BLE001
            logger.warning("tranche sum failed", position_id=str(position_id), error=str(exc))
            return own

    async def _resolve_decision(self, ev: dict) -> None:
        """On the FINAL close, fill the matching decision's realized_r / gap_r / outcome.

        realized_r is computed from the decision's own stored geometry — pnl over the dollar
        risk it was sized to (|entry-sl| * units) — so it is comparable to expected_r on the
        same basis (the feedback loop's core measurement).

        **`B223`: THIS USED TO RUN ON EVERY CLOSE, INCLUDING THE 70% PARTIAL**, popping the
        decision key and writing `realized_r` from the tranche. The 30% runner then closed,
        found no key, and returned — so every winner's record described 70% of itself while
        every loser, closing whole at its stop, was recorded in full. *The bias is not
        symmetric: losses complete, wins truncated, in the field `:1065` calls the feedback
        loop's core input.* ETH 2026-08-19 13:17:01 recorded 1.5276 against a true +228.68.

        **THE ACCUMULATOR IS THE `trades` ROWS, NOT A DICT.** Holding the 70%'s P&L in memory
        until the runner closes is `B224` at smaller scale: if the runner never closes — the
        state both symbols are in at 66 h and 94 h — the accumulator dies with the process and
        the 70% is lost too, trading a truncated record for no record. The rows are written by
        `_persist_live_close` BEFORE this runs, they survive a restart, and after `B225` the
        tranches of one position share a `broker_id`.
        """
        pair = str(ev.get("pair"))

        # PART-CLOSED IS NOT RESOLVED, AND `partial` IS THE BROKER'S OWN EXACT ANSWER.
        # Not `SUM(closed) < sized_units`: that is `B227` — a float comparison across three
        # roundings that do not commute — and this task inherits it MIRRORED, as a finished
        # trade that never resolves. `remaining > 0` is computed once at 10dp by the broker
        # and handed over; no arithmetic here can disagree with it.
        if ev.get("partial"):
            # `realized_r` stays NULL. Nothing honest exists for a 70%-closed, 30%-open
            # position: the closed leg has a realized R, the open leg has an unrealised one
            # that moves every tick, and no weighting of them is a fact about the trade.
            # Verified affordable — every consumer either renders "—" or filters
            # `is not None`; none divides by it or defaults it to zero.
            return

        dec_id = self._open_decision.pop(pair, None)
        if not dec_id:
            # THE DURABLE PATH, and it is what makes a restart survivable. `_open_decision`
            # is in-memory: a process that dies between the partial and the runner loses it,
            # and this method would then return early on the close that matters most.
            dec_id = await self._open_decision_id_from_db(pair)
        if not dec_id:
            return
        try:
            from decimal import Decimal

            from sqlalchemy import select
            from app.db.session import async_session_maker
            from app.models.decision_record import (
                OUTCOME_BREAKEVEN, OUTCOME_LOSS, OUTCOME_WIN, DecisionRecord,
            )
            pnl = await self._realised_pnl_for_position(ev)
            async with async_session_maker() as db:
                rec = (await db.execute(
                    select(DecisionRecord).where(
                        DecisionRecord.id == _as_decision_id(dec_id)
                    ))).scalar_one_or_none()
                if rec is None:
                    return
                # Measure against the price PAID, not the price asked for. Using
                # signal_entry here divided pnl by a dollar risk the account
                # never actually had, so realized_r was systematically wrong by
                # the fill drift — and gap_r, the feedback loop's core input,
                # inherited that error. Falls back to signal_entry for rows
                # written before fill_price was recorded.
                fill = rec.fill_price
                entry = float(fill if fill is not None else (rec.signal_entry or 0))
                sl = float(rec.signal_sl or 0)
                units = float(rec.sized_units or 0)
                risk_dollars = abs(entry - sl) * units
                realized_r = (pnl / risk_dollars) if risk_dollars > 0 else None
                if realized_r is not None:
                    rec.realized_r = Decimal(str(round(realized_r, 4)))
                    if rec.expected_r is not None:
                        rec.gap_r = Decimal(str(round(realized_r - float(rec.expected_r), 4)))
                rec.outcome = (
                    OUTCOME_WIN if pnl > 1e-9 else OUTCOME_LOSS if pnl < -1e-9 else OUTCOME_BREAKEVEN
                )
                db.add(rec)
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("resolve decision failed", pair=pair, error=str(exc))

    def _on_settle_cb(self, ev: dict) -> None:
        """Sync hook fired by the broker on every close. Schedules durable
        persistence + decision resolution on the running loop. If no loop is
        running (e.g. a sync unit test), it's a no-op — the test drives
        _persist_and_resolve directly."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._persist_and_resolve(dict(ev)))

    async def _persist_and_resolve(self, ev: dict) -> None:
        await self._persist_live_close(ev)
        await self._resolve_decision(ev)

    async def _persist_live_close(self, ev: dict) -> None:
        """F3: persist a LIVE paper close to the DB so live trades are durable
        across restarts and separable from the warm-up replay (source tag
        'ICT (live)' vs 'Backtest replay'). The close-event carries no sl/tp/r,
        which are nullable columns, so this is a clean closed-trade insert."""
        try:
            from decimal import Decimal

            from app.db.enums import DirectionType, OutcomeType, TradeStatus
            from app.db.session import async_session_maker
            from app.models.trade import SETUP_TAG_LIVE, Trade

            pnl = float(ev.get("pnl", 0) or 0)
            is_long = str(ev.get("direction")) == "LONG"
            row = Trade(
                # `broker_id` ALREADY MEANS the broker's position id — `reconciler.py:75`
                # keys `{broker_id: Trade}` against `pos.id`. Writing the literal "paper"
                # gave one distinct value across all 274 rows while `ev["position_id"]` sat
                # unused in the same dict (`B225`). It is also what makes T-0063's summing
                # possible: the tranches of one position now share a key.
                user_id="system",
                broker_id=str(ev.get("position_id") or "paper"),
                broker="paper", pair=str(ev.get("pair")),
                direction=DirectionType.LONG if is_long else DirectionType.SHORT,
                entry_price=Decimal(str(round(float(ev.get("entry", 0) or 0), 6))),
                exit_price=Decimal(str(round(float(ev.get("exit", 0) or 0), 6))),
                lot_size=Decimal(str(round(float(ev.get("units", 0) or 0), 6))),
                entry_time=ev.get("open_time"), exit_time=ev.get("close_time"),
                outcome=OutcomeType.WIN if pnl > 0 else OutcomeType.LOSS,
                status=TradeStatus.CLOSED, pnl_dollars=Decimal(str(round(pnl, 2))),
                setup_tag=SETUP_TAG_LIVE,
                run_id=self.run_id,
            )
            async with async_session_maker() as db:
                db.add(row)
                await db.commit()
        except Exception as exc:  # noqa: BLE001 - never let persistence kill the loop
            logger.warning("persist live close failed", error=str(exc))

    async def _tick_symbol(self, pair: str, bsym: str) -> None:
        price = await asyncio.to_thread(_ticker_price, bsym)
        if price is None:
            return
        self._marks[pair] = price
        # EXIT-001 STAGE B: bank 70% at the 2R partial, BEFORE the SL/TP sweep below.
        #
        # Ordering is deliberate. If a single tick reaches both the partial level and the stop,
        # the partial is the earlier event in price terms on the way up (long) and taking it
        # first is what EXIT-001 describes. Running the sweep first would close the whole
        # position and the partial could never fire.
        await self._take_partials(pair, price)
        # mark-to-market + auto-close SL/TP
        for ev in self.paper.on_tick(pair, price):
            # Persistence + decision resolution happen via the broker's settle
            # hook (_on_settle_cb) for ALL close paths; here we only push UI.
            await ws_manager.push_position_close(ev)
            await self._act("exit", f"Closed {pair} {ev.get('reason')} {ev.get('pnl', 0):+.0f} USDT")
        await ws_manager.push_tick(pair, price, price, 0.0)

        # EXIT-001's THIRD terminal reason. Checked on the tick path because that is the only
        # clock this loop has — there is no scheduler — and it is idempotent per NY date.
        await self._close_at_session_end(to_ny(datetime.now(timezone.utc)))

        # new closed entry-TF bar? -> evaluate strategy
        entry = await self._fetch_bars(bsym, self.entry_tf, 320)
        if entry.empty or len(entry) < 60:
            return
        entry = entry.iloc[:-1]  # drop the still-forming bar
        closed_t = entry.index[-1]
        if self._last_eval.get(pair) == closed_t:
            return
        self._last_eval[pair] = closed_t

        # M9 STAGE A — ABOVE THE ENTRY GATES, and the position matters.
        #
        # This call used to sit below the `return` on the next block, so the shadow
        # never saw a bar where the ICT path was blocked — and `already in a position`
        # is the engine's normal state. It therefore missed **exactly the bars
        # following an entry**, which are the bars on which the two strategies would
        # most differ. On 2026-08-13: an entry at 19:00, then 20:00, 21:00 and 22:00
        # all skipped, three consecutive bars the contract engine never evaluated
        # (KNOWN_ISSUES B34).
        #
        # It also made `emission_policy_id="every-closed-bar-roster-v1"` false on every
        # record that carried it.
        #
        # Placed here rather than merely earlier: the bar is already marked consumed
        # above, `entry` already has the forming bar dropped, and the shadow does not
        # read `bias` — which is fetched below the gates. So nothing else moves.
        #
        # Still incapable of affecting a trade: it returns None, it takes a copy of the
        # frame rather than mutating the one the ICT path is about to use, and every
        # exception is swallowed. Being above the gates changes what it SEES, not what
        # it can DO.
        # T-0011 — the block reason, computed EARLY and FOR THE RECORD ONLY.
        #
        # The shadow's record is the only per-bar artefact that survives the process, so
        # it is where "what the live engine would have done with this bar" has to be
        # written. At the old position — after the gates — there was nothing left to
        # attach it to, because the gates `return`.
        #
        # THIS VALUE IS NEVER REUSED AT THE GATE, and that is deliberate rather than an
        # oversight. `_entry_block_reason` reads live mutable state — `kill_switch`,
        # `self.paused`, and `await self._has_position(pair)` — and the shadow call below
        # is `async` and does database I/O, so it YIELDS. A position closed during that
        # yield, or a kill switch armed during it, would leave a reused value describing
        # a world that no longer exists: the engine would skip on "already in a position"
        # while holding none. That is a changed TRADING decision produced by a
        # bookkeeping change, and it would present as a market condition rather than as a
        # bug. The cost of re-evaluating is two position reads.
        engine_policy = await self._entry_block_reason(pair)

        await self._shadow_evaluate(pair, entry, engine_policy)

        # The population record for the session that just ended, if one just did.
        await self._maybe_emit_census(pair, bsym, entry)

        # Entry gates — the bar is marked consumed above, BEFORE these gates, on
        # purpose (re-testing a stale bar later in the hour would fire a market
        # order sized off a stale FVG edge). Each block reason is surfaced to the
        # UI so the engine never no-ops silently.
        #
        # RE-EVALUATED, not reused. See the comment on `engine_policy` above; the
        # ordering is asserted by test_t0011_census.py::test_the_gate_re_evaluates_...
        block = await self._entry_block_reason(pair)
        if block is not None:
            # `B415`. This read `block.startswith("KILL SWITCH")` — the classification lived in
            # the first eleven characters of a human sentence. **An unclassified reason defaults to
            # `halt`, not `skip`**: a block whose seriousness we cannot establish is the alarming
            # case, and this label is display-only, so erring loud costs an operator a second look
            # and erring quiet hides a stopped engine.
            kind = getattr(block, "kind", BLOCK_HALT)
            await self._act(kind, f"{pair} {self.entry_tf} bar closed — {block}, skipped")
            return
        bias = await self._fetch_bars(bsym, self.bias_tf, 220)

        # T-0036 STAGE A: RECORDED, NOT ENFORCED. The verdict lands on the trace beside the
        # three existing gates and suppresses no signal. A gate that has never been observed
        # to block anything must not be given the power to block, and `trace.would_block_by`
        # is the count that has to be non-zero and read before Stage B may enforce.
        news = await self._news_context()
        sig, trace = evaluate_latest_bar_traced(
            pair, entry, bias, risk_pct=self.risk_pct, news=news
        )
        # T-0037 THE ENTRY SEAM. Runs AFTER the decision has already returned, on the trace it
        # produced -- so "change no decision" is structural rather than tested-into-place: this
        # cannot influence a decision that has been made. Not one line inside
        # `evaluate_latest_bar_traced` is touched by it.
        #
        # `compare_entry` catches everything and records NOT_COMPARABLE(RULE_RAISED); the
        # `try` here is the second layer, for a failure in building the bars themselves. A
        # parallel observer that can crash the trading loop is worse than no observer.
        try:
            compare_entry(trace, _bars_from_frame(entry), tf=self.entry_tf).record_on(trace)
        except Exception as exc:  # noqa: BLE001 - the observer may never reach the decision
            logger.warning("Entry comparison failed; decision unaffected", error=str(exc))
        if sig is None:
            # Record WHY, not just that nothing happened. DecisionRecord has
            # carried `abstained`/`reasons`/ABSTAINED since it was written and
            # nothing ever populated them — rows appeared only when an order
            # filled, so the engine's refusals (most of what it does) left no
            # trace at all. "No valid setup" is indistinguishable from "the
            # detector never fires", which is precisely the question a
            # simulation exists to answer.
            await self._record_abstention(pair, entry, trace)
            await self._act("eval", f"{pair} {self.entry_tf} bar closed — {trace.summary}")
            return
        # T-0038 HALF 2, STAGE A: record the tranche plan EXIT-001 WOULD produce. Executes
        # nothing -- the position is still opened whole below, and `close_position` is not
        # called with a lot_size anywhere on this path. The count has to exist before the
        # behaviour does, which is the same staging T-0036 used for the news verdict.
        exit_shadow.record_from_loop(trace, sig)
        await self._act("signal", f"{pair} {sig.direction.value} setup @ {sig.entry:.0f}")
        # ------------------------------------------------------------------
        # A RAISING REJECTION MUST LEAVE A ROW (`B403`).
        #
        # `execute()` catches `DirectionNotSupported` and nothing else, and there is no handler
        # between here and `_loop`'s blanket `except` — so any other raise from `place_order`
        # **aborted the bar before `_record_rejected_signal` ran and left NO ROW AT ALL.** Not an
        # unclassified row: absent from the denominator entirely. A surface reading *"100% of
        # rejections were direction refusals"* would then be reporting the shape of a silence,
        # which is the population defect part 3 exists to prevent, arriving one layer earlier.
        #
        # LIVE ON THE RUNNING BROKERS, not only on Alpaca: both simulators raise
        # `ValueError("lot_size must be > 0")`, reachable when sizing rounds to zero — rare,
        # because it needs a corrupt signal, **and rare is the argument FOR recording it**, since
        # nobody reconstructs a 1e12 stop distance from a log line six weeks later.
        #
        # NOT FIXED BY NARROWING `_loop`'s HANDLER. That handler is correct — one bad pair must
        # not stop the engine — and narrowing it trades a silent gap for a dead engine. The defect
        # is that the abort was not RECORDED. `service.py:189` is the precedent: it already does
        # exactly this, for the one exception type it knew about.
        # ------------------------------------------------------------------
        try:
            res = await self.execution.execute(sig)
        except AlpacaUnprotectedPositionOpen as exc:
            # ------------------------------------------------------------------
            # **`B429`. A POSITION MAY BE OPEN AND UNPROTECTED — SO NO REJECTION ROW.**
            #
            # The handler below records `REJECTION_VENUE_RAISED` for anything the broker raises:
            # a row asserting the engine did not trade. Here the venue TOOK the order, would not
            # take the stop, and flat was NOT observed after remediation — a live position with no stop at
            # the venue and none in process (`B428`). That row would be false in the direction
            # that hides the danger, which is the `PARTIALLY_FILLED`-recorded-as-refused defect
            # this file already documents forty lines down.
            #
            # Halting and arming the alarm are ONE act (`B424`) — see `_declare_halt`.
            # ------------------------------------------------------------------
            self._declare_halt(HALT_UNPROTECTED_POSITION)
            logger.error(
                "live.unprotected_position — HALTING. The venue accepted the order, refused the "
                "stop, and flat was not observed after cancel and close. Reconcile AT THE VENUE before "
                "restarting: there is no stop there and none in this process.",
                pair=pair, direction=sig.direction.value,
                order_id=getattr(exc, "order_id", None),
                detail=getattr(exc, "detail", None),
            )
            await self._act(
                BLOCK_HALT,
                f"{pair} {sig.direction.value} — HALTED: {HALT_UNPROTECTED_POSITION} "
                f"(order {getattr(exc, 'order_id', 'UNREPORTED')})",
            )
            # LAST, and after the halt is already in force (`M-7`): this records the halt, it does
            # not perform it. A failure here cannot un-halt.
            await self._record_unprotected_position(pair, sig, exc)
            raise
        except Exception as exc:  # noqa: BLE001 - recorded, then re-raised to the loop's handler
            await self._record_rejected_signal(
                pair, entry, sig,
                # Redacted and bounded for the same reason as the transport path: this string
                # is PERSISTED, and the log filter does not reach a database column.
                f"{type(exc).__name__}: {redact_for_storage(str(exc))}",
                trace, REJECTION_VENUE_RAISED,
            )
            await self._act(
                "reject",
                f"{pair} {sig.direction.value} setup NOT taken — the broker raised "
                f"{type(exc).__name__}",
            )
            raise
        # ------------------------------------------------------------------
        # `B413`/`T-0141`. THREE OUTCOMES, NOT TWO, and the size is resolved BEFORE the branch so
        # there stays exactly ONE call to `_record_signal_decision` — a second call site is a
        # second place the sizing inputs can be forgotten, which
        # `test_decision_record_schema.py` asserts against by AST.
        status = res.get("status")          # the RAW value, for logs and records only
        outcome = classify_order_status(status)   # the ONE decision about what it means (K-11)
        opened_units = self._position_units(res)

        if outcome in FILL_OUTCOMES and opened_units is None:
            # **THE VENUE ACTED AND WE CANNOT SAY WHAT WE NOW HOLD. FAIL CLOSED.**
            #
            # Ruled: a partial whose size we cannot read HALTS the run with a named reason, because
            # trading around a position of unknown size is worse than stopping.
            #
            # **AND NO REJECTION ROW IS WRITTEN HERE.** Before this, a `PARTIALLY_FILLED` result
            # fell through to the `else` below, which recorded `outcome=REJECTED`,
            # `rejection_reason="PARTIALLY_FILLED"`, `rejection_code=UNCLASSIFIED` — measured by
            # evaluating that branch against the dict the adapter really returns. So the engine did
            # not lose the event; **it recorded a refusal of an order the venue had partly
            # filled.** A false row is worse than none here, because `B399`: a population nobody
            # can characterise, and this one reads as coverage.
            # Halting and arming the alarm are ONE act (`B424`) — see `_declare_halt`.
            self._declare_halt(HALT_PARTIAL_UNSIZED)
            logger.error(
                "live.partial_fill_unsized — HALTING. the venue acted on the order and reported "
                "no usable filled quantity, so a position of unknown size may exist",
                pair=pair, direction=sig.direction.value, status=status,
                filled_units=res.get("filled_units"), submitted_units=res.get("units"),
                # **THE HALT NAMED THE SITUATION AND NOT THE OBJECT.** `res` carries the venue's
                # own id for the position it just opened, so without it the thing this halt warns
                # about is not directly findable at the venue — the operator is told a position of
                # unknown size may exist and given no way to go and look at it.
                position_id=res.get("position_id"),
                client_order_id=res.get("client_order_id"),
            )
            await self._act(
                BLOCK_HALT,
                f"{pair} {sig.direction.value} — HALTED: {HALT_PARTIAL_UNSIZED} "
                f"(status {status}, filled {res.get('filled_units')!r}, "
                f"venue position {res.get('position_id') or 'UNREPORTED'})",
            )
            # LAST, and after the halt is already in force (`M-7`): this records the halt, it does
            # not perform it. Every line above has already run, so a failure here cannot un-halt.
            await self._record_unsized_fill(pair, entry, sig, res)
            return

        if outcome in FILL_OUTCOMES:
            logger.info("Live paper entry", pair=pair, dir=sig.direction.value, fill=res.get("fill"),
                        status=status, opened_units=opened_units)
            # STAGE B. The plan EXIT-001 produces is now EXECUTED, not merely recorded.
            pid = res.get("position_id")
            if pid and sig.partial_price is not None and sig.partial_fraction is not None:
                self._tranche_plans[str(pid)] = {
                    "price": float(sig.partial_price),
                    "fraction": float(sig.partial_fraction),
                    "direction": sig.direction.value,
                    "pair": pair,
                }
            await self._record_signal_decision(
                # **THE SIZE OF THE POSITION THAT EXISTS, not the size we asked for** (`M-1`).
                # This read `res.get("sized_units", 0)` — the quantity `size_position` computed —
                # which for a partial fill is larger than what we hold, and `sized_units` is what
                # the partial-close accounting reads (`:1579`, `:1624`). So the asked size here
                # would make the ladder try to close more than exists.
                #
                # NAMING, and it is `B402`'s shape (`M-1`'s footnote): the parameter and the column
                # are both called `sized_units`, a name for the ASKED quantity, while every
                # consumer already treats the value as the POSITION's size. The name is wrong and
                # renaming a column is a migration plus a consumer sweep — reported as its own
                # item rather than smuggled in here. The asked size is not lost: it is
                # reconstructible from `sizing_equity`, `sizing_risk_pct` and `sizing_price`, which
                # is what `B279`/`B280` added them for.
                pair, entry, sig, opened_units, fill_price=res.get("fill"),
                trace=trace,
                # `B279`. The two inputs `size_position` was actually called with. Passed
                # from the execution result rather than re-read here: a second read of
                # `acct.equity` would be a different number by the time it happened, and
                # would look like the one the size was computed from.
                sizing_equity=res.get("equity_at_entry"),
                sizing_risk_pct=sig.risk_pct,
                # The DIVISOR the size was computed from — `mark` for a market order, and
                # NOT the fill. `B280`.
                sizing_price=res.get("sizing_price"),
            )
            await ws_manager.push_position_open(res)
            # **`B417`, SECOND HALF: THE CONDITIONAL BOUND OVER THE WHOLE CONCATENATION.**
            #
            # This was one expression — four implicitly-joined f-strings, then
            # `if sig.partial_price is not None else` a fifth. Python binds the conditional across
            # the entire joined string, so the `else` branch produced **only**
            # `"@ 70000 (SL 99, no exit plan)"`: the pair, the direction and the size all dropped,
            # leaving an entry line that does not say what was entered.
            #
            # **Latent rather than live, and stated as such:** `strategy_step.py:224,248` set
            # `partial_price` on both the LONG and SHORT paths, so every signal the live strategy
            # produces takes the first branch. It is reachable from a hand-built signal — which is
            # how it surfaced, in an arm written for the size format.
            #
            # Split so the subject is unconditional and only the exit clause varies.
            exit_clause = (
                f"{sig.partial_fraction:.0%} at {sig.partial_price:.0f}, "
                f"remainder passive to STOP_HIT or SESSION_CLOSE"
                if sig.partial_price is not None else "no exit plan"
            )
            # **`B433` (F-2). THE FILL IS READ BY VALUE, AND NOTHING STANDS IN FOR IT.** This was
            # `res.get('fill', sig.entry):.0f`. `.get(key, default)` returns `None` when the key is
            # PRESENT with `None` — Alpaca's result carries `"fill": None` whenever the venue gave no
            # usable price — so the format raised TypeError AFTER the decision was recorded and the
            # position pushed. And where the default did apply it printed the SIGNAL's entry after "@",
            # a fill price nobody reported. So an unreported price is said to be unreported.
            fill_px = res.get("fill")
            fill_text = (f"@ {fill_px:.0f}" if isinstance(fill_px, (int, float)) and not isinstance(fill_px, bool)
                         else "@ fill price unreported")
            await self._act(
                "entry",
                f"Entered {pair} {sig.direction.value} {_fmt_units(opened_units)} "
                f"{fill_text} (SL {sig.sl:.0f}, {exit_clause})",
            )
        elif outcome == ORDER_REFUSED:
            # NEVER drop a generated signal silently. A rejection (non-positive
            # size, or a sim-mode prop-firm breach) is surfaced with its reason.
            #
            # **`T-0130`: ONLY AN AFFIRMATIVE REFUSAL REACHES THIS BRANCH.** It was the `else`, so
            # an absent status, `None`, an acknowledgement and a `CANCELED` order carrying a fill
            # were all recorded here as refusals — measured, each with `rejection_code` `None`.
            reason = res.get("reason") or res.get("status") or outcome
            # `res.get("rejection_code")` is deliberately NOT defaulted here. A missing code means
            # the decision site did not set one, and `_record_rejected_signal` turns that into
            # `UNCLASSIFIED`, which alarms. Supplying a plausible code at this layer would be
            # inventing a classification the decision never made. The PROSE fallback used to be the
            # literal `"rejected"`, which no decision site produced; it is now the class the
            # classifier DID decide (`T-0130`) — and it is not a code, which is why the code must not
            # follow it.
            code = res.get("rejection_code")
            logger.info("Live signal not filled", pair=pair, dir=sig.direction.value, reason=reason)
            # `B271`: the bar was previously observable only in a maxlen=80 deque that is
            # cleared on start. It is now a row.
            await self._record_rejected_signal(pair, entry, sig, reason, trace, code)
            await self._act(
                "reject",
                f"{pair} {sig.direction.value} setup NOT taken — {reason}",
            )
        else:
            # **`T-0130`. NEITHER A FILL NOR A REFUSAL — so neither recorder, and no position push.**
            await self._on_unresolved_order(pair, entry, sig, res, trace)

    # ------------------------------------------------------------------
    # Lifecycle — Start, Pause, Stop
    # ------------------------------------------------------------------
    async def start(self) -> dict:
        """Open a fresh run and begin scanning. Idempotent while already running.

        START ALWAYS OPENS A NEW RUN, and closes any run left open by a crash or
        a killed container. It does not adopt one. Adopting is what produced
        KNOWN_ISSUES A9: the loop picked up an open run and carried on writing
        into it under whatever settings it happened to boot with, so the run's
        stored config stopped describing the trades filed beneath it. One press,
        one run, one configuration — and a run that was interrupted is closed
        where it stopped rather than silently resumed hours later with a gap in
        the middle that nothing records.

        Nothing is deleted by this. The interrupted run keeps its trades and its
        decisions; it simply ends.
        """
        if self._running:
            return await self.status()

        # ------------------------------------------------------------------
        # REFUSE TO START AGAINST A VENUE THAT CANNOT PLACE AN ORDER (`T-0138`).
        #
        # **ONE REFUSAL, BEFORE THE RUN EXISTS — not 146 identical failures afterwards.** With an
        # unwritten order path every entry fails individually, and an operator reading a wall of
        # venue errors concludes the VENUE is broken rather than that the platform was pointed at
        # a half-built adapter. That is `B380`'s shape: a correct record turned into the wrong
        # conclusion by the surface it reaches, and here the wrong conclusion sends someone to
        # Alpaca's status page.
        #
        # ASKED OF THE ADAPTER, NOT KEYED ON THE VENUE'S NAME. `if broker_mode == "alpaca"` would
        # be a second copy of a fact the adapter already knows, and it would still be refusing
        # runs the day after part D wrote the body — `B184` with a string, and stale by
        # construction.
        #
        # BEFORE `reset_run`, deliberately. Refusing after it would have already ended the
        # previous run and opened a new one, so a rejected start would destroy the run it
        # refused to replace.
        # **`B428a`, AND DELIBERATELY BESIDE `order_path_status`.** That refusal asks whether the
        # venue can PLACE an order. This asks whether we can MANAGE what it places, which is the
        # question nobody had asked — `AlpacaAdapter` answers the first affirmatively and has no
        # answer to the second. Same shape, same place, so a reader meets both together.
        if self.broker_missing:
            reason = (f"{BLOCK_BROKER_INCAPABLE} — {type(self.paper).__name__} is missing "
                      f"{', '.join(self.broker_missing)}, so SL/TP cannot be swept and no stop "
                      f"can be enforced")
            logger.error("Engine start REFUSED — broker cannot manage positions",
                         broker=getattr(self.paper, "broker_name", "?"),
                         missing=list(self.broker_missing))
            await self._act("engine", f"Engine NOT started — {reason}")
            return {"started": False, "reason": reason, "broker_missing": list(self.broker_missing)}

        blocked = self.paper.order_path_status()
        if blocked is not None:
            logger.warning("Engine start REFUSED — venue cannot place orders",
                           broker=getattr(self.paper, "broker_name", "?"), reason=blocked)
            await self._act("engine", f"Engine NOT started — {blocked}")
            return {**await self.status(), "started": False, "refused": blocked}

        # Close the books on anything a previous process left dangling BEFORE
        # opening a new run, so the abandoned records belong to the run that
        # created them rather than to this one.
        await self.reconcile_abandoned_decisions()

        await self.reset_run(note="started from the engine page")
        await self.paper.connect()
        self._running = True
        self.started_at = datetime.now(tz=timezone.utc)
        self._task = asyncio.create_task(self._loop())
        logger.info("LiveCryptoLoop started", symbols=list(self.symbols),
                    run_id=str(self.run_id))
        # NAMED AT STARTUP, not only in the record it later fails to produce. A suppression
        # that announces itself once, at boot, is the difference between "nothing happened at
        # 19:00 because the flag is off" and "nothing happened at 19:00".
        logger.info(
            "GATE-022 session flatten "
            + ("ENABLED" if DECLARED_SESSION_FLATTEN.enabled else "SUPPRESSED"),
            flag=DECLARED_SESSION_FLATTEN.name,
            enabled=DECLARED_SESSION_FLATTEN.enabled,
            authority=DECLARED_SESSION_FLATTEN.authority,
            retirement_condition=DECLARED_SESSION_FLATTEN.retirement_condition,
        )
        await self._act(
            "engine",
            f"Engine started — {self.mode}, {self.entry_tf} entries on "
            f"{', '.join(self.symbols)} @ {self.risk_pct*100:.0f}% risk, "
            f"${self.starting_balance:,.0f} balance",
        )
        if not DECLARED_SESSION_FLATTEN.enabled:
            await self._act(
                "engine",
                "GATE-022's 19:00 NY flatten is SUPPRESSED ([ENGINEERING], ours) — Salim's "
                "question 4 on whether a 24/7 instrument flattens daily is unanswered. The rule "
                "still evaluates and is still recorded; only the ORDER is withheld, so an "
                "EXIT-001 runner terminates on STOP_HIT alone.",
            )
        return await self.status()

    async def stop(self) -> dict:
        """Stop scanning and END the run. Safe to call when already stopped.

        OPEN POSITIONS ARE CLOSED, not abandoned. A stopped engine marks no
        prices, so an open position's stop-loss and take-profit would never be
        checked again — it would sit at whatever it was worth the moment the
        engine stopped, and the run's result would be missing a trade that never
        resolved. Closing them at the current mark goes through the normal settle
        path, so each one is persisted against this run with its real P&L.

        The run is ended AFTER that, so the closes land inside it.
        """
        was_running = self._running
        self._running = False

        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

        if was_running:
            try:
                closed = await self.paper.close_all_positions()
                if closed:
                    await self._act(
                        "engine",
                        f"Engine stopping — closed {len(closed)} open position(s) at "
                        "the current price so the run has no unresolved trades",
                    )
            except Exception as exc:  # noqa: BLE001 - stopping must not be blockable
                logger.warning("Could not close positions on stop", error=str(exc))

            await self._end_run()
            await self._act("engine", "Engine STOPPED — run ended")
            logger.info("LiveCryptoLoop stopped", run_id=str(self.run_id))

        self.paused = False
        return await self.status()

    async def reconcile_abandoned_decisions(self) -> int:
        """Resolve decisions the process died holding. Returns how many.

        THE FAILURE THIS EXISTS FOR (KNOWN_ISSUES A11)
        The simulated broker keeps its positions in memory. On 2026-08-08 a run
        opened an ETH long at 06:00; twelve hours later the container was
        recreated for a deploy and the position ceased to exist without ever
        being closed. Its decision record still read `outcome = OPEN`, no trade
        row was ever written, and the run reported "0 trades" when it had taken
        one. Every restart could do that, and nothing noticed.

        WHY `OPEN` HAD TO STOP MEANING TWO THINGS
        `OPEN` claims a position is still running. For a record whose process is
        gone that is not merely stale, it is false — and it is false in the
        direction that keeps the record out of the feedback loop forever, since
        the loop only reads closed outcomes. `ABANDONED` says the trade happened
        and its result is unknowable, which is the true thing.

        WHAT COUNTS AS ABANDONED
        Only records the CURRENT process is not tracking. A record this loop
        holds in `_open_decision` belongs to a live position and is left alone —
        that is what makes this safe to run at Start rather than only at boot.

        Never raises: a bookkeeping failure must not stop the engine starting.
        """
        try:
            from sqlalchemy import select

            from app.db.session import async_session_maker
            from app.models.decision_record import (
                OUTCOME_ABANDONED, OUTCOME_OPEN, DecisionRecord,
            )

            live = {str(v) for v in self._open_decision.values()}
            async with async_session_maker() as db:
                rows = (
                    await db.execute(
                        select(DecisionRecord).where(DecisionRecord.outcome == OUTCOME_OPEN)
                    )
                ).scalars().all()
                stranded = [r for r in rows if str(r.id) not in live]
                for rec in stranded:
                    rec.outcome = OUTCOME_ABANDONED
                    reasons = list(rec.reasons or [])
                    # Say it in the record itself. Someone reading this row later
                    # should not have to know that ABANDONED implies a restart.
                    reasons.append(
                        "ABANDONED: the engine stopped while this position was open, "
                        "so its result was never observed. Not a loss — an absence."
                    )
                    rec.reasons = reasons
                    db.add(rec)
                if stranded:
                    await db.commit()

            if stranded:
                logger.warning(
                    "Resolved decisions abandoned by an earlier process",
                    count=len(stranded),
                )
                await self._act(
                    "engine",
                    f"{len(stranded)} decision(s) from an earlier session were left open "
                    "by a restart — recorded as ABANDONED, not as results",
                )
            return len(stranded)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not reconcile abandoned decisions", error=str(exc))
            return 0

    async def _end_run(self) -> None:
        """Stamp the active run as finished. Never raises — a bookkeeping failure
        must not leave the caller believing the engine is still running."""
        try:
            from datetime import datetime as _dt

            from sqlalchemy import select

            from app.db.session import async_session_maker
            from app.models.engine_run import EngineRun

            async with async_session_maker() as db:
                for row in (
                    await db.execute(select(EngineRun).where(EngineRun.ended_at.is_(None)))
                ).scalars().all():
                    row.ended_at = _dt.now(tz=timezone.utc)
                    db.add(row)
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not close the engine run", error=str(exc))

    async def run(self) -> None:
        """Backwards-compatible entry point: start and block until stopped.

        Kept because the loop body used to be the public surface. Nothing in the
        application calls it now — `start()` owns the task.
        """
        await self.start()
        task = self._task
        if task is not None:
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while self._running:
            for pair, bsym in self.symbols.items():
                try:
                    await self._tick_symbol(pair, bsym)
                except Exception as exc:  # noqa: BLE001 - never let one symbol kill the loop
                    # **`B428a`. THE SEVERITY DECISION, AND IT IS THE WHOLE ENTRY.**
                    #
                    # "Never let one symbol kill the loop" is right, and it was answering the
                    # wrong question. A broker that lacks a method this loop calls is not one
                    # symbol having a bad tick — it is true of EVERY symbol and EVERY poll, and
                    # logging it per symbol at warning level is how a permanently broken engine
                    # reported itself as running for as long as anyone cared to watch.
                    #
                    # Keyed on the CAPABILITY rather than on the exception type: catching
                    # `AttributeError` would be a guess about how the next missing member fails,
                    # and a broker missing `on_tick` fails this way only by accident of syntax.
                    if self.broker_missing:
                        logger.error(
                            "Live loop symbol error — STRUCTURAL, not per-symbol. The bound "
                            "broker is missing capabilities this loop requires, so every symbol "
                            "and every poll will fail identically until it is replaced.",
                            pair=pair, error=str(exc),
                            missing=list(self.broker_missing),
                        )
                    else:
                        logger.warning("Live loop symbol error", pair=pair, error=str(exc))
            try:
                await self._push_state()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Live loop push error", error=str(exc))
            await asyncio.sleep(self.poll_interval)
