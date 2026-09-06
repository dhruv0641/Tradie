"""Unit tests for PriceActionAgent (MLD §6.4, ADD §6.2)."""

from datetime import UTC, datetime
from uuid import uuid4
import pytest

from src.agents.price_action import PriceActionAgent
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
        instrument="NSE:RELIANCE",
        timestamp=now,
        timeframe="15m",
        features=features,
    )
    regime = RegimeClassification(
        instrument="NSE:RELIANCE",
        timeframe="15m",
        timestamp=now,
        trend_state=TrendState.RANGING,
        volatility_level=VolatilityLevel.NORMAL,
        directional_bias=DirectionalBias.NEUTRAL,
        liquidity_condition=LiquidityCondition.NORMAL,
        risk_sentiment=RiskSentiment.RISK_ON,
        regime_label="RANGING_NORMAL_VOL",
    )
    return fs, regime


def test_price_action_agent_bullish_support_bounce() -> None:
    """Verify near support with lower shadow rejection triggers LONG."""
    agent = PriceActionAgent(proximity_threshold_pct=0.50, min_rejection_wick_ratio=0.35)
    feats = {
        "close": 100.2,
        "support_20": 100.0,
        "resistance_20": 110.0,
        "lower_shadow_ratio": 0.40,
        "upper_shadow_ratio": 0.05,
    }
    fs, regime = _make_context(feats)

    sig = agent.evaluate("NSE:RELIANCE", "15m", fs, regime)

    assert sig.agent_id == "price_action_agent"
    assert sig.direction == SignalDirection.LONG
    assert 0.2 <= sig.confidence <= 1.0
    assert sig.raw_score is not None
    assert sig.inputs_used["dist_support_pct"] == pytest.approx(sig.raw_score)


def test_price_action_agent_bullish_pattern_boost() -> None:
    """Verify hammer or bullish engulfing near support yields higher confidence."""
    agent = PriceActionAgent(proximity_threshold_pct=0.50, min_rejection_wick_ratio=0.35)
    base_feats = {
        "close": 100.2,
        "support_20": 100.0,
        "resistance_20": 110.0,
        "lower_shadow_ratio": 0.40,
    }
    hammer_feats = dict(base_feats, pattern_hammer=1.0)

    fs_base, regime_base = _make_context(base_feats)
    fs_hammer, regime_hammer = _make_context(hammer_feats)

    sig_base = agent.evaluate("NSE:RELIANCE", "15m", fs_base, regime_base)
    sig_hammer = agent.evaluate("NSE:RELIANCE", "15m", fs_hammer, regime_hammer)

    assert sig_base.direction == SignalDirection.LONG
    assert sig_hammer.direction == SignalDirection.LONG
    assert sig_hammer.confidence > sig_base.confidence
    assert sig_hammer.confidence == pytest.approx(sig_base.confidence + 0.20, abs=1e-4)


def test_price_action_agent_bullish_engulfing() -> None:
    """Verify bullish engulfing near support triggers LONG."""
    agent = PriceActionAgent()
    feats = {
        "close": 100.1,
        "support_20": 100.0,
        "resistance_20": 105.0,
        "pattern_bullish_engulfing": 1.0,
    }
    fs, regime = _make_context(feats)

    sig = agent.evaluate("NSE:RELIANCE", "15m", fs, regime)

    assert sig.direction == SignalDirection.LONG
    assert sig.confidence >= 0.2


def test_price_action_agent_bearish_resistance_rejection() -> None:
    """Verify near resistance with upper shadow rejection triggers SHORT."""
    agent = PriceActionAgent(proximity_threshold_pct=0.50, min_rejection_wick_ratio=0.35)
    feats = {
        "close": 99.8,
        "resistance_20": 100.0,
        "support_20": 90.0,
        "upper_shadow_ratio": 0.45,
        "lower_shadow_ratio": 0.05,
    }
    fs, regime = _make_context(feats)

    sig = agent.evaluate("NSE:RELIANCE", "15m", fs, regime)

    assert sig.direction == SignalDirection.SHORT
    assert 0.2 <= sig.confidence <= 1.0
    assert sig.raw_score is not None
    assert sig.inputs_used["dist_resistance_pct"] == pytest.approx(sig.raw_score)


def test_price_action_agent_bearish_pattern_boost() -> None:
    """Verify shooting star or bearish engulfing near resistance triggers SHORT."""
    agent = PriceActionAgent()
    feats = {
        "close": 99.9,
        "resistance_20": 100.0,
        "support_20": 90.0,
        "pattern_shooting_star": 1.0,
    }
    fs, regime = _make_context(feats)

    sig = agent.evaluate("NSE:RELIANCE", "15m", fs, regime)

    assert sig.direction == SignalDirection.SHORT
    assert sig.confidence >= 0.2

    # Bearish engulfing check
    feats_engulf = {
        "close": 99.9,
        "resistance_20": 100.0,
        "support_20": 90.0,
        "pattern_bearish_engulfing": 1.0,
    }
    fs_engulf, regime_engulf = _make_context(feats_engulf)
    sig_engulf = agent.evaluate("NSE:RELIANCE", "15m", fs_engulf, regime_engulf)
    assert sig_engulf.direction == SignalDirection.SHORT


def test_price_action_agent_far_from_levels() -> None:
    """Verify being far from support and resistance yields NO_VIEW."""
    agent = PriceActionAgent(proximity_threshold_pct=0.50)
    feats = {
        "close": 105.0,
        "support_20": 100.0,  # ~4.76% away
        "resistance_20": 110.0,  # ~4.76% away
        "lower_shadow_ratio": 0.50,
    }
    fs, regime = _make_context(feats)

    sig = agent.evaluate("NSE:RELIANCE", "15m", fs, regime)

    assert sig.direction == SignalDirection.NO_VIEW
    assert sig.confidence == 0.0


def test_price_action_agent_conflicting_near_both() -> None:
    """Verify if somehow near both support and resistance, resolves to NO_VIEW."""
    agent = PriceActionAgent(proximity_threshold_pct=2.0)
    feats = {
        "close": 100.0,
        "support_20": 99.5,
        "resistance_20": 100.5,
        "lower_shadow_ratio": 0.40,
        "upper_shadow_ratio": 0.40,
    }
    fs, regime = _make_context(feats)

    sig = agent.evaluate("NSE:RELIANCE", "15m", fs, regime)

    assert sig.direction == SignalDirection.NO_VIEW
    assert sig.confidence == 0.0


def test_price_action_agent_only_one_level() -> None:
    """Verify behavior when only support or only resistance is present."""
    agent = PriceActionAgent(proximity_threshold_pct=0.50, min_rejection_wick_ratio=0.35)

    # Only support present
    feats_support_only = {
        "close": 100.2,
        "support_20": 100.0,
        "lower_shadow_ratio": 0.40,
    }
    fs_s, regime_s = _make_context(feats_support_only)
    sig_s = agent.evaluate("NSE:RELIANCE", "15m", fs_s, regime_s)
    assert sig_s.direction == SignalDirection.LONG
    assert "support_20" in sig_s.inputs_used
    assert "resistance_20" not in sig_s.inputs_used

    # Only resistance present
    feats_res_only = {
        "close": 99.8,
        "resistance_20": 100.0,
        "upper_shadow_ratio": 0.40,
    }
    fs_r, regime_r = _make_context(feats_res_only)
    sig_r = agent.evaluate("NSE:RELIANCE", "15m", fs_r, regime_r)
    assert sig_r.direction == SignalDirection.SHORT
    assert "resistance_20" in sig_r.inputs_used
    assert "support_20" not in sig_r.inputs_used


def test_price_action_agent_missing_features() -> None:
    """Verify missing close or missing both levels yields NO_VIEW."""
    agent = PriceActionAgent()
    # Missing close
    fs1, regime1 = _make_context({"support_20": 100.0})
    sig1 = agent.evaluate("NSE:RELIANCE", "15m", fs1, regime1)
    assert sig1.direction == SignalDirection.NO_VIEW
    assert sig1.confidence == 0.0

    # Missing support and resistance
    fs2, regime2 = _make_context({"close": 100.0})
    sig2 = agent.evaluate("NSE:RELIANCE", "15m", fs2, regime2)
    assert sig2.direction == SignalDirection.NO_VIEW
    assert sig2.confidence == 0.0


def test_price_action_agent_invalid_params() -> None:
    """Verify invalid constructor parameters raise ValueError."""
    with pytest.raises(ValueError, match="proximity_threshold_pct must be positive"):
        PriceActionAgent(proximity_threshold_pct=-0.5)

    with pytest.raises(ValueError, match="min_rejection_wick_ratio must be in"):
        PriceActionAgent(min_rejection_wick_ratio=0.0)

    with pytest.raises(ValueError, match="min_rejection_wick_ratio must be in"):
        PriceActionAgent(min_rejection_wick_ratio=1.0)
