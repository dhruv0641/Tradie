"""Broker adapter interface and protocol definitions.

Implements the abstract boundary for all broker integrations per:
- Subsystem Contracts §5
- TRD-EXEC-1 / TRD-EXEC-4
- HLD §9
- EDD §5
"""

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Literal, Protocol, runtime_checkable

import structlog

from src.domain.execution import OrderSubmission, Position

logger = structlog.get_logger(__name__)


class BrokerError(Exception):
    """Base exception for all broker adapter operations."""


class BrokerAuthenticationError(BrokerError):
    """Raised when broker credentials, session tokens, or API auth fails."""


class BrokerConnectionError(BrokerError):
    """Raised when network, heartbeat, or connection to broker is lost."""


class BrokerOrderError(BrokerError):
    """Raised when order submission, modification, or cancellation is rejected by broker."""


class BrokerOrderNotFoundError(BrokerOrderError):
    """Raised when querying or cancelling an order that does not exist on broker."""


class BrokerRateLimitError(BrokerError):
    """Raised when broker API request rate limit is exceeded."""


@runtime_checkable
class BrokerAdapter(Protocol):
    """Abstract protocol for all broker integrations (TRD-EXEC-1/4, HLD §9, EDD §5)."""

    def authenticate(self) -> bool:
        """Establish or refresh session with broker.

        Returns:
            bool: True if authentication succeeded, False otherwise.
        """
        ...

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
        """Submit an order with idempotent client_order_id.

        Args:
            client_order_id: Deterministic client order ID.
            instrument: Traded instrument symbol.
            direction: Order direction ('BUY' or 'SELL').
            quantity: Number of units to trade.
            order_type: Order type ('LIMIT' or 'MARKET').
            price: Limit price (required for LIMIT orders).

        Returns:
            OrderSubmission: Initial submission record from broker.
        """
        ...

    def cancel_order(self, client_order_id: str) -> bool:
        """Cancel a working order.

        Args:
            client_order_id: The client order ID to cancel.

        Returns:
            bool: True if cancellation request was accepted, False otherwise.
        """
        ...

    def modify_order(
        self,
        client_order_id: str,
        quantity: int | None = None,
        price: Decimal | None = None,
    ) -> OrderSubmission:
        """Modify an active working order.

        Args:
            client_order_id: The client order ID to modify.
            quantity: New quantity, or None to keep existing.
            price: New limit price, or None to keep existing.

        Returns:
            OrderSubmission: Updated submission state.
        """
        ...

    def get_positions(self) -> list[Position]:
        """Fetch broker-reported open positions for reconciliation.

        Returns:
            list[Position]: Current broker-side position snapshots.
        """
        ...

    def get_order_status(self, client_order_id: str) -> OrderSubmission:
        """Query status of a specific order.

        Args:
            client_order_id: Deterministic client order ID to inspect.

        Returns:
            OrderSubmission: Latest order status snapshot.
        """
        ...

    def heartbeat(self) -> bool:
        """Check broker session and connection liveness.

        Returns:
            bool: True if connected and responsive, False otherwise.
        """
        ...


class BaseBrokerAdapter(ABC):
    """Abstract base class providing standard logging and base broker lifecycle behavior."""

    def __init__(self, broker_name: str) -> None:
        self.broker_name = broker_name
        self._is_authenticated = False
        self._log = logger.bind(broker=broker_name)

    @property
    def is_authenticated(self) -> bool:
        """Return cached session authentication status."""
        return self._is_authenticated

    @abstractmethod
    def authenticate(self) -> bool:
        """Authenticate session with broker."""

    @abstractmethod
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
        """Submit order to broker."""

    @abstractmethod
    def cancel_order(self, client_order_id: str) -> bool:
        """Cancel working order."""

    @abstractmethod
    def modify_order(
        self,
        client_order_id: str,
        quantity: int | None = None,
        price: Decimal | None = None,
    ) -> OrderSubmission:
        """Modify working order."""

    @abstractmethod
    def get_positions(self) -> list[Position]:
        """Fetch broker positions."""

    @abstractmethod
    def get_order_status(self, client_order_id: str) -> OrderSubmission:
        """Query order status."""

    @abstractmethod
    def heartbeat(self) -> bool:
        """Check connection health."""
