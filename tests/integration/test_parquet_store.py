"""Integration tests for ParquetHistoricalStore partitioned time-series engine."""

import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from src.domain.market_data import OHLCVCandle
from src.infrastructure.parquet_store import ParquetHistoricalStore


@pytest.fixture
def store(tmp_path: Path) -> ParquetHistoricalStore:
    return ParquetHistoricalStore(base_dir=tmp_path / "historical")


def create_candle(
    instrument: str,
    ts: datetime,
    timeframe: str = "1m",
    price: str = "100.0000",
) -> OHLCVCandle:
    p = Decimal(price)
    return OHLCVCandle(
        timestamp=ts,
        instrument=instrument,
        timeframe=timeframe,
        open=p,
        high=p + Decimal("2.0000"),
        low=p - Decimal("1.0000"),
        close=p + Decimal("1.0000"),
        volume=5000,
        turnover=Decimal("500000.0000"),
        quality_state="VALIDATED",
    )


@pytest.mark.integration
def test_parquet_store_write_and_read_roundtrip(store: ParquetHistoricalStore) -> None:
    base_ts = datetime(2025, 1, 15, 9, 15, tzinfo=UTC)
    candles = [
        create_candle("RELIANCE", base_ts + timedelta(minutes=i), price=f"{2500 + i}.0000")
        for i in range(10)
    ]

    written = store.write_candles(candles)
    assert written == 10

    # Read back all candles
    results = store.read_candles(
        instrument="RELIANCE",
        start_time=base_ts,
        end_time=base_ts + timedelta(minutes=10),
        timeframe="1m",
    )
    assert len(results) == 10
    assert results[0].instrument == "RELIANCE"
    assert results[0].open == Decimal("2500.0000")
    assert results[-1].close == Decimal("2510.0000")
    assert results[0].timestamp == base_ts


@pytest.mark.integration
def test_parquet_store_partition_structure(store: ParquetHistoricalStore) -> None:
    ts = datetime(2025, 3, 10, 10, 0, tzinfo=UTC)
    candle = create_candle("INFY", ts, timeframe="5m", price="1600.0000")

    store.write_candles([candle])

    partition_path = store.base_dir / "5m" / "INFY" / "year=2025" / "month=03" / "data.parquet"
    assert partition_path.exists()
    assert partition_path.is_file()


@pytest.mark.integration
def test_parquet_store_zero_lookahead_slicing(store: ParquetHistoricalStore) -> None:
    """Strictly verify [start_time, end_time) excludes timestamp >= end_time."""
    base_ts = datetime(2025, 2, 1, 10, 0, tzinfo=UTC)
    candles = [create_candle("TCS", base_ts + timedelta(minutes=i)) for i in range(5)]
    store.write_candles(candles)

    # Query range exactly up to minute 3 (should exclude minute 3, 4)
    slice_end = base_ts + timedelta(minutes=3)
    results = store.read_candles(
        instrument="TCS",
        start_time=base_ts,
        end_time=slice_end,
        timeframe="1m",
    )
    assert len(results) == 3
    timestamps = [c.timestamp for c in results]
    assert base_ts + timedelta(minutes=0) in timestamps
    assert base_ts + timedelta(minutes=1) in timestamps
    assert base_ts + timedelta(minutes=2) in timestamps
    assert slice_end not in timestamps  # Zero-lookahead guarantee


@pytest.mark.integration
def test_parquet_store_deduplication(store: ParquetHistoricalStore) -> None:
    """Overwriting same instrument and timestamp updates the record without duplicate count."""
    ts = datetime(2025, 4, 1, 9, 30, tzinfo=UTC)
    candle1 = create_candle("HDFCBANK", ts, price="1500.0000")
    store.write_candles([candle1])

    # Overwrite same candle with updated price
    candle2 = create_candle("HDFCBANK", ts, price="1520.0000")
    store.write_candles([candle2])

    results = store.read_candles(
        instrument="HDFCBANK",
        start_time=ts - timedelta(minutes=1),
        end_time=ts + timedelta(minutes=1),
        timeframe="1m",
    )
    assert len(results) == 1
    assert results[0].open == Decimal("1520.0000")


@pytest.mark.integration
def test_parquet_store_multi_month_range(store: ParquetHistoricalStore) -> None:
    """Querying spanning across month boundaries."""
    c_nov = create_candle("ICICIBANK", datetime(2024, 11, 28, 10, 0, tzinfo=UTC))
    c_dec = create_candle("ICICIBANK", datetime(2024, 12, 15, 10, 0, tzinfo=UTC))
    c_jan = create_candle("ICICIBANK", datetime(2025, 1, 10, 10, 0, tzinfo=UTC))

    store.write_candles([c_nov, c_dec, c_jan])

    results = store.read_candles(
        instrument="ICICIBANK",
        start_time=datetime(2024, 11, 1, tzinfo=UTC),
        end_time=datetime(2025, 2, 1, tzinfo=UTC),
        timeframe="1m",
    )
    assert len(results) == 3


@pytest.mark.integration
def test_parquet_store_read_dataframe(store: ParquetHistoricalStore) -> None:
    base_ts = datetime(2025, 5, 1, 9, 15, tzinfo=UTC)
    candles = [create_candle("SBIN", base_ts + timedelta(minutes=i)) for i in range(5)]
    store.write_candles(candles)

    df = store.read_dataframe(
        instrument="SBIN",
        start_time=base_ts,
        end_time=base_ts + timedelta(minutes=5),
        timeframe="1m",
    )
    assert not df.empty
    assert len(df) == 5
    assert "open" in df.columns
    assert "close" in df.columns


@pytest.mark.integration
def test_parquet_store_edge_cases(store: ParquetHistoricalStore) -> None:
    # Empty write returns 0
    assert store.write_candles([]) == 0

    # Non-existent instrument returns empty
    res = store.read_candles(
        instrument="NONEXISTENT",
        start_time=datetime(2025, 1, 1, tzinfo=UTC),
        end_time=datetime(2025, 1, 2, tzinfo=UTC),
        timeframe="1m",
    )
    assert res == []

    # Invalid range (start >= end) returns empty
    res_inv = store.read_candles(
        instrument="SBIN",
        start_time=datetime(2025, 1, 2, tzinfo=UTC),
        end_time=datetime(2025, 1, 1, tzinfo=UTC),
        timeframe="1m",
    )
    assert res_inv == []


@pytest.mark.integration
def test_parquet_store_high_throughput_benchmark(store: ParquetHistoricalStore) -> None:
    """Benchmark writing and querying large batches of candles (<50ms target)."""
    base_ts = datetime(2025, 1, 1, 9, 0, tzinfo=UTC)
    count = 10000  # 10k candles per test batch
    candles = [
        create_candle(
            "NIFTY50",
            base_ts + timedelta(minutes=i),
            price=f"{22000 + (i % 100)}.0000",
        )
        for i in range(count)
    ]

    t0 = time.perf_counter()
    store.write_candles(candles)
    write_time = time.perf_counter() - t0
    assert write_time > 0

    # Benchmark point-in-time range query (e.g. 1-day slice)
    slice_start = base_ts + timedelta(minutes=375)
    slice_end = slice_start + timedelta(minutes=375)

    t1 = time.perf_counter()
    results = store.read_candles("NIFTY50", slice_start, slice_end, timeframe="1m")
    query_time_ms = (time.perf_counter() - t1) * 1000.0

    assert len(results) == 375
    # Query must be sub-50ms
    assert query_time_ms < 50.0, f"Query took {query_time_ms:.2f}ms, expected < 50ms"
