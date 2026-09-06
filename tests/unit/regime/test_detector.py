"""Unit tests for RegimeDetector 5-dimensional classification engine (MLD §5.1, ADD §5)."""

from datetime import UTC, datetime
from uuid import uuid4

import pandas as pd

from src.config.models import RegimeConfig
from src.domain.features import FeatureSet
from src.domain.regime import (
    DirectionalBias,
    LiquidityCondition,
    RiskSentiment,
    TrendState,
    VolatilityLevel,
)
from src.regime.detector import RegimeDetector


def _create_feature_set(features: dict[str, float], instrument: str = "NSE:TCS") -> FeatureSet:
    """Helper to create FeatureSet with UTC timestamp."""
    return FeatureSet(
        feature_set_id=uuid4(),
        instrument=instrument,
        timestamp=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        timeframe="15m",
        features=features,
    )


def test_trending_up_classification() -> None:
    """Verify ADX >= 25 with +DI > -DI classifies as TRENDING_UP and BULLISH."""
    detector = RegimeDetector()
    feats = {
        "adx_14": 32.0,
        "plus_di_14": 28.0,
        "minus_di_14": 14.0,
        "sma_20": 3550.0,
        "sma_50": 3500.0,
        "atr_14": 15.0,
        "volume_ratio_20": 1.2,
    }
    fs = _create_feature_set(feats)
    res = detector.classify(fs)

    assert res.trend_state == TrendState.TRENDING_UP
    assert res.directional_bias == DirectionalBias.BULLISH
    assert res.liquidity_condition == LiquidityCondition.NORMAL
    assert "TRENDING_UP" in res.regime_label


def test_trending_down_classification() -> None:
    """Verify ADX >= 25 with -DI > +DI classifies as TRENDING_DOWN and BEARISH."""
    detector = RegimeDetector()
    feats = {
        "adx_14": 30.0,
        "plus_di_14": 12.0,
        "minus_di_14": 31.0,
        "sma_20": 3480.0,
        "sma_50": 3520.0,
        "atr_14": 16.0,
        "volume_ratio_20": 0.9,
    }
    fs = _create_feature_set(feats)
    res = detector.classify(fs)

    assert res.trend_state == TrendState.TRENDING_DOWN
    assert res.directional_bias == DirectionalBias.BEARISH
    assert res.liquidity_condition == LiquidityCondition.NORMAL
    assert "TRENDING_DOWN" in res.regime_label


def test_ranging_classification_and_neutral_bias_invariant() -> None:
    """Verify MLD §5.1 Invariant: DirectionalBias is strictly NEUTRAL when RANGING."""
    detector = RegimeDetector()
    # Even with positive short-term momentum (e.g. roc_10 = 5.0), RANGING must force NEUTRAL
    feats = {
        "adx_14": 18.0,
        "plus_di_14": 22.0,
        "minus_di_14": 19.0,
        "roc_10": 5.5,
        "atr_14": 10.0,
        "volume_ratio_20": 1.0,
    }
    fs = _create_feature_set(feats)
    res = detector.classify(fs)

    assert res.trend_state == TrendState.RANGING
    assert res.directional_bias == DirectionalBias.NEUTRAL
    assert "RANGING" in res.regime_label


def test_volatility_percentile_classification() -> None:
    """Verify rolling volatility percentile categorization into LOW, NORMAL, HIGH."""
    config = RegimeConfig(volatility_low_percentile=33.0, volatility_high_percentile=67.0)
    detector = RegimeDetector(config)

    # Warm up history with values 10 through 40
    for val in range(10, 41):
        fs_warmup = _create_feature_set({"adx_14": 20.0, "atr_14": float(val)})
        detector.classify(fs_warmup)

    # Test LOW volatility (val = 12, rank ~ 3/31 ~ 9th percentile)
    res_low = detector.classify(_create_feature_set({"adx_14": 20.0, "atr_14": 12.0}))
    assert res_low.volatility_level == VolatilityLevel.LOW
    assert "LOW_VOL" in res_low.regime_label

    # Test NORMAL volatility (val = 25, rank ~ 50th percentile)
    res_norm = detector.classify(_create_feature_set({"adx_14": 20.0, "atr_14": 25.0}))
    assert res_norm.volatility_level == VolatilityLevel.NORMAL
    assert "NORMAL_VOL" in res_norm.regime_label

    # Test HIGH volatility (val = 45, rank = 100th percentile)
    res_high = detector.classify(_create_feature_set({"adx_14": 20.0, "atr_14": 45.0}))
    assert res_high.volatility_level == VolatilityLevel.HIGH
    assert "HIGH_VOL" in res_high.regime_label


def test_liquidity_classification_degraded_and_normal() -> None:
    """Verify liquidity is DEGRADED when volume ratio is below threshold."""
    detector = RegimeDetector(RegimeConfig(liquidity_volume_ratio_threshold=0.50))

    # Degraded condition (volume ratio 0.25)
    fs_degraded = _create_feature_set(
        {
            "adx_14": 20.0,
            "atr_14": 12.0,
            "volume_ratio_20": 0.25,
        }
    )
    res_deg = detector.classify(fs_degraded)
    assert res_deg.liquidity_condition == LiquidityCondition.DEGRADED
    assert "DEGRADED_LIQ" in res_deg.regime_label

    # Normal condition (volume ratio 0.85)
    fs_normal = _create_feature_set(
        {
            "adx_14": 20.0,
            "atr_14": 12.0,
            "volume_ratio_20": 0.85,
        }
    )
    res_norm = detector.classify(fs_normal)
    assert res_norm.liquidity_condition == LiquidityCondition.NORMAL
    assert "DEGRADED_LIQ" not in res_norm.regime_label


def test_risk_sentiment_default_and_cross_asset() -> None:
    """Verify default UNKNOWN risk sentiment and VIX-conditioned evaluation."""
    detector = RegimeDetector()

    # Default without cross-asset data
    res_default = detector.classify(_create_feature_set({"adx_14": 20.0, "atr_14": 10.0}))
    assert res_default.risk_sentiment == RiskSentiment.UNKNOWN

    # Risk-off scenario (VIX > 22.0)
    res_off = detector.classify(
        _create_feature_set(
            {
                "adx_14": 20.0,
                "atr_14": 10.0,
                "india_vix": 26.5,
            }
        )
    )
    assert res_off.risk_sentiment == RiskSentiment.RISK_OFF

    # Risk-on scenario (VIX < 14.0)
    res_on = detector.classify(
        _create_feature_set(
            {
                "adx_14": 20.0,
                "atr_14": 10.0,
                "india_vix": 12.8,
            }
        )
    )
    assert res_on.risk_sentiment == RiskSentiment.RISK_ON


def test_graceful_degradation_on_missing_features() -> None:
    """Verify missing features degrade to UNKNOWN without raising exceptions (MLD §5.3)."""
    detector = RegimeDetector()
    empty_fs = _create_feature_set({})
    res = detector.classify(empty_fs)

    assert res.trend_state == TrendState.UNKNOWN
    assert res.volatility_level == VolatilityLevel.UNKNOWN
    assert res.directional_bias == DirectionalBias.UNKNOWN
    assert res.liquidity_condition == LiquidityCondition.UNKNOWN
    assert res.risk_sentiment == RiskSentiment.UNKNOWN
    assert res.regime_label == "UNKNOWN"


def test_warmup_from_dataframe() -> None:
    """Verify batch warmup using historical DataFrame."""
    detector = RegimeDetector()
    hist_df = pd.DataFrame(
        {
            "atr_14": [10.0 + i * 0.5 for i in range(50)],
            "close": [100.0] * 50,
        }
    )
    fs = _create_feature_set({"adx_14": 20.0, "atr_14": 11.0})
    res = detector.classify(fs, history_df=hist_df)

    assert "volatility_percentile" in res.metrics
    assert res.volatility_level == VolatilityLevel.LOW

    detector.clear_history()
    assert len(detector._volatility_history) == 0


def test_trend_sma_fallback_when_di_missing() -> None:
    """Verify trend direction falls back to SMA20 vs SMA50 when DI indicators are absent."""
    detector = RegimeDetector()

    # Upward SMA alignment
    fs_up = _create_feature_set(
        {
            "adx_14": 28.0,
            "sma_20": 105.0,
            "sma_50": 100.0,
            "atr_14": 5.0,
        }
    )
    res_up = detector.classify(fs_up)
    assert res_up.trend_state == TrendState.TRENDING_UP
    assert res_up.directional_bias == DirectionalBias.BULLISH

    # Downward SMA alignment
    fs_down = _create_feature_set(
        {
            "adx_14": 28.0,
            "sma_20": 95.0,
            "sma_50": 100.0,
            "atr_14": 5.0,
        }
    )
    res_down = detector.classify(fs_down)
    assert res_down.trend_state == TrendState.TRENDING_DOWN
    assert res_down.directional_bias == DirectionalBias.BEARISH

    # Undefined SMA alignment when SMAs missing
    fs_none = _create_feature_set({"adx_14": 28.0, "atr_14": 5.0})
    res_none = detector.classify(fs_none)
    assert res_none.trend_state == TrendState.UNKNOWN


def test_unknown_trend_roc_momentum_fallback() -> None:
    """Verify directional bias falls back to ROC when trend state is UNKNOWN."""
    detector = RegimeDetector()

    # Positive ROC (> 1.0)
    fs_pos = _create_feature_set({"roc_10": 2.5, "atr_14": 5.0})
    res_pos = detector.classify(fs_pos)
    assert res_pos.directional_bias == DirectionalBias.BULLISH

    # Negative ROC (< -1.0)
    fs_neg = _create_feature_set({"roc_10": -3.0, "atr_14": 5.0})
    res_neg = detector.classify(fs_neg)
    assert res_neg.directional_bias == DirectionalBias.BEARISH

    # Neutral ROC (-1.0 to 1.0)
    fs_neut = _create_feature_set({"roc_10": 0.2, "atr_14": 5.0})
    res_neut = detector.classify(fs_neut)
    assert res_neut.directional_bias == DirectionalBias.NEUTRAL


def test_volatility_zscore_heuristic_on_short_history() -> None:
    """Verify zscore >= 2.0 triggers HIGH volatility during history warmup (<10 bars)."""
    detector = RegimeDetector()
    fs_high_z = _create_feature_set({"adx_14": 20.0, "atr_14": 10.0, "zscore_20": 2.5})
    res = detector.classify(fs_high_z)
    assert res.volatility_level == VolatilityLevel.HIGH


def test_liquidity_volume_and_sma_fallback() -> None:
    """Verify volume and volume_sma_20 ratio calculation when volume_ratio_20 is missing."""
    detector = RegimeDetector()
    fs = _create_feature_set(
        {
            "adx_14": 20.0,
            "atr_14": 5.0,
            "volume": 20000.0,
            "volume_sma_20": 50000.0,
        }
    )
    res = detector.classify(fs)
    assert res.liquidity_condition == LiquidityCondition.DEGRADED
    assert res.metrics["volume_ratio"] == 0.4
