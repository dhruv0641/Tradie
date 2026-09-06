"""Chronological time-series data partitioner eliminating look-ahead bias (BTD §5.4, §8.2)."""

from decimal import Decimal

import structlog

from src.domain.market_data import OHLCVCandle
from src.domain.validation import ChronologicalSplit

logger = structlog.get_logger(__name__)


class ChronologicalSplitter:
    """Chronological time-series data partitioner enforcing strict zero-leakage splits."""

    @staticmethod
    def _validate_candle_sequence(candles: list[OHLCVCandle]) -> None:
        """Verify non-empty strictly chronological sequence with zero timestamp regressions."""
        if not candles:
            msg = "Candle sequence cannot be empty"
            raise ValueError(msg)
        for i in range(1, len(candles)):
            if candles[i].timestamp <= candles[i - 1].timestamp:
                msg = (
                    f"Non-chronological candles detected at index {i}: "
                    f"timestamp {candles[i].timestamp} <= previous {candles[i - 1].timestamp}"
                )
                raise ValueError(msg)

    @classmethod
    def split_in_out_of_sample(
        cls,
        candles: list[OHLCVCandle],
        in_sample_ratio: float = 0.7,
    ) -> ChronologicalSplit:
        """Partition candles chronologically into In-Sample (train) and Out-of-Sample (test).

        Standard default is 70% In-Sample / 30% Out-of-Sample per BTD §8.2 (BTD-10).

        Args:
            candles: Chronological series of OHLCVCandle objects.
            in_sample_ratio: Fraction of series reserved for in-sample training (0.0 to 1.0).

        Returns:
            ChronologicalSplit domain entity.

        Raises:
            ValueError: If ratio is invalid, candles are non-chronological, or series is too short.
        """
        if not (0.0 < in_sample_ratio < 1.0):
            msg = f"in_sample_ratio must be strictly between 0.0 and 1.0, got {in_sample_ratio}"
            raise ValueError(msg)

        cls._validate_candle_sequence(candles)

        if len(candles) < 2:
            msg = f"Minimum 2 candles required for in/out-of-sample split, got {len(candles)}"
            raise ValueError(msg)

        split_idx = int(len(candles) * in_sample_ratio)
        # Ensure at least 1 candle in both partitions
        split_idx = max(1, min(split_idx, len(candles) - 1))

        train_candles = candles[:split_idx]
        test_candles = candles[split_idx:]

        # Structural invariant assertion
        if train_candles[-1].timestamp >= test_candles[0].timestamp:
            msg = (
                f"Lookahead leak detected: Train max timestamp ({train_candles[-1].timestamp}) "
                f">= Test min timestamp ({test_candles[0].timestamp})"
            )
            raise RuntimeError(msg)

        logger.info(
            "chronological_split_completed",
            total_candles=len(candles),
            train_candles=len(train_candles),
            test_candles=len(test_candles),
            train_end=str(train_candles[-1].timestamp),
            test_start=str(test_candles[0].timestamp),
        )

        return ChronologicalSplit(
            train_candles=train_candles,
            test_candles=test_candles,
            train_range=(train_candles[0].timestamp, train_candles[-1].timestamp),
            test_range=(test_candles[0].timestamp, test_candles[-1].timestamp),
        )

    @classmethod
    def split_train_val_test(
        cls,
        candles: list[OHLCVCandle],
        train_ratio: float = 0.6,
        val_ratio: float = 0.2,
        test_ratio: float = 0.2,
    ) -> ChronologicalSplit:
        """Partition candles into three strictly chronological non-overlapping windows.

        Args:
            candles: Chronological series of OHLCVCandle objects.
            train_ratio: Fraction for training window.
            val_ratio: Fraction for validation window.
            test_ratio: Fraction for out-of-sample test window.

        Returns:
            ChronologicalSplit entity with train, validation, and test partitions.

        Raises:
            ValueError: If ratios do not sum to 1.0 or series is too short.
        """
        if train_ratio <= 0 or val_ratio <= 0 or test_ratio <= 0:
            msg = "All partition ratios must be strictly positive"
            raise ValueError(msg)

        ratio_sum = Decimal(str(train_ratio)) + Decimal(str(val_ratio)) + Decimal(str(test_ratio))
        if abs(ratio_sum - Decimal("1.0")) > Decimal("0.001"):
            msg = f"Partition ratios must sum to 1.0, got {ratio_sum}"
            raise ValueError(msg)

        cls._validate_candle_sequence(candles)

        if len(candles) < 3:
            msg = f"Minimum 3 candles required for 3-way split, got {len(candles)}"
            raise ValueError(msg)

        idx1 = max(1, int(len(candles) * train_ratio))
        idx2 = max(idx1 + 1, int(len(candles) * (train_ratio + val_ratio)))
        idx2 = min(idx2, len(candles) - 1)

        train_candles = candles[:idx1]
        val_candles = candles[idx1:idx2]
        test_candles = candles[idx2:]

        if train_candles[-1].timestamp >= val_candles[0].timestamp:
            msg = "Lookahead leak between train and validation partitions"
            raise RuntimeError(msg)
        if val_candles[-1].timestamp >= test_candles[0].timestamp:
            msg = "Lookahead leak between validation and test partitions"
            raise RuntimeError(msg)

        return ChronologicalSplit(
            train_candles=train_candles,
            val_candles=val_candles,
            test_candles=test_candles,
            train_range=(train_candles[0].timestamp, train_candles[-1].timestamp),
            val_range=(val_candles[0].timestamp, val_candles[-1].timestamp),
            test_range=(test_candles[0].timestamp, test_candles[-1].timestamp),
        )

    @classmethod
    def generate_rolling_windows(
        cls,
        candles: list[OHLCVCandle],
        train_bars: int,
        test_bars: int,
        step_bars: int,
    ) -> list[tuple[list[OHLCVCandle], list[OHLCVCandle]]]:
        """Generate sliding chronological folds for walk-forward evaluation (BTD §8.3).

        Args:
            candles: Chronological OHLCVCandle dataset.
            train_bars: Number of candles in in-sample window (e.g., 6-month window).
            test_bars: Number of candles in out-of-sample window (e.g., 1-month window).
            step_bars: Step size to roll window forward.

        Returns:
            List of (train_slice, test_slice) tuples.

        Raises:
            ValueError: If window parameters are invalid or dataset is insufficient.
        """
        if train_bars <= 0 or test_bars <= 0 or step_bars <= 0:
            msg = "train_bars, test_bars, and step_bars must all be strictly positive"
            raise ValueError(msg)

        cls._validate_candle_sequence(candles)

        total_req = train_bars + test_bars
        if len(candles) < total_req:
            msg = (
                f"Insufficient candles for rolling window: dataset has {len(candles)}, "
                f"minimum required is {total_req} (train {train_bars} + test {test_bars})"
            )
            raise ValueError(msg)

        folds: list[tuple[list[OHLCVCandle], list[OHLCVCandle]]] = []
        start = 0

        while start + train_bars + test_bars <= len(candles):
            train_slice = candles[start : start + train_bars]
            test_slice = candles[start + train_bars : start + train_bars + test_bars]
            folds.append((train_slice, test_slice))
            start += step_bars

        logger.info(
            "rolling_windows_generated",
            total_folds=len(folds),
            train_bars=train_bars,
            test_bars=test_bars,
            step_bars=step_bars,
        )
        return folds
