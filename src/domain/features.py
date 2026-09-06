"""Canonical feature set domain entities for machine learning and quantitative strategies."""

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FeatureSet(BaseModel):
    """Immutable, point-in-time quantitative feature vector for an instrument."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    feature_set_id: UUID = Field(
        default_factory=uuid4, description="Unique feature vector identifier"
    )
    instrument: str = Field(min_length=1, description="Canonical instrument symbol")
    timestamp: datetime = Field(description="Point-in-time calculation cutoff timestamp in UTC")
    timeframe: str = Field(min_length=1, description="Primary timeframe of the underlying data")
    features: dict[str, float] = Field(description="Named numerical feature values")
    feature_version: str = Field(
        default="feat-v1.0", description="Feature engineering pipeline version"
    )
    quality_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Completeness and quality score of features in [0, 1]",
    )

    @field_validator("timestamp")
    @classmethod
    def validate_utc_timestamp(cls, v: datetime) -> datetime:
        """Enforce that timestamp is timezone-aware."""
        if v.tzinfo is None:
            msg = "Feature timestamp must be timezone-aware UTC"
            raise ValueError(msg)
        return v
