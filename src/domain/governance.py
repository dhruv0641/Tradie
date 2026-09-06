"""Model governance and research-to-production promotion registry domain models."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ModelVersion(BaseModel):
    """Machine learning model version metadata and lifecycle promotion record."""

    model_config = ConfigDict(frozen=False, extra="forbid")

    model_id: str = Field(min_length=1, description="Unique model identifier")
    model_name: str = Field(min_length=1, description="Human-readable model name")
    version_tag: str = Field(min_length=1, description="Semantic version tag (e.g. v1.2.0)")
    model_hash: str = Field(min_length=32, description="SHA-256 hash of serialized model artifact")
    trained_at: datetime = Field(description="Training completion timestamp in UTC")
    status: Literal["candidate", "promoted", "rolled_back", "rejected", "superseded"] = Field(
        default="candidate", description="Current production governance state"
    )
    validation_metrics: dict[str, float] = Field(
        default_factory=dict,
        description="Out-of-sample statistical metrics (Sharpe, profit factor, max DD)",
    )
    promoted_by: str | None = Field(
        default=None, description="Operator or gate agent approving promotion"
    )
    promotion_timestamp: datetime | None = Field(
        default=None, description="Promotion approval timestamp in UTC"
    )
    hypothesis_id: str | None = Field(
        default=None, description="Linked hypothesis identifier motivating candidate"
    )
    source_pattern_id: str | None = Field(
        default=None, description="Foreign key to source ObservedPattern"
    )
    targeted_change: dict[str, Any] = Field(
        default_factory=dict, description="Scoped atomic parameter revision (SLD §6.2)"
    )
    scoping_notes: str = Field(default="", description="Scoping justification and rationale")

    @field_validator("trained_at", "promotion_timestamp")
    @classmethod
    def validate_utc_timestamp(cls, v: datetime | None) -> datetime | None:
        """Enforce timezone awareness in UTC."""
        if v is not None and v.tzinfo is None:
            msg = "Timestamp must be timezone-aware UTC"
            raise ValueError(msg)
        return v
