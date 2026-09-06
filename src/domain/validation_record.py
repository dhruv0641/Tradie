"""Domain models for multi-stage model validation runs and gate assessments.

Conforms to FRD-LEARN-3, FRD-LEARN-8, ADD §8.2, and MLD §9, §10.
"""

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

ValidationStageType = Literal[
    "HISTORICAL_BACKTEST",
    "OUT_OF_SAMPLE",
    "WALK_FORWARD",
    "STRESS_TEST",
    "PARAMETER_PERTURBATION",
    "PAPER_TRADING",
]


class ValidationStageResult(BaseModel):
    """Evaluation result for an individual validation gate in the 6-stage sequence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    stage_name: ValidationStageType = Field(description="Name of the validation gate stage")
    stage_index: int = Field(ge=1, le=6, description="1-indexed sequence order of stage")
    passed: bool = Field(description="True if stage met or exceeded required thresholds")
    metrics: dict[str, Any] = Field(
        default_factory=dict,
        description="Measured quantitative metrics for this stage",
    )
    thresholds: dict[str, Any] = Field(
        default_factory=dict,
        description="Governing thresholds required to pass this stage",
    )
    failure_reason: str | None = Field(
        default=None,
        description="Detailed diagnostic explanation if stage failed",
    )
    evaluated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Evaluation timestamp in UTC",
    )

    @field_validator("evaluated_at")
    @classmethod
    def validate_utc_timestamp(cls, v: datetime) -> datetime:
        """Enforce timezone awareness in UTC."""
        if v.tzinfo is None:
            msg = "ValidationStageResult evaluated_at must be timezone-aware UTC"
            raise ValueError(msg)
        return v


class ValidationRunRecord(BaseModel):
    """Consolidated record of a complete 6-stage validation pipeline run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: UUID = Field(
        default_factory=uuid4,
        description="Unique identifier for this validation pipeline run",
    )
    model_id: str = Field(min_length=1, description="Identifier of evaluated candidate model")
    candidate_hash: str = Field(
        min_length=32,
        description="SHA-256 hash of candidate parameters/model artifact",
    )
    stages: list[ValidationStageResult] = Field(
        default_factory=list,
        description="Sequential list of executed validation stage results",
    )
    overall_passed: bool = Field(
        description="True if candidate cleared all 6 stages; False if any failed",
    )
    halted_stage_index: int | None = Field(
        default=None,
        description="Stage index (1..6) where pipeline halted on failure; None if all passed",
    )
    rejection_reason: str | None = Field(
        default=None,
        description="Summary explanation for rejection if overall_passed is False",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Run completion timestamp in UTC",
    )

    @field_validator("created_at")
    @classmethod
    def validate_utc_timestamp(cls, v: datetime) -> datetime:
        """Enforce timezone awareness in UTC."""
        if v.tzinfo is None:
            msg = "ValidationRunRecord created_at must be timezone-aware UTC"
            raise ValueError(msg)
        return v
