"""Unit tests for stress testing scenarios and StressTestRunner (BTD §8.4, RTLD §11)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.backtesting.engine import BacktestEngine, OrderIntent
from src.backtesting.slippage_model import SlippageConfig
from src.backtesting.stress_scenarios import (
    create_covid_crash_scenario,
    create_slippage_stress_config,
    generate_feed_dropout,
    generate_gap_down_shock,
    generate_volatility_spike,
)
from src.backtesting.stress_test import StressTestRunner
from src.domain.market_data import OHLCVCandle


def _generate_candles(count: int = 25) -> list[OHLCVCandle]:
    base_time = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    candles = []
    price = Decimal("100.00")
    for i in range(count):
        t = base_time + timedelta(minutes=15 * i)
        c = OHLCVCandle(
            instrument="TCS",
            timeframe="15m",
            timestamp=t,
            open=price,
            high=price + Decimal("2.00"),
            low=price - Decimal("2.00"),
            close=price + Decimal("0.50"),
            volume=50_000,
            turnover=(price * Decimal("50000.00")).quantize(Decimal("0.01")),
        )
        candles.append(c)
        price += Decimal("0.50")
    return candles


def test_generate_gap_down_shock_success_and_validations() -> None:
    """Verify gap down injection and input validation."""
    candles = _generate_candles(15)

    # Valid 5% gap at bar 5
    shrunk = generate_gap_down_shock(candles, gap_pct=Decimal("0.05"), bar_index=5)
    assert len(shrunk) == 15
    assert shrunk[4].close == candles[4].close
    assert shrunk[5].open < candles[5].open
    assert shrunk[5].open == (candles[5].open * Decimal("0.95")).quantize(Decimal("0.01"))

    # Empty candles
    with pytest.raises(ValueError, match="cannot be empty"):
        generate_gap_down_shock([], gap_pct=Decimal("0.05"))

    # Invalid gap_pct
    with pytest.raises(ValueError, match=r"between 0 and 1\.0"):
        generate_gap_down_shock(candles, gap_pct=Decimal("0.0"))

    with pytest.raises(ValueError, match=r"between 0 and 1\.0"):
        generate_gap_down_shock(candles, gap_pct=Decimal("1.5"))

    # Bar index out of bounds
    with pytest.raises(ValueError, match="out of bounds"):
        generate_gap_down_shock(candles, bar_index=20)


def test_generate_volatility_spike_success_and_validations() -> None:
    """Verify volatility range multiplication and parameter checks."""
    candles = _generate_candles(15)

    # Valid 3x volatility spike between bar 4 and 8
    spiked = generate_volatility_spike(candles, multiplier=Decimal("3.0"), start_idx=4, end_idx=8)
    assert len(spiked) == 15
    assert (spiked[5].high - spiked[5].low) > (candles[5].high - candles[5].low)

    # Default end_idx
    spiked_all = generate_volatility_spike(candles, multiplier=Decimal("2.0"), start_idx=0)
    assert len(spiked_all) == 15

    # Empty candles
    with pytest.raises(ValueError, match="cannot be empty"):
        generate_volatility_spike([], multiplier=Decimal("2.0"))

    # Multiplier <= 1.0
    with pytest.raises(ValueError, match=r"greater than 1\.0"):
        generate_volatility_spike(candles, multiplier=Decimal("1.0"))

    # Invalid window
    with pytest.raises(ValueError, match="Invalid shock window"):
        generate_volatility_spike(candles, start_idx=10, end_idx=5)


def test_generate_feed_dropout_success_and_validations() -> None:
    """Verify simulated feed dropout and sequence length constraints."""
    candles = _generate_candles(15)

    # Drop 3 bars starting at bar 5
    dropped = generate_feed_dropout(candles, dropout_bars=3, start_idx=5)
    assert len(dropped) == 12
    # Bar 5 in new series corresponds to old bar 8
    assert dropped[5].timestamp == candles[8].timestamp

    # Empty candles
    with pytest.raises(ValueError, match="cannot be empty"):
        generate_feed_dropout([], dropout_bars=2, start_idx=0)

    # Non-positive dropout bars
    with pytest.raises(ValueError, match="strictly positive"):
        generate_feed_dropout(candles, dropout_bars=0, start_idx=2)

    # Start idx out of bounds
    with pytest.raises(ValueError, match="out of bounds"):
        generate_feed_dropout(candles, dropout_bars=2, start_idx=20)

    # Too many bars dropped
    with pytest.raises(ValueError, match="at least 2"):
        generate_feed_dropout(candles, dropout_bars=14, start_idx=0)


def test_create_slippage_stress_config() -> None:
    """Verify 4x slippage stress scaling."""
    base = SlippageConfig(
        base_slippage_bps=5.0,
        spread_proxy_pct=0.0005,
        tier3_multiplier=4.0,
    )
    stressed = create_slippage_stress_config(base, multiplier=4.0)
    assert stressed.base_slippage_bps == 20.0
    assert stressed.spread_proxy_pct == 0.0020
    assert stressed.tier3_multiplier == 16.0


def test_create_covid_crash_scenario_success_and_validations() -> None:
    """Verify COVID crash scenario generation and length constraints."""
    covid_candles = create_covid_crash_scenario(
        instrument="NIFTY50", start_price=Decimal("10000.00"), bars=25
    )
    assert len(covid_candles) == 25
    assert covid_candles[-1].close < covid_candles[0].close

    with pytest.raises(ValueError, match="at least 10"):
        create_covid_crash_scenario(bars=5)


def test_stress_test_runner_single_scenario_and_breach() -> None:
    """Verify StressTestRunner evaluates drawdown and flags 8% halt and 10% kill switch."""
    runner = StressTestRunner(
        strategy_id="crash_buyer",
        initial_capital=Decimal("10000.00"),
        halt_threshold_pct=Decimal("8.00"),
        kill_switch_threshold_pct=Decimal("10.00"),
    )

    # COVID scenario will cause large drawdown for a naive long buyer
    covid_candles = create_covid_crash_scenario(start_price=Decimal("1000.00"), bars=20)

    def aggressive_buyer(
        eng: BacktestEngine, bar_idx: int, candle: OHLCVCandle
    ) -> list[OrderIntent]:
        # Buy 9 shares on bar 0 (~₹9,000 exposure on ₹10,000 capital)
        if bar_idx == 0 and len(eng.portfolio.positions) == 0:
            return [
                OrderIntent(
                    symbol=candle.instrument,
                    direction="BUY",
                    quantity=9,
                    generated_at_bar_index=bar_idx,
                    generated_at_time=candle.timestamp,
                )
            ]
        return []

    res = runner.evaluate_scenario(
        scenario_name="COVID_CRASH",
        scenario_type="HISTORICAL",
        description="Severe collapse test",
        candles=covid_candles,
        strategy=aggressive_buyer,
    )

    assert res.scenario_name == "COVID_CRASH"
    assert res.scenario_type == "HISTORICAL"
    assert res.return_pct < Decimal("0")
    # A ~30% index drop on ~90% exposure causes >10% drawdown
    assert res.max_drawdown_pct >= Decimal("10.00")
    assert res.halt_8pct_breached is True
    assert res.kill_switch_10pct_breached is True


def test_stress_test_runner_standard_battery() -> None:
    """Verify standard 5-scenario battery execution and report assembly."""
    runner = StressTestRunner(strategy_id="safe_strategy", initial_capital=Decimal("10000.00"))
    base_candles = _generate_candles(25)

    def empty_strategy(_e: BacktestEngine, _b: int, _c: OHLCVCandle) -> list[OrderIntent]:
        return []

    report = runner.run_standard_battery(base_candles, empty_strategy)
    assert len(report.scenarios_evaluated) == 5
    assert report.worst_drawdown_pct == Decimal("0.00")
    assert report.passed_stress_test is True
    assert "Evaluated 5 stress scenarios" in report.summary

    # Insufficient candles
    short_candles = _generate_candles(10)
    with pytest.raises(ValueError, match="Minimum 20 candles"):
        runner.run_standard_battery(short_candles, empty_strategy)
