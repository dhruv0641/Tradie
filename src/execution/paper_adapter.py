"""Simulated paper trading broker adapter (SOW §6.5, HLD §11, EDD §12).

Provides a realistic execution simulation environment adhering strictly to:
- BrokerAdapter protocol interface (src.execution.broker_adapter)
- Indian market statutory charges and brokerage deductions via CostModel (BTD §6)
- Virtual cash, margin, and portfolio position tracking starting from ₹10,000 (BRD BR-2)
- Immediate and quote-driven limit order matching with realistic bounded slippage
"""

import threading
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal
from uuid import uuid4

import structlog
from pydantic import BaseModel, ConfigDict, Field

from src.backtesting.cost_model import CostModel, CostModelConfig
from src.domain.execution import OrderFill, OrderSubmission, Position
from src.execution.broker_adapter import (
    BaseBrokerAdapter,
    BrokerAuthenticationError,
    BrokerOrderError,
    BrokerOrderNotFoundError,
)

logger = structlog.get_logger(__name__)


class PaperBrokerConfig(BaseModel):
    """Configuration for simulated paper trading broker adapter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    initial_cash: Decimal = Field(
        default=Decimal("10000.00"),
        gt=Decimal("0"),
        description="Initial virtual cash balance in INR (BRD BR-2)",
    )
    fill_mode: Literal["IMMEDIATE", "QUOTE_DRIVEN"] = Field(
        default="IMMEDIATE",
        description="Execution mode: IMMEDIATE against quotes, or QUOTE_DRIVEN awaiting ticks",
    )
    slippage_bps: Decimal = Field(
        default=Decimal("2.0"),
        ge=Decimal("0"),
        description="Execution slippage in basis points (1 bp = 0.01%)",
    )
    product_type: Literal["INTRADAY", "DELIVERY"] = Field(
        default="INTRADAY",
        description="Tax treatment and statutory schedule (BTD §6)",
    )
    cost_model_config: CostModelConfig | None = Field(
        default=None,
        description="Optional custom configuration for CostModel statutory charges",
    )


class PaperBrokerAdapter(BaseBrokerAdapter):
    """Simulated paper broker adapter fulfilling BrokerAdapter protocol (HLD §11, EDD §12).

    Simulates realistic order execution, deducts statutory Indian taxes and brokerage,
    and maintains virtual account cash, positions, and order book state.
    """

    def __init__(
        self,
        config: PaperBrokerConfig | None = None,
        broker_name: str = "PaperBroker",
    ) -> None:
        super().__init__(broker_name=broker_name)
        self.config = config or PaperBrokerConfig()
        self._cost_model = CostModel(config=self.config.cost_model_config)

        # Internal state guarded by lock
        self._lock = threading.Lock()
        self._cash = self.config.initial_cash
        self._realized_pnl = Decimal("0.00")
        self._total_costs = Decimal("0.00")
        self._orders: dict[str, OrderSubmission] = {}
        self._positions: dict[str, Position] = {}
        self._fills: list[OrderFill] = []
        self._market_prices: dict[str, Decimal] = {}
        self._is_alive = True
        self._is_authenticated = True

    @property
    def cash(self) -> Decimal:
        """Return current virtual cash balance in INR."""
        with self._lock:
            return self._cash

    @property
    def realized_pnl(self) -> Decimal:
        """Return cumulative realized profit or loss in INR."""
        with self._lock:
            return self._realized_pnl

    @property
    def total_costs(self) -> Decimal:
        """Return total statutory charges and brokerage paid in INR."""
        with self._lock:
            return self._total_costs

    @property
    def equity(self) -> Decimal:
        """Return mark-to-market portfolio equity (cash + position market value)."""
        with self._lock:
            portfolio_val = Decimal("0.00")
            for pos in self._positions.values():
                mkt_price = self._market_prices.get(pos.instrument, pos.average_entry_price)
                portfolio_val += Decimal(pos.quantity) * mkt_price
            return (self._cash + portfolio_val).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def fills(self) -> list[OrderFill]:
        """Return immutable audit log copy of executed fills."""
        with self._lock:
            return list(self._fills)

    def set_connection_alive(self, alive: bool) -> None:
        """Simulate network link health for testing ConnectionMonitor."""
        with self._lock:
            self._is_alive = alive
            self._log.info("Simulated connection liveness toggled", alive=alive)

    def set_market_price(self, instrument: str, price: Decimal) -> None:
        """Seed or manually update instrument quote price."""
        if price <= Decimal("0"):
            msg = f"Price must be positive, got {price}"
            raise ValueError(msg)
        with self._lock:
            self._market_prices[instrument] = price

    def authenticate(self) -> bool:
        """Establish or refresh session with paper broker."""
        with self._lock:
            self._is_authenticated = True
            self._log.info("Paper broker authenticated successfully")
            return True

    def heartbeat(self) -> bool:
        """Check paper broker session and connection liveness."""
        with self._lock:
            return self._is_authenticated and self._is_alive

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
        """Submit order to paper broker with idempotent client_order_id."""
        with self._lock:
            if not self._is_authenticated:
                msg = "Paper broker adapter is not authenticated"
                raise BrokerAuthenticationError(msg)

            if not self._is_alive:
                msg = "Paper broker connection is offline"
                raise BrokerOrderError(msg)

            if client_order_id in self._orders:
                existing = self._orders[client_order_id]
                self._log.warning("Duplicate client_order_id", client_order_id=client_order_id)
                return existing

            if quantity <= 0:
                msg = f"Order quantity must be positive, got {quantity}"
                raise BrokerOrderError(msg)

            if order_type == "LIMIT" and (price is None or price <= Decimal("0")):
                msg = f"LIMIT order requires positive limit price, got {price}"
                raise BrokerOrderError(msg)

            now = datetime.now(UTC)
            broker_order_id = f"PAPER-{uuid4().hex[:12].upper()}"

            # Determine base reference price
            ref_price = price
            if ref_price is None:
                ref_price = self._market_prices.get(instrument)
                if ref_price is None and self.config.fill_mode == "IMMEDIATE":
                    msg = f"No market price known for MARKET order on {instrument}"
                    raise BrokerOrderError(msg)

            # Evaluate fill execution mode
            should_fill_now = self._should_fill_on_placement(
                order_type=order_type,
                direction=direction,
                ref_price=ref_price,
                instrument=instrument,
            )

            if should_fill_now:
                if ref_price is None:
                    msg = f"No execution price available for {instrument}"
                    raise BrokerOrderError(msg)
                fill_price = self._apply_slippage(ref_price, direction)
                cost_breakdown = self._cost_model.calculate_leg(
                    price=fill_price,
                    quantity=quantity,
                    side=direction,
                    product_type=self.config.product_type,
                )

                # Validate cash sufficiency for buy orders
                if direction == "BUY":
                    total_cost = (fill_price * Decimal(quantity)) + cost_breakdown.total_cost
                    if self._cash < total_cost:
                        msg = (
                            f"Insufficient virtual cash: required ₹{total_cost:.2f}, "
                            f"available ₹{self._cash:.2f}"
                        )
                        raise BrokerOrderError(msg)

                # Execute fill and update portfolio state
                submission = OrderSubmission(
                    client_order_id=client_order_id,
                    broker_order_id=broker_order_id,
                    instrument=instrument,
                    direction=direction,
                    order_type=order_type,
                    quantity=quantity,
                    limit_price=price,
                    status="FILLED",
                    submitted_at=now,
                    updated_at=now,
                )
                self._orders[client_order_id] = submission
                self._record_fill_locked(
                    submission=submission,
                    fill_price=fill_price,
                    commission=cost_breakdown.total_cost,
                    timestamp=now,
                )
                return submission

            # Quote-driven mode: order remains working (SUBMITTED)
            submission = OrderSubmission(
                client_order_id=client_order_id,
                broker_order_id=broker_order_id,
                instrument=instrument,
                direction=direction,
                order_type=order_type,
                quantity=quantity,
                limit_price=price,
                status="SUBMITTED",
                submitted_at=now,
                updated_at=now,
            )
            self._orders[client_order_id] = submission
            self._log.info(
                "Paper limit order submitted to working book",
                client_order_id=client_order_id,
                instrument=instrument,
                limit_price=price,
            )
            return submission

    def cancel_order(self, client_order_id: str) -> bool:
        """Cancel a working paper order."""
        with self._lock:
            if client_order_id not in self._orders:
                return False

            order = self._orders[client_order_id]
            if order.status != "SUBMITTED":
                return False

            now = datetime.now(UTC)
            cancelled = OrderSubmission(
                client_order_id=order.client_order_id,
                broker_order_id=order.broker_order_id,
                instrument=order.instrument,
                direction=order.direction,
                order_type=order.order_type,
                quantity=order.quantity,
                limit_price=order.limit_price,
                status="CANCELLED",
                submitted_at=order.submitted_at,
                updated_at=now,
            )
            self._orders[client_order_id] = cancelled
            self._log.info("Paper order cancelled", client_order_id=client_order_id)
            return True

    def modify_order(
        self,
        client_order_id: str,
        quantity: int | None = None,
        price: Decimal | None = None,
    ) -> OrderSubmission:
        """Modify limit price or quantity of a working paper order."""
        with self._lock:
            if client_order_id not in self._orders:
                msg = f"Order '{client_order_id}' not found on paper broker"
                raise BrokerOrderNotFoundError(msg)

            order = self._orders[client_order_id]
            if order.status != "SUBMITTED":
                msg = f"Cannot modify paper order '{client_order_id}' in state '{order.status}'"
                raise BrokerOrderError(msg)

            new_qty = quantity if quantity is not None else order.quantity
            new_price = price if price is not None else order.limit_price

            if new_qty <= 0:
                msg = f"Modified quantity must be positive, got {new_qty}"
                raise BrokerOrderError(msg)

            now = datetime.now(UTC)
            modified = OrderSubmission(
                client_order_id=order.client_order_id,
                broker_order_id=order.broker_order_id,
                instrument=order.instrument,
                direction=order.direction,
                order_type=order.order_type,
                quantity=new_qty,
                limit_price=new_price,
                status="SUBMITTED",
                submitted_at=order.submitted_at,
                updated_at=now,
            )
            self._orders[client_order_id] = modified
            self._log.info(
                "Paper order modified",
                client_order_id=client_order_id,
                quantity=new_qty,
                price=new_price,
            )
            return modified

    def get_positions(self) -> list[Position]:
        """Fetch current paper position snapshots for reconciliation."""
        with self._lock:
            return list(self._positions.values())

    def get_order_status(self, client_order_id: str) -> OrderSubmission:
        """Query latest status snapshot of a paper order."""
        with self._lock:
            if client_order_id not in self._orders:
                msg = f"Order '{client_order_id}' not found on paper broker"
                raise BrokerOrderNotFoundError(msg)
            return self._orders[client_order_id]

    def on_tick(
        self,
        instrument: str,
        price: Decimal,
        timestamp: datetime | None = None,
    ) -> list[OrderFill]:
        """Process incoming market tick, update mark-to-market prices, and match working orders.

        Args:
            instrument: Traded symbol.
            price: Latest traded or quote price.
            timestamp: Optional tick timestamp in UTC.

        Returns:
            list[OrderFill]: Executed order fills triggered by this price update.
        """
        if price <= Decimal("0"):
            msg = f"Tick price must be positive, got {price}"
            raise ValueError(msg)

        now = timestamp or datetime.now(UTC)
        executed_fills: list[OrderFill] = []

        with self._lock:
            self._market_prices[instrument] = price

            # Update unrealized mark-to-market P&L on current position if held
            if instrument in self._positions:
                curr = self._positions[instrument]
                unrealized = self._calculate_unrealized_pnl(
                    curr.quantity, curr.average_entry_price, price
                )
                peak_pnl = (
                    max(curr.peak_unrealized_pnl, unrealized)
                    if curr.quantity != 0
                    else Decimal("0.00")
                )
                self._positions[instrument] = Position(
                    instrument=instrument,
                    quantity=curr.quantity,
                    average_entry_price=curr.average_entry_price,
                    current_market_price=price,
                    unrealized_pnl=unrealized,
                    realized_pnl=curr.realized_pnl,
                    peak_unrealized_pnl=peak_pnl,
                    updated_at=now,
                )

            # Inspect working orders for match
            working_orders = [
                o
                for o in self._orders.values()
                if o.instrument == instrument and o.status == "SUBMITTED"
            ]

            for order in working_orders:
                should_fill = order.order_type == "MARKET" or (
                    order.order_type == "LIMIT"
                    and order.limit_price is not None
                    and (
                        (order.direction == "BUY" and price <= order.limit_price)
                        or (order.direction == "SELL" and price >= order.limit_price)
                    )
                )

                if should_fill:
                    fill_price = self._apply_slippage(price, order.direction)
                    cost_breakdown = self._cost_model.calculate_leg(
                        price=fill_price,
                        quantity=order.quantity,
                        side=order.direction,
                        product_type=self.config.product_type,
                    )

                    # Verify cash for buy fills
                    if order.direction == "BUY":
                        req = (fill_price * Decimal(order.quantity)) + cost_breakdown.total_cost
                        if self._cash < req:
                            self._log.warning(
                                "Skipping fill: insufficient virtual cash",
                                client_order_id=order.client_order_id,
                                required=req,
                                cash=self._cash,
                            )
                            continue

                    updated_order = OrderSubmission(
                        client_order_id=order.client_order_id,
                        broker_order_id=order.broker_order_id,
                        instrument=order.instrument,
                        direction=order.direction,
                        order_type=order.order_type,
                        quantity=order.quantity,
                        limit_price=order.limit_price,
                        status="FILLED",
                        submitted_at=order.submitted_at,
                        updated_at=now,
                    )
                    self._orders[order.client_order_id] = updated_order
                    fill = self._record_fill_locked(
                        submission=updated_order,
                        fill_price=fill_price,
                        commission=cost_breakdown.total_cost,
                        timestamp=now,
                    )
                    executed_fills.append(fill)

        return executed_fills

    def _apply_slippage(self, price: Decimal, direction: Literal["BUY", "SELL"]) -> Decimal:
        """Apply configured basis-point execution slippage."""
        if self.config.slippage_bps == Decimal("0"):
            return price

        slippage_rate = self.config.slippage_bps / Decimal("10000")
        if direction == "BUY":
            raw_price = price * (Decimal("1") + slippage_rate)
        else:
            raw_price = price * (Decimal("1") - slippage_rate)

        return raw_price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def _should_fill_on_placement(
        self,
        *,
        order_type: Literal["LIMIT", "MARKET"],
        direction: Literal["BUY", "SELL"],
        ref_price: Decimal | None,
        instrument: str,
    ) -> bool:
        """Evaluate if an incoming order meets immediate execution conditions."""
        if self.config.fill_mode == "IMMEDIATE":
            return True
        if order_type == "MARKET":
            return ref_price is not None
        if order_type == "LIMIT":
            curr = self._market_prices.get(instrument)
            if curr is not None and ref_price is not None:
                return (direction == "BUY" and curr <= ref_price) or (
                    direction == "SELL" and curr >= ref_price
                )
        return False

    def _calculate_unrealized_pnl(
        self,
        quantity: int,
        entry_price: Decimal,
        market_price: Decimal,
    ) -> Decimal:
        """Calculate mark-to-market unrealized P&L."""
        if quantity == 0:
            return Decimal("0.00")
        if quantity > 0:
            raw = (market_price - entry_price) * Decimal(quantity)
        else:
            raw = (entry_price - market_price) * Decimal(abs(quantity))
        return raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def _increase_position(
        self,
        *,
        curr: Position,
        direction: Literal["BUY", "SELL"],
        quantity: int,
        fill_price: Decimal,
        gross_value: Decimal,
        timestamp: datetime,
    ) -> Position:
        """Increase existing long or short position and calculate blended entry price."""
        old_qty = curr.quantity
        signed_qty = quantity if direction == "BUY" else -quantity
        new_qty = old_qty + signed_qty
        total_cost = (Decimal(abs(old_qty)) * curr.average_entry_price) + gross_value
        new_entry = (total_cost / Decimal(abs(new_qty))).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        unrealized = self._calculate_unrealized_pnl(new_qty, new_entry, fill_price)
        return Position(
            instrument=curr.instrument,
            quantity=new_qty,
            average_entry_price=new_entry,
            current_market_price=fill_price,
            unrealized_pnl=unrealized,
            realized_pnl=curr.realized_pnl,
            peak_unrealized_pnl=max(curr.peak_unrealized_pnl, unrealized),
            updated_at=timestamp,
        )

    def _reduce_or_flip_position(
        self,
        *,
        curr: Position,
        quantity: int,
        fill_price: Decimal,
        timestamp: datetime,
    ) -> Position:
        """Reduce, close, or flip an existing position and realize P&L."""
        old_qty = curr.quantity
        abs_old = abs(old_qty)
        instrument = curr.instrument

        if quantity <= abs_old:
            # Partial or exact close
            if old_qty > 0:
                trade_realized = (fill_price - curr.average_entry_price) * Decimal(quantity)
            else:
                trade_realized = (curr.average_entry_price - fill_price) * Decimal(quantity)

            new_qty = old_qty - quantity if old_qty > 0 else old_qty + quantity
            new_entry = curr.average_entry_price if new_qty != 0 else Decimal("0.00")
            new_realized_pnl = curr.realized_pnl + trade_realized
            self._realized_pnl += trade_realized
            unrealized = self._calculate_unrealized_pnl(new_qty, new_entry, fill_price)
            peak_pnl = (
                max(curr.peak_unrealized_pnl, unrealized) if new_qty != 0 else Decimal("0.00")
            )

            return Position(
                instrument=instrument,
                quantity=new_qty,
                average_entry_price=new_entry,
                current_market_price=fill_price,
                unrealized_pnl=unrealized,
                realized_pnl=new_realized_pnl,
                peak_unrealized_pnl=peak_pnl,
                updated_at=timestamp,
            )

        # Position flip (e.g. Long 10 -> Short 5 via SELL 15)
        close_qty = abs_old
        reverse_qty = quantity - close_qty
        if old_qty > 0:
            trade_realized = (fill_price - curr.average_entry_price) * Decimal(close_qty)
        else:
            trade_realized = (curr.average_entry_price - fill_price) * Decimal(close_qty)

        self._realized_pnl += trade_realized
        new_realized_pnl = curr.realized_pnl + trade_realized
        new_qty = -reverse_qty if old_qty > 0 else reverse_qty
        unrealized = Decimal("0.00")

        return Position(
            instrument=instrument,
            quantity=new_qty,
            average_entry_price=fill_price,
            current_market_price=fill_price,
            unrealized_pnl=unrealized,
            realized_pnl=new_realized_pnl,
            peak_unrealized_pnl=Decimal("0.00"),
            updated_at=timestamp,
        )

    def _record_fill_locked(
        self,
        *,
        submission: OrderSubmission,
        fill_price: Decimal,
        commission: Decimal,
        timestamp: datetime,
    ) -> OrderFill:
        """Record fill execution, update cash, and adjust position under lock."""
        instrument = submission.instrument
        direction = submission.direction
        quantity = submission.quantity
        gross_value = fill_price * Decimal(quantity)

        # Update cash and costs
        self._total_costs += commission
        if direction == "BUY":
            self._cash -= gross_value + commission
        else:
            self._cash += gross_value - commission

        # Update position
        curr = self._positions.get(instrument)
        if curr is None or curr.quantity == 0:
            new_qty = quantity if direction == "BUY" else -quantity
            unrealized = Decimal("0.00")
            prior_realized = curr.realized_pnl if curr else Decimal("0.00")
            updated_pos = Position(
                instrument=instrument,
                quantity=new_qty,
                average_entry_price=fill_price,
                current_market_price=fill_price,
                unrealized_pnl=unrealized,
                realized_pnl=prior_realized,
                peak_unrealized_pnl=Decimal("0.00"),
                updated_at=timestamp,
            )
        elif (curr.quantity > 0 and direction == "BUY") or (
            curr.quantity < 0 and direction == "SELL"
        ):
            updated_pos = self._increase_position(
                curr=curr,
                direction=direction,
                quantity=quantity,
                fill_price=fill_price,
                gross_value=gross_value,
                timestamp=timestamp,
            )
        else:
            updated_pos = self._reduce_or_flip_position(
                curr=curr,
                quantity=quantity,
                fill_price=fill_price,
                timestamp=timestamp,
            )

        self._positions[instrument] = updated_pos

        fill = OrderFill(
            fill_id=f"FILL-{uuid4().hex[:12].upper()}",
            client_order_id=submission.client_order_id,
            instrument=instrument,
            direction=direction,
            quantity=quantity,
            price=fill_price,
            commission=commission,
            timestamp=timestamp,
        )
        self._fills.append(fill)

        self._log.info(
            "Paper fill executed",
            client_order_id=submission.client_order_id,
            instrument=instrument,
            direction=direction,
            quantity=quantity,
            fill_price=fill_price,
            commission=commission,
            cash_remaining=self._cash,
        )
        return fill
