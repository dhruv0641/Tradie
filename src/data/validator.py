"""Deterministic market data validation pipeline and physical sanity checks (FRD-DATA-6, DDD §7)."""

from collections.abc import Sequence
from decimal import Decimal
from typing import Literal

import structlog
from pydantic import BaseModel, ConfigDict, Field

from src.domain.market_data import OHLCVCandle

logger = structlog.get_logger(__name__)


class ValidationResult(BaseModel):
    """Immutable audit result of a candle validation inspection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    passed: bool = Field(description="True if all physical sanity and outlier checks passed")
    status: Literal["VALIDATED", "QUARANTINED"] = Field(description="Resulting data quality state")
    reasons: list[str] = Field(default_factory=list, description="Audit failure messages")
    candle: OHLCVCandle = Field(description="Candle instance with updated quality_state")


class InMemoryQuarantineStore:
    """In-memory audit store and dead-letter queue for quarantined market data bars."""

    def __init__(self) -> None:
        self._records: list[ValidationResult] = []

    def record(self, result: ValidationResult) -> None:
        """Store a quarantined bar validation result."""
        self._records.append(result)

    def get_all(self) -> list[ValidationResult]:
        """Return all quarantined records."""
        return list(self._records)

    def get_by_instrument(self, instrument: str) -> list[ValidationResult]:
        """Return all quarantined records for a specific instrument."""
        target = instrument.strip().upper()
        return [r for r in self._records if r.candle.instrument == target]

    def count(self) -> int:
        """Return total count of quarantined items."""
        return len(self._records)

    def clear(self) -> None:
        """Drain and reset quarantine store."""
        self._records.clear()


class DataValidationPipeline:
    """Deterministic validation engine enforcing physical reality and outlier filtering (DDD §7).

    Validation Rules:
    1. Physical Price Bounds: High >= Low > 0, Low <= Open <= High, Low <= Close <= High.
    2. Non-Negativity: Volume >= 0, Turnover >= 0.
    3. Timestamp Monotonicity: Timestamp_curr > Timestamp_prev.
    4. Series Continuity: Consistent instrument and timeframe across consecutive bars.
    5. Single-Bar Jump Filter: |Close_curr - Close_prev| / Close_prev <= max_price_jump_pct.
    """

    def __init__(
        self,
        *,
        max_price_jump_pct: Decimal = Decimal("0.20"),
        allow_zero_volume: bool = True,
        quarantine_store: InMemoryQuarantineStore | None = None,
    ) -> None:
        """Initialize data validation pipeline with configurable boundary parameters.

        Args:
            max_price_jump_pct: Return threshold before flagging single-bar anomaly.
            allow_zero_volume: Whether zero volume is permitted (illiquid/off-market bars).
            quarantine_store: Optional dead-letter store to record quarantined bars.
        """
        self.max_price_jump_pct = max_price_jump_pct
        self.allow_zero_volume = allow_zero_volume
        self.quarantine_store = quarantine_store or InMemoryQuarantineStore()

    @staticmethod
    def _check_physical_bounds(current: OHLCVCandle, reasons: list[str]) -> None:
        """Enforce positivity and geometric OHLC bounding constraints."""
        if (
            current.open <= Decimal("0")
            or current.high <= Decimal("0")
            or current.low <= Decimal("0")
            or current.close <= Decimal("0")
        ):
            reasons.append("Non-positive price detected in OHLC components")

        if current.high < current.low:
            reasons.append(f"High price ({current.high}) is less than low price ({current.low})")
        if not (current.low <= current.open <= current.high):
            reasons.append(
                f"Open price ({current.open}) falls outside "
                f"[low={current.low}, high={current.high}]"
            )
        if not (current.low <= current.close <= current.high):
            reasons.append(
                f"Close price ({current.close}) falls outside "
                f"[low={current.low}, high={current.high}]"
            )

    def _check_volume_and_turnover(self, current: OHLCVCandle, reasons: list[str]) -> None:
        """Enforce volume and turnover non-negativity."""
        if current.volume < 0:
            reasons.append(f"Negative volume detected ({current.volume})")
        elif not self.allow_zero_volume and current.volume == 0:
            reasons.append("Zero volume not permitted for this series")

        if current.turnover < Decimal("0"):
            reasons.append(f"Negative turnover detected ({current.turnover})")

    def _check_continuity_and_jump(
        self,
        current: OHLCVCandle,
        previous: OHLCVCandle,
        reasons: list[str],
    ) -> None:
        """Enforce instrument identity, timeframe continuity, and jump thresholds."""
        if current.instrument != previous.instrument:
            reasons.append(
                f"Instrument mismatch: current ({current.instrument}) "
                f"!= previous ({previous.instrument})"
            )
        if current.timeframe != previous.timeframe:
            reasons.append(
                f"Timeframe mismatch: current ({current.timeframe}) "
                f"!= previous ({previous.timeframe})"
            )
        if current.timestamp <= previous.timestamp:
            reasons.append(
                f"Non-monotonic timestamp: current ({current.timestamp.isoformat()}) "
                f"<= previous ({previous.timestamp.isoformat()})"
            )

        if previous.close > Decimal("0"):
            pct_change = abs(current.close - previous.close) / previous.close
            if pct_change > self.max_price_jump_pct:
                reasons.append(
                    f"Extreme single-bar price jump ({pct_change:.2%}) "
                    f"exceeds limit ({self.max_price_jump_pct:.2%})"
                )

    def validate_candle(
        self,
        current: OHLCVCandle,
        previous: OHLCVCandle | None = None,
    ) -> ValidationResult:
        """Validate an individual OHLCVCandle against physical reality rules and jump thresholds.

        Args:
            current: The candle under inspection.
            previous: Optional chronologically preceding candle in the same series.

        Returns:
            ValidationResult with passed boolean, VALIDATED or QUARANTINED status, and audit log.
        """
        reasons: list[str] = []

        self._check_physical_bounds(current, reasons)
        self._check_volume_and_turnover(current, reasons)

        if previous is not None:
            self._check_continuity_and_jump(current, previous, reasons)

        if reasons:
            quarantined_candle = current.model_copy(update={"quality_state": "QUARANTINED"})
            logger.warning(
                "market_data_quarantined",
                instrument=current.instrument,
                timestamp=current.timestamp.isoformat(),
                timeframe=current.timeframe,
                reasons=reasons,
            )
            result = ValidationResult(
                passed=False,
                status="QUARANTINED",
                reasons=reasons,
                candle=quarantined_candle,
            )
            self.quarantine_store.record(result)
            return result

        validated_candle = (
            current
            if current.quality_state == "VALIDATED"
            else current.model_copy(update={"quality_state": "VALIDATED"})
        )
        return ValidationResult(
            passed=True,
            status="VALIDATED",
            reasons=[],
            candle=validated_candle,
        )

    def validate_sequence(
        self,
        candles: Sequence[OHLCVCandle],
    ) -> tuple[list[OHLCVCandle], list[ValidationResult]]:
        """Validate a chronological sequence of candles, partitioning into valid and quarantined.

        Args:
            candles: Chronological sequence of OHLCVCandle bars.

        Returns:
            Tuple of (list of VALIDATED candles, list of QUARANTINED ValidationResults).
        """
        valid_candles: list[OHLCVCandle] = []
        quarantined_results: list[ValidationResult] = []
        prev_valid: OHLCVCandle | None = None

        for candle in candles:
            res = self.validate_candle(candle, previous=prev_valid)
            if res.passed:
                valid_candles.append(res.candle)
                prev_valid = res.candle
            else:
                quarantined_results.append(res)

        return valid_candles, quarantined_results
