import enum


class DirectionType(str, enum.Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class OutcomeType(str, enum.Enum):
    WIN = "WIN"
    LOSS = "LOSS"
    BE = "BE"
    OPEN = "OPEN"


class TradeStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class AlertType(str, enum.Enum):
    ENTRY_SIGNAL = "ENTRY_SIGNAL"
    EXIT_MGMT = "EXIT_MGMT"
    RISK_WARNING = "RISK_WARNING"
    PATTERN = "PATTERN"
    PSYCHOLOGY = "PSYCHOLOGY"


class AlertPriority(str, enum.Enum):
    INFO = "INFO"
    SUGGESTION = "SUGGESTION"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EDITED = "EDITED"
    EXECUTING = "EXECUTING"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class ICTType(str, enum.Enum):
    OB = "OB"
    FVG = "FVG"
    BOS = "BOS"
    CHOCH = "CHOCH"
    LIQ = "LIQ"
    SFP = "SFP"
    BREAKER = "BREAKER"
    SD_ZONE = "SD_ZONE"


class ICTDir(str, enum.Enum):
    BULL = "BULL"
    BEAR = "BEAR"


class ICTStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    MITIGATED = "MITIGATED"
    EXPIRED = "EXPIRED"


class ScreenshotTrigger(str, enum.Enum):
    TRADE_OPEN = "TRADE_OPEN"
    INTERVAL = "INTERVAL"
    KEY_LEVEL = "KEY_LEVEL"
    NEWS = "NEWS"
    STRUCTURE = "STRUCTURE"
    MANUAL = "MANUAL"


class ActorType(str, enum.Enum):
    SYSTEM = "SYSTEM"
    AI = "AI"
    TRADER = "TRADER"


class ComplianceState(str, enum.Enum):
    ACTIVE = "ACTIVE"
    AT_RISK = "AT_RISK"
    CRITICAL = "CRITICAL"
    HALTED = "HALTED"
    COOLDOWN = "COOLDOWN"
    BREACHED = "BREACHED"


class OrderType(str, enum.Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class OrderStatus(str, enum.Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
