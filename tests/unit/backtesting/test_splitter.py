"""Unit tests for ChronologicalSplitter (BTD §5.4, §8.2)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.backtesting.splitter import ChronologicalSplitter
from src.domain.market_data import OHLCVCandle


def _generate_candles(count: int) -> list[OHLCVCandle]:
    base = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    candles = []
    for i in range(count):
        t = base + timedelta(minutes=15 * i)
        c = OHLCVCandle(
            instrument="TCS",
            timeframe="15m",
            timestamp=t,
            open=Decimal("100.00"),
            high=Decimal("105.00"),
            low=Decimal("98.00"),
            close=Decimal("101.00"),
            volume=1000,
            turnover=Decimal("101000.00"),
        )
        candles.append(c)
    return candles


def test_split_in_out_of_sample_default() -> None:
    """Verify default 70% In-Sample / 30% Out-of-Sample split (BTD-10)."""
    candles = _generate_candles(10)
    split = ChronologicalSplitter.split_in_out_of_sample(candles, in_sample_ratio=0.7)

    assert len(split.train_candles) == 7
    assert len(split.test_candles) == 3
    assert split.train_candles[-1].timestamp < split.test_candles[0].timestamp
    assert split.train_range == (candles[0].timestamp, candles[6].timestamp)
    assert split.test_range == (candles[7].timestamp, candles[9].timestamp)


def test_split_in_out_of_sample_custom_ratio() -> None:
    """Verify custom in-sample ratio partitioning."""
    candles = _generate_candles(10)
    split = ChronologicalSplitter.split_in_out_of_sample(candles, in_sample_ratio=0.8)

    assert len(split.train_candles) == 8
    assert len(split.test_candles) == 2
    assert split.train_candles[-1].timestamp < split.test_candles[0].timestamp


def test_split_in_out_of_sample_validations() -> None:
    """Verify ratio boundary and candle count guards."""
    candles = _generate_candles(10)

    # Invalid ratios
    with pytest.raises(ValueError, match=r"strictly between 0\.0 and 1\.0"):
        ChronologicalSplitter.split_in_out_of_sample(candles, in_sample_ratio=0.0)

    with pytest.raises(ValueError, match=r"strictly between 0\.0 and 1\.0"):
        ChronologicalSplitter.split_in_out_of_sample(candles, in_sample_ratio=1.0)

    # Empty candles
    with pytest.raises(ValueError, match="cannot be empty"):
        ChronologicalSplitter.split_in_out_of_sample([], in_sample_ratio=0.7)

    # Single candle
    single_candle = _generate_candles(1)
    with pytest.raises(ValueError, match="Minimum 2 candles"):
        ChronologicalSplitter.split_in_out_of_sample(single_candle, in_sample_ratio=0.7)


def test_split_train_val_test_success() -> None:
    """Verify 3-way chronological partitioning with zero date overlap."""
    candles = _generate_candles(10)
    split = ChronologicalSplitter.split_train_val_test(
        candles, train_ratio=0.6, val_ratio=0.2, test_ratio=0.2
    )

    assert len(split.train_candles) == 6
    assert len(split.val_candles) == 2
    assert len(split.test_candles) == 2
    assert split.val_range is not None

    assert split.train_range[1] < split.val_range[0]
    assert split.val_range[1] < split.test_range[0]


def test_split_train_val_test_validations() -> None:
    """Verify 3-way partition ratio validation and short sequence rejection."""
    candles = _generate_candles(10)

    # Ratios not summing to 1.0
    with pytest.raises(ValueError, match=r"must sum to 1\.0"):
        ChronologicalSplitter.split_train_val_test(
            candles, train_ratio=0.5, val_ratio=0.2, test_ratio=0.2
        )

    # Non-positive ratio
    with pytest.raises(ValueError, match="strictly positive"):
        ChronologicalSplitter.split_train_val_test(
            candles, train_ratio=0.8, val_ratio=0.2, test_ratio=0.0
        )

    # Too short
    short_candles = _generate_candles(2)
    with pytest.raises(ValueError, match="Minimum 3 candles"):
        ChronologicalSplitter.split_train_val_test(
            short_candles, train_ratio=0.6, val_ratio=0.2, test_ratio=0.2
        )


def test_generate_rolling_windows() -> None:
    """Verify sliding chronological rolling window generation for walk-forward."""
    candles = _generate_candles(10)
    # 10 candles, train=4, test=2, step=2 -> folds at 0, 2, 4
    folds = ChronologicalSplitter.generate_rolling_windows(
        candles=candles, train_bars=4, test_bars=2, step_bars=2
    )

    assert len(folds) == 3
    # Fold 0
    assert len(folds[0][0]) == 4
    assert len(folds[0][1]) == 2
    assert folds[0][0][-1].timestamp < folds[0][1][0].timestamp

    # Fold 1
    assert folds[1][0][0].timestamp == candles[2].timestamp
    assert folds[1][1][-1].timestamp == candles[7].timestamp

    # Fold 2
    assert folds[2][0][0].timestamp == candles[4].timestamp
    assert folds[2][1][-1].timestamp == candles[9].timestamp


def test_generate_rolling_windows_validations() -> None:
    """Verify rolling window parameter guards."""
    candles = _generate_candles(10)

    with pytest.raises(ValueError, match="strictly positive"):
        ChronologicalSplitter.generate_rolling_windows(
            candles, train_bars=0, test_bars=2, step_bars=2
        )

    with pytest.raises(ValueError, match="strictly positive"):
        ChronologicalSplitter.generate_rolling_windows(
            candles, train_bars=4, test_bars=-1, step_bars=2
        )

    with pytest.raises(ValueError, match="strictly positive"):
        ChronologicalSplitter.generate_rolling_windows(
            candles, train_bars=4, test_bars=2, step_bars=0
        )

    # Dataset smaller than window
    with pytest.raises(ValueError, match="Insufficient candles"):
        ChronologicalSplitter.generate_rolling_windows(
            candles, train_bars=8, test_bars=5, step_bars=1
        )


def test_non_chronological_sequence_rejected() -> None:
    """Verify non-monotonic timestamp regressions are blocked."""
    c0 = _generate_candles(1)[0]
    c1_stale = _generate_candles(1)[0]  # Same timestamp!

    with pytest.raises(ValueError, match="Non-chronological candles"):
        ChronologicalSplitter.split_in_out_of_sample([c0, c1_stale])
