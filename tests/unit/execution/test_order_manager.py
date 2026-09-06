"""Unit tests for OrderManager state machine, audit logging, and pending timeout escalation.

Verifies:
- FRD-EXEC-3 (order state tracking)
- FRD-EXEC-10 (timestamped audit logging for every lifecycle event)
- EDD §4 (order lifecycle transitions and terminal immutability)
- EDD §13 (5-second pending timeout manager)
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.execution import OrderSubmission
from src.execution.order_manager import (
    TERMINAL_STATES,
    VALID_TRANSITIONS,
    InvalidStateTransitionError,
    OrderLifecycleError,
    OrderLifecycleEvent,
    OrderManager,
    OrderNotFoundError,
    OrderStatus,
)
from src.infrastructure.models import OrderSubmissionModel


def _create_sample_order(
    client_order_id: str = "order-test-1",
    status: OrderStatus = "PENDING",
    submitted_at: datetime | None = None,
) -> OrderSubmission:
    now = submitted_at or datetime.now(UTC)
    return OrderSubmission(
        client_order_id=client_order_id,
        broker_order_id=None,
        instrument="RELIANCE",
        direction="BUY",
        order_type="LIMIT",
        quantity=10,
        limit_price=Decimal("2500.00"),
        status=status,
        submitted_at=now,
        updated_at=now,
    )


def test_order_manager_initial_state() -> None:
    """Verify clean initial state of OrderManager."""
    mgr = OrderManager(pending_timeout_seconds=5.0)
    assert mgr.pending_timeout_seconds == 5.0
    assert mgr.total_orders_count == 0
    assert mgr.active_orders_count == 0
    assert mgr.get_order("unknown") is None
    assert mgr.get_history("unknown") == []
    assert mgr.get_orders_by_status("PENDING") == []


def test_order_registration_and_initial_audit_event() -> None:
    """Verify order registration records initial state and audit event (FRD-EXEC-10)."""
    mgr = OrderManager()
    order = _create_sample_order("ORD-101", status="PENDING")

    mgr.register_order(order)
    assert mgr.total_orders_count == 1
    assert mgr.active_orders_count == 1

    retrieved = mgr.get_order("ORD-101")
    assert retrieved is not None
    assert retrieved.client_order_id == "ORD-101"
    assert retrieved.status == "PENDING"

    history = mgr.get_history("ORD-101")
    assert len(history) == 1
    initial_event = history[0]
    assert initial_event.client_order_id == "ORD-101"
    assert initial_event.from_status is None
    assert initial_event.to_status == "PENDING"
    assert initial_event.reason == "Initial order registration"
    assert initial_event.timestamp == order.submitted_at


def test_register_duplicate_order_raises_value_error() -> None:
    """Verify duplicate client_order_id registration is rejected."""
    mgr = OrderManager()
    order = _create_sample_order("ORD-DUP")
    mgr.register_order(order)

    with pytest.raises(ValueError, match="already registered"):
        mgr.register_order(order)


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        ("PENDING", "SUBMITTED"),
        ("PENDING", "CANCELLED"),
        ("PENDING", "REJECTED"),
        ("SUBMITTED", "PARTIAL"),
        ("SUBMITTED", "FILLED"),
        ("SUBMITTED", "CANCELLED"),
        ("SUBMITTED", "REJECTED"),
        ("PARTIAL", "PARTIAL"),
        ("PARTIAL", "FILLED"),
        ("PARTIAL", "CANCELLED"),
    ],
)
def test_valid_state_transitions(from_status: OrderStatus, to_status: OrderStatus) -> None:
    """Verify all legal transitions per EDD §4 succeed."""
    mgr = OrderManager()
    order = _create_sample_order("ORD-TRANS", status=from_status)
    mgr.register_order(order)

    updated = mgr.transition_to(
        "ORD-TRANS",
        to_status,
        reason=f"Transitioning from {from_status} to {to_status}",
        broker_order_id="BRK-12345",
        filled_quantity=5 if to_status in ("PARTIAL", "FILLED") else None,
        average_fill_price=Decimal("2501.50") if to_status in ("PARTIAL", "FILLED") else None,
    )

    assert updated.status == to_status
    assert updated.broker_order_id == "BRK-12345"

    history = mgr.get_history("ORD-TRANS")
    assert len(history) == 2
    assert history[1].from_status == from_status
    assert history[1].to_status == to_status
    assert history[1].broker_order_id == "BRK-12345"


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        ("PENDING", "PARTIAL"),
        ("PENDING", "FILLED"),
        ("SUBMITTED", "PENDING"),
        ("PARTIAL", "SUBMITTED"),
        ("PARTIAL", "PENDING"),
        ("PARTIAL", "REJECTED"),
    ],
)
def test_invalid_state_transitions_rejected(
    from_status: OrderStatus, to_status: OrderStatus
) -> None:
    """Verify illegal transitions violate state machine and raise InvalidStateTransitionError."""
    mgr = OrderManager()
    order = _create_sample_order("ORD-ILLEGAL", status=from_status)
    mgr.register_order(order)

    with pytest.raises(InvalidStateTransitionError, match="Invalid state transition"):
        mgr.transition_to("ORD-ILLEGAL", to_status)


@pytest.mark.parametrize("terminal_status", ["FILLED", "CANCELLED", "REJECTED"])
@pytest.mark.parametrize(
    "target_status", ["PENDING", "SUBMITTED", "PARTIAL", "FILLED", "CANCELLED", "REJECTED"]
)
def test_terminal_states_are_immutable(
    terminal_status: OrderStatus, target_status: OrderStatus
) -> None:
    """Verify terminal states (FILLED, CANCELLED, REJECTED) reject transitions (EDD §4)."""
    mgr = OrderManager()
    order = _create_sample_order("ORD-TERM", status=terminal_status)
    mgr.register_order(order)

    with pytest.raises(InvalidStateTransitionError, match="from terminal state"):
        mgr.transition_to("ORD-TERM", target_status)


def test_transition_unknown_order_raises_not_found() -> None:
    """Verify modifying an unregistered order raises OrderNotFoundError."""
    mgr = OrderManager()
    with pytest.raises(OrderNotFoundError, match="not found"):
        mgr.transition_to("NONEXISTENT", "SUBMITTED")


def test_active_orders_count_and_filtering() -> None:
    """Verify active orders count drops when orders reach terminal states."""
    mgr = OrderManager()
    o1 = _create_sample_order("ORD-1", "PENDING")
    o2 = _create_sample_order("ORD-2", "PENDING")
    o3 = _create_sample_order("ORD-3", "PENDING")

    mgr.register_order(o1)
    mgr.register_order(o2)
    mgr.register_order(o3)
    assert mgr.active_orders_count == 3

    mgr.transition_to("ORD-1", "SUBMITTED")
    mgr.transition_to("ORD-1", "FILLED")
    assert mgr.active_orders_count == 2

    mgr.transition_to("ORD-2", "CANCELLED")
    assert mgr.active_orders_count == 1

    mgr.transition_to("ORD-3", "REJECTED")
    assert mgr.active_orders_count == 0
    assert mgr.total_orders_count == 3

    assert len(mgr.get_orders_by_status("FILLED")) == 1
    assert len(mgr.get_orders_by_status("CANCELLED")) == 1
    assert len(mgr.get_orders_by_status("REJECTED")) == 1
    assert len(mgr.get_orders_by_status("SUBMITTED")) == 0


def test_pending_timeouts_escalation_and_auto_cancel() -> None:
    """Verify 5-second pending timeout escalates and auto-cancels stale orders (EDD §13)."""
    mgr = OrderManager(pending_timeout_seconds=5.0)
    base_time = datetime.now(UTC)

    # Order 1: submitted 2 seconds ago (still valid, within 5s window)
    o1 = _create_sample_order(
        "ORD-FRESH", status="PENDING", submitted_at=base_time - timedelta(seconds=2)
    )
    # Order 2: submitted 6 seconds ago (exceeded 5s threshold)
    o2 = _create_sample_order(
        "ORD-STALE", status="PENDING", submitted_at=base_time - timedelta(seconds=6)
    )
    # Order 3: submitted 10 seconds ago, but already SUBMITTED (not pending, should not cancel)
    o3 = _create_sample_order(
        "ORD-WORKING", status="SUBMITTED", submitted_at=base_time - timedelta(seconds=10)
    )

    mgr.register_order(o1)
    mgr.register_order(o2)
    mgr.register_order(o3)

    escalated = mgr.check_pending_timeouts(current_time=base_time, auto_cancel=True)
    assert len(escalated) == 1
    assert escalated[0].client_order_id == "ORD-STALE"
    assert escalated[0].status == "CANCELLED"

    stale_order = mgr.get_order("ORD-STALE")
    assert stale_order is not None
    assert stale_order.status == "CANCELLED"

    history = mgr.get_history("ORD-STALE")
    assert len(history) == 2
    assert history[1].to_status == "CANCELLED"
    assert "Pending submission timeout exceeded" in (history[1].reason or "")

    fresh_order = mgr.get_order("ORD-FRESH")
    assert fresh_order is not None
    assert fresh_order.status == "PENDING"

    working_order = mgr.get_order("ORD-WORKING")
    assert working_order is not None
    assert working_order.status == "SUBMITTED"


def test_pending_timeouts_no_auto_cancel() -> None:
    """Verify check_pending_timeouts returns timed-out orders without auto-cancelling."""
    mgr = OrderManager(pending_timeout_seconds=5.0)
    base_time = datetime.now(UTC)
    o = _create_sample_order(
        "ORD-EXPIRE", status="PENDING", submitted_at=base_time - timedelta(seconds=8)
    )
    mgr.register_order(o)

    escalated = mgr.check_pending_timeouts(current_time=base_time, auto_cancel=False)
    assert len(escalated) == 1
    assert escalated[0].client_order_id == "ORD-EXPIRE"
    assert escalated[0].status == "PENDING"


def test_clear_resets_manager() -> None:
    """Verify clear() wipes all registered state."""
    mgr = OrderManager()
    mgr.register_order(_create_sample_order("ORD-1"))
    assert mgr.total_orders_count == 1

    mgr.clear()
    assert mgr.total_orders_count == 0
    assert mgr.active_orders_count == 0
    assert mgr.get_order("ORD-1") is None


def test_order_lifecycle_event_timezone_validation() -> None:
    """Verify OrderLifecycleEvent rejects naive datetime."""
    naive_now = datetime.now()  # no tzinfo
    with pytest.raises(ValueError, match="must be timezone-aware UTC"):
        OrderLifecycleEvent(
            client_order_id="ORD-1",
            from_status=None,
            to_status="PENDING",
            timestamp=naive_now,
        )


@pytest.mark.asyncio
async def test_transition_to_transactional_syncs_database() -> None:
    """Verify transition_to_transactional updates in-memory state and PostgreSQL record."""
    mgr = OrderManager()
    order = _create_sample_order("ORD-DB-1", status="PENDING")
    mgr.register_order(order)

    # Mock DB record and session
    mock_db_record = MagicMock(spec=OrderSubmissionModel)
    mock_db_record.client_order_id = "ORD-DB-1"
    mock_db_record.status = "PENDING"
    mock_db_record.broker_order_id = None
    mock_db_record.filled_quantity = 0
    mock_db_record.average_fill_price = None
    mock_db_record.rejection_reason = None

    mock_scalars = MagicMock()
    mock_scalars.first.return_value = mock_db_record
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    updated = await mgr.transition_to_transactional(
        session=mock_session,
        client_order_id="ORD-DB-1",
        new_status="SUBMITTED",
        broker_order_id="BROKER-999",
        reason="Order accepted by exchange",
    )

    assert updated.status == "SUBMITTED"
    assert updated.broker_order_id == "BROKER-999"

    # Verify DB record properties updated
    assert mock_db_record.status == "SUBMITTED"
    assert mock_db_record.broker_order_id == "BROKER-999"
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_transition_to_transactional_handles_missing_db_record() -> None:
    """Verify transition_to_transactional succeeds gracefully if no matching DB record exists."""
    mgr = OrderManager()
    order = _create_sample_order("ORD-DB-2", status="PENDING")
    mgr.register_order(order)

    mock_scalars = MagicMock()
    mock_scalars.first.return_value = None
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    updated = await mgr.transition_to_transactional(
        session=mock_session,
        client_order_id="ORD-DB-2",
        new_status="CANCELLED",
        reason="Cancelled before DB persist",
    )

    assert updated.status == "CANCELLED"
    mock_session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_transition_to_transactional_with_fills_and_reasons() -> None:
    """Verify transition_to_transactional synchronizes filled_quantity and average_fill_price."""
    mgr = OrderManager()
    order = _create_sample_order("ORD-DB-3", status="SUBMITTED")
    mgr.register_order(order)

    mock_db_record = MagicMock(spec=OrderSubmissionModel)
    mock_db_record.client_order_id = "ORD-DB-3"
    mock_db_record.status = "SUBMITTED"
    mock_db_record.broker_order_id = "BRK-1"
    mock_db_record.filled_quantity = 0
    mock_db_record.average_fill_price = None
    mock_db_record.rejection_reason = None

    mock_scalars = MagicMock()
    mock_scalars.first.return_value = mock_db_record
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    updated = await mgr.transition_to_transactional(
        session=mock_session,
        client_order_id="ORD-DB-3",
        new_status="FILLED",
        filled_quantity=10,
        average_fill_price=Decimal("2505.25"),
        reason="Fully executed",
    )

    assert updated.status == "FILLED"
    assert mock_db_record.status == "FILLED"
    assert mock_db_record.filled_quantity == 10
    assert mock_db_record.average_fill_price == Decimal("2505.25")
    assert mock_db_record.rejection_reason == "Fully executed"
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_transition_to_transactional_without_optional_fields() -> None:
    """Verify transition_to_transactional handles None for optional fields."""
    mgr = OrderManager()
    order = _create_sample_order("ORD-DB-4", status="PENDING")
    mgr.register_order(order)

    mock_db_record = MagicMock(spec=OrderSubmissionModel)
    mock_db_record.client_order_id = "ORD-DB-4"
    mock_db_record.status = "PENDING"
    mock_db_record.broker_order_id = None
    mock_db_record.filled_quantity = None
    mock_db_record.average_fill_price = None
    mock_db_record.rejection_reason = None

    mock_scalars = MagicMock()
    mock_scalars.first.return_value = mock_db_record
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    updated = await mgr.transition_to_transactional(
        session=mock_session,
        client_order_id="ORD-DB-4",
        new_status="CANCELLED",
        reason=None,
        broker_order_id=None,
        filled_quantity=None,
        average_fill_price=None,
    )

    assert updated.status == "CANCELLED"
    assert mock_db_record.status == "CANCELLED"
    assert mock_db_record.broker_order_id is None
    mock_session.commit.assert_awaited_once()


def test_exception_inheritance_and_valid_transitions_mapping() -> None:
    """Verify OrderLifecycleError inheritance and VALID_TRANSITIONS coverage."""
    assert issubclass(OrderNotFoundError, OrderLifecycleError)
    assert issubclass(InvalidStateTransitionError, OrderLifecycleError)
    assert "FILLED" in TERMINAL_STATES
    assert "CANCELLED" in TERMINAL_STATES
    assert "REJECTED" in TERMINAL_STATES
    for term in TERMINAL_STATES:
        assert len(VALID_TRANSITIONS[term]) == 0
