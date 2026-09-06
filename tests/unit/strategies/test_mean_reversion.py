"""Unit and integration tests for BollingerBandsRSIMeanReversionStrategy."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.backtesting.engine import BacktestConfig, BacktestEngine
from src.backtesting.stress_test import StressTestRunner
from src.backtesting.walk_forward import WalkForwardConfig, WalkForwardOptimizer
from src.domain.market_data import OHLCVCandle
from src.strategies.mean_reversion_baseline import (
    BollingerBandsRSIMeanReversionStrategy,
)


def _generate_synthetic_oscillating_series(
    n_bars: int = 150,
    start_price: float = 100.0,
) -> list[OHLCVCandle]:
    """Generate synthetic sequential candles exhibiting mean-reverting wave oscillations."""
    base_time = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    candles: list[OHLCVCandle] = []
    price = start_price

    for i in range(n_bars):
        # Oscillate in 10-bar cycles
        cycle = i % 10
        drift = -1.2 if cycle < 5 else 1.4

        open_p = Decimal(str(round(price, 2)))
        close_p = Decimal(str(round(price + drift, 2)))
        high_p = max(open_p, close_p) + Decimal("0.80")
        low_p = min(open_p, close_p) - Decimal("0.80")
        price = float(close_p)

        candle = OHLCVCandle(
            instrument="TCS",
            timeframe="15m",
            timestamp=base_time + timedelta(minutes=15 * i),
            open=open_p,
            high=high_p,
            low=low_p,
            close=close_p,
            volume=45000,
            turnover=Decimal(str(round(float(close_p) * 45000, 2))),
        )
        candles.append(candle)

    return candles


def test_mean_reversion_parameter_validation() -> None:
    """Verify parameter bounds for BollingerBandsRSIMeanReversionStrategy."""
    with pytest.raises(ValueError, match="bb_window"):
        BollingerBandsRSIMeanReversionStrategy(bb_window=1)
    with pytest.raises(ValueError, match="bb_std"):
        BollingerBandsRSIMeanReversionStrategy(bb_std=0.0)
    with pytest.raises(ValueError, match="rsi_period"):
        BollingerBandsRSIMeanReversionStrategy(rsi_period=0)
    with pytest.raises(ValueError, match="rsi_oversold"):
        BollingerBandsRSIMeanReversionStrategy(rsi_oversold=60.0, rsi_exit=50.0)
    with pytest.raises(ValueError, match="stop_loss_pct"):
        BollingerBandsRSIMeanReversionStrategy(stop_loss_pct=-0.01)


def test_mean_reversion_warmup_and_signals() -> None:
    """Verify strategy respects warmup period and generates BUY on oversold condition."""
    strat = BollingerBandsRSIMeanReversionStrategy(
        bb_window=10,
        bb_std=1.0,
        rsi_period=7,
        rsi_oversold=35.0,
        rsi_exit=55.0,
    )
    engine = BacktestEngine(BacktestConfig(initial_capital=Decimal("10000.00")))
    candles = _generate_synthetic_oscillating_series(n_bars=40)

    # Bars prior to warmup return empty
    for i in range(12):
        orders = strat(engine, i, candles[i])
        assert orders == []
        engine.process_bar(candles[i], i)

    # Run through series and verify orders are generated
    all_orders = []
    for i in range(12, len(candles)):
        engine.process_bar(candles[i], i)
        orders = strat(engine, i, candles[i])
        for o in orders:
            engine.submit_order(o)
            all_orders.append(o)

    assert any(o.direction == "BUY" for o in all_orders)


def test_mean_reversion_exit_signal_on_middle_band() -> None:
    """Verify strategy exits position when price reverts to or above the middle band."""
    strat = BollingerBandsRSIMeanReversionStrategy(
        bb_window=10,
        rsi_period=5,
        rsi_oversold=35.0,
        rsi_exit=50.0,
    )
    engine = BacktestEngine()
    base_time = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)

    # Feed 15 flat/oversold bars
    for i in range(15):
        p = Decimal(str(100.0 - i * 0.5))
        c = OHLCVCandle(
            instrument="TCS",
            timeframe="15m",
            timestamp=base_time + timedelta(minutes=15 * i),
            open=p,
            high=p + Decimal("0.50"),
            low=p - Decimal("0.50"),
            close=p,
            volume=50000,
            turnover=p * Decimal("50000"),
        )
        engine.process_bar(c, i)
        strat(engine, i, c)

    # Open position
    engine.portfolio.open_position(
        symbol="TCS",
        direction="BUY",
        quantity=10,
        fill_price=Decimal("93.00"),
        timestamp=base_time + timedelta(minutes=15 * 14),
        entry_cost=Decimal("20.00"),
    )
    assert strat.has_position(engine, "TCS")

    # Sharp upward surge bar above the middle band
    bounce_candle = OHLCVCandle(
        instrument="TCS",
        timeframe="15m",
        timestamp=base_time + timedelta(minutes=15 * 15),
        open=Decimal("93.00"),
        high=Decimal("105.00"),
        low=Decimal("92.50"),
        close=Decimal("104.00"),
        volume=90000,
        turnover=Decimal("9360000.00"),
    )
    engine.process_bar(bounce_candle, 15)
    orders = strat(engine, 15, bounce_candle)

    assert len(orders) == 1
    assert orders[0].direction == "SELL"
    assert orders[0].quantity == 10


def test_mean_reversion_end_to_end_backtest() -> None:
    """Verify BollingerBandsRSIMeanReversionStrategy runs cleanly in BacktestEngine.run."""
    candles = _generate_synthetic_oscillating_series(n_bars=120)
    strat = BollingerBandsRSIMeanReversionStrategy(
        bb_window=15,
        rsi_period=10,
        rsi_oversold=35.0,
        rsi_exit=50.0,
    )
    engine = BacktestEngine(
        BacktestConfig(strategy_id="mean_rev_test", initial_capital=Decimal("10000.00"))
    )

    result = engine.run(candles, strategy_callback=strat)

    assert result.strategy_id == "mean_rev_test"
    assert result.initial_capital == Decimal("10000.00")
    assert result.final_equity > Decimal("0")
    assert len(result.equity_curve) == len(candles)


def test_mean_reversion_walk_forward_integration() -> None:
    """Verify mean-reversion strategy runs through WalkForwardOptimizer."""
    candles = _generate_synthetic_oscillating_series(n_bars=180)
    wf_config = WalkForwardConfig(
        strategy_id="wf_mean_rev",
        train_bars=80,
        test_bars=30,
        step_bars=30,
        efficiency_gate_threshold=Decimal("0.30"),
    )
    optimizer = WalkForwardOptimizer(wf_config)

    def factory(params: dict[str, object]) -> BollingerBandsRSIMeanReversionStrategy:
        win = int(str(params.get("bb_window", 15)))
        return BollingerBandsRSIMeanReversionStrategy(bb_window=win, rsi_period=7)

    param_grid: list[dict[str, object]] = [
        {"bb_window": 10},
        {"bb_window": 15},
    ]

    report = optimizer.run(candles=candles, strategy_factory=factory, param_grid=param_grid)

    assert len(report.folds) > 0
    assert report.strategy_id == "wf_mean_rev"


def test_mean_reversion_stress_test_integration() -> None:
    """Verify mean-reversion strategy runs through StressTestRunner battery."""
    candles = _generate_synthetic_oscillating_series(n_bars=100)
    strat = BollingerBandsRSIMeanReversionStrategy(bb_window=10, rsi_period=7)
    runner = StressTestRunner(strategy_id="stress_mean_rev")

    report = runner.run_standard_battery(base_candles=candles, strategy=strat)

    assert report.strategy_id == "stress_mean_rev"
    assert len(report.scenarios_evaluated) == 5
