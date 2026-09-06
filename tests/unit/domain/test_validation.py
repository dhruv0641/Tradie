"""Unit tests for ChronologicalSplit, WalkForwardFold, and WalkForwardReport domain models."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.domain.backtest_result import BacktestMetrics
from src.domain.market_data import OHLCVCandle
from src.domain.validation import (
    ChronologicalSplit,
    WalkForwardFold,
    WalkForwardReport,
)


def _make_candle(idx: int) -> OHLCVCandle:
    t = datetime(2026, 1, 1, 9, 15, tzinfo=UTC) + timedelta(minutes=15 * idx)
    return OHLCVCandle(
        instrument="TCS",
        timeframe="15m",
        timestamp=t,
        open=Decimal("100.00"),
        high=Decimal("105.00"),
        low=Decimal("99.00"),
        close=Decimal("102.00"),
        volume=1000,
        turnover=Decimal("102000.00"),
    )


def _make_metrics(profit: Decimal = Decimal("100.00")) -> BacktestMetrics:
    return BacktestMetrics(
        total_trades=5,
        winning_trades=4,
        losing_trades=1,
        win_rate=Decimal("80.00"),
        profit_factor=Decimal("3.00"),
        gross_profit=Decimal("150.00"),
        gross_loss=Decimal("50.00"),
        total_costs=Decimal("10.00"),
        net_profit=profit,
        return_pct=Decimal("1.00"),
        max_drawdown_pct=Decimal("2.00"),
    )


def test_chronological_split_success() -> None:
    """Verify ChronologicalSplit creation with valid strictly chronological ranges."""
    c0 = _make_candle(0)
    c1 = _make_candle(1)

    split = ChronologicalSplit(
        train_candles=[c0],
        test_candles=[c1],
        train_range=(c0.timestamp, c0.timestamp),
        test_range=(c1.timestamp, c1.timestamp),
    )
    assert len(split.train_candles) == 1
    assert len(split.test_candles) == 1
    assert split.train_range[1] < split.test_range[0]


def test_chronological_split_validations() -> None:
    """Verify boundary leakage guards and UTC timestamp requirements."""
    c0 = _make_candle(0)
    c1 = _make_candle(1)

    # Naive timestamp in tuple (start naive or end naive)
    naive_t = datetime(2026, 1, 1, 9, 15)
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        ChronologicalSplit(
            train_candles=[c0],
            test_candles=[c1],
            train_range=(naive_t, c0.timestamp),
            test_range=(c1.timestamp, c1.timestamp),
        )

    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        ChronologicalSplit(
            train_candles=[c0],
            test_candles=[c1],
            train_range=(c0.timestamp, naive_t),
            test_range=(c1.timestamp, c1.timestamp),
        )

    # Start after end in range
    with pytest.raises(ValidationError, match="cannot be after end"):
        ChronologicalSplit(
            train_candles=[c0],
            test_candles=[c1],
            train_range=(c1.timestamp, c0.timestamp),
            test_range=(c1.timestamp, c1.timestamp),
        )

    # Train end >= Test start (overlap leakage)
    with pytest.raises(ValidationError, match="must be strictly before"):
        ChronologicalSplit(
            train_candles=[c0],
            test_candles=[c1],
            train_range=(c0.timestamp, c1.timestamp),
            test_range=(c1.timestamp, c1.timestamp),
        )


def test_chronological_split_with_validation_range() -> None:
    """Verify ChronologicalSplit with val_range and its boundary checks."""
    c0 = _make_candle(0)
    c1 = _make_candle(1)
    c2 = _make_candle(2)

    # Valid 3-way split
    split = ChronologicalSplit(
        train_candles=[c0],
        val_candles=[c1],
        test_candles=[c2],
        train_range=(c0.timestamp, c0.timestamp),
        val_range=(c1.timestamp, c1.timestamp),
        test_range=(c2.timestamp, c2.timestamp),
    )
    assert len(split.val_candles) == 1
    assert split.val_range is not None

    # Train end >= val start
    with pytest.raises(ValidationError, match="must be strictly before validation start"):
        ChronologicalSplit(
            train_candles=[c0],
            val_candles=[c1],
            test_candles=[c2],
            train_range=(c0.timestamp, c1.timestamp),
            val_range=(c1.timestamp, c1.timestamp),
            test_range=(c2.timestamp, c2.timestamp),
        )

    # Val end >= test start
    with pytest.raises(ValidationError, match="must be strictly before test start"):
        ChronologicalSplit(
            train_candles=[c0],
            val_candles=[c1],
            test_candles=[c2],
            train_range=(c0.timestamp, c0.timestamp),
            val_range=(c1.timestamp, c2.timestamp),
            test_range=(c2.timestamp, c2.timestamp),
        )

    # Naive timestamp in val_range
    naive_t = datetime(2026, 1, 1, 9, 15)
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        ChronologicalSplit(
            train_candles=[c0],
            val_candles=[c1],
            test_candles=[c2],
            train_range=(c0.timestamp, c0.timestamp),
            val_range=(naive_t, c1.timestamp),
            test_range=(c2.timestamp, c2.timestamp),
        )


def test_walk_forward_fold_success_and_validations() -> None:
    """Verify WalkForwardFold creation and window boundary validation."""
    t0 = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 1, 15, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 16, 0, 0, tzinfo=UTC)
    t3 = datetime(2026, 1, 31, 0, 0, tzinfo=UTC)

    fold = WalkForwardFold(
        fold_index=0,
        train_start=t0,
        train_end=t1,
        test_start=t2,
        test_end=t3,
        in_sample_metrics=_make_metrics(Decimal("200.00")),
        out_of_sample_metrics=_make_metrics(Decimal("150.00")),
        selected_parameters={"period": 14},
        fold_efficiency_ratio=Decimal("0.75"),
    )
    assert fold.fold_index == 0
    assert fold.fold_efficiency_ratio == Decimal("0.75")

    # Naive timestamp
    naive_t = datetime(2026, 1, 1, 0, 0)
    with pytest.raises(ValidationError, match="must be timezone-aware UTC"):
        WalkForwardFold(
            fold_index=0,
            train_start=naive_t,
            train_end=t1,
            test_start=t2,
            test_end=t3,
            in_sample_metrics=_make_metrics(),
            out_of_sample_metrics=_make_metrics(),
            fold_efficiency_ratio=Decimal("0.50"),
        )

    # Train start > train end
    with pytest.raises(ValidationError, match="cannot be after train end"):
        WalkForwardFold(
            fold_index=0,
            train_start=t1,
            train_end=t0,
            test_start=t2,
            test_end=t3,
            in_sample_metrics=_make_metrics(),
            out_of_sample_metrics=_make_metrics(),
            fold_efficiency_ratio=Decimal("0.50"),
        )

    # Test start > test end
    with pytest.raises(ValidationError, match="cannot be after test end"):
        WalkForwardFold(
            fold_index=0,
            train_start=t0,
            train_end=t1,
            test_start=t3,
            test_end=t2,
            in_sample_metrics=_make_metrics(),
            out_of_sample_metrics=_make_metrics(),
            fold_efficiency_ratio=Decimal("0.50"),
        )

    # Overlapping train end and test start
    with pytest.raises(ValidationError, match="must precede test window start"):
        WalkForwardFold(
            fold_index=0,
            train_start=t0,
            train_end=t2,
            test_start=t1,  # t1 < t2!
            test_end=t3,
            in_sample_metrics=_make_metrics(),
            out_of_sample_metrics=_make_metrics(),
            fold_efficiency_ratio=Decimal("0.50"),
        )


def test_walk_forward_report_creation() -> None:
    """Verify WalkForwardReport domain entity creation."""
    t0 = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 1, 15, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 16, 0, 0, tzinfo=UTC)
    t3 = datetime(2026, 1, 31, 0, 0, tzinfo=UTC)

    fold = WalkForwardFold(
        fold_index=0,
        train_start=t0,
        train_end=t1,
        test_start=t2,
        test_end=t3,
        in_sample_metrics=_make_metrics(Decimal("200.00")),
        out_of_sample_metrics=_make_metrics(Decimal("150.00")),
        fold_efficiency_ratio=Decimal("0.75"),
    )

    report = WalkForwardReport(
        strategy_id="momentum_strategy",
        folds=[fold],
        aggregate_is_metrics=_make_metrics(Decimal("200.00")),
        aggregate_oos_metrics=_make_metrics(Decimal("150.00")),
        walk_forward_efficiency_ratio=Decimal("0.75"),
        efficiency_gate_threshold=Decimal("0.50"),
        passed_gate=True,
        overfit_flag=False,
    )
    assert report.strategy_id == "momentum_strategy"
    assert report.passed_gate is True
    assert report.overfit_flag is False
