"""Canonical Pydantic v2 domain models for AI Trader."""

from src.domain.backtest_result import (
    BacktestMetrics,
    BacktestResult,
    BacktestTrade,
    EquityPoint,
)
from src.domain.decision import DecisionRecord
from src.domain.evaluation import TradeEvaluation
from src.domain.execution import OrderSubmission, Position
from src.domain.features import FeatureSet
from src.domain.governance import ModelVersion
from src.domain.market_data import (
    CorporateAction,
    MarketDepthLevel,
    MarketDepthQuote,
    MarketTick,
    OHLCVCandle,
)
from src.domain.validation import (
    ChronologicalSplit,
    WalkForwardFold,
    WalkForwardReport,
)

__all__ = [
    "BacktestMetrics",
    "BacktestResult",
    "BacktestTrade",
    "ChronologicalSplit",
    "CorporateAction",
    "DecisionRecord",
    "EquityPoint",
    "FeatureSet",
    "MarketDepthLevel",
    "MarketDepthQuote",
    "MarketTick",
    "ModelVersion",
    "OHLCVCandle",
    "OrderSubmission",
    "Position",
    "TradeEvaluation",
    "WalkForwardFold",
    "WalkForwardReport",
]
