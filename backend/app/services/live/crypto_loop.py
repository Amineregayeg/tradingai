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
from datetime import datetime, timedelta, timezone

from app.core.logging import logger
from app.services.broker.paper import PaperBroker
from app.services.execution.service import ExecMode, ExecutionService
from app.services.live import fixed_config as fixed
from app.services.live.news_context import (
    NewsContext,
    build_news_context,
    fetch_calendar_events,
)
from app.services.telemetry.ny_time import to_ny
from app.services.live.strategy_step import evaluate_latest_bar_traced
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
        if self.broker_mode == "sim":
            from app.services.broker.cft_sim import PropFirmRules, SimPropFirmBroker

            async def _price_source(pair: str) -> float:
                return self._marks.get(pair, 0.0)

            self.paper = SimPropFirmBroker(
                PropFirmRules(starting_balance=starting_balance), _price_source
            )
            self.mode = "PROP_FIRM_SIM"
        else:
            self.paper = PaperBroker(starting_balance=starting_balance, price_fn=self._mark)
            self.mode = "PAPER"
        # Persist + resolve EVERY close (SL/TP tick, manual DELETE, kill switch)
        # through one hook — no close path can be silently lost from the DB or
        # leave its DecisionRecord stuck OPEN.
        self.paper._on_settle = self._on_settle_cb
        self.execution = ExecutionService(self.paper, ExecMode.PAPER)

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
            closed = [c for c in self.paper._closed if c.get("reason") != "replay"]
            closed_n = len(closed)
            wins = sum(1 for c in closed if c["pnl"] > 0)
            losses = sum(1 for c in closed if c["pnl"] <= 0)
            realized = sum(float(c.get("pnl", 0) or 0) for c in closed)

        balance = round(self.starting_balance + realized, 2)
        equity = round(balance + acct.unrealized_pl, 2)
        return {
            "running": self._running,
            "paused": self.paused,
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
            "win_rate": round(100 * wins / closed_n, 1) if closed_n else 0.0,
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
        if self.broker_mode == "sim":
            await self._act("engine", "Warm start skipped — prop-firm sim account stays clean")
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
        if kill_switch.is_armed:
            return f"KILL SWITCH ARMED ({kill_switch.reason or 'no reason given'})"
        if self.paused:
            return "engine paused"
        if await self._has_position(pair):
            return "already in a position"
        if await self._open_count() >= self.max_concurrent:
            return f"max concurrent {self.max_concurrent} reached"
        return None

    async def _news_context(self) -> NewsContext | None:
        """T-0036 Stage A — the order path's news verdict, RECORDED and not enforced.

        Deliberately NOT part of `_entry_block_reason`. That function documents itself as
        *"pure gate logic (no network) so it is directly testable"*, and it is the ENFORCING
        path — a reason returned there skips the bar. Stage A must suppress nothing, and
        putting a calendar fetch there would break a property the function states about
        itself. **Stage B belongs there, and will need the events passed in rather than
        fetched, for that same reason.**

        Returns `None` when the calendar could not be read. **`None` is NOT an empty
        calendar**: the evaluator records it as `NOT-EVALUATED`, so a period of provider
        outage is visible in the traces instead of being indistinguishable from a quiet news
        week. A `[]` here would make an unreachable calendar say *"no blackout"* — the
        fail-open `T-0035` closed at the source, rebuilt at the consumer.
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
        await ws_manager.broadcast(
            channel="positions", event="update",
            data={"positions": [p.model_dump(mode="json") for p in positions]},
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

    async def _record_signal_decision(
        self, pair: str, entry_df, sig, sized_units: float, fill_price: float | None = None,
        trace=None,
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
                reasons=(trace.reasons if trace is not None else None),
                signal_dir=sig.direction.value,
                signal_entry=Decimal(str(round(entry, 6))),
                signal_sl=Decimal(str(round(sl, 6))),
                signal_tp=Decimal(str(round(tp, 6))) if tp is not None else None,
                fill_price=Decimal(str(round(fill, 6))) if fill is not None else None,
                sized_units=Decimal(str(round(float(sized_units), 6))),
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
        }

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

        # Reset the in-memory simulation to match. Without this the broker would
        # carry the previous run's balance and open positions into a run whose
        # metrics start at zero — the same incoherence this task exists to fix.
        await self._reset_broker_state()

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
        try:
            self.paper._on_settle = None  # noqa: SLF001 - suppress settle during reset
            if self.broker_mode == "sim":
                from app.services.broker.cft_sim import PropFirmRules, SimPropFirmBroker

                async def _price_source(pair: str) -> float:
                    return self._marks.get(pair, 0.0)

                self.paper = SimPropFirmBroker(
                    PropFirmRules(starting_balance=self.starting_balance), _price_source
                )
            else:
                self.paper = PaperBroker(
                    starting_balance=self.starting_balance, price_fn=self._mark
                )
            self.paper._on_settle = self._on_settle_cb  # noqa: SLF001
            self.execution = ExecutionService(self.paper, ExecMode.PAPER)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Broker reset failed", error=str(exc))

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

    async def _resolve_decision(self, ev: dict) -> None:
        """On close, fill the matching OPEN decision's realized_r / gap_r / outcome.

        realized_r is computed from the decision's own stored geometry — pnl over
        the dollar risk it was sized to (|entry-sl| * units) — so it is comparable
        to expected_r on the same basis (the feedback loop's core measurement)."""
        pair = str(ev.get("pair"))
        dec_id = self._open_decision.pop(pair, None)
        if not dec_id:
            return
        try:
            from decimal import Decimal

            from sqlalchemy import select
            from app.db.session import async_session_maker
            from app.models.decision_record import (
                OUTCOME_BREAKEVEN, OUTCOME_LOSS, OUTCOME_WIN, DecisionRecord,
            )
            pnl = float(ev.get("pnl", 0) or 0)
            async with async_session_maker() as db:
                rec = (await db.execute(
                    select(DecisionRecord).where(DecisionRecord.id == dec_id))).scalar_one_or_none()
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
                user_id="system", broker_id="paper", broker="paper", pair=str(ev.get("pair")),
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
        # mark-to-market + auto-close SL/TP
        for ev in self.paper.on_tick(pair, price):
            # Persistence + decision resolution happen via the broker's settle
            # hook (_on_settle_cb) for ALL close paths; here we only push UI.
            await ws_manager.push_position_close(ev)
            await self._act("exit", f"Closed {pair} {ev.get('reason')} {ev.get('pnl', 0):+.0f} USDT")
        await ws_manager.push_tick(pair, price, price, 0.0)

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
            kind = "halt" if block.startswith("KILL SWITCH") else "skip"
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
        await self._act("signal", f"{pair} {sig.direction.value} setup @ {sig.entry:.0f}")
        res = await self.execution.execute(sig)
        if res.get("status") == "FILLED":
            logger.info("Live paper entry", pair=pair, dir=sig.direction.value, fill=res.get("fill"))
            await self._record_signal_decision(
                pair, entry, sig, res.get("sized_units", 0), fill_price=res.get("fill"),
                trace=trace,
            )
            await ws_manager.push_position_open(res)
            await self._act(
                "entry",
                f"Entered {pair} {sig.direction.value} {res.get('sized_units', 0):.3f} "
                f"@ {res.get('fill', sig.entry):.0f} (SL {sig.sl:.0f} TP {sig.tp:.0f})",
            )
        else:
            # NEVER drop a generated signal silently. A rejection (non-positive
            # size, or a sim-mode prop-firm breach) is surfaced with its reason.
            reason = res.get("reason") or res.get("status") or "rejected"
            logger.info("Live signal not filled", pair=pair, dir=sig.direction.value, reason=reason)
            await self._act(
                "reject",
                f"{pair} {sig.direction.value} setup NOT taken — {reason}",
            )

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
        await self._act(
            "engine",
            f"Engine started — {self.mode}, {self.entry_tf} entries on "
            f"{', '.join(self.symbols)} @ {self.risk_pct*100:.0f}% risk, "
            f"${self.starting_balance:,.0f} balance",
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
                    logger.warning("Live loop symbol error", pair=pair, error=str(exc))
            try:
                await self._push_state()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Live loop push error", error=str(exc))
            await asyncio.sleep(self.poll_interval)
