"""Unit tests for price action, candlestick patterns, and market structure extractor (MLD §6.4)."""

import pandas as pd
import pytest

from src.features.price_action import (
    compute_candlestick_anatomy,
    compute_support_resistance,
    detect_candlestick_patterns,
    detect_swing_points,
    extract_price_action_features,
)


def test_candlestick_anatomy_calculations() -> None:
    """Verify geometry formulas for body size, range, wicks, and relative ratios."""
    # Bullish candle: Open=100, High=110, Low=95, Close=105
    # Range = 15, Body = 5, Upper wick = 5 (110 - 105), Lower wick = 5 (100 - 95)
    open_ = pd.Series([100.0])
    high = pd.Series([110.0])
    low = pd.Series([95.0])
    close = pd.Series([105.0])

    anatomy = compute_candlestick_anatomy(open_, high, low, close)

    assert anatomy["candle_range"].iloc[0] == 15.0
    assert anatomy["body_size"].iloc[0] == 5.0
    assert anatomy["upper_wick"].iloc[0] == 5.0
    assert anatomy["lower_wick"].iloc[0] == 5.0
    assert anatomy["body_ratio"].iloc[0] == pytest.approx(5.0 / 15.0)
    assert anatomy["upper_wick_ratio"].iloc[0] == pytest.approx(5.0 / 15.0)
    assert anatomy["lower_wick_ratio"].iloc[0] == pytest.approx(5.0 / 15.0)
    assert bool(anatomy["is_bullish"].iloc[0]) is True


def test_doji_detection() -> None:
    """Verify Doji pattern triggers when body ratio is <= 0.10 of range."""
    # Doji: Open=100.0, Close=100.05, High=102.0, Low=98.0 -> Range=4.0, Body=0.05, BodyRatio=0.0125
    open_ = pd.Series([100.0, 100.0])
    high = pd.Series([102.0, 110.0])
    low = pd.Series([98.0, 90.0])
    close = pd.Series([100.05, 108.0])  # Bar 0 is Doji, Bar 1 is large body

    patterns = detect_candlestick_patterns(open_, high, low, close)
    assert bool(patterns["is_doji"].iloc[0]) is True
    assert bool(patterns["is_doji"].iloc[1]) is False


def test_hammer_detection() -> None:
    """Verify Hammer pattern: small upper body, long lower rejection wick >= 60% of range."""
    # Hammer: Open=100.0, Close=101.0, High=101.2, Low=90.0
    # Range = 11.2, Body = 1.0 (8.9%), Upper wick = 0.2 (1.7%), Lower wick = 10.0 (89.2%)
    open_ = pd.Series([100.0])
    high = pd.Series([101.2])
    low = pd.Series([90.0])
    close = pd.Series([101.0])

    patterns = detect_candlestick_patterns(open_, high, low, close)
    assert bool(patterns["is_hammer"].iloc[0]) is True
    assert bool(patterns["is_shooting_star"].iloc[0]) is False


def test_shooting_star_detection() -> None:
    """Verify Shooting Star pattern: small lower body, long upper rejection wick >= 60% of range."""
    # Shooting Star: Open=99.0, Close=98.5, High=110.0, Low=98.3
    # Range = 11.7, Body = 0.5 (4.2%), Upper wick = 11.0 (94%), Lower wick = 0.2 (1.7%)
    open_ = pd.Series([99.0])
    high = pd.Series([110.0])
    low = pd.Series([98.3])
    close = pd.Series([98.5])

    patterns = detect_candlestick_patterns(open_, high, low, close)
    assert bool(patterns["is_shooting_star"].iloc[0]) is True
    assert bool(patterns["is_hammer"].iloc[0]) is False


def test_engulfing_patterns() -> None:
    """Verify Bullish and Bearish Engulfing two-bar sequence classifications."""
    # Bar 0: Bearish, Bar 1: Bullish Engulfing
    # Bar 2: Bullish, Bar 3: Bearish Engulfing
    open_ = pd.Series([100.0, 89.0, 102.0, 111.0])
    high = pd.Series([102.0, 103.0, 112.0, 113.0])
    low = pd.Series([88.0, 87.0, 101.0, 99.0])
    close = pd.Series([90.0, 102.0, 110.0, 100.0])

    patterns = detect_candlestick_patterns(open_, high, low, close)
    assert bool(patterns["is_bullish_engulfing"].iloc[1]) is True
    assert bool(patterns["is_bearish_engulfing"].iloc[3]) is True


def test_swing_points_backward_looking() -> None:
    """Verify swing points are identified strictly using past backward-looking window."""
    # 7 bars: High peaks at index 4 (120), Low troughs at index 2 (80)
    high = pd.Series([100.0, 105.0, 102.0, 110.0, 120.0, 115.0, 112.0])
    low = pd.Series([95.0, 90.0, 80.0, 92.0, 100.0, 98.0, 97.0])

    is_sh, is_sl = detect_swing_points(high, low, window=5)

    # At index 4 (120), it is highest of [100, 105, 102, 110, 120] -> Swing High True
    assert bool(is_sh.iloc[4]) is True
    # At index 5 (115), highest of [105, 102, 110, 120, 115] is 120, not 115 -> False
    assert bool(is_sh.iloc[5]) is False
    # At index 4, lowest of [95, 90, 80, 92, 100] is index 2 (80), so index 4 is not swing low
    assert bool(is_sl.iloc[4]) is False

    with pytest.raises(ValueError, match="Swing window must be >= 1"):
        detect_swing_points(high, low, window=0)


def test_support_resistance_calculations() -> None:
    """Verify support and resistance bounds and normalized distance percentages."""
    high = pd.Series([100.0 + i for i in range(25)])
    low = pd.Series([90.0 + i for i in range(25)])
    close = pd.Series([95.0 + i for i in range(25)])

    supp, res, dist_s, dist_r = compute_support_resistance(high, low, close, window=20)

    # At index 20 (window=20: bars 1..20): low was min(91..110) = 91, high was max(101..120) = 120
    assert supp.iloc[20] == 91.0
    assert res.iloc[20] == 120.0
    assert dist_s.iloc[20] > 0.0
    assert dist_r.iloc[20] > 0.0

    with pytest.raises(ValueError, match="Lookback window must be >= 1"):
        compute_support_resistance(high, low, close, window=0)


def test_extract_price_action_features_pipeline() -> None:
    """Verify batch extraction enriches DataFrame with all required price action columns."""
    df = pd.DataFrame(
        {
            "open": [100.0] * 30,
            "high": [105.0] * 30,
            "low": [95.0] * 30,
            "close": [102.0] * 30,
            "volume": [1000.0] * 30,
        }
    )
    enriched = extract_price_action_features(df)

    expected_cols = [
        "candle_range",
        "body_size",
        "upper_wick",
        "lower_wick",
        "body_ratio",
        "upper_wick_ratio",
        "lower_wick_ratio",
        "is_bullish",
        "is_doji",
        "is_hammer",
        "is_shooting_star",
        "is_bullish_engulfing",
        "is_bearish_engulfing",
        "is_swing_high_5",
        "is_swing_low_5",
        "support_20",
        "resistance_20",
        "dist_to_support_pct_20",
        "dist_to_resistance_pct_20",
    ]
    for col in expected_cols:
        assert col in enriched.columns, f"Missing price action column: {col}"
