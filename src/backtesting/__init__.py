"""Backtesting, transaction cost modeling, and fill simulation subsystem (BTD v0.1, PRD FR-25)."""

from src.backtesting.cost_model import (
    CostBreakdown,
    CostModel,
    CostModelConfig,
    RoundTripCostBreakdown,
)
from src.backtesting.engine import (
    BacktestConfig,
    BacktestEngine,
    OrderIntent,
)
from src.backtesting.monte_carlo import MonteCarloSimulator
from src.backtesting.portfolio import (
    SimulatedPortfolio,
    SimulatedPosition,
)
from src.backtesting.slippage_model import (
    SlippageConfig,
    SlippageModel,
    SlippageResult,
)
from src.backtesting.splitter import ChronologicalSplitter
from src.backtesting.stress_scenarios import (
    create_covid_crash_scenario,
    create_slippage_stress_config,
    generate_feed_dropout,
    generate_gap_down_shock,
    generate_volatility_spike,
)
from src.backtesting.stress_test import StressTestRunner
from src.backtesting.walk_forward import (
    WalkForwardConfig,
    WalkForwardOptimizer,
)

__all__ = [
    "BacktestConfig",
    "BacktestEngine",
    "ChronologicalSplitter",
    "CostBreakdown",
    "CostModel",
    "CostModelConfig",
    "MonteCarloSimulator",
    "OrderIntent",
    "RoundTripCostBreakdown",
    "SimulatedPortfolio",
    "SimulatedPosition",
    "SlippageConfig",
    "SlippageModel",
    "SlippageResult",
    "StressTestRunner",
    "WalkForwardConfig",
    "WalkForwardOptimizer",
    "create_covid_crash_scenario",
    "create_slippage_stress_config",
    "generate_feed_dropout",
    "generate_gap_down_shock",
    "generate_volatility_spike",
]
