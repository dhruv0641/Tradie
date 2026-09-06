"""Integration tests for CSV market data adapter, HistoricalDataLoader, and CLI runner."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from scripts.ingest_historical import build_parser, run_ingestion
from src.data.adapter import MockDataSourceAdapter, create_sample_candle
from src.data.csv_adapter import CSVDataSourceAdapter
from src.data.historical_loader import HistoricalDataLoader
from src.domain.market_data import OHLCVCandle
from src.infrastructure.parquet_store import ParquetHistoricalStore


@pytest.fixture
def parquet_store(tmp_path: Path) -> ParquetHistoricalStore:
    return ParquetHistoricalStore(base_dir=tmp_path / "historical")


@pytest.fixture
def sample_standard_csv(tmp_path: Path) -> Path:
    csv_file = tmp_path / "standard_ohlcv.csv"
    csv_content = """timestamp,symbol,open,high,low,close,volume,turnover,timeframe
2025-01-15 09:15:00,RELIANCE,2500.50,2525.00,2495.00,2518.75,150000,377812500.00,1d
2025-01-16 09:15:00,RELIANCE,2518.75,2540.00,2510.00,2535.25,120000,304230000.00,1d
2025-01-15 09:15:00,TCS,3800.00,3850.00,3790.00,3840.50,80000,307240000.00,1d
"""
    csv_file.write_text(csv_content, encoding="utf-8")
    return csv_file


@pytest.fixture
def sample_bhavcopy_csv(tmp_path: Path) -> Path:
    csv_file = tmp_path / "bhavcopy.csv"
    csv_content = """SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP
RELIANCE,EQ,2500.00,2530.00,2490.00,2520.00,2522.00,2495.00,250000,630000000.00,15-Jan-2025
INFY,EQ,1600.00,1625.00,1595.00,1615.00,1618.00,1590.00,180000,290700000.00,15-Jan-2025
HDFCBANK,EQ,1550.00,1570.00,1545.00,1565.00,1564.00,1540.00,300000,469500000.00,15-Jan-2025
TCS,BE,3800.00,3850.00,3790.00,3840.50,3842.00,3795.00,10000,38405000.00,15-Jan-2025
"""
    csv_file.write_text(csv_content, encoding="utf-8")
    return csv_file


@pytest.mark.asyncio
@pytest.mark.integration
async def test_csv_adapter_standard_format(sample_standard_csv: Path) -> None:
    """Verify parsing of standard OHLCV CSV file."""
    adapter = CSVDataSourceAdapter(file_path=sample_standard_csv)
    await adapter.connect()
    assert await adapter.is_connected()

    # Query RELIANCE
    candles = await adapter.fetch_historical_candles(
        instrument="NSE:RELIANCE",
        timeframe="1d",
        start_time=datetime(2025, 1, 1, tzinfo=UTC),
        end_time=datetime(2025, 2, 1, tzinfo=UTC),
    )
    assert len(candles) == 2
    assert candles[0].instrument == "NSE:RELIANCE"
    assert candles[0].open == Decimal("2500.5000")
    assert candles[0].close == Decimal("2518.7500")
    assert candles[0].volume == 150000
    assert candles[0].timestamp == datetime(2025, 1, 15, 9, 15, tzinfo=UTC)

    # Query TCS
    tcs_candles = await adapter.fetch_historical_candles(
        instrument="NSE:TCS",
        timeframe="1d",
        start_time=datetime(2025, 1, 1, tzinfo=UTC),
        end_time=datetime(2025, 2, 1, tzinfo=UTC),
    )
    assert len(tcs_candles) == 1
    assert tcs_candles[0].open == Decimal("3800.0000")

    await adapter.disconnect()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_csv_adapter_bhavcopy_format(sample_bhavcopy_csv: Path) -> None:
    """Verify parsing of NSE Bhavcopy CSV file and filtering for equity series (EQ)."""
    adapter = CSVDataSourceAdapter(file_path=sample_bhavcopy_csv)
    await adapter.connect()

    # Query RELIANCE
    candles = await adapter.fetch_historical_candles(
        instrument="NSE:RELIANCE",
        timeframe="1d",
        start_time=datetime(2025, 1, 1, tzinfo=UTC),
        end_time=datetime(2025, 2, 1, tzinfo=UTC),
    )
    assert len(candles) == 1
    assert candles[0].instrument == "NSE:RELIANCE"
    assert candles[0].close == Decimal("2520.0000")
    assert candles[0].volume == 250000
    assert candles[0].timestamp == datetime(2025, 1, 15, 0, 0, tzinfo=UTC)

    # Verify that TCS with series 'BE' was filtered out
    tcs_candles = await adapter.fetch_historical_candles(
        instrument="NSE:TCS",
        timeframe="1d",
        start_time=datetime(2025, 1, 1, tzinfo=UTC),
        end_time=datetime(2025, 2, 1, tzinfo=UTC),
    )
    assert len(tcs_candles) == 0

    await adapter.disconnect()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_historical_loader_ingest_csv(
    parquet_store: ParquetHistoricalStore, sample_standard_csv: Path
) -> None:
    """Verify HistoricalDataLoader persists CSV data to partitioned Parquet store."""
    loader = HistoricalDataLoader(parquet_store=parquet_store)
    results = await loader.ingest_csv_file(sample_standard_csv, timeframe="1d")

    assert len(results) == 2  # RELIANCE and TCS
    instruments = {r.instrument for r in results}
    assert instruments == {"NSE:RELIANCE", "NSE:TCS"}

    # Read back from Parquet store to confirm roundtrip persistence
    reliance_candles = parquet_store.read_candles(
        instrument="NSE:RELIANCE",
        start_time=datetime(2025, 1, 1, tzinfo=UTC),
        end_time=datetime(2025, 2, 1, tzinfo=UTC),
        timeframe="1d",
    )
    assert len(reliance_candles) == 2
    assert reliance_candles[0].open == Decimal("2500.5000")
    assert reliance_candles[1].close == Decimal("2535.2500")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_historical_loader_ingest_from_adapter(
    parquet_store: ParquetHistoricalStore,
) -> None:
    """Verify HistoricalDataLoader ingesting from a DataSourceAdapter instance."""
    base_ts = datetime(2025, 1, 15, 9, 15, tzinfo=UTC)
    c1 = create_sample_candle("NSE:INFY", base_ts, "1d", "1600.0000", "1620.0000")
    mock_adapter = MockDataSourceAdapter(candles=[c1])

    loader = HistoricalDataLoader(parquet_store=parquet_store)
    result = await loader.ingest_from_adapter(
        adapter=mock_adapter,
        instrument="NSE:INFY",
        timeframe="1d",
        start_time=datetime(2025, 1, 1, tzinfo=UTC),
        end_time=datetime(2025, 2, 1, tzinfo=UTC),
    )

    assert result.instrument == "NSE:INFY"
    assert result.total_candles == 1
    assert result.partitions_updated == 1

    # Verify in Parquet store
    stored = parquet_store.read_candles(
        "NSE:INFY",
        start_time=datetime(2025, 1, 1, tzinfo=UTC),
        end_time=datetime(2025, 2, 1, tzinfo=UTC),
        timeframe="1d",
    )
    assert len(stored) == 1
    assert stored[0].open == Decimal("1600.0000")


@pytest.mark.integration
def test_historical_loader_validation_rules(
    parquet_store: ParquetHistoricalStore,
) -> None:
    """Verify physical candle sanity validation rules."""
    loader = HistoricalDataLoader(parquet_store=parquet_store)
    now = datetime(2025, 1, 15, 9, 15, tzinfo=UTC)

    # Valid candle
    valid_c = create_sample_candle("NSE:SBIN", now)
    assert loader.validate_candle(valid_c) is True

    # Negative volume
    invalid_vol = OHLCVCandle.model_construct(
        instrument="NSE:SBIN",
        timestamp=now,
        open=Decimal("500"),
        high=Decimal("510"),
        low=Decimal("490"),
        close=Decimal("505"),
        volume=-10,
        turnover=Decimal("0"),
        timeframe="1d",
        quality_state="VALIDATED",
    )
    assert loader.validate_candle(invalid_vol) is False

    # Low > Open
    invalid_bounds = OHLCVCandle.model_construct(
        instrument="NSE:SBIN",
        timestamp=now,
        open=Decimal("480"),
        high=Decimal("510"),
        low=Decimal("490"),
        close=Decimal("505"),
        volume=100,
        turnover=Decimal("0"),
        timeframe="1d",
        quality_state="VALIDATED",
    )
    assert loader.validate_candle(invalid_bounds) is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_historical_loader_database_persistence(
    parquet_store: ParquetHistoricalStore,
) -> None:
    """Verify optional TimescaleDB / PostgreSQL persistence via DatabaseManager mock."""
    mock_db = MagicMock()
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_execute_result
    mock_db.get_session.return_value.__aenter__.return_value = mock_session
    mock_db.get_session.return_value.__aexit__.return_value = None

    loader = HistoricalDataLoader(parquet_store=parquet_store, db_manager=mock_db)

    base_ts = datetime(2025, 1, 15, 9, 15, tzinfo=UTC)
    c1 = create_sample_candle("NSE:WIPRO", base_ts, "1d")
    mock_adapter = MockDataSourceAdapter(candles=[c1])

    result = await loader.ingest_from_adapter(
        adapter=mock_adapter,
        instrument="NSE:WIPRO",
        timeframe="1d",
        start_time=datetime(2025, 1, 1, tzinfo=UTC),
        end_time=datetime(2025, 2, 1, tzinfo=UTC),
        persist_db=True,
    )
    assert result.persisted_to_db is True
    mock_session.add.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_cli_ingest_historical_execution(tmp_path: Path, sample_standard_csv: Path) -> None:
    """Verify CLI workflow runner and argument parsing."""
    parser = build_parser()
    args = parser.parse_args(["--file", str(sample_standard_csv), "--timeframe", "1d"])
    assert args.file == sample_standard_csv
    assert args.timeframe == "1d"

    # Execute workflow directly
    exit_code = await run_ingestion(
        file_path=sample_standard_csv,
        timeframe="1d",
        storage_dir=tmp_path / "cli_storage",
        persist_db=False,
    )
    assert exit_code == 0

    # Non-existent file error handling
    err_code = await run_ingestion(
        file_path=tmp_path / "non_existent.csv",
        timeframe="1d",
        storage_dir=tmp_path / "cli_storage",
        persist_db=False,
    )
    assert err_code == 1
