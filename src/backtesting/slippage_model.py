"""Bid-ask spread and liquidity-scaled slippage model (PRD FR-25, BTD §6.1, RTLD §11)."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.utils.logging import get_logger

logger = get_logger(__name__)


class SlippageConfig(BaseModel):
    """Configuration for execution slippage and bid-ask spread modeling.

    Conforms to BTD §6.1 liquidity scaling tiers and RTLD §11 liquidity thresholds.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    base_slippage_bps: float = Field(
        default=5.0,
        ge=0.0,
        description="Base execution slippage in basis points (default 5 bps = 0.05%)",
    )
    spread_proxy_pct: float = Field(
        default=0.0005,
        ge=0.0,
        description=(
            "Default bid-ask spread proxy percentage when depth is unavailable (default 0.05%)"
        ),
    )
    tier1_threshold: float = Field(
        default=0.01,
        gt=0.0,
        description="Threshold ratio of order quantity to bar volume for Tier 1 (1x multiplier)",
    )
    tier2_threshold: float = Field(
        default=0.05,
        gt=0.0,
        description="Threshold ratio of order quantity to bar volume for Tier 2 (2x multiplier)",
    )
    tier1_multiplier: float = Field(
        default=1.0, ge=1.0, description="Slippage multiplier for Tier 1 (< 1% volume)"
    )
    tier2_multiplier: float = Field(
        default=2.0, ge=1.0, description="Slippage multiplier for Tier 2 (1%-5% volume)"
    )
    tier3_multiplier: float = Field(
        default=4.0, ge=1.0, description="Slippage multiplier for Tier 3 (> 5% volume when allowed)"
    )
    reject_above_tier2: bool = Field(
        default=True,
        description="If True, orders exceeding tier2_threshold (>5% of bar volume) are rejected",
    )


class SlippageResult(BaseModel):
    """Immutable execution outcome incorporating spread drag, slippage, and liquidity gating."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    requested_price: Decimal = Field(gt=Decimal("0"))
    executed_price: Decimal = Field(gt=Decimal("0"))
    quantity: int = Field(gt=0)
    side: Literal["BUY", "SELL"]
    spread_drag: Decimal = Field(ge=Decimal("0"))
    slippage_drag: Decimal = Field(ge=Decimal("0"))
    total_price_impact: Decimal = Field(ge=Decimal("0"))
    liquidity_ratio: float = Field(ge=0.0)
    multiplier: float = Field(ge=1.0)
    effective_slippage_bps: float = Field(ge=0.0)
    rejected: bool = Field(default=False)
    rejection_reason: str | None = Field(default=None)


class SlippageModel:
    """Calculates realistic execution prices with adverse spread drag and volume-scaled slippage.

    Guarantees conservative fills conforming to BTD §6.1 to prevent overfitting in illiquid bars.
    """

    def __init__(self, config: SlippageConfig | None = None) -> None:
        """Initialize SlippageModel with configuration."""
        self.config = config or SlippageConfig()
        self._logger = logger.bind(component="SlippageModel")

    def calculate_slippage(
        self,
        requested_price: Decimal,
        quantity: int,
        side: Literal["BUY", "SELL"],
        bar_volume: float,
        bid_ask_spread: Decimal | None = None,
    ) -> SlippageResult:
        """Calculate executed price after adverse spread drag and liquidity-scaled slippage.

        Args:
            requested_price: Target fill price (e.g. bar open or limit price).
            quantity: Order share quantity (must be > 0).
            side: 'BUY' or 'SELL'.
            bar_volume: Available historical bar volume in shares.
            bid_ask_spread: Quoted bid-ask spread. If None, uses spread_proxy_pct.

        Returns:
            SlippageResult capturing adjusted price and execution attribution.

        Raises:
            ValueError: If requested_price <= 0 or quantity <= 0.
        """
        if requested_price <= Decimal("0"):
            msg = f"requested_price must be positive, got {requested_price}"
            raise ValueError(msg)
        if quantity <= 0:
            msg = f"quantity must be greater than zero, got {quantity}"
            raise ValueError(msg)

        # 1. Zero bar volume check
        if bar_volume <= 0.0:
            return SlippageResult(
                requested_price=requested_price,
                executed_price=requested_price,
                quantity=quantity,
                side=side,
                spread_drag=Decimal("0.00"),
                slippage_drag=Decimal("0.00"),
                total_price_impact=Decimal("0.00"),
                liquidity_ratio=float("inf"),
                multiplier=self.config.tier3_multiplier,
                effective_slippage_bps=self.config.base_slippage_bps * self.config.tier3_multiplier,
                rejected=True,
                rejection_reason="ZERO_BAR_VOLUME",
            )

        liquidity_ratio = float(quantity) / float(bar_volume)

        # 2. Determine liquidity multiplier and volume limit gating
        if liquidity_ratio < self.config.tier1_threshold:
            multiplier = self.config.tier1_multiplier
        elif liquidity_ratio <= self.config.tier2_threshold:
            multiplier = self.config.tier2_multiplier
        else:
            if self.config.reject_above_tier2:
                return SlippageResult(
                    requested_price=requested_price,
                    executed_price=requested_price,
                    quantity=quantity,
                    side=side,
                    spread_drag=Decimal("0.00"),
                    slippage_drag=Decimal("0.00"),
                    total_price_impact=Decimal("0.00"),
                    liquidity_ratio=round(liquidity_ratio, 6),
                    multiplier=self.config.tier3_multiplier,
                    effective_slippage_bps=self.config.base_slippage_bps
                    * self.config.tier3_multiplier,
                    rejected=True,
                    rejection_reason="EXCESSIVE_VOLUME_SHARE",
                )
            multiplier = self.config.tier3_multiplier

        # 3. Half-spread execution drag
        if bid_ask_spread is not None and bid_ask_spread >= Decimal("0"):
            half_spread = (bid_ask_spread / Decimal("2")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        else:
            proxy_dec = Decimal(str(self.config.spread_proxy_pct / 2.0))
            half_spread = (requested_price * proxy_dec).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

        # 4. Liquidity-scaled slippage drag
        effective_bps = self.config.base_slippage_bps * multiplier
        slippage_pct_dec = Decimal(str(effective_bps / 10000.0))
        slippage_drag = (requested_price * slippage_pct_dec).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        total_impact = half_spread + slippage_drag

        # 5. Executed price with adverse direction
        if side == "BUY":
            executed_price = requested_price + total_impact
        else:
            executed_price = max(Decimal("0.01"), requested_price - total_impact)

        return SlippageResult(
            requested_price=requested_price,
            executed_price=executed_price,
            quantity=quantity,
            side=side,
            spread_drag=half_spread,
            slippage_drag=slippage_drag,
            total_price_impact=total_impact,
            liquidity_ratio=round(liquidity_ratio, 6),
            multiplier=multiplier,
            effective_slippage_bps=round(effective_bps, 2),
            rejected=False,
            rejection_reason=None,
        )
