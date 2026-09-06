"""Fixed-fractional position sizing engine with multi-cap bounding.

Implements deterministic position sizing per RTLD §6, FRD-RISK-2, FRD-RISK-3,
and FRD-RISK-6:
- Risk Amount = Current Capital * Max Risk Per Trade Pct (adjusted by streak/volatility)
- Raw Quantity = floor(Risk Amount / Stop Distance)
- Max Position Value Cap = Current Capital * Max Position Size Pct
- Exposure Headroom Cap = max(0, Max Exposure - Currently Deployed)
- Final Quantity = min(Raw Quantity, floor(Max Pos Value / Entry), floor(Headroom / Entry))
"""

from dataclasses import dataclass
from decimal import Decimal

import structlog

from src.domain.risk import CandidateTrade, CapitalState, MarketState, StreakState
from src.risk.config import RiskConfig

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class SizingResult:
    """Immutable outcome of position sizing calculation."""

    approved: bool
    final_quantity: int
    raw_quantity: int
    pos_cap_quantity: int
    exposure_cap_quantity: int
    binding_constraint: (
        str  # "none", "risk_budget", "position_cap", "exposure_headroom", "unsizeable"
    )
    risk_amount: Decimal
    risk_pct_used: Decimal
    actual_risk_at_stop: Decimal
    position_value: Decimal
    reason: str = ""


class PositionSizer:
    """Fixed-fractional position sizer enforcing multi-constraint bounds (RTLD §6)."""

    def __init__(self, config: RiskConfig | None = None) -> None:
        self._config = config or RiskConfig()

    @property
    def config(self) -> RiskConfig:
        """Return the active risk configuration."""
        return self._config

    def calculate(
        self,
        candidate: CandidateTrade,
        capital: CapitalState,
        streak: StreakState | None = None,
        market: MarketState | None = None,
    ) -> SizingResult:
        """Calculate approved position size respecting all portfolio and risk constraints.

        Args:
            candidate: Candidate trade parameters (entry, stop, direction).
            capital: Real-time account capital state.
            streak: Behavioral consecutive loss streak state (optional).
            market: Real-time market volatility and context (optional).

        Returns:
            SizingResult with final approved quantity and binding constraint diagnostic.
        """
        stop_distance = abs(candidate.entry_price - candidate.stop_price)
        if stop_distance <= Decimal("0"):
            return SizingResult(
                approved=False,
                final_quantity=0,
                raw_quantity=0,
                pos_cap_quantity=0,
                exposure_cap_quantity=0,
                binding_constraint="unsizeable",
                risk_amount=Decimal("0"),
                risk_pct_used=Decimal("0"),
                actual_risk_at_stop=Decimal("0"),
                position_value=Decimal("0"),
                reason="Stop distance must be strictly positive",
            )

        if candidate.entry_price <= Decimal("0"):
            return SizingResult(
                approved=False,
                final_quantity=0,
                raw_quantity=0,
                pos_cap_quantity=0,
                exposure_cap_quantity=0,
                binding_constraint="unsizeable",
                risk_amount=Decimal("0"),
                risk_pct_used=Decimal("0"),
                actual_risk_at_stop=Decimal("0"),
                position_value=Decimal("0"),
                reason="Entry price must be strictly positive",
            )

        # Base per-trade risk percentage
        risk_pct = self._config.max_risk_per_trade_pct

        # Tier-1 behavioral streak reduction (RTLD-11: 50% reduction on >= 3 losses)
        if (
            streak is not None
            and streak.consecutive_losses >= self._config.consec_loss_reduce_trigger
        ):
            risk_pct = risk_pct * Decimal("0.5")

        # Volatility scaling (RTLD-14: 50% reduction when vol > 2x baseline)
        if (
            market is not None
            and market.trailing_20session_avg_volatility > Decimal("0")
            and market.current_volatility
            > market.trailing_20session_avg_volatility * self._config.vol_reduce_multiple
        ):
            risk_pct = risk_pct * Decimal("0.5")

        risk_budget = capital.current_capital * risk_pct
        raw_quantity = int(risk_budget // stop_distance)
        if raw_quantity <= 0:
            msg = (
                f"Risk budget ₹{risk_budget:.2f} cannot purchase 1 unit "
                f"at stop distance ₹{stop_distance:.2f}"
            )
            return SizingResult(
                approved=False,
                final_quantity=0,
                raw_quantity=raw_quantity,
                pos_cap_quantity=0,
                exposure_cap_quantity=0,
                binding_constraint="unsizeable",
                risk_amount=risk_budget,
                risk_pct_used=risk_pct,
                actual_risk_at_stop=Decimal("0"),
                position_value=Decimal("0"),
                reason=msg,
            )

        # Max single position value constraint (RTLD §8)
        max_pos_value = capital.current_capital * self._config.max_position_size_pct
        pos_cap_quantity = int(max_pos_value // candidate.entry_price)

        # Max portfolio exposure headroom constraint (RTLD §6, §8)
        max_exposure = capital.current_capital * self._config.max_portfolio_exposure_pct
        exposure_headroom = max(Decimal("0"), max_exposure - capital.currently_deployed)
        exposure_cap_quantity = int(exposure_headroom // candidate.entry_price)

        final_quantity = min(raw_quantity, pos_cap_quantity, exposure_cap_quantity)

        if final_quantity <= 0:
            binding = "position_cap" if pos_cap_quantity <= 0 else "exposure_headroom"
            reason = (
                "Single position cap prevents purchasing 1 unit"
                if pos_cap_quantity <= 0
                else "Exposure headroom prevents purchasing 1 unit"
            )
            return SizingResult(
                approved=False,
                final_quantity=0,
                raw_quantity=raw_quantity,
                pos_cap_quantity=pos_cap_quantity,
                exposure_cap_quantity=exposure_cap_quantity,
                binding_constraint=binding,
                risk_amount=risk_budget,
                risk_pct_used=risk_pct,
                actual_risk_at_stop=Decimal("0"),
                position_value=Decimal("0"),
                reason=reason,
            )

        # Determine governing binding constraint
        if raw_quantity <= pos_cap_quantity and raw_quantity <= exposure_cap_quantity:
            binding = "risk_budget"
        elif pos_cap_quantity <= exposure_cap_quantity:
            binding = "position_cap"
        else:
            binding = "exposure_headroom"

        actual_risk = Decimal(str(final_quantity)) * stop_distance
        position_value = Decimal(str(final_quantity)) * candidate.entry_price

        logger.debug(
            "position_sizing_completed",
            instrument=candidate.instrument,
            final_quantity=final_quantity,
            raw_quantity=raw_quantity,
            pos_cap=pos_cap_quantity,
            exposure_cap=exposure_cap_quantity,
            binding=binding,
            actual_risk=float(actual_risk),
            position_value=float(position_value),
        )

        return SizingResult(
            approved=True,
            final_quantity=final_quantity,
            raw_quantity=raw_quantity,
            pos_cap_quantity=pos_cap_quantity,
            exposure_cap_quantity=exposure_cap_quantity,
            binding_constraint=binding,
            risk_amount=risk_budget,
            risk_pct_used=risk_pct,
            actual_risk_at_stop=actual_risk,
            position_value=position_value,
            reason="",
        )
