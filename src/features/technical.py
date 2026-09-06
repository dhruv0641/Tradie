"""Vectorized technical indicators calculation engine (FRD-FEAT-1, MLD §4.1)."""

import numpy as np
import pandas as pd


def compute_sma(series: pd.Series, window: int) -> pd.Series:
    """Calculate Simple Moving Average (SMA).

    Args:
        series: Input price or value series.
        window: Moving average period length (>= 1).
    """
    if window < 1:
        msg = f"SMA window must be >= 1, got {window}"
        raise ValueError(msg)
    return series.rolling(window=window, min_periods=window).mean()


def compute_ema(series: pd.Series, span: int) -> pd.Series:
    """Calculate Exponential Moving Average (EMA).

    Args:
        series: Input price or value series.
        span: EMA span length (>= 1).
    """
    if span < 1:
        msg = f"EMA span must be >= 1, got {span}"
        raise ValueError(msg)
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def compute_macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Calculate Moving Average Convergence Divergence (MACD).

    Args:
        close: Closing price series.
        fast: Fast EMA period (default: 12).
        slow: Slow EMA period (default: 26).
        signal: Signal line EMA period (default: 9).

    Returns:
        Tuple of (macd_line, signal_line, histogram).
    """
    if fast >= slow:
        msg = f"Fast span ({fast}) must be strictly less than slow span ({slow})"
        raise ValueError(msg)

    fast_ema = compute_ema(close, span=fast)
    slow_ema = compute_ema(close, span=slow)
    macd_line = fast_ema - slow_ema
    signal_line = compute_ema(macd_line, span=signal)
    histogram = macd_line - signal_line

    return macd_line, signal_line, histogram


def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Calculate Relative Strength Index (RSI) with Wilder's smoothing.

    Args:
        close: Closing price series.
        period: RSI period length (default: 14).
    """
    if period < 1:
        msg = f"RSI period must be >= 1, got {period}"
        raise ValueError(msg)

    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    # Wilder's exponential smoothing (alpha = 1 / period)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))

    # Where avg_loss is 0 and avg_gain > 0, RSI is 100; where both are 0, RSI is 50
    fallback = pd.Series(
        np.where(avg_gain > 0.0, 100.0, np.where(avg_loss > 0.0, 0.0, 50.0)),
        index=close.index,
    )
    rsi = rsi.fillna(fallback)
    # Mask warmup period
    rsi.iloc[:period] = np.nan
    return rsi


def compute_bollinger_bands(
    close: pd.Series,
    window: int = 20,
    num_std: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    """Calculate Bollinger Bands (middle, upper, lower, bandwidth, percent_b).

    Args:
        close: Closing price series.
        window: Moving average window (default: 20).
        num_std: Multiplier for standard deviation (default: 2.0).

    Returns:
        Tuple of (middle_band, upper_band, lower_band, bandwidth, percent_b).
    """
    if window < 2:
        msg = f"Bollinger Bands window must be >= 2, got {window}"
        raise ValueError(msg)

    middle_band = compute_sma(close, window=window)
    rolling_std = close.rolling(window=window, min_periods=window).std()

    upper_band = middle_band + (rolling_std * num_std)
    lower_band = middle_band - (rolling_std * num_std)

    band_range = (upper_band - lower_band).replace(0.0, np.nan)
    bandwidth = (upper_band - lower_band) / middle_band.replace(0.0, np.nan)
    percent_b = (close - lower_band) / band_range

    return middle_band, upper_band, lower_band, bandwidth, percent_b


def compute_atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """Calculate Average True Range (ATR) with Wilder's smoothing.

    Args:
        high: High price series.
        low: Low price series.
        close: Close price series.
        period: ATR period (default: 14).
    """
    if period < 1:
        msg = f"ATR period must be >= 1, got {period}"
        raise ValueError(msg)

    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()

    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return true_range.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def compute_adx(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Calculate Average Directional Index (ADX), +DI, and -DI.

    Args:
        high: High price series.
        low: Low price series.
        close: Close price series.
        period: ADX smoothing period (default: 14).

    Returns:
        Tuple of (adx, plus_di, minus_di).
    """
    if period < 1:
        msg = f"ADX period must be >= 1, got {period}"
        raise ValueError(msg)

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    atr = compute_atr(high, low, close, period=period)
    atr_safe = atr.replace(0.0, np.nan)

    alpha = 1.0 / period
    smooth_plus_dm = (
        pd.Series(plus_dm, index=high.index)
        .ewm(alpha=alpha, adjust=False, min_periods=period)
        .mean()
    )
    smooth_minus_dm = (
        pd.Series(minus_dm, index=low.index)
        .ewm(alpha=alpha, adjust=False, min_periods=period)
        .mean()
    )

    plus_di = 100.0 * (smooth_plus_dm / atr_safe)
    minus_di = 100.0 * (smooth_minus_dm / atr_safe)

    di_sum = (plus_di + minus_di).replace(0.0, np.nan)
    dx = 100.0 * ((plus_di - minus_di).abs() / di_sum)

    adx = dx.ewm(alpha=alpha, adjust=False, min_periods=period).mean()

    return adx, plus_di, minus_di


def compute_stochastic(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    k_period: int = 14,
    d_period: int = 3,
) -> tuple[pd.Series, pd.Series]:
    """Calculate Fast and Slow Stochastic Oscillators (%K, %D).

    Args:
        high: High price series.
        low: Low price series.
        close: Close price series.
        k_period: Lookback period for %K (default: 14).
        d_period: Moving average period for %D (default: 3).

    Returns:
        Tuple of (stoch_k, stoch_d).
    """
    rolling_low = low.rolling(window=k_period, min_periods=k_period).min()
    rolling_high = high.rolling(window=k_period, min_periods=k_period).max()

    price_range = (rolling_high - rolling_low).replace(0.0, np.nan)
    stoch_k = 100.0 * ((close - rolling_low) / price_range)
    stoch_d = stoch_k.rolling(window=d_period, min_periods=d_period).mean()

    return stoch_k, stoch_d


def compute_roc(close: pd.Series, period: int = 10) -> pd.Series:
    """Calculate Rate-of-Change (ROC) percentage.

    Args:
        close: Close price series.
        period: Shift period (default: 10).
    """
    if period < 1:
        msg = f"ROC period must be >= 1, got {period}"
        raise ValueError(msg)
    shifted = close.shift(period).replace(0.0, np.nan)
    return 100.0 * ((close - shifted) / shifted)


def compute_rolling_zscore(close: pd.Series, window: int = 20) -> pd.Series:
    """Calculate Rolling Z-Score of price relative to moving mean.

    Args:
        close: Close price series.
        window: Rolling window length (default: 20).
    """
    mean = compute_sma(close, window=window)
    std = close.rolling(window=window, min_periods=window).std().replace(0.0, np.nan)
    return (close - mean) / std


def compute_rolling_volatility(close: pd.Series, window: int = 20) -> pd.Series:
    """Calculate Rolling Standard Deviation of percentage returns.

    Args:
        close: Close price series.
        window: Return lookback window (default: 20).
    """
    returns = close.pct_change()
    return returns.rolling(window=window, min_periods=window).std()


def compute_volume_features(
    volume: pd.Series,
    window: int = 20,
) -> tuple[pd.Series, pd.Series]:
    """Calculate Volume SMA and relative Volume Ratio.

    Args:
        volume: Traded volume series.
        window: Moving average window (default: 20).

    Returns:
        Tuple of (volume_sma, volume_ratio).
    """
    vol_sma = compute_sma(volume.astype(float), window=window)
    vol_ratio = volume / vol_sma.replace(0.0, np.nan)
    return vol_sma, vol_ratio


def compute_all_technical_features(df: pd.DataFrame) -> pd.DataFrame:
    """Enrich an OHLCV DataFrame with all standard technical indicators.

    Expected columns: 'open', 'high', 'low', 'close', 'volume' (case-insensitive).

    Returns:
        New enriched DataFrame containing all computed technical indicators.
    """
    # Normalize column names to lowercase
    data = df.copy()
    data.columns = pd.Index([str(c).lower() for c in data.columns])

    close = data["close"].astype(float)
    high = data["high"].astype(float)
    low = data["low"].astype(float)
    volume = data["volume"].astype(float)

    # 1. Trend indicators
    for w in (5, 10, 20, 50, 200):
        data[f"sma_{w}"] = compute_sma(close, window=w)
        data[f"ema_{w}"] = compute_ema(close, span=w)

    macd_line, macd_signal, macd_hist = compute_macd(close)
    data["macd_line"] = macd_line
    data["macd_signal"] = macd_signal
    data["macd_hist"] = macd_hist

    adx, plus_di, minus_di = compute_adx(high, low, close)
    data["adx_14"] = adx
    data["plus_di_14"] = plus_di
    data["minus_di_14"] = minus_di

    # 2. Momentum indicators
    data["rsi_14"] = compute_rsi(close, period=14)
    data["roc_10"] = compute_roc(close, period=10)
    stoch_k, stoch_d = compute_stochastic(high, low, close)
    data["stoch_k"] = stoch_k
    data["stoch_d"] = stoch_d

    # 3. Mean-Reversion & Volatility indicators
    bb_mid, bb_upper, bb_lower, bb_width, bb_pct_b = compute_bollinger_bands(close)
    data["bb_middle"] = bb_mid
    data["bb_upper"] = bb_upper
    data["bb_lower"] = bb_lower
    data["bb_bandwidth"] = bb_width
    data["bb_percent_b"] = bb_pct_b

    data["zscore_20"] = compute_rolling_zscore(close, window=20)
    data["atr_14"] = compute_atr(high, low, close, period=14)
    data["volatility_20"] = compute_rolling_volatility(close, window=20)

    # 4. Volume indicators
    vol_sma, vol_ratio = compute_volume_features(volume, window=20)
    data["volume_sma_20"] = vol_sma
    data["volume_ratio_20"] = vol_ratio

    return data
