"""Domain models for model promotion and automated rollback lifecycle events.

Conforms to FRD-LEARN-4, FRD-LEARN-5, FRD-LEARN-7, ADD §8.3, §8.4, and SLD §7.
"""

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PromotionEvent(BaseModel):
    """Immutable audit record of a model promotion decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: UUID = Field(
        default_factory=uuid4,
        description="Unique identifier for this promotion event",
    )
    candidate_id: str = Field(
        min_length=1,
        description="Model ID of candidate evaluated for promotion",
    )
    baseline_id: str | None = Field(
        default=None,
        description="Model ID of superseded baseline model, if any",
    )
    validation_run_id: UUID = Field(
        description="Foreign key to passed ValidationRunRecord",
    )
    promoted: bool = Field(
        description="True if model was promoted; False if promotion was rejected",
    )
    promoted_by: str = Field(
        min_length=1,
        description="Operator identifier or cryptographic sign-off token",
    )
    metrics_comparison: dict[str, Any] = Field(
        default_factory=dict,
        description="Comparative metrics between candidate and baseline",
    )
    rejection_reasons: list[str] = Field(
        default_factory=list,
        description="Detailed failure reasons if promotion was rejected",
    )
    notes: str = Field(
        default="",
        description="Operator rationale and promotion notes",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Promotion event timestamp in UTC",
    )

    @field_validator("timestamp")
    @classmethod
    def validate_utc_timestamp(cls, v: datetime) -> datetime:
        """Enforce timezone awareness in UTC."""
        if v.tzinfo is None:
            msg = "PromotionEvent timestamp must be timezone-aware UTC"
            raise ValueError(msg)
        return v


class RollbackEvent(BaseModel):
    """Immutable audit record of an automated production model reversion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: UUID = Field(
        default_factory=uuid4,
        description="Unique identifier for this rollback event",
    )
    failed_model_id: str = Field(
        min_length=1,
        description="Model ID of active model that degraded and was demoted",
    )
    restored_model_id: str = Field(
        min_length=1,
        description="Model ID of previous model restored to active status",
    )
    trigger_reason: Literal[
        "DRAWDOWN_BREACH",
        "ROLLING_SHARPE_DROP",
        "CONSECUTIVE_LOSSES",
        "WIN_RATE_COLLAPSE",
    ] = Field(description="Primary statistical degradation trigger forcing rollback")
    evidence: dict[str, Any] = Field(
        default_factory=dict,
        description="Empirical metrics triggering the rollback",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Rollback trigger timestamp in UTC",
    )
    notes: str = Field(
        default="",
        description="Automated system diagnostic notes",
    )

    @field_validator("timestamp")
    @classmethod
    def validate_utc_timestamp(cls, v: datetime) -> datetime:
        """Enforce timezone awareness in UTC."""
        if v.tzinfo is None:
            msg = "RollbackEvent timestamp must be timezone-aware UTC"
            raise ValueError(msg)
        return v
