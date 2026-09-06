"""Canonical domain models for trading agent signal generation."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SignalDirection(StrEnum):
    """Directional view emitted by a trading intelligence agent (ADD §4, MLD §6)."""

    LONG = "LONG"
    SHORT = "SHORT"
    NO_VIEW = "NO_VIEW"


class AgentSignalOutput(BaseModel):
    """Immutable, strongly-typed output contract emitted by all trading intelligence agents.

    Adheres to ADD §4, LLD §8.1, and subsystem-contracts.md §2.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_id: str = Field(min_length=1, description="Canonical identifier of the producing agent")
    direction: SignalDirection = Field(
        description="Directional conviction: LONG, SHORT, or NO_VIEW"
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Normalized confidence score strictly bounded in [0.0, 1.0]",
    )
    inputs_used: dict[str, float] = Field(
        default_factory=dict,
        description="Point-in-time features and indicator values used for inference",
    )
    timestamp: datetime = Field(description="Point-in-time calculation timestamp in UTC")
    raw_score: float | None = Field(
        default=None,
        description="Underlying unnormalized metric (e.g. z-score, ROC, distance) before scaling",
    )

    @field_validator("timestamp")
    @classmethod
    def validate_utc_timestamp(cls, v: datetime) -> datetime:
        """Enforce that timestamp is timezone-aware UTC."""
        if v.tzinfo is None:
            msg = "AgentSignalOutput timestamp must be timezone-aware UTC"
            raise ValueError(msg)
        return v

    @model_validator(mode="after")
    def validate_no_view_confidence(self) -> "AgentSignalOutput":
        """Enforce that NO_VIEW direction strictly carries 0.0 confidence (FRD-SIG-3)."""
        if self.direction == SignalDirection.NO_VIEW and self.confidence != 0.0:
            msg = "AgentSignalOutput with NO_VIEW direction must carry confidence=0.0"
            raise ValueError(msg)
        return self
