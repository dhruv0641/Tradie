"""Unit tests for SuppressionGate and fail-safe trading suppression (RTLD §11, HLD §7)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from src.data.staleness_monitor import StalenessMonitor
from src.data.suppression_gate import SuppressionGate
from src.domain.market_data import OHLCVCandle


def make_test_candle(
    quality_state: str = "VALIDATED",
    instrument: str = "NSE:RELIANCE",
    ts: datetime | None = None,
) -> OHLCVCandle:
    """Helper to construct candles with configurable quality state."""
    return OHLCVCandle(
        instrument=instrument,
        timestamp=ts or datetime(2025, 1, 15, 9, 30, 0, tzinfo=UTC),
        open=Decimal("2500.00"),
        high=Decimal("2520.00"),
        low=Decimal("2490.00"),
        close=Decimal("2510.00"),
        volume=5000,
        turnover=Decimal("12550000.00"),
        timeframe="1m",
        quality_state=quality_state,  # type: ignore[arg-type]
    )


def test_suppression_gate_quarantined_candle() -> None:
    """Verify candle with QUARANTINED quality state is suppressed immediately."""
    gate = SuppressionGate()
    candle = make_test_candle(quality_state="QUARANTINED")

    res = gate.evaluate_candle(candle)
    assert res.should_suppress is True
    assert res.action == "SUPPRESS"
    assert res.forced_decision == "NO_TRADE"
    assert res.reason == "DATA_QUALITY_QUARANTINED"
    assert res.data_quality == "QUARANTINED"


def test_suppression_gate_raw_candle() -> None:
    """Verify unvalidated RAW candle triggers suppression."""
    gate = SuppressionGate()
    candle = make_test_candle(quality_state="RAW")

    res = gate.evaluate_candle(candle)
    assert res.should_suppress is True
    assert res.action == "SUPPRESS"
    assert res.forced_decision == "NO_TRADE"
    assert res.reason == "DATA_QUALITY_RAW"
    assert res.data_quality == "RAW"


def test_suppression_gate_stale_candle() -> None:
    """Verify candle tagged as STALE triggers suppression."""
    gate = SuppressionGate()
    candle = make_test_candle(quality_state="STALE")

    res = gate.evaluate_candle(candle)
    assert res.should_suppress is True
    assert res.action == "SUPPRESS"
    assert res.forced_decision == "NO_TRADE"
    assert res.reason == "DATA_QUALITY_STALE"
    assert res.data_quality == "STALE"


def test_suppression_gate_real_time_feed_staleness_trigger() -> None:
    """Verify clean VALIDATED candle is suppressed if feed staleness SLA is breached."""
    monitor = StalenessMonitor(max_staleness_seconds=10.0)
    gate = SuppressionGate(staleness_monitor=monitor)

    t0 = datetime(2025, 1, 15, 9, 30, 0, tzinfo=UTC)
    monitor.record_heartbeat("NSE:RELIANCE", arrival_time=t0)

    # Candle timestamp is t0, but current wall-clock is 15 seconds later (SLA breached)
    candle = make_test_candle(quality_state="VALIDATED", ts=t0)
    now = t0 + timedelta(seconds=15.0)

    res = gate.evaluate_candle(candle, current_time=now)
    assert res.should_suppress is True
    assert res.action == "SUPPRESS"
    assert res.forced_decision == "NO_TRADE"
    assert res.reason == "FEED_STALE_TICK_TIMEOUT"
    assert res.data_quality == "STALE"
    assert res.details["elapsed_seconds"] == 15.0


def test_suppression_gate_clean_validated_candle_allowed() -> None:
    """Verify clean VALIDATED candle within freshness SLA is authorized for inference."""
    monitor = StalenessMonitor(max_staleness_seconds=10.0)
    gate = SuppressionGate(staleness_monitor=monitor)

    t0 = datetime(2025, 1, 15, 9, 30, 0, tzinfo=UTC)
    monitor.record_heartbeat("NSE:RELIANCE", arrival_time=t0)

    candle = make_test_candle(quality_state="VALIDATED", ts=t0)
    now = t0 + timedelta(seconds=2.0)

    res = gate.evaluate_candle(candle, current_time=now)
    assert res.should_suppress is False
    assert res.action == "ALLOW"
    assert res.forced_decision is None
    assert res.reason is None
    assert res.data_quality == "VALIDATED"


def test_suppression_gate_without_staleness_monitor() -> None:
    """Verify gate functions strictly on candle quality state when monitor is not provided."""
    gate = SuppressionGate(staleness_monitor=None)
    candle = make_test_candle(quality_state="VALIDATED")

    res = gate.evaluate_candle(candle)
    assert res.should_suppress is False
    assert res.action == "ALLOW"


def test_suppression_gate_configurable_fallback_decision() -> None:
    """Verify custom forced fallback decision (e.g. HOLD) is respected."""
    gate = SuppressionGate(default_forced_decision="HOLD")
    candle = make_test_candle(quality_state="QUARANTINED")

    res = gate.evaluate_candle(candle)
    assert res.should_suppress is True
    assert res.forced_decision == "HOLD"


def test_suppression_gate_decision_record_generation() -> None:
    """Verify creation of canonical SHA-256 stamped DecisionRecord for suppressed cycles."""
    gate = SuppressionGate()
    candle = make_test_candle(quality_state="QUARANTINED", instrument="NSE:TCS")

    res = gate.evaluate_candle(candle)
    assert res.should_suppress is True

    t_eval = datetime(2025, 1, 15, 9, 31, 0, tzinfo=UTC)
    record = gate.create_suppressed_decision(
        instrument="NSE:TCS",
        suppression_result=res,
        timestamp=t_eval,
        git_commit="test_commit_hash",
    )

    assert record.instrument == "NSE:TCS"
    assert record.decision == "NO_TRADE"
    assert record.regime == "DATA_SUPPRESSED"
    assert record.agent_scores == {}
    assert record.aggregated_score == 0.0
    assert record.approved_quantity == 0
    assert record.stop_loss_price is None
    assert record.target_price is None
    assert record.git_commit == "test_commit_hash"
    assert record.risk_result["suppressed"] is True
    assert record.risk_result["reason"] == "DATA_QUALITY_QUARANTINED"

    # Verify cryptographic SHA-256 hash validity
    expected_hash = record.calculate_canonical_hash()
    assert record.decision_hash == expected_hash
    assert len(record.decision_hash) == 64

    # Verify naive timestamp normalization
    naive_t = datetime(2025, 1, 15, 9, 31, 0)
    record_naive = gate.create_suppressed_decision(
        instrument="NSE:TCS",
        suppression_result=res,
        timestamp=naive_t,
    )
    assert record_naive.timestamp.tzinfo == UTC

    # Verify default timestamp generation
    record_default = gate.create_suppressed_decision(
        instrument="NSE:TCS",
        suppression_result=res,
    )
    assert record_default.timestamp.tzinfo == UTC
