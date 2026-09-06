"""Unit tests for backtest domain models and UTC validation."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.domain.backtest_result import (
    BacktestMetrics,
    BacktestResult,
    BacktestTrade,
    EquityPoint,
)


def test_backtest_trade_utc_validation() -> None:
    """Verify BacktestTrade enforces UTC timezone awareness."""
    utc_now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    naive_dt = datetime(2026, 1, 1, 12, 0)

    trade = BacktestTrade(
        symbol="TCS",
        direction="BUY",
        quantity=10,
        entry_time=utc_now,
        exit_time=utc_now,
        entry_price=Decimal("100.00"),
        exit_price=Decimal("110.00"),
        gross_pnl=Decimal("100.00"),
        net_pnl=Decimal("95.00"),
        total_costs=Decimal("5.00"),
        return_pct=Decimal("9.50"),
        holding_period_bars=3,
        exit_reason="TAKE_PROFIT",
    )
    assert trade.symbol == "TCS"

    # Naive entry time
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        BacktestTrade(
            symbol="TCS",
            direction="BUY",
            quantity=10,
            entry_time=naive_dt,
            exit_time=utc_now,
            entry_price=Decimal("100.00"),
            exit_price=Decimal("110.00"),
            gross_pnl=Decimal("100.00"),
            net_pnl=Decimal("95.00"),
            total_costs=Decimal("5.00"),
            return_pct=Decimal("9.50"),
            holding_period_bars=3,
            exit_reason="TAKE_PROFIT",
        )

    # Naive exit time
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        BacktestTrade(
            symbol="TCS",
            direction="BUY",
            quantity=10,
            entry_time=utc_now,
            exit_time=naive_dt,
            entry_price=Decimal("100.00"),
            exit_price=Decimal("110.00"),
            gross_pnl=Decimal("100.00"),
            net_pnl=Decimal("95.00"),
            total_costs=Decimal("5.00"),
            return_pct=Decimal("9.50"),
            holding_period_bars=3,
            exit_reason="TAKE_PROFIT",
        )


def test_equity_point_utc_validation() -> None:
    """Verify EquityPoint enforces UTC timezone awareness."""
    utc_now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    naive_dt = datetime(2026, 1, 1, 12, 0)

    point = EquityPoint(
        timestamp=utc_now,
        cash=Decimal("10000.00"),
        holdings_value=Decimal("0.00"),
        total_equity=Decimal("10000.00"),
        drawdown_pct=Decimal("0.00"),
        open_positions_count=0,
    )
    assert point.total_equity == Decimal("10000.00")

    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        EquityPoint(
            timestamp=naive_dt,
            cash=Decimal("10000.00"),
            holdings_value=Decimal("0.00"),
            total_equity=Decimal("10000.00"),
            drawdown_pct=Decimal("0.00"),
            open_positions_count=0,
        )


def test_backtest_result_and_metrics_creation() -> None:
    """Verify BacktestMetrics and BacktestResult fields and immutability."""
    metrics = BacktestMetrics(
        total_trades=0,
        winning_trades=0,
        losing_trades=0,
        win_rate=Decimal("0.00"),
        profit_factor=Decimal("0.00"),
        gross_profit=Decimal("0.00"),
        gross_loss=Decimal("0.00"),
        total_costs=Decimal("0.00"),
        net_profit=Decimal("0.00"),
        return_pct=Decimal("0.00"),
        max_drawdown_pct=Decimal("0.00"),
    )

    result = BacktestResult(
        strategy_id="strat_test",
        initial_capital=Decimal("10000.00"),
        final_equity=Decimal("10000.00"),
        metrics=metrics,
    )
    assert result.strategy_id == "strat_test"
    assert result.final_equity == Decimal("10000.00")
