"""Domain models for chronological data splits, walk-forward folds, and validation reports."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.domain.backtest_result import BacktestMetrics
from src.domain.market_data import OHLCVCandle


class ChronologicalSplit(BaseModel):
    """Container for strictly chronological time-series data partitions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    train_candles: list[OHLCVCandle] = Field(min_length=1, description="In-sample training candles")
    test_candles: list[OHLCVCandle] = Field(
        min_length=1, description="Out-of-sample testing candles"
    )
    val_candles: list[OHLCVCandle] = Field(
        default_factory=list, description="Optional validation candles"
    )
    train_range: tuple[datetime, datetime] = Field(
        description="UTC (min, max) timestamps of training partition"
    )
    test_range: tuple[datetime, datetime] = Field(
        description="UTC (min, max) timestamps of testing partition"
    )
    val_range: tuple[datetime, datetime] | None = Field(
        default=None, description="UTC (min, max) timestamps of validation partition"
    )

    @field_validator("train_range", "test_range", "val_range")
    @classmethod
    def validate_utc_tuple(
        cls, v: tuple[datetime, datetime] | None
    ) -> tuple[datetime, datetime] | None:
        """Verify timezone-aware UTC timestamps in range tuple."""
        if v is None:
            return None
        if v[0].tzinfo is None or v[1].tzinfo is None:
            msg = "Partition timestamps must be timezone-aware UTC"
            raise ValueError(msg)
        if v[0] > v[1]:
            msg = f"Partition start timestamp {v[0]} cannot be after end {v[1]}"
            raise ValueError(msg)
        return v

    @model_validator(mode="after")
    def validate_chronological_boundaries(self) -> "ChronologicalSplit":
        """Structurally enforce zero lookahead leakage across partition boundaries."""
        if self.val_range is not None:
            if self.train_range[1] >= self.val_range[0]:
                msg = (
                    f"Train partition end ({self.train_range[1]}) must be strictly before "
                    f"validation start ({self.val_range[0]})"
                )
                raise ValueError(msg)
            if self.val_range[1] >= self.test_range[0]:
                msg = (
                    f"Validation partition end ({self.val_range[1]}) must be strictly before "
                    f"test start ({self.test_range[0]})"
                )
                raise ValueError(msg)
        elif self.train_range[1] >= self.test_range[0]:
            msg = (
                f"Train partition end ({self.train_range[1]}) must be strictly before "
                f"test start ({self.test_range[0]})"
            )
            raise ValueError(msg)
        return self


class WalkForwardFold(BaseModel):
    """Single rolling-window evaluation fold in a walk-forward optimization run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fold_index: int = Field(ge=0, description="0-indexed fold number")
    train_start: datetime = Field(description="In-sample training start UTC")
    train_end: datetime = Field(description="In-sample training end UTC")
    test_start: datetime = Field(description="Out-of-sample testing start UTC")
    test_end: datetime = Field(description="Out-of-sample testing end UTC")
    in_sample_metrics: BacktestMetrics = Field(description="Performance metrics on training window")
    out_of_sample_metrics: BacktestMetrics = Field(
        description="Performance metrics on unseen test window"
    )
    selected_parameters: dict[str, Any] = Field(
        default_factory=dict, description="Locked parameters chosen in-sample"
    )
    fold_efficiency_ratio: Decimal = Field(
        description="Ratio of out-of-sample to in-sample performance"
    )

    @field_validator("train_start", "train_end", "test_start", "test_end")
    @classmethod
    def validate_utc(cls, v: datetime) -> datetime:
        """Enforce timezone-aware UTC timestamp."""
        if v.tzinfo is None:
            msg = "Timestamp must be timezone-aware UTC"
            raise ValueError(msg)
        return v

    @model_validator(mode="after")
    def validate_fold_boundaries(self) -> "WalkForwardFold":
        """Enforce that fold train window strictly precedes test window."""
        if self.train_start > self.train_end:
            msg = f"Train start {self.train_start} cannot be after train end {self.train_end}"
            raise ValueError(msg)
        if self.test_start > self.test_end:
            msg = f"Test start {self.test_start} cannot be after test end {self.test_end}"
            raise ValueError(msg)
        if self.train_end >= self.test_start:
            msg = (
                f"Train window end ({self.train_end}) must precede "
                f"test window start ({self.test_start})"
            )
            raise ValueError(msg)
        return self


class WalkForwardReport(BaseModel):
    """Consolidated report across all walk-forward folds with gating assessment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_id: str = Field(min_length=1, description="Strategy identifier")
    folds: list[WalkForwardFold] = Field(
        min_length=1, description="List of evaluated rolling folds"
    )
    aggregate_is_metrics: BacktestMetrics = Field(
        description="Aggregated in-sample metrics across all folds"
    )
    aggregate_oos_metrics: BacktestMetrics = Field(
        description="Aggregated out-of-sample metrics across all folds"
    )
    walk_forward_efficiency_ratio: Decimal = Field(
        description="Global Walk-Forward Efficiency Ratio (WFER = Aggregate OOS / Aggregate IS)"
    )
    efficiency_gate_threshold: Decimal = Field(
        default=Decimal("0.50"),
        description="Minimum WFER threshold required to pass validation gate (BTD-12)",
    )
    passed_gate: bool = Field(
        description="Whether strategy achieved WFER >= efficiency_gate_threshold"
    )
    overfit_flag: bool = Field(
        description="True if strategy failed gate indicating probable in-sample overfitting"
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict, description="Configuration parameters for walk-forward run"
    )


StressScenarioType = Literal[
    "HISTORICAL",
    "GAP_DOWN",
    "VOLATILITY_SPIKE",
    "FEED_DROPOUT",
    "SLIPPAGE_STRESS",
]


class StressScenarioResult(BaseModel):
    """Execution metrics and drawdown impact of a single stress scenario run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario_name: str = Field(min_length=1, description="Unique scenario identifier")
    scenario_type: StressScenarioType = Field(description="Category of stress test")
    description: str = Field(description="Summary of simulated shock conditions")
    initial_capital: Decimal = Field(gt=Decimal("0"), description="Starting capital in INR")
    final_equity: Decimal = Field(description="Ending equity after stress period in INR")
    net_profit: Decimal = Field(description="Net profit or loss in INR")
    return_pct: Decimal = Field(description="Total percentage return during stress")
    max_drawdown_pct: Decimal = Field(
        ge=Decimal("0"), description="Peak-to-trough max drawdown percentage"
    )
    total_trades: int = Field(ge=0, description="Total trades executed during stress")
    halt_8pct_breached: bool = Field(
        description="Whether max drawdown reached or exceeded 8% intraday halt tier"
    )
    kill_switch_10pct_breached: bool = Field(
        description="Whether max drawdown reached or exceeded 10% kill switch ceiling"
    )


class StressTestReport(BaseModel):
    """Consolidated report across all historical and synthetic stress scenarios."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_id: str = Field(min_length=1, description="Evaluated strategy identifier")
    scenarios_evaluated: list[StressScenarioResult] = Field(
        min_length=1, description="List of scenario evaluation outcomes"
    )
    worst_drawdown_pct: Decimal = Field(
        ge=Decimal("0"), description="Worst drawdown encountered across all stress scenarios"
    )
    passed_stress_test: bool = Field(
        description="True if strategy survived all scenarios without breaching 10% kill switch"
    )
    summary: str = Field(
        default="", description="High-level narrative summary of stress resilience"
    )


class MonteCarloSimulationResult(BaseModel):
    """Statistical distribution of equity and drawdowns from bootstrap trade sequence resampling."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    simulation_count: int = Field(
        ge=100, description="Number of bootstrap resample iterations (>= 1,000 per BTD-13)"
    )
    initial_capital: Decimal = Field(gt=Decimal("0"), description="Starting capital in INR")
    trade_count: int = Field(ge=0, description="Number of realized trades resampled per path")
    seed: int | None = Field(default=None, description="PRNG seed for deterministic execution")
    equity_p5: Decimal = Field(description="5th percentile final equity (pessimistic)")
    equity_p50: Decimal = Field(description="50th percentile (median) final equity")
    equity_p95: Decimal = Field(description="95th percentile final equity (optimistic)")
    max_drawdown_p5: Decimal = Field(description="5th percentile max drawdown percentage")
    max_drawdown_p50: Decimal = Field(description="50th percentile max drawdown percentage")
    max_drawdown_p95: Decimal = Field(description="95th percentile max drawdown percentage")
    worst_case_drawdown: Decimal = Field(
        description="Worst-case drawdown across all resampled paths"
    )
    prob_drawdown_halt_8pct: Decimal = Field(
        ge=Decimal("0"),
        le=Decimal("1"),
        description="Estimated probability of touching 8% drawdown halt tier",
    )
    prob_kill_switch_10pct: Decimal = Field(
        ge=Decimal("0"),
        le=Decimal("1"),
        description="Estimated probability of touching 10% extreme-loss kill switch",
    )
    prob_ruin: Decimal = Field(
        ge=Decimal("0"),
        le=Decimal("1"),
        description="Estimated probability of equity dropping to zero or below",
    )
    sample_equity_curves: list[list[Decimal]] = Field(
        default_factory=list, description="Representative sample of simulated equity trajectories"
    )
