"""Unit tests for Monte Carlo trade-sequence resampling engine (BTD §8.5, RTLD §8)."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from src.backtesting.monte_carlo import MonteCarloSimulator
from src.domain.backtest_result import BacktestTrade


def _make_trade(net_pnl: Decimal) -> BacktestTrade:
    now = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    return BacktestTrade(
        trade_id=uuid4(),
        symbol="TCS",
        direction="BUY",
        quantity=10,
        entry_time=now,
        exit_time=now,
        entry_price=Decimal("100.00"),
        exit_price=Decimal("105.00"),
        gross_pnl=net_pnl + Decimal("5.00"),
        net_pnl=net_pnl,
        total_costs=Decimal("5.00"),
        return_pct=Decimal("5.00"),
        holding_period_bars=1,
        exit_reason="TAKE_PROFIT",
    )


def test_monte_carlo_init_validations() -> None:
    """Verify simulation_count and initial_capital validation."""
    with pytest.raises(ValueError, match="simulation_count must be at least 100"):
        MonteCarloSimulator(simulation_count=50)

    with pytest.raises(ValueError, match="initial_capital must be strictly positive"):
        MonteCarloSimulator(initial_capital=Decimal("0.00"))


def test_monte_carlo_empty_trades() -> None:
    """Verify behavior on empty trades or PnLs."""
    sim = MonteCarloSimulator(simulation_count=100, initial_capital=Decimal("10000.00"), seed=42)
    res = sim.run_from_pnls([])

    assert res.trade_count == 0
    assert res.equity_p5 == Decimal("10000.00")
    assert res.equity_p50 == Decimal("10000.00")
    assert res.equity_p95 == Decimal("10000.00")
    assert res.worst_case_drawdown == Decimal("0.00")
    assert res.prob_drawdown_halt_8pct == Decimal("0.0000")
    assert res.prob_kill_switch_10pct == Decimal("0.0000")
    assert res.prob_ruin == Decimal("0.0000")


def test_monte_carlo_seed_reproducibility() -> None:
    """Verify deterministic seeded reproducibility (BTD §10)."""
    pnls = [
        Decimal("100.00"),
        Decimal("-50.00"),
        Decimal("200.00"),
        Decimal("-150.00"),
        Decimal("80.00"),
    ]

    sim1 = MonteCarloSimulator(simulation_count=200, seed=42)
    res1 = sim1.run_from_pnls(pnls)

    sim2 = MonteCarloSimulator(simulation_count=200, seed=42)
    res2 = sim2.run_from_pnls(pnls)

    assert res1.equity_p50 == res2.equity_p50
    assert res1.equity_p5 == res2.equity_p5
    assert res1.equity_p95 == res2.equity_p95
    assert res1.max_drawdown_p50 == res2.max_drawdown_p50
    assert res1.worst_case_drawdown == res2.worst_case_drawdown
    assert res1.prob_drawdown_halt_8pct == res2.prob_drawdown_halt_8pct


def test_monte_carlo_profitable_distribution_and_percentiles() -> None:
    """Verify percentile monotonic ordering and low drawdown probabilities for winning trades."""
    # 20 consistently profitable trades
    pnls = [Decimal("50.00") for _ in range(20)]
    sim = MonteCarloSimulator(simulation_count=200, seed=123)
    res = sim.run_from_pnls(pnls)

    assert res.equity_p5 <= res.equity_p50 <= res.equity_p95
    assert res.max_drawdown_p5 <= res.max_drawdown_p50 <= res.max_drawdown_p95
    # No losses means zero drawdown
    assert res.max_drawdown_p50 == Decimal("0.00")
    assert res.prob_drawdown_halt_8pct == Decimal("0.0000")
    assert res.prob_kill_switch_10pct == Decimal("0.0000")
    assert len(res.sample_equity_curves) == 10


def test_monte_carlo_losing_strategy_and_breaches() -> None:
    """Verify detection of sequence risk, 8% halt, and 10% kill switch breaches."""
    # Severe losses: 10 trades of -₹200 each (-₹2,000 on ₹10,000 is 20% drawdown)
    pnls = [Decimal("-200.00") for _ in range(10)]
    sim = MonteCarloSimulator(simulation_count=200, seed=999)
    res = sim.run_from_pnls(pnls)

    assert res.equity_p50 < Decimal("10000.00")
    assert res.worst_case_drawdown >= Decimal("10.00")
    # All paths suffer heavy losses, so both halt and kill switch must be 100%
    assert res.prob_drawdown_halt_8pct == Decimal("1.0000")
    assert res.prob_kill_switch_10pct == Decimal("1.0000")


def test_monte_carlo_run_from_trades() -> None:
    """Verify run_from_trades extracts net_pnl correctly from BacktestTrade objects."""
    trades = [
        _make_trade(Decimal("100.00")),
        _make_trade(Decimal("-50.00")),
        _make_trade(Decimal("250.00")),
    ]
    sim = MonteCarloSimulator(simulation_count=100, seed=42)
    res = sim.run_from_trades(trades)

    assert res.trade_count == 3
    assert res.simulation_count == 100
    assert res.equity_p50 > Decimal("10000.00")


def test_monte_carlo_ruin_probability() -> None:
    """Verify detection of complete capital depletion / ruin event."""
    # -₹15,000 loss on ₹10,000 initial capital
    pnls = [Decimal("-15000.00")]
    sim = MonteCarloSimulator(simulation_count=100, seed=1)
    res = sim.run_from_pnls(pnls)
    assert res.prob_ruin == Decimal("1.0000")
