"""Canonical Pydantic v2 domain models for AI Trader."""

from src.domain.decision import DecisionRecord
from src.domain.evaluation import TradeEvaluation
from src.domain.execution import OrderSubmission, Position
from src.domain.features import FeatureSet
from src.domain.governance import ModelVersion
from src.domain.market_data import (
    CorporateAction,
    MarketDepthLevel,
    MarketDepthQuote,
    OHLCVCandle,
)

__all__ = [
    "CorporateAction",
    "DecisionRecord",
    "FeatureSet",
    "MarketDepthLevel",
    "MarketDepthQuote",
    "ModelVersion",
    "OHLCVCandle",
    "OrderSubmission",
    "Position",
    "TradeEvaluation",
]
