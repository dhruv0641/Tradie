"""Domain models for chronological data splits, walk-forward folds, and validation reports."""

from datetime import datetime
from decimal import Decimal
from typing import Any

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
