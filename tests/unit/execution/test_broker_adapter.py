from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

import pytest

from src.domain.execution import OrderSubmission, Position
from src.execution.broker_adapter import (
    BaseBrokerAdapter,
    BrokerAdapter,
    BrokerAuthenticationError,
    BrokerConnectionError,
    BrokerError,
    BrokerOrderError,
    BrokerOrderNotFoundError,
    BrokerRateLimitError,
)


class DummyBrokerAdapter(BaseBrokerAdapter):
    """Concrete implementation for testing BaseBrokerAdapter."""

    def __init__(self, broker_name: str = "DummyBroker") -> None:
        super().__init__(broker_name=broker_name)

    def authenticate(self) -> bool:
        self._is_authenticated = True
        return True

    def place_order(
        self,
        client_order_id: str,
        instrument: str,
        direction: Literal["BUY", "SELL"],
        quantity: int,
        *,
        order_type: Literal["LIMIT", "MARKET"] = "LIMIT",
        price: Decimal | None = None,
    ) -> OrderSubmission:
        now = datetime.now(UTC)
        return OrderSubmission(
            client_order_id=client_order_id,
            broker_order_id=f"BRK-{client_order_id}",
            instrument=instrument,
            direction=direction,
            order_type=order_type,
            quantity=quantity,
            limit_price=price,
            status="SUBMITTED",
            submitted_at=now,
            updated_at=now,
        )

    def cancel_order(self, client_order_id: str) -> bool:
        return client_order_id != "INVALID"

    def modify_order(
        self,
        client_order_id: str,
        quantity: int | None = None,
        price: Decimal | None = None,
    ) -> OrderSubmission:
        now = datetime.now(UTC)
        return OrderSubmission(
            client_order_id=client_order_id,
            broker_order_id=f"BRK-{client_order_id}",
            instrument="RELIANCE",
            direction="BUY",
            order_type="LIMIT",
            quantity=quantity or 10,
            limit_price=price or Decimal("2500.00"),
            status="SUBMITTED",
            submitted_at=now,
            updated_at=now,
        )

    def get_positions(self) -> list[Position]:
        return []

    def get_order_status(self, client_order_id: str) -> OrderSubmission:
        now = datetime.now(UTC)
        return OrderSubmission(
            client_order_id=client_order_id,
            broker_order_id=f"BRK-{client_order_id}",
            instrument="RELIANCE",
            direction="BUY",
            order_type="LIMIT",
            quantity=10,
            limit_price=Decimal("2500.00"),
            status="FILLED",
            submitted_at=now,
            updated_at=now,
        )

    def heartbeat(self) -> bool:
        return self._is_authenticated


def test_broker_adapter_protocol_runtime_check() -> None:
    """Verify DummyBrokerAdapter satisfies BrokerAdapter runtime check."""
    adapter = DummyBrokerAdapter()
    assert isinstance(adapter, BrokerAdapter)


def test_broker_adapter_protocol_negative_check() -> None:
    """Verify an object missing methods fails BrokerAdapter runtime check."""

    class IncompleteAdapter:
        def authenticate(self) -> bool:
            return True

    assert not isinstance(IncompleteAdapter(), BrokerAdapter)


def test_base_broker_adapter_lifecycle() -> None:
    """Verify BaseBrokerAdapter initialization, authentication flag, and methods."""
    adapter = DummyBrokerAdapter(broker_name="TestKite")
    assert adapter.broker_name == "TestKite"
    assert bool(adapter.is_authenticated) is False

    assert adapter.authenticate()
    assert bool(adapter.is_authenticated) is True
    assert adapter.heartbeat()

    submission = adapter.place_order(
        client_order_id="order-1",
        instrument="TCS",
        direction="BUY",
        quantity=5,
        order_type="LIMIT",
        price=Decimal("3800.00"),
    )
    assert submission.client_order_id == "order-1"
    assert submission.status == "SUBMITTED"
    assert submission.limit_price == Decimal("3800.00")

    modified = adapter.modify_order("order-1", quantity=10, price=Decimal("3810.00"))
    assert modified.quantity == 10
    assert modified.limit_price == Decimal("3810.00")

    status = adapter.get_order_status("order-1")
    assert status.status == "FILLED"

    assert adapter.cancel_order("order-1") is True
    assert adapter.cancel_order("INVALID") is False
    assert adapter.get_positions() == []


def test_cannot_instantiate_abstract_base_broker_adapter() -> None:
    """Verify BaseBrokerAdapter cannot be instantiated directly."""
    with pytest.raises(TypeError):
        BaseBrokerAdapter("Base")  # type: ignore[abstract]


def test_broker_exception_hierarchy() -> None:
    """Verify custom broker exception inheritance and string formatting."""
    assert issubclass(BrokerAuthenticationError, BrokerError)
    assert issubclass(BrokerConnectionError, BrokerError)
    assert issubclass(BrokerOrderError, BrokerError)
    assert issubclass(BrokerOrderNotFoundError, BrokerOrderError)
    assert issubclass(BrokerRateLimitError, BrokerError)

    err = BrokerAuthenticationError("Invalid API key")
    assert str(err) == "Invalid API key"
    assert isinstance(err, BrokerError)
