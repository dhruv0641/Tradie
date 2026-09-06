"""Multi-factor reward engine for Reinforcement Learning training.

Conforms to PRD FR-24, FRD-LEARN-9, and ADD §11:
RL reward functions must incorporate return, risk, drawdown, volatility,
transaction costs, slippage, and consistency — never raw profit alone.
"""

from collections.abc import Sequence
from decimal import Decimal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.backtesting.cost_model import CostModel
from src.domain.agent_signal import SignalDirection
from src.utils.logging import get_logger

logger = get_logger(__name__)


class RewardConfig(BaseModel):
    """Configuration for multi-factor RL reward computation.

    Enforces that RL training penalizes risk, tail drawdowns, and transaction churn (ADD §11).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    return_weight: float = Field(
        default=1.0,
        ge=0.0,
        description="Weight applied to period net return",
    )
    drawdown_weight: float = Field(
        default=2.0,
        ge=0.0,
        description="Weight applied to quadratic peak-to-trough drawdown penalty",
    )
    volatility_weight: float = Field(
        default=0.5,
        ge=0.0,
        description="Weight applied to rolling return standard deviation penalty",
    )
    cost_weight: float = Field(
        default=1.0,
        ge=0.0,
        description="Weight applied to transaction fee and statutory charges drag",
    )
    slippage_weight: float = Field(
        default=1.0,
        ge=0.0,
        description="Weight applied to execution slippage drag",
    )
    churn_weight: float = Field(
        default=0.1,
        ge=0.0,
        description="Weight applied to position flipping / churning penalty",
    )
    consistency_weight: float = Field(
        default=0.2,
        ge=0.0,
        description="Weight applied to risk-adjusted consistency reward bonus",
    )
    rolling_window: int = Field(
        default=20,
        ge=2,
        description="Number of past steps used for rolling volatility and consistency",
    )

    @model_validator(mode="after")
    def validate_not_raw_profit_alone(self) -> "RewardConfig":
        """Enforce FRD-LEARN-9: reward function is never raw profit alone."""
        risk_components_sum = self.drawdown_weight + self.volatility_weight + self.cost_weight
        if risk_components_sum <= 0.0:
            msg = (
                "Reward function must incorporate risk, drawdown, volatility, and "
                "transaction costs — raw profit alone is strictly prohibited (FRD-LEARN-9)."
            )
            raise ValueError(msg)
        return self


class RewardComponents(BaseModel):
    """Itemized breakdown of multi-factor reward components for audit and diagnostics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    total_reward: float = Field(description="Aggregated multi-factor scalar reward")
    net_return: float = Field(description="Period net return fraction")
    return_component: float = Field(description="Weighted return contribution")
    drawdown_penalty: float = Field(
        description="Penalty assessed for current peak-to-trough drawdown"
    )
    volatility_penalty: float = Field(description="Penalty assessed for rolling return volatility")
    cost_drag: float = Field(description="Drag assessed for transaction and statutory fees")
    slippage_drag: float = Field(description="Drag assessed for simulated execution slippage")
    churn_penalty: float = Field(description="Penalty assessed for excessive position churning")
    consistency_bonus: float = Field(description="Bonus for stable, non-negative return trajectory")
    drawdown_pct: float = Field(description="Current drawdown percentage from peak [0.0, 1.0]")
    rolling_volatility: float = Field(description="Standard deviation of recent period returns")


class MultiFactorRewardCalculator:
    """Calculates multi-factor reward vectors for RL trading episodes.

    Adheres to FRD-LEARN-9, ADD §11, and TRD-ML-4.
    """

    def __init__(
        self,
        config: RewardConfig | None = None,
        cost_model: CostModel | None = None,
    ) -> None:
        """Initialize MultiFactorRewardCalculator."""
        self.config = config or RewardConfig()
        self.cost_model = cost_model or CostModel()
        self._logger = logger.bind(component="MultiFactorRewardCalculator")

    def calculate_step_reward(
        self,
        *,
        current_portfolio_value: float,
        previous_portfolio_value: float,
        peak_portfolio_value: float,
        transaction_cost: float,
        slippage_cost: float,
        current_direction: SignalDirection,
        previous_direction: SignalDirection | None,
        recent_returns: Sequence[float],
    ) -> RewardComponents:
        """Calculate multi-factor reward for a single environment transition.

        Args:
            current_portfolio_value: Current mark-to-market equity.
            previous_portfolio_value: Equity before step execution.
            peak_portfolio_value: Maximum equity achieved in this episode.
            transaction_cost: Absolute rupee brokerage and statutory fees incurred.
            slippage_cost: Absolute rupee slippage incurred.
            current_direction: Current signal direction (LONG, SHORT, NO_VIEW).
            previous_direction: Signal direction in prior step.
            recent_returns: Sequence of recent period return percentages.

        Returns:
            RewardComponents with total scalar reward and audit attribution.
        """
        base_denom = max(previous_portfolio_value, 1.0)

        # 1. Net Return Component
        gross_pnl = current_portfolio_value - previous_portfolio_value
        net_pnl = gross_pnl - transaction_cost - slippage_cost
        net_return = net_pnl / base_denom
        return_component = self.config.return_weight * net_return

        # 2. Drawdown Penalty (Quadratic peak-to-trough penalty)
        peak_denom = max(peak_portfolio_value, 1.0)
        drawdown_pct = max(0.0, (peak_portfolio_value - current_portfolio_value) / peak_denom)
        drawdown_penalty = self.config.drawdown_weight * (drawdown_pct**2)

        # 3. Volatility Penalty (Rolling standard deviation of returns)
        vol = float(np.std(recent_returns, ddof=1)) if len(recent_returns) >= 2 else 0.0
        volatility_penalty = self.config.volatility_weight * vol

        # 4. Cost Drag (Statutory taxes and brokerage)
        cost_drag = self.config.cost_weight * (transaction_cost / base_denom)

        # 5. Slippage Drag
        slippage_drag = self.config.slippage_weight * (slippage_cost / base_denom)

        # 6. Churn Penalty (Discourage rapid unconvincing signal flips)
        churn_penalty = 0.0
        if (
            previous_direction is not None
            and current_direction != previous_direction
            and SignalDirection.NO_VIEW not in (current_direction, previous_direction)
        ):
            churn_penalty = self.config.churn_weight * 0.005

        # 7. Consistency Bonus (Positive Sharpe-like risk-adjusted consistency)
        consistency_bonus = 0.0
        if len(recent_returns) >= 5 and vol > 1e-6:
            mean_ret = float(np.mean(recent_returns))
            if mean_ret > 0.0:
                sharpe_ratio = mean_ret / vol
                consistency_bonus = self.config.consistency_weight * min(sharpe_ratio * 0.01, 0.05)

        # Total Aggregated Multi-Factor Reward
        total_reward = (
            return_component
            - drawdown_penalty
            - volatility_penalty
            - cost_drag
            - slippage_drag
            - churn_penalty
            + consistency_bonus
        )

        return RewardComponents(
            total_reward=total_reward,
            net_return=net_return,
            return_component=return_component,
            drawdown_penalty=drawdown_penalty,
            volatility_penalty=volatility_penalty,
            cost_drag=cost_drag,
            slippage_drag=slippage_drag,
            churn_penalty=churn_penalty,
            consistency_bonus=consistency_bonus,
            drawdown_pct=drawdown_pct,
            rolling_volatility=vol,
        )

    def calculate_trade_costs(
        self,
        price: float,
        quantity: int,
        side: str,
    ) -> float:
        """Calculate exact statutory and brokerage cost using CostModel.

        Args:
            price: Executed price in INR.
            quantity: Traded volume.
            side: 'BUY' or 'SELL'.

        Returns:
            Total transaction charges in INR.
        """
        if quantity <= 0 or price <= 0:
            return 0.0

        leg_cost = self.cost_model.calculate_leg(
            price=Decimal(str(round(price, 4))),
            quantity=quantity,
            side="BUY" if side.upper() == "BUY" else "SELL",
            product_type="INTRADAY",
        )
        return float(leg_cost.total_cost)
