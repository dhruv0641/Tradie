"""Multi-agent signal aggregation and dynamic timeframe selection module."""

from src.aggregation.aggregator import SignalAggregator
from src.aggregation.timeframe_selector import TimeframeSelector

__all__ = ["SignalAggregator", "TimeframeSelector"]
