"""Stress testing scenario definitions and synthetic shock generators (BTD §8.4, RTLD §11)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from src.backtesting.slippage_model import SlippageConfig
from src.domain.market_data import OHLCVCandle


def generate_gap_down_shock(
    candles: list[OHLCVCandle],
    gap_pct: Decimal = Decimal("0.05"),
    bar_index: int = 10,
) -> list[OHLCVCandle]:
    """Inject a sudden overnight opening gap down into candle series.

    Args:
        candles: Source chronological candle list.
        gap_pct: Fraction to gap down (e.g. 0.05 for 5% drop).
        bar_index: Bar index at which gap occurs.

    Returns:
        New candle list with opening gap down applied to bar_index and subsequent bars.
    """
    if not candles:
        msg = "Candle sequence cannot be empty"
        raise ValueError(msg)
    if not (Decimal("0") < gap_pct < Decimal("1.0")):
        msg = f"gap_pct must be between 0 and 1.0, got {gap_pct}"
        raise ValueError(msg)
    if not (0 <= bar_index < len(candles)):
        msg = f"bar_index {bar_index} out of bounds for sequence length {len(candles)}"
        raise ValueError(msg)

    scale = Decimal("1.0") - gap_pct
    mutated: list[OHLCVCandle] = []

    for i, c in enumerate(candles):
        if i < bar_index:
            mutated.append(c)
        else:
            new_open = (c.open * scale).quantize(Decimal("0.01"))
            new_high = (c.high * scale).quantize(Decimal("0.01"))
            new_low = (c.low * scale).quantize(Decimal("0.01"))
            new_close = (c.close * scale).quantize(Decimal("0.01"))
            mutated.append(
                OHLCVCandle(
                    instrument=c.instrument,
                    timeframe=c.timeframe,
                    timestamp=c.timestamp,
                    open=new_open,
                    high=new_high,
                    low=new_low,
                    close=new_close,
                    volume=c.volume,
                    turnover=(new_close * Decimal(str(c.volume))).quantize(Decimal("0.01")),
                    quality_state=c.quality_state,
                )
            )
    return mutated


def generate_volatility_spike(
    candles: list[OHLCVCandle],
    multiplier: Decimal = Decimal("3.0"),
    start_idx: int = 5,
    end_idx: int | None = None,
) -> list[OHLCVCandle]:
    """Multiply intraday high-low range by a factor (e.g. 3x) to simulate extreme volatility.

    Args:
        candles: Source candle list.
        multiplier: Range multiplier (e.g. 3.0 for 3x spike).
        start_idx: Starting bar index for shock window.
        end_idx: Ending bar index for shock window (inclusive). Defaults to end of sequence.

    Returns:
        New candle list with expanded high-low swings.
    """
    if not candles:
        msg = "Candle sequence cannot be empty"
        raise ValueError(msg)
    if multiplier <= Decimal("1.0"):
        msg = f"multiplier must be greater than 1.0, got {multiplier}"
        raise ValueError(msg)

    stop = len(candles) if end_idx is None else min(len(candles), end_idx + 1)
    if not (0 <= start_idx < stop):
        msg = f"Invalid shock window: start={start_idx}, stop={stop}"
        raise ValueError(msg)

    mutated: list[OHLCVCandle] = []

    for i, c in enumerate(candles):
        if start_idx <= i < stop:
            mid = (c.high + c.low) / Decimal("2")
            half_range = ((c.high - c.low) / Decimal("2")) * multiplier
            new_high = (mid + half_range).quantize(Decimal("0.01"))
            new_low = max(Decimal("0.05"), (mid - half_range).quantize(Decimal("0.01")))
            new_open = min(new_high, max(new_low, c.open))
            new_close = min(new_high, max(new_low, c.close))
            mutated.append(
                OHLCVCandle(
                    instrument=c.instrument,
                    timeframe=c.timeframe,
                    timestamp=c.timestamp,
                    open=new_open,
                    high=new_high,
                    low=new_low,
                    close=new_close,
                    volume=c.volume * int(multiplier),
                    turnover=(new_close * Decimal(str(c.volume * int(multiplier)))).quantize(
                        Decimal("0.01")
                    ),
                    quality_state=c.quality_state,
                )
            )
        else:
            mutated.append(c)

    return mutated


def generate_feed_dropout(
    candles: list[OHLCVCandle],
    dropout_bars: int = 5,
    start_idx: int = 10,
) -> list[OHLCVCandle]:
    """Simulate missing broker quotes / network dropout by removing consecutive bars.

    Args:
        candles: Source candle list.
        dropout_bars: Number of consecutive bars dropped.
        start_idx: Starting bar index for blackout window.

    Returns:
        Candle list with specified bars omitted.
    """
    if not candles:
        msg = "Candle sequence cannot be empty"
        raise ValueError(msg)
    if dropout_bars <= 0:
        msg = f"dropout_bars must be strictly positive, got {dropout_bars}"
        raise ValueError(msg)
    if not (0 <= start_idx < len(candles)):
        msg = f"start_idx {start_idx} out of bounds for sequence length {len(candles)}"
        raise ValueError(msg)
    if len(candles) - dropout_bars < 2:
        msg = (
            f"Remaining candles after dropout must be at least 2, got {len(candles) - dropout_bars}"
        )
        raise ValueError(msg)

    return candles[:start_idx] + candles[start_idx + dropout_bars :]


def create_slippage_stress_config(
    base_config: SlippageConfig | None = None,
    multiplier: float = 4.0,
) -> SlippageConfig:
    """Produce an adverse slippage configuration simulating dried liquidity and wide spreads."""
    base = base_config or SlippageConfig()
    return SlippageConfig(
        base_slippage_bps=base.base_slippage_bps * multiplier,
        spread_proxy_pct=base.spread_proxy_pct * multiplier,
        tier1_threshold=base.tier1_threshold,
        tier2_threshold=base.tier2_threshold,
        tier1_multiplier=base.tier1_multiplier,
        tier2_multiplier=base.tier2_multiplier,
        tier3_multiplier=base.tier3_multiplier * multiplier,
        reject_above_tier2=base.reject_above_tier2,
    )


def create_covid_crash_scenario(
    instrument: str = "NIFTY50",
    start_price: Decimal = Decimal("12000.00"),
    bars: int = 60,
) -> list[OHLCVCandle]:
    """Generate synthetic March 2020 COVID shock period (cascading crash, circuit breakers).

    Simulates a rapid cumulative ~30% market collapse with expanding volatility.
    """
    if bars < 10:
        msg = f"bars must be at least 10 for COVID crash scenario, got {bars}"
        raise ValueError(msg)

    candles: list[OHLCVCandle] = []
    base_time = datetime(2020, 3, 2, 9, 15, tzinfo=UTC)
    price = start_price

    for i in range(bars):
        t = base_time + timedelta(minutes=15 * i)
        # First 10 bars stable, next 30 bars severe collapse (-1.2%/bar),
        # last 20 bars volatile bottom
        if i < 10:
            step_pct = Decimal("0.0005")
            range_pct = Decimal("0.005")
        elif i < 40:
            step_pct = Decimal("-0.012")  # Heavy cascading selloff
            range_pct = Decimal("0.025")  # Wide erratic swings
        else:
            step_pct = Decimal("0.001")  # Volatile consolidation
            range_pct = Decimal("0.020")

        open_p = (price + (price * step_pct * Decimal("0.5"))).quantize(Decimal("0.05"))
        close_p = (price + (price * step_pct)).quantize(Decimal("0.05"))
        high_p = (max(open_p, close_p) + (price * range_pct)).quantize(Decimal("0.05"))
        low_p = (min(open_p, close_p) - (price * range_pct)).quantize(Decimal("0.05"))
        price = max(Decimal("100.00"), close_p)

        vol = 250_000 if i < 10 else 750_000  # High panic volume during collapse
        candles.append(
            OHLCVCandle(
                instrument=instrument,
                timeframe="15m",
                timestamp=t,
                open=open_p,
                high=high_p,
                low=low_p,
                close=close_p,
                volume=vol,
                turnover=(close_p * Decimal(str(vol))).quantize(Decimal("0.01")),
            )
        )

    return candles
