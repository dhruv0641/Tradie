"""Market data ingestion pipelines, adapter interfaces, and historical loaders."""

from src.data.adapter import (
    AdapterFactory,
    DataSourceAdapter,
    MockDataSourceAdapter,
    create_sample_candle,
    create_sample_depth_quote,
)
from src.data.csv_adapter import CSVDataSourceAdapter
from src.data.historical_loader import HistoricalDataLoader, IngestionResult

__all__ = [
    "AdapterFactory",
    "CSVDataSourceAdapter",
    "DataSourceAdapter",
    "HistoricalDataLoader",
    "IngestionResult",
    "MockDataSourceAdapter",
    "create_sample_candle",
    "create_sample_depth_quote",
]
