"""Unit tests for MomentumAgent (MLD §6.2, ADD §6.2)."""

from datetime import UTC, datetime
from uuid import uuid4
import pytest

from src.agents.momentum import MomentumAgent
from src.domain.agent_signal import SignalDirection
from src.domain.features import FeatureSet
from src.domain.regime import (
    DirectionalBias,
    LiquidityCondition,
    RegimeClassification,
    RiskSentiment,
    TrendState,
    VolatilityLevel,
)


def _make_context(features: dict[str, float]) -> tuple[FeatureSet, RegimeClassification]:
    """Helper to create FeatureSet and RegimeClassification."""
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    fs = FeatureSet(
        feature_set_id=uuid4(),
        instrument="NSE:INFY",
        timestamp=now,
        timeframe="5m",
        features=features,
    )
    regime = RegimeClassification(
        instrument="NSE:INFY",
        timeframe="5m",
        timestamp=now,
        trend_state=TrendState.TRENDING_UP,
        volatility_level=VolatilityLevel.NORMAL,
        directional_bias=DirectionalBias.BULLISH,
        liquidity_condition=LiquidityCondition.NORMAL,
        risk_sentiment=RiskSentiment.RISK_ON,
        regime_label="TRENDING_UP_NORMAL_VOL",
    )
    return fs, regime


def test_momentum_agent_bullish() -> None:
    """Verify positive ROC and RSI > 50 produces LONG signal."""
    agent = MomentumAgent()
    feats = {"roc_10": 1.5, "rsi_14": 65.0}
    fs, regime = _make_context(feats)

    sig = agent.evaluate("NSE:INFY", "5m", fs, regime)

    assert sig.agent_id == "momentum_agent"
    assert sig.direction == SignalDirection.LONG
    assert 0.1 <= sig.confidence <= 1.0
    assert sig.inputs_used["roc_10"] == 1.5


def test_momentum_agent_bearish() -> None:
    """Verify negative ROC and RSI < 50 produces SHORT signal."""
    agent = MomentumAgent()
    feats = {"roc_10": -2.0, "rsi_14": 35.0}
    fs, regime = _make_context(feats)

    sig = agent.evaluate("NSE:INFY", "5m", fs, regime)

    assert sig.direction == SignalDirection.SHORT
    assert 0.1 <= sig.confidence <= 1.0


def test_momentum_agent_neutral_band() -> None:
    """Verify within neutral band (|roc| <= 0.5 and |rsi - 50| <= 3) produces NO_VIEW."""
    agent = MomentumAgent(roc_neutral_band=0.5, rsi_neutral_band=3.0)
    feats = {"roc_10": 0.2, "rsi_14": 51.0}
    fs, regime = _make_context(feats)

    sig = agent.evaluate("NSE:INFY", "5m", fs, regime)

    assert sig.direction == SignalDirection.NO_VIEW
    assert sig.confidence == 0.0


def test_momentum_agent_conflicting_signals() -> None:
    """Verify conflicting signals (positive ROC but sub-50 RSI) produces NO_VIEW."""
    agent = MomentumAgent()
    feats = {"roc_10": 1.2, "rsi_14": 45.0}  # Divergent
    fs, regime = _make_context(feats)

    sig = agent.evaluate("NSE:INFY", "5m", fs, regime)

    assert sig.direction == SignalDirection.NO_VIEW
    assert sig.confidence == 0.0


def test_momentum_agent_missing_features() -> None:
    """Verify missing features degrades to NO_VIEW."""
    agent = MomentumAgent()
    feats = {"roc_10": 1.5}  # Missing rsi_14
    fs, regime = _make_context(feats)

    sig = agent.evaluate("NSE:INFY", "5m", fs, regime)

    assert sig.direction == SignalDirection.NO_VIEW
    assert sig.confidence == 0.0


def test_momentum_agent_invalid_params() -> None:
    """Verify invalid constructor parameters raise ValueError."""
    with pytest.raises(ValueError, match="roc_neutral_band must be non-negative"):
        MomentumAgent(roc_neutral_band=-0.1)
    with pytest.raises(ValueError, match="rsi_neutral_band must be non-negative"):
        MomentumAgent(rsi_neutral_band=-1.0)
    with pytest.raises(ValueError, match="rsi_max_deviation must be strictly greater"):
        MomentumAgent(rsi_neutral_band=5.0, rsi_max_deviation=4.0)
