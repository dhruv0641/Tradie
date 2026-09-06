"""Real-time market data feed staleness monitoring and SLA enforcement (FRD-DATA-9, NFR-DATA-1)."""

from datetime import UTC, datetime

import structlog
from pydantic import BaseModel, ConfigDict, Field

from src.domain.market_data import MarketTick, OHLCVCandle

logger = structlog.get_logger(__name__)


class StalenessStatus(BaseModel):
    """Immutable status report of an instrument's feed freshness."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument: str = Field(min_length=1, description="Canonical instrument identifier")
    is_stale: bool = Field(description="True if feed age exceeds maximum allowed SLA threshold")
    elapsed_seconds: float = Field(
        ge=0.0, description="Elapsed seconds since last verified arrival"
    )
    threshold_seconds: float = Field(
        gt=0.0, description="Maximum allowable staleness limit in seconds"
    )
    last_seen_timestamp: datetime | None = Field(
        default=None, description="UTC timestamp of last recorded arrival"
    )
    checked_at: datetime = Field(description="UTC timestamp when staleness was checked")
    reason: str | None = Field(
        default=None, description="Detailed reason for staleness flag, if stale"
    )


class StalenessMonitor:
    """Real-time monitor tracking arrival timestamps and enforcing staleness thresholds.

    Per NFR-DATA-1, if elapsed time since last valid message exceeds max_staleness_seconds
    (default 10.0s), the instrument is marked as STALE, triggering trading decision suppression.
    """

    def __init__(self, *, max_staleness_seconds: float = 10.0) -> None:
        """Initialize staleness monitor with configurable SLA window.

        Args:
            max_staleness_seconds: Maximum allowable delay in seconds before marking stale.
        """
        if max_staleness_seconds <= 0.0:
            msg = f"max_staleness_seconds must be positive, got {max_staleness_seconds}"
            raise ValueError(msg)

        self.max_staleness_seconds = max_staleness_seconds
        self._last_arrival: dict[str, datetime] = {}

    def record_heartbeat(
        self,
        instrument: str,
        arrival_time: datetime | None = None,
    ) -> None:
        """Record the arrival of a valid data event for an instrument.

        Args:
            instrument: Canonical instrument symbol (e.g. NSE:RELIANCE).
            arrival_time: Optional arrival timestamp; defaults to current UTC time.
        """
        symbol = instrument.strip().upper()
        if not symbol:
            msg = "Instrument identifier cannot be empty"
            raise ValueError(msg)

        ts = arrival_time or datetime.now(UTC)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)

        self._last_arrival[symbol] = ts

    def record_candle(
        self,
        candle: OHLCVCandle,
        arrival_time: datetime | None = None,
    ) -> None:
        """Convenience method to register a candle arrival."""
        self.record_heartbeat(candle.instrument, arrival_time or candle.timestamp)

    def record_tick(
        self,
        tick: MarketTick,
        arrival_time: datetime | None = None,
    ) -> None:
        """Convenience method to register a market tick arrival."""
        self.record_heartbeat(tick.instrument, arrival_time or tick.timestamp)

    def check_staleness(
        self,
        instrument: str,
        current_time: datetime | None = None,
    ) -> StalenessStatus:
        """Check whether an instrument's incoming feed has breached the staleness SLA.

        Args:
            instrument: Canonical instrument symbol.
            current_time: Optional evaluation timestamp; defaults to current UTC time.

        Returns:
            StalenessStatus containing is_stale boolean, elapsed time, and diagnostics.
        """
        symbol = instrument.strip().upper()
        now = current_time or datetime.now(UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)

        if symbol not in self._last_arrival:
            return StalenessStatus(
                instrument=symbol,
                is_stale=True,
                elapsed_seconds=float("inf"),
                threshold_seconds=self.max_staleness_seconds,
                last_seen_timestamp=None,
                checked_at=now,
                reason="NO_DATA_RECEIVED",
            )

        last_seen = self._last_arrival[symbol]
        elapsed = max(0.0, (now - last_seen).total_seconds())
        is_stale = elapsed > self.max_staleness_seconds

        if is_stale:
            logger.warning(
                "market_data_stale",
                instrument=symbol,
                elapsed_seconds=elapsed,
                threshold_seconds=self.max_staleness_seconds,
            )
            reason = "TICK_TIMEOUT"
        else:
            reason = None

        return StalenessStatus(
            instrument=symbol,
            is_stale=is_stale,
            elapsed_seconds=elapsed,
            threshold_seconds=self.max_staleness_seconds,
            last_seen_timestamp=last_seen,
            checked_at=now,
            reason=reason,
        )

    def check_all(
        self,
        current_time: datetime | None = None,
    ) -> dict[str, StalenessStatus]:
        """Evaluate staleness across all actively tracked instruments."""
        now = current_time or datetime.now(UTC)
        return {
            symbol: self.check_staleness(symbol, current_time=now) for symbol in self._last_arrival
        }

    def get_tracked_instruments(self) -> list[str]:
        """Return list of all actively monitored instrument symbols."""
        return sorted(self._last_arrival.keys())

    def reset(self, instrument: str | None = None) -> None:
        """Reset arrival tracking for a single instrument or all instruments."""
        if instrument is not None:
            self._last_arrival.pop(instrument.strip().upper(), None)
        else:
            self._last_arrival.clear()
