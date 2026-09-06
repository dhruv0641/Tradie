"""Unit tests for MeanReversionAgent (MLD §6.3, ADD §6.2)."""

from datetime import UTC, datetime
from uuid import uuid4
import pytest

from src.agents.mean_reversion import MeanReversionAgent
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
    trend_state: TrendState = TrendState.RANGING,
) -> tuple[FeatureSet, RegimeClassification]:
    """Helper to create FeatureSet and RegimeClassification."""
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    fs = FeatureSet(
        feature_set_id=uuid4(),
        instrument="NSE:RELIANCE",
        timestamp=now,
        timeframe="15m",
        features=features,
    )
    regime = RegimeClassification(
        instrument="NSE:RELIANCE",
        timeframe="15m",
        timestamp=now,
        trend_state=trend_state,
        volatility_level=VolatilityLevel.NORMAL,
        directional_bias=DirectionalBias.NEUTRAL,
        liquidity_condition=LiquidityCondition.NORMAL,
        risk_sentiment=RiskSentiment.RISK_ON,
        regime_label=f"{trend_state.value}_NORMAL_VOL",
    )
    return fs, regime


def test_mean_reversion_oversold_long() -> None:
    """Verify negative z-score (price below mean) produces contrarian LONG signal."""
    agent = MeanReversionAgent(zscore_neutral_band=1.0)
    feats = {"zscore_20": -2.2}
    fs, regime = _make_context(feats, TrendState.RANGING)

    sig = agent.evaluate("NSE:RELIANCE", "15m", fs, regime)

    assert sig.agent_id == "mean_reversion_agent"
    assert sig.direction == SignalDirection.LONG
    assert 0.1 <= sig.confidence <= 1.0
    assert sig.raw_score == -2.2


def test_mean_reversion_overbought_short() -> None:
    """Verify positive z-score (price above mean) produces contrarian SHORT signal."""
    agent = MeanReversionAgent(zscore_neutral_band=1.0)
    feats = {"zscore_20": 2.5}
    fs, regime = _make_context(feats, TrendState.RANGING)

    sig = agent.evaluate("NSE:RELIANCE", "15m", fs, regime)

    assert sig.direction == SignalDirection.SHORT
    assert 0.1 <= sig.confidence <= 1.0


def test_mean_reversion_neutral_band() -> None:
    """Verify z-score within neutral band (|z| <= 1.0) produces NO_VIEW."""
    agent = MeanReversionAgent(zscore_neutral_band=1.0)
    feats = {"zscore_20": 0.75}
    fs, regime = _make_context(feats, TrendState.RANGING)

    sig = agent.evaluate("NSE:RELIANCE", "15m", fs, regime)

    assert sig.direction == SignalDirection.NO_VIEW
    assert sig.confidence == 0.0


def test_mean_reversion_trending_regime_discount_invariant() -> None:
    """Verify MLD §6.3 invariant: confidence discounted by 50% in trending regimes."""
    agent = MeanReversionAgent(zscore_neutral_band=1.0, trending_discount_factor=0.50)
    feats = {"zscore_20": -2.0}

    # In RANGING regime: full confidence
    fs_ranging, regime_ranging = _make_context(feats, TrendState.RANGING)
    sig_ranging = agent.evaluate("NSE:RELIANCE", "15m", fs_ranging, regime_ranging)

    # In TRENDING_UP regime: discounted confidence
    fs_trending, regime_trending = _make_context(feats, TrendState.TRENDING_UP)
    sig_trending = agent.evaluate("NSE:RELIANCE", "15m", fs_trending, regime_trending)

    assert sig_ranging.direction == SignalDirection.LONG
    assert sig_trending.direction == SignalDirection.LONG
    # Discount factor check
    assert sig_trending.confidence == pytest.approx(sig_ranging.confidence * 0.50, rel=1e-5)


def test_mean_reversion_missing_features() -> None:
    """Verify missing z-score safely degrades to NO_VIEW."""
    agent = MeanReversionAgent()
    feats: dict[str, float] = {}  # Empty
    fs, regime = _make_context(feats, TrendState.RANGING)

    sig = agent.evaluate("NSE:RELIANCE", "15m", fs, regime)

    assert sig.direction == SignalDirection.NO_VIEW
    assert sig.confidence == 0.0


def test_mean_reversion_invalid_params() -> None:
    """Verify invalid constructor parameters raise ValueError."""
    with pytest.raises(ValueError, match="zscore_neutral_band must be non-negative"):
        MeanReversionAgent(zscore_neutral_band=-0.5)
    with pytest.raises(ValueError, match="zscore_cap must be strictly greater"):
        MeanReversionAgent(zscore_neutral_band=2.0, zscore_cap=1.5)
    with pytest.raises(ValueError, match="trending_discount_factor must be in"):
        MeanReversionAgent(trending_discount_factor=0.0)
