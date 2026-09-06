"""Canonical domain models and enumerations for 5-dimensional market regime intelligence."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TrendState(StrEnum):
    """Canonical trend classification state based on directional strength (MLD §5.1)."""

    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING = "RANGING"
    UNKNOWN = "UNKNOWN"


class VolatilityLevel(StrEnum):
    """Canonical volatility classification level based on rolling percentile rank (MLD §5.1)."""

    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class DirectionalBias(StrEnum):
    """Canonical directional bias combining trend state and return momentum (MLD §5.1)."""

    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"


class LiquidityCondition(StrEnum):
    """Canonical liquidity condition relative to trailing session volume (MLD §5.1)."""

    NORMAL = "NORMAL"
    DEGRADED = "DEGRADED"
    UNKNOWN = "UNKNOWN"


class RiskSentiment(StrEnum):
    """Canonical macro/cross-asset risk sentiment state (MLD §5.1)."""

    RISK_ON = "RISK_ON"
    RISK_OFF = "RISK_OFF"
    UNKNOWN = "UNKNOWN"


class RegimeClassification(BaseModel):
    """Immutable, strongly-typed classification snapshot across all 5 regime dimensions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    classification_id: UUID = Field(
        default_factory=uuid4,
        description="Unique identifier for this regime classification event",
    )
    instrument: str = Field(min_length=1, description="Canonical instrument symbol")
    timeframe: str = Field(min_length=1, description="Primary timeframe of underlying data")
    timestamp: datetime = Field(description="Point-in-time calculation cutoff timestamp in UTC")
    trend_state: TrendState = Field(description="Primary trend classification state")
    volatility_level: VolatilityLevel = Field(
        description="Trailing volatility percentile classification"
    )
    directional_bias: DirectionalBias = Field(
        description="Directional bias (enforces NEUTRAL when RANGING)"
    )
    liquidity_condition: LiquidityCondition = Field(
        description="Volume/liquidity adequacy relative to trailing baseline"
    )
    risk_sentiment: RiskSentiment = Field(
        default=RiskSentiment.UNKNOWN,
        description="Cross-asset/macro risk sentiment state (defaults to UNKNOWN)",
    )
    regime_label: str = Field(
        min_length=1,
        description="Composite canonical regime string for logging and decision records",
    )
    is_transition: bool = Field(
        default=False,
        description="True if this cycle represents a confirmed transition from previous regime",
    )
    previous_regime: str | None = Field(
        default=None,
        description="Prior confirmed composite regime label if is_transition is True",
    )
    metrics: dict[str, float] = Field(
        default_factory=dict,
        description="Underlying numeric indicator values and percentiles that drove classification",
    )
    feature_set_id: UUID | None = Field(
        default=None,
        description="Unique ID of the parent FeatureSet used for inference",
    )

    @field_validator("timestamp")
    @classmethod
    def validate_utc_timestamp(cls, v: datetime) -> datetime:
        """Enforce that timestamp is timezone-aware UTC."""
        if v.tzinfo is None:
            msg = "Regime classification timestamp must be timezone-aware UTC"
            raise ValueError(msg)
        return v
