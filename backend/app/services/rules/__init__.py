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
    ConditionReading,
    ConditionState,
    DuplicateRuleImplementation,
    RuleImplementation,
    implementations,
    implemented_ids,
    open_rule_requires_declared_parameter,
    quorum_blocked,
)
from app.services.rules.consolidation import (  # noqa: F401
    DECLARED_THRESHOLD,
    WINDOW_BARS,
    ConsolidationThreshold,
    ConsolidationWindow,
    detect_window,
    detection_rate_pct,
)
from app.services.rules.entry_001_imbalance_poi import (  # noqa: F401
    Block,
    EntryPOI,
    ImbalanceIsTheOnlyEntryPOI,
)
from app.services.rules.exit_001_v1_model import (  # noqa: F401
    DECLARED_SESSION_CLOSE,
    EXIT_001_REASONS,
    FINAL_TARGET,
    PARTIAL_2R,
    PARTIAL_AT_R,
    PARTIAL_FRACTION,
    RUNNER_FRACTION,
    SCHEMA_ONLY_REASONS,
    SESSION_CLOSE,
    STOP_HIT,
    TERMINAL_REASONS,
    DeclaredSessionClose,
    DegenerateRunner,
    ExitEvent,
    ExitSimulation,
    TradePlan,
    V1ExitModel,
    next_session_close_after,
    ticks_from_prices,
)
from app.services.rules.exit_002_ladder_off import (  # noqa: F401
    LADDER_SIGNATURE,
    MAX_TRANCHES,
    ConformanceFinding,
    LadderOffForV1,
    assert_v1_exit_shape,
    ladder_violations,
)
from app.services.rules.evaluator import (  # noqa: F401
    LayoutEvaluation,
    LayoutEvaluator,
    build_correlate_reads,
    evaluate_layout,
)
from app.services.rules.gate_002_disturbance import (  # noqa: F401
    AbsoluteCountNotRatio,
    AlignmentForms,
    CorrelateRead,
    CorrelationIsSelectionOnly,
    Disturbance,
    DisturbanceClassifier,
    HeavyDisturbanceSkip,
    MainAssetCountChoice,
    OffConditionDetector,
    PanelAgreement,
    PanelVerdict,
    StructuralNotStatistical,
)
from app.services.rules.gate_008_roster import (  # noqa: F401
    AlignmentTimeframe,
    LayoutReadability,
    LayoutRoster,
    Panel,
)
from app.services.rules.gate_017_analysis_only_tfs import (  # noqa: F401
    ANALYSIS_ONLY_TFS,
    TRADING_MODE,
    AnalysisOnlyTimeframes,
    DayTradingMode,
    is_analysis_only,
    normalise_tf,
)
from app.services.rules.gate_023_timezone import NewYorkTimestamps  # noqa: F401
from app.services.rules.gate_036_stand_aside import Decision, StandAside  # noqa: F401
from app.services.rules.gate_037_no_premium_discount import (  # noqa: F401
    NoPremiumDiscountOrOTEFilter,
)
from app.services.rules.gate_038_amplifiers import (  # noqa: F401
    AmplifierLevel,
    AmplifiersNeverCreateATrade,
    DECLARED_COLLISION_WINDOW,
)
from app.services.rules.gate_040_cool_off import (  # noqa: F401
    DECLARED_COOL_OFF,
    INPUT_UNION,
    CoolOffBeforeReversal,
    DeclaredDuration,
)
from app.services.rules.gate_041_reverse_switch import (  # noqa: F401
    CONDITIONS,
    MANDATORY_CONDITION,
    ReverseSwitchConfirmations,
)
from app.services.rules.grade_031_declared_quorums import (  # noqa: F401
    DECLARED_QUORUMS,
    DeclaredQuorum,
    QuorumNotDeclared,
    QuorumsAreDeclaredParameters,
    require_declared,
)
from app.services.rules.grade_001_structure_box import (  # noqa: F401
    BoxScopeDeclaration,
    StructureBox,
    StructureBoxes,
)
from app.services.rules.grade_002_box_grade import (  # noqa: F401
    BoxEvidence,
    BoxGradeLadder,
    GradedBox,
    ManipulatedBoxGrade,
    ManipulatedDefinitionChoice,
    PoiTimingGate,
    StandardBoxGrade,
    SuperBoxGrade,
    grade_box,
)
from app.services.rules.grade_008_fake_msb import FakeMSB, FakeMSBClassifier  # noqa: F401
from app.services.rules.prim_001_swings import Bar, Swing, SwingPoints  # noqa: F401
from app.services.rules.prim_002_imbalances import Imbalance, ImbalanceInventory  # noqa: F401
from app.services.rules.prim_003_liquidity import LiquidityPool, LiquidityPools  # noqa: F401
from app.services.rules.prim_004_sweeps import SweepEvent, SweepEvents  # noqa: F401
from app.services.rules.prim_005_breaks import BreakEvent, BreakEvents  # noqa: F401
from app.services.rules.prim_006_sr_flips import SRFlip, SRFlipZones  # noqa: F401

__all__ = [
    "AbsoluteCountNotRatio",
    "AlignmentForms",
    "AlignmentTimeframe",
    "Bar",
    "BoxEvidence",
    "BoxGradeLadder",
    "BoxScopeDeclaration",
    "BreakEvent",
    "BreakEvents",
    "CorrelateRead",
    "CorrelationIsSelectionOnly",
    "Decision",
    "Disturbance",
    "DisturbanceClassifier",
    "DuplicateRuleImplementation",
    "ExitEvent",
    "ExitSimulation",
    "FakeMSB",
    "FakeMSBClassifier",
    "GradedBox",
    "HeavyDisturbanceSkip",
    "Imbalance",
    "ImbalanceInventory",
    "LayoutEvaluation",
    "LayoutEvaluator",
    "LayoutReadability",
    "LayoutRoster",
    "LiquidityPool",
    "LiquidityPools",
    "MainAssetCountChoice",
    "ManipulatedBoxGrade",
    "ManipulatedDefinitionChoice",
    "NewYorkTimestamps",
    "OffConditionDetector",
    "Panel",
    "PanelAgreement",
    "PanelVerdict",
    "PoiTimingGate",
    "RuleImplementation",
    "SRFlip",
    "SRFlipZones",
    "StandAside",
    "StandardBoxGrade",
    "StructuralNotStatistical",
    "StructureBox",
    "StructureBoxes",
    "SuperBoxGrade",
    "Swing",
    "SwingPoints",
    "SweepEvent",
    "SweepEvents",
    "TradePlan",
    "V1ExitModel",
    "LadderOffForV1",
    "assert_v1_exit_shape",
    "ladder_violations",
    "next_session_close_after",
    "build_correlate_reads",
    "evaluate_layout",
    "grade_box",
    "implementations",
    "implemented_ids",
    "open_rule_requires_declared_parameter",
]
