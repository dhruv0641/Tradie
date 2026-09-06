"""Database connection engine and session lifecycle manager."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.config.models import DatabaseConfig

logger = structlog.get_logger(__name__)


class DatabaseManager:
    """Manages AsyncIO PostgreSQL / TimescaleDB engine and session lifecycle."""

    def __init__(self, config: DatabaseConfig) -> None:
        self._config = config
        self._engine: AsyncEngine | None = None
        self._sessionmaker: async_sessionmaker[AsyncSession] | None = None

    @property
    def is_initialized(self) -> bool:
        """Check if engine has been initialized."""
        return self._engine is not None

    def get_engine(self) -> AsyncEngine:
        """Get or initialize the AsyncEngine."""
        if self._engine is None:
            url = self._config.get_connection_url(async_driver=True)
            logger.info(
                "initializing_database_engine",
                host=self._config.host,
                port=self._config.port,
                database=self._config.database,
                pool_size=self._config.pool_size,
            )
            self._engine = create_async_engine(
                url,
                pool_size=self._config.pool_size,
                pool_pre_ping=True,
                echo=False,
            )
            self._sessionmaker = async_sessionmaker(
                bind=self._engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=False,
            )
        return self._engine

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Provide an asynchronous transactional database session scope."""
        if self._sessionmaker is None:
            self.get_engine()
        assert self._sessionmaker is not None

        async with self._sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def health_check(self) -> bool:
        """Perform a liveness check against the database."""
        try:
            engine = self.get_engine()
            async with engine.connect() as conn:
                result = await conn.execute(text("SELECT 1"))
                row = result.scalar()
                return bool(row == 1)
        except Exception as exc:
            logger.warning("database_health_check_failed", error=str(exc))
            return False

    async def close(self) -> None:
        """Dispose the AsyncEngine connection pool."""
        if self._engine is not None:
            logger.info("closing_database_engine")
            await self._engine.dispose()
            self._engine = None
            self._sessionmaker = None
