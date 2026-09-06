"""Unit tests for real-time market data StalenessMonitor and SLA thresholds (NFR-DATA-1)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.data.staleness_monitor import StalenessMonitor
from src.domain.market_data import MarketTick, OHLCVCandle


def test_staleness_monitor_initialization_validation() -> None:
    """Verify monitor validates positive staleness threshold."""
    monitor = StalenessMonitor(max_staleness_seconds=5.0)
    assert monitor.max_staleness_seconds == 5.0

    with pytest.raises(ValueError, match="max_staleness_seconds must be positive"):
        StalenessMonitor(max_staleness_seconds=0.0)

    with pytest.raises(ValueError, match="max_staleness_seconds must be positive"):
        StalenessMonitor(max_staleness_seconds=-1.0)


def test_staleness_monitor_fresh_heartbeat() -> None:
    """Verify fresh heartbeat within SLA window returns is_stale=False."""
    monitor = StalenessMonitor(max_staleness_seconds=10.0)
    t0 = datetime(2025, 1, 15, 9, 30, 0, tzinfo=UTC)

    monitor.record_heartbeat("NSE:RELIANCE", arrival_time=t0)
    status = monitor.check_staleness("NSE:RELIANCE", current_time=t0 + timedelta(seconds=3))

    assert status.instrument == "NSE:RELIANCE"
    assert status.is_stale is False
    assert status.elapsed_seconds == pytest.approx(3.0)
    assert status.threshold_seconds == 10.0
    assert status.last_seen_timestamp == t0
    assert status.reason is None


def test_staleness_monitor_timeout_transition() -> None:
    """Verify exceeding max staleness threshold triggers TICK_TIMEOUT."""
    monitor = StalenessMonitor(max_staleness_seconds=10.0)
    t0 = datetime(2025, 1, 15, 9, 30, 0, tzinfo=UTC)

    monitor.record_heartbeat("NSE:INFY", arrival_time=t0)

    # At exact threshold (10.0s), not stale (> 10.0 required)
    status_edge = monitor.check_staleness("NSE:INFY", current_time=t0 + timedelta(seconds=10.0))
    assert status_edge.is_stale is False

    # Past threshold (10.1s), transitions to STALE
    status_stale = monitor.check_staleness("NSE:INFY", current_time=t0 + timedelta(seconds=10.1))
    assert status_stale.is_stale is True
    assert status_stale.reason == "TICK_TIMEOUT"
    assert status_stale.elapsed_seconds == pytest.approx(10.1)

    # Fresh tick arrives -> recovers to fresh
    t1 = t0 + timedelta(seconds=11.0)
    monitor.record_heartbeat("NSE:INFY", arrival_time=t1)
    status_recovered = monitor.check_staleness("NSE:INFY", current_time=t1 + timedelta(seconds=1.0))
    assert status_recovered.is_stale is False
    assert status_recovered.reason is None


def test_staleness_monitor_tick_and_candle_helpers() -> None:
    """Verify convenience helpers record_tick and record_candle correctly update arrival."""
    monitor = StalenessMonitor(max_staleness_seconds=10.0)
    t0 = datetime(2025, 1, 15, 9, 30, 0, tzinfo=UTC)

    # 1. Record MarketTick
    tick = MarketTick(
        instrument="NSE:TCS",
        timestamp=t0,
        last_price=Decimal("3800.00"),
        volume=50,
    )
    monitor.record_tick(tick)
    status_tick = monitor.check_staleness("NSE:TCS", current_time=t0 + timedelta(seconds=2))
    assert status_tick.is_stale is False
    assert status_tick.last_seen_timestamp == t0

    # 2. Record OHLCVCandle
    candle = OHLCVCandle(
        instrument="NSE:SBIN",
        timestamp=t0,
        open=Decimal("750.00"),
        high=Decimal("755.00"),
        low=Decimal("748.00"),
        close=Decimal("752.00"),
        volume=1000,
        turnover=Decimal("752000.00"),
        timeframe="1m",
        quality_state="VALIDATED",
    )
    monitor.record_candle(candle)
    status_candle = monitor.check_staleness("NSE:SBIN", current_time=t0 + timedelta(seconds=5))
    assert status_candle.is_stale is False
    assert status_candle.last_seen_timestamp == t0


def test_staleness_monitor_untracked_instrument() -> None:
    """Verify querying an instrument with no recorded arrivals returns NO_DATA_RECEIVED."""
    monitor = StalenessMonitor(max_staleness_seconds=10.0)
    now = datetime(2025, 1, 15, 9, 30, 0, tzinfo=UTC)

    status = monitor.check_staleness("NSE:UNKNOWN", current_time=now)
    assert status.instrument == "NSE:UNKNOWN"
    assert status.is_stale is True
    assert status.reason == "NO_DATA_RECEIVED"
    assert status.last_seen_timestamp is None
    assert status.elapsed_seconds == float("inf")


def test_staleness_monitor_multi_instrument_isolation() -> None:
    """Verify multiple instruments maintain isolated arrival timestamps."""
    monitor = StalenessMonitor(max_staleness_seconds=10.0)
    t0 = datetime(2025, 1, 15, 9, 30, 0, tzinfo=UTC)

    monitor.record_heartbeat("NSE:RELIANCE", arrival_time=t0)
    monitor.record_heartbeat("NSE:TCS", arrival_time=t0 - timedelta(seconds=20))

    check_time = t0 + timedelta(seconds=2)
    status_reliance = monitor.check_staleness("NSE:RELIANCE", current_time=check_time)
    status_tcs = monitor.check_staleness("NSE:TCS", current_time=check_time)

    assert status_reliance.is_stale is False
    assert status_tcs.is_stale is True
    assert status_tcs.reason == "TICK_TIMEOUT"

    all_statuses = monitor.check_all(current_time=check_time)
    assert len(all_statuses) == 2
    assert all_statuses["NSE:RELIANCE"].is_stale is False
    assert all_statuses["NSE:TCS"].is_stale is True
    assert monitor.get_tracked_instruments() == ["NSE:RELIANCE", "NSE:TCS"]


def test_staleness_monitor_reset_and_empty_validation() -> None:
    """Verify reset clears tracking cache and empty symbols are rejected."""
    monitor = StalenessMonitor()
    t0 = datetime(2025, 1, 15, 9, 30, 0, tzinfo=UTC)

    with pytest.raises(ValueError, match="Instrument identifier cannot be empty"):
        monitor.record_heartbeat("   ")

    monitor.record_heartbeat("NSE:RELIANCE", arrival_time=t0)
    monitor.record_heartbeat("NSE:TCS", arrival_time=t0)
    assert len(monitor.get_tracked_instruments()) == 2

    # Reset single instrument
    monitor.reset("NSE:RELIANCE")
    assert monitor.get_tracked_instruments() == ["NSE:TCS"]

    # Reset all
    monitor.reset()
    assert monitor.get_tracked_instruments() == []


def test_staleness_monitor_naive_and_default_time() -> None:
    """Verify naive datetime is converted to UTC and default wall-clock timestamps work."""
    monitor = StalenessMonitor(max_staleness_seconds=10.0)
    naive_ts = datetime(2025, 1, 15, 9, 30, 0)  # no tzinfo

    monitor.record_heartbeat("NSE:WIPRO", arrival_time=naive_ts)
    status = monitor.check_staleness("NSE:WIPRO", current_time=naive_ts + timedelta(seconds=1))

    assert status.is_stale is False
    assert status.last_seen_timestamp == naive_ts.replace(tzinfo=UTC)

    # Check default now() recording and evaluation
    monitor.record_heartbeat("NSE:HDFCBANK")
    live_status = monitor.check_staleness("NSE:HDFCBANK")
    assert live_status.is_stale is False
