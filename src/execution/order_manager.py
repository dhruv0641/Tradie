"""Order lifecycle state machine and timeout escalation manager.

Implements the deterministic order state machine and audit trail per:
- FRD-EXEC-3 (order status tracking)
- FRD-EXEC-10 (timestamped audit logging for every lifecycle event)
- EDD §4 (order lifecycle state machine transitions)
- EDD §13 (5-second PENDING-to-SUBMITTED escalation timeout)
"""

import asyncio
import threading
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

import structlog
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.execution import OrderSubmission
from src.infrastructure.models import OrderSubmissionModel

logger = structlog.get_logger(__name__)

OrderStatus = Literal[
    "PENDING",
    "SUBMITTED",
    "PARTIAL",
    "FILLED",
    "CANCELLED",
    "REJECTED",
]

# Valid state transition mapping per EDD §4
VALID_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    "PENDING": {"SUBMITTED", "CANCELLED", "REJECTED"},
    "SUBMITTED": {"PARTIAL", "FILLED", "CANCELLED", "REJECTED"},
    "PARTIAL": {"PARTIAL", "FILLED", "CANCELLED"},
    "FILLED": set(),  # Terminal state
    "CANCELLED": set(),  # Terminal state
    "REJECTED": set(),  # Terminal state
}

TERMINAL_STATES: set[OrderStatus] = {"FILLED", "CANCELLED", "REJECTED"}


class OrderLifecycleError(Exception):
    """Base exception for order lifecycle management."""


class OrderNotFoundError(OrderLifecycleError):
    """Raised when an operation targets an unmanaged or unknown client_order_id."""


class InvalidStateTransitionError(OrderLifecycleError):
    """Raised when an order transition violates EDD §4 state machine rules."""


class OrderLifecycleEvent(BaseModel):
    """Immutable audit record capturing an order lifecycle state change (FRD-EXEC-10)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: UUID = Field(
        default_factory=uuid4, description="Unique primary key for the transition event"
    )
    client_order_id: str = Field(description="Deterministic client order ID")
    from_status: OrderStatus | None = Field(
        default=None, description="Previous lifecycle state (None on initial registration)"
    )
    to_status: OrderStatus = Field(description="New lifecycle state")
    reason: str | None = Field(
        default=None, description="Detailed explanation or rejection/escalation cause"
    )
    broker_order_id: str | None = Field(
        default=None, description="Exchange/broker assigned order ID"
    )
    filled_quantity: int | None = Field(
        default=None, ge=0, description="Cumulative filled quantity"
    )
    average_fill_price: Decimal | None = Field(
        default=None, ge=Decimal("0"), description="Average execution fill price"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Event generation timestamp in UTC",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Arbitrary context attributes for auditing"
    )

    @field_validator("timestamp")
    @classmethod
    def validate_utc_timestamp(cls, v: datetime) -> datetime:
        """Enforce timezone-aware UTC timestamp."""
        if v.tzinfo is None:
            msg = "Lifecycle event timestamp must be timezone-aware UTC"
            raise ValueError(msg)
        return v


class OrderManager:
    """Manages order state transitions, event audit logging, and timeout escalation.

    Enforces EDD §4 state transitions and EDD §13 5-second pending timeout rule.
    """

    def __init__(self, pending_timeout_seconds: float = 5.0) -> None:
        self.pending_timeout_seconds = pending_timeout_seconds
        self._orders: dict[str, OrderSubmission] = {}
        self._history: dict[str, list[OrderLifecycleEvent]] = {}
        self._filled_quantities: dict[str, int] = {}
        self._average_fill_prices: dict[str, Decimal] = {}
        self._rejection_reasons: dict[str, str] = {}
        self._sync_lock = threading.Lock()
        self._async_lock = asyncio.Lock()
        self._log = logger.bind(component="OrderManager")

    @property
    def total_orders_count(self) -> int:
        """Return total count of registered orders."""
        with self._sync_lock:
            return len(self._orders)

    @property
    def active_orders_count(self) -> int:
        """Return count of non-terminal working orders."""
        with self._sync_lock:
            return sum(1 for o in self._orders.values() if o.status not in TERMINAL_STATES)

    def get_order(self, client_order_id: str) -> OrderSubmission | None:
        """Retrieve current order snapshot by client_order_id."""
        with self._sync_lock:
            return self._orders.get(client_order_id)

    def get_history(self, client_order_id: str) -> list[OrderLifecycleEvent]:
        """Retrieve full event audit history for an order."""
        with self._sync_lock:
            return list(self._history.get(client_order_id, []))

    def get_orders_by_status(self, status: OrderStatus) -> list[OrderSubmission]:
        """Query all orders currently in a specific lifecycle state."""
        with self._sync_lock:
            return [o for o in self._orders.values() if o.status == status]

    def clear(self) -> None:
        """Clear all in-memory registries (for test isolation and session resets)."""
        with self._sync_lock:
            self._orders.clear()
            self._history.clear()
            self._filled_quantities.clear()
            self._average_fill_prices.clear()
            self._rejection_reasons.clear()

    def register_order(self, order: OrderSubmission) -> None:
        """Register a newly created order and record its initial event.

        Args:
            order: Initial OrderSubmission entity.

        Raises:
            ValueError: If client_order_id is already managed by this OrderManager.
        """
        with self._sync_lock:
            if order.client_order_id in self._orders:
                msg = f"Order '{order.client_order_id}' is already registered in OrderManager"
                raise ValueError(msg)

            self._orders[order.client_order_id] = order
            initial_event = OrderLifecycleEvent(
                client_order_id=order.client_order_id,
                from_status=None,
                to_status=order.status,
                reason="Initial order registration",
                broker_order_id=order.broker_order_id,
                timestamp=order.submitted_at,
            )
            self._history[order.client_order_id] = [initial_event]
            self._log.info(
                "Registered order",
                client_order_id=order.client_order_id,
                instrument=order.instrument,
                status=order.status,
            )

    def transition_to(
        self,
        client_order_id: str,
        new_status: OrderStatus,
        *,
        reason: str | None = None,
        broker_order_id: str | None = None,
        filled_quantity: int | None = None,
        average_fill_price: Decimal | None = None,
        timestamp: datetime | None = None,
    ) -> OrderSubmission:
        """Execute a state transition on a registered order.

        Args:
            client_order_id: Identifier of the order to transition.
            new_status: Target lifecycle state.
            reason: Optional justification or failure explanation.
            broker_order_id: Optional exchange/broker order ID.
            filled_quantity: Optional updated executed quantity.
            average_fill_price: Optional execution fill price.
            timestamp: Optional transition timestamp (defaults to UTC now).

        Returns:
            OrderSubmission: Updated order state.

        Raises:
            OrderNotFoundError: If client_order_id is not registered.
            InvalidStateTransitionError: If transition violates EDD §4 state machine.
        """
        with self._sync_lock:
            if client_order_id not in self._orders:
                msg = f"Order '{client_order_id}' not found in OrderManager"
                raise OrderNotFoundError(msg)

            current_order = self._orders[client_order_id]
            current_status = current_order.status

            # Disallow transitions from terminal states
            if current_status in TERMINAL_STATES:
                msg = (
                    f"Cannot transition order '{client_order_id}' from terminal state "
                    f"'{current_status}' to '{new_status}'"
                )
                raise InvalidStateTransitionError(msg)

            # Check valid transition rules per EDD §4
            if new_status not in VALID_TRANSITIONS[current_status]:
                msg = (
                    f"Invalid state transition for order '{client_order_id}': "
                    f"'{current_status}' -> '{new_status}'"
                )
                raise InvalidStateTransitionError(msg)

            now = timestamp or datetime.now(UTC)
            effective_broker_id = broker_order_id or current_order.broker_order_id

            # Create updated domain entity
            updated_order = OrderSubmission(
                client_order_id=current_order.client_order_id,
                broker_order_id=effective_broker_id,
                instrument=current_order.instrument,
                direction=current_order.direction,
                order_type=current_order.order_type,
                quantity=current_order.quantity,
                limit_price=current_order.limit_price,
                status=new_status,
                submitted_at=current_order.submitted_at,
                updated_at=now,
            )

            # Record event
            event = OrderLifecycleEvent(
                client_order_id=client_order_id,
                from_status=current_status,
                to_status=new_status,
                reason=reason,
                broker_order_id=effective_broker_id,
                filled_quantity=filled_quantity,
                average_fill_price=average_fill_price,
                timestamp=now,
            )

            self._orders[client_order_id] = updated_order
            self._history[client_order_id].append(event)

            if filled_quantity is not None:
                self._filled_quantities[client_order_id] = filled_quantity
            if average_fill_price is not None:
                self._average_fill_prices[client_order_id] = average_fill_price
            if reason and new_status == "REJECTED":
                self._rejection_reasons[client_order_id] = reason

            self._log.info(
                "Order state transitioned",
                client_order_id=client_order_id,
                from_status=current_status,
                to_status=new_status,
                reason=reason,
            )
            return updated_order

    def check_pending_timeouts(
        self,
        *,
        current_time: datetime | None = None,
        auto_cancel: bool = True,
    ) -> list[OrderSubmission]:
        """Inspect all PENDING orders and escalate any exceeding the 5-second threshold (EDD §13).

        Args:
            current_time: Optional current time (defaults to UTC now).
            auto_cancel: If True, transitions timed-out orders to CANCELLED.

        Returns:
            list[OrderSubmission]: Orders that exceeded the pending timeout threshold.
        """
        now = current_time or datetime.now(UTC)
        escalated: list[OrderSubmission] = []

        with self._sync_lock:
            pending_orders = [o for o in self._orders.values() if o.status == "PENDING"]

        for order in pending_orders:
            elapsed = (now - order.submitted_at).total_seconds()
            if elapsed > self.pending_timeout_seconds:
                self._log.warning(
                    "Order pending timeout exceeded (5-second threshold); escalating",
                    client_order_id=order.client_order_id,
                    elapsed_seconds=elapsed,
                    timeout_seconds=self.pending_timeout_seconds,
                )
                if auto_cancel:
                    msg = (
                        f"Pending submission timeout exceeded "
                        f"({elapsed:.1f}s > {self.pending_timeout_seconds}s)"
                    )
                    updated = self.transition_to(
                        order.client_order_id,
                        "CANCELLED",
                        reason=msg,
                        timestamp=now,
                    )
                    escalated.append(updated)
                else:
                    escalated.append(order)

        return escalated

    async def transition_to_transactional(
        self,
        session: AsyncSession,
        client_order_id: str,
        new_status: OrderStatus,
        *,
        reason: str | None = None,
        broker_order_id: str | None = None,
        filled_quantity: int | None = None,
        average_fill_price: Decimal | None = None,
        timestamp: datetime | None = None,
    ) -> OrderSubmission:
        """Asynchronously transition order state and synchronize with PostgreSQL order_submissions.

        Args:
            session: Active SQLAlchemy AsyncSession.
            client_order_id: Order identifier.
            new_status: Target lifecycle state.
            reason: Optional justification or failure explanation.
            broker_order_id: Optional broker-assigned order ID.
            filled_quantity: Optional cumulative filled quantity.
            average_fill_price: Optional execution price.
            timestamp: Optional transition timestamp.

        Returns:
            OrderSubmission: Updated order state.
        """
        async with self._async_lock:
            # Execute transition in memory
            updated = self.transition_to(
                client_order_id,
                new_status,
                reason=reason,
                broker_order_id=broker_order_id,
                filled_quantity=filled_quantity,
                average_fill_price=average_fill_price,
                timestamp=timestamp,
            )

            # Synchronize with PostgreSQL / SQLite table
            stmt = select(OrderSubmissionModel).where(
                OrderSubmissionModel.client_order_id == client_order_id
            )
            result = await session.execute(stmt)
            db_record = result.scalars().first()

            if db_record is not None:
                db_record.status = new_status
                db_record.updated_at = updated.updated_at
                if updated.broker_order_id is not None:
                    db_record.broker_order_id = updated.broker_order_id
                if filled_quantity is not None:
                    db_record.filled_quantity = filled_quantity
                if average_fill_price is not None:
                    db_record.average_fill_price = average_fill_price
                if reason is not None:
                    db_record.rejection_reason = reason

                await session.commit()
                self._log.info(
                    "Order state synchronized to database",
                    client_order_id=client_order_id,
                    new_status=new_status,
                )

            return updated
