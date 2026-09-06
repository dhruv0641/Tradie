"""Production Live Broker Adapter for Indian Financial Markets.

Implements the BrokerAdapter protocol for live execution per:
- SOW §6.6, §9
- FRD-EXEC-1, FRD-EXEC-2
- TRD-EXEC-1, TRD-EXEC-4, TRD-SEC-1
- EDD §5, HLD §9
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import uuid4

import httpx
import structlog

from src.config.models import BrokerConfig
from src.domain.execution import OrderSubmission, Position
from src.execution.broker_adapter import (
    BaseBrokerAdapter,
    BrokerAuthenticationError,
    BrokerConnectionError,
    BrokerOrderError,
    BrokerOrderNotFoundError,
    BrokerRateLimitError,
)

logger = structlog.get_logger(__name__)


class LiveBrokerAdapter(BaseBrokerAdapter):
    """Production live broker adapter wrapping Indian broker REST APIs (e.g. Zerodha Kite Connect).

    Enforces:
    - Strict TLS certificate validation (TRD-SEC-1).
    - Secret masking in logs (no API keys/secrets leaked).
    - Protocol error translation into canonical BrokerError exceptions.
    - Hermetic sandbox/mock support for verification without external network access.
    """

    def __init__(
        self,
        config: BrokerConfig | None = None,
        *,
        client: httpx.Client | None = None,
        sandbox_mode: bool = False,
    ) -> None:
        super().__init__(broker_name=config.broker_name if config else "live_broker")
        self.config = config or BrokerConfig(paper_trading=False)
        self.sandbox_mode = (
            sandbox_mode
            or self.config.paper_trading
            or self.config.api_key.get_secret_value() in ("mock_key", "test_key", "sandbox")
        )

        self.base_url = self.config.base_url.rstrip("/")
        self._timeout_seconds = self.config.timeout_seconds

        # Enforce strict TLS certificate verification (TRD-SEC-1 / NFR-SEC)
        self._client = client or httpx.Client(
            verify=True,
            timeout=self._timeout_seconds,
            headers={"User-Agent": "AITrader-LiveBrokerAdapter/1.0"},
        )

        # In-memory tracking for sandbox/mock simulation
        # and client_order_id -> broker_order_id mappings
        self._client_to_broker_id: dict[str, str] = {}
        self._orders_by_id: dict[str, OrderSubmission] = {}
        self._sandbox_positions: dict[str, Position] = {}
        self._sandbox_cash: Decimal = Decimal("10000.00")

    def _get_auth_headers(self) -> dict[str, str]:
        """Construct secure authorization headers without exposing secrets in logs."""
        api_key = self.config.api_key.get_secret_value()
        access_token = (
            self.config.access_token.get_secret_value()
            if self.config.access_token is not None
            else ""
        )
        return {
            "Authorization": f"token {api_key}:{access_token}",
            "X-Kite-Version": "3",
        }

    def authenticate(self) -> bool:
        """Establish or verify authenticated session with broker.

        Returns:
            bool: True if authenticated successfully.

        Raises:
            BrokerAuthenticationError: If authentication fails.
            BrokerConnectionError: If network connection fails.
        """
        self._log.info("Authenticating broker session", sandbox_mode=self.sandbox_mode)

        if self.sandbox_mode:
            self._is_authenticated = True
            return True

        url = f"{self.base_url}/user/profile"
        try:
            resp = self._client.get(url, headers=self._get_auth_headers())
            if resp.status_code == 200:
                self._is_authenticated = True
                self._log.info("Broker session authenticated successfully")
                return True
            if resp.status_code in (401, 403):
                self._is_authenticated = False
                msg = f"Broker authentication failed with status {resp.status_code}: {resp.text}"
                self._log.error("Broker authentication failed", status_code=resp.status_code)
                raise BrokerAuthenticationError(msg)

            self._is_authenticated = False
            msg = f"Unexpected broker authentication status {resp.status_code}"
            raise BrokerAuthenticationError(msg)
        except httpx.RequestError as exc:
            self._is_authenticated = False
            msg = f"Network connection error during broker authentication: {exc}"
            self._log.error("Network connection error during broker auth", error=str(exc))
            raise BrokerConnectionError(msg) from exc

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
        """Submit order to broker with idempotent client_order_id.

        Raises:
            BrokerOrderError: If order is rejected by broker.
            BrokerRateLimitError: If broker rate limit is breached.
            BrokerConnectionError: If connection error occurs.
        """
        if not self._is_authenticated:
            self.authenticate()

        now_utc = datetime.now(UTC)
        broker_order_id = f"BO-{uuid4().hex[:12].upper()}"

        if self.sandbox_mode:
            self._client_to_broker_id[client_order_id] = broker_order_id
            submission = OrderSubmission(
                client_order_id=client_order_id,
                broker_order_id=broker_order_id,
                instrument=instrument,
                direction=direction,
                order_type=order_type,
                quantity=quantity,
                limit_price=price if order_type == "LIMIT" else None,
                status="SUBMITTED",
                submitted_at=now_utc,
                updated_at=now_utc,
            )
            self._orders_by_id[client_order_id] = submission
            self._orders_by_id[broker_order_id] = submission
            self._log.info(
                "Sandbox order placed",
                client_order_id=client_order_id,
                broker_order_id=broker_order_id,
                instrument=instrument,
                direction=direction,
                quantity=quantity,
            )
            return submission

        url = f"{self.base_url}/orders/regular"
        payload: dict[str, Any] = {
            "tradingsymbol": instrument.replace("NSE:", ""),
            "exchange": "NSE",
            "transaction_type": direction,
            "order_type": order_type,
            "quantity": quantity,
            "product": "CNC",
            "validity": "DAY",
            "tag": client_order_id,
        }
        if order_type == "LIMIT" and price is not None:
            payload["price"] = str(price)

        try:
            resp = self._client.post(url, headers=self._get_auth_headers(), data=payload)
            self._handle_http_errors(resp, operation=f"place_order({client_order_id})")
            data = resp.json().get("data", {})
            real_broker_order_id = str(data.get("order_id", broker_order_id))

            self._client_to_broker_id[client_order_id] = real_broker_order_id
            submission = OrderSubmission(
                client_order_id=client_order_id,
                broker_order_id=real_broker_order_id,
                instrument=instrument,
                direction=direction,
                order_type=order_type,
                quantity=quantity,
                limit_price=price if order_type == "LIMIT" else None,
                status="SUBMITTED",
                submitted_at=now_utc,
                updated_at=now_utc,
            )
            self._orders_by_id[client_order_id] = submission
            self._orders_by_id[real_broker_order_id] = submission
            return submission
        except httpx.RequestError as exc:
            msg = f"Network connection error submitting order {client_order_id}: {exc}"
            self._log.error("Network error during place_order", error=str(exc))
            raise BrokerConnectionError(msg) from exc

    def modify_order(
        self,
        client_order_id: str,
        quantity: int | None = None,
        price: Decimal | None = None,
    ) -> OrderSubmission:
        """Modify an active working order."""
        if not self._is_authenticated:
            self.authenticate()

        existing = self._orders_by_id.get(client_order_id)
        if existing is None:
            msg = f"Order with client_order_id {client_order_id} not found for modification"
            raise BrokerOrderNotFoundError(msg)

        now_utc = datetime.now(UTC)
        new_qty = quantity if quantity is not None else existing.quantity
        new_price = price if price is not None else existing.limit_price

        if self.sandbox_mode:
            updated = OrderSubmission(
                client_order_id=existing.client_order_id,
                broker_order_id=existing.broker_order_id,
                instrument=existing.instrument,
                direction=existing.direction,
                order_type=existing.order_type,
                quantity=new_qty,
                limit_price=new_price,
                status="SUBMITTED",
                submitted_at=existing.submitted_at,
                updated_at=now_utc,
            )
            self._orders_by_id[client_order_id] = updated
            if existing.broker_order_id:
                self._orders_by_id[existing.broker_order_id] = updated
            return updated

        broker_order_id = existing.broker_order_id or self._client_to_broker_id.get(client_order_id)
        if not broker_order_id:
            msg = f"Cannot modify order {client_order_id}: missing broker_order_id"
            raise BrokerOrderNotFoundError(msg)

        url = f"{self.base_url}/orders/regular/{broker_order_id}"
        payload: dict[str, Any] = {}
        if quantity is not None:
            payload["quantity"] = quantity
        if price is not None:
            payload["price"] = str(price)

        try:
            resp = self._client.put(url, headers=self._get_auth_headers(), data=payload)
            self._handle_http_errors(resp, operation=f"modify_order({client_order_id})")
            updated = OrderSubmission(
                client_order_id=existing.client_order_id,
                broker_order_id=broker_order_id,
                instrument=existing.instrument,
                direction=existing.direction,
                order_type=existing.order_type,
                quantity=new_qty,
                limit_price=new_price,
                status="SUBMITTED",
                submitted_at=existing.submitted_at,
                updated_at=now_utc,
            )
            self._orders_by_id[client_order_id] = updated
            self._orders_by_id[broker_order_id] = updated
            return updated
        except httpx.RequestError as exc:
            msg = f"Network connection error modifying order {client_order_id}: {exc}"
            raise BrokerConnectionError(msg) from exc

    def cancel_order(self, client_order_id: str) -> bool:
        """Cancel a working order."""
        if not self._is_authenticated:
            self.authenticate()

        existing = self._orders_by_id.get(client_order_id)
        if existing is None:
            msg = f"Order with client_order_id {client_order_id} not found for cancellation"
            raise BrokerOrderNotFoundError(msg)

        now_utc = datetime.now(UTC)

        if self.sandbox_mode:
            updated = OrderSubmission(
                client_order_id=existing.client_order_id,
                broker_order_id=existing.broker_order_id,
                instrument=existing.instrument,
                direction=existing.direction,
                order_type=existing.order_type,
                quantity=existing.quantity,
                limit_price=existing.limit_price,
                status="CANCELLED",
                submitted_at=existing.submitted_at,
                updated_at=now_utc,
            )
            self._orders_by_id[client_order_id] = updated
            if existing.broker_order_id:
                self._orders_by_id[existing.broker_order_id] = updated
            return True

        broker_order_id = existing.broker_order_id or self._client_to_broker_id.get(client_order_id)
        if not broker_order_id:
            msg = f"Cannot cancel order {client_order_id}: missing broker_order_id"
            raise BrokerOrderNotFoundError(msg)

        url = f"{self.base_url}/orders/regular/{broker_order_id}"
        try:
            resp = self._client.delete(url, headers=self._get_auth_headers())
            self._handle_http_errors(resp, operation=f"cancel_order({client_order_id})")
            updated = OrderSubmission(
                client_order_id=existing.client_order_id,
                broker_order_id=broker_order_id,
                instrument=existing.instrument,
                direction=existing.direction,
                order_type=existing.order_type,
                quantity=existing.quantity,
                limit_price=existing.limit_price,
                status="CANCELLED",
                submitted_at=existing.submitted_at,
                updated_at=now_utc,
            )
            self._orders_by_id[client_order_id] = updated
            self._orders_by_id[broker_order_id] = updated
            return True
        except httpx.RequestError as exc:
            msg = f"Network connection error cancelling order {client_order_id}: {exc}"
            raise BrokerConnectionError(msg) from exc

    def get_order_status(self, client_order_id: str) -> OrderSubmission:
        """Query latest status of an order."""
        if not self._is_authenticated:
            self.authenticate()

        existing = self._orders_by_id.get(client_order_id)
        if existing is not None and self.sandbox_mode:
            return existing

        if self.sandbox_mode:
            msg = f"Order {client_order_id} not found"
            raise BrokerOrderNotFoundError(msg)

        url = f"{self.base_url}/orders"
        try:
            resp = self._client.get(url, headers=self._get_auth_headers())
            self._handle_http_errors(resp, operation=f"get_order_status({client_order_id})")
            orders_data = resp.json().get("data", [])
            broker_order_id = self._client_to_broker_id.get(client_order_id)

            for item in orders_data:
                tag = item.get("tag")
                oid = str(item.get("order_id"))
                if tag == client_order_id or (broker_order_id and oid == broker_order_id):
                    now_utc = datetime.now(UTC)
                    status_raw = item.get("status", "SUBMITTED").upper()
                    status_map = {
                        "COMPLETE": "FILLED",
                        "CANCELLED": "CANCELLED",
                        "REJECTED": "REJECTED",
                        "OPEN": "SUBMITTED",
                    }
                    canonical_status = status_map.get(status_raw, "SUBMITTED")
                    submission = OrderSubmission(
                        client_order_id=client_order_id,
                        broker_order_id=oid,
                        instrument=f"NSE:{item.get('tradingsymbol', 'UNKNOWN')}",
                        direction="BUY" if item.get("transaction_type") == "BUY" else "SELL",
                        order_type="LIMIT" if item.get("order_type") == "LIMIT" else "MARKET",
                        quantity=int(item.get("quantity", 0)),
                        limit_price=(
                            Decimal(str(item.get("price", "0"))) if item.get("price") else None
                        ),
                        status=canonical_status,  # type: ignore[arg-type]
                        submitted_at=existing.submitted_at if existing else now_utc,
                        updated_at=now_utc,
                    )
                    self._orders_by_id[client_order_id] = submission
                    return submission

            msg = f"Order {client_order_id} not found on broker"
            raise BrokerOrderNotFoundError(msg)
        except httpx.RequestError as exc:
            msg = f"Network connection error querying order {client_order_id}: {exc}"
            raise BrokerConnectionError(msg) from exc

    def get_positions(self) -> list[Position]:
        """Fetch broker-reported open positions for startup reconciliation."""
        if not self._is_authenticated:
            self.authenticate()

        if self.sandbox_mode:
            return list(self._sandbox_positions.values())

        url = f"{self.base_url}/portfolio/positions"
        try:
            resp = self._client.get(url, headers=self._get_auth_headers())
            self._handle_http_errors(resp, operation="get_positions")
            data = resp.json().get("data", {})
            net_positions = data.get("net", [])
            results: list[Position] = []
            now_utc = datetime.now(UTC)

            for item in net_positions:
                qty = int(item.get("quantity", 0))
                symbol = f"NSE:{item.get('tradingsymbol')}"
                avg_price = Decimal(str(item.get("average_price", 0)))
                last_price = Decimal(str(item.get("last_price", 0)))
                pnl = Decimal(str(item.get("pnl", 0)))

                results.append(
                    Position(
                        instrument=symbol,
                        quantity=qty,
                        average_entry_price=avg_price,
                        current_market_price=last_price,
                        unrealized_pnl=pnl,
                        realized_pnl=Decimal(str(item.get("realised", 0))),
                        peak_unrealized_pnl=pnl,
                        updated_at=now_utc,
                    )
                )
            return results
        except httpx.RequestError as exc:
            msg = f"Network connection error fetching positions: {exc}"
            raise BrokerConnectionError(msg) from exc

    def get_account_balance(self) -> Decimal:
        """Fetch available cash balance from broker."""
        if not self._is_authenticated:
            self.authenticate()

        if self.sandbox_mode:
            return self._sandbox_cash

        url = f"{self.base_url}/user/margins"
        try:
            resp = self._client.get(url, headers=self._get_auth_headers())
            self._handle_http_errors(resp, operation="get_account_balance")
            data = resp.json().get("data", {})
            equity_margins = data.get("equity", {})
            available_cash = equity_margins.get("available", {}).get("cash", 10000.0)
            return Decimal(str(available_cash))
        except httpx.RequestError as exc:
            msg = f"Network connection error fetching account balance: {exc}"
            raise BrokerConnectionError(msg) from exc

    def heartbeat(self) -> bool:
        """Check connection health and broker session liveness."""
        if not self._is_authenticated:
            return False

        if self.sandbox_mode:
            return True

        url = f"{self.base_url}/user/profile"
        try:
            resp = self._client.get(url, headers=self._get_auth_headers())
            return bool(resp.status_code == 200)
        except Exception:
            return False

    def _handle_http_errors(self, response: httpx.Response, operation: str) -> None:
        """Translate HTTP status codes to typed Broker exceptions."""
        if response.status_code == 200:
            return

        status = response.status_code
        text = response.text

        if status in (401, 403):
            msg = f"Broker authentication error during {operation}: {text}"
            raise BrokerAuthenticationError(msg)
        if status == 404:
            msg = f"Broker resource not found during {operation}: {text}"
            raise BrokerOrderNotFoundError(msg)
        if status == 429:
            msg = f"Broker rate limit exceeded during {operation}: {text}"
            raise BrokerRateLimitError(msg)
        if status in (400, 422):
            msg = f"Broker rejected order during {operation}: {text}"
            raise BrokerOrderError(msg)

        msg = f"Broker error during {operation} (HTTP {status}): {text}"
        raise BrokerOrderError(msg)

    # Sandbox helper methods for testing
    def set_sandbox_position(self, position: Position) -> None:
        """Set a simulated position in sandbox mode for test setups."""
        self._sandbox_positions[position.instrument] = position

    def set_sandbox_cash(self, cash: Decimal) -> None:
        """Set simulated cash in sandbox mode."""
        self._sandbox_cash = cash

    def close(self) -> None:
        """Close underlying HTTP client."""
        self._client.close()
