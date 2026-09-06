"""Master decision record domain model enforcing 100% auditability and SHA-256 hash stamping."""

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
