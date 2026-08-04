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
        entry_tf: str = "1H",
        bias_tf: str = "D",
        starting_balance: float = 50_000.0,
        risk_pct: float = 0.01,   # pre-registered FIXED at 1% (not a tunable knob)
        max_concurrent: int = 3,
        poll_interval: float = 10.0,
        broker_mode: str | None = None,
    ) -> None:
        self.symbols = symbols or dict(_DEFAULT_SYMBOLS)
        self.entry_tf = entry_tf
        self.bias_tf = bias_tf
        self.risk_pct = risk_pct
        self.max_concurrent = max_concurrent
        self.poll_interval = poll_interval
        # Broker: "paper" = plain simulation; "sim" = SimPropFirmBroker, which
        # enforces the prop-firm challenge rules (daily loss / drawdown / target)
        # — the mode Agent B assigns a strategy to and tests against. Both are
        # is_simulation=True; no real order is ever possible from this loop.
        self.broker_mode = (broker_mode or os.getenv("ENGINE_BROKER", "paper")).lower()
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
        # With PRICE_SOURCE=cft the loop reads Crypto Fund Trader's own candles
        # instead of Binance's. That matters because the strategy trades
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
        source_name = (os.getenv("PRICE_SOURCE", "binance") or "binance").strip().lower()
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
                COHORT_PAPER, OUTCOME_OPEN, DecisionRecord,
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
                COHORT_PAPER, OUTCOME_ABSTAINED, DecisionRecord,
            )
            rec = DecisionRecord(
                symbol=pair, timeframe=self.entry_tf,
                inputs_hash=self._inputs_hash(entry_df),
                code_path_hash=self._code_path_hash(),
                score=None, abstained=True,
                reasons=trace.reasons,
                outcome=OUTCOME_ABSTAINED, cohort=COHORT_PAPER,
                run_id=self.run_id,
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

        # Entry gates — the bar is marked consumed above, BEFORE these gates, on
        # purpose (re-testing a stale bar later in the hour would fire a market
        # order sized off a stale FVG edge). Each block reason is surfaced to the
        # UI so the engine never no-ops silently.
        block = await self._entry_block_reason(pair)
        if block is not None:
            kind = "halt" if block.startswith("KILL SWITCH") else "skip"
            await self._act(kind, f"{pair} {self.entry_tf} bar closed — {block}, skipped")
            return
        bias = await self._fetch_bars(bsym, self.bias_tf, 220)
        sig, trace = evaluate_latest_bar_traced(pair, entry, bias, risk_pct=self.risk_pct)
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

    async def run(self) -> None:
        self._running = True
        self.started_at = datetime.now(tz=timezone.utc)
        await self.ensure_run()
        await self.paper.connect()
        logger.info("LiveCryptoLoop started", symbols=list(self.symbols))
        await self._act(
            "engine",
            f"Engine started — PAPER, {self.entry_tf} entries on {', '.join(self.symbols)} "
            f"@ {self.risk_pct*100:.0f}% risk, ${self.starting_balance:,.0f} balance",
        )
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

    async def stop(self) -> None:
        self._running = False
