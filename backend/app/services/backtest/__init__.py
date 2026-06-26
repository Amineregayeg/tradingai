"""Backtest harness for the client's crypto ICT/SMC strategy.

v1 implements the documented *core* edge end-to-end on real Binance history:
HTF bias -> imbalance (FVG) entry at a discount/premium POI -> structural
cushion SL -> asymmetric exit (70% at 2R, 30% to EOD) at fixed risk.

Higher-fidelity layers (BPR/super-BPR, Magic Alignment multi-asset confirmation,
key-level amplifiers, Normal/Super/Manipulated box grading, dominance regime)
are added on top in v2 to calibrate toward the +37.3% / ~59-trade / ~44% WR
target. See STRATEGY_BUILD_PLAN.md.
"""
