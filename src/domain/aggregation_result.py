"""Canonical domain models for multi-agent signal aggregation and trade quality scoring."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AggregationResult(BaseModel):
    """Immutable, strongly-typed domain model representing aggregated multi-agent consensus.

    Adheres to FRD Module 5 (FRD-AGG-1-6), ADD §7, MLD §7, and LLD §8.2.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    passed: bool = Field(
        description="Whether the candidate opportunity cleared the minimum trade quality threshold"
    )
    score: float = Field(
        ge=0.0,
        le=1.0,
        description="Trade quality score Q = |S| normalized strictly in [0.0, 1.0] (FRD-AGG-2)",
    )
    direction: Literal["BUY", "SELL"] | None = Field(
        default=None,
        description="Aggregated trade direction if passed, else None for NO_TRADE (FRD-AGG-4)",
    )
    disagreement: float = Field(
        ge=0.0,
        description="Weighted standard deviation of signed agent confidences (FRD-AGG-5)",
    )
    weighted_score: float = Field(
        ge=-1.0,
        le=1.0,
        description="Signed consensus score S in [-1.0, 1.0] (positive=bullish, negative=bearish)",
    )
    contributing_agents: list[str] = Field(
        default_factory=list,
        description="List of agent IDs that produced valid non-NO_VIEW directional signals",
    )
    agent_scores: dict[str, float] = Field(
        default_factory=dict,
        description="Point-in-time signed confidence contribution per responding agent",
    )
    agent_weights: dict[str, float] = Field(
        default_factory=dict,
        description="Re-normalized weights applied to responding agents summing to 1.0",
    )
    selected_timeframe: str | None = Field(
        default=None,
        description="Candidate timeframe selected during multi-timeframe evaluation",
    )
    reason: str = Field(
        min_length=1,
        description="Diagnostic explanation of threshold clearance or rejection reason",
    )
    timestamp: datetime = Field(description="Aggregation calculation timestamp in UTC")

    @field_validator("timestamp")
    @classmethod
    def validate_utc_timestamp(cls, v: datetime) -> datetime:
        """Enforce that timestamp is timezone-aware UTC."""
        if v.tzinfo is None:
            msg = "AggregationResult timestamp must be timezone-aware UTC"
            raise ValueError(msg)
        return v

    @model_validator(mode="after")
    def validate_passed_direction_consistency(self) -> "AggregationResult":
        """Enforce that passing trades carry a valid direction, and rejected trades carry None."""
        if self.passed and self.direction is None:
            msg = "AggregationResult with passed=True must specify direction ('BUY' or 'SELL')"
            raise ValueError(msg)
        if not self.passed and self.direction is not None:
            msg = "AggregationResult with passed=False must carry direction=None (NO_TRADE)"
            raise ValueError(msg)
        return self
