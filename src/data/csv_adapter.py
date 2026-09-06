"""CSV historical data adapter supporting standard OHLCV and NSE Bhavcopy formats."""

import csv
import io
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import structlog

from src.data.adapter import AdapterFactory
from src.domain.market_data import MarketDepthQuote, OHLCVCandle

logger = structlog.get_logger(__name__)


class CSVDataSourceAdapter:
    """Ingests historical OHLCV data from CSV files and NSE Bhavcopy archives."""

    def __init__(
        self,
        file_path: Path | str | None = None,
        csv_content: str | None = None,
    ) -> None:
        self.file_path = Path(file_path) if file_path else None
        self.csv_content = csv_content
        self._connected = False
        self._parsed_candles: list[OHLCVCandle] = []

    async def connect(self) -> None:
        """Parse source CSV upon connection."""
        self._connected = True
        self._parsed_candles = self._load_candles()
        logger.info(
            "csv_adapter_connected",
            file_path=str(self.file_path) if self.file_path else "in-memory",
            candles_loaded=len(self._parsed_candles),
        )

    async def disconnect(self) -> None:
        """Clear cache and disconnect."""
        self._connected = False
        self._parsed_candles.clear()
        logger.info("csv_adapter_disconnected")

    async def is_connected(self) -> bool:
        """Return connection status."""
        return self._connected

    def _parse_timestamp(self, ts_str: str) -> datetime:
        """Parse various date and timestamp string representations into UTC datetime."""
        cleaned = ts_str.strip()
        # Format 1: ISO 8601 (2025-01-15T09:15:00 or 2025-01-15T09:15:00Z)
        if "T" in cleaned:
            dt = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)

        # Format 2: Standard datetime 'YYYY-MM-DD HH:MM:SS'
        if " " in cleaned:
            return datetime.strptime(cleaned, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)

        # Format 3: Date only 'YYYY-MM-DD'
        if len(cleaned) == 10 and cleaned[4] == "-" and cleaned[7] == "-":
            return datetime.strptime(cleaned, "%Y-%m-%d").replace(tzinfo=UTC)

        # Format 4: NSE Bhavcopy date 'DD-Mon-YYYY' or 'DD-MON-YYYY' (e.g. 15-Jan-2025)
        try:
            return datetime.strptime(cleaned.title(), "%d-%b-%Y").replace(tzinfo=UTC)
        except ValueError:
            pass

        # Fallback to generic fromisoformat
        dt = datetime.fromisoformat(cleaned)
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)

    def _normalize_symbol(self, raw_symbol: str) -> str:
        """Normalize equity symbol to canonical prefix: NSE:{SYMBOL}."""
        sym = raw_symbol.strip().upper()
        if sym.startswith("NSE:"):
            return sym
        return f"NSE:{sym}"

    def _parse_bhavcopy_row(
        self, row: dict[str, str], field_map: dict[str, str]
    ) -> OHLCVCandle | None:
        """Parse a single NSE Bhavcopy CSV row."""
        series_col = field_map.get("series")
        if series_col and row[series_col].strip().upper() not in {"EQ", ""}:
            return None

        instrument = self._normalize_symbol(row[field_map["symbol"]])
        ts = self._parse_timestamp(row[field_map["timestamp"]])

        open_val = Decimal(row[field_map["open"]].strip()).quantize(Decimal("0.0001"))
        high_val = Decimal(row[field_map["high"]].strip()).quantize(Decimal("0.0001"))
        low_val = Decimal(row[field_map["low"]].strip()).quantize(Decimal("0.0001"))
        close_val = Decimal(row[field_map["close"]].strip()).quantize(Decimal("0.0001"))

        vol_col = field_map.get("tottrdqty") or field_map.get("volume")
        vol = int(float(row[vol_col].strip())) if vol_col else 0

        val_col = field_map.get("tottrdval") or field_map.get("turnover")
        turnover = (
            Decimal(row[val_col].strip()).quantize(Decimal("0.0001"))
            if val_col
            else Decimal("0.0000")
        )

        return OHLCVCandle(
            instrument=instrument,
            timestamp=ts,
            open=open_val,
            high=max(high_val, open_val, close_val),
            low=min(low_val, open_val, close_val),
            close=close_val,
            volume=vol,
            turnover=turnover,
            timeframe="1d",
            quality_state="VALIDATED",
        )

    def _parse_standard_row(self, row: dict[str, str], field_map: dict[str, str]) -> OHLCVCandle:
        """Parse a single standard OHLCV CSV row."""
        raw_sym = row.get(field_map.get("instrument", ""), "NSE:UNKNOWN")
        if not raw_sym or raw_sym == "NSE:UNKNOWN":
            raw_sym = row.get(field_map.get("symbol", ""), "NSE:UNKNOWN")
        instrument = self._normalize_symbol(raw_sym)

        ts = self._parse_timestamp(row[field_map["timestamp"]])

        open_val = Decimal(row[field_map["open"]].strip()).quantize(Decimal("0.0001"))
        high_val = Decimal(row[field_map["high"]].strip()).quantize(Decimal("0.0001"))
        low_val = Decimal(row[field_map["low"]].strip()).quantize(Decimal("0.0001"))
        close_val = Decimal(row[field_map["close"]].strip()).quantize(Decimal("0.0001"))

        vol_col = field_map.get("volume")
        vol = int(float(row[vol_col].strip())) if vol_col else 0

        turn_col = field_map.get("turnover")
        turnover = (
            Decimal(row[turn_col].strip()).quantize(Decimal("0.0001"))
            if turn_col
            else Decimal("0.0000")
        )

        tf_col = field_map.get("timeframe")
        timeframe = row[tf_col].strip() if tf_col else "1d"

        return OHLCVCandle(
            instrument=instrument,
            timestamp=ts,
            open=open_val,
            high=max(high_val, open_val, close_val),
            low=min(low_val, open_val, close_val),
            close=close_val,
            volume=vol,
            turnover=turnover,
            timeframe=timeframe,
            quality_state="VALIDATED",
        )

    def _load_candles(self) -> list[OHLCVCandle]:
        """Read and parse CSV stream into strongly-typed OHLCVCandle models."""
        if self.csv_content is not None:
            reader_stream = io.StringIO(self.csv_content)
        elif self.file_path is not None and self.file_path.exists():
            reader_stream = io.StringIO(self.file_path.read_text(encoding="utf-8"))
        else:
            return []

        csv_reader = csv.DictReader(reader_stream)
        if csv_reader.fieldnames is None:
            return []

        field_map = {f.strip().lower(): f for f in csv_reader.fieldnames}
        is_bhavcopy = "symbol" in field_map and (
            "tottrdqty" in field_map or "tottrdval" in field_map
        )

        candles: list[OHLCVCandle] = []
        for row in csv_reader:
            try:
                candle = (
                    self._parse_bhavcopy_row(row, field_map)
                    if is_bhavcopy
                    else self._parse_standard_row(row, field_map)
                )
                if candle is not None:
                    candles.append(candle)
            except Exception as exc:
                logger.warning("csv_row_parse_error", row=row, error=str(exc))
                continue

        candles.sort(key=lambda x: x.timestamp)
        return candles

    async def fetch_historical_candles(
        self,
        instrument: str,
        timeframe: str,
        start_time: datetime,
        end_time: datetime,
    ) -> list[OHLCVCandle]:
        """Query parsed candles strictly within [start_time, end_time)."""
        if not self._connected:
            self._parsed_candles = self._load_candles()

        norm_inst = self._normalize_symbol(instrument)
        start_utc = start_time if start_time.tzinfo is not None else start_time.replace(tzinfo=UTC)
        end_utc = end_time if end_time.tzinfo is not None else end_time.replace(tzinfo=UTC)

        matched: list[OHLCVCandle] = []
        for c in self._parsed_candles:
            if c.instrument != norm_inst or c.timeframe != timeframe:
                continue
            c_ts = (
                c.timestamp if c.timestamp.tzinfo is not None else c.timestamp.replace(tzinfo=UTC)
            )
            if start_utc <= c_ts < end_utc:
                matched.append(c)

        return matched

    async def subscribe_candles(
        self, instruments: list[str], timeframe: str
    ) -> AsyncIterator[OHLCVCandle]:
        """Stream parsed candles sequentially."""
        target_insts = {self._normalize_symbol(i) for i in instruments}
        for c in self._parsed_candles:
            if c.instrument in target_insts and c.timeframe == timeframe:
                yield c

    async def subscribe_depth(self, instruments: list[str]) -> AsyncIterator[MarketDepthQuote]:
        """CSV adapter does not contain Level-2 depth data; empty stream."""
        _ = instruments
        if False:
            yield None  # type: ignore[unreachable]


# Register csv adapter in factory
AdapterFactory.register("csv", CSVDataSourceAdapter)
