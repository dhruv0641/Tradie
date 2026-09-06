"""Rolling walk-forward optimizer and efficiency ratio gating engine (BTD §8.3, MLD §9.2)."""

from collections.abc import Callable
from decimal import Decimal
from typing import Any, Literal

import structlog
from pydantic import BaseModel, ConfigDict, Field

from src.backtesting.cost_model import CostModelConfig
from src.backtesting.engine import BacktestConfig, BacktestEngine, OrderIntent
from src.backtesting.portfolio import SimulatedPortfolio
from src.backtesting.slippage_model import SlippageConfig
from src.backtesting.splitter import ChronologicalSplitter
from src.domain.backtest_result import BacktestMetrics
from src.domain.market_data import OHLCVCandle
from src.domain.validation import WalkForwardFold, WalkForwardReport

logger = structlog.get_logger(__name__)

StrategyCallbackType = Callable[[BacktestEngine, int, OHLCVCandle], list[OrderIntent]]
StrategyFactoryType = Callable[[dict[str, Any]], StrategyCallbackType]


class WalkForwardConfig(BaseModel):
    """Configuration settings for walk-forward evaluation run."""

    model_config = ConfigDict(frozen=True)

    strategy_id: str = "walk_forward_strategy"
    train_bars: int = Field(default=120, gt=0, description="Number of bars in in-sample window")
    test_bars: int = Field(default=20, gt=0, description="Number of bars in out-of-sample window")
    step_bars: int = Field(default=20, gt=0, description="Step size to roll forward")
    efficiency_gate_threshold: Decimal = Field(
        default=Decimal("0.50"),
        gt=Decimal("0"),
        le=Decimal("1.0"),
        description="Minimum WFER threshold to pass promotion gate (BTD-12)",
    )
    metric_key: Literal["net_profit", "return_pct", "sharpe_ratio", "profit_factor"] = "net_profit"
    initial_capital: Decimal = Field(default=Decimal("10000.00"), gt=Decimal("0"))
    cost_config: CostModelConfig = Field(default_factory=CostModelConfig)
    slippage_config: SlippageConfig = Field(default_factory=SlippageConfig)
    conservative_tie_breaking: bool = True


class WalkForwardOptimizer:
    """Rolling walk-forward evaluator assessing out-of-sample persistence and overfitting."""

    def __init__(self, config: WalkForwardConfig | None = None) -> None:
        """Initialize optimizer with configuration parameters.

        Args:
            config: WalkForwardConfig settings. Defaults to standard baseline.
        """
        self.config = config or WalkForwardConfig()

    def _extract_metric_value(self, metrics: BacktestMetrics, key: str) -> Decimal:
        """Extract evaluation metric value as Decimal."""
        if key == "net_profit":
            return metrics.net_profit
        if key == "return_pct":
            return metrics.return_pct
        if key == "profit_factor":
            return metrics.profit_factor
        if key == "sharpe_ratio":
            return metrics.sharpe_ratio or Decimal("0")
        msg = f"Unsupported metric key: {key}"
        raise ValueError(msg)

    def _calculate_efficiency_ratio(
        self,
        oos_val: Decimal,
        is_val: Decimal,
    ) -> Decimal:
        """Calculate scaled efficiency ratio between out-of-sample and in-sample metrics."""
        duration_scale = (
            Decimal(str(self.config.train_bars)) / Decimal(str(self.config.test_bars))
            if self.config.metric_key in ("net_profit", "return_pct")
            else Decimal("1.0")
        )
        if is_val > Decimal("0"):
            return ((oos_val / is_val) * duration_scale).quantize(Decimal("0.0001"))
        if oos_val > Decimal("0"):
            return Decimal("1.0000")
        return Decimal("0.0000")

    def run(
        self,
        candles: list[OHLCVCandle],
        strategy_factory: StrategyFactoryType,
        param_grid: list[dict[str, Any]] | None = None,
    ) -> WalkForwardReport:
        """Run complete rolling walk-forward optimization across chronological dataset.

        Args:
            candles: Chronological series of OHLCVCandle objects.
            strategy_factory: Factory function returning strategy callback for a parameter set.
            param_grid: Optional candidate parameter sets for in-sample tuning.

        Returns:
            WalkForwardReport containing all fold evaluations and gating decision.

        Raises:
            ValueError: If dataset is too short to construct rolling folds.
        """
        grid = param_grid if (param_grid is not None and len(param_grid) > 0) else [{}]

        # Generate sliding non-overlapping chronological folds (BTD §8.3)
        folds_data = ChronologicalSplitter.generate_rolling_windows(
            candles=candles,
            train_bars=self.config.train_bars,
            test_bars=self.config.test_bars,
            step_bars=self.config.step_bars,
        )

        evaluated_folds: list[WalkForwardFold] = []

        # Synthetic portfolio to accumulate unified out-of-sample trades
        aggregate_oos_portfolio = SimulatedPortfolio(initial_capital=self.config.initial_capital)
        aggregate_is_portfolio = SimulatedPortfolio(initial_capital=self.config.initial_capital)

        for fold_idx, (train_slice, test_slice) in enumerate(folds_data):
            logger.debug(
                "evaluating_walk_forward_fold",
                fold_idx=fold_idx,
                train_start=str(train_slice[0].timestamp),
                train_end=str(train_slice[-1].timestamp),
                test_start=str(test_slice[0].timestamp),
                test_end=str(test_slice[-1].timestamp),
            )

            # -------------------------------------------------------------
            # STEP 1: In-Sample Optimization / Evaluation
            # -------------------------------------------------------------
            best_params: dict[str, Any] = grid[0]
            best_is_metric_val = Decimal("-999999999")
            best_is_metrics: BacktestMetrics | None = None

            for params in grid:
                engine = BacktestEngine(
                    BacktestConfig(
                        strategy_id=f"{self.config.strategy_id}_fold_{fold_idx}_is",
                        initial_capital=self.config.initial_capital,
                        cost_config=self.config.cost_config,
                        slippage_config=self.config.slippage_config,
                        conservative_tie_breaking=self.config.conservative_tie_breaking,
                    )
                )
                strategy_cb = strategy_factory(params)
                is_result = engine.run(train_slice, strategy_cb)
                metric_val = self._extract_metric_value(is_result.metrics, self.config.metric_key)

                if metric_val > best_is_metric_val:
                    best_is_metric_val = metric_val
                    best_params = params
                    best_is_metrics = is_result.metrics

            assert best_is_metrics is not None

            # -------------------------------------------------------------
            # STEP 2: Out-of-Sample Evaluation on Locked Parameters
            # -------------------------------------------------------------
            oos_engine = BacktestEngine(
                BacktestConfig(
                    strategy_id=f"{self.config.strategy_id}_fold_{fold_idx}_oos",
                    initial_capital=self.config.initial_capital,
                    cost_config=self.config.cost_config,
                    slippage_config=self.config.slippage_config,
                    conservative_tie_breaking=self.config.conservative_tie_breaking,
                )
            )
            locked_cb = strategy_factory(best_params)
            oos_result = oos_engine.run(test_slice, locked_cb)
            oos_metric_val = self._extract_metric_value(oos_result.metrics, self.config.metric_key)

            # Record trades into aggregate portfolios
            for trade in oos_result.trades:
                aggregate_oos_portfolio.trades.append(trade)
            for trade in is_result.trades:
                aggregate_is_portfolio.trades.append(trade)

            # Record equity curves
            for pt in oos_result.equity_curve:
                aggregate_oos_portfolio.equity_curve.append(pt)
            for pt in is_result.equity_curve:
                aggregate_is_portfolio.equity_curve.append(pt)

            # Compute fold efficiency ratio
            fold_wfer = self._calculate_efficiency_ratio(oos_metric_val, best_is_metric_val)

            fold_record = WalkForwardFold(
                fold_index=fold_idx,
                train_start=train_slice[0].timestamp,
                train_end=train_slice[-1].timestamp,
                test_start=test_slice[0].timestamp,
                test_end=test_slice[-1].timestamp,
                in_sample_metrics=best_is_metrics,
                out_of_sample_metrics=oos_result.metrics,
                selected_parameters=best_params,
                fold_efficiency_ratio=fold_wfer,
            )
            evaluated_folds.append(fold_record)

        # -------------------------------------------------------------
        # STEP 3: Aggregate Metrics & Global WFER Computation
        # -------------------------------------------------------------
        agg_is_metrics = aggregate_is_portfolio.compute_metrics()
        agg_oos_metrics = aggregate_oos_portfolio.compute_metrics()

        agg_is_val = self._extract_metric_value(agg_is_metrics, self.config.metric_key)
        agg_oos_val = self._extract_metric_value(agg_oos_metrics, self.config.metric_key)

        global_wfer = self._calculate_efficiency_ratio(agg_oos_val, agg_is_val)

        passed_gate = global_wfer >= self.config.efficiency_gate_threshold
        overfit_flag = not passed_gate

        logger.info(
            "walk_forward_optimization_completed",
            strategy_id=self.config.strategy_id,
            total_folds=len(evaluated_folds),
            aggregate_is_metric=str(agg_is_val),
            aggregate_oos_metric=str(agg_oos_val),
            global_wfer=str(global_wfer),
            passed_gate=passed_gate,
            overfit_flag=overfit_flag,
        )

        return WalkForwardReport(
            strategy_id=self.config.strategy_id,
            folds=evaluated_folds,
            aggregate_is_metrics=agg_is_metrics,
            aggregate_oos_metrics=agg_oos_metrics,
            walk_forward_efficiency_ratio=global_wfer,
            efficiency_gate_threshold=self.config.efficiency_gate_threshold,
            passed_gate=passed_gate,
            overfit_flag=overfit_flag,
            parameters={
                "train_bars": self.config.train_bars,
                "test_bars": self.config.test_bars,
                "step_bars": self.config.step_bars,
                "metric_key": self.config.metric_key,
                "total_parameter_candidates": len(grid),
            },
        )
