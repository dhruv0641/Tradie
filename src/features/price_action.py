"""Price action, candlestick anatomy, and market structure features (FRD-FEAT-1, MLD §6.4)."""

import numpy as np
import pandas as pd


def compute_candlestick_anatomy(
    open_: pd.Series,
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
) -> pd.DataFrame:
    """Calculate geometric candlestick components and relative ratios.

    Args:
        open_: Opening price series.
        high: High price series.
        low: Low price series.
        close: Close price series.

    Returns:
        DataFrame containing range, body_size, upper/lower wicks, and normalized ratios.
    """
    candle_range = (high - low).replace(0.0, np.nan)
    body_size = (close - open_).abs()
    upper_wick = high - np.maximum(open_, close)
    lower_wick = np.minimum(open_, close) - low

    body_ratio = (body_size / candle_range).fillna(0.0)
    upper_wick_ratio = (upper_wick / candle_range).fillna(0.0)
    lower_wick_ratio = (lower_wick / candle_range).fillna(0.0)
    is_bullish = close > open_

    return pd.DataFrame(
        {
            "candle_range": candle_range.fillna(0.0),
            "body_size": body_size,
            "upper_wick": upper_wick,
            "lower_wick": lower_wick,
            "body_ratio": body_ratio,
            "upper_wick_ratio": upper_wick_ratio,
            "lower_wick_ratio": lower_wick_ratio,
            "is_bullish": is_bullish,
        },
        index=open_.index,
    )


def detect_candlestick_patterns(
    open_: pd.Series,
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
) -> pd.DataFrame:
    """Detect canonical rule-based candlestick formations with zero look-ahead bias.

    Formations:
    - Doji: Thin body (body_ratio <= 0.10) with non-zero range.
    - Hammer: Small upper body with long lower rejection wick (lower_wick_ratio >= 0.60).
    - Shooting Star: Small lower body with long upper rejection wick (upper_wick_ratio >= 0.60).
    - Bullish Engulfing: Current bullish candle body fully engulfs previous bearish body.
    - Bearish Engulfing: Current bearish candle body fully engulfs previous bullish body.
    """
    anatomy = compute_candlestick_anatomy(open_, high, low, close)
    candle_range = anatomy["candle_range"]
    body_ratio = anatomy["body_ratio"]
    upper_wick_ratio = anatomy["upper_wick_ratio"]
    lower_wick_ratio = anatomy["lower_wick_ratio"]
    is_bullish = anatomy["is_bullish"]

    has_range = candle_range > 0.0

    # 1. Doji
    is_doji = (body_ratio <= 0.10) & has_range

    # 2. Hammer (bullish rejection at bottom)
    is_hammer = (
        (lower_wick_ratio >= 0.60) & (body_ratio <= 0.30) & (upper_wick_ratio <= 0.15) & has_range
    )

    # 3. Shooting Star (bearish rejection at top)
    is_shooting_star = (
        (upper_wick_ratio >= 0.60) & (body_ratio <= 0.30) & (lower_wick_ratio <= 0.15) & has_range
    )

    # 4. Engulfing patterns
    prev_open = open_.shift(1)
    prev_close = close.shift(1)
    prev_bearish = prev_close < prev_open
    prev_bullish = prev_close > prev_open

    is_bullish_engulfing = (
        prev_bearish & is_bullish & (open_ <= prev_close) & (close >= prev_open) & has_range
    )

    is_bearish_engulfing = (
        prev_bullish & (~is_bullish) & (open_ >= prev_close) & (close <= prev_open) & has_range
    )

    return pd.DataFrame(
        {
            "is_doji": is_doji,
            "is_hammer": is_hammer,
            "is_shooting_star": is_shooting_star,
            "is_bullish_engulfing": is_bullish_engulfing,
            "is_bearish_engulfing": is_bearish_engulfing,
        },
        index=open_.index,
    )


def detect_swing_points(
    high: pd.Series,
    low: pd.Series,
    window: int = 5,
) -> tuple[pd.Series, pd.Series]:
    """Identify backward-looking swing highs and swing lows without look-ahead bias.

    A bar at t is marked as a swing high if high[t] is the maximum in [t - window + 1 ... t].
    A bar at t is marked as a swing low if low[t] is the minimum in [t - window + 1 ... t].

    Args:
        high: High price series.
        low: Low price series.
        window: Backward lookback window length (default: 5).

    Returns:
        Tuple of (is_swing_high, is_swing_low) boolean Series.
    """
    if window < 1:
        msg = f"Swing window must be >= 1, got {window}"
        raise ValueError(msg)

    rolling_high = high.rolling(window=window, min_periods=window).max()
    rolling_low = low.rolling(window=window, min_periods=window).min()

    is_swing_high = high == rolling_high
    is_swing_low = low == rolling_low

    return is_swing_high, is_swing_low


def compute_support_resistance(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    window: int = 20,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """Compute rolling support/resistance levels and normalized price distances.

    Args:
        high: High price series.
        low: Low price series.
        close: Close price series.
        window: Historical lookback window (default: 20).

    Returns:
        Tuple of (support_level, resistance_level, dist_to_support_pct, dist_to_resistance_pct).
    """
    if window < 1:
        msg = f"Lookback window must be >= 1, got {window}"
        raise ValueError(msg)

    support = low.rolling(window=window, min_periods=window).min()
    resistance = high.rolling(window=window, min_periods=window).max()

    close_safe = close.replace(0.0, np.nan)
    dist_to_support = (close - support) / close_safe
    dist_to_resistance = (resistance - close) / close_safe

    return support, resistance, dist_to_support, dist_to_resistance


def extract_price_action_features(df: pd.DataFrame) -> pd.DataFrame:
    """Extract complete price action feature set from an OHLCV DataFrame.

    Expected columns: 'open', 'high', 'low', 'close', 'volume' (case-insensitive).

    Returns:
        DataFrame enriched with candlestick anatomy, patterns, swings, and support/resistance.
    """
    data = df.copy()
    data.columns = pd.Index([str(c).lower() for c in data.columns])

    open_ = data["open"].astype(float)
    high = data["high"].astype(float)
    low = data["low"].astype(float)
    close = data["close"].astype(float)

    # 1. Candlestick anatomy
    anatomy = compute_candlestick_anatomy(open_, high, low, close)
    for col in anatomy.columns:
        data[col] = anatomy[col]

    # 2. Candlestick patterns
    patterns = detect_candlestick_patterns(open_, high, low, close)
    for col in patterns.columns:
        data[col] = patterns[col]

    # 3. Swing points
    is_sh, is_sl = detect_swing_points(high, low, window=5)
    data["is_swing_high_5"] = is_sh
    data["is_swing_low_5"] = is_sl

    # 4. Support / Resistance
    supp, res, dist_s, dist_r = compute_support_resistance(high, low, close, window=20)
    data["support_20"] = supp
    data["resistance_20"] = res
    data["dist_to_support_pct_20"] = dist_s
    data["dist_to_resistance_pct_20"] = dist_r

    return data
