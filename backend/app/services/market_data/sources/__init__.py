"""Pluggable external market-data sources (prices + dominance).

Detection and backtest code depends only on the ``MarketDataSource`` interface,
so a paid/vendor feed can be swapped in later without touching strategy logic.
"""
