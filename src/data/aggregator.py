"""Real-time tick-to-candle aggregator assembling canonical OHLCV bars."""

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog

from src.domain.market_data import MarketTick, OHLCVCandle

logger = structlog.get_logger(__name__)

# Type alias for sync or async candle callbacks
CandleCallback = Callable[[OHLCVCandle], Coroutine[Any, Any, None] | None]


def parse_timeframe_seconds(timeframe: str) -> int:
    """Parse timeframe string (e.g. '1m', '5m', '15m', '1h', '1d') into total seconds."""
    tf = timeframe.strip().lower()
    if tf.endswith("m"):
        return int(tf[:-1]) * 60
    if tf.endswith("h"):
        return int(tf[:-1]) * 3600
    if tf.endswith("d"):
        return int(tf[:-1]) * 86400
    if tf.endswith("s"):
        return int(tf[:-1])
    msg = f"Unsupported timeframe specification: '{timeframe}'"
    raise ValueError(msg)


def floor_to_timeframe(dt: datetime, timeframe: str) -> datetime:
    """Calculate the lower interval boundary for a given timestamp and timeframe."""
    ts_utc = dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
    total_seconds = parse_timeframe_seconds(timeframe)

    # For daily timeframes, floor to 00:00:00 UTC
    if timeframe.lower().endswith("d"):
        return datetime(ts_utc.year, ts_utc.month, ts_utc.day, tzinfo=UTC)

    # For intraday timeframes, align to unix epoch modulo interval
    epoch = int(ts_utc.timestamp())
    floored_epoch = (epoch // total_seconds) * total_seconds
    return datetime.fromtimestamp(floored_epoch, tz=UTC)


@dataclass
class _ActiveBarState:
    """Internal mutable accumulator for an in-flight unsealed candle."""

    instrument: str
    timeframe: str
    window_start: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    turnover: Decimal
    tick_count: int

    def to_candle(self) -> OHLCVCandle:
        """Seal current state into an immutable OHLCVCandle."""
        return OHLCVCandle(
            instrument=self.instrument,
            timestamp=self.window_start,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            turnover=self.turnover,
            timeframe=self.timeframe,
            quality_state="VALIDATED",
        )


class CandleAggregator:
    """Buffers real-time market ticks and aggregates them into exact OHLCV candles (TRD-PIPE-3)."""

    def __init__(
        self,
        timeframes: list[str] | None = None,
        callbacks: list[CandleCallback] | None = None,
    ) -> None:
        """Initialize aggregator with supported timeframes and listeners.

        Args:
            timeframes: List of intervals to aggregate (e.g. ['1m', '5m']). Defaults to ['1m'].
            callbacks: Callbacks invoked when a candle interval is sealed.
        """
        self.timeframes = [tf.strip().lower() for tf in (timeframes or ["1m"])]
        self._callbacks: list[CandleCallback] = list(callbacks or [])

        # Active in-flight bars indexed by (instrument, timeframe)
        self._active_bars: dict[tuple[str, str], _ActiveBarState] = {}

        # Sealed closed candles buffer awaiting persistence/processing
        self._closed_candles: list[OHLCVCandle] = []

        # Total ticks processed counter
        self._total_ticks_processed: int = 0
        self._background_tasks: set[asyncio.Task[Any]] = set()

    @property
    def total_ticks_processed(self) -> int:
        """Return cumulative count of ticks processed."""
        return self._total_ticks_processed

    def register_callback(self, callback: CandleCallback) -> None:
        """Register a callback for closed candle notifications."""
        self._callbacks.append(callback)

    def process_tick(self, tick: MarketTick) -> list[OHLCVCandle]:
        """Ingest a market tick and update active bars across all configured timeframes.

        If a tick crosses an interval boundary, the previous candle is sealed,
        emitted to registered callbacks, and returned.

        Args:
            tick: Validated incoming market trade tick.

        Returns:
            List of newly closed OHLCVCandle bars sealed by this tick.
        """
        self._total_ticks_processed += 1
        newly_closed: list[OHLCVCandle] = []

        turnover = (
            tick.turnover
            if tick.turnover > Decimal("0")
            else (tick.last_price * Decimal(tick.volume))
        )

        for tf in self.timeframes:
            window_start = floor_to_timeframe(tick.timestamp, tf)
            key = (tick.instrument, tf)
            active = self._active_bars.get(key)

            if active is None:
                # First tick for this instrument and timeframe: initialize new active bar
                self._active_bars[key] = _ActiveBarState(
                    instrument=tick.instrument,
                    timeframe=tf,
                    window_start=window_start,
                    open=tick.last_price,
                    high=tick.last_price,
                    low=tick.last_price,
                    close=tick.last_price,
                    volume=tick.volume,
                    turnover=turnover,
                    tick_count=1,
                )
            elif window_start == active.window_start:
                # Tick belongs to the current bar window: update running extrema
                active.high = max(active.high, tick.last_price)
                active.low = min(active.low, tick.last_price)
                active.close = tick.last_price
                active.volume += tick.volume
                active.turnover += turnover
                active.tick_count += 1
            elif window_start > active.window_start:
                # New interval reached: seal the previous bar
                closed_candle = active.to_candle()
                self._closed_candles.append(closed_candle)
                newly_closed.append(closed_candle)

                self._dispatch_candle(closed_candle)

                # Initialize next active bar with this tick
                self._active_bars[key] = _ActiveBarState(
                    instrument=tick.instrument,
                    timeframe=tf,
                    window_start=window_start,
                    open=tick.last_price,
                    high=tick.last_price,
                    low=tick.last_price,
                    close=tick.last_price,
                    volume=tick.volume,
                    turnover=turnover,
                    tick_count=1,
                )
            else:
                # Out-of-order tick arriving with an older timestamp
                logger.warning(
                    "out_of_order_tick_ignored",
                    instrument=tick.instrument,
                    timeframe=tf,
                    tick_timestamp=tick.timestamp.isoformat(),
                    active_window=active.window_start.isoformat(),
                )

        return newly_closed

    def _dispatch_candle(self, candle: OHLCVCandle) -> None:
        """Notify registered callbacks of sealed candle."""
        for cb in self._callbacks:
            try:
                res = cb(candle)
                if asyncio.iscoroutine(res):
                    try:
                        loop = asyncio.get_running_loop()
                        task = loop.create_task(res)
                        self._background_tasks.add(task)
                        task.add_done_callback(self._background_tasks.discard)
                    except RuntimeError:
                        # No running event loop in thread; run synchronously
                        asyncio.run(res)
            except Exception as e:
                logger.error(
                    "candle_callback_failed",
                    instrument=candle.instrument,
                    timeframe=candle.timeframe,
                    error=str(e),
                )

    def get_active_candle(self, instrument: str, timeframe: str) -> OHLCVCandle | None:
        """Return point-in-time snapshot of the current unsealed bar in progress."""
        active = self._active_bars.get((instrument, timeframe.strip().lower()))
        if active is None:
            return None
        return active.to_candle()

    def force_close_all(self) -> list[OHLCVCandle]:
        """Force seal all currently active in-flight bars (e.g. at market close).

        Returns:
            List of all sealed OHLCVCandle instances.
        """
        closed: list[OHLCVCandle] = []
        for key in list(self._active_bars.keys()):
            active = self._active_bars.pop(key)
            candle = active.to_candle()
            self._closed_candles.append(candle)
            closed.append(candle)
            self._dispatch_candle(candle)

        return closed

    def flush_closed_candles(self) -> list[OHLCVCandle]:
        """Drain and return all sealed candles waiting in the buffer."""
        flushed = self._closed_candles
        self._closed_candles = []
        return flushed
