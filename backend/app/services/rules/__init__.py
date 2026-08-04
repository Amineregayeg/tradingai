"""Contract rule implementations (M2).

Importing this package registers every implementation, which is what makes
`scripts/check_rule_coverage.py` able to answer "which of the 117 rules does this engine
actually implement?" without guessing from filenames.

Every module here must be imported below. A rule implementation that nothing imports is
invisible to the coverage report — it would count as unimplemented while sitting in the
tree, which is the one failure mode a coverage report must not have. `test_rules_base.py`
asserts this list matches the modules on disk.
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
from app.services.rules.prim_005_breaks import BreakEvent, BreakEvents  # noqa: F401

__all__ = [
    "Bar",
    "BreakEvent",
    "BreakEvents",
    "DuplicateRuleImplementation",
    "NewYorkTimestamps",
    "Swing",
    "SwingPoints",
    "RuleImplementation",
    "implementations",
    "implemented_ids",
    "open_rule_requires_declared_parameter",
]
