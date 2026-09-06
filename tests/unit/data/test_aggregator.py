"""Unit tests for CandleAggregator and timeframe boundary calculation."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.data.aggregator import (
    CandleAggregator,
    floor_to_timeframe,
    parse_timeframe_seconds,
)
from src.domain.market_data import MarketTick, OHLCVCandle


def create_tick(
    instrument: str,
    ts: datetime,
    price: str,
    volume: int = 100,
    turnover: str = "0",
) -> MarketTick:
    p = Decimal(price)
    to = Decimal(turnover) if turnover != "0" else p * Decimal(volume)
    return MarketTick(
        instrument=instrument,
        timestamp=ts,
        last_price=p,
        volume=volume,
        turnover=to,
    )


def test_parse_timeframe_seconds() -> None:
    """Verify timeframe string parsing to seconds."""
    assert parse_timeframe_seconds("1m") == 60
    assert parse_timeframe_seconds("5m") == 300
    assert parse_timeframe_seconds("15m") == 900
    assert parse_timeframe_seconds("1h") == 3600
    assert parse_timeframe_seconds("1d") == 86400
    assert parse_timeframe_seconds("30s") == 30

    with pytest.raises(ValueError, match="Unsupported timeframe specification"):
        parse_timeframe_seconds("1w")


def test_floor_to_timeframe() -> None:
    """Verify timestamp rounding to timeframe interval boundaries."""
    # 09:17:42 UTC
    dt = datetime(2025, 1, 15, 9, 17, 42, tzinfo=UTC)

    # 1m floor -> 09:17:00
    f_1m = floor_to_timeframe(dt, "1m")
    assert f_1m == datetime(2025, 1, 15, 9, 17, 0, tzinfo=UTC)

    # 5m floor -> 09:15:00
    f_5m = floor_to_timeframe(dt, "5m")
    assert f_5m == datetime(2025, 1, 15, 9, 15, 0, tzinfo=UTC)

    # 15m floor -> 09:15:00
    f_15m = floor_to_timeframe(dt, "15m")
    assert f_15m == datetime(2025, 1, 15, 9, 15, 0, tzinfo=UTC)

    # 1h floor -> 09:00:00
    f_1h = floor_to_timeframe(dt, "1h")
    assert f_1h == datetime(2025, 1, 15, 9, 0, 0, tzinfo=UTC)

    # 1d floor -> 00:00:00
    f_1d = floor_to_timeframe(dt, "1d")
    assert f_1d == datetime(2025, 1, 15, 0, 0, 0, tzinfo=UTC)


def test_aggregator_single_tick_initialization() -> None:
    """Verify aggregator initializes active bar on first tick."""
    agg = CandleAggregator(timeframes=["1m"])
    base_ts = datetime(2025, 1, 15, 9, 15, 10, tzinfo=UTC)
    tick = create_tick("NSE:RELIANCE", base_ts, "2500.00", volume=50)

    closed = agg.process_tick(tick)
    assert len(closed) == 0
    assert agg.total_ticks_processed == 1

    active = agg.get_active_candle("NSE:RELIANCE", "1m")
    assert active is not None
    assert active.instrument == "NSE:RELIANCE"
    assert active.timestamp == datetime(2025, 1, 15, 9, 15, 0, tzinfo=UTC)
    assert active.open == Decimal("2500.00")
    assert active.high == Decimal("2500.00")
    assert active.low == Decimal("2500.00")
    assert active.close == Decimal("2500.00")
    assert active.volume == 50


def test_aggregator_intra_candle_price_updates() -> None:
    """Verify multiple ticks within the same bar interval update high, low, close, volume."""
    agg = CandleAggregator(timeframes=["1m"])
    base_ts = datetime(2025, 1, 15, 9, 15, 0, tzinfo=UTC)

    t1 = create_tick("NSE:RELIANCE", base_ts + timedelta(seconds=5), "2500.00", volume=100)
    t2 = create_tick("NSE:RELIANCE", base_ts + timedelta(seconds=15), "2520.00", volume=150)
    t3 = create_tick("NSE:RELIANCE", base_ts + timedelta(seconds=30), "2490.00", volume=200)
    t4 = create_tick("NSE:RELIANCE", base_ts + timedelta(seconds=45), "2510.00", volume=50)

    for t in [t1, t2, t3, t4]:
        assert len(agg.process_tick(t)) == 0

    assert agg.total_ticks_processed == 4
    active = agg.get_active_candle("NSE:RELIANCE", "1m")
    assert active is not None
    assert active.open == Decimal("2500.00")
    assert active.high == Decimal("2520.00")
    assert active.low == Decimal("2490.00")
    assert active.close == Decimal("2510.00")
    assert active.volume == 500  # 100 + 150 + 200 + 50


def test_aggregator_interval_closure_and_callback() -> None:
    """Verify crossing into next interval seals active bar, notifies callback, and resets."""
    received_candles: list[OHLCVCandle] = []

    def on_closed(candle: OHLCVCandle) -> None:
        received_candles.append(candle)

    agg = CandleAggregator(timeframes=["1m"], callbacks=[on_closed])
    base_ts = datetime(2025, 1, 15, 9, 15, 0, tzinfo=UTC)

    # 3 ticks in 09:15 interval
    agg.process_tick(create_tick("NSE:TCS", base_ts + timedelta(seconds=10), "3800.00", 10))
    agg.process_tick(create_tick("NSE:TCS", base_ts + timedelta(seconds=20), "3820.00", 20))
    agg.process_tick(create_tick("NSE:TCS", base_ts + timedelta(seconds=50), "3810.00", 30))
    assert len(received_candles) == 0

    # 1 tick in 09:16 interval -> should seal 09:15 bar
    closed = agg.process_tick(
        create_tick("NSE:TCS", base_ts + timedelta(seconds=65), "3815.00", 15)
    )
    assert len(closed) == 1
    assert len(received_candles) == 1

    sealed = closed[0]
    assert sealed.instrument == "NSE:TCS"
    assert sealed.timestamp == datetime(2025, 1, 15, 9, 15, 0, tzinfo=UTC)
    assert sealed.open == Decimal("3800.00")
    assert sealed.high == Decimal("3820.00")
    assert sealed.low == Decimal("3800.00")
    assert sealed.close == Decimal("3810.00")
    assert sealed.volume == 60

    # Verify new active bar is 09:16
    active = agg.get_active_candle("NSE:TCS", "1m")
    assert active is not None
    assert active.timestamp == datetime(2025, 1, 15, 9, 16, 0, tzinfo=UTC)
    assert active.open == Decimal("3815.00")
    assert active.volume == 15


def test_aggregator_multi_timeframe() -> None:
    """Verify simultaneous 1m and 5m aggregation."""
    agg = CandleAggregator(timeframes=["1m", "5m"])
    base_ts = datetime(2025, 1, 15, 9, 15, 0, tzinfo=UTC)

    # Minute 0 (09:15)
    agg.process_tick(create_tick("NSE:INFY", base_ts + timedelta(seconds=10), "1600.00", 10))

    # Minute 1 (09:16) -> closes 09:15 1m bar, 5m bar continues
    c1 = agg.process_tick(
        create_tick("NSE:INFY", base_ts + timedelta(minutes=1, seconds=10), "1610.00", 20)
    )
    assert len(c1) == 1
    assert c1[0].timeframe == "1m"
    assert c1[0].timestamp == datetime(2025, 1, 15, 9, 15, tzinfo=UTC)

    # Minute 5 (09:20) -> closes 09:19 1m bar AND 09:15 5m bar
    c2 = agg.process_tick(
        create_tick("NSE:INFY", base_ts + timedelta(minutes=5, seconds=5), "1625.00", 30)
    )
    assert len(c2) == 2
    timeframes = {c.timeframe for c in c2}
    assert timeframes == {"1m", "5m"}

    five_m_bar = next(c for c in c2 if c.timeframe == "5m")
    assert five_m_bar.timestamp == datetime(2025, 1, 15, 9, 15, tzinfo=UTC)
    assert five_m_bar.open == Decimal("1600.00")
    assert five_m_bar.close == Decimal("1610.00")


def test_aggregator_out_of_order_tick() -> None:
    """Verify that older ticks arriving out-of-order are rejected without altering state."""
    agg = CandleAggregator(timeframes=["1m"])
    base_ts = datetime(2025, 1, 15, 9, 15, 30, tzinfo=UTC)

    agg.process_tick(create_tick("NSE:WIPRO", base_ts, "500.00", 100))
    # Move to next interval
    agg.process_tick(create_tick("NSE:WIPRO", base_ts + timedelta(minutes=1), "510.00", 100))

    # Older tick with 09:15 timestamp arrives late
    stale_tick = create_tick("NSE:WIPRO", base_ts - timedelta(seconds=10), "490.00", 50)
    closed = agg.process_tick(stale_tick)
    assert len(closed) == 0

    # Active bar remains the 09:16 bar
    active = agg.get_active_candle("NSE:WIPRO", "1m")
    assert active is not None
    assert active.timestamp == datetime(2025, 1, 15, 9, 16, tzinfo=UTC)
    assert active.low == Decimal("510.00")


def test_aggregator_force_close_and_flush() -> None:
    """Verify force_close_all seals in-flight bars and flush_closed_candles clears buffer."""
    agg = CandleAggregator(timeframes=["1m"])
    base_ts = datetime(2025, 1, 15, 9, 15, 10, tzinfo=UTC)

    agg.process_tick(create_tick("NSE:HDFCBANK", base_ts, "1550.00", 100))
    agg.process_tick(create_tick("NSE:ICICIBANK", base_ts, "1000.00", 200))

    assert agg.get_active_candle("NSE:HDFCBANK", "1m") is not None
    assert agg.get_active_candle("NSE:ICICIBANK", "1m") is not None

    # Force close all
    closed = agg.force_close_all()
    assert len(closed) == 2
    instruments = {c.instrument for c in closed}
    assert instruments == {"NSE:HDFCBANK", "NSE:ICICIBANK"}

    # Active bars should now be empty
    assert agg.get_active_candle("NSE:HDFCBANK", "1m") is None
    assert agg.get_active_candle("NSE:ICICIBANK", "1m") is None

    # Flush closed candles buffer
    flushed = agg.flush_closed_candles()
    assert len(flushed) == 2

    # Subsequent flush returns empty
    assert len(agg.flush_closed_candles()) == 0


@pytest.mark.asyncio
async def test_aggregator_async_callback() -> None:
    """Verify aggregator dispatches to async coroutine callbacks."""
    async_received: list[OHLCVCandle] = []

    async def async_cb(c: OHLCVCandle) -> None:
        await asyncio.sleep(0.001)
        async_received.append(c)

    agg = CandleAggregator(timeframes=["1m"])
    agg.register_callback(async_cb)

    base_ts = datetime(2025, 1, 15, 9, 15, 0, tzinfo=UTC)
    agg.process_tick(create_tick("NSE:SBIN", base_ts + timedelta(seconds=10), "750.00", 10))
    # Seal by moving interval
    agg.process_tick(create_tick("NSE:SBIN", base_ts + timedelta(seconds=70), "755.00", 20))

    # Allow event loop slice to complete coroutine
    for _ in range(20):
        if async_received:
            break
        await asyncio.sleep(0.01)

    assert len(async_received) == 1
    assert async_received[0].instrument == "NSE:SBIN"
