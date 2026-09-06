"""Domain models for deterministic risk management and portfolio safety boundaries."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CandidateTrade(BaseModel):
    """Candidate trade opportunity presented to the deterministic Risk Engine."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument: str = Field(min_length=1, description="Instrument trading symbol")
    direction: Literal["BUY", "SELL"] = Field(description="Trade direction")
    entry_price: Decimal = Field(gt=Decimal("0"), description="Intended entry price")
    stop_price: Decimal = Field(gt=Decimal("0"), description="Protective hard stop-loss price")
    timeframe: str = Field(min_length=1, description="Timeframe of the opportunity")
    trade_quality_score: float = Field(
        ge=0.0, le=1.0, description="Normalized composite quality score from Aggregator"
    )
    expected_value: Decimal = Field(description="Post-friction expected monetary value per unit")
    confidence: float = Field(
        ge=0.0, le=1.0, description="Normalized model confidence score [0.0, 1.0]"
    )
    timestamp: datetime = Field(description="Timestamp in UTC")

    @property
    def symbol(self) -> str:
        """Alias for instrument trading symbol."""
        return self.instrument

    @field_validator("timestamp")
    @classmethod
    def validate_utc_timestamp(cls, v: datetime) -> datetime:
        """Enforce that timestamp is timezone-aware."""
        if v.tzinfo is None:
            msg = "CandidateTrade timestamp must be timezone-aware UTC"
            raise ValueError(msg)
        return v

    @model_validator(mode="after")
    def validate_stop_distance_and_direction(self) -> "CandidateTrade":
        """Validate that stop loss is on the correct protective side of entry."""
        if self.entry_price == self.stop_price:
            msg = "Entry price and stop price cannot be identical"
            raise ValueError(msg)
        if self.direction == "BUY" and self.stop_price >= self.entry_price:
            msg = (
                f"BUY order stop price ({self.stop_price}) must be strictly "
                f"below entry price ({self.entry_price})"
            )
            raise ValueError(msg)
        if self.direction == "SELL" and self.stop_price <= self.entry_price:
            msg = (
                f"SELL order stop price ({self.stop_price}) must be strictly "
                f"above entry price ({self.entry_price})"
            )
            raise ValueError(msg)
        return self


class CapitalState(BaseModel):
    """Real-time portfolio equity and capital allocation state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    current_capital: Decimal = Field(
        ge=Decimal("0"), description="Current allocated capital in INR"
    )
    peak_equity: Decimal = Field(
        ge=Decimal("0"), description="Peak total equity achieved for drawdown tracking"
    )
    session_start_capital: Decimal = Field(
        ge=Decimal("0"), description="Capital at the start of current trading session"
    )
    currently_deployed: Decimal = Field(
        ge=Decimal("0"), description="Total capital currently deployed in open positions"
    )
    open_position_count: int = Field(ge=0, description="Number of currently open positions")
    trades_today: int = Field(ge=0, description="Number of completed/active trades initiated today")

    @model_validator(mode="after")
    def validate_equity_relationships(self) -> "CapitalState":
        """Sanity check capital relationships."""
        if self.currently_deployed > self.current_capital:
            msg = (
                f"Currently deployed capital ({self.currently_deployed}) "
                f"cannot exceed current capital ({self.current_capital})"
            )
            raise ValueError(msg)
        return self


class StreakState(BaseModel):
    """Behavioral consecutive loss tracking state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    consecutive_losses: int = Field(
        default=0, ge=0, description="Count of consecutive losing trades"
    )
    is_tier1_active: bool = Field(
        default=False, description="True if Tier-1 50% size reduction is triggered"
    )
    is_tier2_active: bool = Field(
        default=False, description="True if Tier-2 session pause is triggered"
    )
    session_paused: bool = Field(
        default=False, description="True if session trading is currently paused due to streak"
    )
    last_trade_pnl: Decimal | None = Field(
        default=None, description="P&L of most recent completed trade"
    )


class MarketState(BaseModel):
    """Real-time market volatility and liquidity health context."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument: str = Field(min_length=1, description="Instrument trading symbol")
    current_volatility: Decimal = Field(
        ge=Decimal("0"), description="Realized volatility / ATR over active timeframe"
    )
    trailing_20session_avg_volatility: Decimal = Field(
        ge=Decimal("0"), description="Trailing 20-session average volatility benchmark"
    )
    data_quality: Literal["VALIDATED", "QUARANTINED", "STALE"] = Field(
        default="VALIDATED", description="Data pipeline quality state"
    )
    exchange_condition: Literal["NORMAL", "HALTED", "CIRCUIT"] = Field(
        default="NORMAL", description="Exchange-level market condition"
    )


class RiskCheckResult(BaseModel):
    """Immutable audit result emitted by the deterministic Risk Engine."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    passed: bool = Field(
        description="True if all deterministic risk checks passed; False otherwise"
    )
    failed_check: str | None = Field(
        default=None, description="Name of the specific check that failed"
    )
    rtld_param_id: str | None = Field(
        default=None, description="RTLD numeric parameter ID (e.g., RTLD-4) for auditability"
    )
    reason: str | None = Field(
        default=None, description="Detailed human-readable explanation of approval or rejection"
    )
    config_version: str = Field(description="Active RiskConfig version snapshot tag")
    approved_quantity: int = Field(
        default=0, ge=0, description="Risk-approved position quantity (0 if rejected)"
    )
    stop_loss_price: Decimal | None = Field(
        default=None, description="Deterministic protective stop loss price"
    )
    target_price: Decimal | None = Field(
        default=None, description="Optional profit target price level"
    )

    @model_validator(mode="after")
    def validate_passed_invariants(self) -> "RiskCheckResult":
        """Enforce that passed trades have positive quantity and no failed check."""
        if self.passed:
            if self.failed_check is not None or self.rtld_param_id is not None:
                msg = "Passed risk result cannot carry a failed_check or rtld_param_id"
                raise ValueError(msg)
            if self.approved_quantity <= 0:
                msg = "Passed risk result must have approved_quantity > 0"
                raise ValueError(msg)
            if self.stop_loss_price is None or self.stop_loss_price <= Decimal("0"):
                msg = "Passed risk result must carry a valid positive stop_loss_price"
                raise ValueError(msg)
        elif self.approved_quantity != 0:
            msg = "Rejected risk result must have approved_quantity == 0"
            raise ValueError(msg)
        return self
