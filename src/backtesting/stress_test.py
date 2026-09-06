"""Market stress testing runner evaluating strategy survivability (BTD §8.4, RTLD §11)."""

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import structlog

from src.backtesting.cost_model import CostModelConfig
from src.backtesting.engine import BacktestConfig, BacktestEngine, OrderIntent
from src.backtesting.slippage_model import SlippageConfig
from src.backtesting.stress_scenarios import (
    create_covid_crash_scenario,
    create_slippage_stress_config,
    generate_feed_dropout,
    generate_gap_down_shock,
    generate_volatility_spike,
)
from src.domain.market_data import OHLCVCandle
from src.domain.validation import StressScenarioResult, StressTestReport

logger = structlog.get_logger(__name__)

StrategyCallback = Callable[[BacktestEngine, int, OHLCVCandle], list[OrderIntent]]
StrategyFactoryType = Callable[[dict[str, Any]], StrategyCallback]


class StressTestRunner:
    """Runner executing strategies against historical crisis fixtures and synthetic tail shocks."""

    def __init__(
        self,
        strategy_id: str = "strategy",
        *,
        initial_capital: Decimal = Decimal("10000.00"),
        cost_config: CostModelConfig | None = None,
        base_slippage_config: SlippageConfig | None = None,
        halt_threshold_pct: Decimal = Decimal("8.00"),
        kill_switch_threshold_pct: Decimal = Decimal("10.00"),
    ) -> None:
        """Initialize runner with capital and risk threshold targets.

        Args:
            strategy_id: Identifier of strategy being tested.
            initial_capital: Starting capital (₹10,000 baseline per PRD §9).
            cost_config: Transaction cost configuration.
            base_slippage_config: Normal baseline slippage settings.
            halt_threshold_pct: Drawdown percentage triggering intraday trading halt (RTLD §8).
            kill_switch_threshold_pct: Drawdown percentage triggering kill switch (RTLD §8).
        """
        self.strategy_id = strategy_id
        self.initial_capital = initial_capital
        self.cost_config = cost_config or CostModelConfig()
        self.base_slippage_config = base_slippage_config or SlippageConfig()
        self.halt_threshold_pct = halt_threshold_pct
        self.kill_switch_threshold_pct = kill_switch_threshold_pct

    def evaluate_scenario(
        self,
        scenario_name: str,
        *,
        scenario_type: str,
        description: str,
        candles: list[OHLCVCandle],
        strategy: StrategyCallback,
        slippage_config: SlippageConfig | None = None,
    ) -> StressScenarioResult:
        """Run strategy against a single stress candle series and evaluate risk impact.

        Args:
            scenario_name: Unique name for scenario.
            scenario_type: Category identifier.
            description: Narrative description.
            candles: Stressed candle dataset.
            strategy: Strategy callback.
            slippage_config: Optional custom slippage settings (e.g. 4x stress).

        Returns:
            StressScenarioResult with equity, drawdown, and breach flags.
        """
        engine = BacktestEngine(
            BacktestConfig(
                strategy_id=f"{self.strategy_id}_{scenario_name}",
                initial_capital=self.initial_capital,
                cost_config=self.cost_config,
                slippage_config=slippage_config or self.base_slippage_config,
            )
        )

        result = engine.run(candles, strategy)

        halt_breached = result.metrics.max_drawdown_pct >= self.halt_threshold_pct
        kill_switch_breached = result.metrics.max_drawdown_pct >= self.kill_switch_threshold_pct

        logger.info(
            "stress_scenario_evaluated",
            scenario_name=scenario_name,
            scenario_type=scenario_type,
            return_pct=str(result.metrics.return_pct),
            max_drawdown_pct=str(result.metrics.max_drawdown_pct),
            halt_breached=halt_breached,
            kill_switch_breached=kill_switch_breached,
        )

        return StressScenarioResult(
            scenario_name=scenario_name,
            scenario_type=scenario_type,  # type: ignore[arg-type]
            description=description,
            initial_capital=self.initial_capital,
            final_equity=result.final_equity,
            net_profit=result.metrics.net_profit,
            return_pct=result.metrics.return_pct,
            max_drawdown_pct=result.metrics.max_drawdown_pct,
            total_trades=result.metrics.total_trades,
            halt_8pct_breached=halt_breached,
            kill_switch_10pct_breached=kill_switch_breached,
        )

    def run_standard_battery(
        self,
        base_candles: list[OHLCVCandle],
        strategy: StrategyCallback,
    ) -> StressTestReport:
        """Run the comprehensive 5-stage standard stress battery.

        Battery includes:
        1. March 2020 COVID Crash shock simulation
        2. Severe 5% overnight gap-down shock
        3. 3x volatility expansion spike
        4. Broker feed dropout (blackout during trading)
        5. 4x adverse slippage / spread stress on base candles

        Args:
            base_candles: Baseline candle series (minimum 20 candles).
            strategy: Strategy callback.

        Returns:
            StressTestReport with all scenario results and overall survival status.
        """
        if len(base_candles) < 20:
            msg = (
                f"Minimum 20 candles required for standard stress battery, got {len(base_candles)}"
            )
            raise ValueError(msg)

        scenarios: list[StressScenarioResult] = []

        # 1. COVID 2020 Crash Simulation
        covid_candles = create_covid_crash_scenario(
            instrument=base_candles[0].instrument,
            start_price=base_candles[0].close,
            bars=len(base_candles),
        )
        scenarios.append(
            self.evaluate_scenario(
                scenario_name="COVID_2020_CRASH",
                scenario_type="HISTORICAL",
                description="March 2020 pandemic collapse with cascading -30% selloff",
                candles=covid_candles,
                strategy=strategy,
            )
        )

        # 2. 5% Opening Gap Down Shock
        gap_idx = len(base_candles) // 2
        gap_candles = generate_gap_down_shock(
            base_candles, gap_pct=Decimal("0.05"), bar_index=gap_idx
        )
        scenarios.append(
            self.evaluate_scenario(
                scenario_name="GAP_DOWN_5PCT",
                scenario_type="GAP_DOWN",
                description="Sudden 5% overnight opening gap-down on held positions",
                candles=gap_candles,
                strategy=strategy,
            )
        )

        # 3. 3x Volatility Spike
        vol_candles = generate_volatility_spike(
            base_candles,
            multiplier=Decimal("3.0"),
            start_idx=len(base_candles) // 3,
            end_idx=(2 * len(base_candles)) // 3,
        )
        scenarios.append(
            self.evaluate_scenario(
                scenario_name="VOLATILITY_SPIKE_3X",
                scenario_type="VOLATILITY_SPIKE",
                description="3x high-low range expansion and erratic market whip",
                candles=vol_candles,
                strategy=strategy,
            )
        )

        # 4. Broker Feed Dropout
        dropout_idx = len(base_candles) // 2
        feed_candles = generate_feed_dropout(base_candles, dropout_bars=3, start_idx=dropout_idx)
        scenarios.append(
            self.evaluate_scenario(
                scenario_name="FEED_DROPOUT_BLACKOUT",
                scenario_type="FEED_DROPOUT",
                description="Broker feed dropout with 3 missing bars during open cycle",
                candles=feed_candles,
                strategy=strategy,
            )
        )

        # 5. 4x Adverse Slippage Stress
        slippage_stress = create_slippage_stress_config(self.base_slippage_config, multiplier=4.0)
        scenarios.append(
            self.evaluate_scenario(
                scenario_name="SLIPPAGE_STRESS_4X",
                scenario_type="SLIPPAGE_STRESS",
                description="4x adverse slippage and spread widening under dried liquidity",
                candles=base_candles,
                strategy=strategy,
                slippage_config=slippage_stress,
            )
        )

        worst_dd = max(s.max_drawdown_pct for s in scenarios)
        passed = all(not s.kill_switch_10pct_breached for s in scenarios)
        summary = (
            f"Evaluated {len(scenarios)} stress scenarios. Worst drawdown: {worst_dd}%. "
            f"Kill switch breached: {not passed}."
        )

        logger.info(
            "stress_test_battery_completed",
            strategy_id=self.strategy_id,
            scenarios_count=len(scenarios),
            worst_drawdown_pct=str(worst_dd),
            passed_stress_test=passed,
        )

        return StressTestReport(
            strategy_id=self.strategy_id,
            scenarios_evaluated=scenarios,
            worst_drawdown_pct=worst_dd,
            passed_stress_test=passed,
            summary=summary,
        )
