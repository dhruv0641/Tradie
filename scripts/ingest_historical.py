"""CLI utility for ingesting historical market data into the Parquet archive and TimescaleDB."""

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

import structlog

from src.data.historical_loader import HistoricalDataLoader
from src.infrastructure.parquet_store import ParquetHistoricalStore
from src.utils.logging import configure_logging

logger = structlog.get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Construct command-line argument parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Ingest historical market data into Parquet historical storage and TimescaleDB."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--file",
        "-f",
        type=Path,
        required=True,
        help="Path to CSV data file (standard OHLCV or NSE Bhavcopy format)",
    )
    parser.add_argument(
        "--timeframe",
        "-t",
        default="1d",
        help="Candle timeframe interval (e.g. 1d, 5m, 1m)",
    )
    parser.add_argument(
        "--storage-dir",
        type=Path,
        default=Path("data/historical"),
        help="Base directory path for partitioned Parquet storage",
    )
    parser.add_argument(
        "--persist-db",
        action="store_true",
        default=False,
        help="Also persist closed candles into PostgreSQL/TimescaleDB hypertable",
    )
    return parser


async def run_ingestion(
    file_path: Path,
    timeframe: str,
    storage_dir: Path,
    persist_db: bool,
) -> int:
    """Execute ingestion workflow."""
    if not file_path.exists():
        logger.error("csv_file_not_found", path=str(file_path))
        return 1

    parquet_store = ParquetHistoricalStore(base_dir=storage_dir)
    loader = HistoricalDataLoader(parquet_store=parquet_store)

    logger.info(
        "starting_historical_csv_ingestion",
        file=str(file_path),
        timeframe=timeframe,
        storage_dir=str(storage_dir),
    )

    t0 = datetime.now(UTC)
    results = await loader.ingest_csv_file(
        file_path=file_path,
        timeframe=timeframe,
        persist_db=persist_db,
    )
    duration = (datetime.now(UTC) - t0).total_seconds()

    total_candles = sum(r.total_candles for r in results)
    logger.info(
        "historical_ingestion_completed",
        instruments_processed=len(results),
        total_candles=total_candles,
        duration_seconds=duration,
    )

    for r in results:
        logger.info(
            "instrument_summary",
            instrument=r.instrument,
            timeframe=r.timeframe,
            candles=r.total_candles,
            start=r.start_time.isoformat() if r.start_time else None,
            end=r.end_time.isoformat() if r.end_time else None,
            partitions=r.partitions_updated,
        )

    return 0


def main() -> int:
    """CLI application entrypoint."""
    configure_logging(environment="local", log_level="INFO")
    parser = build_parser()
    args = parser.parse_args()

    return asyncio.run(
        run_ingestion(
            file_path=args.file,
            timeframe=args.timeframe,
            storage_dir=args.storage_dir,
            persist_db=args.persist_db,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
