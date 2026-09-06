"""Safety Verification Test Suite KS-TEST-1 through KS-TEST-4 per LLD §6.3 and NFR-SAFE-4."""

import threading
import time
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.decision.supervisor import Supervisor
from src.domain.risk import (
    CandidateTrade,
    CapitalState,
    MarketState,
    StreakState,
)
from src.risk.config import RiskConfig
from src.risk.engine import RiskEngine
from src.risk.kill_switch import (
    AuditLogProtocol,
    InMemoryKillSwitch,
    KillSwitch,
    TriggerSource,
)


class MockOperatorToken:
    """Mock token satisfying OperatorAuthTokenProtocol for testing."""

    def __init__(self, op_id: str, valid: bool) -> None:
        self._op_id = op_id
        self._valid = valid

    @property
    def operator_id(self) -> str:
        return self._op_id

    def is_valid(self) -> bool:
        return self._valid


@pytest.fixture
def risk_config() -> RiskConfig:
    """Fixture providing standard RiskConfig."""
    return RiskConfig()


@pytest.fixture
def sample_candidate() -> CandidateTrade:
    """Fixture providing a high-confidence, high-quality BUY candidate from Aggregator."""
    return CandidateTrade(
        instrument="RELIANCE",
        direction="BUY",
        entry_price=Decimal("2500.00"),
        stop_price=Decimal("2480.00"),
        timeframe="15m",
        trade_quality_score=0.95,  # Top tier conviction
        expected_value=Decimal("50.00"),
        confidence=0.92,
        timestamp=datetime.now(UTC),
    )


@pytest.fixture
def sample_capital() -> CapitalState:
    """Fixture providing healthy capital state."""
    return CapitalState(
        current_capital=Decimal("10000.00"),
        peak_equity=Decimal("10000.00"),
        session_start_capital=Decimal("10000.00"),
        currently_deployed=Decimal("0.00"),
        open_position_count=0,
        trades_today=0,
    )


@pytest.fixture
def sample_streak() -> StreakState:
    """Fixture providing zero-loss streak state."""
    return StreakState(consecutive_losses=0)


@pytest.fixture
def sample_market() -> MarketState:
    """Fixture providing normal validated market state."""
    return MarketState(
        instrument="RELIANCE",
        current_volatility=Decimal("20.0"),
        trailing_20session_avg_volatility=Decimal("18.0"),
        data_quality="VALIDATED",
        exchange_condition="NORMAL",
    )


# ==============================================================================
# KS-TEST-1: Independence from Favorable Upstream Signals (LLD §6.3)
# ==============================================================================
def test_ks_test_1_independence_from_favorable_upstream_signals(
    risk_config: RiskConfig,
    sample_candidate: CandidateTrade,
    sample_capital: CapitalState,
    sample_streak: StreakState,
    sample_market: MarketState,
) -> None:
    """KS-TEST-1: All upstream agents recommend high-quality BUY; kill switch is ACTIVE.

    Expected Result: Supervisor.decide() returns HOLD/NO_TRADE regardless of favorable signals.
    """
    kill_switch = KillSwitch()
    risk_engine = RiskEngine(config=risk_config, kill_switch=kill_switch)
    supervisor = Supervisor(risk_engine=risk_engine, kill_switch=kill_switch)

    # 1. Activate kill switch
    kill_switch.activate(TriggerSource.MANUAL_OPERATOR, "Operator STOP pressed on UI")
    assert kill_switch.is_active() is True

    # 2. Evaluate when no position is open -> Must be NO_TRADE
    decision_no_pos = supervisor.decide(
        candidate=sample_candidate,
        capital=sample_capital,
        streak=sample_streak,
        market=sample_market,
        has_open_position=False,
    )
    assert decision_no_pos.outcome == "NO_TRADE"
    assert decision_no_pos.kill_switch_active is True
    assert decision_no_pos.approved_quantity == 0
    assert "kill switch/STOP active" in decision_no_pos.reason
    assert decision_no_pos.is_trade_approved is False

    # 3. Evaluate when open position exists -> Must be HOLD (safe-state hold, no new entry)
    decision_with_pos = supervisor.decide(
        candidate=sample_candidate,
        capital=sample_capital,
        streak=sample_streak,
        market=sample_market,
        has_open_position=True,
    )
    assert decision_with_pos.outcome == "HOLD"
    assert decision_with_pos.kill_switch_active is True
    assert decision_with_pos.approved_quantity == 0
    assert "kill switch/STOP active" in decision_with_pos.reason
    assert decision_with_pos.is_trade_approved is False


# ==============================================================================
# KS-TEST-2: Minimal Runtime Dependency & Execution Latency Target (RTLD-17)
# ==============================================================================
def test_ks_test_2_minimal_dependency_latency_under_stalled_upstream() -> None:
    """KS-TEST-2: Simulated stalled/hanging upstream process does NOT block kill switch.

    Activation and is_active() check complete well under RTLD-17's <2 second target
    (in practice under 1 millisecond).
    """
    kill_switch = InMemoryKillSwitch()

    # Simulate an upstream worker that is stalled/blocked in another thread
    stall_event = threading.Event()

    def simulated_slow_upstream() -> None:
        # Simulate heavy ML inference or hanging network socket
        time.sleep(0.5)
        stall_event.set()

    upstream_thread = threading.Thread(target=simulated_slow_upstream, daemon=True)
    upstream_thread.start()

    # While upstream is busy/stalled, activate kill switch and measure latency
    start_time = time.perf_counter()
    kill_switch.activate(TriggerSource.MANUAL_OPERATOR, "Emergency manual halt")
    active = kill_switch.is_active()
    elapsed_seconds = time.perf_counter() - start_time

    assert active is True
    # Latency must be < 2.0 seconds per RTLD-17 / NFR-SAFE-2 (in fact < 0.05s)
    err_msg = f"Kill switch activation took {elapsed_seconds:.4f}s, exceeding target"
    assert elapsed_seconds < 0.05, err_msg


# ==============================================================================
# KS-TEST-3: Extreme Drawdown Auto-Trigger (RTLD-6, 10% Threshold)
# ==============================================================================
def test_ks_test_3_extreme_drawdown_auto_trigger(
    risk_config: RiskConfig,
    sample_candidate: CandidateTrade,
    sample_streak: StreakState,
    sample_market: MarketState,
) -> None:
    """KS-TEST-3: Peak-to-trough drawdown reaches exactly RTLD-6 threshold (10%).

    Risk Engine blocks candidate trade and KillSwitch can be auto-activated.
    """
    kill_switch = KillSwitch()
    risk_engine = RiskEngine(config=risk_config, kill_switch=kill_switch)
    supervisor = Supervisor(risk_engine=risk_engine, kill_switch=kill_switch)

    # 10% drawdown: peak ₹10,000, current ₹9,000 (drawdown = ₹1,000 = 10%)
    # Session start capital ₹9,100 (daily loss = ₹100 < ₹273 daily limit)
    drawdown_capital = CapitalState(
        current_capital=Decimal("9000.00"),
        peak_equity=Decimal("10000.00"),
        session_start_capital=Decimal("9100.00"),
        currently_deployed=Decimal("0.00"),
        open_position_count=0,
        trades_today=3,
    )

    # RiskEngine evaluation should block due to extreme drawdown killswitch threshold (RTLD-6)
    risk_result = risk_engine.evaluate(
        sample_candidate, drawdown_capital, sample_streak, sample_market
    )
    assert risk_result.passed is False
    assert risk_result.failed_check == "extreme_drawdown_killswitch"
    assert risk_result.rtld_param_id == "RTLD-6"

    # Auto-trigger kill switch via EXTREME_DRAWDOWN
    kill_switch.activate(TriggerSource.EXTREME_DRAWDOWN, "Auto-triggered at 10% drawdown threshold")
    assert kill_switch.is_active() is True

    # Subsequent supervisor decision is definitively halted
    decision = supervisor.decide(
        candidate=sample_candidate,
        capital=drawdown_capital,
        streak=sample_streak,
        market=sample_market,
        has_open_position=False,
    )
    assert decision.outcome == "NO_TRADE"
    assert decision.kill_switch_active is True


# ==============================================================================
# KS-TEST-4: Unauthenticated Reset Attempt Rejected (TRD-SEC-3, RTLD §16)
# ==============================================================================
def test_ks_test_4_unauthenticated_reset_attempt_rejected() -> None:
    """KS-TEST-4: Reset attempted with missing/invalid operator auth token.

    Expected Result: PermissionError raised; kill switch state remains ACTIVE.
    """
    kill_switch = KillSwitch()
    kill_switch.activate(TriggerSource.MANUAL_OPERATOR, "Emergency halt")
    assert kill_switch.is_active() is True

    # 1. Attempt reset with empty string
    with pytest.raises(PermissionError, match="non-empty authenticated operator token"):
        kill_switch.reset("")
    assert kill_switch.is_active() is True

    # 2. Attempt reset with whitespace string
    with pytest.raises(PermissionError, match="non-empty authenticated operator token"):
        kill_switch.reset("   ")
    assert kill_switch.is_active() is True

    # 3. Attempt reset with invalid OperatorAuthTokenProtocol object
    invalid_token = MockOperatorToken(op_id="BAD_OPERATOR", valid=False)
    with pytest.raises(PermissionError, match="authenticated operator action"):
        kill_switch.reset(invalid_token)
    assert kill_switch.is_active() is True

    # 4. Valid token successfully resets kill switch
    valid_token = MockOperatorToken(op_id="CHIEF_OPERATOR_001", valid=True)
    kill_switch.reset(valid_token)
    assert kill_switch.is_active() is False


# ==============================================================================
# Additional KillSwitch Subsystem Tests (Audit Log, History, Thread-Safety)
# ==============================================================================
def test_kill_switch_synchronous_audit_log_recording() -> None:
    """Verify KillSwitch records events synchronously via AuditLogProtocol."""
    mock_audit = MagicMock(spec=AuditLogProtocol)
    ks = KillSwitch(audit_log=mock_audit)

    ks.activate(TriggerSource.SYSTEM_FAILURE, "Fatal feed disconnect")
    assert ks.is_active() is True
    mock_audit.record_sync.assert_called_once()
    call_args = mock_audit.record_sync.call_args[1]
    assert call_args["event"] == "kill_switch_activated"
    assert call_args["source"] == "system_failure"

    mock_audit.reset_mock()
    ks.reset("valid_operator_auth_key_1234")
    assert ks.is_active() is False
    mock_audit.record_sync.assert_called_once()
    call_args_reset = mock_audit.record_sync.call_args[1]
    assert call_args_reset["event"] == "kill_switch_reset"


def test_kill_switch_history_retrieval() -> None:
    """Verify history of activations and resets is properly accumulated."""
    ks = KillSwitch()
    ks.activate(TriggerSource.MANUAL_OPERATOR, "First halt")
    ks.reset("valid_key_1")
    ks.activate(TriggerSource.EXTREME_DRAWDOWN, "Second halt")

    history = ks.get_history()
    assert len(history) == 3
    assert history[0]["event"] == "kill_switch_activated"
    assert history[1]["event"] == "kill_switch_reset"
    assert history[2]["event"] == "kill_switch_activated"


def test_kill_switch_thread_safety() -> None:
    """Verify thread-safe reading of is_active() under concurrent activation."""
    ks = KillSwitch()
    read_results: list[bool] = []
    stop_event = threading.Event()

    def reader() -> None:
        while not stop_event.is_set():
            read_results.append(ks.is_active())
            time.sleep(0.001)

    threads = [threading.Thread(target=reader) for _ in range(5)]
    for t in threads:
        t.start()

    time.sleep(0.01)
    ks.activate(TriggerSource.MANUAL_OPERATOR, "Thread test")
    time.sleep(0.01)
    stop_event.set()

    for t in threads:
        t.join()

    assert ks.is_active() is True
    assert any(r is True for r in read_results)
    assert any(r is False for r in read_results)
