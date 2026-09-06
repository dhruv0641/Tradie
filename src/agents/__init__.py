"""Multi-agent signal generation subsystem for AI Trader.

Implements the TradingAgent contract and rule-based intelligence roster per
FRD Module 4, ADD §4, §6, and MLD §6.
"""

from src.agents.base import BaseAgent, TradingAgent
from src.agents.mean_reversion import MeanReversionAgent
from src.agents.momentum import MomentumAgent
from src.agents.price_action import PriceActionAgent
from src.agents.trend import TrendAgent

__all__ = [
    "BaseAgent",
    "MeanReversionAgent",
    "MomentumAgent",
    "PriceActionAgent",
    "TradingAgent",
    "TrendAgent",
]
