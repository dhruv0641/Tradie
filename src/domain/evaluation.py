"""Canonical post-trade evaluation domain entities for performance attribution."""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TradeEvaluation(BaseModel):
    """Completed round-trip trade performance attribution and post-trade analysis record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trade_id: UUID = Field(default_factory=uuid4, description="Unique completed trade identifier")
    entry_decision_id: UUID = Field(description="Foreign key to entry DecisionRecord")
    exit_decision_id: UUID = Field(description="Foreign key to exit DecisionRecord")
    instrument: str = Field(min_length=1, description="Instrument traded")
    direction: Literal["BUY", "SELL"] = Field(description="Trade direction on entry")
    entry_price: Decimal = Field(gt=Decimal("0"), description="Average executed entry price")
    exit_price: Decimal = Field(gt=Decimal("0"), description="Average executed exit price")
    quantity: int = Field(gt=0, description="Total executed quantity")
    gross_pnl: Decimal = Field(description="Gross profit or loss before costs")
    net_pnl: Decimal = Field(description="Net profit or loss after all charges and slippage")
    total_slippage: Decimal = Field(
        default=Decimal("0"), description="Total execution slippage incurred"
    )
    statutory_costs: Decimal = Field(
        default=Decimal("0"),
        ge=Decimal("0"),
        description="Total Indian statutory charges (STT, GST, Stamp Duty)",
    )
    variance_driver: Literal[
        # Canonical DDD §5.3 / FRD-EVAL-3 drivers:
        "good_trade",
        "bad_signal",
        "bad_timing",
        "bad_sizing",
        "bad_execution",
        "unexpected_event",
        "regime_change",
        "data_problem",
        "model_problem",
        # Legacy uppercase drivers:
        "STRATEGY_EDGE",
        "SLIPPAGE",
        "MARKET_GAP",
        "BROKER_LATENCY",
        "REGIME_SHIFT",
        "RULE_VIOLATION",
    ] = Field(description="Primary driver explaining performance variance vs backtest expectation")
    rule_adherence: bool = Field(
        default=True,
        description="Flag confirming execution adhered 100% to deterministic risk parameters",
    )
    entry_timestamp: datetime | None = Field(
        default=None, description="Trade entry fill timestamp in UTC"
    )
    exit_timestamp: datetime | None = Field(
        default=None, description="Trade exit fill timestamp in UTC"
    )
    total_cost_drag: Decimal = Field(
        default=Decimal("0"),
        description="Total execution drag (statutory charges + execution slippage)",
    )
    expected_pnl: Decimal = Field(
        default=Decimal("0"), description="Mathematical expected P&L at entry"
    )
    pnl_variance: Decimal = Field(
        default=Decimal("0"), description="Variance between realized net P&L and expected P&L"
    )
    evaluation_notes: str = Field(
        default="", description="Operator or automated post-trade analysis notes"
    )
    evaluated_at: datetime = Field(description="Post-trade evaluation timestamp in UTC")

    @field_validator("evaluated_at", "entry_timestamp", "exit_timestamp")
    @classmethod
    def validate_utc_timestamp(cls, v: datetime | None) -> datetime | None:
        """Enforce that timestamp is timezone-aware."""
        if v is not None and v.tzinfo is None:
            msg = "Evaluation timestamp must be timezone-aware UTC"
            raise ValueError(msg)
        return v
