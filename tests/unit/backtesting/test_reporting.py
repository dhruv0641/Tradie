"""Unit tests for BacktestReporter formatting PRD §10 metrics and BTD §12 audit reports."""

import json
from datetime import UTC, datetime
from decimal import Decimal

from src.backtesting.reporting import BacktestReporter
from src.domain.backtest_result import (
    BacktestMetrics,
    BacktestResult,
    EquityPoint,
)


def _create_mock_result(
    total_trades: int = 15,
    gross_profit: Decimal = Decimal("1500.00"),
    gross_loss: Decimal = Decimal("600.00"),
    total_costs: Decimal = Decimal("200.00"),
) -> BacktestResult:
    """Helper creating BacktestResult fixture for reporting tests."""
    net_profit = gross_profit - gross_loss - total_costs
    metrics = BacktestMetrics(
        total_trades=total_trades,
        winning_trades=int(total_trades * 0.6),
        losing_trades=total_trades - int(total_trades * 0.6),
        win_rate=Decimal("60.00"),
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        net_profit=net_profit,
        total_costs=total_costs,
        profit_factor=Decimal("2.50"),
        max_drawdown_pct=Decimal("3.50"),
        sharpe_ratio=Decimal("1.85"),
        sortino_ratio=Decimal("2.40"),
        return_pct=Decimal("7.00"),
    )
    return BacktestResult(
        strategy_id="test_baseline_strategy",
        initial_capital=Decimal("10000.00"),
        final_equity=Decimal("10700.00"),
        metrics=metrics,
        trades=[],
        equity_curve=[
            EquityPoint(
                timestamp=datetime(2026, 1, 1, 9, 15, tzinfo=UTC),
                cash=Decimal("10000.00"),
                holdings_value=Decimal("0.00"),
                total_equity=Decimal("10000.00"),
                drawdown_pct=Decimal("0.00"),
                open_positions_count=0,
            )
        ],
        parameters={"fast_span": 20, "slow_span": 50},
    )


def test_markdown_report_structure_and_small_sample_warning() -> None:
    """Verify Markdown report includes BTD §12 small sample caveat when trades < 30."""
    result = _create_mock_result(total_trades=12)
    meta = {"symbol": "NSE:TCS", "timeframe": "15m"}
    md = BacktestReporter.generate_markdown_report(result, run_metadata=meta)

    assert "# Backtest Performance Report: test_baseline_strategy" in md
    assert "SAMPLE SIZE CAVEAT (BTD §12)" in md
    assert "12 trades" in md
    assert "threshold: 30 trades" in md
    assert "Initial Capital" in md
    assert "₹10,000.00" in md
    assert "Net Profit" in md
    assert "₹700.00" in md
    assert "Profit Factor" in md
    assert "2.50" in md
    assert "Indian Market Cost Drag Attribution" in md
    assert "Known Limitations & Bias Disclosures" in md
    assert "NSE:TCS" in md


def test_markdown_report_large_sample_affirmation() -> None:
    """Verify Markdown report validates sample size when trades >= 30."""
    result = _create_mock_result(total_trades=45)
    md = BacktestReporter.generate_markdown_report(result)

    assert "Sample Size Validation (BTD §12)" in md
    assert "45 trades" in md
    assert "SAMPLE SIZE CAVEAT" not in md


def test_json_report_schema_and_serialization() -> None:
    """Verify JSON report generates structured valid JSON with all PRD §10 sections."""
    result = _create_mock_result(total_trades=18)
    meta = {"version": "V1.0"}
    json_data = BacktestReporter.generate_json_report(result, run_metadata=meta)

    assert json_data["strategy_id"] == "test_baseline_strategy"
    assert json_data["metadata"]["version"] == "V1.0"
    assert json_data["capital"]["initial"] == 10000.0
    assert json_data["capital"]["final"] == 10700.0
    assert json_data["performance"]["sharpe_ratio"] == 1.85
    assert json_data["performance"]["profit_factor"] == 2.5
    assert json_data["trade_statistics"]["total_trades"] == 18
    assert json_data["caveats"]["sample_size_warning"] is True
    assert json_data["caveats"]["trade_count"] == 18
    assert json_data["parameters"]["fast_span"] == 20

    # Ensure clean serialization to string and deserialization
    raw_str = json.dumps(json_data)
    loaded = json.loads(raw_str)
    assert loaded["strategy_id"] == "test_baseline_strategy"


def test_zero_gross_profit_cost_drag_edge_case() -> None:
    """Verify cost drag calculation does not divide by zero when gross profit is 0."""
    result = _create_mock_result(
        total_trades=5,
        gross_profit=Decimal("0.00"),
        gross_loss=Decimal("500.00"),
        total_costs=Decimal("50.00"),
    )
    md = BacktestReporter.generate_markdown_report(result)
    json_data = BacktestReporter.generate_json_report(result)

    assert "0.00%" in md
    assert json_data["cost_attribution"]["cost_drag_pct"] == 0.0
