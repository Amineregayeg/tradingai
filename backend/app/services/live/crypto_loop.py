"""LiveCryptoLoop — real-time crypto PAPER trading spine.

Polls Binance for BTC/ETH, marks the PaperBroker to the live price (firing
SL/TP), runs the validated strategy on each newly-closed entry-TF bar, executes
via the mode-gated ExecutionService (PAPER), and pushes ticks / positions /
account over the existing WebSocket. No real broker is touched — paper only.
"""
from __future__ import annotations

import asyncio
import json
import urllib.request
from collections import deque
from datetime import datetime, timedelta, timezone

from app.core.logging import logger
from app.services.broker.paper import PaperBroker
from app.services.execution.service import ExecMode, ExecutionService
from app.services.live.strategy_step import evaluate_latest_bar
from app.services.market_data.sources.binance import BinanceSource
from app.services.ws.manager import ws_manager

_DEFAULT_SYMBOLS = {"BTC/USD": "BTCUSDT", "ETH/USD": "ETHUSDT"}


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
        risk_pct: float = 0.02,
        max_concurrent: int = 3,
        poll_interval: float = 10.0,
    ) -> None:
        self.symbols = symbols or dict(_DEFAULT_SYMBOLS)
        self.entry_tf = entry_tf
        self.bias_tf = bias_tf
        self.risk_pct = risk_pct
        self.max_concurrent = max_concurrent
        self.poll_interval = poll_interval
        self.paper = PaperBroker(starting_balance=starting_balance, price_fn=self._mark)
        self.execution = ExecutionService(self.paper, ExecMode.PAPER)
        self.source = BinanceSource()
        self._marks: dict[str, float] = {}
        self._last_eval: dict[str, datetime] = {}
        self._running = False
        self.paused = False
        self.started_at: datetime | None = None
        self.mode = "PAPER"
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
        """Engine status + metrics for the monitoring panel."""
        acct = await self.paper.get_account()
        closed = list(self.paper._closed)
        wins = sum(1 for c in closed if c["pnl"] > 0)
        losses = sum(1 for c in closed if c["pnl"] <= 0)
        return {
            "running": self._running,
            "paused": self.paused,
            "mode": self.mode,
            "symbols": list(self.symbols),
            "entry_tf": self.entry_tf,
            "risk_pct": self.risk_pct,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "starting_balance": self.starting_balance,
            "balance": acct.balance,
            "equity": acct.equity,
            "unrealized_pl": acct.unrealized_pl,
            "open_positions": acct.open_trade_count,
            "closed_trades": len(closed),
            "wins": wins,
            "losses": losses,
            "win_rate": round(100 * wins / len(closed), 1) if closed else 0.0,
            "total_pnl": round(acct.equity - self.starting_balance, 2),
            "total_pnl_pct": round(100 * (acct.equity / self.starting_balance - 1), 2),
            "activity": list(self.activity)[:40],
        }

    async def warmup(self, days: int = 14) -> dict:
        """Backfill the paper account with the strategy's REAL trades over the
        last `days` of Binance data, so the metrics panel shows genuine recent
        gains/losses (real strategy decisions on real prices)."""
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
        from app.models.trade import Trade

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
                "reason": "TP" if pnl > 0 else "SL",
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
                setup_tag="ICT Magic Alignment",
            ))
        try:
            async with async_session_maker() as db:
                # clear any prior warmup rows so re-running doesn't duplicate
                from sqlalchemy import delete
                await db.execute(delete(Trade).where(Trade.broker == "paper"))
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
        minutes = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1H": 60, "4H": 240, "D": 1440}.get(tf, 60)
        end = datetime.now(tz=timezone.utc)
        start = end - timedelta(minutes=minutes * (count + 5))
        return await asyncio.to_thread(self.source.fetch_ohlcv, binance_symbol, tf, start, end)

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

    async def _tick_symbol(self, pair: str, bsym: str) -> None:
        price = await asyncio.to_thread(_ticker_price, bsym)
        if price is None:
            return
        self._marks[pair] = price
        # mark-to-market + auto-close SL/TP
        for ev in self.paper.on_tick(pair, price):
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

        if self.paused or await self._has_position(pair) or await self._open_count() >= self.max_concurrent:
            return
        bias = await self._fetch_bars(bsym, self.bias_tf, 220)
        sig = evaluate_latest_bar(pair, entry, bias, risk_pct=self.risk_pct)
        if sig is None:
            await self._act("eval", f"{pair} {self.entry_tf} bar closed — no valid setup")
            return
        await self._act("signal", f"{pair} {sig.direction.value} setup @ {sig.entry:.0f}")
        res = await self.execution.execute(sig)
        if res.get("status") == "FILLED":
            logger.info("Live paper entry", pair=pair, dir=sig.direction.value, fill=res.get("fill"))
            await ws_manager.push_position_open(res)
            await self._act(
                "entry",
                f"Entered {pair} {sig.direction.value} {res.get('sized_units', 0):.3f} "
                f"@ {res.get('fill', sig.entry):.0f} (SL {sig.sl:.0f} TP {sig.tp:.0f})",
            )

    async def run(self) -> None:
        self._running = True
        self.started_at = datetime.now(tz=timezone.utc)
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
