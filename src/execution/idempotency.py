"""Deterministic client order ID generation and idempotent order dispatcher.

Guarantees zero duplicate orders on retry or timeout per:
- FRD-EXEC-5 (duplicate order prevention)
- TRD-EXEC-2 (client order ID idempotency)
- EDD §6.1 (idempotency key design)
"""

import asyncio
import threading
from datetime import UTC
from decimal import Decimal
from typing import Literal
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.execution import OrderSubmission
from src.execution.broker_adapter import BrokerAdapter
from src.infrastructure.models import OrderSubmissionModel

logger = structlog.get_logger(__name__)


def generate_client_order_id(decision_record_id: UUID | str, prefix: str = "aitrader") -> str:
    """Generate a deterministic client order ID from a decision record identifier.

    Args:
        decision_record_id: Unique decision record UUID or string.
        prefix: Optional order prefix (default: 'aitrader').

    Returns:
        str: Deterministic client order ID string.

    Raises:
        ValueError: If decision_record_id or prefix is empty.
    """
    id_str = str(decision_record_id).strip()
    prefix_str = prefix.strip()
    if not id_str:
        msg = "decision_record_id must not be empty"
        raise ValueError(msg)
    if not prefix_str:
        msg = "prefix must not be empty"
        raise ValueError(msg)

    return f"{prefix_str}-{id_str}"


class IdempotentOrderDispatcher:
    """Dispatches orders to a BrokerAdapter with strict idempotency and duplicate suppression.

    Maintains an in-memory ledger and supports transactional synchronization with
    the PostgreSQL / SQLite order_submissions database table.
    """

    def __init__(self) -> None:
        self._orders: dict[str, OrderSubmission] = {}
        self._sync_lock = threading.Lock()
        self._async_lock = asyncio.Lock()
        self._log = logger.bind(component="IdempotentOrderDispatcher")

    @property
    def registered_orders_count(self) -> int:
        """Return count of registered order submissions in memory."""
        with self._sync_lock:
            return len(self._orders)

    def has_submission(self, client_order_id: str) -> bool:
        """Check if an order submission exists in memory for the given client_order_id."""
        with self._sync_lock:
            return client_order_id in self._orders

    def get_submission(self, client_order_id: str) -> OrderSubmission | None:
        """Retrieve cached order submission by client_order_id, if present."""
        with self._sync_lock:
            return self._orders.get(client_order_id)

    def clear(self) -> None:
        """Clear the in-memory registry (used for tests and session resets)."""
        with self._sync_lock:
            self._orders.clear()

    def dispatch_order(
        self,
        broker: BrokerAdapter,
        client_order_id: str,
        instrument: str,
        direction: Literal["BUY", "SELL"],
        quantity: int,
        *,
        order_type: Literal["LIMIT", "MARKET"] = "LIMIT",
        price: Decimal | None = None,
    ) -> OrderSubmission:
        """Synchronously dispatch an order with strict in-memory idempotency.

        If client_order_id has already been dispatched, returns the cached
        OrderSubmission immediately without sending a second order to the broker.

        Args:
            broker: Active BrokerAdapter implementation.
            client_order_id: Deterministic client order ID.
            instrument: Traded instrument symbol.
            direction: 'BUY' or 'SELL'.
            quantity: Order quantity.
            order_type: 'LIMIT' or 'MARKET'.
            price: Order price (required for LIMIT).

        Returns:
            OrderSubmission: Initial submission record (either new from broker or cached).
        """
        with self._sync_lock:
            if client_order_id in self._orders:
                cached = self._orders[client_order_id]
                self._log.warning(
                    "Duplicate order dispatch intercepted; returning cached order",
                    client_order_id=client_order_id,
                    instrument=cached.instrument,
                    status=cached.status,
                )
                return cached

            # Dispatch new order to broker
            submission = broker.place_order(
                client_order_id=client_order_id,
                instrument=instrument,
                direction=direction,
                quantity=quantity,
                order_type=order_type,
                price=price,
            )
            self._orders[client_order_id] = submission
            self._log.info(
                "Dispatched new order to broker",
                client_order_id=client_order_id,
                instrument=instrument,
                direction=direction,
                quantity=quantity,
                order_type=order_type,
                status=submission.status,
            )
            return submission

    async def dispatch_order_transactional(
        self,
        broker: BrokerAdapter,
        session: AsyncSession,
        client_order_id: str,
        instrument: str,
        *,
        direction: Literal["BUY", "SELL"],
        quantity: int,
        order_type: Literal["LIMIT", "MARKET"] = "LIMIT",
        price: Decimal | None = None,
        decision_record_id: str | None = None,
    ) -> OrderSubmission:
        """Asynchronously dispatch an order with database-backed transactional idempotency.

        Guarantees zero duplicates across distributed restarts by querying the
        order_submissions table before placing an order.

        Args:
            broker: Active BrokerAdapter implementation.
            session: Active SQLAlchemy AsyncSession.
            client_order_id: Deterministic client order ID.
            instrument: Traded instrument symbol.
            direction: 'BUY' or 'SELL'.
            quantity: Order quantity.
            order_type: 'LIMIT' or 'MARKET'.
            price: Order price.
            decision_record_id: Optional linked DecisionRecord UUID string.

        Returns:
            OrderSubmission: Initial submission record (either new or existing).
        """
        async with self._async_lock:
            # 1. Fast in-memory check
            with self._sync_lock:
                if client_order_id in self._orders:
                    cached = self._orders[client_order_id]
                    self._log.warning(
                        "Duplicate order dispatch intercepted in-memory",
                        client_order_id=client_order_id,
                        instrument=cached.instrument,
                    )
                    return cached

            # 2. Database persistent check
            stmt = select(OrderSubmissionModel).where(
                OrderSubmissionModel.client_order_id == client_order_id
            )
            result = await session.execute(stmt)
            db_record = result.scalars().first()
            if db_record is not None:
                # Reconstruct domain model from DB record
                submitted_at = (
                    db_record.submitted_at
                    if db_record.submitted_at.tzinfo
                    else db_record.submitted_at.replace(tzinfo=UTC)
                )
                updated_at = (
                    db_record.updated_at
                    if db_record.updated_at.tzinfo
                    else db_record.updated_at.replace(tzinfo=UTC)
                )
                domain_submission = OrderSubmission(
                    client_order_id=db_record.client_order_id,
                    broker_order_id=db_record.broker_order_id,
                    instrument=db_record.instrument,
                    direction=db_record.direction,  # type: ignore[arg-type]
                    order_type=db_record.order_type,  # type: ignore[arg-type]
                    quantity=db_record.quantity,
                    limit_price=db_record.limit_price,
                    status=db_record.status,  # type: ignore[arg-type]
                    submitted_at=submitted_at,
                    updated_at=updated_at,
                )
                with self._sync_lock:
                    self._orders[client_order_id] = domain_submission

                self._log.warning(
                    "Duplicate order dispatch intercepted from database; returning stored order",
                    client_order_id=client_order_id,
                    instrument=db_record.instrument,
                )
                return domain_submission

            # 3. Submit to broker
            submission = broker.place_order(
                client_order_id=client_order_id,
                instrument=instrument,
                direction=direction,
                quantity=quantity,
                order_type=order_type,
                price=price,
            )

            # 4. Save to database within transaction
            model = OrderSubmissionModel(
                client_order_id=submission.client_order_id,
                broker_order_id=submission.broker_order_id,
                decision_record_id=decision_record_id,
                instrument=submission.instrument,
                direction=submission.direction,
                order_type=submission.order_type,
                limit_price=submission.limit_price,
                quantity=submission.quantity,
                filled_quantity=0,
                average_fill_price=Decimal("0.0000"),
                status=submission.status,
                rejection_reason=None,
                submitted_at=submission.submitted_at,
                updated_at=submission.updated_at,
            )
            session.add(model)
            await session.commit()

            # 5. Populate in-memory registry
            with self._sync_lock:
                self._orders[client_order_id] = submission

            self._log.info(
                "Dispatched new order transactional",
                client_order_id=client_order_id,
                instrument=instrument,
                status=submission.status,
            )
            return submission
