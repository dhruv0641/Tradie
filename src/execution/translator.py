"""Order parameter translator and slippage guard.

Translates Supervisor decisions and candidate trades into concrete broker orders per:
- FRD-EXEC-2 (order parameter translation)
- FRD-EXEC-9 (correctness-over-speed priority and bounded slippage)
- EDD §6.2 (limit-order-with-bounded-slippage default and tick rounding)
"""

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.domain.decision import Decision
from src.domain.risk import CandidateTrade
from src.execution.idempotency import generate_client_order_id


class OrderTranslationError(Exception):
    """Raised when an order translation fails validation or violates execution constraints."""


class OrderTranslationConfig(BaseModel):
    """Configuration for order parameter translation and slippage bounds."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    default_order_type: Literal["LIMIT", "MARKET"] = Field(
        default="LIMIT", description="Default order type (LIMIT per EDD §6.2)"
    )
    max_slippage_pct: Decimal = Field(
        default=Decimal("0.002"),
        ge=Decimal("0"),
        description="Max allowable slippage percentage from quote (default: 0.20%)",
    )
    allow_market_orders: bool = Field(
        default=False,
        description="Whether MARKET orders are permitted. If False, MARKET requests are rejected",
    )
    default_tick_size: Decimal = Field(
        default=Decimal("0.05"),
        gt=Decimal("0"),
        description="Default exchange price tick size (e.g. ₹0.05 for NSE Equities)",
    )
    instrument_tick_sizes: dict[str, Decimal] = Field(
        default_factory=dict, description="Override tick sizes keyed by instrument symbol"
    )
    instrument_lot_sizes: dict[str, int] = Field(
        default_factory=dict, description="Minimum lot sizes keyed by instrument symbol"
    )
    symbol_mappings: dict[str, str] = Field(
        default_factory=dict, description="Mapping from internal symbols to broker trading symbols"
    )


class OrderTranslationResult(BaseModel):
    """Immutable result of translating a decision into broker order parameters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    client_order_id: str = Field(description="Deterministic idempotent client order ID")
    instrument: str = Field(description="Internal instrument trading symbol")
    broker_symbol: str = Field(description="Mapped broker trading symbol")
    direction: Literal["BUY", "SELL"] = Field(description="Order direction")
    order_type: Literal["LIMIT", "MARKET"] = Field(description="Order type")
    quantity: int = Field(gt=0, description="Order quantity")
    limit_price: Decimal | None = Field(
        default=None, description="Calculated limit price (None for MARKET orders)"
    )
    decision_quote_price: Decimal = Field(
        description="Decision-time quote price used for slippage calculation"
    )
    slippage_bound: Decimal | None = Field(
        default=None, description="Applied slippage bound amount"
    )
    tick_size: Decimal = Field(gt=Decimal("0"), description="Applicable exchange tick size")
    lot_size: int = Field(gt=0, description="Applicable instrument lot size")


class OrderTranslator:
    """Translates Supervisor decisions and candidate trades into broker orders."""

    def __init__(self, config: OrderTranslationConfig | None = None) -> None:
        self.config = config or OrderTranslationConfig()

    def get_tick_size(self, instrument: str) -> Decimal:
        """Get applicable tick size for the instrument."""
        if instrument in self.config.instrument_tick_sizes:
            return self.config.instrument_tick_sizes[instrument]
        base_symbol = instrument.rsplit(":", maxsplit=1)[-1]
        if base_symbol in self.config.instrument_tick_sizes:
            return self.config.instrument_tick_sizes[base_symbol]
        return self.config.default_tick_size

    def get_lot_size(self, instrument: str) -> int:
        """Get applicable lot size for the instrument (default 1)."""
        if instrument in self.config.instrument_lot_sizes:
            return self.config.instrument_lot_sizes[instrument]
        base_symbol = instrument.rsplit(":", maxsplit=1)[-1]
        if base_symbol in self.config.instrument_lot_sizes:
            return self.config.instrument_lot_sizes[base_symbol]
        return 1

    def map_symbol(self, instrument: str) -> str:
        """Map internal instrument symbol to broker trading symbol."""
        return self.config.symbol_mappings.get(instrument, instrument)

    def calculate_bounded_limit_price(
        self,
        direction: Literal["BUY", "SELL"],
        quote_price: Decimal,
        instrument: str,
        slippage_pct: Decimal | None = None,
    ) -> Decimal:
        """Calculate conservative tick-rounded limit price bounded by maximum slippage.

        For BUY orders: Limit price is capped at quote * (1 + max_slippage) and rounded
        DOWN to the nearest tick to guarantee slippage does not exceed the bound.

        For SELL orders: Limit price is floored at quote * (1 - max_slippage) and rounded
        UP to the nearest tick to guarantee slippage does not exceed the bound.

        Args:
            direction: 'BUY' or 'SELL'.
            quote_price: Decision-time base market price.
            instrument: Traded instrument symbol.
            slippage_pct: Optional custom slippage percentage override.

        Returns:
            Decimal: Valid, tick-aligned limit price.

        Raises:
            OrderTranslationError: If calculated limit price is non-positive or invalid.
        """
        if quote_price <= Decimal("0"):
            msg = f"Quote price must be strictly positive, got {quote_price}"
            raise OrderTranslationError(msg)

        pct = slippage_pct if slippage_pct is not None else self.config.max_slippage_pct
        tick = self.get_tick_size(instrument)

        if direction == "BUY":
            raw_bound = quote_price * (Decimal("1") + pct)
            # Conservative round DOWN to nearest tick to avoid exceeding slippage ceiling
            tick_count = (raw_bound / tick).to_integral_value(rounding=ROUND_FLOOR)
        else:
            raw_bound = quote_price * (Decimal("1") - pct)
            # Conservative round UP to nearest tick to avoid falling below slippage floor
            tick_count = (raw_bound / tick).to_integral_value(rounding=ROUND_CEILING)

        limit_price = tick_count * tick

        if limit_price <= Decimal("0"):
            msg = f"Calculated limit price must be strictly positive, got {limit_price}"
            raise OrderTranslationError(msg)

        # Enforce exact tick alignment
        if (limit_price % tick) != Decimal("0"):
            msg = f"Calculated limit price {limit_price} violates tick constraint for tick {tick}"
            raise OrderTranslationError(msg)

        return limit_price

    def translate(
        self,
        decision: Decision,
        candidate: CandidateTrade,
        current_quote: Decimal | None = None,
        decision_record_id: UUID | str | None = None,
        override_order_type: Literal["LIMIT", "MARKET"] | None = None,
    ) -> OrderTranslationResult:
        """Translate a Supervisor decision and CandidateTrade into broker order parameters.

        Args:
            decision: Approved Supervisor Decision.
            candidate: Associated CandidateTrade opportunity.
            current_quote: Optional live quote price. If None, candidate.entry_price is used.
            decision_record_id: Optional linked DecisionRecord UUID or ID.
            override_order_type: Optional order type override (must satisfy safety configuration).

        Returns:
            OrderTranslationResult: Validated order translation ready for broker dispatch.

        Raises:
            OrderTranslationError: If decision is not actionable, lot size is violated,
                                  market orders are forbidden, or price calculations fail.
        """
        if not decision.is_trade_approved:
            msg = (
                f"Cannot translate non-approved decision with outcome='{decision.outcome}' "
                f"and approved_quantity={decision.approved_quantity}"
            )
            raise OrderTranslationError(msg)

        if decision.approved_quantity <= 0:
            msg = f"Approved quantity must be positive, got {decision.approved_quantity}"
            raise OrderTranslationError(msg)

        direction: Literal["BUY", "SELL"] = "BUY" if decision.outcome == "BUY" else "SELL"
        if direction != candidate.direction:
            msg = (
                f"Direction mismatch between decision ('{decision.outcome}') and "
                f"candidate trade ('{candidate.direction}')"
            )
            raise OrderTranslationError(msg)

        instrument = candidate.instrument
        lot_size = self.get_lot_size(instrument)
        if decision.approved_quantity % lot_size != 0:
            msg = (
                f"Approved quantity {decision.approved_quantity} is not a multiple of "
                f"lot size {lot_size} for instrument '{instrument}'"
            )
            raise OrderTranslationError(msg)

        # Resolve order type
        order_type = override_order_type or self.config.default_order_type
        if order_type == "MARKET" and not self.config.allow_market_orders:
            msg = (
                "Market orders are forbidden by safety policy (allow_market_orders=False). "
                "EDD §6.2 requires bounded limit orders."
            )
            raise OrderTranslationError(msg)

        quote_price = current_quote if current_quote is not None else candidate.entry_price
        tick_size = self.get_tick_size(instrument)

        limit_price: Decimal | None = None
        slippage_bound: Decimal | None = None

        if order_type == "LIMIT":
            limit_price = self.calculate_bounded_limit_price(
                direction=direction,
                quote_price=quote_price,
                instrument=instrument,
            )
            slippage_bound = abs(limit_price - quote_price)

        # Resolve client order ID
        if decision_record_id is not None:
            client_order_id = generate_client_order_id(decision_record_id)
        else:
            # Fallback deterministic key based on decision timestamp and candidate attributes
            ts_str = decision.timestamp.strftime("%Y%m%d%H%M%S%f")
            client_order_id = f"aitrader-{instrument}-{direction}-{ts_str}"

        broker_symbol = self.map_symbol(instrument)

        return OrderTranslationResult(
            client_order_id=client_order_id,
            instrument=instrument,
            broker_symbol=broker_symbol,
            direction=direction,
            order_type=order_type,
            quantity=decision.approved_quantity,
            limit_price=limit_price,
            decision_quote_price=quote_price,
            slippage_bound=slippage_bound,
            tick_size=tick_size,
            lot_size=lot_size,
        )
