"""Gymnasium-compliant reinforcement learning trading environment.

Conforms to PRD FR-24, FRD-LEARN-9, ADD §10-§11, and TRD-ML-4:
- Sandboxed offline RL training structurally lacking live order submission capabilities.
- Action space strictly constrained to AgentSignalOutput (direction and confidence [0, 1]).
- Multi-factor reward penalizing drawdown, volatility, and transaction churn.
"""

from collections import deque
from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, cast

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from src.backtesting.cost_model import CostModel
from src.domain.agent_signal import AgentSignalOutput, SignalDirection
from src.research.environment import ResearchIsolationError
from src.research.rl.reward import (
    MultiFactorRewardCalculator,
    RewardComponents,
    RewardConfig,
)
from src.utils.logging import get_logger

logger = get_logger(__name__)


class ActionSpaceType(StrEnum):
    """Supported action space representations for RL agent training."""

    DISCRETE = "DISCRETE"
    CONTINUOUS = "CONTINUOUS"


class DiscreteSpace:
    """Gymnasium-compatible discrete space implementation."""

    def __init__(self, n: int, start: int = 0) -> None:
        """Initialize discrete space [start, start + n - 1]."""
        self.n = int(n)
        self.start = int(start)
        self.shape: tuple[int, ...] = ()
        self.dtype = np.int64

    def sample(self, mask: Any = None) -> int:
        """Sample uniformly from the discrete space."""
        _ = mask
        return int(np.random.randint(self.start, self.start + self.n))

    def contains(self, x: Any) -> bool:
        """Check whether element x belongs to the discrete space."""
        if isinstance(x, int | np.integer):
            return bool(self.start <= x < self.start + self.n)
        return False

    def __repr__(self) -> str:
        return f"DiscreteSpace({self.n})"


class BoxSpace:
    """Gymnasium-compatible continuous Box space implementation."""

    def __init__(
        self,
        low: float | np.ndarray,
        high: float | np.ndarray,
        shape: tuple[int, ...],
        dtype: type = np.float32,
    ) -> None:
        """Initialize continuous bounded Box space."""
        self.shape = shape
        self.dtype = dtype
        self.low: np.ndarray
        self.high: np.ndarray
        if np.isscalar(low):
            self.low = np.full(shape, low, dtype=dtype)
        else:
            self.low = np.asarray(low, dtype=dtype)
        if np.isscalar(high):
            self.high = np.full(shape, high, dtype=dtype)
        else:
            self.high = np.asarray(high, dtype=dtype)

    def sample(self, mask: Any = None) -> np.ndarray:
        """Sample uniformly from bounded box (or standard normal for unbounded)."""
        _ = mask
        has_inf = np.isinf(self.low).any() or np.isinf(self.high).any()
        if has_inf:
            sample_arr = np.random.standard_normal(self.shape)
        else:
            sample_arr = np.random.uniform(self.low, self.high, size=self.shape)
        return cast(np.ndarray, np.asarray(sample_arr, dtype=self.dtype))

    def contains(self, x: Any) -> bool:
        """Check whether element x belongs to the Box space."""
        arr = np.asarray(x, dtype=self.dtype)
        if arr.shape != self.shape:
            return False
        return bool(np.all(arr >= self.low) and np.all(arr <= self.high))

    def __repr__(self) -> str:
        return f"BoxSpace(shape={self.shape}, dtype={self.dtype})"


class TradingEnvConfig(BaseModel):
    """Configuration options for Gymnasium Trading Environment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    initial_capital: float = Field(
        default=10_000.0,
        gt=0.0,
        description="Starting sandbox episode equity in INR (matches ₹10,000 baseline)",
    )
    window_size: int = Field(
        default=20,
        ge=2,
        description="Number of past bars per observation window",
    )
    max_steps: int = Field(
        default=500,
        ge=10,
        description="Maximum episode step horizon before truncation",
    )
    action_space_type: ActionSpaceType = Field(
        default=ActionSpaceType.DISCRETE,
        description="Action space representation (DISCRETE or CONTINUOUS)",
    )
    instrument: str = Field(
        default="NSE:NIFTY50",
        min_length=1,
        description="Target trading instrument identifier",
    )
    max_drawdown_limit: float = Field(
        default=0.15,
        gt=0.0,
        le=1.0,
        description="Max peak-to-trough drawdown fraction before forced episode termination",
    )
    slippage_bps: float = Field(
        default=2.0,
        ge=0.0,
        description="Simulated execution slippage in basis points (default 2 bps)",
    )


class TradingEnv:
    """Gymnasium-compliant simulated trading environment for RL agent experimentation.

    Enforces ADD §11 invariants:
    - Structurally lacks order submission or broker connections.
    - Action space strictly limited to AgentSignalOutput confidence and direction.
    - Zero discretion over position sizing, leverage, or risk limits.
    """

    def __init__(
        self,
        df: pd.DataFrame,
        config: TradingEnvConfig | None = None,
        reward_calculator: MultiFactorRewardCalculator | None = None,
        feature_columns: Sequence[str] | None = None,
    ) -> None:
        """Initialize TradingEnv with historical market data dataframe.

        Args:
            df: Historical OHLCV dataframe with features. Must contain 'close'.
            config: Environment configuration options.
            reward_calculator: MultiFactorRewardCalculator instance.
            feature_columns: Specific feature column names to feed to agent observation.
        """
        if df.empty or "close" not in df.columns:
            msg = "TradingEnv dataframe must be non-empty and contain a 'close' column"
            raise ValueError(msg)

        self.df = df.reset_index(drop=True)
        self.config = config or TradingEnvConfig()
        self.reward_calculator = reward_calculator or MultiFactorRewardCalculator(
            config=RewardConfig(),
            cost_model=CostModel(),
        )

        # Determine feature columns
        if feature_columns is not None:
            self.feature_columns = list(feature_columns)
        else:
            numeric_cols = self.df.select_dtypes(include=[np.number]).columns.tolist()
            self.feature_columns = [c for c in numeric_cols if c not in ("timestamp",)]

        self.num_features = len(self.feature_columns)
        if self.num_features == 0:
            msg = "TradingEnv requires at least 1 numeric feature column"
            raise ValueError(msg)

        # Build Gymnasium spaces
        self.observation_space = BoxSpace(
            low=-np.inf,
            high=np.inf,
            shape=(self.config.window_size, self.num_features),
            dtype=np.float32,
        )

        self.action_space: DiscreteSpace | BoxSpace
        if self.config.action_space_type == ActionSpaceType.DISCRETE:
            # 0: NO_VIEW, 1: LONG, 2: SHORT
            self.action_space = DiscreteSpace(n=3)
        else:
            # [-1.0, 1.0]: negative = SHORT, positive = LONG, magnitude = confidence
            self.action_space = BoxSpace(
                low=-1.0,
                high=1.0,
                shape=(1,),
                dtype=np.float32,
            )

        # Precompute features as float32 numpy array
        self._feature_data = self.df[self.feature_columns].to_numpy(dtype=np.float32)
        self._close_prices = self.df["close"].to_numpy(dtype=np.float64)
        self._n_bars = len(self.df)

        # Episode state variables
        self._current_step = 0
        self._portfolio_value = self.config.initial_capital
        self._peak_portfolio_value = self.config.initial_capital
        self._current_position: int = 0  # -1 (short), 0 (flat), 1 (long)
        self._current_shares: int = 0
        self._last_signal: AgentSignalOutput | None = None
        window = self.reward_calculator.config.rolling_window
        self._recent_returns: deque[float] = deque(maxlen=window)
        self._total_trades = 0
        self._logger = logger.bind(component="TradingEnv", instrument=self.config.instrument)

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Reset environment to initial state at start of episode.

        Args:
            seed: Optional random seed.
            options: Optional reset options dictionary.

        Returns:
            Tuple of (initial_observation, info_dictionary).
        """
        _ = options
        if seed is not None:
            np.random.seed(seed)

        self._current_step = self.config.window_size
        self._portfolio_value = self.config.initial_capital
        self._peak_portfolio_value = self.config.initial_capital
        self._current_position = 0
        self._current_shares = 0
        self._last_signal = None
        self._recent_returns.clear()
        self._total_trades = 0

        obs = self._get_observation()
        info: dict[str, Any] = {
            "step": self._current_step,
            "portfolio_value": self._portfolio_value,
            "peak_value": self._peak_portfolio_value,
            "drawdown_pct": 0.0,
            "position": self._current_position,
        }
        return obs, info

    def step(
        self,
        action: Any,
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        """Execute one step in the trading environment.

        Args:
            action: Action strictly constrained to direction and confidence.
                   Zero access to position sizing or risk parameter overrides (ADD §11).

        Returns:
            Tuple of (observation, reward, terminated, truncated, info).
        """
        if self._current_step >= self._n_bars - 1:
            # End of dataset reached
            obs = self._get_observation()
            return obs, 0.0, True, False, {"reason": "end_of_data"}

        # 1. Map action to AgentSignalOutput
        signal = self._map_action_to_signal(action)
        previous_signal = self._last_signal
        self._last_signal = signal

        current_price = float(self._close_prices[self._current_step])
        next_price = float(self._close_prices[self._current_step + 1])
        prev_portfolio_value = self._portfolio_value

        # 2. Determine target position from signal conviction
        # Note: Research RL has zero discretion over sizing; standard 1 unit / fixed notional
        target_position = 0
        if signal.direction == SignalDirection.LONG:
            target_position = 1
        elif signal.direction == SignalDirection.SHORT:
            target_position = -1

        position_changed = target_position != self._current_position

        # 3. Simulate execution costs & slippage on position change
        transaction_cost = 0.0
        slippage_cost = 0.0

        if position_changed:
            self._total_trades += 1
            # Standard simulated position units based on initial capital
            shares = max(1, int(self.config.initial_capital / current_price))
            turnover = shares * current_price

            # Brokerage & statutory charges via CostModel
            side = "BUY" if target_position > self._current_position else "SELL"
            transaction_cost = self.reward_calculator.calculate_trade_costs(
                price=current_price,
                quantity=shares,
                side=side,
            )

            # Slippage drag
            slippage_cost = turnover * (self.config.slippage_bps / 10_000.0)

            self._current_position = target_position
            self._current_shares = shares if target_position != 0 else 0

        # 4. Mark-to-market PnL on held position
        price_diff = next_price - current_price
        gross_step_pnl = float(self._current_position * self._current_shares * price_diff)
        net_step_pnl = gross_step_pnl - transaction_cost - slippage_cost

        self._portfolio_value += net_step_pnl
        self._peak_portfolio_value = max(self._peak_portfolio_value, self._portfolio_value)

        # 5. Record return fraction
        step_return_pct = net_step_pnl / max(prev_portfolio_value, 1.0)
        self._recent_returns.append(step_return_pct)

        # 6. Compute multi-factor reward
        reward_components: RewardComponents = self.reward_calculator.calculate_step_reward(
            current_portfolio_value=self._portfolio_value,
            previous_portfolio_value=prev_portfolio_value,
            peak_portfolio_value=self._peak_portfolio_value,
            transaction_cost=transaction_cost,
            slippage_cost=slippage_cost,
            current_direction=signal.direction,
            previous_direction=previous_signal.direction if previous_signal else None,
            recent_returns=list(self._recent_returns),
        )

        # 7. Advance step
        self._current_step += 1

        # 8. Check termination and truncation
        current_drawdown = reward_components.drawdown_pct
        terminated = (
            current_drawdown >= self.config.max_drawdown_limit
            or self._current_step >= self._n_bars - 1
        )
        truncated = (self._current_step - self.config.window_size) >= self.config.max_steps

        obs = self._get_observation()
        info: dict[str, Any] = {
            "step": self._current_step,
            "portfolio_value": self._portfolio_value,
            "peak_value": self._peak_portfolio_value,
            "drawdown_pct": current_drawdown,
            "position": self._current_position,
            "signal": signal.model_dump(),
            "reward_components": reward_components.model_dump(),
            "total_trades": self._total_trades,
            "net_step_pnl": net_step_pnl,
        }

        return obs, reward_components.total_reward, terminated, truncated, info

    def _map_action_to_signal(self, action: Any) -> AgentSignalOutput:
        """Map raw agent action into canonical AgentSignalOutput.

        Strictly enforces that action space specifies only direction and confidence [0, 1].
        """
        now = datetime.now(UTC)

        if self.config.action_space_type == ActionSpaceType.DISCRETE:
            act_int = int(action)
            if act_int == 1:
                return AgentSignalOutput(
                    agent_id="rl_research_agent",
                    direction=SignalDirection.LONG,
                    confidence=1.0,
                    timestamp=now,
                )
            if act_int == 2:
                return AgentSignalOutput(
                    agent_id="rl_research_agent",
                    direction=SignalDirection.SHORT,
                    confidence=1.0,
                    timestamp=now,
                )
            return AgentSignalOutput(
                agent_id="rl_research_agent",
                direction=SignalDirection.NO_VIEW,
                confidence=0.0,
                timestamp=now,
            )

        # Continuous Box action [-1.0, 1.0]
        act_val = float(np.asarray(action).ravel()[0])
        # Deadband in [-0.05, 0.05] maps to NO_VIEW
        if act_val > 0.05:
            conf = min(1.0, max(0.0, act_val))
            return AgentSignalOutput(
                agent_id="rl_research_agent",
                direction=SignalDirection.LONG,
                confidence=conf,
                timestamp=now,
            )
        if act_val < -0.05:
            conf = min(1.0, max(0.0, abs(act_val)))
            return AgentSignalOutput(
                agent_id="rl_research_agent",
                direction=SignalDirection.SHORT,
                confidence=conf,
                timestamp=now,
            )
        return AgentSignalOutput(
            agent_id="rl_research_agent",
            direction=SignalDirection.NO_VIEW,
            confidence=0.0,
            timestamp=now,
        )

    def _get_observation(self) -> np.ndarray:
        """Extract rolling historical window observation tensor."""
        start_idx = self._current_step - self.config.window_size
        end_idx = self._current_step
        window = self._feature_data[start_idx:end_idx]
        return cast(np.ndarray, np.asarray(window, dtype=np.float32))

    def render(self) -> None:
        """Render current environment state for monitoring."""
        self._logger.info(
            "render_state",
            step=self._current_step,
            portfolio_value=self._portfolio_value,
            position=self._current_position,
        )

    def close(self) -> None:
        """Close environment resources."""
        self._recent_returns.clear()

    # --- Architectural Boundary Isolation Guards ---
    def can_place_live_orders(self) -> bool:
        """Confirm RL environment structurally lacks live order execution capability."""
        return False

    def attempt_order_placement(self, *args: Any, **kwargs: Any) -> None:
        """Structurally reject order placement in RL environment."""
        _ = args, kwargs
        raise ResearchIsolationError(
            "RL TradingEnv is an offline simulation environment structurally incapable "
            "of placing live orders (TRD-ML-4, ADD §11)."
        )

    def attempt_position_mutation(self, *args: Any, **kwargs: Any) -> None:
        """Structurally reject live position mutation in RL environment."""
        _ = args, kwargs
        raise ResearchIsolationError(
            "RL TradingEnv has zero authority to mutate live positions (ADD §11)."
        )
