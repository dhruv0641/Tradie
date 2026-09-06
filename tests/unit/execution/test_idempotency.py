"""Unit tests for client order ID generation and IdempotentOrderDispatcher."""

import concurrent.futures
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.domain.execution import OrderSubmission
from src.execution.broker_adapter import BrokerAdapter
from src.execution.idempotency import (
    IdempotentOrderDispatcher,
    generate_client_order_id,
)
from src.infrastructure.models import OrderSubmissionModel


def make_submission(
    client_order_id: str,
    instrument: str = "RELIANCE",
    direction: str = "BUY",
    quantity: int = 10,
    price: Decimal | None = Decimal("2500.00"),
) -> OrderSubmission:
    now = datetime.now(UTC)
    return OrderSubmission(
        client_order_id=client_order_id,
        broker_order_id=f"BRK-{client_order_id}",
        instrument=instrument,
        direction=direction,  # type: ignore[arg-type]
        order_type="LIMIT",
        quantity=quantity,
        limit_price=price,
        status="SUBMITTED",
        submitted_at=now,
        updated_at=now,
    )


def test_generate_client_order_id() -> None:
    """Verify deterministic formatting from UUID and string."""
    uid = uuid4()
    order_id = generate_client_order_id(uid)
    assert order_id == f"aitrader-{uid}"

    order_id_custom = generate_client_order_id("test-decision-123", prefix="live")
    assert order_id_custom == "live-test-decision-123"


def test_generate_client_order_id_validation() -> None:
    """Verify rejection of empty IDs and prefixes."""
    with pytest.raises(ValueError, match="decision_record_id must not be empty"):
        generate_client_order_id("")

    with pytest.raises(ValueError, match="decision_record_id must not be empty"):
        generate_client_order_id("   ")

    with pytest.raises(ValueError, match="prefix must not be empty"):
        generate_client_order_id("valid-id", prefix="")


def test_idempotent_dispatcher_sync_single_and_duplicate() -> None:
    """Verify dispatcher sends initial order and caches subsequent duplicates without resending."""
    dispatcher = IdempotentOrderDispatcher()
    assert dispatcher.registered_orders_count == 0

    mock_broker = MagicMock(spec=BrokerAdapter)
    mock_broker.place_order.side_effect = lambda **kwargs: make_submission(
        kwargs["client_order_id"]
    )

    # First dispatch
    order1 = dispatcher.dispatch_order(
        broker=mock_broker,
        client_order_id="order-alpha",
        instrument="RELIANCE",
        direction="BUY",
        quantity=10,
        order_type="LIMIT",
        price=Decimal("2500.00"),
    )
    assert order1.client_order_id == "order-alpha"
    assert mock_broker.place_order.call_count == 1
    assert dispatcher.registered_orders_count == 1
    assert dispatcher.has_submission("order-alpha") is True
    assert dispatcher.get_submission("order-alpha") == order1

    # Second dispatch with identical client_order_id
    order2 = dispatcher.dispatch_order(
        broker=mock_broker,
        client_order_id="order-alpha",
        instrument="RELIANCE",
        direction="BUY",
        quantity=10,
        order_type="LIMIT",
        price=Decimal("2500.00"),
    )
    # Broker must NOT be called a second time
    assert mock_broker.place_order.call_count == 1
    assert order2 == order1

    # Third dispatch with different client_order_id
    order3 = dispatcher.dispatch_order(
        broker=mock_broker,
        client_order_id="order-beta",
        instrument="TCS",
        direction="SELL",
        quantity=5,
        order_type="LIMIT",
        price=Decimal("3800.00"),
    )
    assert mock_broker.place_order.call_count == 2
    assert order3.client_order_id == "order-beta"
    assert dispatcher.registered_orders_count == 2

    # Clear registry
    dispatcher.clear()
    assert dispatcher.registered_orders_count == 0
    assert dispatcher.has_submission("order-alpha") is False
    assert dispatcher.get_submission("order-alpha") is None


def test_idempotent_dispatcher_concurrent_dispatch() -> None:
    """Verify thread-safety when multiple threads dispatch identical client_order_id."""
    dispatcher = IdempotentOrderDispatcher()
    mock_broker = MagicMock(spec=BrokerAdapter)
    mock_broker.place_order.side_effect = lambda **kwargs: make_submission(
        kwargs["client_order_id"]
    )

    client_id = "concurrent-order-001"

    def worker() -> OrderSubmission:
        return dispatcher.dispatch_order(
            broker=mock_broker,
            client_order_id=client_id,
            instrument="INFY",
            direction="BUY",
            quantity=20,
            order_type="LIMIT",
            price=Decimal("1500.00"),
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(worker) for _ in range(20)]
        results = [f.result() for f in futures]

    # Broker must have been called exactly once
    assert mock_broker.place_order.call_count == 1
    # All threads received the identical submission
    for res in results:
        assert res.client_order_id == client_id


@pytest.mark.asyncio
async def test_idempotent_dispatcher_transactional_new_order() -> None:
    """Verify transactional dispatch persists new order to database."""
    dispatcher = IdempotentOrderDispatcher()
    mock_broker = MagicMock(spec=BrokerAdapter)
    mock_broker.place_order.side_effect = lambda **kwargs: make_submission(
        kwargs["client_order_id"]
    )

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_session.execute.return_value = mock_result
    mock_session.add = MagicMock()

    submission = await dispatcher.dispatch_order_transactional(
        broker=mock_broker,
        session=mock_session,
        client_order_id="tx-order-001",
        instrument="HDFCBANK",
        direction="BUY",
        quantity=15,
        order_type="LIMIT",
        price=Decimal("1600.00"),
        decision_record_id="dec-123",
    )

    assert submission.client_order_id == "tx-order-001"
    assert mock_broker.place_order.call_count == 1
    mock_session.add.assert_called_once()
    mock_session.commit.assert_awaited_once()
    assert dispatcher.has_submission("tx-order-001") is True


@pytest.mark.asyncio
async def test_idempotent_dispatcher_transactional_in_memory_intercept() -> None:
    """Verify transactional dispatch intercepts already-cached orders without hitting DB."""
    dispatcher = IdempotentOrderDispatcher()
    mock_broker = MagicMock(spec=BrokerAdapter)
    mock_session = AsyncMock()

    cached_sub = make_submission("cached-order-001")
    dispatcher._orders["cached-order-001"] = cached_sub

    submission = await dispatcher.dispatch_order_transactional(
        broker=mock_broker,
        session=mock_session,
        client_order_id="cached-order-001",
        instrument="RELIANCE",
        direction="BUY",
        quantity=10,
    )

    assert submission == cached_sub
    mock_broker.place_order.assert_not_called()
    mock_session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_idempotent_dispatcher_transactional_db_intercept() -> None:
    """Verify transactional dispatch recovers existing order from database on cold cache."""
    dispatcher = IdempotentOrderDispatcher()
    mock_broker = MagicMock(spec=BrokerAdapter)

    now = datetime.now(UTC)
    db_model = OrderSubmissionModel(
        client_order_id="cold-db-order-001",
        broker_order_id="BRK-999",
        decision_record_id="dec-abc",
        instrument="SBIN",
        direction="SELL",
        order_type="LIMIT",
        limit_price=Decimal("800.00"),
        quantity=50,
        filled_quantity=0,
        average_fill_price=Decimal("0.0000"),
        status="SUBMITTED",
        submitted_at=now,
        updated_at=now,
    )

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = db_model
    mock_session.execute.return_value = mock_result

    submission = await dispatcher.dispatch_order_transactional(
        broker=mock_broker,
        session=mock_session,
        client_order_id="cold-db-order-001",
        instrument="SBIN",
        direction="SELL",
        quantity=50,
        order_type="LIMIT",
        price=Decimal("800.00"),
    )

    assert submission.client_order_id == "cold-db-order-001"
    assert submission.broker_order_id == "BRK-999"
    assert submission.direction == "SELL"
    assert submission.status == "SUBMITTED"
    mock_broker.place_order.assert_not_called()
    assert dispatcher.has_submission("cold-db-order-001") is True


@pytest.mark.asyncio
async def test_idempotent_dispatcher_transactional_db_naive_timestamp() -> None:
    """Verify handling of database model with naive timestamps converts to UTC."""
    dispatcher = IdempotentOrderDispatcher()
    mock_broker = MagicMock(spec=BrokerAdapter)

    naive_dt = datetime(2026, 9, 6, 12, 0, 0)
    db_model = OrderSubmissionModel(
        client_order_id="naive-order",
        broker_order_id="BRK-NAIVE",
        decision_record_id=None,
        instrument="WIPRO",
        direction="BUY",
        order_type="LIMIT",
        limit_price=Decimal("500.00"),
        quantity=25,
        filled_quantity=0,
        average_fill_price=Decimal("0.0000"),
        status="PENDING",
        submitted_at=naive_dt,
        updated_at=naive_dt,
    )

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = db_model
    mock_session.execute.return_value = mock_result

    submission = await dispatcher.dispatch_order_transactional(
        broker=mock_broker,
        session=mock_session,
        client_order_id="naive-order",
        instrument="WIPRO",
        direction="BUY",
        quantity=25,
    )

    assert submission.submitted_at.tzinfo == UTC
    assert submission.updated_at.tzinfo == UTC
