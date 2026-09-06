"""Unit tests for WalkForwardOptimizer and WFER gate enforcement (BTD §8.3, MLD §9.2)."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from src.backtesting.engine import BacktestEngine, OrderIntent
from src.backtesting.walk_forward import WalkForwardConfig, WalkForwardOptimizer
from src.domain.market_data import OHLCVCandle


def _generate_price_series(count: int, trend: float = 1.0) -> list[OHLCVCandle]:
    base_time = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    candles = []
    price = Decimal("100.00")
    for i in range(count):
        t = base_time + timedelta(minutes=15 * i)
        step = Decimal(str(trend)) * Decimal("0.50")
        price = max(Decimal("10.00"), price + step)
        c = OHLCVCandle(
            instrument="TCS",
            timeframe="15m",
            timestamp=t,
            open=price,
            high=price + Decimal("2.00"),
            low=price - Decimal("2.00"),
            close=price + Decimal("0.50"),
            volume=100_000,
            turnover=price * Decimal("100000.00"),
        )
        candles.append(c)
    return candles


def test_walk_forward_passing_gate() -> None:
    """Verify robust persistent strategy achieves WFER >= 0.50 and passes gate."""
    # 50 candles with upward trend: train=20, test=10, step=10 -> 3 folds
    candles = _generate_price_series(50, trend=1.0)

    config = WalkForwardConfig(
        strategy_id="persistent_momentum",
        train_bars=20,
        test_bars=10,
        step_bars=10,
        efficiency_gate_threshold=Decimal("0.50"),
        metric_key="net_profit",
    )
    optimizer = WalkForwardOptimizer(config)

    def persistent_strategy_factory(
        _params: dict[str, Any],
    ) -> Callable[[BacktestEngine, int, OHLCVCandle], list[OrderIntent]]:
        def strategy(eng: BacktestEngine, bar_idx: int, candle: OHLCVCandle) -> list[OrderIntent]:
            # Simple persistent rule: buy on bar 0 of the window if no position
            if bar_idx == 0 and len(eng.portfolio.positions) == 0:
                return [
                    OrderIntent(
                        symbol="TCS",
                        direction="BUY",
                        quantity=5,
                        generated_at_bar_index=bar_idx,
                        generated_at_time=candle.timestamp,
                    )
                ]
            return []

        return strategy

    report = optimizer.run(candles, persistent_strategy_factory)

    assert len(report.folds) == 3
    assert report.strategy_id == "persistent_momentum"
    # Because prices rise consistently across train and test, both IS and OOS are profitable
    assert report.passed_gate is True
    assert report.overfit_flag is False
    assert report.walk_forward_efficiency_ratio >= Decimal("0.50")


def test_walk_forward_failing_gate_overfit() -> None:
    """Verify overfitted strategy fails WFER >= 0.50 gate and triggers overfit_flag."""
    # 50 candles: prices rise in first half (train), but crash in second half (test)
    base_time = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    candles = []
    price = Decimal("100.00")
    for i in range(50):
        t = base_time + timedelta(minutes=15 * i)
        # Upward in train (first 20 bars), severe drop during test (bars 20 to 30)
        step = Decimal("1.00") if (i % 30 < 20) else Decimal("-2.50")
        price = max(Decimal("10.00"), price + step)
        c = OHLCVCandle(
            instrument="TCS",
            timeframe="15m",
            timestamp=t,
            open=price,
            high=price + Decimal("1.00"),
            low=price - Decimal("1.00"),
            close=price,
            volume=100_000,
            turnover=price * Decimal("100000.00"),
        )
        candles.append(c)

    config = WalkForwardConfig(
        strategy_id="overfitted_buyer",
        train_bars=20,
        test_bars=10,
        step_bars=10,
        efficiency_gate_threshold=Decimal("0.50"),
        metric_key="net_profit",
    )
    optimizer = WalkForwardOptimizer(config)

    def buyer_strategy_factory(
        _params: dict[str, Any],
    ) -> Callable[[BacktestEngine, int, OHLCVCandle], list[OrderIntent]]:
        def strategy(eng: BacktestEngine, bar_idx: int, candle: OHLCVCandle) -> list[OrderIntent]:
            if bar_idx == 0 and len(eng.portfolio.positions) == 0:
                return [
                    OrderIntent(
                        symbol="TCS",
                        direction="BUY",
                        quantity=5,
                        generated_at_bar_index=bar_idx,
                        generated_at_time=candle.timestamp,
                    )
                ]
            return []

        return strategy

    report = optimizer.run(candles, buyer_strategy_factory)

    # Strategy loses money out-of-sample due to the crash
    assert report.passed_gate is False
    assert report.overfit_flag is True
    assert report.walk_forward_efficiency_ratio < Decimal("0.50")


def test_walk_forward_parameter_tuning() -> None:
    """Verify in-sample parameter selection chooses best candidate."""
    candles = _generate_price_series(40, trend=1.0)
    config = WalkForwardConfig(
        train_bars=20,
        test_bars=10,
        step_bars=10,
    )
    optimizer = WalkForwardOptimizer(config)

    param_grid = [{"quantity": 1}, {"quantity": 10}]

    def param_strategy_factory(
        params: dict[str, Any],
    ) -> Callable[[BacktestEngine, int, OHLCVCandle], list[OrderIntent]]:
        qty = params.get("quantity", 1)

        def strategy(eng: BacktestEngine, bar_idx: int, candle: OHLCVCandle) -> list[OrderIntent]:
            if bar_idx == 0 and len(eng.portfolio.positions) == 0:
                return [
                    OrderIntent(
                        symbol="TCS",
                        direction="BUY",
                        quantity=qty,
                        generated_at_bar_index=bar_idx,
                        generated_at_time=candle.timestamp,
                    )
                ]
            return []

        return strategy

    report = optimizer.run(candles, param_strategy_factory, param_grid=param_grid)
    # In an uptrend, buying 10 shares yields more profit than 1 share, so quantity 10 selected
    for fold in report.folds:
        assert fold.selected_parameters["quantity"] == 10


def test_walk_forward_metric_keys_and_unsupported() -> None:
    """Verify metric extraction for return_pct, profit_factor, and unsupported key."""
    candles = _generate_price_series(30, trend=1.0)

    # return_pct
    opt_ret = WalkForwardOptimizer(
        WalkForwardConfig(train_bars=15, test_bars=10, step_bars=10, metric_key="return_pct")
    )
    # profit_factor
    opt_pf = WalkForwardOptimizer(
        WalkForwardConfig(train_bars=15, test_bars=10, step_bars=10, metric_key="profit_factor")
    )
    # sharpe_ratio
    opt_sr = WalkForwardOptimizer(
        WalkForwardConfig(train_bars=15, test_bars=10, step_bars=10, metric_key="sharpe_ratio")
    )

    def dummy_factory(
        _params: dict[str, Any],
    ) -> Callable[[BacktestEngine, int, OHLCVCandle], list[OrderIntent]]:
        return lambda _e, _b, _c: []

    rep_ret = opt_ret.run(candles, dummy_factory)
    assert rep_ret.parameters["metric_key"] == "return_pct"

    rep_pf = opt_pf.run(candles, dummy_factory)
    assert rep_pf.parameters["metric_key"] == "profit_factor"

    rep_sr = opt_sr.run(candles, dummy_factory)
    assert rep_sr.parameters["metric_key"] == "sharpe_ratio"

    # Unsupported key
    invalid_opt = WalkForwardOptimizer()
    with pytest.raises(ValueError, match="Unsupported metric key"):
        invalid_opt._extract_metric_value(rep_ret.aggregate_is_metrics, "invalid_metric")


def test_walk_forward_zero_and_negative_metric_branches() -> None:
    """Verify fold and global WFER calculation when in-sample or out-of-sample metrics are <= 0."""
    # 30 candles: downward trending prices (losses on longs)
    candles = _generate_price_series(30, trend=-1.0)

    config = WalkForwardConfig(
        strategy_id="losing_buyer",
        train_bars=15,
        test_bars=10,
        step_bars=10,
        efficiency_gate_threshold=Decimal("0.50"),
        metric_key="net_profit",
    )
    optimizer = WalkForwardOptimizer(config)

    def buyer_factory(
        _params: dict[str, Any],
    ) -> Callable[[BacktestEngine, int, OHLCVCandle], list[OrderIntent]]:
        def strategy(eng: BacktestEngine, bar_idx: int, candle: OHLCVCandle) -> list[OrderIntent]:
            if bar_idx == 0 and len(eng.portfolio.positions) == 0:
                return [
                    OrderIntent(
                        symbol="TCS",
                        direction="BUY",
                        quantity=5,
                        generated_at_bar_index=bar_idx,
                        generated_at_time=candle.timestamp,
                    )
                ]
            return []

        return strategy

    report = optimizer.run(candles, buyer_factory)
    # Since both IS and OOS lose money, global WFER should be 0.0000
    assert report.walk_forward_efficiency_ratio == Decimal("0.0000")
    assert report.passed_gate is False
    assert report.overfit_flag is True
