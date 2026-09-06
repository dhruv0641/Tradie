"""Unit tests for SimulatedPortfolio and SimulatedPosition tracking."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.backtesting.portfolio import SimulatedPortfolio


def test_portfolio_initialization() -> None:
    """Verify portfolio initializes with baseline cash and empty state."""
    portfolio = SimulatedPortfolio(initial_capital=Decimal("10000.00"))
    assert portfolio.cash == Decimal("10000.00")
    assert portfolio.total_equity == Decimal("10000.00")
    assert len(portfolio.positions) == 0
    assert len(portfolio.trades) == 0
    assert len(portfolio.equity_curve) == 0

    with pytest.raises(ValueError, match="strictly positive"):
        SimulatedPortfolio(initial_capital=Decimal("0"))

    with pytest.raises(ValueError, match="strictly positive"):
        SimulatedPortfolio(initial_capital=Decimal("-1000"))


def test_portfolio_open_position_success() -> None:
    """Verify position opens with cash deduction and correct attributes."""
    portfolio = SimulatedPortfolio(initial_capital=Decimal("10000.00"))
    now = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)

    pos = portfolio.open_position(
        symbol="RELIANCE",
        direction="BUY",
        quantity=2,
        fill_price=Decimal("2000.00"),
        timestamp=now,
        entry_cost=Decimal("15.50"),
        stop_loss=Decimal("1950.00"),
        take_profit=Decimal("2100.00"),
    )

    assert pos.symbol == "RELIANCE"
    assert pos.quantity == 2
    assert pos.entry_price == Decimal("2000.00")
    assert pos.stop_loss == Decimal("1950.00")
    assert pos.take_profit == Decimal("2100.00")
    assert "RELIANCE" in portfolio.positions

    # Expected cash: 10000 - (2 * 2000 + 15.50) = 10000 - 4015.50 = 5984.50
    assert portfolio.cash == Decimal("5984.50")
    assert portfolio.total_equity == Decimal("9984.50")  # Cash + 4000 holdings


def test_portfolio_open_position_validations() -> None:
    """Verify validation guards on open_position."""
    portfolio = SimulatedPortfolio(initial_capital=Decimal("1000.00"))
    now = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)

    # Insufficient cash
    with pytest.raises(ValueError, match="Insufficient cash"):
        portfolio.open_position(
            symbol="TCS",
            direction="BUY",
            quantity=1,
            fill_price=Decimal("3500.00"),
            timestamp=now,
            entry_cost=Decimal("10.00"),
        )

    # Duplicate symbol
    portfolio.open_position(
        symbol="INFY",
        direction="BUY",
        quantity=1,
        fill_price=Decimal("500.00"),
        timestamp=now,
        entry_cost=Decimal("5.00"),
    )
    with pytest.raises(ValueError, match="already exists"):
        portfolio.open_position(
            symbol="INFY",
            direction="BUY",
            quantity=1,
            fill_price=Decimal("500.00"),
            timestamp=now,
            entry_cost=Decimal("5.00"),
        )

    # Invalid quantity or price
    with pytest.raises(ValueError, match="Quantity must be strictly positive"):
        portfolio.open_position(
            symbol="WIPRO",
            direction="BUY",
            quantity=0,
            fill_price=Decimal("500.00"),
            timestamp=now,
            entry_cost=Decimal("5.00"),
        )

    with pytest.raises(ValueError, match="Fill price must be strictly positive"):
        portfolio.open_position(
            symbol="WIPRO",
            direction="BUY",
            quantity=1,
            fill_price=Decimal("0"),
            timestamp=now,
            entry_cost=Decimal("5.00"),
        )


def test_portfolio_close_position_long() -> None:
    """Verify closing long position correctly realizes PnL and updates cash."""
    portfolio = SimulatedPortfolio(initial_capital=Decimal("10000.00"))
    t1 = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    t2 = datetime(2026, 1, 1, 15, 30, tzinfo=UTC)

    portfolio.open_position(
        symbol="HDFCBANK",
        direction="BUY",
        quantity=5,
        fill_price=Decimal("1500.00"),
        timestamp=t1,
        entry_cost=Decimal("10.00"),
    )
    # Cash after entry: 10000 - 7510 = 2490.00

    trade = portfolio.close_position(
        symbol="HDFCBANK",
        exit_price=Decimal("1600.00"),
        timestamp=t2,
        exit_cost=Decimal("12.00"),
        exit_reason="TAKE_PROFIT",
    )

    # Gross PnL: (1600 - 1500) * 5 = +500.00
    # Total Costs: 10.00 + 12.00 = 22.00
    # Net PnL: 500.00 - 22.00 = 478.00
    assert trade.gross_pnl == Decimal("500.00")
    assert trade.total_costs == Decimal("22.00")
    assert trade.net_pnl == Decimal("478.00")
    assert trade.exit_reason == "TAKE_PROFIT"
    assert "HDFCBANK" not in portfolio.positions

    # Proceeds added to cash: (5 * 1600) - 12.00 = 8000 - 12 = 7988.00
    # Total Cash: 2490.00 + 7988.00 = 10478.00 (+478.00 net change)
    assert portfolio.cash == Decimal("10478.00")
    assert portfolio.total_equity == Decimal("10478.00")


def test_portfolio_close_position_short() -> None:
    """Verify closing short position correctly calculates inverted PnL."""
    portfolio = SimulatedPortfolio(initial_capital=Decimal("10000.00"))
    t1 = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    t2 = datetime(2026, 1, 1, 15, 30, tzinfo=UTC)

    portfolio.open_position(
        symbol="SBIN",
        direction="SELL",
        quantity=10,
        fill_price=Decimal("800.00"),
        timestamp=t1,
        entry_cost=Decimal("10.00"),
    )

    trade = portfolio.close_position(
        symbol="SBIN",
        exit_price=Decimal("780.00"),
        timestamp=t2,
        exit_cost=Decimal("10.00"),
        exit_reason="SIGNAL_EXIT",
    )

    # Gross PnL: (800 - 780) * 10 = +200.00
    # Total Costs: 20.00
    # Net PnL: +180.00
    assert trade.gross_pnl == Decimal("200.00")
    assert trade.net_pnl == Decimal("180.00")


def test_portfolio_close_position_guards() -> None:
    """Verify close position error handling."""
    portfolio = SimulatedPortfolio(initial_capital=Decimal("10000.00"))
    t1 = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)

    with pytest.raises(KeyError, match="No active position"):
        portfolio.close_position(
            symbol="UNKNOWN",
            exit_price=Decimal("100.00"),
            timestamp=t1,
            exit_cost=Decimal("1.00"),
            exit_reason="STOP_LOSS",
        )

    portfolio.open_position(
        symbol="TEST",
        direction="BUY",
        quantity=1,
        fill_price=Decimal("100.00"),
        timestamp=t1,
        entry_cost=Decimal("1.00"),
    )
    with pytest.raises(ValueError, match="strictly positive"):
        portfolio.close_position(
            symbol="TEST",
            exit_price=Decimal("0"),
            timestamp=t1,
            exit_cost=Decimal("1.00"),
            exit_reason="STOP_LOSS",
        )


def test_portfolio_mark_to_market_and_drawdown() -> None:
    """Verify mark-to-market revaluation, peak equity, and drawdown calculation."""
    portfolio = SimulatedPortfolio(initial_capital=Decimal("10000.00"))
    t1 = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    t2 = datetime(2026, 1, 2, 15, 30, tzinfo=UTC)
    t3 = datetime(2026, 1, 3, 15, 30, tzinfo=UTC)

    portfolio.open_position(
        symbol="AXISBANK",
        direction="BUY",
        quantity=10,
        fill_price=Decimal("500.00"),
        timestamp=t1,
        entry_cost=Decimal("10.00"),
    )
    # Cash: 10000 - 5010 = 4990.00

    # Bar 1: Price goes up to 550
    pt1 = portfolio.mark_to_market(
        timestamp=t2,
        current_prices={"AXISBANK": Decimal("550.00")},
    )
    # Holdings: 10 * 550 = 5500.00
    # Total equity: 4990 + 5500 = 10490.00
    # Peak equity: 10490.00, Drawdown: 0.00%
    assert pt1.total_equity == Decimal("10490.00")
    assert pt1.drawdown_pct == Decimal("0.00")
    assert portfolio.peak_equity == Decimal("10490.00")

    # Bar 2: Price drops to 450
    pt2 = portfolio.mark_to_market(
        timestamp=t3,
        current_prices={"AXISBANK": Decimal("450.00")},
    )
    # Holdings: 10 * 450 = 4500.00
    # Total equity: 4990 + 4500 = 9490.00
    # Peak equity: 10490.00
    # Drawdown: (10490 - 9490) / 10490 * 100 = 1000 / 10490 * 100 = 9.5328...% ~ 9.53%
    assert pt2.total_equity == Decimal("9490.00")
    assert pt2.drawdown_pct == Decimal("9.53")
    assert portfolio.max_drawdown_pct == Decimal("9.53")


def test_portfolio_compute_metrics() -> None:
    """Verify metrics computation across winning and losing trades."""
    portfolio = SimulatedPortfolio(initial_capital=Decimal("10000.00"))
    t1 = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    t2 = datetime(2026, 1, 2, 15, 30, tzinfo=UTC)
    t3 = datetime(2026, 1, 3, 15, 30, tzinfo=UTC)
    t4 = datetime(2026, 1, 4, 15, 30, tzinfo=UTC)

    # Empty metrics check
    empty_metrics = portfolio.compute_metrics()
    assert empty_metrics.total_trades == 0
    assert empty_metrics.win_rate == Decimal("0.00")
    assert empty_metrics.profit_factor == Decimal("0.00")

    # Baseline equity point
    portfolio.mark_to_market(t1, {})

    # Trade 1 (Win): +500 gross, 20 costs => +480 net
    portfolio.open_position("A", "BUY", 5, Decimal("100.00"), t1, entry_cost=Decimal("10.00"))
    portfolio.close_position("A", Decimal("200.00"), t2, Decimal("10.00"), "TAKE_PROFIT")
    portfolio.mark_to_market(t2, {})

    # Trade 2 (Loss): -200 gross, 20 costs => -220 net
    portfolio.open_position("B", "BUY", 10, Decimal("50.00"), t3, entry_cost=Decimal("10.00"))
    portfolio.close_position("B", Decimal("30.00"), t4, Decimal("10.00"), "STOP_LOSS")
    portfolio.mark_to_market(t4, {})

    metrics = portfolio.compute_metrics()
    assert metrics.total_trades == 2
    assert metrics.winning_trades == 1
    assert metrics.losing_trades == 1
    assert metrics.win_rate == Decimal("50.00")
    assert metrics.gross_profit == Decimal("500.00")
    assert metrics.gross_loss == Decimal("200.00")
    # Profit factor = 500 / 200 = 2.50
    assert metrics.profit_factor == Decimal("2.50")
    assert metrics.total_costs == Decimal("40.00")
    # Net profit: 480 - 220 = 260.00
    assert metrics.net_profit == Decimal("260.00")
    assert metrics.return_pct == Decimal("2.60")
    assert metrics.sharpe_ratio is not None


def test_portfolio_mark_to_market_short() -> None:
    """Verify mark-to-market revaluation for short position."""
    portfolio = SimulatedPortfolio(initial_capital=Decimal("10000.00"))
    t1 = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    t2 = datetime(2026, 1, 2, 15, 30, tzinfo=UTC)

    portfolio.open_position(
        symbol="SBIN",
        direction="SELL",
        quantity=10,
        fill_price=Decimal("500.00"),
        timestamp=t1,
        entry_cost=Decimal("10.00"),
    )

    # Price drops to 450 (gain for short: (500 - 450) * 10 = +500)
    pt = portfolio.mark_to_market(t2, {"SBIN": Decimal("450.00")})
    assert pt.holdings_value > Decimal("0")
    pos = portfolio.positions["SBIN"]
    assert pos.unrealized_pnl == Decimal("500.00")


def test_portfolio_metrics_all_wins() -> None:
    """Verify profit factor caps at 999.99 when there are only winning trades."""
    portfolio = SimulatedPortfolio(initial_capital=Decimal("10000.00"))
    t1 = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    t2 = datetime(2026, 1, 2, 15, 30, tzinfo=UTC)

    portfolio.open_position("WIN", "BUY", 1, Decimal("100.00"), t1, entry_cost=Decimal("1.00"))
    portfolio.close_position("WIN", Decimal("150.00"), t2, Decimal("1.00"), "TAKE_PROFIT")

    metrics = portfolio.compute_metrics()
    assert metrics.profit_factor == Decimal("999.99")
    assert metrics.win_rate == Decimal("100.00")
