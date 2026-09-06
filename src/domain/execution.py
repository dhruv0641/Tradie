"""Execution and position domain entities tracking orders and portfolio state."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OrderSubmission(BaseModel):
    """Order submission entity tracking broker lifecycle states and audit linkage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    client_order_id: str = Field(
        min_length=1, description="Deterministic idempotent client order ID"
    )
    broker_order_id: str | None = Field(
        default=None, description="Exchange or broker assigned order ID"
    )
    instrument: str = Field(min_length=1, description="Instrument traded")
    direction: Literal["BUY", "SELL"] = Field(description="Order direction")
    order_type: Literal["LIMIT", "MARKET"] = Field(description="Order execution type")
    quantity: int = Field(gt=0, description="Order quantity")
    limit_price: Decimal | None = Field(
        default=None, gt=Decimal("0"), description="Limit price if LIMIT order"
    )
    status: Literal[
        "PENDING",
        "SUBMITTED",
        "PARTIAL",
        "FILLED",
        "CANCELLED",
        "REJECTED",
    ] = Field(default="PENDING", description="Current lifecycle state")
    submitted_at: datetime = Field(description="Order submission timestamp in UTC")
    updated_at: datetime = Field(description="State update timestamp in UTC")

    @field_validator("submitted_at", "updated_at")
    @classmethod
    def validate_utc_timestamp(cls, v: datetime) -> datetime:
        """Enforce timezone awareness in UTC."""
        if v.tzinfo is None:
            msg = "Timestamp must be timezone-aware UTC"
            raise ValueError(msg)
        return v


class OrderFill(BaseModel):
    """Order fill execution event emitted by broker or execution simulation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fill_id: str = Field(min_length=1, description="Unique fill identifier")
    client_order_id: str = Field(min_length=1, description="Client order ID")
    instrument: str = Field(min_length=1, description="Traded instrument identifier")
    direction: Literal["BUY", "SELL"] = Field(description="Order fill direction")
    quantity: int = Field(gt=0, description="Executed fill quantity")
    price: Decimal = Field(gt=Decimal("0"), description="Execution fill price per unit")
    commission: Decimal = Field(
        default=Decimal("0"), ge=Decimal("0"), description="Brokerage and statutory charges"
    )
    timestamp: datetime = Field(description="Fill timestamp in UTC")

    @field_validator("timestamp")
    @classmethod
    def validate_utc_timestamp(cls, v: datetime) -> datetime:
        """Enforce timezone awareness in UTC."""
        if v.tzinfo is None:
            msg = "Timestamp must be timezone-aware UTC"
            raise ValueError(msg)
        return v


class Position(BaseModel):
    """Current portfolio holding position for an instrument."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument: str = Field(min_length=1, description="Instrument identifier")
    quantity: int = Field(
        description="Current position quantity (+ for long, - for short, 0 for flat)"
    )
    average_entry_price: Decimal = Field(
        default=Decimal("0"), ge=Decimal("0"), description="Average cost basis per unit"
    )
    current_market_price: Decimal = Field(
        default=Decimal("0"), ge=Decimal("0"), description="Latest mark-to-market price"
    )
    unrealized_pnl: Decimal = Field(
        default=Decimal("0"), description="Unrealized profit or loss mark-to-market"
    )
    realized_pnl: Decimal = Field(
        default=Decimal("0"),
        description="Cumulative realized profit or loss from closed trades",
    )
    peak_unrealized_pnl: Decimal = Field(
        default=Decimal("0"),
        description="Peak unrealized profit or loss reached during position lifetime",
    )
    updated_at: datetime = Field(description="Position update timestamp in UTC")

    @field_validator("updated_at")
    @classmethod
    def validate_utc_timestamp(cls, v: datetime) -> datetime:
        """Enforce timezone awareness in UTC."""
        if v.tzinfo is None:
            msg = "Timestamp must be timezone-aware UTC"
            raise ValueError(msg)
        return v
