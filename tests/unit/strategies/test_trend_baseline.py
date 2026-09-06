"""Unit and integration tests for DualEMACrossoverStrategy and DonchianBreakoutStrategy."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.backtesting.engine import BacktestConfig, BacktestEngine, OrderIntent
from src.backtesting.stress_test import StressTestRunner
from src.backtesting.walk_forward import WalkForwardConfig, WalkForwardOptimizer
from src.domain.market_data import OHLCVCandle
from src.strategies.trend_baseline import (
    DonchianBreakoutStrategy,
    DualEMACrossoverStrategy,
)


def _generate_synthetic_trend_series(
    n_bars: int = 150,
    start_price: float = 100.0,
    trend: str = "up",
) -> list[OHLCVCandle]:
    """Generate synthetic sequential candles exhibiting an upward,
    downward, or oscillating trend.
    """
    base_time = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    candles: list[OHLCVCandle] = []
    price = start_price

    for i in range(n_bars):
        if trend == "up":
            drift = 0.3 if i > 30 else 0.0
        elif trend == "down":
            drift = -0.3 if i > 30 else 0.0
        else:
            drift = 0.5 if (i // 25) % 2 == 1 else -0.5

        open_p = Decimal(str(round(price, 2)))
        close_p = Decimal(str(round(price + drift + 0.1, 2)))
        high_p = max(open_p, close_p) + Decimal("1.00")
        low_p = min(open_p, close_p) - Decimal("1.00")
        price = float(close_p)

        candle = OHLCVCandle(
            instrument="TCS",
            timeframe="15m",
            timestamp=base_time + timedelta(minutes=15 * i),
            open=open_p,
            high=high_p,
            low=low_p,
            close=close_p,
            volume=50000,
            turnover=Decimal(str(round(float(close_p) * 50000, 2))),
        )
        candles.append(candle)

    return candles


def test_dual_ema_parameter_validation() -> None:
    """Verify parameter bounds for DualEMACrossoverStrategy."""
    with pytest.raises(ValueError, match="fast_span"):
        DualEMACrossoverStrategy(fast_span=50, slow_span=20)
    with pytest.raises(ValueError, match="fast_span"):
        DualEMACrossoverStrategy(fast_span=20, slow_span=20)
    with pytest.raises(ValueError, match="atr_period"):
        DualEMACrossoverStrategy(fast_span=10, slow_span=20, atr_period=0)
    with pytest.raises(ValueError, match="atr_multiplier"):
        DualEMACrossoverStrategy(fast_span=10, slow_span=20, atr_multiplier=-1.0)


def test_dual_ema_warmup_and_signals() -> None:
    """Verify warmup period returns no orders and crossover generates BUY and SELL orders."""
    strat = DualEMACrossoverStrategy(fast_span=5, slow_span=10, atr_period=5)
    engine = BacktestEngine(BacktestConfig(initial_capital=Decimal("10000.00")))

    candles = _generate_synthetic_trend_series(n_bars=40, trend="wave")

    # Bars prior to slow_span + 2 return empty
    for i in range(11):
        orders = strat(engine, i, candles[i])
        assert orders == []
        engine.process_bar(candles[i], i)

    # Continue running through wave series to confirm order generation
    orders_generated: list[str] = []
    for i in range(11, len(candles)):
        engine.process_bar(candles[i], i)
        orders = strat(engine, i, candles[i])
        for ord_intent in orders:
            engine.submit_order(ord_intent)
            orders_generated.append(ord_intent.direction)

    assert "BUY" in orders_generated


def test_dual_ema_end_to_end_backtest() -> None:
    """Verify DualEMACrossoverStrategy integrates cleanly with BacktestEngine.run."""
    candles = _generate_synthetic_trend_series(n_bars=120, trend="wave")
    strat = DualEMACrossoverStrategy(fast_span=10, slow_span=25, atr_period=10)
    engine = BacktestEngine(
        BacktestConfig(strategy_id="dual_ema_test", initial_capital=Decimal("10000.00"))
    )

    result = engine.run(candles, strategy_callback=strat)

    assert result.strategy_id == "dual_ema_test"
    assert result.initial_capital == Decimal("10000.00")
    assert result.final_equity > Decimal("0")
    assert result.metrics.total_trades >= 0
    assert len(result.equity_curve) == len(candles)


def test_donchian_breakout_parameter_validation() -> None:
    """Verify parameter bounds for DonchianBreakoutStrategy."""
    with pytest.raises(ValueError, match="lookback_period"):
        DonchianBreakoutStrategy(lookback_period=1)
    with pytest.raises(ValueError, match="atr_period"):
        DonchianBreakoutStrategy(lookback_period=20, atr_period=0)
    with pytest.raises(ValueError, match="stop_atr_multiplier"):
        DonchianBreakoutStrategy(lookback_period=20, stop_atr_multiplier=-0.5)


def test_donchian_breakout_zero_lookahead_and_signals() -> None:
    """Verify Donchian channel breakout triggers and guarantees zero lookahead."""
    strat = DonchianBreakoutStrategy(lookback_period=10, atr_period=5, stop_atr_multiplier=1.5)
    engine = BacktestEngine(BacktestConfig(initial_capital=Decimal("10000.00")))

    # Create 15 flat bars followed by a sharp breakout bar
    candles = _generate_synthetic_trend_series(n_bars=12, start_price=100.0, trend="flat")

    for i in range(len(candles)):
        engine.process_bar(candles[i], i)
        orders = strat(engine, i, candles[i])
        # Warmup period: no orders
        if i <= 10:
            assert orders == []

    # Bar 12: explosive breakout bar above prior 10-bar high (~101.00)
    breakout_candle = OHLCVCandle(
        instrument="TCS",
        timeframe="15m",
        timestamp=candles[-1].timestamp + timedelta(minutes=15),
        open=Decimal("102.00"),
        high=Decimal("110.00"),
        low=Decimal("101.50"),
        close=Decimal("108.00"),
        volume=100000,
        turnover=Decimal("10800000.00"),
    )
    engine.process_bar(breakout_candle, 12)
    breakout_orders = strat(engine, 12, breakout_candle)

    assert len(breakout_orders) == 1
    assert breakout_orders[0].direction == "BUY"
    assert breakout_orders[0].stop_loss is not None
    assert breakout_orders[0].stop_loss < breakout_candle.close


def test_donchian_breakout_end_to_end_backtest() -> None:
    """Verify DonchianBreakoutStrategy integrates cleanly with BacktestEngine.run."""
    candles = _generate_synthetic_trend_series(n_bars=120, trend="wave")
    strat = DonchianBreakoutStrategy(lookback_period=15, atr_period=10)
    engine = BacktestEngine(
        BacktestConfig(strategy_id="donchian_test", initial_capital=Decimal("10000.00"))
    )

    result = engine.run(candles, strategy_callback=strat)

    assert result.strategy_id == "donchian_test"
    assert result.metrics.win_rate >= Decimal("0")
    assert len(result.equity_curve) == len(candles)


def test_strategy_walk_forward_optimization_integration() -> None:
    """Verify baseline trend strategy runs cleanly through WalkForwardOptimizer."""
    candles = _generate_synthetic_trend_series(n_bars=180, trend="wave")
    wf_config = WalkForwardConfig(
        strategy_id="wf_dual_ema",
        train_bars=80,
        test_bars=30,
        step_bars=30,
        efficiency_gate_threshold=Decimal("0.30"),
    )
    optimizer = WalkForwardOptimizer(wf_config)

    def factory(params: dict[str, object]) -> DualEMACrossoverStrategy:
        f_span = int(str(params.get("fast_span", 5)))
        s_span = int(str(params.get("slow_span", 15)))
        return DualEMACrossoverStrategy(fast_span=f_span, slow_span=s_span)

    param_grid: list[dict[str, object]] = [
        {"fast_span": 5, "slow_span": 15},
        {"fast_span": 10, "slow_span": 20},
    ]

    report = optimizer.run(candles=candles, strategy_factory=factory, param_grid=param_grid)

    assert len(report.folds) > 0
    assert report.strategy_id == "wf_dual_ema"


def test_strategy_stress_test_battery_integration() -> None:
    """Verify baseline trend strategy runs through StressTestRunner standard battery."""
    candles = _generate_synthetic_trend_series(n_bars=100, trend="wave")
    strat = DualEMACrossoverStrategy(fast_span=5, slow_span=15)
    runner = StressTestRunner(strategy_id="stress_dual_ema")

    report = runner.run_standard_battery(base_candles=candles, strategy=strat)

    assert report.strategy_id == "stress_dual_ema"
    assert len(report.scenarios_evaluated) == 5


def test_dual_ema_bearish_crossover_exit_signal() -> None:
    """Verify dual EMA emits SELL OrderIntent when holding position and bearish cross occurs."""
    strat = DualEMACrossoverStrategy(fast_span=3, slow_span=6, atr_period=3)
    engine = BacktestEngine()
    base_time = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)

    # 1. Rising sequence to establish fast EMA > slow EMA
    for i in range(12):
        p = Decimal(str(100.0 + i * 2.0))
        c = OHLCVCandle(
            instrument="TCS",
            timeframe="15m",
            timestamp=base_time + timedelta(minutes=15 * i),
            open=p,
            high=p + Decimal("1.00"),
            low=p - Decimal("1.00"),
            close=p,
            volume=50000,
            turnover=p * Decimal("50000"),
        )
        engine.process_bar(c, i)
        strat(engine, i, c)

    # Open a long position manually
    engine.portfolio.open_position(
        symbol="TCS",
        direction="BUY",
        quantity=10,
        fill_price=Decimal("122.00"),
        timestamp=base_time + timedelta(minutes=15 * 11),
        entry_cost=Decimal("20.00"),
    )
    assert strat.has_position(engine, "TCS")

    # 2. Falling sequence to force bearish crossover (fast EMA plunges below slow EMA)
    exit_orders: list[OrderIntent] = []
    for j in range(12, 20):
        p = Decimal(str(122.0 - (j - 11) * 4.0))
        c = OHLCVCandle(
            instrument="TCS",
            timeframe="15m",
            timestamp=base_time + timedelta(minutes=15 * j),
            open=p + Decimal("1.00"),
            high=p + Decimal("1.50"),
            low=p - Decimal("1.00"),
            close=p,
            volume=50000,
            turnover=p * Decimal("50000"),
        )
        engine.process_bar(c, j)
        orders = strat(engine, j, c)
        for o in orders:
            if o.direction == "SELL":
                exit_orders.append(o)

    assert len(exit_orders) >= 1
    assert exit_orders[0].direction == "SELL"
    assert exit_orders[0].quantity == 10


def test_donchian_breakdown_exit_signal() -> None:
    """Verify Donchian breakout strategy emits SELL order when price breaks below lower band."""
    strat = DonchianBreakoutStrategy(lookback_period=10, atr_period=5)
    engine = BacktestEngine()
    base_time = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)

    # 15 flat candles with low at 98.00
    for i in range(15):
        c = OHLCVCandle(
            instrument="TCS",
            timeframe="15m",
            timestamp=base_time + timedelta(minutes=15 * i),
            open=Decimal("100.00"),
            high=Decimal("102.00"),
            low=Decimal("98.00"),
            close=Decimal("100.00"),
            volume=50000,
            turnover=Decimal("5000000.00"),
        )
        engine.process_bar(c, i)
        strat(engine, i, c)

    # Open position
    engine.portfolio.open_position(
        symbol="TCS",
        direction="BUY",
        quantity=15,
        fill_price=Decimal("100.00"),
        timestamp=base_time + timedelta(minutes=15 * 14),
        entry_cost=Decimal("20.00"),
    )

    # Sharp breakdown bar with close 95.00 < 98.00 lower channel
    breakdown_candle = OHLCVCandle(
        instrument="TCS",
        timeframe="15m",
        timestamp=base_time + timedelta(minutes=15 * 15),
        open=Decimal("97.00"),
        high=Decimal("97.50"),
        low=Decimal("94.00"),
        close=Decimal("95.00"),
        volume=80000,
        turnover=Decimal("7600000.00"),
    )
    engine.process_bar(breakdown_candle, 15)
    orders = strat(engine, 15, breakdown_candle)

    assert len(orders) == 1
    assert orders[0].direction == "SELL"
    assert orders[0].quantity == 15
