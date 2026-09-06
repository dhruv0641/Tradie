"""Domain models for backtesting results, equity curves, trade logs, and metrics."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BacktestTrade(BaseModel):
    """Completed round-trip simulated trade record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trade_id: UUID = Field(
        default_factory=uuid4, description="Unique identifier for simulated trade"
    )
    symbol: str = Field(min_length=1, description="Traded instrument symbol")
    direction: Literal["BUY", "SELL"] = Field(description="Entry direction of position")
    quantity: int = Field(gt=0, description="Executed quantity")
    entry_time: datetime = Field(description="Entry execution timestamp in UTC")
    exit_time: datetime = Field(description="Exit execution timestamp in UTC")
    entry_price: Decimal = Field(gt=Decimal("0"), description="Realized entry fill price")
    exit_price: Decimal = Field(gt=Decimal("0"), description="Realized exit fill price")
    gross_pnl: Decimal = Field(description="Gross profit or loss before costs")
    net_pnl: Decimal = Field(description="Net profit or loss after statutory charges and slippage")
    total_costs: Decimal = Field(
        ge=Decimal("0"), description="Total statutory taxes and brokerage incurred"
    )
    return_pct: Decimal = Field(description="Net return percentage on capital deployed")
    holding_period_bars: int = Field(ge=0, description="Duration held in bars")
    exit_reason: Literal[
        "STOP_LOSS",
        "TAKE_PROFIT",
        "SIGNAL_EXIT",
        "END_OF_DATA",
        "FORCE_CLOSE",
    ] = Field(description="Cause of trade exit")

    @field_validator("entry_time", "exit_time")
    @classmethod
    def validate_utc(cls, v: datetime) -> datetime:
        """Enforce timezone-aware UTC timestamp."""
        if v.tzinfo is None:
            msg = "Timestamp must be timezone-aware UTC"
            raise ValueError(msg)
        return v


class EquityPoint(BaseModel):
    """Point on the backtest portfolio equity curve."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp: datetime = Field(description="Snapshot timestamp in UTC")
    cash: Decimal = Field(description="Uninvested cash balance")
    holdings_value: Decimal = Field(
        ge=Decimal("0"), description="Mark-to-market value of open positions"
    )
    total_equity: Decimal = Field(
        ge=Decimal("0"), description="Total portfolio value (cash + holdings)"
    )
    drawdown_pct: Decimal = Field(
        ge=Decimal("0"),
        le=Decimal("100"),
        description="Current drawdown percentage from peak equity",
    )
    open_positions_count: int = Field(ge=0, description="Number of active open positions")

    @field_validator("timestamp")
    @classmethod
    def validate_utc(cls, v: datetime) -> datetime:
        """Enforce timezone-aware UTC timestamp."""
        if v.tzinfo is None:
            msg = "Timestamp must be timezone-aware UTC"
            raise ValueError(msg)
        return v


class BacktestMetrics(BaseModel):
    """Statistical performance metrics of a completed backtest run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    total_trades: int = Field(ge=0, description="Total completed round-trip trades")
    winning_trades: int = Field(ge=0, description="Number of profitable trades")
    losing_trades: int = Field(ge=0, description="Number of loss-making trades")
    win_rate: Decimal = Field(ge=Decimal("0"), le=Decimal("100"), description="Win rate percentage")
    profit_factor: Decimal = Field(ge=Decimal("0"), description="Gross profit / Gross loss ratio")
    gross_profit: Decimal = Field(ge=Decimal("0"), description="Sum of positive gross gains")
    gross_loss: Decimal = Field(ge=Decimal("0"), description="Sum of negative gross losses")
    total_costs: Decimal = Field(
        ge=Decimal("0"), description="Total statutory taxes and brokerage paid"
    )
    net_profit: Decimal = Field(description="Net realized profit or loss after all frictions")
    return_pct: Decimal = Field(description="Total net return percentage on initial capital")
    max_drawdown_pct: Decimal = Field(
        ge=Decimal("0"),
        le=Decimal("100"),
        description="Maximum peak-to-trough drawdown percentage",
    )
    sharpe_ratio: Decimal | None = Field(
        default=None, description="Annualized Sharpe ratio if computable"
    )
    sortino_ratio: Decimal | None = Field(
        default=None, description="Annualized Sortino ratio if computable"
    )


class BacktestResult(BaseModel):
    """Complete output artifact of an event-driven backtest simulation run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_id: str = Field(min_length=1, description="Identifier of strategy")
    initial_capital: Decimal = Field(
        gt=Decimal("0"), description="Starting capital in base currency (INR)"
    )
    final_equity: Decimal = Field(
        ge=Decimal("0"), description="Ending portfolio equity in base currency"
    )
    metrics: BacktestMetrics = Field(description="Aggregated performance and risk statistics")
    trades: list[BacktestTrade] = Field(
        default_factory=list, description="Ordered log of completed trades"
    )
    equity_curve: list[EquityPoint] = Field(
        default_factory=list, description="Historical equity curve points"
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict, description="Configuration parameters used for run"
    )
