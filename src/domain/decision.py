"""Master decision record domain model enforcing 100% auditability and SHA-256 hash stamping."""

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.domain.risk import RiskCheckResult


class Decision(BaseModel):
    """Final decision emitted by the Supervisor for order translation and execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: Literal["BUY", "SELL", "HOLD", "NO_TRADE"] = Field(
        description="Final action decided by the Supervisor"
    )
    reason: str = Field(description="Deterministic justification for the decision")
    risk_check: RiskCheckResult = Field(
        description="Risk verification snapshot evaluated by the Risk Engine"
    )
    kill_switch_active: bool = Field(
        default=False, description="Whether kill switch was active during decision"
    )
    approved_quantity: int = Field(
        default=0, ge=0, description="Risk-approved position quantity (0 for NO_TRADE or HOLD)"
    )
    stop_loss_price: Decimal | None = Field(
        default=None, description="Deterministic hard stop-loss price"
    )
    target_price: Decimal | None = Field(default=None, description="Profit target price level")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Decision generation timestamp in UTC",
    )

    @field_validator("timestamp")
    @classmethod
    def validate_utc_timestamp(cls, v: datetime) -> datetime:
        """Enforce that timestamp is timezone-aware UTC."""
        if v.tzinfo is None:
            msg = "Decision timestamp must be timezone-aware UTC"
            raise ValueError(msg)
        return v

    @property
    def is_trade_approved(self) -> bool:
        """Return True if decision is an actionable BUY or SELL trade."""
        return self.outcome in ("BUY", "SELL") and self.approved_quantity > 0


class DecisionRecord(BaseModel):
    """Immutable audit contract capturing the end-to-end trading decision cycle."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_record_id: UUID = Field(
        default_factory=uuid4, description="Unique primary key for the decision record"
    )
    timestamp: datetime = Field(description="Decision generation timestamp in UTC")
    instrument: str = Field(min_length=1, description="Instrument traded")
    decision: Literal["BUY", "SELL", "HOLD", "NO_TRADE"] = Field(
        description="Final action selected by the system"
    )
    regime: str = Field(description="Market regime classified during this cycle")
    agent_scores: dict[str, float] = Field(
        description="Individual opportunity scores expressed by trading agents"
    )
    aggregated_score: float = Field(
        description="Weighted consensus score produced by the Aggregator"
    )
    risk_result: dict[str, Any] = Field(
        description="Deterministic risk engine verification snapshot"
    )
    approved_quantity: int = Field(
        ge=0, description="Risk-approved position quantity (0 for NO_TRADE or HOLD)"
    )
    stop_loss_price: Decimal | None = Field(
        default=None, description="Deterministic hard stop-loss price"
    )
    target_price: Decimal | None = Field(default=None, description="Profit target price level")
    timeframe: str = Field(default="1m", description="Timeframe of the decision candle")
    environment: Literal["research", "paper", "live"] = Field(
        default="paper", description="Operating environment"
    )
    data_quality_state: Literal["VALIDATED", "STALE", "QUARANTINED"] = Field(
        default="VALIDATED", description="Data quality state"
    )
    disagreement_metric: float = Field(
        default=0.0, description="Agent opportunity disagreement metric"
    )
    expected_value: Decimal = Field(
        default=Decimal("0.0000"), description="Mathematical expected trade value"
    )
    client_order_id: str | None = Field(
        default=None, description="Linked client order ID if dispatched"
    )
    reason: str = Field(default="", description="Decision justification / rationale")
    inputs_used: dict[str, Any] = Field(
        default_factory=dict, description="Raw model and market inputs used"
    )
    features: dict[str, float] = Field(
        default_factory=dict, description="Derived features computed for this cycle"
    )
    config_version: str = Field(default="0.1.0", description="Active RiskConfig version tag")
    git_commit: str = Field(default="unknown", description="Source code git commit hash")
    decision_hash: str | None = Field(
        default=None, description="Cryptographic SHA-256 checksum over record fields"
    )

    @field_validator("timestamp")
    @classmethod
    def validate_utc_timestamp(cls, v: datetime) -> datetime:
        """Enforce that timestamp is timezone-aware."""
        if v.tzinfo is None:
            msg = "Decision timestamp must be timezone-aware UTC"
            raise ValueError(msg)
        return v

    def calculate_canonical_hash(self) -> str:
        """Compute deterministic SHA-256 hash for tamper-evident audit storage."""
        canonical_data = {
            "decision_record_id": str(self.decision_record_id),
            "timestamp": self.timestamp.isoformat(),
            "instrument": self.instrument,
            "decision": self.decision,
            "regime": self.regime,
            "agent_scores": {k: float(v) for k, v in sorted(self.agent_scores.items())},
            "aggregated_score": float(self.aggregated_score),
            "approved_quantity": self.approved_quantity,
            "stop_loss_price": str(self.stop_loss_price) if self.stop_loss_price else None,
            "target_price": str(self.target_price) if self.target_price else None,
            "config_version": self.config_version,
            "git_commit": self.git_commit,
        }
        encoded = json.dumps(canonical_data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
