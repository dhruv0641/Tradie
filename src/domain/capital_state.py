"""Canonical portfolio capital and equity state domain model."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
