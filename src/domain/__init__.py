"""Canonical Pydantic v2 domain models for AI Trader."""

from src.domain.agent_signal import AgentSignalOutput, SignalDirection
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
from src.domain.regime import (
    DirectionalBias,
    LiquidityCondition,
    RegimeClassification,
    RegimeTransitionEvent,
    RiskSentiment,
    TrendState,
    VolatilityLevel,
)
from src.domain.validation import (
    ChronologicalSplit,
    MonteCarloSimulationResult,
    StressScenarioResult,
    StressScenarioType,
    StressTestReport,
    WalkForwardFold,
    WalkForwardReport,
)

__all__ = [
    "AgentSignalOutput",
    "BacktestMetrics",
    "BacktestResult",
    "BacktestTrade",
    "ChronologicalSplit",
    "CorporateAction",
    "DecisionRecord",
    "DirectionalBias",
    "EquityPoint",
    "FeatureSet",
    "LiquidityCondition",
    "MarketDepthLevel",
    "MarketDepthQuote",
    "MarketTick",
    "ModelVersion",
    "MonteCarloSimulationResult",
    "OHLCVCandle",
    "OrderSubmission",
    "Position",
    "RegimeClassification",
    "RegimeTransitionEvent",
    "RiskSentiment",
    "SignalDirection",
    "StressScenarioResult",
    "StressScenarioType",
    "StressTestReport",
    "TradeEvaluation",
    "TrendState",
    "VolatilityLevel",
    "WalkForwardFold",
    "WalkForwardReport",
]
