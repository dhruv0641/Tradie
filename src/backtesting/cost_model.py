"""Indian market statutory charges and brokerage cost engine (PRD FR-25, BTD §6, RTLD §4)."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.utils.logging import get_logger

logger = get_logger(__name__)


class CostModelConfig(BaseModel):
    """Configuration for Indian market brokerage schedule and statutory taxes.

    Conforms to official NSE, SEBI, and statutory tax schedules (BTD §6, BTD-1-7).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    flat_brokerage_cap: Decimal = Field(
        default=Decimal("20.00"),
        ge=Decimal("0"),
        description="Maximum flat fee cap per executed order leg in INR",
    )
    brokerage_pct: Decimal = Field(
        default=Decimal("0.0003"),
        ge=Decimal("0"),
        description="Percentage brokerage of turnover (default 0.03%)",
    )
    stt_delivery_rate: Decimal = Field(
        default=Decimal("0.0010"),
        ge=Decimal("0"),
        description="STT rate on delivery trades (default 0.1% on buy & sell)",
    )
    stt_intraday_sell_rate: Decimal = Field(
        default=Decimal("0.00025"),
        ge=Decimal("0"),
        description="STT rate on intraday trades (default 0.025% on sell only)",
    )
    exchange_turnover_rate: Decimal = Field(
        default=Decimal("0.0000297"),
        ge=Decimal("0"),
        description="NSE exchange turnover charges rate (default 0.00297%)",
    )
    sebi_turnover_rate: Decimal = Field(
        default=Decimal("0.000001"),
        ge=Decimal("0"),
        description="SEBI turnover fee rate (default 0.0001% or ₹10/crore)",
    )
    stamp_duty_delivery_rate: Decimal = Field(
        default=Decimal("0.00015"),
        ge=Decimal("0"),
        description="Stamp duty rate on delivery buy orders (default 0.015%)",
    )
    stamp_duty_intraday_rate: Decimal = Field(
        default=Decimal("0.00003"),
        ge=Decimal("0"),
        description="Stamp duty rate on intraday buy orders (default 0.003%)",
    )
    gst_rate: Decimal = Field(
        default=Decimal("0.18"),
        ge=Decimal("0"),
        description="GST rate applied to (Brokerage + Exchange Charges) (default 18%)",
    )
    stt_round_to_rupee: bool = Field(
        default=False,
        description="If True, rounds STT to the nearest integer rupee per contract note convention",
    )


class CostBreakdown(BaseModel):
    """Immutable, itemized transaction cost breakdown for an executed order leg."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    side: Literal["BUY", "SELL"]
    product_type: Literal["INTRADAY", "DELIVERY"]
    price: Decimal = Field(ge=Decimal("0"))
    quantity: int = Field(gt=0)
    turnover: Decimal = Field(ge=Decimal("0"))
    brokerage: Decimal = Field(ge=Decimal("0"))
    stt: Decimal = Field(ge=Decimal("0"))
    exchange_charges: Decimal = Field(ge=Decimal("0"))
    sebi_charges: Decimal = Field(ge=Decimal("0"))
    stamp_duty: Decimal = Field(ge=Decimal("0"))
    gst: Decimal = Field(ge=Decimal("0"))
    total_statutory_charges: Decimal = Field(ge=Decimal("0"))
    total_cost: Decimal = Field(ge=Decimal("0"))
    effective_cost_bps: float = Field(ge=0.0)


class RoundTripCostBreakdown(BaseModel):
    """Cumulative round-trip execution cost and breakeven attribution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entry_cost: CostBreakdown
    exit_cost: CostBreakdown
    product_type: Literal["INTRADAY", "DELIVERY"]
    quantity: int = Field(gt=0)
    total_turnover: Decimal = Field(ge=Decimal("0"))
    total_brokerage: Decimal = Field(ge=Decimal("0"))
    total_statutory_charges: Decimal = Field(ge=Decimal("0"))
    total_cost: Decimal = Field(ge=Decimal("0"))
    gross_pnl: Decimal
    net_pnl: Decimal
    effective_cost_bps: float = Field(ge=0.0)
    breakeven_price_diff: Decimal = Field(ge=Decimal("0"))


class CostModel:
    """Calculates exact statutory taxes, exchange fees, and brokerage per trade.

    Adheres to BTD §6 and RTLD §4 to prevent unrealistic backtest profitability.
    """

    def __init__(self, config: CostModelConfig | None = None) -> None:
        """Initialize CostModel with configurable rates."""
        self.config = config or CostModelConfig()
        self._logger = logger.bind(component="CostModel")

    def calculate_leg(
        self,
        price: Decimal,
        quantity: int,
        side: Literal["BUY", "SELL"],
        product_type: Literal["INTRADAY", "DELIVERY"] = "INTRADAY",
    ) -> CostBreakdown:
        """Calculate detailed cost breakdown for a single executed leg.

        Args:
            price: Executed share price.
            quantity: Executed quantity (must be > 0).
            side: 'BUY' or 'SELL'.
            product_type: 'INTRADAY' or 'DELIVERY'.

        Returns:
            Itemized CostBreakdown domain model.
        """
        if price <= Decimal("0"):
            msg = f"Price must be positive, got {price}"
            raise ValueError(msg)
        if quantity <= 0:
            msg = f"Quantity must be greater than zero, got {quantity}"
            raise ValueError(msg)

        turnover = (price * Decimal(quantity)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # 1. Brokerage: min(flat_cap, pct * turnover)
        raw_brokerage = turnover * self.config.brokerage_pct
        brokerage = min(self.config.flat_brokerage_cap, raw_brokerage).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        # 2. STT (Securities Transaction Tax)
        if product_type == "DELIVERY":
            raw_stt = turnover * self.config.stt_delivery_rate
        elif side == "SELL":
            raw_stt = turnover * self.config.stt_intraday_sell_rate
        else:
            raw_stt = Decimal("0.00")

        if self.config.stt_round_to_rupee:
            stt = raw_stt.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        else:
            stt = raw_stt.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # 3. Exchange transaction charges (NSE)
        exchange_charges = (turnover * self.config.exchange_turnover_rate).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        # 4. SEBI turnover fee
        sebi_charges = (turnover * self.config.sebi_turnover_rate).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        # 5. Stamp duty (BUY leg only)
        if side == "BUY":
            if product_type == "DELIVERY":
                stamp_duty = (turnover * self.config.stamp_duty_delivery_rate).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
            else:
                stamp_duty = (turnover * self.config.stamp_duty_intraday_rate).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
        else:
            stamp_duty = Decimal("0.00")

        # 6. GST: 18% on (Brokerage + Exchange Charges) per BTD §6 item 7
        gst_base = brokerage + exchange_charges
        gst = (gst_base * self.config.gst_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        total_statutory = stt + exchange_charges + sebi_charges + stamp_duty + gst
        total_cost = brokerage + total_statutory

        effective_bps = (
            float(total_cost / turnover * Decimal("10000")) if turnover > Decimal("0") else 0.0
        )

        return CostBreakdown(
            side=side,
            product_type=product_type,
            price=price,
            quantity=quantity,
            turnover=turnover,
            brokerage=brokerage,
            stt=stt,
            exchange_charges=exchange_charges,
            sebi_charges=sebi_charges,
            stamp_duty=stamp_duty,
            gst=gst,
            total_statutory_charges=total_statutory,
            total_cost=total_cost,
            effective_cost_bps=round(effective_bps, 2),
        )

    def calculate_round_trip(
        self,
        entry_price: Decimal,
        exit_price: Decimal,
        quantity: int,
        product_type: Literal["INTRADAY", "DELIVERY"] = "INTRADAY",
    ) -> RoundTripCostBreakdown:
        """Calculate complete round-trip transaction costs and breakeven attribution.

        Args:
            entry_price: Executed entry buy price.
            exit_price: Executed exit sell price.
            quantity: Executed quantity.
            product_type: 'INTRADAY' or 'DELIVERY'.

        Returns:
            Aggregated RoundTripCostBreakdown domain model.
        """
        entry_cost = self.calculate_leg(
            price=entry_price, quantity=quantity, side="BUY", product_type=product_type
        )
        exit_cost = self.calculate_leg(
            price=exit_price, quantity=quantity, side="SELL", product_type=product_type
        )

        total_turnover = entry_cost.turnover + exit_cost.turnover
        total_brokerage = entry_cost.brokerage + exit_cost.brokerage
        total_statutory = entry_cost.total_statutory_charges + exit_cost.total_statutory_charges
        total_cost = entry_cost.total_cost + exit_cost.total_cost

        gross_pnl = (exit_price - entry_price) * Decimal(quantity)
        net_pnl = gross_pnl - total_cost

        effective_bps = (
            float(total_cost / total_turnover * Decimal("10000"))
            if total_turnover > Decimal("0")
            else 0.0
        )
        breakeven_diff = (total_cost / Decimal(quantity)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        return RoundTripCostBreakdown(
            entry_cost=entry_cost,
            exit_cost=exit_cost,
            product_type=product_type,
            quantity=quantity,
            total_turnover=total_turnover,
            total_brokerage=total_brokerage,
            total_statutory_charges=total_statutory,
            total_cost=total_cost,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            effective_cost_bps=round(effective_bps, 2),
            breakeven_price_diff=breakeven_diff,
        )
