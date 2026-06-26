from app.api.routers.alerts import router as alerts_router
from app.api.routers.calendar import router as calendar_router
from app.api.routers.analysis import router as analysis_router
from app.api.routers.audit_log import router as audit_log_router
from app.api.routers.brokers import router as brokers_router
from app.api.routers.candles import router as candles_router
from app.api.routers.engine import router as engine_router
from app.api.routers.ict import router as ict_router
from app.api.routers.journal import router as journal_router
from app.api.routers.positions import router as positions_router
from app.api.routers.prop_firm import router as prop_firm_router
from app.api.routers.screenshots import router as screenshots_router
from app.api.routers.settings_router import router as settings_router
from app.api.routers.system import router as system_router
from app.api.routers.trades import router as trades_router
from app.api.routers.ws import router as ws_router

__all__ = [
    "alerts_router",
    "calendar_router",
    "analysis_router",
    "audit_log_router",
    "brokers_router",
    "candles_router",
    "engine_router",
    "ict_router",
    "journal_router",
    "positions_router",
    "prop_firm_router",
    "screenshots_router",
    "settings_router",
    "system_router",
    "trades_router",
    "ws_router",
]
