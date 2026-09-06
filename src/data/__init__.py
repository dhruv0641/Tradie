"""Market data ingestion pipelines, adapter interfaces, and historical loaders."""

from src.data.adapter import (
    AdapterFactory,
    DataSourceAdapter,
    MockDataSourceAdapter,
    create_sample_candle,
    create_sample_depth_quote,
)
from src.data.aggregator import CandleAggregator
from src.data.csv_adapter import CSVDataSourceAdapter
from src.data.historical_loader import HistoricalDataLoader, IngestionResult
from src.data.streaming import WebSocketFeedHandler
from src.data.validator import (
    DataValidationPipeline,
    InMemoryQuarantineStore,
    ValidationResult,
)

__all__ = [
    "AdapterFactory",
    "CSVDataSourceAdapter",
    "CandleAggregator",
    "DataSourceAdapter",
    "DataValidationPipeline",
    "HistoricalDataLoader",
    "InMemoryQuarantineStore",
    "IngestionResult",
    "MockDataSourceAdapter",
    "ValidationResult",
    "WebSocketFeedHandler",
    "create_sample_candle",
    "create_sample_depth_quote",
]
