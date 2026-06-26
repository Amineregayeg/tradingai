"""Trading AI Co-Pilot — FastAPI application entry point."""
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.api.routers import (
    alerts_router,
    analysis_router,
    audit_log_router,
    brokers_router,
    calendar_router,
    candles_router,
    engine_router,
    ict_router,
    journal_router,
    positions_router,
    prop_firm_router,
    screenshots_router,
    settings_router,
    system_router,
    trades_router,
    ws_router,
)
from app.config import settings
from app.core.exceptions import TradingAIError, problem_response
from app.core.logging import logger, setup_logging
from app.core.security import get_request_id

# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown)
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler — initialises all services in dependency order."""
    setup_logging()
    logger.info(
        "Trading AI Co-Pilot starting up",
        version=app.version,
        environment=settings.oanda_environment,
    )

    # Ensure data directories exist
    data_dir = settings.data_dir
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(os.path.join(data_dir, "screenshots"), exist_ok=True)
    os.makedirs(os.path.join(data_dir, "logs"), exist_ok=True)
    logger.info("Data directories ensured", data_dir=data_dir)

    # ------------------------------------------------------------------
    # 1. Redis client (shared across services)
    # ------------------------------------------------------------------
    import redis.asyncio as aioredis

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)

    # ------------------------------------------------------------------
    # 2. AI service
    # ------------------------------------------------------------------
    try:
        from app.db.session import async_session_maker
        from app.services.ai.service import ai_service

        ai_service.init(api_key=settings.anthropic_api_key, db_factory=async_session_maker)
        logger.info("AI service initialised")
    except Exception as exc:
        logger.warning("AI service init failed (non-fatal)", error=str(exc))

    # ------------------------------------------------------------------
    # 3. Calendar service
    # ------------------------------------------------------------------
    try:
        from app.services.calendar.finnhub import calendar_service

        calendar_service.init(api_key=settings.finnhub_api_key, redis_client=redis_client)
        logger.info("Calendar service initialised")
    except Exception as exc:
        logger.warning("Calendar service init failed (non-fatal)", error=str(exc))

    # ------------------------------------------------------------------
    # 4. Candle pipeline — DB session factory
    # ------------------------------------------------------------------
    from app.db.session import async_session_maker  # noqa: F811 (already imported above but isolated)
    from app.services.market_data.pipeline import candle_pipeline

    candle_pipeline.set_db_session_factory(async_session_maker)

    # ------------------------------------------------------------------
    # 5. Wire candle pipeline → ICT detector
    # ------------------------------------------------------------------
    from app.services.ict.detector import ict_detector

    ict_detector.set_db_session_factory(async_session_maker)
    candle_pipeline.on_candle_close(ict_detector.on_candle_close_callback)

    # ------------------------------------------------------------------
    # 6. Wire candle pipeline → decision engine
    # ------------------------------------------------------------------
    from app.services.decision.engine import decision_engine

    async def _decision_on_candle(pair: str, timeframe: str, candle: dict) -> None:
        try:
            async with async_session_maker() as db:
                await decision_engine.on_candle_close(pair, timeframe, candle, db)
        except Exception as exc:
            logger.error("Decision engine candle handler error", error=str(exc))

    candle_pipeline.on_candle_close(_decision_on_candle)

    # ------------------------------------------------------------------
    # 7. Wire decision engine alert callback → WS
    # ------------------------------------------------------------------
    from app.services.ws.manager import ws_manager

    decision_engine.register_alert_callback(ws_manager.push_alert)

    # ------------------------------------------------------------------
    # 8. Wire ICT detector → WS
    # ------------------------------------------------------------------
    ict_detector.register_ws_callback(ws_manager.push_ict_detected)

    # ------------------------------------------------------------------
    # 9. Wire broker manager price callback → candle pipeline + WS
    # ------------------------------------------------------------------
    from app.services.broker.manager import broker_manager

    async def _on_price_tick(tick: dict) -> None:
        """Receive a normalised tick dict from any broker adapter.

        Every adapter forwards the same shape:
        ``{"pair", "instrument", "bid", "ask", "time", "tradeable", "type", "broker"}``.
        """
        from datetime import datetime, timezone

        if not isinstance(tick, dict):
            return

        pair = tick.get("pair")
        bid_raw = tick.get("bid")
        ask_raw = tick.get("ask")
        if pair is None or bid_raw is None or ask_raw is None:
            return
        try:
            bid = float(bid_raw)
            ask = float(ask_raw)
        except (TypeError, ValueError):
            return

        raw_ts = tick.get("time")
        ts: datetime
        if isinstance(raw_ts, datetime):
            ts = raw_ts
        elif raw_ts is None or raw_ts == "":
            ts = datetime.now(tz=timezone.utc)
        else:
            try:
                ts = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
            except ValueError:
                try:
                    epoch = float(raw_ts)
                    ts = datetime.fromtimestamp(
                        epoch / 1000.0 if epoch > 1e12 else epoch, tz=timezone.utc
                    )
                except (TypeError, ValueError, OSError, OverflowError):
                    ts = datetime.now(tz=timezone.utc)

        try:
            await candle_pipeline.process_tick(pair, bid, ask, ts)
        except Exception as exc:
            logger.error("Candle pipeline tick error", pair=pair, error=str(exc))
        try:
            await ws_manager.push_tick(pair, bid, ask, round(ask - bid, 6))
        except Exception as exc:
            logger.error("WS tick push error", pair=pair, error=str(exc))

    broker_manager.set_price_callback(_on_price_tick)

    # ------------------------------------------------------------------
    # 10. Load broker connections from DB + start price streaming
    # ------------------------------------------------------------------
    try:
        async with async_session_maker() as db:
            await broker_manager.load_from_db(db)
    except Exception as exc:
        logger.warning("Failed to load broker connections from DB", error=str(exc))

    # Crypto-only: drive the app from a live Binance PAPER-trading loop instead
    # of an OANDA/forex price stream. The loop owns a PaperBroker (registered
    # into broker_manager so REST /positions + kill-switch see it) and executes
    # the validated strategy in PAPER mode (nothing reaches a real broker).
    import asyncio as _asyncio

    from app.services.live.crypto_loop import LiveCryptoLoop

    live_loop = LiveCryptoLoop()
    broker_manager._adapters["paper"] = live_loop.paper
    app.state.live_loop = live_loop
    app.state.live_task = _asyncio.create_task(live_loop.run())
    logger.info("Live crypto paper-trading loop started", symbols=list(live_loop.symbols))

    # ------------------------------------------------------------------
    # 11. APScheduler for periodic jobs
    # ------------------------------------------------------------------
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler()

    # Calendar refresh every hour at xx:05
    async def _refresh_calendar() -> None:
        try:
            from app.services.calendar.finnhub import calendar_service as _cs

            await _cs.refresh()
        except Exception as exc:
            logger.warning("Calendar refresh failed", error=str(exc))

    scheduler.add_job(_refresh_calendar, "cron", minute=5)

    # Expire old alerts every 5 minutes
    async def _expire_alerts() -> None:
        try:
            from app.services.decision.alerts import expire_old_alerts

            async with async_session_maker() as db:
                count = await expire_old_alerts(db, "system")
                if count:
                    logger.info("Expired alerts", count=count)
        except Exception as exc:
            logger.warning("Alert expiry job failed", error=str(exc))

    scheduler.add_job(_expire_alerts, "interval", minutes=5)

    # Observe-only prop-firm compliance sync (monitoring only — never auto-closes).
    # Pulls balance/equity from connected accounts (e.g. Crypto Fund Trader) into
    # compliance snapshots wherever the broker is reachable.
    async def _sync_propfirm_observe() -> None:
        try:
            from app.services.broker.observe_sync import sync_all_observe_only

            async with async_session_maker() as db:
                count = await sync_all_observe_only(db, "system")
                if count:
                    logger.info("Observe-only prop-firm sync", profiles=count)
        except Exception as exc:
            logger.warning("Observe-only prop-firm sync failed", error=str(exc))

    scheduler.add_job(_sync_propfirm_observe, "interval", minutes=2)

    scheduler.start()
    logger.info("Trading AI Co-Pilot startup complete")

    yield

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------
    logger.info("Trading AI Co-Pilot shutting down")
    try:
        await app.state.live_loop.stop()
        app.state.live_task.cancel()
    except Exception as exc:
        logger.warning("Live loop stop error", error=str(exc))
    try:
        scheduler.shutdown(wait=False)
    except Exception as exc:
        logger.warning("Scheduler shutdown error", error=str(exc))
    try:
        await broker_manager.stop_price_streaming()
    except Exception as exc:
        logger.warning("Broker streaming stop error", error=str(exc))
    try:
        await redis_client.aclose()
    except Exception as exc:
        logger.warning("Redis close error", error=str(exc))
    logger.info("Trading AI Co-Pilot stopped")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    app = FastAPI(
        title="Trading AI Co-Pilot",
        description=(
            "Self-hosted AI-powered trading assistant with ICT pattern detection, "
            "risk compliance, and broker integration."
        ),
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    # ---- Middleware --------------------------------------------------------

    # CORS — localhost origins only for self-hosted deployment
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost",
            "http://localhost:3000",
            "http://localhost:5173",
            "http://localhost:8080",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:8080",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Rate limiting
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)

    # ---- X-Request-ID middleware -------------------------------------------

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next: Any) -> Response:
        request_id = request.headers.get("X-Request-ID") or get_request_id()
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    # ---- Exception handlers ------------------------------------------------

    @app.exception_handler(TradingAIError)
    async def trading_ai_error_handler(
        request: Request, exc: TradingAIError
    ) -> JSONResponse:
        logger.warning(
            "TradingAIError",
            error_type=type(exc).__name__,
            message=exc.message,
            path=str(request.url),
        )
        return JSONResponse(
            status_code=400,
            content=problem_response(
                title=type(exc).__name__,
                status=400,
                detail=exc.detail,
                instance=str(request.url.path),
            ),
            media_type="application/problem+json",
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=problem_response(
                title="HTTP Error",
                status=exc.status_code,
                detail=str(exc.detail),
                instance=str(request.url.path),
            ),
            media_type="application/problem+json",
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.exception(
            "Unhandled exception",
            error_type=type(exc).__name__,
            path=str(request.url),
        )
        return JSONResponse(
            status_code=500,
            content=problem_response(
                title="Internal Server Error",
                status=500,
                detail="An unexpected error occurred. Please try again later.",
                instance=str(request.url.path),
            ),
            media_type="application/problem+json",
        )

    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # ---- Routers -----------------------------------------------------------

    api_prefix = "/api"

    app.include_router(brokers_router, prefix=api_prefix)
    app.include_router(candles_router, prefix=api_prefix)
    app.include_router(engine_router, prefix=api_prefix)
    app.include_router(positions_router, prefix=api_prefix)
    app.include_router(trades_router, prefix=api_prefix)
    app.include_router(journal_router, prefix=api_prefix)
    app.include_router(screenshots_router, prefix=api_prefix)
    app.include_router(analysis_router, prefix=api_prefix)
    app.include_router(alerts_router, prefix=api_prefix)
    app.include_router(ict_router, prefix=api_prefix)
    app.include_router(settings_router, prefix=api_prefix)
    app.include_router(audit_log_router, prefix=api_prefix)
    app.include_router(system_router, prefix=api_prefix)
    app.include_router(prop_firm_router, prefix=api_prefix)
    app.include_router(calendar_router, prefix=api_prefix)
    app.include_router(ws_router)  # WebSocket has no /api prefix

    return app


app = create_app()
