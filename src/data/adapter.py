"""Market data adapter interface protocols, factory registry, and mock implementations."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, ClassVar, Protocol, runtime_checkable

import structlog

from src.domain.market_data import MarketDepthLevel, MarketDepthQuote, OHLCVCandle

logger = structlog.get_logger(__name__)


@runtime_checkable
class DataSourceAdapter(Protocol):
    """Abstract interface for all market data providers (TRD-PIPE-1, HLD §9)."""

    async def connect(self) -> None:
        """Establish connection to data vendor API or stream."""
        ...

    async def disconnect(self) -> None:
        """Gracefully disconnect and release network resources."""
        ...

    async def is_connected(self) -> bool:
        """Return current connectivity status."""
        ...

    async def fetch_historical_candles(
        self,
        instrument: str,
        timeframe: str,
        start_time: datetime,
        end_time: datetime,
    ) -> list[OHLCVCandle]:
        """Fetch bulk historical candles strictly point-in-time [start_time, end_time)."""
        ...

    def subscribe_candles(
        self, instruments: list[str], timeframe: str
    ) -> AsyncIterator[OHLCVCandle]:
        """Stream real-time closed or updated OHLCV candles."""
        ...

    def subscribe_depth(self, instruments: list[str]) -> AsyncIterator[MarketDepthQuote]:
        """Stream real-time Level-2 market depth quotes."""
        ...


class AdapterFactory:
    """Registry and factory for market data adapter implementations."""

    _registry: ClassVar[dict[str, type[DataSourceAdapter]]] = {}

    @classmethod
    def register(cls, name: str, adapter_cls: type[DataSourceAdapter]) -> None:
        """Register an adapter class under a unique name."""
        key = name.strip().lower()
        cls._registry[key] = adapter_cls
        logger.info("data_adapter_registered", name=key, adapter_class=adapter_cls.__name__)

    @classmethod
    def create(cls, name: str, **kwargs: Any) -> DataSourceAdapter:
        """Instantiate a registered adapter by name."""
        key = name.strip().lower()
        if key not in cls._registry:
            registered = sorted(cls._registry.keys())
            msg = f"Unknown data adapter '{name}'. Available adapters: {registered}"
            raise ValueError(msg)
        adapter_cls = cls._registry[key]
        return adapter_cls(**kwargs)

    @classmethod
    def available_adapters(cls) -> list[str]:
        """List all registered adapter names."""
        return sorted(cls._registry.keys())

    @classmethod
    def clear(cls) -> None:
        """Clear registry (useful for test isolation)."""
        cls._registry.clear()


class MockDataSourceAdapter:
    """In-memory mock adapter for unit tests, offline backtesting, and simulation."""

    def __init__(
        self,
        candles: list[OHLCVCandle] | None = None,
        depth_quotes: list[MarketDepthQuote] | None = None,
    ) -> None:
        self._connected = False
        self._candles = candles or []
        self._depth_quotes = depth_quotes or []

    async def connect(self) -> None:
        """Simulate connection."""
        self._connected = True
        logger.info("mock_adapter_connected")

    async def disconnect(self) -> None:
        """Simulate disconnection."""
        self._connected = False
        logger.info("mock_adapter_disconnected")

    async def is_connected(self) -> bool:
        """Return connectivity status."""
        return self._connected

    def add_candle(self, candle: OHLCVCandle) -> None:
        """Append a candle to the mock data store."""
        self._candles.append(candle)

    def add_depth_quote(self, quote: MarketDepthQuote) -> None:
        """Append a depth quote to the mock data store."""
        self._depth_quotes.append(quote)

    async def fetch_historical_candles(
        self,
        instrument: str,
        timeframe: str,
        start_time: datetime,
        end_time: datetime,
    ) -> list[OHLCVCandle]:
        """Filter in-memory candles matching instrument, timeframe, and [start_time, end_time)."""
        start_utc = start_time if start_time.tzinfo is not None else start_time.replace(tzinfo=UTC)
        end_utc = end_time if end_time.tzinfo is not None else end_time.replace(tzinfo=UTC)

        matched: list[OHLCVCandle] = []
        for c in self._candles:
            if c.instrument != instrument or c.timeframe != timeframe:
                continue
            c_ts = (
                c.timestamp if c.timestamp.tzinfo is not None else c.timestamp.replace(tzinfo=UTC)
            )
            if start_utc <= c_ts < end_utc:
                matched.append(c)

        matched.sort(key=lambda x: x.timestamp)
        return matched

    async def subscribe_candles(
        self, instruments: list[str], timeframe: str
    ) -> AsyncIterator[OHLCVCandle]:
        """Stream configured in-memory candles matching instruments and timeframe."""
        target_insts = set(instruments)
        for c in self._candles:
            if c.instrument in target_insts and c.timeframe == timeframe:
                yield c

    async def subscribe_depth(self, instruments: list[str]) -> AsyncIterator[MarketDepthQuote]:
        """Stream configured in-memory depth quotes matching instruments."""
        target_insts = set(instruments)
        for q in self._depth_quotes:
            if q.instrument in target_insts:
                yield q


def create_sample_candle(
    instrument: str = "NSE:RELIANCE",
    ts: datetime | None = None,
    timeframe: str = "1d",
    open_price: str = "2500.0000",
    close_price: str = "2520.0000",
) -> OHLCVCandle:
    """Helper factory for synthetic test candles."""
    now = ts or datetime(2025, 1, 15, 9, 15, tzinfo=UTC)
    o = Decimal(open_price)
    c = Decimal(close_price)
    h = max(o, c) + Decimal("10.0000")
    low = min(o, c) - Decimal("5.0000")
    return OHLCVCandle(
        instrument=instrument,
        timestamp=now,
        open=o,
        high=h,
        low=low,
        close=c,
        volume=100000,
        turnover=Decimal("250000000.0000"),
        timeframe=timeframe,
        quality_state="VALIDATED",
    )


def create_sample_depth_quote(
    instrument: str = "NSE:RELIANCE",
    ts: datetime | None = None,
    best_bid: str = "2500.0000",
    best_ask: str = "2500.5000",
) -> MarketDepthQuote:
    """Helper factory for synthetic test depth quotes."""
    now = ts or datetime(2025, 1, 15, 9, 15, tzinfo=UTC)
    return MarketDepthQuote(
        instrument=instrument,
        timestamp=now,
        bids=[MarketDepthLevel(price=Decimal(best_bid), quantity=500, orders_count=5)],
        asks=[MarketDepthLevel(price=Decimal(best_ask), quantity=450, orders_count=4)],
    )


# Register mock adapter by default
AdapterFactory.register("mock", MockDataSourceAdapter)
