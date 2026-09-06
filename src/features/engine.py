"""Point-in-time feature engineering engine with zero look-ahead bias guarantees.

Conforms to FRD-FEAT-3/4, BTD §5.2, and DDD §5.1.
"""

from collections.abc import Mapping, Set
from datetime import UTC, datetime
from typing import Any, ClassVar
from uuid import uuid4

import numpy as np
import pandas as pd

from src.domain.features import FeatureSet
from src.features.price_action import extract_price_action_features
from src.features.technical import compute_all_technical_features
from src.utils.logging import get_logger

logger = get_logger(__name__)


class FeatureEngine:
    """Orchestrates deterministic, point-in-time quantitative feature calculation.

    Enforces strict point-in-time cutoffs ($t \\le T$) to prevent look-ahead bias
    across both real-time execution and historical backtesting (TRD-PIPE-3, BTD §5.2).
    """

    EXCLUDED_BASE_COLUMNS: ClassVar[Set[str]] = {
        "open",
        "high",
        "low",
        "close",
        "volume",
        "turnover",
        "timestamp",
        "symbol",
        "instrument",
    }

    REQUIRED_OHLCV_COLUMNS: ClassVar[Set[str]] = {
        "open",
        "high",
        "low",
        "close",
        "volume",
    }

    def __init__(
        self,
        feature_version: str = "feat-v1.0",
        impute_missing: bool = False,
        min_bars: int = 5,
    ) -> None:
        """Initialize FeatureEngine.

        Args:
            feature_version: Version tag of the feature calculation pipeline.
            impute_missing: If True, replace NaN/Inf feature values with 0.0.
            min_bars: Minimum historical bars required to compute features.
        """
        if min_bars < 1:
            msg = "min_bars must be at least 1"
            raise ValueError(msg)

        self.feature_version = feature_version
        self.impute_missing = impute_missing
        self.min_bars = min_bars
        self._logger = logger.bind(feature_version=feature_version)

    def compute_features(
        self,
        df: pd.DataFrame,
        instrument: str,
        timeframe: str,
        cutoff_time: datetime | None = None,
    ) -> FeatureSet:
        """Compute point-in-time features for an instrument up to cutoff_time.

        Args:
            df: Historical market data containing OHLCV columns.
            instrument: Canonical instrument symbol (e.g. 'NSE:RELIANCE').
            timeframe: Primary candle aggregation timeframe (e.g. '1m', '5m').
            cutoff_time: Strict point-in-time calculation cutoff timestamp (UTC).
                If None, defaults to the timestamp of the latest available bar.

        Returns:
            Immutable, strongly-typed FeatureSet domain object.

        Raises:
            ValueError: If input data is empty, missing required columns, has invalid
                timestamps, or contains fewer bars than min_bars.
        """
        if df.empty:
            msg = "Cannot compute features on empty DataFrame"
            raise ValueError(msg)

        # Validate required OHLCV columns (case-insensitive)
        cols_lower = {str(c).lower(): c for c in df.columns}
        missing = self.REQUIRED_OHLCV_COLUMNS - set(cols_lower.keys())
        if missing:
            msg = f"Missing required OHLCV columns: {sorted(missing)}"
            raise ValueError(msg)

        # Determine cutoff and apply point-in-time filter
        filtered_df, effective_cutoff = self._slice_point_in_time(df, cols_lower, cutoff_time)

        if len(filtered_df) < self.min_bars:
            msg = (
                f"Insufficient historical data on or before {effective_cutoff}: "
                f"required at least {self.min_bars} bars, got {len(filtered_df)}"
            )
            raise ValueError(msg)

        self._logger.debug(
            "computing_features",
            instrument=instrument,
            timeframe=timeframe,
            cutoff_time=effective_cutoff.isoformat(),
            bars_count=len(filtered_df),
        )

        # 1. Vectorized technical indicator enrichment
        enriched = compute_all_technical_features(filtered_df)

        # 2. Vectorized price action & market structure enrichment
        enriched = extract_price_action_features(enriched)

        # 3. Extract the feature vector at the exact cutoff bar
        latest_row = enriched.iloc[-1]
        feature_cols = [
            c for c in enriched.columns if str(c).lower() not in self.EXCLUDED_BASE_COLUMNS
        ]

        features_dict: dict[str, float] = {}
        finite_count = 0

        for col in feature_cols:
            val_raw = latest_row[col]
            if isinstance(val_raw, bool | np.bool_):
                val = 1.0 if val_raw else 0.0
                finite_count += 1
            else:
                val = float(val_raw)
                if np.isfinite(val):
                    finite_count += 1
                elif self.impute_missing:
                    val = 0.0
                else:
                    val = float("nan") if np.isnan(val) else val

            features_dict[str(col)] = val

        quality_score = float(finite_count / len(feature_cols)) if feature_cols else 1.0

        return FeatureSet(
            feature_set_id=uuid4(),
            instrument=instrument,
            timestamp=effective_cutoff,
            timeframe=timeframe,
            features=features_dict,
            feature_version=self.feature_version,
            quality_score=round(quality_score, 4),
        )

    def compute_historical_features(
        self,
        df: pd.DataFrame,
    ) -> pd.DataFrame:
        """Compute features across the entire historical DataFrame.

        All calculations are strictly backward-looking, ensuring zero forward-looking
        leakage at each point in time.

        Args:
            df: Historical market data containing OHLCV columns.

        Returns:
            DataFrame enriched with all technical indicator and price action columns.
        """
        if df.empty:
            msg = "Cannot compute historical features on empty DataFrame"
            raise ValueError(msg)

        cols_lower = {str(c).lower(): c for c in df.columns}
        missing = self.REQUIRED_OHLCV_COLUMNS - set(cols_lower.keys())
        if missing:
            msg = f"Missing required OHLCV columns: {sorted(missing)}"
            raise ValueError(msg)

        enriched = compute_all_technical_features(df)
        enriched = extract_price_action_features(enriched)

        if self.impute_missing:
            feature_cols = [
                c for c in enriched.columns if str(c).lower() not in self.EXCLUDED_BASE_COLUMNS
            ]
            for col in feature_cols:
                enriched[col] = enriched[col].replace([np.inf, -np.inf], np.nan).fillna(0.0)

        return enriched

    def _slice_from_timestamp_column(
        self,
        df: pd.DataFrame,
        ts_col: object,
        cutoff_utc: datetime | None,
    ) -> tuple[pd.DataFrame, datetime]:
        """Slice DataFrame using its timestamp column."""
        ts_series = pd.to_datetime(df[ts_col])
        if ts_series.dt.tz is None:
            msg = "DataFrame 'timestamp' column must be timezone-aware UTC"
            raise ValueError(msg)

        ts_series = ts_series.dt.tz_convert(UTC)
        if cutoff_utc is not None:
            filtered = df.loc[ts_series <= cutoff_utc]
            if filtered.empty:
                msg = f"No market data available on or before cutoff_time {cutoff_utc}"
                raise ValueError(msg)
            return filtered, cutoff_utc

        effective_cutoff = ts_series.iloc[-1].to_pydatetime()
        return df, effective_cutoff

    def _slice_from_datetime_index(
        self,
        df: pd.DataFrame,
        cutoff_utc: datetime | None,
    ) -> tuple[pd.DataFrame, datetime]:
        """Slice DataFrame using its DatetimeIndex."""
        assert isinstance(df.index, pd.DatetimeIndex)

        if df.index.tz is None:
            msg = "DataFrame DatetimeIndex must be timezone-aware UTC"
            raise ValueError(msg)

        idx_utc = df.index.tz_convert(UTC)
        if cutoff_utc is not None:
            cutoff_ts = pd.Timestamp(cutoff_utc)
            filtered = df.loc[idx_utc <= cutoff_ts]
            if filtered.empty:
                msg = f"No market data available on or before cutoff_time {cutoff_utc}"
                raise ValueError(msg)
            return filtered, cutoff_utc

        effective_cutoff: datetime = idx_utc[-1].to_pydatetime()
        return df, effective_cutoff

    def _slice_point_in_time(
        self,
        df: pd.DataFrame,
        cols_lower: Mapping[str, Any],
        cutoff_time: datetime | None,
    ) -> tuple[pd.DataFrame, datetime]:
        """Filter DataFrame strictly to t <= cutoff_time and resolve effective cutoff.

        Raises:
            ValueError: If timestamps are timezone-naive or no bars exist <= cutoff_time.
        """
        if cutoff_time is not None:
            if cutoff_time.tzinfo is None:
                msg = "cutoff_time must be timezone-aware UTC"
                raise ValueError(msg)
            cutoff_utc = cutoff_time.astimezone(UTC)
        else:
            cutoff_utc = None

        if "timestamp" in cols_lower:
            return self._slice_from_timestamp_column(df, cols_lower["timestamp"], cutoff_utc)

        if isinstance(df.index, pd.DatetimeIndex):
            return self._slice_from_datetime_index(df, cutoff_utc)

        msg = "DataFrame must have a timezone-aware DatetimeIndex or 'timestamp' column"
        raise ValueError(msg)
