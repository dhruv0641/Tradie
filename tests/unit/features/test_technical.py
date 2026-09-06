"""Unit tests for technical indicators calculation engine (FRD-FEAT-1, MLD §4.1)."""

import numpy as np
import pandas as pd
import pytest

from src.features.technical import (
    compute_adx,
    compute_all_technical_features,
    compute_atr,
    compute_bollinger_bands,
    compute_ema,
    compute_macd,
    compute_roc,
    compute_rolling_volatility,
    compute_rolling_zscore,
    compute_rsi,
    compute_sma,
    compute_stochastic,
    compute_volume_features,
)


@pytest.fixture
def sample_ohlcv() -> pd.DataFrame:
    """Generate 100 bars of synthetic trending and oscillating price data."""
    np.random.seed(42)
    n = 100
    base_price = 100.0
    returns = np.random.normal(loc=0.001, scale=0.015, size=n)
    close = base_price * np.cumprod(1.0 + returns)

    high = close * (1.0 + np.abs(np.random.normal(0, 0.008, n)))
    low = close * (1.0 - np.abs(np.random.normal(0, 0.008, n)))
    open_ = (high + low) / 2.0
    volume = np.random.randint(1000, 100000, size=n).astype(float)

    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


def test_sma_calculation(sample_ohlcv: pd.DataFrame) -> None:
    """Verify SMA calculation against manual rolling mean and window validation."""
    close = sample_ohlcv["close"]
    sma_5 = compute_sma(close, window=5)

    assert len(sma_5) == 100
    assert np.isnan(sma_5.iloc[3])
    assert not np.isnan(sma_5.iloc[4])
    assert sma_5.iloc[4] == pytest.approx(close.iloc[:5].mean(), rel=1e-5)

    with pytest.raises(ValueError, match="SMA window must be >= 1"):
        compute_sma(close, window=0)


def test_ema_calculation(sample_ohlcv: pd.DataFrame) -> None:
    """Verify EMA calculation and span parameter validation."""
    close = sample_ohlcv["close"]
    ema_10 = compute_ema(close, span=10)

    assert len(ema_10) == 100
    assert np.isnan(ema_10.iloc[8])
    assert not np.isnan(ema_10.iloc[9])

    with pytest.raises(ValueError, match="EMA span must be >= 1"):
        compute_ema(close, span=0)


def test_macd_calculation(sample_ohlcv: pd.DataFrame) -> None:
    """Verify MACD line, signal line, and histogram arithmetic."""
    close = sample_ohlcv["close"]
    macd, signal, hist = compute_macd(close, fast=12, slow=26, signal=9)

    assert len(macd) == len(close)
    # MACD line equals fast_ema - slow_ema
    fast_ema = compute_ema(close, span=12)
    slow_ema = compute_ema(close, span=26)
    expected_macd = fast_ema - slow_ema

    valid_idx = ~np.isnan(macd)
    np.testing.assert_allclose(macd[valid_idx], expected_macd[valid_idx], rtol=1e-5)
    np.testing.assert_allclose((macd - signal)[valid_idx], hist[valid_idx], rtol=1e-5)

    with pytest.raises(ValueError, match="strictly less than slow span"):
        compute_macd(close, fast=26, slow=12)


def test_rsi_calculation_boundaries(sample_ohlcv: pd.DataFrame) -> None:
    """Verify RSI remains bounded in [0, 100] and handles uniform prices."""
    close = sample_ohlcv["close"]
    rsi = compute_rsi(close, period=14)

    valid_rsi = rsi.dropna()
    assert (valid_rsi >= 0.0).all()
    assert (valid_rsi <= 100.0).all()

    # Flat series should produce neutral RSI
    flat_series = pd.Series([100.0] * 30)
    flat_rsi = compute_rsi(flat_series, period=14).dropna()
    assert (flat_rsi == 50.0).all()

    with pytest.raises(ValueError, match="RSI period must be >= 1"):
        compute_rsi(close, period=0)


def test_bollinger_bands_geometry(sample_ohlcv: pd.DataFrame) -> None:
    """Verify Upper Band >= Middle Band >= Lower Band and %b consistency."""
    close = sample_ohlcv["close"]
    mid, upper, lower, width, pct_b = compute_bollinger_bands(close, window=20, num_std=2.0)

    valid = ~np.isnan(mid)
    assert (upper[valid] >= mid[valid]).all()
    assert (mid[valid] >= lower[valid]).all()
    assert (width[valid] >= 0.0).all()

    expected_b = (close[valid] - lower[valid]) / (upper[valid] - lower[valid])
    np.testing.assert_allclose(pct_b[valid], expected_b, rtol=1e-5)

    with pytest.raises(ValueError, match="Bollinger Bands window must be >= 2"):
        compute_bollinger_bands(close, window=1)


def test_atr_calculation(sample_ohlcv: pd.DataFrame) -> None:
    """Verify ATR is strictly positive and matches true range smoothing."""
    high = sample_ohlcv["high"]
    low = sample_ohlcv["low"]
    close = sample_ohlcv["close"]

    atr = compute_atr(high, low, close, period=14)
    valid_atr = atr.dropna()
    assert len(valid_atr) > 0
    assert (valid_atr > 0.0).all()

    with pytest.raises(ValueError, match="ATR period must be >= 1"):
        compute_atr(high, low, close, period=0)


def test_adx_directional_components(sample_ohlcv: pd.DataFrame) -> None:
    """Verify ADX, +DI, and -DI non-negativity and bounds."""
    high = sample_ohlcv["high"]
    low = sample_ohlcv["low"]
    close = sample_ohlcv["close"]

    adx, plus_di, minus_di = compute_adx(high, low, close, period=14)

    valid = ~np.isnan(adx)
    assert (adx[valid] >= 0.0).all()
    assert (plus_di[valid] >= 0.0).all()
    assert (minus_di[valid] >= 0.0).all()

    with pytest.raises(ValueError, match="ADX period must be >= 1"):
        compute_adx(high, low, close, period=0)


def test_stochastic_oscillator_bounds(sample_ohlcv: pd.DataFrame) -> None:
    """Verify Stochastic %K and %D oscillate within [0, 100]."""
    high = sample_ohlcv["high"]
    low = sample_ohlcv["low"]
    close = sample_ohlcv["close"]

    k, d = compute_stochastic(high, low, close, k_period=14, d_period=3)
    valid_k = k.dropna()
    valid_d = d.dropna()

    assert (valid_k >= 0.0).all() and (valid_k <= 100.0).all()
    assert (valid_d >= 0.0).all() and (valid_d <= 100.0).all()


def test_roc_and_zscore(sample_ohlcv: pd.DataFrame) -> None:
    """Verify ROC, Z-score, and rolling return volatility calculations."""
    close = sample_ohlcv["close"]
    roc = compute_roc(close, period=10)
    zscore = compute_rolling_zscore(close, window=20)
    vol = compute_rolling_volatility(close, window=20)

    # 10-period manual ROC verification at index 10
    expected_roc_10 = 100.0 * (close.iloc[10] - close.iloc[0]) / close.iloc[0]
    assert roc.iloc[10] == pytest.approx(expected_roc_10, rel=1e-5)

    valid_z = zscore.dropna()
    assert abs(valid_z.mean()) < 1.0

    valid_vol = vol.dropna()
    assert (valid_vol > 0.0).all()

    with pytest.raises(ValueError, match="ROC period must be >= 1"):
        compute_roc(close, period=0)


def test_volume_features(sample_ohlcv: pd.DataFrame) -> None:
    """Verify Volume SMA and relative volume ratio."""
    vol = sample_ohlcv["volume"]
    vol_sma, vol_ratio = compute_volume_features(vol, window=20)

    valid = ~np.isnan(vol_sma)
    assert (vol_sma[valid] > 0.0).all()
    assert (vol_ratio[valid] > 0.0).all()


def test_zero_lookahead_bias_invariant(sample_ohlcv: pd.DataFrame) -> None:
    """Critical Invariant (BTD §5.2): Modifying future data (t > T) produces 0 change at t <= T."""
    df_original = sample_ohlcv.copy()
    cutoff_t = 50

    feats_orig = compute_all_technical_features(df_original)

    # Mutate future data radically past cutoff_t
    df_future_spike = df_original.copy()
    df_future_spike.loc[cutoff_t + 1 :, "close"] *= 5.0
    df_future_spike.loc[cutoff_t + 1 :, "high"] *= 5.0
    df_future_spike.loc[cutoff_t + 1 :, "low"] *= 5.0
    df_future_spike.loc[cutoff_t + 1 :, "volume"] *= 10.0

    feats_spiked = compute_all_technical_features(df_future_spike)

    # At t <= cutoff_t, all features must be byte-for-byte or numerically identical
    cols_to_check = [
        c for c in feats_orig.columns if c not in ("open", "high", "low", "close", "volume")
    ]
    for col in cols_to_check:
        v_orig = feats_orig.loc[:cutoff_t, col].to_numpy(dtype=float)
        v_spiked = feats_spiked.loc[:cutoff_t, col].to_numpy(dtype=float)
        np.testing.assert_allclose(
            v_orig,
            v_spiked,
            equal_nan=True,
            err_msg=f"Look-ahead bias detected in indicator column: {col}",
        )


def test_compute_all_technical_features_schema(sample_ohlcv: pd.DataFrame) -> None:
    """Verify all expected technical indicator columns are populated."""
    enriched = compute_all_technical_features(sample_ohlcv)

    expected_cols = [
        "sma_5",
        "sma_20",
        "sma_200",
        "ema_5",
        "ema_20",
        "ema_200",
        "macd_line",
        "macd_signal",
        "macd_hist",
        "adx_14",
        "plus_di_14",
        "minus_di_14",
        "rsi_14",
        "roc_10",
        "stoch_k",
        "stoch_d",
        "bb_middle",
        "bb_upper",
        "bb_lower",
        "bb_bandwidth",
        "bb_percent_b",
        "zscore_20",
        "atr_14",
        "volatility_20",
        "volume_sma_20",
        "volume_ratio_20",
    ]
    for col in expected_cols:
        assert col in enriched.columns, f"Missing expected feature column: {col}"
