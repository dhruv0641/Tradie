"""Canonical market data domain models with strict mathematical and boundary validation."""

from datetime import datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class OHLCVCandle(BaseModel):
    """Immutable, strongly-typed single OHLCV candlestick representation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument: str = Field(
        min_length=1, description="Canonical instrument symbol (e.g. NSE:RELIANCE)"
    )
    timestamp: datetime = Field(description="Bar opening/closing timestamp in UTC")
    open: Decimal = Field(gt=Decimal("0"), description="Opening price")
    high: Decimal = Field(gt=Decimal("0"), description="Highest price in timeframe")
    low: Decimal = Field(gt=Decimal("0"), description="Lowest price in timeframe")
    close: Decimal = Field(gt=Decimal("0"), description="Closing price")
    volume: int = Field(ge=0, description="Total volume traded in timeframe")
    turnover: Decimal = Field(
        default=Decimal("0"),
        ge=Decimal("0"),
        description="Total turnover traded in currency",
    )
    timeframe: str = Field(min_length=1, description="Candle timeframe interval (e.g. 1m, 5m, 1d)")
    quality_state: Literal["VALIDATED", "QUARANTINED", "STALE"] = Field(
        default="VALIDATED", description="Data hygiene and validation status"
    )

    @field_validator("timestamp")
    @classmethod
    def validate_utc_timestamp(cls, v: datetime) -> datetime:
        """Enforce that timestamp is timezone-aware."""
        if v.tzinfo is None:
            msg = "Timestamp must be timezone-aware UTC"
            raise ValueError(msg)
        return v

    @model_validator(mode="after")
    def validate_price_bounds(self) -> Self:
        """Enforce strict candle price boundaries: Low <= Open, Close <= High."""
        if self.high < self.low:
            msg = f"High price ({self.high}) cannot be less than low price ({self.low})"
            raise ValueError(msg)
        if not (self.low <= self.open <= self.high):
            msg = (
                f"Open price ({self.open}) must be between low ({self.low}) and high ({self.high})"
            )
            raise ValueError(msg)
        if not (self.low <= self.close <= self.high):
            msg = (
                f"Close price ({self.close}) must be between low ({self.low}) "
                f"and high ({self.high})"
            )
            raise ValueError(msg)
        return self


class MarketDepthLevel(BaseModel):
    """Single level in the order book market depth ladder."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    price: Decimal = Field(gt=Decimal("0"), description="Price level")
    quantity: int = Field(gt=0, description="Cumulative quantity at this price")
    orders_count: int = Field(default=1, ge=1, description="Number of orders at this level")


class MarketDepthQuote(BaseModel):
    """Level 2 market depth quote containing 5-level bids and asks."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument: str = Field(min_length=1, description="Canonical instrument identifier")
    timestamp: datetime = Field(description="Market depth snapshot timestamp in UTC")
    bids: list[MarketDepthLevel] = Field(description="Top bids ordered descending by price")
    asks: list[MarketDepthLevel] = Field(description="Top asks ordered ascending by price")

    @field_validator("timestamp")
    @classmethod
    def validate_utc_timestamp(cls, v: datetime) -> datetime:
        """Enforce that timestamp is timezone-aware."""
        if v.tzinfo is None:
            msg = "Timestamp must be timezone-aware UTC"
            raise ValueError(msg)
        return v

    @model_validator(mode="after")
    def validate_spread(self) -> Self:
        """Enforce that top bid is less than or equal to top ask (non-inverted book)."""
        if self.bids and self.asks:
            top_bid = self.bids[0].price
            top_ask = self.asks[0].price
            if top_bid > top_ask:
                msg = f"Inverted order book: Top bid ({top_bid}) exceeds top ask ({top_ask})"
                raise ValueError(msg)
        return self


class CorporateAction(BaseModel):
    """Corporate action adjustment (split, dividend, bonus) for point-in-time calculation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument: str = Field(min_length=1, description="Canonical instrument symbol")
    ex_date: datetime = Field(description="Ex-action date in UTC")
    action_type: Literal["SPLIT", "DIVIDEND", "BONUS", "RIGHTS"] = Field(
        description="Category of corporate action"
    )
    adjustment_factor: Decimal = Field(
        gt=Decimal("0"), description="Multiplier factor to adjust historical prices"
    )

    @field_validator("ex_date")
    @classmethod
    def validate_utc_date(cls, v: datetime) -> datetime:
        """Enforce that ex_date is timezone-aware."""
        if v.tzinfo is None:
            msg = "Ex-date must be timezone-aware UTC"
            raise ValueError(msg)
        return v
