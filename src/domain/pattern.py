"""Canonical domain entities for empirical trade failure and variance patterns.

Conforms to FRD-LEARN-2, SLD §5.2, and MLD §8.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ObservedPattern(BaseModel):
    """Empirical failure or underperformance cluster extracted across historical trades.

    Adheres to SLD §5.2 and FRD-LEARN-2:
    - Never modifies live parameters directly (Stage 1 is analysis, not action).
    - Differentiates CONFIRMED_HYPOTHESIS (statistically significant, >=30 trades)
      from OBSERVED_UNCONFIRMED (accumulating evidence without generating candidates).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    pattern_id: UUID = Field(
        default_factory=uuid4,
        description="Unique identifier for the observed pattern",
    )
    pattern_type: Literal[
        "REGIME_FAILURE",
        "AGENT_UNDERPERFORMANCE",
        "VARIANCE_CLUSTER",
        "DISAGREEMENT_FAILURE",
    ] = Field(description="High-level category of the observed pattern")
    target_dimension: str = Field(
        min_length=1,
        description="Evaluated dimension name (e.g. 'regime', 'agent_id', 'variance_driver')",
    )
    target_value: str = Field(
        min_length=1,
        description="Specific dimension value under test (e.g. 'HIGH_VOLATILITY', 'bad_timing')",
    )
    sample_size: int = Field(
        gt=0,
        description="Number of completed trades in this specific pattern cluster",
    )
    total_trades_analyzed: int = Field(
        gt=0,
        description="Total background population of completed trades in evaluation batch",
    )
    failure_count: int = Field(
        ge=0,
        description="Count of losing / negative net PnL trades in this cluster",
    )
    win_rate: float = Field(
        ge=0.0,
        le=1.0,
        description="Observed win rate fraction within this cluster",
    )
    baseline_win_rate: float = Field(
        ge=0.0,
        le=1.0,
        description="Overall population win rate across the entire evaluation batch",
    )
    mean_pnl: Decimal = Field(
        description="Average net PnL in INR per trade for this cluster",
    )
    baseline_mean_pnl: Decimal = Field(
        description="Average net PnL in INR per trade across entire evaluation batch",
    )
    p_value: float = Field(
        ge=0.0,
        le=1.0,
        description="One-tailed p-value for statistical significance of underperformance",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Statistical confidence level (1.0 - p_value)",
    )
    is_statistically_significant: bool = Field(
        description="True if p_value <= alpha threshold and sample_size >= min_sample_size",
    )
    status: Literal["CONFIRMED_HYPOTHESIS", "OBSERVED_UNCONFIRMED"] = Field(
        description="CONFIRMED_HYPOTHESIS if evidence bar cleared; else OBSERVED_UNCONFIRMED",
    )
    description: str = Field(
        min_length=1,
        description="Diagnostic narrative summarizing observed anomaly",
    )
    detected_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Detection timestamp in UTC",
    )

    @field_validator("detected_at")
    @classmethod
    def validate_utc_timestamp(cls, v: datetime) -> datetime:
        """Enforce that detection timestamp is timezone-aware UTC."""
        if v.tzinfo is None:
            msg = "ObservedPattern detected_at must be timezone-aware UTC"
            raise ValueError(msg)
        return v
