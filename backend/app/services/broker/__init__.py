"""Broker service layer — adapters + manager."""
from app.services.broker.base import BrokerAdapter
from app.services.broker.manager import BrokerManager, broker_manager
from app.services.broker.oanda import OANDAAdapter

__all__ = [
    "BrokerAdapter",
    "OANDAAdapter",
    "BrokerManager",
    "broker_manager",
]
