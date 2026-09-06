"""Historical market data ingestion coordinator and persistence pipeline."""

from datetime import UTC, datetime
from pathlib import Path

import structlog
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from src.data.adapter import DataSourceAdapter
from src.data.csv_adapter import CSVDataSourceAdapter
from src.domain.market_data import OHLCVCandle
from src.infrastructure.database import DatabaseManager
from src.infrastructure.models import OHLCVCandleModel
from src.infrastructure.parquet_store import ParquetHistoricalStore

logger = structlog.get_logger(__name__)


class IngestionResult(BaseModel):
    """Execution summary metric for historical market data ingestion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument: str = Field(description="Canonical instrument symbol (e.g. NSE:RELIANCE)")
    timeframe: str = Field(description="Candle timeframe interval (e.g. 1d, 1m)")
    total_candles: int = Field(ge=0, description="Total candles successfully ingested")
    start_time: datetime | None = Field(default=None, description="Earliest ingested timestamp")
    end_time: datetime | None = Field(default=None, description="Latest ingested timestamp")
    partitions_updated: int = Field(ge=0, description="Number of Parquet partitions updated")
    persisted_to_db: bool = Field(default=False, description="Whether persisted to TimescaleDB")


class HistoricalDataLoader:
    """Orchestrates ingestion, validation, and multi-tier persistence of historical candles."""

    def __init__(
        self,
        parquet_store: ParquetHistoricalStore,
        db_manager: DatabaseManager | None = None,
    ) -> None:
        self.parquet_store = parquet_store
        self.db_manager = db_manager

    def validate_candle(self, candle: OHLCVCandle) -> bool:
        """Validate physical sanity rules (DDD §7)."""
        if candle.volume < 0:
            return False
        if not (candle.low <= candle.open <= candle.high):
            return False
        return candle.low <= candle.close <= candle.high

    async def ingest_from_adapter(
        self,
        adapter: DataSourceAdapter,
        instrument: str,
        timeframe: str,
        start_time: datetime,
        end_time: datetime,
        *,
        persist_db: bool = False,
    ) -> IngestionResult:
        """Fetch historical candles from an adapter and persist into Parquet and TimescaleDB."""
        if not await adapter.is_connected():
            await adapter.connect()

        logger.info(
            "fetching_historical_candles_from_adapter",
            instrument=instrument,
            timeframe=timeframe,
            start_time=start_time.isoformat(),
            end_time=end_time.isoformat(),
        )

        raw_candles = await adapter.fetch_historical_candles(
            instrument=instrument,
            timeframe=timeframe,
            start_time=start_time,
            end_time=end_time,
        )

        valid_candles = [c for c in raw_candles if self.validate_candle(c)]
        if not valid_candles:
            logger.warning("no_valid_candles_ingested", instrument=instrument)
            return IngestionResult(
                instrument=instrument,
                timeframe=timeframe,
                total_candles=0,
                start_time=None,
                end_time=None,
                partitions_updated=0,
                persisted_to_db=False,
            )

        # 1. Persist to Parquet historical archive
        written_count = self.parquet_store.write_candles(valid_candles)

        # Calculate partition count (unique year/month pairs)
        partitions = {
            (
                c.timestamp.year
                if c.timestamp.tzinfo is not None
                else c.timestamp.replace(tzinfo=UTC).year,
                c.timestamp.month
                if c.timestamp.tzinfo is not None
                else c.timestamp.replace(tzinfo=UTC).month,
            )
            for c in valid_candles
        }

        # 2. Optionally persist to TimescaleDB
        db_persisted = False
        if persist_db and self.db_manager is not None:
            db_persisted = await self._persist_to_database(valid_candles)

        first_ts = valid_candles[0].timestamp
        last_ts = valid_candles[-1].timestamp

        logger.info(
            "historical_ingestion_complete",
            instrument=instrument,
            candles_persisted=written_count,
            partitions_updated=len(partitions),
            persisted_to_db=db_persisted,
        )

        return IngestionResult(
            instrument=instrument,
            timeframe=timeframe,
            total_candles=len(valid_candles),
            start_time=first_ts,
            end_time=last_ts,
            partitions_updated=len(partitions),
            persisted_to_db=db_persisted,
        )

    async def ingest_csv_file(
        self,
        file_path: Path | str,
        timeframe: str = "1d",
        persist_db: bool = False,
    ) -> list[IngestionResult]:
        """Ingest all instruments found in a CSV file."""
        csv_adapter = CSVDataSourceAdapter(file_path=file_path)
        await csv_adapter.connect()

        # Group candles by instrument
        instrument_map: dict[str, list[OHLCVCandle]] = {}
        for c in csv_adapter._parsed_candles:
            instrument_map.setdefault(c.instrument, []).append(c)

        results: list[IngestionResult] = []
        for inst, candles in instrument_map.items():
            valid_candles = [c for c in candles if self.validate_candle(c)]
            if not valid_candles:
                continue

            self.parquet_store.write_candles(valid_candles)
            partitions = {
                (
                    c.timestamp.year
                    if c.timestamp.tzinfo is not None
                    else c.timestamp.replace(tzinfo=UTC).year,
                    c.timestamp.month
                    if c.timestamp.tzinfo is not None
                    else c.timestamp.replace(tzinfo=UTC).month,
                )
                for c in valid_candles
            }

            db_persisted = False
            if persist_db and self.db_manager is not None:
                db_persisted = await self._persist_to_database(valid_candles)

            result = IngestionResult(
                instrument=inst,
                timeframe=timeframe,
                total_candles=len(valid_candles),
                start_time=valid_candles[0].timestamp,
                end_time=valid_candles[-1].timestamp,
                partitions_updated=len(partitions),
                persisted_to_db=db_persisted,
            )
            results.append(result)

        await csv_adapter.disconnect()
        return results

    async def _persist_to_database(self, candles: list[OHLCVCandle]) -> bool:
        """Upsert candles into the PostgreSQL / TimescaleDB ohlcv_candles table."""
        if self.db_manager is None:
            return False

        try:
            async with self.db_manager.get_session() as session:
                for c in candles:
                    stmt = select(OHLCVCandleModel).where(
                        OHLCVCandleModel.instrument == c.instrument,
                        OHLCVCandleModel.timeframe == c.timeframe,
                        OHLCVCandleModel.timestamp == c.timestamp,
                    )
                    existing = (await session.execute(stmt)).scalar_one_or_none()
                    if existing is None:
                        model = OHLCVCandleModel(
                            instrument=c.instrument,
                            timeframe=c.timeframe,
                            timestamp=c.timestamp,
                            open=c.open,
                            high=c.high,
                            low=c.low,
                            close=c.close,
                            volume=c.volume,
                            turnover=c.turnover,
                            quality_state=c.quality_state,
                        )
                        session.add(model)
                    else:
                        existing.open = c.open
                        existing.high = c.high
                        existing.low = c.low
                        existing.close = c.close
                        existing.volume = c.volume
                        existing.turnover = c.turnover
                        existing.quality_state = c.quality_state
            return True
        except Exception as exc:
            logger.warning("database_persistence_failed", error=str(exc))
            return False
