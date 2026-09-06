"""Baseline quantitative trading strategies and interfaces."""

from src.strategies.base import BaseStrategy
from src.strategies.trend_baseline import (
    DonchianBreakoutStrategy,
    DualEMACrossoverStrategy,
)

__all__ = [
    "BaseStrategy",
    "DonchianBreakoutStrategy",
    "DualEMACrossoverStrategy",
]
