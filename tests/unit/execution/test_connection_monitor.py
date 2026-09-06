"""Unit tests for ConnectionMonitor, heartbeat tracking, and safe-state circuit breakers.

Verifies:
- FRD-EXEC-6 (broker connectivity and connection health monitoring)
- FRD-EXEC-10 (timestamped audit logging of connection state changes)
- NFR-REL-4 (reconnection window before escalation)
- RTLD §11 / RTLD-15 (30-second disconnection timeout before escalation)
- EDD §9 (safe-state hold and suppression of new orders during broker outages)
- LLD §9.3 (broker disconnection handling and health reporting)
"""

import time
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from src.execution.broker_adapter import BrokerAdapter, BrokerConnectionError
from src.execution.connection_monitor import (
    ConnectionEvent,
    ConnectionMonitor,
    ConnectionMonitorConfig,
)


def test_connection_monitor_initial_state() -> None:
    """Verify clean initial state of ConnectionMonitor."""
    monitor = ConnectionMonitor()
    assert monitor.state == "CONNECTED"
    assert monitor.is_healthy is True
    assert monitor.is_circuit_open is False
    assert monitor.consecutive_failures == 0
    assert monitor.last_heartbeat_time is None
    assert monitor.disconnection_start_time is None
    assert monitor.downtime_seconds == 0.0
    assert monitor.should_suppress_trading() is False
    assert monitor.history == []


def test_heartbeat_success_records_timestamp_and_maintains_connected() -> None:
    """Verify recording heartbeat success updates timestamp and maintains healthy state."""
    monitor = ConnectionMonitor()
    now = datetime.now(UTC)

    state = monitor.record_heartbeat_success(timestamp=now)
    assert state == "CONNECTED"
    assert monitor.last_heartbeat_time == now
    assert monitor.is_healthy is True
    assert monitor.consecutive_failures == 0
    assert monitor.should_suppress_trading() is False


def test_heartbeat_failure_progression_to_degraded_and_disconnected() -> None:
    """Verify failures advance from DEGRADED to DISCONNECTED per threshold config."""
    config = ConnectionMonitorConfig(max_consecutive_failures=3, disconnection_timeout_seconds=30.0)
    monitor = ConnectionMonitor(config)
    t0 = datetime.now(UTC)

    # 1st failure -> DEGRADED
    s1 = monitor.record_heartbeat_failure(reason="Network blip", timestamp=t0)
    assert s1 == "DEGRADED"
    assert monitor.is_healthy is False
    assert monitor.consecutive_failures == 1
    assert monitor.should_suppress_trading() is False

    # 2nd failure -> stays DEGRADED
    s2 = monitor.record_heartbeat_failure(reason="HTTP 502", timestamp=t0 + timedelta(seconds=2))
    assert s2 == "DEGRADED"
    assert monitor.consecutive_failures == 2
    assert monitor.should_suppress_trading() is False

    # 3rd failure (reaches max_consecutive_failures=3) -> DISCONNECTED
    s3 = monitor.record_heartbeat_failure(
        reason="Connection refused", timestamp=t0 + timedelta(seconds=4)
    )
    assert s3 == "DISCONNECTED"
    assert monitor.consecutive_failures == 3
    assert monitor.should_suppress_trading() is True

    # Audit log records all transitions
    assert len(monitor.history) == 2  # CONNECTED -> DEGRADED, then DEGRADED -> DISCONNECTED
    assert monitor.history[0].new_state == "DEGRADED"
    assert monitor.history[1].new_state == "DISCONNECTED"


def test_recovery_from_disconnected_under_30_seconds() -> None:
    """Verify recovery restores CONNECTED state when downtime is less than 30s."""
    monitor = ConnectionMonitor()
    t0 = datetime.now(UTC)

    monitor.record_heartbeat_failure(reason="F1", timestamp=t0)
    monitor.record_heartbeat_failure(reason="F2", timestamp=t0 + timedelta(seconds=2))
    monitor.record_heartbeat_failure(reason="F3", timestamp=t0 + timedelta(seconds=5))
    assert monitor.state == "DISCONNECTED"

    # Heartbeat restores at t + 10s (< 30s timeout)
    t_recover = t0 + timedelta(seconds=10)
    s = monitor.record_heartbeat_success(timestamp=t_recover)
    assert s == "CONNECTED"
    assert monitor.is_healthy is True
    assert monitor.is_circuit_open is False
    assert monitor.consecutive_failures == 0
    assert monitor.disconnection_start_time is None
    assert monitor.should_suppress_trading() is False

    last_event = monitor.history[-1]
    assert last_event.new_state == "CONNECTED"
    assert last_event.reason == "Broker heartbeat restored"
    assert last_event.downtime_seconds == 10.0


def test_30_second_disconnection_trips_circuit_open_and_suppresses_trading() -> None:
    """Verify outages >= 30s trip CIRCUIT_OPEN and suppress trading (NFR-REL-4, RTLD-15, EDD §9)."""
    monitor = ConnectionMonitor(ConnectionMonitorConfig(disconnection_timeout_seconds=30.0))
    t0 = datetime.now(UTC)

    # Initial disconnect
    monitor.record_heartbeat_failure(reason="Initial drop", timestamp=t0)

    # Subsequent failure at 30 seconds
    t_outage = t0 + timedelta(seconds=30)
    s = monitor.record_heartbeat_failure(reason="Still unreachable", timestamp=t_outage)

    assert s == "CIRCUIT_OPEN"
    assert monitor.is_circuit_open is True
    assert monitor.should_suppress_trading() is True

    # Check event
    event = monitor.history[-1]
    assert event.new_state == "CIRCUIT_OPEN"
    assert ">= 30.0s" in event.reason


def test_safe_state_hold_requires_manual_operator_reset_by_default() -> None:
    """Verify CIRCUIT_OPEN stays open on reconnect when auto_reset_on_reconnect=False.

    Enforces manual operator reset per RTLD §11, EDD §9.
    """
    monitor = ConnectionMonitor(
        ConnectionMonitorConfig(disconnection_timeout_seconds=30.0, auto_reset_on_reconnect=False)
    )
    t0 = datetime.now(UTC)

    monitor.record_heartbeat_failure(timestamp=t0)
    monitor.record_heartbeat_failure(timestamp=t0 + timedelta(seconds=30.0))
    assert bool(monitor.is_circuit_open) is True
    assert str(monitor.state) == "CIRCUIT_OPEN"

    # Broker reconnects, but auto_reset is False -> remains CIRCUIT_OPEN
    s = monitor.record_heartbeat_success(timestamp=t0 + timedelta(seconds=35.0))
    assert s == "CIRCUIT_OPEN"
    assert bool(monitor.is_circuit_open) is True
    assert monitor.should_suppress_trading() is True

    # Operator explicitly verifies and resets safe state
    monitor.reset_safe_state(
        operator_id="OPERATOR-OPS-1", reason="Broker API online and reconciled"
    )
    assert str(monitor.state) == "CONNECTED"
    assert bool(monitor.is_circuit_open) is False
    assert monitor.should_suppress_trading() is False

    reset_event = monitor.history[-1]
    assert reset_event.new_state == "CONNECTED"
    assert reset_event.metadata["operator_id"] == "OPERATOR-OPS-1"
    assert reset_event.metadata["reset_reason"] == "Broker API online and reconciled"


def test_safe_state_auto_reset_when_configured() -> None:
    """Verify CIRCUIT_OPEN automatically resets if auto_reset_on_reconnect=True."""
    monitor = ConnectionMonitor(
        ConnectionMonitorConfig(disconnection_timeout_seconds=30.0, auto_reset_on_reconnect=True)
    )
    t0 = datetime.now(UTC)

    monitor.record_heartbeat_failure(timestamp=t0)
    monitor.record_heartbeat_failure(timestamp=t0 + timedelta(seconds=30.0))
    assert bool(monitor.is_circuit_open) is True

    s = monitor.record_heartbeat_success(timestamp=t0 + timedelta(seconds=35.0))
    assert s == "CONNECTED"
    assert bool(monitor.is_circuit_open) is False
    assert monitor.should_suppress_trading() is False


def test_check_health_evaluates_silence_thresholds() -> None:
    """Verify check_health detects silence without explicit failure events."""
    config = ConnectionMonitorConfig(
        degraded_threshold_seconds=10.0,
        disconnection_timeout_seconds=30.0,
    )
    monitor = ConnectionMonitor(config)
    t0 = datetime.now(UTC)
    monitor.record_heartbeat_success(timestamp=t0)

    # 5s elapsed: still healthy
    assert monitor.check_health(current_time=t0 + timedelta(seconds=5)) == "CONNECTED"

    # 12s elapsed: exceeded degraded threshold (10s)
    assert monitor.check_health(current_time=t0 + timedelta(seconds=12)) == "DEGRADED"

    # 31s elapsed: exceeded 30s threshold -> trips CIRCUIT_OPEN
    assert monitor.check_health(current_time=t0 + timedelta(seconds=31)) == "CIRCUIT_OPEN"
    assert monitor.is_circuit_open is True
    assert monitor.should_suppress_trading() is True

    # Already open circuit maintains CIRCUIT_OPEN
    assert monitor.check_health(current_time=t0 + timedelta(seconds=40)) == "CIRCUIT_OPEN"


def test_check_health_detects_prolonged_disconnection() -> None:
    """Verify check_health trips circuit when disconnection_start_time crosses 30s."""
    monitor = ConnectionMonitor(ConnectionMonitorConfig(disconnection_timeout_seconds=30.0))
    t0 = datetime.now(UTC)
    monitor.record_heartbeat_failure(timestamp=t0)
    assert monitor.state == "DEGRADED"

    # After 31 seconds
    s = monitor.check_health(current_time=t0 + timedelta(seconds=31))
    assert s == "CIRCUIT_OPEN"
    assert monitor.is_circuit_open is True


def test_reset_safe_state_validation() -> None:
    """Verify reset_safe_state rejects empty operator_id or reason."""
    monitor = ConnectionMonitor()
    with pytest.raises(ValueError, match="operator_id must not be empty"):
        monitor.reset_safe_state(operator_id="   ", reason="Valid reason")

    with pytest.raises(ValueError, match="reason for reset must not be empty"):
        monitor.reset_safe_state(operator_id="OP-1", reason="   ")


def test_clear_resets_connection_monitor() -> None:
    """Verify clear() restores initial baseline state."""
    monitor = ConnectionMonitor()
    monitor.record_heartbeat_failure(reason="Failure")
    assert str(monitor.state) != "CONNECTED"

    monitor.clear()
    assert str(monitor.state) == "CONNECTED"
    assert monitor.consecutive_failures == 0
    assert monitor.last_heartbeat_time is None
    assert monitor.history == []


def test_connection_event_timezone_validation() -> None:
    """Verify ConnectionEvent rejects naive datetime."""
    naive_now = datetime.now()
    with pytest.raises(ValueError, match="must be timezone-aware UTC"):
        ConnectionEvent(
            previous_state="CONNECTED",
            new_state="DEGRADED",
            reason="Silence",
            timestamp=naive_now,
        )


@pytest.mark.asyncio
async def test_poll_broker_heartbeat_success() -> None:
    """Verify poll_broker_heartbeat succeeds and updates state when broker returns True."""
    monitor = ConnectionMonitor()
    mock_broker = MagicMock(spec=BrokerAdapter)
    mock_broker.heartbeat.return_value = True

    result = await monitor.poll_broker_heartbeat(mock_broker, timeout_seconds=2.0)
    assert result is True
    assert monitor.state == "CONNECTED"
    assert monitor.is_healthy is True


@pytest.mark.asyncio
async def test_poll_broker_heartbeat_failure_return_false() -> None:
    """Verify poll_broker_heartbeat records failure when broker returns False."""
    monitor = ConnectionMonitor()
    mock_broker = MagicMock(spec=BrokerAdapter)
    mock_broker.heartbeat.return_value = False

    result = await monitor.poll_broker_heartbeat(mock_broker, timeout_seconds=2.0)
    assert result is False
    assert monitor.state == "DEGRADED"
    assert monitor.consecutive_failures == 1


@pytest.mark.asyncio
async def test_poll_broker_heartbeat_exception_handling() -> None:
    """Verify poll_broker_heartbeat captures BrokerConnectionError as failure."""
    monitor = ConnectionMonitor()
    mock_broker = MagicMock(spec=BrokerAdapter)
    mock_broker.heartbeat.side_effect = BrokerConnectionError("Socket disconnected")

    result = await monitor.poll_broker_heartbeat(mock_broker, timeout_seconds=2.0)
    assert result is False
    assert monitor.state == "DEGRADED"
    assert "Socket disconnected" in monitor.history[0].reason


@pytest.mark.asyncio
async def test_poll_broker_heartbeat_timeout_handling() -> None:
    """Verify poll_broker_heartbeat handles asyncio timeout."""
    monitor = ConnectionMonitor()
    mock_broker = MagicMock(spec=BrokerAdapter)

    def slow_heartbeat() -> bool:
        time.sleep(0.5)
        return True

    mock_broker.heartbeat.side_effect = slow_heartbeat

    result = await monitor.poll_broker_heartbeat(mock_broker, timeout_seconds=0.1)
    assert result is False
    assert monitor.state == "DEGRADED"
    assert "timed out" in monitor.history[0].reason


def test_downtime_seconds_property_active() -> None:
    """Verify downtime_seconds returns positive float when disconnected."""
    monitor = ConnectionMonitor()
    t0 = datetime.now(UTC) - timedelta(seconds=5)
    monitor.record_heartbeat_failure(timestamp=t0)
    assert monitor.downtime_seconds >= 4.9


def test_repeated_failure_when_circuit_already_open() -> None:
    """Verify failure when circuit is already open does not duplicate transition."""
    monitor = ConnectionMonitor(ConnectionMonitorConfig(disconnection_timeout_seconds=30.0))
    t0 = datetime.now(UTC)
    monitor.record_heartbeat_failure(timestamp=t0)
    monitor.record_heartbeat_failure(timestamp=t0 + timedelta(seconds=31.0))
    assert monitor.state == "CIRCUIT_OPEN"
    initial_events_count = len(monitor.history)

    # Subsequent failure while already in CIRCUIT_OPEN
    s = monitor.record_heartbeat_failure(timestamp=t0 + timedelta(seconds=35.0))
    assert s == "CIRCUIT_OPEN"
    assert len(monitor.history) == initial_events_count


def test_repeated_failure_when_already_disconnected() -> None:
    """Verify record_heartbeat_failure when already DISCONNECTED does not duplicate transition."""
    monitor = ConnectionMonitor(
        ConnectionMonitorConfig(max_consecutive_failures=2, disconnection_timeout_seconds=30.0)
    )
    t0 = datetime.now(UTC)
    monitor.record_heartbeat_failure(timestamp=t0)
    monitor.record_heartbeat_failure(timestamp=t0 + timedelta(seconds=1))
    assert monitor.state == "DISCONNECTED"
    initial_events_count = len(monitor.history)

    # Another failure, but downtime still under 30s
    s = monitor.record_heartbeat_failure(timestamp=t0 + timedelta(seconds=2))
    assert s == "DISCONNECTED"
    assert len(monitor.history) == initial_events_count


def test_check_health_branch_coverage() -> None:
    """Verify check_health when never received heartbeat and when silence crosses thresholds."""
    config = ConnectionMonitorConfig(
        degraded_threshold_seconds=10.0, disconnection_timeout_seconds=30.0
    )
    monitor = ConnectionMonitor(config)

    # 1. Never had a heartbeat and no disconnect -> stays CONNECTED
    assert monitor.check_health() == "CONNECTED"

    # 2. Had heartbeat, now silence >= 10s and state already DEGRADED
    t0 = datetime.now(UTC)
    monitor.record_heartbeat_success(timestamp=t0)
    monitor.record_heartbeat_failure(timestamp=t0 + timedelta(seconds=2))
    assert monitor.state == "DEGRADED"

    # check_health at 15s elapsed silence, state is already DEGRADED
    s = monitor.check_health(current_time=t0 + timedelta(seconds=15))
    assert s == "DEGRADED"

    # check_health at 35s elapsed silence where disconnection_start_time was already set
    s2 = monitor.check_health(current_time=t0 + timedelta(seconds=35))
    assert s2 == "CIRCUIT_OPEN"


def test_check_health_immediate_jump_to_30s_silence() -> None:
    """Verify check_health when silence jumps to >= 30s directly without prior check."""
    monitor = ConnectionMonitor(ConnectionMonitorConfig(disconnection_timeout_seconds=30.0))
    t0 = datetime.now(UTC)
    monitor.record_heartbeat_success(timestamp=t0)
    assert monitor.disconnection_start_time is None

    # Jump directly to 35 seconds without prior check_health
    s = monitor.check_health(current_time=t0 + timedelta(seconds=35))
    assert s == "CIRCUIT_OPEN"
    assert monitor.is_circuit_open is True
    assert monitor.disconnection_start_time == t0
