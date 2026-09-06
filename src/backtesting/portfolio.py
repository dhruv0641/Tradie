"""Simulated portfolio and position state tracker for event-driven backtesting."""

import math
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.domain.backtest_result import (
    BacktestMetrics,
    BacktestTrade,
    EquityPoint,
)


class SimulatedPosition(BaseModel):
    """Active open position during backtest simulation."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    symbol: str
    direction: Literal["BUY", "SELL"]
    quantity: int = Field(gt=0)
    entry_price: Decimal = Field(gt=Decimal("0"))
    entry_time: datetime
    entry_cost: Decimal = Field(ge=Decimal("0"))
    current_price: Decimal = Field(gt=Decimal("0"))
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    unrealized_pnl: Decimal = Decimal("0")
    bars_held: int = 0


class SimulatedPortfolio:
    """Event-driven portfolio tracking cash, open positions, trades, and equity curve."""

    def __init__(
        self,
        initial_capital: Decimal = Decimal("10000.00"),
    ) -> None:
        """Initialize simulated portfolio with baseline cash.

        Args:
            initial_capital: Starting cash balance in INR.
        """
        if initial_capital <= Decimal("0"):
            msg = "Initial capital must be strictly positive"
            raise ValueError(msg)

        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions: dict[str, SimulatedPosition] = {}
        self.trades: list[BacktestTrade] = []
        self.equity_curve: list[EquityPoint] = []
        self.peak_equity = initial_capital
        self.max_drawdown_pct = Decimal("0.00")

    @property
    def total_equity(self) -> Decimal:
        """Current total portfolio value (cash + mark-to-market holdings)."""
        holdings_val = sum(
            (pos.current_price * Decimal(pos.quantity) for pos in self.positions.values()),
            Decimal("0"),
        )
        return self.cash + holdings_val

    def open_position(
        self,
        symbol: str,
        direction: Literal["BUY", "SELL"],
        quantity: int,
        fill_price: Decimal,
        timestamp: datetime,
        *,
        entry_cost: Decimal,
        stop_loss: Decimal | None = None,
        take_profit: Decimal | None = None,
    ) -> SimulatedPosition:
        """Open a new position if cash margin is sufficient.

        Args:
            symbol: Traded instrument.
            direction: Position side (currently BUY for long equity).
            quantity: Number of shares.
            fill_price: Realized fill price per share.
            timestamp: Fill timestamp in UTC.
            entry_cost: Statutory taxes and brokerage incurred on entry.
            stop_loss: Optional stop-loss exit threshold.
            take_profit: Optional take-profit exit threshold.

        Returns:
            Created SimulatedPosition.

        Raises:
            ValueError: If position already open or cash is insufficient.
        """
        if symbol in self.positions:
            msg = f"Position for {symbol} already exists in portfolio"
            raise ValueError(msg)
        if quantity <= 0:
            msg = f"Quantity must be strictly positive, got {quantity}"
            raise ValueError(msg)
        if fill_price <= Decimal("0"):
            msg = f"Fill price must be strictly positive, got {fill_price}"
            raise ValueError(msg)

        required_cash = (Decimal(quantity) * fill_price) + entry_cost
        if self.cash < required_cash:
            msg = f"Insufficient cash: required ₹{required_cash}, available ₹{self.cash}"
            raise ValueError(msg)

        # Deduct purchase capital and entry friction
        self.cash -= required_cash

        pos = SimulatedPosition(
            symbol=symbol,
            direction=direction,
            quantity=quantity,
            entry_price=fill_price,
            entry_time=timestamp,
            entry_cost=entry_cost,
            current_price=fill_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            unrealized_pnl=Decimal("0"),
            bars_held=0,
        )
        self.positions[symbol] = pos
        return pos

    def close_position(
        self,
        symbol: str,
        exit_price: Decimal,
        timestamp: datetime,
        exit_cost: Decimal,
        exit_reason: Literal[
            "STOP_LOSS",
            "TAKE_PROFIT",
            "SIGNAL_EXIT",
            "END_OF_DATA",
            "FORCE_CLOSE",
        ],
    ) -> BacktestTrade:
        """Close an active position and realize PnL.

        Args:
            symbol: Symbol to close.
            exit_price: Realized exit price per share.
            timestamp: Exit timestamp in UTC.
            exit_cost: Statutory taxes and brokerage incurred on exit.
            exit_reason: Trigger reason for exit.

        Returns:
            Completed BacktestTrade record.

        Raises:
            KeyError: If position does not exist.
            ValueError: If exit price is invalid.
        """
        if symbol not in self.positions:
            msg = f"No active position for {symbol} to close"
            raise KeyError(msg)
        if exit_price <= Decimal("0"):
            msg = f"Exit price must be strictly positive, got {exit_price}"
            raise ValueError(msg)

        pos = self.positions.pop(symbol)
        qty_dec = Decimal(pos.quantity)

        if pos.direction == "BUY":
            gross_pnl = (exit_price - pos.entry_price) * qty_dec
            proceeds = (exit_price * qty_dec) - exit_cost
        else:
            # Extensible for short selling / derivatives
            gross_pnl = (pos.entry_price - exit_price) * qty_dec
            proceeds = ((pos.entry_price * Decimal("2") - exit_price) * qty_dec) - exit_cost

        total_costs = pos.entry_cost + exit_cost
        net_pnl = gross_pnl - total_costs
        self.cash += proceeds

        invested_capital = pos.entry_price * qty_dec
        return_pct = (
            (net_pnl / invested_capital) * Decimal("100")
            if invested_capital > Decimal("0")
            else Decimal("0")
        )

        trade = BacktestTrade(
            symbol=symbol,
            direction=pos.direction,
            quantity=pos.quantity,
            entry_time=pos.entry_time,
            exit_time=timestamp,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            gross_pnl=gross_pnl.quantize(Decimal("0.01")),
            net_pnl=net_pnl.quantize(Decimal("0.01")),
            total_costs=total_costs.quantize(Decimal("0.01")),
            return_pct=return_pct.quantize(Decimal("0.01")),
            holding_period_bars=pos.bars_held,
            exit_reason=exit_reason,
        )
        self.trades.append(trade)
        return trade

    def mark_to_market(
        self,
        timestamp: datetime,
        current_prices: dict[str, Decimal],
        increment_bars: bool = True,
    ) -> EquityPoint:
        """Revalue open positions and record an equity curve point.

        Args:
            timestamp: Bar timestamp in UTC.
            current_prices: Mapping of symbol to current bar close price.
            increment_bars: Whether to increment bars_held for open positions.

        Returns:
            Recorded EquityPoint.
        """
        holdings_value = Decimal("0")

        for sym, pos in self.positions.items():
            if sym in current_prices:
                pos.current_price = current_prices[sym]

            qty_dec = Decimal(pos.quantity)
            if pos.direction == "BUY":
                pos.unrealized_pnl = (pos.current_price - pos.entry_price) * qty_dec
                holdings_value += pos.current_price * qty_dec
            else:
                pos.unrealized_pnl = (pos.entry_price - pos.current_price) * qty_dec
                holdings_value += (pos.entry_price * Decimal("2") - pos.current_price) * qty_dec

            if increment_bars:
                pos.bars_held += 1

        total_eq = self.cash + holdings_value
        self.peak_equity = max(self.peak_equity, total_eq)

        drawdown = Decimal("0")
        if self.peak_equity > Decimal("0"):
            drawdown = ((self.peak_equity - total_eq) / self.peak_equity) * Decimal("100")
            drawdown = max(drawdown, Decimal("0"))

        drawdown_quantized = drawdown.quantize(Decimal("0.01"))
        self.max_drawdown_pct = max(self.max_drawdown_pct, drawdown_quantized)

        pt = EquityPoint(
            timestamp=timestamp,
            cash=self.cash.quantize(Decimal("0.01")),
            holdings_value=holdings_value.quantize(Decimal("0.01")),
            total_equity=total_eq.quantize(Decimal("0.01")),
            drawdown_pct=drawdown_quantized,
            open_positions_count=len(self.positions),
        )
        self.equity_curve.append(pt)
        return pt

    def compute_metrics(self) -> BacktestMetrics:
        """Compute aggregate performance and risk statistics across completed trades.

        Returns:
            BacktestMetrics instance.
        """
        total_trades = len(self.trades)
        winning_trades = sum(1 for t in self.trades if t.net_pnl > Decimal("0"))
        losing_trades = sum(1 for t in self.trades if t.net_pnl < Decimal("0"))

        win_rate = (
            (Decimal(winning_trades) / Decimal(total_trades)) * Decimal("100")
            if total_trades > 0
            else Decimal("0")
        )

        gross_profit = sum(
            (t.gross_pnl for t in self.trades if t.gross_pnl > Decimal("0")),
            Decimal("0"),
        )
        gross_loss = sum(
            (abs(t.gross_pnl) for t in self.trades if t.gross_pnl < Decimal("0")),
            Decimal("0"),
        )

        profit_factor = (
            gross_profit / gross_loss
            if gross_loss > Decimal("0")
            else (Decimal("999.99") if gross_profit > Decimal("0") else Decimal("0"))
        )

        total_costs = sum((t.total_costs for t in self.trades), Decimal("0"))
        net_profit = sum((t.net_pnl for t in self.trades), Decimal("0"))

        return_pct = (
            (net_profit / self.initial_capital) * Decimal("100")
            if self.initial_capital > Decimal("0")
            else Decimal("0")
        )

        sharpe_ratio: Decimal | None = None
        sortino_ratio: Decimal | None = None

        if len(self.equity_curve) >= 2:
            # Compute equity curve periodic returns
            returns: list[float] = []
            for i in range(1, len(self.equity_curve)):
                prev = float(self.equity_curve[i - 1].total_equity)
                curr = float(self.equity_curve[i].total_equity)
                if prev > 0:
                    returns.append((curr - prev) / prev)

            if len(returns) > 1:
                mean_ret = sum(returns) / len(returns)
                var = sum((r - mean_ret) ** 2 for r in returns) / (len(returns) - 1)
                stdev = math.sqrt(var)

                # Annualization factor assuming daily bars (~252 trading days/year)
                ann_factor = math.sqrt(252)

                if stdev > 1e-8:
                    sharpe = (mean_ret / stdev) * ann_factor
                    sharpe_ratio = Decimal(str(round(sharpe, 4)))

                downside_returns = [r for r in returns if r < 0]
                if downside_returns:
                    downside_var = sum(r**2 for r in downside_returns) / len(returns)
                    downside_stdev = math.sqrt(downside_var)
                    if downside_stdev > 1e-8:
                        sortino = (mean_ret / downside_stdev) * ann_factor
                        sortino_ratio = Decimal(str(round(sortino, 4)))

        return BacktestMetrics(
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate.quantize(Decimal("0.01")),
            profit_factor=profit_factor.quantize(Decimal("0.01")),
            gross_profit=gross_profit.quantize(Decimal("0.01")),
            gross_loss=gross_loss.quantize(Decimal("0.01")),
            total_costs=total_costs.quantize(Decimal("0.01")),
            net_profit=net_profit.quantize(Decimal("0.01")),
            return_pct=return_pct.quantize(Decimal("0.01")),
            max_drawdown_pct=self.max_drawdown_pct.quantize(Decimal("0.01")),
            sharpe_ratio=sharpe_ratio,
            sortino_ratio=sortino_ratio,
        )
