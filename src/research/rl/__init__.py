"""Reinforcement learning sandboxed training modules (FRD-LEARN-9, ADD §11)."""

from src.research.rl.environment import (
    ActionSpaceType,
    TradingEnv,
    TradingEnvConfig,
)
from src.research.rl.reward import (
    MultiFactorRewardCalculator,
    RewardComponents,
    RewardConfig,
)

__all__ = [
    "ActionSpaceType",
    "MultiFactorRewardCalculator",
    "RewardComponents",
    "RewardConfig",
    "TradingEnv",
    "TradingEnvConfig",
]
