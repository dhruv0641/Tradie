"""Integration test suite for Phase V5 Live Trading Activation (EPIC-18).

Verifies end-to-end integration across:
- SOW §9 Preconditions verification (SEBI review, broker creds, gates, KS-TEST, token)
- LiveBrokerAdapter sandbox execution and connection monitoring
- StartupReconciler position and order verification gate
- TradingBrainRunner safe-state enforcement and order suppression on mismatch
- Manual operator override recovery and trade execution resumption
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from scripts.verify_live_preconditions import LivePreconditionsVerifier
from src.config.models import BrokerConfig
from src.core.runner import RunnerConfig, TradingBrainRunner
from src.domain.execution import Position
from src.domain.market_data import OHLCVCandle
from src.execution.live_broker_adapter import LiveBrokerAdapter
from src.execution.position_ledger import PositionLedger
from src.execution.reconciliation import StartupReconciler
from src.risk.kill_switch import InMemoryKillSwitch


def _make_test_candle(
    timestamp: datetime,
    close_price: Decimal = Decimal("2500.00"),
    instrument: str = "NSE:RELIANCE",
) -> OHLCVCandle:
    """Helper to construct valid OHLCVCandle instances."""
    return OHLCVCandle(
        instrument=instrument,
        timeframe="15m",
        timestamp=timestamp,
        open=close_price - Decimal("2.00"),
        high=close_price + Decimal("5.00"),
        low=close_price - Decimal("4.00"),
        close=close_price,
        volume=10000,
        turnover=close_price * Decimal("10000"),
    )


@pytest.mark.integration
def test_sow9_preconditions_verifier_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that all 5 SOW §9 preconditions pass cleanly in the repository."""
    monkeypatch.setenv("BROKER_API_KEY", "MOCK_API_KEY_LIVE_12345")
    monkeypatch.setenv("BROKER_API_SECRET", "MOCK_API_SECRET_LIVE_12345")

    repo_root = Path(__file__).resolve().parent.parent.parent
    verifier = LivePreconditionsVerifier(base_dir=repo_root)
    all_passed, results = verifier.verify_all()

    assert all_passed is True
    assert len(results) == 5
    for r in results:
        assert r.passed is True


@pytest.mark.integration
def test_live_activation_clean_startup_and_runner_session() -> None:
    """Verify clean startup reconciliation and runner session execution with LiveBrokerAdapter."""
    broker_cfg = BrokerConfig(
        broker_name="zerodha",
    )
    broker = LiveBrokerAdapter(config=broker_cfg, sandbox_mode=True)
    ledger = PositionLedger(initial_capital=Decimal("10000.00"))
    kill_switch = InMemoryKillSwitch()
    reconciler = StartupReconciler(
        broker=broker,
        ledger=ledger,
        kill_switch=kill_switch,
        auto_halt_on_mismatch=True,
    )

    runner_cfg = RunnerConfig(enforce_market_hours=False, warmup_bars=5)
    runner = TradingBrainRunner(
        broker=broker,
        config=runner_cfg,
        position_ledger=ledger,
        reconciler=reconciler,
        kill_switch=kill_switch,
    )

    # 1. Pre-market reconciliation check
    now = datetime(2026, 9, 7, 9, 15, tzinfo=UTC)
    runner.pre_market_reconciliation(now)

    assert reconciler.is_reconciled is True
    assert reconciler.can_submit_orders() is True
    assert kill_switch.is_active() is False

    # 2. Process a sequence of candles with 5 warmup bars
    candles = [
        _make_test_candle(now + timedelta(minutes=15 * i), Decimal("2500.00") + Decimal(i))
        for i in range(10)
    ]

    summary = runner.run_session(candles)

    assert summary.initial_capital == Decimal("10000.00")
    assert summary.final_equity == Decimal("10000.00")
    assert runner.total_cycles >= 5
    assert reconciler.is_reconciled is True


@pytest.mark.integration
def test_live_activation_startup_discrepancy_suppresses_trading() -> None:
    """Verify that a position mismatch blocks order dispatch and locks safe state."""
    broker_cfg = BrokerConfig(
        broker_name="zerodha",
    )
    broker = LiveBrokerAdapter(config=broker_cfg, sandbox_mode=True)

    # Incur an unrecorded broker position (simulating out-of-band trade or restart)
    now = datetime(2026, 9, 7, 9, 15, tzinfo=UTC)
    broker._sandbox_positions["NSE:INFY"] = Position(
        instrument="NSE:INFY",
        quantity=25,
        average_entry_price=Decimal("1500.00"),
        current_market_price=Decimal("1500.00"),
        unrealized_pnl=Decimal("0.00"),
        realized_pnl=Decimal("0.00"),
        peak_unrealized_pnl=Decimal("0.00"),
        updated_at=now,
    )

    ledger = PositionLedger(initial_capital=Decimal("10000.00"))
    kill_switch = InMemoryKillSwitch()
    reconciler = StartupReconciler(
        broker=broker,
        ledger=ledger,
        kill_switch=kill_switch,
        auto_halt_on_mismatch=True,
    )

    runner_cfg = RunnerConfig(enforce_market_hours=False, warmup_bars=5)
    runner = TradingBrainRunner(
        broker=broker,
        config=runner_cfg,
        position_ledger=ledger,
        reconciler=reconciler,
        kill_switch=kill_switch,
    )

    # 1. Pre-market reconciliation runs and detects discrepancy
    runner.pre_market_reconciliation(now)

    assert reconciler.can_submit_orders() is False
    assert kill_switch.is_active() is True
    assert kill_switch._history[-1]["source"] == "startup_reconciler"

    # Feed 4 warmup bars
    for i in range(4):
        runner.process_candle(_make_test_candle(now + timedelta(minutes=15 * i)))

    # 5th bar reaches warm buffer and hits startup reconciliation gate
    fifth_candle = _make_test_candle(now + timedelta(minutes=15 * 4))
    cycle_res = runner.process_candle(fifth_candle)

    assert cycle_res.executed_fill is None
    assert "Trading suppressed: startup reconciliation failed or pending" in str(cycle_res.reason)
    assert runner.orders_placed == 0

    # 3. Manual Operator Override unblocks trading
    override_res = reconciler.manual_override(
        operator_token="OPERATOR-OPS-SUPERVISOR",
        reason="Manual verification completed with Zerodha OMS; ledger synchronized",
    )
    # Also reset kill switch as part of emergency procedure
    kill_switch.reset("OPERATOR-OPS-SUPERVISOR")

    assert override_res.reconciled is True
    assert reconciler.can_submit_orders() is True
    assert kill_switch.is_active() is False

    # 4. Processing candle now proceeds past reconciliation gate
    cycle_res_after = runner.process_candle(_make_test_candle(now + timedelta(minutes=15 * 5)))
    assert cycle_res_after.reason != "Trading suppressed: startup reconciliation failed or pending"
