"""Canonical Pydantic v2 domain models for AI Trader."""

from src.domain.agent_signal import AgentSignalOutput, SignalDirection
from src.domain.aggregation_result import AggregationResult
from src.domain.backtest_result import (
    BacktestMetrics,
    BacktestResult,
    BacktestTrade,
    EquityPoint,
)
from src.domain.capital_event import CapitalEvent, CapitalEventType
from src.domain.capital_state import CapitalState
from src.domain.decision import Decision, DecisionRecord
from src.domain.evaluation import TradeEvaluation
from src.domain.execution import OrderFill, OrderSubmission, Position
from src.domain.features import FeatureSet
from src.domain.governance import ModelVersion
from src.domain.governance_event import PromotionEvent, RollbackEvent
from src.domain.market_data import (
    CorporateAction,
    MarketDepthLevel,
    MarketDepthQuote,
    MarketTick,
    OHLCVCandle,
)
from src.domain.pattern import ObservedPattern
from src.domain.regime import (
    DirectionalBias,
    LiquidityCondition,
    RegimeClassification,
    RegimeTransitionEvent,
    RiskSentiment,
    TrendState,
    VolatilityLevel,
)
from src.domain.risk import (
    CandidateTrade,
    MarketState,
    RiskCheckResult,
    StreakState,
)
from src.domain.scaling_report import CapitalScalingReport, CriterionResult
from src.domain.validation import (
    ChronologicalSplit,
    MonteCarloSimulationResult,
    StressScenarioResult,
    StressScenarioType,
    StressTestReport,
    WalkForwardFold,
    WalkForwardReport,
)
from src.domain.validation_record import (
    ValidationRunRecord,
    ValidationStageResult,
    ValidationStageType,
)

__all__ = [
    "AgentSignalOutput",
    "AggregationResult",
    "BacktestMetrics",
    "BacktestResult",
    "BacktestTrade",
    "CandidateTrade",
    "CapitalEvent",
    "CapitalEventType",
    "CapitalScalingReport",
    "CapitalState",
    "ChronologicalSplit",
    "CorporateAction",
    "CriterionResult",
    "Decision",
    "DecisionRecord",
    "DirectionalBias",
    "EquityPoint",
    "FeatureSet",
    "LiquidityCondition",
    "MarketDepthLevel",
    "MarketDepthQuote",
    "MarketState",
    "MarketTick",
    "ModelVersion",
    "MonteCarloSimulationResult",
    "OHLCVCandle",
    "ObservedPattern",
    "OrderFill",
    "OrderSubmission",
    "Position",
    "PromotionEvent",
    "RegimeClassification",
    "RegimeTransitionEvent",
    "RiskCheckResult",
    "RiskSentiment",
    "RollbackEvent",
    "SignalDirection",
    "StreakState",
    "StressScenarioResult",
    "StressScenarioType",
    "StressTestReport",
    "TradeEvaluation",
    "TrendState",
    "ValidationRunRecord",
    "ValidationStageResult",
    "ValidationStageType",
    "VolatilityLevel",
    "WalkForwardFold",
    "WalkForwardReport",
]
