"""Downstream trading suppression gate blocking actions on quarantined or stale market data."""

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

import structlog
from pydantic import BaseModel, ConfigDict, Field

from src.data.staleness_monitor import StalenessMonitor
from src.domain.decision import DecisionRecord
from src.domain.market_data import OHLCVCandle

logger = structlog.get_logger(__name__)


class SuppressionResult(BaseModel):
    """Immutable evaluation result determining whether downstream inference must be suppressed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    should_suppress: bool = Field(
        description="True if trading decision evaluation must be short-circuited"
    )
    action: Literal["ALLOW", "SUPPRESS"] = Field(
        description="Action allowed for the downstream Decision Engine"
    )
    forced_decision: Literal["NO_TRADE", "HOLD"] | None = Field(
        default=None,
        description="Forced fail-safe decision if suppressed, None if allowed",
    )
    reason: str | None = Field(
        default=None, description="Detailed explanation for suppression trigger"
    )
    data_quality: Literal["VALIDATED", "QUARANTINED", "STALE", "RAW"] = Field(
        description="Evaluated market data hygiene state"
    )
    details: dict[str, Any] = Field(
        default_factory=dict, description="Diagnostic telemetry and metrics"
    )


class SuppressionGate:
    """Deterministic suppression gate protecting system from stale or quarantined data.

    Per FRD-DATA-9, RTLD §11, and HLD §7, any corrupted or stale market feed must immediately
    prevent trading signals from reaching the Risk Engine, compelling a NO_TRADE outcome.
    """

    def __init__(
        self,
        *,
        staleness_monitor: StalenessMonitor | None = None,
        default_forced_decision: Literal["NO_TRADE", "HOLD"] = "NO_TRADE",
    ) -> None:
        """Initialize suppression gate with optional feed staleness monitor.

        Args:
            staleness_monitor: Optional staleness monitor for real-time SLA feed checks.
            default_forced_decision: Deterministic fallback decision (default NO_TRADE).
        """
        self.staleness_monitor = staleness_monitor
        self.default_forced_decision = default_forced_decision

    def evaluate_candle(
        self,
        candle: OHLCVCandle,
        current_time: datetime | None = None,
    ) -> SuppressionResult:
        """Inspect candle quality state and real-time staleness to authorize or suppress trading.

        Args:
            candle: Candidate OHLCVCandle to inspect.
            current_time: Optional evaluation timestamp (UTC).

        Returns:
            SuppressionResult with ALLOW or SUPPRESS verdict and forced decision.
        """
        # 1. Immediate suppression on explicit quarantine state
        if candle.quality_state == "QUARANTINED":
            logger.warning(
                "trade_suppressed_quarantine",
                instrument=candle.instrument,
                quality_state=candle.quality_state,
            )
            return SuppressionResult(
                should_suppress=True,
                action="SUPPRESS",
                forced_decision=self.default_forced_decision,
                reason="DATA_QUALITY_QUARANTINED",
                data_quality="QUARANTINED",
                details={"candle_timestamp": candle.timestamp.isoformat()},
            )

        # 2. Immediate suppression on raw unvalidated state
        if candle.quality_state == "RAW":
            logger.warning(
                "trade_suppressed_unvalidated_raw",
                instrument=candle.instrument,
                quality_state=candle.quality_state,
            )
            return SuppressionResult(
                should_suppress=True,
                action="SUPPRESS",
                forced_decision=self.default_forced_decision,
                reason="DATA_QUALITY_RAW",
                data_quality="RAW",
                details={"candle_timestamp": candle.timestamp.isoformat()},
            )

        # 3. Immediate suppression on explicitly stale candle
        if candle.quality_state == "STALE":
            logger.warning(
                "trade_suppressed_stale_candle",
                instrument=candle.instrument,
                quality_state=candle.quality_state,
            )
            return SuppressionResult(
                should_suppress=True,
                action="SUPPRESS",
                forced_decision=self.default_forced_decision,
                reason="DATA_QUALITY_STALE",
                data_quality="STALE",
                details={"candle_timestamp": candle.timestamp.isoformat()},
            )

        # 4. Real-time feed staleness SLA monitor check
        if self.staleness_monitor is not None:
            now = current_time or datetime.now(UTC)
            staleness = self.staleness_monitor.check_staleness(candle.instrument, current_time=now)
            if staleness.is_stale:
                reason = f"FEED_STALE_{staleness.reason or 'TIMEOUT'}"
                logger.warning(
                    "trade_suppressed_feed_staleness",
                    instrument=candle.instrument,
                    elapsed_seconds=staleness.elapsed_seconds,
                    threshold_seconds=staleness.threshold_seconds,
                    reason=reason,
                )
                return SuppressionResult(
                    should_suppress=True,
                    action="SUPPRESS",
                    forced_decision=self.default_forced_decision,
                    reason=reason,
                    data_quality="STALE",
                    details={
                        "elapsed_seconds": staleness.elapsed_seconds,
                        "threshold_seconds": staleness.threshold_seconds,
                        "checked_at": staleness.checked_at.isoformat(),
                    },
                )

        # 5. Clean validated data authorized for inference
        return SuppressionResult(
            should_suppress=False,
            action="ALLOW",
            forced_decision=None,
            reason=None,
            data_quality="VALIDATED",
            details={"candle_timestamp": candle.timestamp.isoformat()},
        )

    def create_suppressed_decision(
        self,
        instrument: str,
        suppression_result: SuppressionResult,
        timestamp: datetime | None = None,
        git_commit: str = "unknown",
    ) -> DecisionRecord:
        """Construct an immutable, SHA-256 stamped DecisionRecord for a suppressed cycle.

        Args:
            instrument: Canonical instrument symbol.
            suppression_result: Result from evaluate_candle triggering suppression.
            timestamp: Optional cycle timestamp in UTC.
            git_commit: Source code version identifier.

        Returns:
            Deterministic DecisionRecord documenting the forced NO_TRADE action.
        """
        ts = timestamp or datetime.now(UTC)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)

        forced_action = suppression_result.forced_decision or "NO_TRADE"

        record = DecisionRecord(
            decision_record_id=uuid4(),
            timestamp=ts,
            instrument=instrument.strip().upper(),
            decision=forced_action,
            regime="DATA_SUPPRESSED",
            agent_scores={},
            aggregated_score=0.0,
            risk_result={
                "suppressed": True,
                "reason": suppression_result.reason,
                "data_quality": suppression_result.data_quality,
                "details": suppression_result.details,
            },
            approved_quantity=0,
            stop_loss_price=None,
            target_price=None,
            git_commit=git_commit,
        )

        canonical_hash = record.calculate_canonical_hash()
        return record.model_copy(update={"decision_hash": canonical_hash})
