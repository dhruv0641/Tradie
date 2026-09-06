"""Unit tests for FeatureEngine and point-in-time calculation guarantees.

Conforms to FRD-FEAT-3/4 and BTD §5.2.
"""

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from src.domain.features import FeatureSet
from src.features.engine import FeatureEngine


def _generate_synthetic_ohlcv(
    bars: int = 100,
    start_time: datetime | None = None,
    seed: int = 42,
    as_index: bool = False,
) -> pd.DataFrame:
    """Helper to generate realistic synthetic OHLCV data."""
    np.random.seed(seed)
    start = start_time or datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    timestamps = [start + timedelta(minutes=i) for i in range(bars)]

    close = 100.0 + np.cumsum(np.random.randn(bars) * 0.5)
    high = close + np.random.uniform(0.1, 1.0, size=bars)
    low = close - np.random.uniform(0.1, 1.0, size=bars)
    open_ = low + np.random.uniform(0.0, 1.0, size=bars) * (high - low)
    volume = np.random.randint(100, 5000, size=bars).astype(float)

    data = {
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }

    if as_index:
        return pd.DataFrame(data, index=pd.DatetimeIndex(timestamps))

    data["timestamp"] = timestamps
    return pd.DataFrame(data)


def test_feature_engine_initialization() -> None:
    """Test FeatureEngine parameter initialization and validation."""
    engine = FeatureEngine(feature_version="feat-v2.0", impute_missing=True, min_bars=10)
    assert engine.feature_version == "feat-v2.0"
    assert engine.impute_missing is True
    assert engine.min_bars == 10

    with pytest.raises(ValueError, match="min_bars must be at least 1"):
        FeatureEngine(min_bars=0)


def test_compute_features_with_explicit_cutoff() -> None:
    """Test feature calculation at an explicit point-in-time timestamp T."""
    df = _generate_synthetic_ohlcv(bars=80)
    engine = FeatureEngine(min_bars=10)

    cutoff = df["timestamp"].iloc[40]
    fs = engine.compute_features(
        df=df,
        instrument="NSE:TCS",
        timeframe="1m",
        cutoff_time=cutoff,
    )

    assert isinstance(fs, FeatureSet)
    assert fs.instrument == "NSE:TCS"
    assert fs.timeframe == "1m"
    assert fs.timestamp == cutoff
    assert fs.feature_version == "feat-v1.0"
    assert "rsi_14" in fs.features
    assert "macd_line" in fs.features
    assert "is_doji" in fs.features
    assert "support_20" in fs.features
    assert 0.0 <= fs.quality_score <= 1.0


def test_compute_features_default_latest_cutoff() -> None:
    """Test feature calculation when cutoff_time is None (defaults to latest bar)."""
    df = _generate_synthetic_ohlcv(bars=50)
    engine = FeatureEngine(min_bars=5)

    fs = engine.compute_features(
        df=df,
        instrument="NSE:INFY",
        timeframe="5m",
        cutoff_time=None,
    )

    expected_latest = df["timestamp"].iloc[-1]
    assert fs.timestamp == expected_latest
    assert fs.instrument == "NSE:INFY"
    assert fs.timeframe == "5m"
    assert len(fs.features) >= 40


def test_compute_features_datetime_index() -> None:
    """Test feature calculation on a DataFrame with a DatetimeIndex."""
    df = _generate_synthetic_ohlcv(bars=60, as_index=True)
    engine = FeatureEngine(min_bars=10)

    # Test with explicit cutoff
    cutoff = df.index[30]
    fs = engine.compute_features(
        df=df,
        instrument="NSE:RELIANCE",
        timeframe="1m",
        cutoff_time=cutoff,
    )
    assert fs.timestamp == cutoff
    assert "bb_upper" in fs.features

    # Test with implicit cutoff
    fs_latest = engine.compute_features(
        df=df,
        instrument="NSE:RELIANCE",
        timeframe="1m",
        cutoff_time=None,
    )
    assert fs_latest.timestamp == df.index[-1]


def test_zero_look_ahead_leak_detection() -> None:
    """CRITICAL: Failure injection test verifying zero look-ahead bias (BTD §5.2, FRD-FEAT-3).

    Mutating data strictly for t > T (price shocks, volume spikes, regime shift) must
    produce ZERO difference in the FeatureSet calculated at T.
    """
    df = _generate_synthetic_ohlcv(bars=100, seed=123)
    engine = FeatureEngine(min_bars=20)

    cutoff_idx = 50
    cutoff_time = df["timestamp"].iloc[cutoff_idx]

    # Baseline calculation at cutoff T
    fs_baseline = engine.compute_features(
        df=df,
        instrument="NSE:HDFCBANK",
        timeframe="1m",
        cutoff_time=cutoff_time,
    )

    # Create mutated DataFrame injecting extreme future price & volume shocks at t > T
    df_mutated = df.copy()
    future_mask = df_mutated["timestamp"] > cutoff_time

    df_mutated.loc[future_mask, "close"] = df_mutated.loc[future_mask, "close"] * 50.0
    df_mutated.loc[future_mask, "high"] = df_mutated.loc[future_mask, "close"] * 1.05
    df_mutated.loc[future_mask, "low"] = df_mutated.loc[future_mask, "close"] * 0.95
    df_mutated.loc[future_mask, "open"] = df_mutated.loc[future_mask, "close"] * 0.99
    df_mutated.loc[future_mask, "volume"] = 99_999_999.0

    # Recalculate feature set on mutated DataFrame at same cutoff T
    fs_mutated = engine.compute_features(
        df=df_mutated,
        instrument="NSE:HDFCBANK",
        timeframe="1m",
        cutoff_time=cutoff_time,
    )

    # Verify identical quality score and feature dictionary values
    assert fs_baseline.quality_score == fs_mutated.quality_score
    assert set(fs_baseline.features.keys()) == set(fs_mutated.features.keys())

    for k in fs_baseline.features:
        v_base = fs_baseline.features[k]
        v_mut = fs_mutated.features[k]
        if math.isnan(v_base):
            assert math.isnan(v_mut), f"Feature {k} expected NaN, got {v_mut}"
        else:
            assert v_base == pytest.approx(
                v_mut, rel=1e-7
            ), f"Look-ahead leak detected in feature {k}! Base: {v_base}, Mutated: {v_mut}"


def test_quality_score_and_completeness() -> None:
    """Test that quality_score correctly reflects feature warmup completeness."""
    # 25 bars: long-period indicators (e.g. SMA-50, SMA-200) are NaN
    df_short = _generate_synthetic_ohlcv(bars=25)
    engine = FeatureEngine(min_bars=10)
    fs_short = engine.compute_features(df_short, "NSE:TEST", "1m")
    assert 0.0 < fs_short.quality_score < 1.0

    # 250 bars: all indicators up to window 200 are populated
    df_long = _generate_synthetic_ohlcv(bars=250)
    fs_long = engine.compute_features(df_long, "NSE:TEST", "1m")
    assert fs_long.quality_score == 1.0


def test_impute_missing_behavior() -> None:
    """Test that impute_missing=True replaces NaNs and Infs with 0.0."""
    df = _generate_synthetic_ohlcv(bars=20)

    # Without imputation: some values are NaN
    engine_raw = FeatureEngine(impute_missing=False, min_bars=5)
    fs_raw = engine_raw.compute_features(df, "NSE:TEST", "1m")
    has_nan = any(math.isnan(v) for v in fs_raw.features.values())
    assert has_nan is True

    # With imputation: all values are finite (no NaNs)
    engine_imputed = FeatureEngine(impute_missing=True, min_bars=5)
    fs_imputed = engine_imputed.compute_features(df, "NSE:TEST", "1m")
    for k, v in fs_imputed.features.items():
        assert math.isfinite(v), f"Feature {k} is not finite: {v}"


def test_compute_historical_features() -> None:
    """Test batch historical feature computation across all rows."""
    df = _generate_synthetic_ohlcv(bars=50)
    engine = FeatureEngine()

    enriched = engine.compute_historical_features(df)
    assert len(enriched) == len(df)
    assert "rsi_14" in enriched.columns
    assert "bb_bandwidth" in enriched.columns
    assert "is_hammer" in enriched.columns
    assert "is_swing_high_5" in enriched.columns

    # Test with imputation
    engine_imputed = FeatureEngine(impute_missing=True)
    enriched_imputed = engine_imputed.compute_historical_features(df)
    assert not enriched_imputed["rsi_14"].isna().any()


def test_validation_errors() -> None:
    """Test fail-fast input validation and error raising."""
    engine = FeatureEngine(min_bars=5)
    df_valid = _generate_synthetic_ohlcv(bars=20)

    # 1. Empty DataFrame
    with pytest.raises(ValueError, match="Cannot compute features on empty DataFrame"):
        engine.compute_features(pd.DataFrame(), "NSE:TEST", "1m")

    with pytest.raises(ValueError, match="Cannot compute historical features on empty DataFrame"):
        engine.compute_historical_features(pd.DataFrame())

    # 2. Missing required OHLCV columns
    df_missing = df_valid.drop(columns=["close"])
    with pytest.raises(ValueError, match="Missing required OHLCV columns"):
        engine.compute_features(df_missing, "NSE:TEST", "1m")

    with pytest.raises(ValueError, match="Missing required OHLCV columns"):
        engine.compute_historical_features(df_missing)

    # 3. Naive cutoff_time
    naive_cutoff = datetime(2026, 1, 1, 9, 30)
    with pytest.raises(ValueError, match="cutoff_time must be timezone-aware UTC"):
        engine.compute_features(df_valid, "NSE:TEST", "1m", cutoff_time=naive_cutoff)

    # 4. Naive timestamp column
    df_naive = df_valid.copy()
    df_naive["timestamp"] = [ts.replace(tzinfo=None) for ts in df_naive["timestamp"]]
    with pytest.raises(ValueError, match="'timestamp' column must be timezone-aware UTC"):
        engine.compute_features(df_naive, "NSE:TEST", "1m")

    # 5. Naive DatetimeIndex
    df_idx_naive = df_valid.set_index(
        pd.DatetimeIndex([ts.replace(tzinfo=None) for ts in df_valid["timestamp"]])
    ).drop(columns=["timestamp"])
    with pytest.raises(ValueError, match="DatetimeIndex must be timezone-aware UTC"):
        engine.compute_features(df_idx_naive, "NSE:TEST", "1m")

    # 6. No timestamp column or DatetimeIndex
    df_no_ts = df_valid.drop(columns=["timestamp"]).reset_index(drop=True)
    with pytest.raises(ValueError, match="must have a timezone-aware DatetimeIndex or 'timestamp'"):
        engine.compute_features(df_no_ts, "NSE:TEST", "1m")

    # 7. Cutoff time before earliest bar (column timestamp)
    early_cutoff = df_valid["timestamp"].iloc[0] - timedelta(hours=1)
    with pytest.raises(ValueError, match="No market data available on or before cutoff_time"):
        engine.compute_features(df_valid, "NSE:TEST", "1m", cutoff_time=early_cutoff)

    # 7b. Cutoff time before earliest bar (DatetimeIndex)
    df_idx_valid = _generate_synthetic_ohlcv(bars=20, as_index=True)
    with pytest.raises(ValueError, match="No market data available on or before cutoff_time"):
        engine.compute_features(df_idx_valid, "NSE:TEST", "1m", cutoff_time=early_cutoff)

    # 8. Insufficient bars below min_bars
    cutoff_two_bars = df_valid["timestamp"].iloc[2]
    with pytest.raises(ValueError, match="Insufficient historical data"):
        engine.compute_features(df_valid, "NSE:TEST", "1m", cutoff_time=cutoff_two_bars)


def test_featureset_immutability() -> None:
    """Test that returned FeatureSet domain models are strictly frozen."""
    df = _generate_synthetic_ohlcv(bars=20)
    engine = FeatureEngine(min_bars=5)
    fs = engine.compute_features(df, "NSE:TEST", "1m")

    with pytest.raises(ValidationError):
        fs.instrument = "NSE:MUTATED"

    with pytest.raises(ValidationError):
        fs.quality_score = 0.5
