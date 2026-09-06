"""Unit tests for StartupReconciler and safe-state trading gate.

Verifies:
- LLD §9.1 & EDD §10
- TRD-DR-2, TRD-DR-3 (Safe-state trading lock and auto-halt on discrepancy)
- FRD-EXEC-7 (Startup reconciliation across broker, orders, and ledger)
- Clean matching positions vs. phantom broker, phantom ledger, and quantity discrepancies
- KillSwitch auto-halt activation on mismatch
- Operator manual override mechanics and validation
"""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.domain.execution import Position
from src.execution.broker_adapter import BrokerAdapter
from src.execution.order_manager import OrderManager
from src.execution.position_ledger import PositionLedger
from src.execution.reconciliation import (
    StartupReconciler,
    StartupReconciliationMismatchError,
)
from src.risk.kill_switch import KillSwitchProtocol


def _make_position(symbol: str, qty: int) -> Position:
    """Helper to construct a Position entity."""
    return Position(
        instrument=symbol,
        quantity=qty,
        average_entry_price=Decimal("100.00"),
        current_market_price=Decimal("100.00"),
        unrealized_pnl=Decimal("0.00"),
        realized_pnl=Decimal("0.00"),
        peak_unrealized_pnl=Decimal("0.00"),
        updated_at=datetime.now(UTC),
    )


def test_initial_state_unreconciled() -> None:
    """StartupReconciler must initially disallow order dispatch until reconciled."""
    broker = MagicMock(spec=BrokerAdapter)
    ledger = PositionLedger(initial_capital=Decimal("10000.00"))

    reconciler = StartupReconciler(broker=broker, ledger=ledger)

    assert reconciler.is_reconciled is False
    assert reconciler.last_result is None
    assert reconciler.can_submit_orders() is False


def test_clean_match_both_flat() -> None:
    """Reconciler succeeds when both broker and ledger hold zero positions."""
    broker = MagicMock(spec=BrokerAdapter)
    broker.get_positions.return_value = []
    ledger = PositionLedger(initial_capital=Decimal("10000.00"))

    reconciler = StartupReconciler(broker=broker, ledger=ledger)
    result = reconciler.reconcile()

    assert result.reconciled is True
    assert reconciler.is_reconciled is True
    assert reconciler.can_submit_orders() is True
    assert result.discrepancies == []
    assert result.broker_positions_count == 0
    assert result.ledger_positions_count == 0
    assert result.override_applied is False
    assert reconciler.last_result == result


def test_clean_match_with_matching_positions() -> None:
    """Reconciler succeeds when broker and ledger positions match exactly."""
    broker = MagicMock(spec=BrokerAdapter)
    broker.get_positions.return_value = [
        _make_position("INFY", 10),
        _make_position("TCS", -5),
    ]

    ledger = MagicMock()
    ledger.get_open_positions.return_value = [
        _make_position("INFY", 10),
        _make_position("TCS", -5),
    ]

    reconciler = StartupReconciler(broker=broker, ledger=ledger)
    result = reconciler.reconcile()

    assert result.reconciled is True
    assert reconciler.can_submit_orders() is True
    assert len(result.discrepancies) == 0
    assert result.broker_positions_count == 2
    assert result.ledger_positions_count == 2


def test_phantom_broker_position_detected() -> None:
    """Discrepancy detected when broker reports position not in local ledger."""
    broker = MagicMock(spec=BrokerAdapter)
    broker.get_positions.return_value = [_make_position("RELIANCE", 25)]

    ledger = MagicMock()
    ledger.get_open_positions.return_value = []

    kill_switch = MagicMock(spec=KillSwitchProtocol)

    reconciler = StartupReconciler(broker=broker, ledger=ledger, kill_switch=kill_switch)
    result = reconciler.reconcile()

    assert result.reconciled is False
    assert reconciler.can_submit_orders() is False
    assert len(result.discrepancies) == 1

    disc = result.discrepancies[0]
    assert disc.discrepancy_type == "PHANTOM_BROKER_POSITION"
    assert disc.instrument == "RELIANCE"
    assert disc.broker_quantity == 25
    assert disc.ledger_quantity == 0
    assert disc.severity == "CRITICAL"

    kill_switch.activate.assert_called_once()
    call_kwargs = kill_switch.activate.call_args.kwargs
    assert call_kwargs["source"] == "startup_reconciler"
    assert "Startup reconciliation mismatch" in call_kwargs["reason"]


def test_phantom_ledger_position_detected() -> None:
    """Discrepancy detected when local ledger reports position not at broker."""
    broker = MagicMock(spec=BrokerAdapter)
    broker.get_positions.return_value = []

    ledger = MagicMock()
    ledger.get_open_positions.return_value = [_make_position("SBIN", 50)]

    reconciler = StartupReconciler(broker=broker, ledger=ledger)
    result = reconciler.reconcile()

    assert result.reconciled is False
    assert reconciler.can_submit_orders() is False
    assert len(result.discrepancies) == 1

    disc = result.discrepancies[0]
    assert disc.discrepancy_type == "PHANTOM_LEDGER_POSITION"
    assert disc.instrument == "SBIN"
    assert disc.broker_quantity == 0
    assert disc.ledger_quantity == 50


def test_quantity_mismatch_detected() -> None:
    """Discrepancy detected when broker and ledger quantities differ."""
    broker = MagicMock(spec=BrokerAdapter)
    broker.get_positions.return_value = [_make_position("TATAMOTORS", 100)]

    ledger = MagicMock()
    ledger.get_open_positions.return_value = [_make_position("TATAMOTORS", 80)]

    reconciler = StartupReconciler(broker=broker, ledger=ledger)
    result = reconciler.reconcile()

    assert result.reconciled is False
    assert reconciler.can_submit_orders() is False
    assert len(result.discrepancies) == 1

    disc = result.discrepancies[0]
    assert disc.discrepancy_type == "QUANTITY_MISMATCH"
    assert disc.instrument == "TATAMOTORS"
    assert disc.broker_quantity == 100
    assert disc.ledger_quantity == 80


def test_raise_on_mismatch_flag() -> None:
    """When raise_on_mismatch is True, StartupReconciliationMismatchError is raised."""
    broker = MagicMock(spec=BrokerAdapter)
    broker.get_positions.return_value = [_make_position("INFY", 10)]

    ledger = MagicMock()
    ledger.get_open_positions.return_value = []

    reconciler = StartupReconciler(broker=broker, ledger=ledger)

    with pytest.raises(StartupReconciliationMismatchError) as exc_info:
        reconciler.reconcile(raise_on_mismatch=True)

    assert exc_info.value.result.reconciled is False
    assert len(exc_info.value.result.discrepancies) == 1


def test_auto_halt_disabled_does_not_activate_kill_switch() -> None:
    """When auto_halt_on_mismatch is False, kill switch is not triggered on mismatch."""
    broker = MagicMock(spec=BrokerAdapter)
    broker.get_positions.return_value = [_make_position("INFY", 10)]

    ledger = MagicMock()
    ledger.get_open_positions.return_value = []

    kill_switch = MagicMock(spec=KillSwitchProtocol)

    reconciler = StartupReconciler(
        broker=broker,
        ledger=ledger,
        kill_switch=kill_switch,
        auto_halt_on_mismatch=False,
    )
    result = reconciler.reconcile()

    assert result.reconciled is False
    kill_switch.activate.assert_not_called()


def test_broker_query_exception_fails_safe() -> None:
    """If broker position query raises an exception, reconciler fails safe."""
    broker = MagicMock(spec=BrokerAdapter)
    broker.get_positions.side_effect = RuntimeError("Broker connection timeout")

    ledger = MagicMock()
    kill_switch = MagicMock(spec=KillSwitchProtocol)

    reconciler = StartupReconciler(broker=broker, ledger=ledger, kill_switch=kill_switch)
    result = reconciler.reconcile()

    assert result.reconciled is False
    assert reconciler.can_submit_orders() is False
    assert len(result.discrepancies) == 1
    assert "connection timeout" in result.discrepancies[0].details
    kill_switch.activate.assert_called_once()

    # Verify raise_on_mismatch propagates exception as StartupReconciliationMismatchError
    with pytest.raises(StartupReconciliationMismatchError):
        reconciler.reconcile(raise_on_mismatch=True)


def test_broker_query_exception_without_kill_switch() -> None:
    """If broker query fails and kill_switch is None, safe state is still enforced."""
    broker = MagicMock(spec=BrokerAdapter)
    broker.get_positions.side_effect = RuntimeError("Network unreachable")

    ledger = MagicMock()
    reconciler = StartupReconciler(broker=broker, ledger=ledger, kill_switch=None)
    result = reconciler.reconcile()

    assert result.reconciled is False
    assert reconciler.can_submit_orders() is False
    assert len(result.discrepancies) == 1


def test_order_manager_active_orders_count_recorded() -> None:
    """Reconciliation result tracks working orders count from order manager."""
    broker = MagicMock(spec=BrokerAdapter)
    broker.get_positions.return_value = []

    ledger = MagicMock()
    ledger.get_open_positions.return_value = []

    order_manager = MagicMock(spec=OrderManager)
    order_manager.active_orders_count = 3

    reconciler = StartupReconciler(broker=broker, ledger=ledger, order_manager=order_manager)
    result = reconciler.reconcile()

    assert result.reconciled is True
    assert result.open_orders_count == 3


def test_manual_override_unlocks_trading() -> None:
    """Manual operator override unlocks trading and preserves discrepancy lineage."""
    broker = MagicMock(spec=BrokerAdapter)
    broker.get_positions.return_value = [_make_position("INFY", 10)]

    ledger = MagicMock()
    ledger.get_open_positions.return_value = []

    reconciler = StartupReconciler(broker=broker, ledger=ledger)
    first_result = reconciler.reconcile()
    assert first_result.reconciled is False
    assert reconciler.can_submit_orders() is False

    # Apply manual override
    override_result = reconciler.manual_override(
        operator_token="OPERATOR-OPS-01",
        reason="Broker position verified manually on web console; ledger will sync on next tick",
    )

    assert override_result.reconciled is True
    assert override_result.override_applied is True
    assert override_result.override_operator_id == "OPERATOR-OPS-01"
    assert "verified manually" in (override_result.override_reason or "")
    assert len(override_result.discrepancies) == 1
    assert reconciler.is_reconciled is True
    assert reconciler.can_submit_orders() is True


def test_manual_override_validation() -> None:
    """Manual override rejects invalid or blank operator token and rationale."""
    broker = MagicMock(spec=BrokerAdapter)
    ledger = MagicMock()

    reconciler = StartupReconciler(broker=broker, ledger=ledger)

    with pytest.raises(ValueError, match="Operator token required"):
        reconciler.manual_override(operator_token="", reason="Valid reason here")

    with pytest.raises(ValueError, match="Operator token required"):
        reconciler.manual_override(operator_token="AB", reason="Valid reason here")

    with pytest.raises(ValueError, match="Detailed rationale required"):
        reconciler.manual_override(operator_token="OPERATOR-1", reason="")

    with pytest.raises(ValueError, match="Detailed rationale required"):
        reconciler.manual_override(operator_token="OPERATOR-1", reason="noop")
