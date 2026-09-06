"""Unit tests for Reinforcement Learning sandboxed environment and multi-factor rewards.

Conforms to PRD FR-24, FRD-LEARN-9, ADD §11, and TRD-ML-4.
"""

import numpy as np
import pandas as pd
import pytest

from src.domain.agent_signal import SignalDirection
from src.research.environment import ResearchIsolationError
from src.research.rl.environment import (
    ActionSpaceType,
    BoxSpace,
    DiscreteSpace,
    TradingEnv,
    TradingEnvConfig,
)
from src.research.rl.reward import (
    MultiFactorRewardCalculator,
    RewardComponents,
    RewardConfig,
)


def _create_sample_ohlcv(n_bars: int = 100) -> pd.DataFrame:
    """Generate deterministic synthetic market data with features."""
    np.random.seed(42)
    t = np.linspace(0, 4 * np.pi, n_bars)
    prices = 100.0 + 5.0 * np.sin(t) + np.cumsum(np.random.normal(0, 0.2, n_bars))

    df = pd.DataFrame(
        {
            "open": prices * 0.999,
            "high": prices * 1.005,
            "low": prices * 0.995,
            "close": prices,
            "volume": np.random.randint(1000, 5000, n_bars),
            "feature_rsi": np.random.uniform(20, 80, n_bars),
            "feature_macd": np.random.normal(0, 1.0, n_bars),
        }
    )
    return df


class TestRewardConfig:
    """Test suite for RewardConfig validation and architectural invariants."""

    def test_valid_config(self) -> None:
        """Verify default configuration satisfies safety invariants."""
        config = RewardConfig()
        assert config.return_weight == 1.0
        assert config.drawdown_weight == 2.0
        assert config.volatility_weight == 0.5

    def test_prohibit_raw_profit_alone(self) -> None:
        """Enforce FRD-LEARN-9: reward cannot be configured as raw profit alone."""
        with pytest.raises(ValueError, match="raw profit alone is strictly prohibited"):
            RewardConfig(
                return_weight=1.0,
                drawdown_weight=0.0,
                volatility_weight=0.0,
                cost_weight=0.0,
            )


class TestMultiFactorRewardCalculator:
    """Test suite for MultiFactorRewardCalculator logic."""

    @pytest.fixture
    def calculator(self) -> MultiFactorRewardCalculator:
        return MultiFactorRewardCalculator()

    def test_positive_return_reward(self, calculator: MultiFactorRewardCalculator) -> None:
        """Verify reward calculation when trade has positive net return."""
        res = calculator.calculate_step_reward(
            current_portfolio_value=10_200.0,
            previous_portfolio_value=10_000.0,
            peak_portfolio_value=10_200.0,
            transaction_cost=10.0,
            slippage_cost=5.0,
            current_direction=SignalDirection.LONG,
            previous_direction=SignalDirection.LONG,
            recent_returns=[0.02, 0.015, 0.018, 0.02, 0.019],
        )
        assert isinstance(res, RewardComponents)
        assert res.net_return > 0.0
        assert res.drawdown_penalty == 0.0  # At all-time high
        assert res.churn_penalty == 0.0
        assert res.total_reward > 0.0

    def test_drawdown_penalty_scales_quadratically(
        self, calculator: MultiFactorRewardCalculator
    ) -> None:
        """Verify that peak-to-trough drawdown triggers quadratic penalty."""
        # 10% drawdown
        res_10 = calculator.calculate_step_reward(
            current_portfolio_value=9_000.0,
            previous_portfolio_value=9_200.0,
            peak_portfolio_value=10_000.0,
            transaction_cost=0.0,
            slippage_cost=0.0,
            current_direction=SignalDirection.LONG,
            previous_direction=SignalDirection.LONG,
            recent_returns=[-0.02, -0.01],
        )
        # 20% drawdown
        res_20 = calculator.calculate_step_reward(
            current_portfolio_value=8_000.0,
            previous_portfolio_value=8_200.0,
            peak_portfolio_value=10_000.0,
            transaction_cost=0.0,
            slippage_cost=0.0,
            current_direction=SignalDirection.LONG,
            previous_direction=SignalDirection.LONG,
            recent_returns=[-0.02, -0.01],
        )
        assert res_10.drawdown_pct == pytest.approx(0.10)
        assert res_20.drawdown_pct == pytest.approx(0.20)
        # 20% drawdown squared is 4x that of 10% drawdown
        assert res_20.drawdown_penalty == pytest.approx(res_10.drawdown_penalty * 4, rel=1e-2)

    def test_churn_penalty_on_direction_flip(self, calculator: MultiFactorRewardCalculator) -> None:
        """Verify churn penalty is assessed when flipping from LONG to SHORT."""
        res_churn = calculator.calculate_step_reward(
            current_portfolio_value=10_000.0,
            previous_portfolio_value=10_000.0,
            peak_portfolio_value=10_000.0,
            transaction_cost=5.0,
            slippage_cost=2.0,
            current_direction=SignalDirection.SHORT,
            previous_direction=SignalDirection.LONG,
            recent_returns=[0.0, 0.0],
        )
        assert res_churn.churn_penalty > 0.0

    def test_trade_cost_calculation(self, calculator: MultiFactorRewardCalculator) -> None:
        """Verify transaction cost calculation via CostModel."""
        cost = calculator.calculate_trade_costs(price=100.0, quantity=10, side="BUY")
        assert cost > 0.0

        # Zero quantity costs zero
        assert calculator.calculate_trade_costs(price=100.0, quantity=0, side="BUY") == 0.0


class TestSpaces:
    """Test suite for Gymnasium-compatible space implementations."""

    def test_discrete_space(self) -> None:
        space = DiscreteSpace(n=3)
        assert space.contains(0)
        assert space.contains(2)
        assert not space.contains(3)
        assert not space.contains("invalid")

        sampled = space.sample()
        assert 0 <= sampled < 3
        assert "DiscreteSpace" in repr(space)

    def test_box_space(self) -> None:
        space = BoxSpace(low=-1.0, high=1.0, shape=(2, 3), dtype=np.float32)
        assert space.contains(np.zeros((2, 3), dtype=np.float32))
        assert not space.contains(np.full((2, 3), 2.0, dtype=np.float32))
        assert not space.contains(np.zeros((1, 3), dtype=np.float32))

        sample = space.sample()
        assert sample.shape == (2, 3)
        assert "BoxSpace" in repr(space)

    def test_unbounded_box_space_sample(self) -> None:
        space = BoxSpace(low=-np.inf, high=np.inf, shape=(4,), dtype=np.float32)
        sample = space.sample()
        assert sample.shape == (4,)


class TestTradingEnv:
    """Test suite for TradingEnv lifecycle and boundary enforcement."""

    def test_invalid_dataframe_raises(self) -> None:
        """Verify environment requires non-empty dataframe with 'close' column."""
        with pytest.raises(ValueError, match="TradingEnv dataframe must be non-empty"):
            TradingEnv(pd.DataFrame())

        with pytest.raises(ValueError, match="contain a 'close' column"):
            TradingEnv(pd.DataFrame({"open": [10.0, 11.0]}))

    def test_empty_numeric_features_raises(self) -> None:
        """Verify environment requires numeric feature columns."""
        df = pd.DataFrame({"close": [10.0, 11.0], "timestamp": ["t1", "t2"]})
        with pytest.raises(ValueError, match="requires at least 1 numeric feature"):
            TradingEnv(df, feature_columns=[])

    def test_discrete_env_lifecycle(self) -> None:
        """Verify complete reset and step cycle in discrete mode."""
        df = _create_sample_ohlcv(50)
        config = TradingEnvConfig(window_size=5, max_steps=20)
        env = TradingEnv(df, config=config)

        obs, info = env.reset(seed=123)
        assert obs.shape == (5, 7)  # 5 bars window, 7 numeric columns
        assert info["step"] == 5
        assert info["portfolio_value"] == 10_000.0

        # Step 0: NO_VIEW
        obs, _reward0, term, trunc, step_info = env.step(0)
        assert not term
        assert not trunc
        assert step_info["position"] == 0

        # Step 1: LONG
        obs, _reward, term, trunc, step_info = env.step(1)
        assert step_info["position"] == 1
        assert step_info["total_trades"] == 1

        # Step 2: SHORT
        obs, _reward2, term, trunc, step_info = env.step(2)
        assert step_info["position"] == -1
        assert step_info["total_trades"] == 2

        env.render()
        env.close()

    def test_continuous_env_lifecycle(self) -> None:
        """Verify complete step cycle with continuous Box actions."""
        df = _create_sample_ohlcv(50)
        config = TradingEnvConfig(
            window_size=5,
            max_steps=20,
            action_space_type=ActionSpaceType.CONTINUOUS,
        )
        env = TradingEnv(df, config=config)

        _obs0, _ = env.reset()
        # High positive conviction -> LONG
        _o1, _r1, _t1, _tr1, step_info = env.step(np.array([0.85]))
        assert step_info["signal"]["direction"] == "LONG"
        assert step_info["signal"]["confidence"] == pytest.approx(0.85)

        # High negative conviction -> SHORT
        _o2, _r2, _t2, _tr2, step_info = env.step(np.array([-0.90]))
        assert step_info["signal"]["direction"] == "SHORT"
        assert step_info["signal"]["confidence"] == pytest.approx(0.90)

        # Near-zero conviction -> NO_VIEW
        _obs, _reward, _term, _trunc, step_info = env.step(np.array([0.02]))
        assert step_info["signal"]["direction"] == "NO_VIEW"
        assert step_info["signal"]["confidence"] == 0.0

    def test_drawdown_early_termination(self) -> None:
        """Verify environment early terminates when max drawdown limit is exceeded."""
        # Create collapsing price trajectory
        n_bars = 40
        collapsing_prices = np.linspace(100.0, 50.0, n_bars)
        df = pd.DataFrame(
            {
                "close": collapsing_prices,
                "feature_1": np.ones(n_bars),
            }
        )
        config = TradingEnvConfig(
            window_size=5,
            max_steps=50,
            max_drawdown_limit=0.10,  # 10% limit
        )
        env = TradingEnv(df, config=config)
        env.reset()

        terminated = False
        for _ in range(15):
            _, _, term, _, _ = env.step(1)  # Buy collapsing asset
            if term:
                terminated = True
                break

        assert terminated

    def test_architectural_boundary_isolation(self) -> None:
        """Verify RL environment structurally lacks order placement capabilities (ADD §11)."""
        df = _create_sample_ohlcv(30)
        env = TradingEnv(df)

        assert not env.can_place_live_orders()

        with pytest.raises(ResearchIsolationError, match="incapable of placing live orders"):
            env.attempt_order_placement(symbol="SBIN", quantity=10)

        with pytest.raises(ResearchIsolationError, match="zero authority to mutate live"):
            env.attempt_position_mutation(symbol="SBIN", position=0)
