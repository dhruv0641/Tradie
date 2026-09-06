"""Unit tests for TrendAgent (MLD §6.1, ADD §6.2)."""

from datetime import UTC, datetime
from uuid import uuid4
import pytest

from src.agents.trend import TrendAgent
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


def _make_context(
    features: dict[str, float],
    trend_state: TrendState = TrendState.TRENDING_UP,
) -> tuple[FeatureSet, RegimeClassification]:
    """Helper to create FeatureSet and RegimeClassification."""
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    fs = FeatureSet(
        feature_set_id=uuid4(),
        instrument="NSE:TCS",
        timestamp=now,
        timeframe="15m",
        features=features,
    )
    regime = RegimeClassification(
        instrument="NSE:TCS",
        timeframe="15m",
        timestamp=now,
        trend_state=trend_state,
        volatility_level=VolatilityLevel.NORMAL,
        directional_bias=(
            DirectionalBias.NEUTRAL
            if trend_state == TrendState.RANGING
            else DirectionalBias.BULLISH
        ),
        liquidity_condition=LiquidityCondition.NORMAL,
        risk_sentiment=RiskSentiment.RISK_ON,
        regime_label=f"{trend_state.value}_NORMAL_VOL",
    )
    return fs, regime


def test_trend_agent_bullish_alignment() -> None:
    """Verify MA and DI alignment with ADX >= 25 produces LONG signal."""
    agent = TrendAgent()
    feats = {
        "adx_14": 30.0,
        "plus_di_14": 25.0,
        "minus_di_14": 15.0,
        "sma_20": 3550.0,
        "sma_50": 3500.0,
    }
    fs, regime = _make_context(feats, TrendState.TRENDING_UP)

    sig = agent.evaluate("NSE:TCS", "15m", fs, regime)

    assert sig.agent_id == "trend_agent"
    assert sig.direction == SignalDirection.LONG
    assert 0.1 <= sig.confidence <= 1.0
    assert sig.inputs_used["adx_14"] == 30.0


def test_trend_agent_bearish_alignment() -> None:
    """Verify negative MA and DI alignment with ADX >= 25 produces SHORT signal."""
    agent = TrendAgent()
    feats = {
        "adx_14": 35.0,
        "plus_di_14": 12.0,
        "minus_di_14": 28.0,
        "sma_20": 3400.0,
        "sma_50": 3500.0,
    }
    fs, regime = _make_context(feats, TrendState.TRENDING_DOWN)

    sig = agent.evaluate("NSE:TCS", "15m", fs, regime)

    assert sig.direction == SignalDirection.SHORT
    assert 0.1 <= sig.confidence <= 1.0


def test_trend_agent_ranging_invariant() -> None:
    """Verify RANGING regime forces NO_VIEW with 0.0 confidence (MLD §6.1)."""
    agent = TrendAgent()
    feats = {
        "adx_14": 30.0,
        "plus_di_14": 25.0,
        "minus_di_14": 15.0,
        "sma_20": 3550.0,
        "sma_50": 3500.0,
    }
    # Even though indicators look bullish, RANGING regime must suppress signal!
    fs, regime = _make_context(feats, TrendState.RANGING)

    sig = agent.evaluate("NSE:TCS", "15m", fs, regime)

    assert sig.direction == SignalDirection.NO_VIEW
    assert sig.confidence == 0.0


def test_trend_agent_unknown_regime_suppression() -> None:
    """Verify UNKNOWN regime forces NO_VIEW with 0.0 confidence."""
    agent = TrendAgent()
    feats = {
        "adx_14": 30.0,
        "plus_di_14": 25.0,
        "minus_di_14": 15.0,
        "sma_20": 3550.0,
        "sma_50": 3500.0,
    }
    fs, regime = _make_context(feats, TrendState.UNKNOWN)

    sig = agent.evaluate("NSE:TCS", "15m", fs, regime)

    assert sig.direction == SignalDirection.NO_VIEW
    assert sig.confidence == 0.0


def test_trend_agent_weak_adx_suppression() -> None:
    """Verify ADX < min_adx_strength produces NO_VIEW."""
    agent = TrendAgent(min_adx_strength=25.0)
    feats = {
        "adx_14": 18.0,  # Below 25.0 threshold
        "plus_di_14": 25.0,
        "minus_di_14": 15.0,
        "sma_20": 3550.0,
        "sma_50": 3500.0,
    }
    fs, regime = _make_context(feats, TrendState.TRENDING_UP)

    sig = agent.evaluate("NSE:TCS", "15m", fs, regime)

    assert sig.direction == SignalDirection.NO_VIEW
    assert sig.confidence == 0.0


def test_trend_agent_conflicting_signals() -> None:
    """Verify conflicting MAs vs DIs produces NO_VIEW."""
    agent = TrendAgent()
    feats = {
        "adx_14": 30.0,
        "plus_di_14": 28.0,
        "minus_di_14": 14.0,  # DIs indicate bullish
        "sma_20": 3400.0,
        "sma_50": 3500.0,  # MAs indicate bearish
    }
    fs, regime = _make_context(feats, TrendState.TRENDING_UP)

    sig = agent.evaluate("NSE:TCS", "15m", fs, regime)

    assert sig.direction == SignalDirection.NO_VIEW
    assert sig.confidence == 0.0


def test_trend_agent_missing_features_fallback() -> None:
    """Verify missing required features safely degrades to NO_VIEW."""
    agent = TrendAgent()
    feats = {"adx_14": 30.0}  # Missing plus_di, minus_di, sma
    fs, regime = _make_context(feats, TrendState.TRENDING_UP)

    sig = agent.evaluate("NSE:TCS", "15m", fs, regime)

    assert sig.direction == SignalDirection.NO_VIEW
    assert sig.confidence == 0.0


def test_trend_agent_invalid_init_parameters() -> None:
    """Verify invalid constructor bounds raise ValueError."""
    with pytest.raises(ValueError, match="min_adx_strength must be positive"):
        TrendAgent(min_adx_strength=0.0)
    with pytest.raises(ValueError, match="adx_saturation must be greater"):
        TrendAgent(min_adx_strength=30.0, adx_saturation=25.0)


def test_trend_agent_rolling_percentile_and_clear() -> None:
    """Verify rolling history populates and clear_history resets."""
    agent = TrendAgent(rolling_window=20)
    for adx_val in range(26, 40):
        feats = {
            "adx_14": float(adx_val),
            "plus_di_14": 25.0,
            "minus_di_14": 15.0,
            "sma_20": 3550.0,
            "sma_50": 3500.0,
        }
        fs, regime = _make_context(feats, TrendState.TRENDING_UP)
        sig = agent.evaluate("NSE:TCS", "15m", fs, regime)
        assert sig.direction == SignalDirection.LONG

    agent.clear_history()
    assert len(agent._adx_history) == 0
