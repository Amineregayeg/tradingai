"""Contract rule implementations (M2).

Importing this package registers every implementation, which is what makes
`scripts/check_rule_coverage.py` able to answer "which of the 117 rules does this engine
actually implement?" without guessing from filenames.

Every module here must be imported below. A rule implementation that nothing imports is
invisible to the coverage report — it would count as unimplemented while sitting in the
tree, which is the one failure mode a coverage report must not have. `test_rules_base.py`
asserts this list matches the modules on disk.

A SECOND FAILURE MODE, WHICH THE IMPORT LIST CANNOT CATCH
A rule can be registered and still only half built — PRIM-003 names seven classes of
liquidity pool and three of them need numbers the trader declined to fix. Those
implementations declare `COVERAGE_NOTE`, and the coverage report prints it, so "implemented"
never quietly means "finished".
"""
from __future__ import annotations

from app.services.rules.base import (  # noqa: F401
    DuplicateRuleImplementation,
    RuleImplementation,
    implementations,
    implemented_ids,
    open_rule_requires_declared_parameter,
)
from app.services.rules.gate_023_timezone import NewYorkTimestamps  # noqa: F401
from app.services.rules.prim_001_swings import Bar, Swing, SwingPoints  # noqa: F401
from app.services.rules.prim_002_imbalances import Imbalance, ImbalanceInventory  # noqa: F401
from app.services.rules.prim_003_liquidity import LiquidityPool, LiquidityPools  # noqa: F401
from app.services.rules.prim_004_sweeps import SweepEvent, SweepEvents  # noqa: F401
from app.services.rules.prim_005_breaks import BreakEvent, BreakEvents  # noqa: F401
from app.services.rules.prim_006_sr_flips import SRFlip, SRFlipZones  # noqa: F401

__all__ = [
    "Bar",
    "BreakEvent",
    "BreakEvents",
    "DuplicateRuleImplementation",
    "Imbalance",
    "ImbalanceInventory",
    "LiquidityPool",
    "LiquidityPools",
    "NewYorkTimestamps",
    "RuleImplementation",
    "SRFlip",
    "SRFlipZones",
    "Swing",
    "SwingPoints",
    "SweepEvent",
    "SweepEvents",
    "implementations",
    "implemented_ids",
    "open_rule_requires_declared_parameter",
]
