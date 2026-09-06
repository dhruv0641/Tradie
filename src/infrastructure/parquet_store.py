"""High-throughput partitioned Parquet historical storage manager."""

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import structlog

from src.domain.market_data import OHLCVCandle

logger = structlog.get_logger(__name__)

# PyArrow schema preserving exact financial precision (DDD §6, TRD-DATA-1)
CANDLE_SCHEMA = pa.schema(
    [
        ("timestamp", pa.timestamp("us", tz="UTC")),
        ("instrument", pa.string()),
        ("timeframe", pa.string()),
        ("open", pa.decimal128(18, 4)),
        ("high", pa.decimal128(18, 4)),
        ("low", pa.decimal128(18, 4)),
        ("close", pa.decimal128(18, 4)),
        ("volume", pa.int64()),
        ("turnover", pa.decimal128(18, 4)),
        ("quality_state", pa.string()),
    ]
)


class ParquetHistoricalStore:
    """Manages partitioned Snappy-compressed Parquet historical archive."""

    def __init__(self, base_dir: Path | str = "data/historical") -> None:
        self.base_dir = Path(base_dir)

    def _get_partition_dir(self, timeframe: str, instrument: str, year: int, month: int) -> Path:
        """Construct directory path: {base_dir}/{timeframe}/{instrument}/year={YYYY}/month={MM}."""
        return self.base_dir / timeframe / instrument / f"year={year:04d}" / f"month={month:02d}"

    def write_candles(self, candles: Sequence[OHLCVCandle]) -> int:
        """Write and deduplicate candles into partitioned Snappy Parquet files.

        Returns:
            The total number of candles written/updated.
        """
        if not candles:
            return 0

        # Group candles by (timeframe, instrument, year, month)
        grouped: dict[tuple[str, str, int, int], list[OHLCVCandle]] = defaultdict(list)
        for candle in candles:
            ts = (
                candle.timestamp
                if candle.timestamp.tzinfo is not None
                else candle.timestamp.replace(tzinfo=UTC)
            )
            key = (candle.timeframe, candle.instrument, ts.year, ts.month)
            grouped[key].append(candle)

        total_written = 0

        for (timeframe, instrument, year, month), candle_batch in grouped.items():
            partition_dir = self._get_partition_dir(timeframe, instrument, year, month)
            partition_dir.mkdir(parents=True, exist_ok=True)
            partition_file = partition_dir / "data.parquet"

            existing_candles_dict: dict[tuple[str, datetime], OHLCVCandle] = {}

            # Read existing partition if present to handle deduplication
            if partition_file.exists():
                existing_candles = self._read_file_to_candles(partition_file)
                for c in existing_candles:
                    existing_candles_dict[(c.instrument, c.timestamp)] = c

            # Merge / overwrite with new incoming batch
            for c in candle_batch:
                ts = (
                    c.timestamp
                    if c.timestamp.tzinfo is not None
                    else c.timestamp.replace(tzinfo=UTC)
                )
                existing_candles_dict[(c.instrument, ts)] = c

            # Sort merged candles by timestamp ascending
            merged_candles = sorted(existing_candles_dict.values(), key=lambda x: x.timestamp)

            # Convert to PyArrow Table
            table = self._candles_to_table(merged_candles)

            # Write with Snappy compression
            pq.write_table(
                table,
                partition_file,
                compression="snappy",
                use_dictionary=True,
            )
            total_written += len(candle_batch)

        logger.info(
            "parquet_candles_persisted",
            candles_written=total_written,
            partitions=len(grouped),
        )
        return total_written

    def read_candles(
        self,
        instrument: str,
        start_time: datetime,
        end_time: datetime,
        timeframe: str,
    ) -> list[OHLCVCandle]:
        """Read point-in-time ordered candles strictly within [start_time, end_time).

        Zero-lookahead guarantee: strictly excludes timestamps >= end_time.
        """
        table = self.read_table(instrument, start_time, end_time, timeframe)
        if table is None or table.num_rows == 0:
            return []

        return self._table_to_candles(table)

    def read_dataframe(
        self,
        instrument: str,
        start_time: datetime,
        end_time: datetime,
        timeframe: str,
    ) -> pd.DataFrame:
        """Read point-in-time candles as a Pandas DataFrame for vectorized backtesting."""
        table = self.read_table(instrument, start_time, end_time, timeframe)
        if table is None or table.num_rows == 0:
            return pd.DataFrame()

        df: pd.DataFrame = table.to_pandas()
        return df

    def read_table(
        self,
        instrument: str,
        start_time: datetime,
        end_time: datetime,
        timeframe: str,
    ) -> pa.Table | None:
        """Read point-in-time candles as a PyArrow Table within [start_time, end_time)."""
        start_utc = start_time if start_time.tzinfo is not None else start_time.replace(tzinfo=UTC)
        end_utc = end_time if end_time.tzinfo is not None else end_time.replace(tzinfo=UTC)

        if start_utc >= end_utc:
            return None

        instrument_dir = self.base_dir / timeframe / instrument
        if not instrument_dir.exists():
            return None

        # Find all candidate month partitions
        matching_tables: list[pa.Table] = []

        # Find all year/month subdirectories
        for year_dir in sorted(instrument_dir.glob("year=*")):
            try:
                year_val = int(year_dir.name.split("=")[1])
            except ValueError:
                continue

            if year_val < start_utc.year or year_val > end_utc.year:
                continue

            for month_dir in sorted(year_dir.glob("month=*")):
                try:
                    month_val = int(month_dir.name.split("=")[1])
                except ValueError:
                    continue

                # Check if month overlaps with start_utc and end_utc
                if (year_val == start_utc.year and month_val < start_utc.month) or (
                    year_val == end_utc.year and month_val > end_utc.month
                ):
                    continue

                partition_file = month_dir / "data.parquet"
                if not partition_file.exists():
                    continue

                table = pq.read_table(partition_file, schema=CANDLE_SCHEMA)

                # Filter strictly [start_utc, end_utc)
                # PyArrow compute timestamp filter
                filter_mask = pc.and_(
                    pc.greater_equal(table["timestamp"], pa.scalar(start_utc)),
                    pc.less(table["timestamp"], pa.scalar(end_utc)),
                )
                filtered = table.filter(filter_mask)
                if filtered.num_rows > 0:
                    matching_tables.append(filtered)

        if not matching_tables:
            return None

        combined = pa.concat_tables(matching_tables)
        # Sort by timestamp ascending
        sort_indices = pc.sort_indices(combined["timestamp"])
        sorted_table = combined.take(sort_indices)
        return cast("pa.Table", sorted_table)

    def _candles_to_table(self, candles: Sequence[OHLCVCandle]) -> pa.Table:
        """Convert a sequence of OHLCVCandle instances into a typed PyArrow Table."""
        pydict = {
            "timestamp": [c.timestamp for c in candles],
            "instrument": [c.instrument for c in candles],
            "timeframe": [c.timeframe for c in candles],
            "open": [c.open for c in candles],
            "high": [c.high for c in candles],
            "low": [c.low for c in candles],
            "close": [c.close for c in candles],
            "volume": [c.volume for c in candles],
            "turnover": [c.turnover for c in candles],
            "quality_state": [c.quality_state for c in candles],
        }
        return pa.Table.from_pydict(pydict, schema=CANDLE_SCHEMA)

    def _read_file_to_candles(self, path: Path) -> list[OHLCVCandle]:
        """Read a single parquet file and parse into OHLCVCandle entities."""
        table = pq.read_table(path, schema=CANDLE_SCHEMA)
        return self._table_to_candles(table)

    def _table_to_candles(self, table: pa.Table) -> list[OHLCVCandle]:
        """Convert PyArrow Table into a list of canonical OHLCVCandle domain entities."""
        pydict = table.to_pydict()
        count = table.num_rows
        candles: list[OHLCVCandle] = []

        timestamps = pydict["timestamp"]
        instruments = pydict["instrument"]
        timeframes = pydict["timeframe"]
        opens = pydict["open"]
        highs = pydict["high"]
        lows = pydict["low"]
        closes = pydict["close"]
        volumes = pydict["volume"]
        turnovers = pydict["turnover"]
        quality_states = pydict["quality_state"]

        for i in range(count):
            candle = OHLCVCandle(
                timestamp=timestamps[i],
                instrument=instruments[i],
                timeframe=timeframes[i],
                open=opens[i],
                high=highs[i],
                low=lows[i],
                close=closes[i],
                volume=volumes[i],
                turnover=turnovers[i],
                quality_state=quality_states[i],
            )
            candles.append(candle)

        return candles
