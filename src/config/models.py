"""Canonical configuration models with strict typing and secret masking."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class DatabaseConfig(BaseModel):
    """PostgreSQL and TimescaleDB storage configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    host: str = Field(default="localhost", description="Database host address")
    port: int = Field(default=5432, ge=1, le=65535, description="Database port")
    user: str = Field(default="postgres", min_length=1, description="Database username")
    password: SecretStr = Field(
        default=SecretStr("postgres"), description="Database password (masked)"
    )
    database: str = Field(default="ai_trader", min_length=1, description="Database name")
    pool_size: int = Field(default=10, ge=1, le=100, description="Connection pool size")
    ssl_mode: str = Field(default="prefer", description="PostgreSQL SSL mode")

    def get_connection_url(self, async_driver: bool = True) -> str:
        """Construct database connection URL with unmasked credentials."""
        driver = "postgresql+asyncpg" if async_driver else "postgresql"
        pwd = self.password.get_secret_value()
        return f"{driver}://{self.user}:{pwd}@{self.host}:{self.port}/{self.database}"


class RiskConfig(BaseModel):
    """Deterministic hard risk limits defined per RTLD §14 and BRD BR-1/BR-4."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_daily_loss_pct: float = Field(
        default=0.02,
        ge=0.001,
        le=0.10,
        description="Maximum daily loss percentage before kill-switch triggers (e.g. 0.02 = 2%)",
    )
    max_drawdown_pct: float = Field(
        default=0.05,
        ge=0.005,
        le=0.20,
        description="Maximum peak-to-trough drawdown percentage allowed",
    )
    max_position_size_pct: float = Field(
        default=0.05,
        ge=0.005,
        le=0.20,
        description="Maximum capital allocation to a single position",
    )
    max_exposure_pct: float = Field(
        default=0.50,
        ge=0.05,
        le=1.00,
        description="Maximum aggregated portfolio exposure across all active positions",
    )
    max_consecutive_losses: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Consecutive losing trades triggering temporary cooling-off breaker",
    )
    initial_capital_inr: float = Field(
        default=10000.0,
        ge=1000.0,
        description="Initial live trading capital in INR (₹10,000 baseline per BRD BR-2)",
    )


class BrokerConfig(BaseModel):
    """Broker API configuration supporting paper and live trading."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    broker_name: str = Field(default="zerodha", description="Broker identifier")
    api_key: SecretStr = Field(default=SecretStr("mock_key"), description="Broker API key (masked)")
    api_secret: SecretStr = Field(
        default=SecretStr("mock_secret"), description="Broker API secret (masked)"
    )
    paper_trading: bool = Field(
        default=True, description="Flag indicating simulated paper execution vs live execution"
    )
    reconnection_window_s: int = Field(
        default=30,
        ge=5,
        le=300,
        description="Reconnection deadline in seconds upon broker disconnection (RTLD-15)",
    )


class AppConfig(BaseModel):
    """Master application configuration encapsulating all architectural subsystems."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    environment: Literal["research", "paper", "live", "test"] = Field(
        default="test", description="Target execution environment"
    )
    version: str = Field(default="0.1.0", description="Application release version")
    log_level: str = Field(default="INFO", description="Log verbosity level")
    db: DatabaseConfig = Field(default_factory=DatabaseConfig, description="Database settings")
    risk: RiskConfig = Field(default_factory=RiskConfig, description="Risk boundaries")
    broker: BrokerConfig = Field(default_factory=BrokerConfig, description="Broker settings")
