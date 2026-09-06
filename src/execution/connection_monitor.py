"""Broker connection health monitor and disconnection handler.

Implements broker connection state tracking, heartbeat evaluation,
and safe-state circuit breakers per:
- FRD-EXEC-6 (broker connectivity and connection health monitoring)
- FRD-EXEC-10 (timestamped audit logging of connection state changes)
- NFR-REL-4 (broker reconnection window before escalation)
- RTLD §11 / RTLD-15 (30-second disconnection timeout before escalation)
- EDD §9 (safe-state hold and suppression of new orders during broker outages)
- LLD §9.3 (broker disconnection handling and health reporting)
"""

import asyncio
import threading
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

import structlog
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.execution.broker_adapter import BrokerAdapter

logger = structlog.get_logger(__name__)

ConnectionState = Literal["CONNECTED", "DEGRADED", "DISCONNECTED", "CIRCUIT_OPEN"]


class ConnectionMonitorConfig(BaseModel):
    """Configuration settings for broker connection health monitor."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    heartbeat_interval_seconds: float = Field(
        default=5.0, gt=0, description="Interval between periodic heartbeat checks in seconds"
    )
    degraded_threshold_seconds: float = Field(
        default=10.0, gt=0, description="Elapsed silence before transitioning to DEGRADED"
    )
    disconnection_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        description="RTLD-15 / NFR-REL-4 outage deadline in seconds triggering CIRCUIT_OPEN",
    )
    max_consecutive_failures: int = Field(
        default=3, gt=0, description="Consecutive failed heartbeats before DISCONNECTED state"
    )
    auto_reset_on_reconnect: bool = Field(
        default=False,
        description=(
            "If False (safe default per RTLD §11 / EDD §9), recovery from CIRCUIT_OPEN "
            "requires manual operator reset"
        ),
    )


class ConnectionEvent(BaseModel):
    """Immutable audit record capturing connection status changes (FRD-EXEC-6, FRD-EXEC-10)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: UUID = Field(
        default_factory=uuid4, description="Unique primary key for the connection event"
    )
    previous_state: ConnectionState = Field(description="Previous connection state")
    new_state: ConnectionState = Field(description="New connection state")
    reason: str = Field(description="Detailed reason or failure message for the transition")
    consecutive_failures: int = Field(
        default=0, ge=0, description="Number of consecutive heartbeat failures at event time"
    )
    downtime_seconds: float = Field(
        default=0.0, ge=0.0, description="Cumulative downtime in seconds if disconnected"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Event generation timestamp in UTC",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Arbitrary diagnostic metadata"
    )

    @field_validator("timestamp")
    @classmethod
    def validate_utc_timestamp(cls, v: datetime) -> datetime:
        """Enforce timezone-aware UTC timestamp."""
        if v.tzinfo is None:
            msg = "Connection event timestamp must be timezone-aware UTC"
            raise ValueError(msg)
        return v


class ConnectionMonitor:
    """Monitors broker connection health, heartbeat frequency, and outage escalation.

    Enforces 30-second disconnection timeout (NFR-REL-4, RTLD-15, EDD §9),
    tripping the circuit breaker to prevent trading on unconfirmed broker state.
    """

    def __init__(self, config: ConnectionMonitorConfig | None = None) -> None:
        self.config = config or ConnectionMonitorConfig()
        self._state: ConnectionState = "CONNECTED"
        self._last_heartbeat_time: datetime | None = None
        self._disconnection_start_time: datetime | None = None
        self._consecutive_failures: int = 0
        self._is_circuit_open: bool = False
        self._history: list[ConnectionEvent] = []
        self._lock = threading.Lock()
        self._log = logger.bind(component="ConnectionMonitor")

    @property
    def state(self) -> ConnectionState:
        """Return the current connection state."""
        with self._lock:
            return self._state

    @property
    def is_healthy(self) -> bool:
        """Return True if connection is fully healthy and CONNECTED."""
        with self._lock:
            return self._state == "CONNECTED"

    @property
    def is_circuit_open(self) -> bool:
        """Return True if disconnection circuit breaker has tripped."""
        with self._lock:
            return self._is_circuit_open

    @property
    def consecutive_failures(self) -> int:
        """Return count of consecutive failed heartbeat checks."""
        with self._lock:
            return self._consecutive_failures

    @property
    def last_heartbeat_time(self) -> datetime | None:
        """Return timestamp of the last successful heartbeat in UTC."""
        with self._lock:
            return self._last_heartbeat_time

    @property
    def disconnection_start_time(self) -> datetime | None:
        """Return timestamp when disconnection was first detected."""
        with self._lock:
            return self._disconnection_start_time

    @property
    def downtime_seconds(self) -> float:
        """Return current cumulative disconnection duration in seconds."""
        with self._lock:
            if self._disconnection_start_time is None:
                return 0.0
            return (datetime.now(UTC) - self._disconnection_start_time).total_seconds()

    @property
    def history(self) -> list[ConnectionEvent]:
        """Return copy of the full connection event audit trail."""
        with self._lock:
            return list(self._history)

    def clear(self) -> None:
        """Reset internal state to clean initial defaults (for test isolation)."""
        with self._lock:
            self._state = "CONNECTED"
            self._last_heartbeat_time = None
            self._disconnection_start_time = None
            self._consecutive_failures = 0
            self._is_circuit_open = False
            self._history.clear()

    def should_suppress_trading(self) -> bool:
        """Check if current connection state mandates suppressing new orders (EDD §9).

        Returns:
            bool: True if trading must be suppressed (CIRCUIT_OPEN or DISCONNECTED).
        """
        with self._lock:
            return self._is_circuit_open or self._state in ("CIRCUIT_OPEN", "DISCONNECTED")

    def record_heartbeat_success(self, *, timestamp: datetime | None = None) -> ConnectionState:
        """Record a successful heartbeat from the broker adapter.

        Args:
            timestamp: Optional UTC timestamp of the heartbeat (defaults to UTC now).

        Returns:
            ConnectionState: Resulting connection state.
        """
        now = timestamp or datetime.now(UTC)
        with self._lock:
            self._last_heartbeat_time = now
            self._consecutive_failures = 0

            # If circuit is already open, evaluate auto-reset policy
            if self._is_circuit_open:
                if self.config.auto_reset_on_reconnect:
                    self._is_circuit_open = False
                    downtime = (
                        (now - self._disconnection_start_time).total_seconds()
                        if self._disconnection_start_time
                        else 0.0
                    )
                    self._disconnection_start_time = None
                    self._transition_state_locked(
                        new_state="CONNECTED",
                        reason="Broker reconnected; circuit automatically reset",
                        downtime_seconds=downtime,
                        timestamp=now,
                    )
                else:
                    self._log.warning(
                        "Heartbeat succeeded but CIRCUIT_OPEN safe-state hold remains active",
                        reason="Manual operator reset required per RTLD §11 / EDD §9",
                    )
                return self._state

            # If recovering from DEGRADED or DISCONNECTED
            if self._state != "CONNECTED":
                downtime = (
                    (now - self._disconnection_start_time).total_seconds()
                    if self._disconnection_start_time
                    else 0.0
                )
                self._disconnection_start_time = None
                self._transition_state_locked(
                    new_state="CONNECTED",
                    reason="Broker heartbeat restored",
                    downtime_seconds=downtime,
                    timestamp=now,
                )

            return self._state

    def record_heartbeat_failure(
        self,
        *,
        reason: str = "Broker heartbeat check failed",
        timestamp: datetime | None = None,
    ) -> ConnectionState:
        """Record a failed heartbeat check and evaluate outage thresholds.

        Args:
            reason: Description of heartbeat error or exception.
            timestamp: Optional UTC timestamp (defaults to UTC now).

        Returns:
            ConnectionState: Resulting connection state.
        """
        now = timestamp or datetime.now(UTC)
        with self._lock:
            self._consecutive_failures += 1
            if self._disconnection_start_time is None:
                self._disconnection_start_time = now

            downtime = (now - self._disconnection_start_time).total_seconds()

            # Check if 30-second outage threshold is reached (NFR-REL-4, RTLD-15)
            if downtime >= self.config.disconnection_timeout_seconds:
                self._is_circuit_open = True
                if self._state != "CIRCUIT_OPEN":
                    msg = (
                        f"Broker disconnected for {downtime:.1f}s >= "
                        f"{self.config.disconnection_timeout_seconds}s: {reason}"
                    )
                    self._transition_state_locked(
                        new_state="CIRCUIT_OPEN",
                        reason=msg,
                        downtime_seconds=downtime,
                        timestamp=now,
                    )
            elif self._consecutive_failures >= self.config.max_consecutive_failures:
                if self._state not in ("DISCONNECTED", "CIRCUIT_OPEN"):
                    msg = (
                        f"Exceeded {self.config.max_consecutive_failures} "
                        f"consecutive failures: {reason}"
                    )
                    self._transition_state_locked(
                        new_state="DISCONNECTED",
                        reason=msg,
                        downtime_seconds=downtime,
                        timestamp=now,
                    )
            elif self._state == "CONNECTED":
                self._transition_state_locked(
                    new_state="DEGRADED",
                    reason=reason,
                    downtime_seconds=downtime,
                    timestamp=now,
                )

            return self._state

    def check_health(self, *, current_time: datetime | None = None) -> ConnectionState:
        """Evaluate elapsed silence and enforce disconnection deadlines (NFR-REL-4, RTLD-15).

        Args:
            current_time: Optional current time (defaults to UTC now).

        Returns:
            ConnectionState: Current evaluated connection state.
        """
        now = current_time or datetime.now(UTC)
        with self._lock:
            # If already circuit open, state is maintained until reset
            if self._is_circuit_open:
                return self._state

            # If disconnected start time exists, check downtime
            if self._disconnection_start_time is not None:
                downtime = (now - self._disconnection_start_time).total_seconds()
                if downtime >= self.config.disconnection_timeout_seconds:
                    self._is_circuit_open = True
                    msg = f"Disconnection duration {downtime:.1f}s reached 30s threshold (RTLD-15)"
                    self._transition_state_locked(
                        new_state="CIRCUIT_OPEN",
                        reason=msg,
                        downtime_seconds=downtime,
                        timestamp=now,
                    )
                    return self._state

            # If we had a prior heartbeat, check silence elapsed since last heartbeat
            if self._last_heartbeat_time is not None:
                silence_seconds = (now - self._last_heartbeat_time).total_seconds()
                if silence_seconds >= self.config.disconnection_timeout_seconds:
                    if self._disconnection_start_time is None:
                        self._disconnection_start_time = self._last_heartbeat_time
                    downtime = (now - self._disconnection_start_time).total_seconds()
                    self._is_circuit_open = True
                    msg = f"Broker silent for {silence_seconds:.1f}s >= 30s threshold (RTLD-15)"
                    self._transition_state_locked(
                        new_state="CIRCUIT_OPEN",
                        reason=msg,
                        downtime_seconds=downtime,
                        timestamp=now,
                    )
                elif silence_seconds >= self.config.degraded_threshold_seconds:
                    if self._state == "CONNECTED":
                        self._disconnection_start_time = now
                        msg = (
                            f"Heartbeat silence {silence_seconds:.1f}s exceeded degraded threshold"
                        )
                        self._transition_state_locked(
                            new_state="DEGRADED",
                            reason=msg,
                            downtime_seconds=silence_seconds,
                            timestamp=now,
                        )

            return self._state

    def reset_safe_state(
        self,
        *,
        operator_id: str,
        reason: str,
        timestamp: datetime | None = None,
    ) -> None:
        """Operator-authorized manual reset of CIRCUIT_OPEN safe-state hold (RTLD §11, EDD §9).

        Args:
            operator_id: Identifier of the authorized human operator.
            reason: Justification for resetting the safe state.
            timestamp: Optional UTC timestamp (defaults to UTC now).

        Raises:
            ValueError: If operator_id or reason is blank.
        """
        if not operator_id.strip():
            msg = "operator_id must not be empty"
            raise ValueError(msg)
        if not reason.strip():
            msg = "reason for reset must not be empty"
            raise ValueError(msg)

        now = timestamp or datetime.now(UTC)
        with self._lock:
            old_state = self._state
            self._is_circuit_open = False
            self._disconnection_start_time = None
            self._consecutive_failures = 0
            self._state = "CONNECTED"

            event = ConnectionEvent(
                previous_state=old_state,
                new_state="CONNECTED",
                reason=f"Manual operator reset: {reason}",
                consecutive_failures=0,
                downtime_seconds=0.0,
                timestamp=now,
                metadata={"operator_id": operator_id, "reset_reason": reason},
            )
            self._history.append(event)
            self._log.info(
                "Operator reset safe-state hold",
                operator_id=operator_id,
                reason=reason,
                previous_state=old_state,
            )

    async def poll_broker_heartbeat(
        self,
        broker: BrokerAdapter,
        *,
        timeout_seconds: float = 5.0,
    ) -> bool:
        """Asynchronously query broker liveness and update connection health state.

        Args:
            broker: Target BrokerAdapter instance to inspect.
            timeout_seconds: Max seconds to await broker response.

        Returns:
            bool: True if broker returned healthy response, False otherwise.
        """
        try:
            is_alive = await asyncio.wait_for(
                asyncio.to_thread(broker.heartbeat),
                timeout=timeout_seconds,
            )
            if is_alive:
                self.record_heartbeat_success()
                return True

            self.record_heartbeat_failure(reason="Broker heartbeat returned False")
            return False
        except TimeoutError:
            self.record_heartbeat_failure(
                reason=f"Broker heartbeat query timed out after {timeout_seconds}s"
            )
            return False
        except Exception as exc:
            self.record_heartbeat_failure(reason=f"Broker heartbeat error: {exc}")
            return False

    def _transition_state_locked(
        self,
        *,
        new_state: ConnectionState,
        reason: str,
        downtime_seconds: float = 0.0,
        timestamp: datetime | None = None,
    ) -> None:
        """Internal helper to record state change and audit event under lock."""
        now = timestamp or datetime.now(UTC)
        old_state = self._state
        self._state = new_state

        event = ConnectionEvent(
            previous_state=old_state,
            new_state=new_state,
            reason=reason,
            consecutive_failures=self._consecutive_failures,
            downtime_seconds=downtime_seconds,
            timestamp=now,
        )
        self._history.append(event)
        self._log.info(
            "Connection state transitioned",
            previous_state=old_state,
            new_state=new_state,
            reason=reason,
            failures=self._consecutive_failures,
            downtime_seconds=downtime_seconds,
        )
