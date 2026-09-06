"""Unit tests for DataSourceAdapter protocol, AdapterFactory registry, and MockDataSourceAdapter."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.data.adapter import (
    AdapterFactory,
    DataSourceAdapter,
    MockDataSourceAdapter,
    create_sample_candle,
    create_sample_depth_quote,
)
from src.data.csv_adapter import CSVDataSourceAdapter


@pytest.mark.unit
def test_protocol_runtime_check() -> None:
    """Verify that adapters conform to the DataSourceAdapter protocol."""
    mock_adapter = MockDataSourceAdapter()
    assert isinstance(mock_adapter, DataSourceAdapter)

    csv_adapter = CSVDataSourceAdapter()
    assert isinstance(csv_adapter, DataSourceAdapter)


@pytest.mark.unit
def test_adapter_factory_registry() -> None:
    """Verify AdapterFactory creates registered adapters and handles unknown names."""
    available = AdapterFactory.available_adapters()
    assert "mock" in available
    assert "csv" in available

    mock_inst = AdapterFactory.create("mock")
    assert isinstance(mock_inst, MockDataSourceAdapter)

    csv_inst = AdapterFactory.create("csv")
    assert isinstance(csv_inst, CSVDataSourceAdapter)

    with pytest.raises(ValueError, match="Unknown data adapter 'unregistered'"):
        AdapterFactory.create("unregistered")


@pytest.mark.unit
def test_adapter_factory_custom_registration() -> None:
    """Verify dynamic registration of custom adapter classes."""

    class CustomAdapter(MockDataSourceAdapter):
        pass

    AdapterFactory.register("custom", CustomAdapter)
    assert "custom" in AdapterFactory.available_adapters()
    inst = AdapterFactory.create("custom")
    assert isinstance(inst, CustomAdapter)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_mock_adapter_lifecycle() -> None:
    """Verify MockDataSourceAdapter connection state lifecycle."""
    adapter = MockDataSourceAdapter()
    assert not await adapter.is_connected()

    await adapter.connect()
    assert await adapter.is_connected()

    await adapter.disconnect()
    assert not await adapter.is_connected()


@pytest.mark.asyncio
@pytest.mark.unit
async def test_mock_adapter_fetch_historical_candles() -> None:
    """Verify MockDataSourceAdapter point-in-time candle slicing."""
    base_ts = datetime(2025, 1, 15, 9, 15, tzinfo=UTC)
    c1 = create_sample_candle("NSE:RELIANCE", base_ts, "1m", "2500.0000", "2510.0000")
    c2 = create_sample_candle(
        "NSE:RELIANCE", base_ts + timedelta(minutes=1), "1m", "2510.0000", "2520.0000"
    )
    c3 = create_sample_candle(
        "NSE:RELIANCE", base_ts + timedelta(minutes=2), "1m", "2520.0000", "2530.0000"
    )
    # Different instrument
    c_infy = create_sample_candle("NSE:INFY", base_ts, "1m", "1500.0000", "1510.0000")

    adapter = MockDataSourceAdapter(candles=[c3, c1, c2, c_infy])
    await adapter.connect()

    # Query range exactly up to minute 2 (should exclude minute 2)
    results = await adapter.fetch_historical_candles(
        instrument="NSE:RELIANCE",
        timeframe="1m",
        start_time=base_ts,
        end_time=base_ts + timedelta(minutes=2),
    )
    assert len(results) == 2
    # Verify sorted order
    assert results[0].timestamp == base_ts
    assert results[1].timestamp == base_ts + timedelta(minutes=1)
    assert results[0].open == Decimal("2500.0000")


@pytest.mark.asyncio
@pytest.mark.unit
async def test_mock_adapter_streaming_subscriptions() -> None:
    """Verify MockDataSourceAdapter candle and depth streaming generators."""
    base_ts = datetime(2025, 1, 15, 9, 15, tzinfo=UTC)
    c1 = create_sample_candle("NSE:RELIANCE", base_ts, "1m")
    q1 = create_sample_depth_quote("NSE:RELIANCE", base_ts, "2500.0000", "2500.5000")

    adapter = MockDataSourceAdapter()
    adapter.add_candle(c1)
    adapter.add_depth_quote(q1)

    # Test candle stream
    streamed_candles = [c async for c in adapter.subscribe_candles(["NSE:RELIANCE"], "1m")]
    assert len(streamed_candles) == 1
    assert streamed_candles[0].instrument == "NSE:RELIANCE"

    # Test depth stream
    streamed_depth = [q async for q in adapter.subscribe_depth(["NSE:RELIANCE"])]
    assert len(streamed_depth) == 1
    assert streamed_depth[0].bids[0].price == Decimal("2500.0000")
